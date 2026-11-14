"""A5：功能验收。

覆盖：
 1. 窗口属性（WS_POPUP / TOOLWINDOW / TOPMOST / NOACTIVATE，无任务栏按钮）
 2. 单实例（第二次启动应快速退出 code 0，不产生第二个窗口）
 3. --quit 收尾（退出码 0、窗口消失、无残留进程）；空跑 --quit 也应 code 0
 4. 配置持久化：
    a) 配置文件 -> 启动读取（mode/theme），重启仍生效
    b) 运行期左键拖动 -> 应用自动保存 mode=free + 坐标 + theme，重启后位置/主题仍生效
 5. free 模式指定坐标精确落位
 6. 托盘图标：IconStreams 注册表搜索 + 任务栏托盘区截图
 7. 全屏自动隐藏（自建覆盖全屏窗口 + 强制前台；hide_fs=1 隐藏 / hide_fs=0 保持）
 8. TaskbarCreated 重挂消息（模拟 explorer 重启广播，验证处理路径不崩、位置保持）
 9. 开机自启 HKCU Run：仅实测沙箱是否允许写（决定能否验证）

产出：data/a5-functional.json + screenshots/verify-tray-*.png
用法：python a5_functional.py
"""
import ctypes
import json
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

u = c.u32
k = c.k32

# ---- 补充原型 ----
u.GetForegroundWindow.restype = c.wintypes.HWND
u.SetForegroundWindow.argtypes = [c.wintypes.HWND]
u.SetForegroundWindow.restype = c.wintypes.BOOL
u.BringWindowToTop.argtypes = [c.wintypes.HWND]
u.BringWindowToTop.restype = c.wintypes.BOOL
u.SwitchToThisWindow.argtypes = [c.wintypes.HWND, c.wintypes.BOOL]
u.AttachThreadInput.argtypes = [c.wintypes.DWORD, c.wintypes.DWORD, c.wintypes.BOOL]
u.AttachThreadInput.restype = c.wintypes.BOOL
k.GetCurrentThreadId.restype = c.wintypes.DWORD
u.GetAncestor.argtypes = [c.wintypes.HWND, c.wintypes.UINT]
u.GetAncestor.restype = c.wintypes.HWND
u.SetWindowPos.argtypes = [c.wintypes.HWND, c.wintypes.HWND, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_int, c.wintypes.UINT]
u.SetWindowPos.restype = c.wintypes.BOOL
u.ShowWindow.argtypes = [c.wintypes.HWND, ctypes.c_int]
u.ShowWindow.restype = c.wintypes.BOOL

LP = lambda x, y: ((y & 0xFFFF) << 16) | (x & 0xFFFF)  # noqa: E731


def rec(name, status, detail):
    return {"test": name, "status": status, "detail": detail}


def dominant_bg(png_path):
    im = Image.open(png_path).convert("RGB")
    a = np.array(im)[10:-10, 10:-10].reshape(-1, 3)
    vals, counts = np.unique(a, axis=0, return_counts=True)
    return list(map(int, vals[counts.argmax()]))


def stop_and_check(p=None):
    code = c.stop(wait_exit=p)
    time.sleep(0.2)
    return {"quit_exit": code, "window": c.find_widget() is not None,
            "pids": c.list_pids()}


# ---------------------------------------------------------------- 托盘
def tray_registry_probe():
    import winreg
    out = {"iconstreams_found": None, "error": None}
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\TrayNotify")
        for name in ("IconStreams", "PastIconsStream"):
            try:
                val, typ = winreg.QueryValueEx(key, name)
            except OSError:
                continue
            needle = "SysMonChip.exe".encode("utf-16-le")
            out[name] = {"bytes": len(val), "found": needle in val}
        winreg.CloseKey(key)
        out["iconstreams_found"] = out.get("IconStreams", {}).get("found")
    except OSError as e:
        out["error"] = f"{getattr(e, 'winerror', None)}: {e.strerror}"
    return out


def tray_screenshots(tag):
    bar = c.taskbar_rect_physical()
    shots = {}
    if not bar:
        return {"error": "no taskbar"}
    full = os.path.join(c.SHOTS, f"verify-tray-taskbar-{tag}.png")
    c.grab_crop(bar, pad=0, path=full)
    shots["taskbar"] = os.path.basename(full)
    # 右侧托盘区（任务栏右端 1000 px）
    right = (max(bar[0], bar[2] - 1000), bar[1], bar[2], bar[3])
    area = os.path.join(c.SHOTS, f"verify-tray-area-{tag}.png")
    c.grab_crop(right, pad=0, path=area)
    shots["tray_right_1000px"] = os.path.basename(area)
    # 放大 2x 便于人眼核对
    im = Image.open(area)
    im.resize((im.width * 2, im.height * 2), Image.NEAREST).save(
        os.path.join(c.SHOTS, f"verify-tray-area-{tag}-2x.png"))
    shots["tray_right_1000px_2x"] = f"verify-tray-area-{tag}-2x.png"
    return shots


# ---------------------------------------------------------------- 全屏隐藏
def make_fullscreen():
    import tkinter as tk
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("300x200+0+0")
    root.configure(bg="black")
    root.update()
    child = root.winfo_id()
    top = u.GetAncestor(child, 2) or child  # GA_ROOT
    u.SetWindowPos(top, c.wintypes.HWND(-1), 0, 0, 3456, 2160, 0x0040 | 0x0004)
    u.ShowWindow(top, 5)  # SW_SHOW
    root.update()
    fg0 = u.GetForegroundWindow()
    fg_tid = u.GetWindowThreadProcessId(fg0, None)
    cur_tid = k.GetCurrentThreadId()
    u.AttachThreadInput(cur_tid, fg_tid, True)
    u.SetForegroundWindow(top)
    u.BringWindowToTop(top)
    u.AttachThreadInput(cur_tid, fg_tid, False)
    root.update()
    fg = u.GetForegroundWindow()
    if fg != top:
        u.SwitchToThisWindow(top, True)
        root.update()
        fg = u.GetForegroundWindow()
    return root, int(top), bool(fg == top)


def wait_widget_visible(expect, timeout=3.0):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        h = c.find_widget()
        last = bool(h and u.IsWindowVisible(h))
        if last == expect:
            return last, round(time.time() - t0, 2)
        time.sleep(0.1)
    return last, None


def fullscreen_hide_test(hide_fs):
    res = {"hide_fs": hide_fs}
    c.write_config(mode="desktop", theme="light", hide_fs=hide_fs)
    c.stop()
    time.sleep(0.3)
    p = c.launch()
    before = c.widget_info()
    root = hwnd = None
    try:
        root, hwnd, fg_ok = make_fullscreen()
        res["fullscreen_hwnd"] = hwnd
        res["foreground_ok"] = fg_ok
        if not fg_ok:
            res["status"] = "unverified"
            res["reason"] = "沙箱内无法把测试窗口置前（SetForegroundWindow/SwitchToThisWindow 均失败）"
            return res
        vis, took = wait_widget_visible(expect=(hide_fs == 0), timeout=3.5)
        res["widget_visible_in_fullscreen"] = vis
        res["reaction_s"] = took
        res["status"] = "pass" if (vis == (hide_fs == 0)) else "fail"
    except Exception as e:
        res["status"] = "error"
        res["reason"] = f"{type(e).__name__}: {e}"
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        time.sleep(0.3)
        try:
            vis2, took2 = wait_widget_visible(expect=True, timeout=3.5)
            res["visible_after_close"] = vis2
            res["recover_s"] = took2
        except Exception:
            pass
        res["quit"] = stop_and_check(p)
    return res


# ---------------------------------------------------------------- 主流程
def main():
    c.ensure_dirs()
    c.stop()
    time.sleep(0.4)
    R = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

    # 1. 窗口属性
    c.write_config(mode="desktop", theme="light")
    c.stop()
    time.sleep(0.3)
    p = c.launch()
    info = c.widget_info()
    R["window"] = {"info": info,
                   "style_popup": bool(info["style"] & 0x80000000),
                   "ex_toolwindow": bool(info["exstyle"] & 0x00000080),
                   "ex_topmost": bool(info["exstyle"] & 0x00000008),
                   "ex_noactivate": bool(info["exstyle"] & 0x08000000),
                   "rect": info["rect"]}
    tray_reg = tray_registry_probe()
    tray_shots = tray_screenshots("running")
    R["tray"] = {"registry": tray_reg, "shots": tray_shots}

    # 2. 单实例
    hwnd_before = c.find_widget()
    p2 = subprocess.Popen([c.EXE], env=dict(os.environ, APPDATA=c.APPDATA_TEST),
                          close_fds=True, creationflags=0x00000008)
    t0 = time.perf_counter()
    try:
        code2 = p2.wait(timeout=8)
        dt = round(time.perf_counter() - t0, 3)
        R["single_instance"] = {"second_exit_code": code2, "second_exit_s": dt,
                                "pids_after": c.list_pids(),
                                "window_same": c.find_widget() == hwnd_before,
                                "status": "pass" if code2 == 0 and len(c.list_pids()) == 1
                                and c.find_widget() == hwnd_before else "fail"}
    except subprocess.TimeoutExpired:
        R["single_instance"] = {"status": "fail", "reason": "second instance did not exit"}
        p2.kill()

    # 3. --quit（在有实例时）
    q = subprocess.run([c.EXE, "--quit"], capture_output=True, timeout=10)
    p.wait(timeout=8)
    time.sleep(0.3)
    R["quit"] = {"quit_exit_code": q.returncode, "app_exit_code": p.returncode,
                 "window_after": c.find_widget() is not None, "pids_after": c.list_pids(),
                 "status": "pass" if q.returncode == 0 and not c.list_pids()
                 and c.find_widget() is None else "fail"}
    # 空跑 --quit
    q2 = subprocess.run([c.EXE, "--quit"], capture_output=True, timeout=10)
    R["quit_no_instance"] = {"exit_code": q2.returncode,
                             "status": "pass" if q2.returncode == 0 else "fail"}

    # 4a. 配置文件读取 + 重启仍生效
    c.write_config(mode="desktop", theme="dark")
    p = c.launch()
    time.sleep(1.3)
    shot1 = os.path.join(c.SHOTS, "verify-persist-dark-1.png")
    c.grab_crop(c.window_rect_physical(c.find_widget()), pad=0, path=shot1)
    d1 = c.run_dump()
    stop_and_check(p)
    time.sleep(0.3)
    p = c.launch()
    time.sleep(1.2)
    shot2 = os.path.join(c.SHOTS, "verify-persist-dark-2.png")
    c.grab_crop(c.window_rect_physical(c.find_widget()), pad=0, path=shot2)
    d2 = c.run_dump()
    stop_and_check(p)
    R["persist_config_load"] = {
        "dump1": {k2: d1["map"].get(k2) for k2 in ("mode", "theme")},
        "dump2": {k2: d2["map"].get(k2) for k2 in ("mode", "theme")},
        "bg1": dominant_bg(shot1), "bg2": dominant_bg(shot2),
        "status": "pass" if d1["map"].get("mode") == "Desktop"
        and d2["map"].get("mode") == "Desktop"
        and d1["map"].get("theme") == "Dark" and d2["map"].get("theme") == "Dark" else "fail",
    }

    # 4b. 运行期拖动 -> 自动保存 mode=free/坐标，重启后仍生效
    c.write_config(mode="desktop", theme="dark")
    c.stop()
    time.sleep(0.3)
    p = c.launch()
    time.sleep(0.8)
    info = c.widget_info()
    rect = info["rect"]
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    u.SetCursorPos(cx, cy)
    time.sleep(0.1)
    hwnd = info["hwnd"]
    u.PostMessageW(hwnd, c.WM_LBUTTONDOWN, 1, LP(cx - rect[0], cy - rect[1]))
    time.sleep(0.15)
    u.PostMessageW(hwnd, c.WM_MOUSEMOVE, 1, LP(cx - rect[0], cy - rect[1]))
    time.sleep(0.15)
    u.PostMessageW(hwnd, c.WM_LBUTTONUP, 0, LP(cx - rect[0], cy - rect[1]))
    time.sleep(0.5)
    cfg_after_drag = c.read_config_dict()
    stop_and_check(p)
    time.sleep(0.3)
    p = c.launch()
    time.sleep(1.2)
    info2 = c.widget_info()
    shot3 = os.path.join(c.SHOTS, "verify-persist-drag-after-restart.png")
    c.grab_crop(info2["rect"], pad=0, path=shot3)
    d3 = c.run_dump()
    stop_and_check(p)
    cfg = c.read_config_dict()
    expect_xy = None
    try:
        expect_xy = (int(cfg.get("x", -1)), int(cfg.get("y", -1)))
    except ValueError:
        pass
    R["persist_drag_save"] = {
        "rect_before_drag": rect,
        "config_after_drag": cfg_after_drag,
        "rect_after_restart": info2["rect"],
        "expect_xy_from_config": expect_xy,
        "dump": {k2: d3["map"].get(k2) for k2 in ("mode", "theme")},
        "bg_after_restart": dominant_bg(shot3),
        "status": "pass" if cfg.get("mode") == "free" and expect_xy == (info2["rect"][0], info2["rect"][1])
        and d3["map"].get("mode") == "Free" and d3["map"].get("theme") == "Dark" else "fail",
    }

    # 5. free 模式不同坐标精确落位
    c.write_config(mode="free", x=1777, y=999, theme="light")
    c.stop()
    time.sleep(0.3)
    p = c.launch()
    time.sleep(1.0)
    free_rect = c.widget_info()["rect"]
    R["free_mode"] = {"config_xy": [1777, 999], "rect": free_rect,
                      "status": "pass" if free_rect[:2] == (1777, 999) else "fail"}
    stop_and_check(p)

    # 6. TaskbarCreated 模拟（taskbar 模式）
    c.write_config(mode="taskbar", theme="light")
    c.stop()
    time.sleep(0.3)
    p = c.launch()
    time.sleep(0.8)
    before = c.widget_info()
    msg = u.RegisterWindowMessageW("TaskbarCreated")
    u.PostMessageW(before["hwnd"], msg, 0, 0)
    time.sleep(1.4)
    after = c.widget_info()
    R["taskbar_created"] = {
        "msg": msg, "alive": c.proc_alive(p.pid),
        "rect_before": before["rect"], "rect_after": after["rect"] if after else None,
        "status": "partial" if c.proc_alive(p.pid) and after
        and after["rect"] == before["rect"] else "fail",
        "note": "模拟 explorer 广播；真 explorer 重启未做（会打断老板桌面）",
    }
    stop_and_check(p)

    # 7. 全屏隐藏
    R["fullscreen_hide_fs1"] = fullscreen_hide_test(1)
    R["fullscreen_hide_fs0"] = fullscreen_hide_test(0)

    # 8. HKCU Run 写入能力实测（决定开机自启能否验证）
    import winreg
    run_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    probe = "SysMonChipVerifierProbe"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_path, 0, winreg.KEY_SET_VALUE) as kk:
            winreg.SetValueEx(kk, probe, 0, winreg.REG_SZ, '"D:\\nonexistent.exe" --probe')
        wrote = True
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_path, 0, winreg.KEY_ALL_ACCESS) as kk:
                winreg.DeleteValue(kk, probe)
        except OSError:
            pass
        R["autostart"] = {"can_write_hkcu_run": wrote,
                          "status": "unverified",
                          "reason": "沙箱可写 HKCU Run，但触发『开机自启』菜单项需要右键菜单点击，"
                                    "本轮未做 GUI 菜单自动化；故自启功能未实测"}
    except OSError as e:
        R["autostart"] = {"can_write_hkcu_run": False,
                          "error": f"{getattr(e, 'winerror', None)}: {e.strerror}",
                          "status": "unverified",
                          "reason": "低完整性沙箱拒绝写 HKCU\\...\\Run，自启写注册表路径无法在本环境验证"}
    # 万一之前写成功并残留
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_path, 0, winreg.KEY_SET_VALUE) as kk:
            winreg.DeleteValue(kk, probe)
    except OSError:
        pass

    R["final_residual_pids"] = c.list_pids()
    c.save_json(os.path.join(c.DATA, "a5-functional.json"), R)
    print(json.dumps(R, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
