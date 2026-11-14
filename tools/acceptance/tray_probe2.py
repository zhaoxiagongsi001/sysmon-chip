"""托盘图标专项探测 2：用「自建对照图标」校准 Shell_NotifyIcon / Shell_NotifyIconGetRect 语义。

结论判定：
- 自身 NIM_ADD 失败 -> 本沙箱不允许低完整性进程加托盘图标 -> 托盘项无法验证（环境限制）。
- 自身 NIM_ADD 成功且 GetRect OK，而 SysMonChip 的 GetRect 失败 -> 说明 app 托盘注册有问题。
- 两者都 NIM_ADD 成功但都进 overflow（GetRect E_FAIL）-> overflow 属 Windows 默认行为，App 托盘注册有效。

产出：data/tray-probe2.json + screenshots/verify-tray-probe*.png
"""
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

u = c.u32
k = c.k32

u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HANDLE,
                              wintypes.HINSTANCE, ctypes.c_void_p]
u.CreateWindowExW.restype = wintypes.HWND
u.DestroyWindow.argtypes = [wintypes.HWND]
u.DestroyWindow.restype = wintypes.BOOL
u.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
u.LoadIconW.restype = wintypes.HICON
u.GetLastError = k.GetLastError

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
                ("hBalloonIcon", wintypes.HICON)]


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("guidItem", GUID)]


sh = ctypes.WinDLL("shell32", use_last_error=True)
sh.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(NOTIFYICONIDENTIFIER),
                                       ctypes.POINTER(wintypes.RECT)]
sh.Shell_NotifyIconGetRect.restype = ctypes.c_long
sh.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
sh.Shell_NotifyIconW.restype = wintypes.BOOL


def get_rect(hwnd, uid):
    nid = NOTIFYICONIDENTIFIER()
    nid.cbSize = ctypes.sizeof(NOTIFYICONIDENTIFIER)
    nid.hWnd = hwnd
    nid.uID = uid
    r = wintypes.RECT()
    ctypes.set_last_error(0)
    hr = sh.Shell_NotifyIconGetRect(ctypes.byref(nid), ctypes.byref(r))
    return {"hr": hex(hr & 0xFFFFFFFF), "ok": hr == 0,
            "file_not_found": (hr & 0xFFFFFFFF) == 0x80070002,
            "rect": [r.left, r.top, r.right, r.bottom]}


def screenshot(tag, bar=None):
    bar = bar or c.taskbar_rect_physical()
    p = os.path.join(c.SHOTS, f"verify-tray-{tag}.png")
    c.grab_crop(bar, pad=0, path=p)
    im = c.grab_crop(bar, pad=0)
    im2 = im.resize((im.width // 2, im.height // 2), 1).resize((im.width, im.height), 1)
    # 托盘右端 900px 放大 2x
    r = (max(bar[0], bar[2] - 900), bar[1], bar[2], bar[3])
    c.grab_crop(r, pad=0, path=os.path.join(c.SHOTS, f"verify-tray-{tag}-icons.png"))
    return {"taskbar": os.path.basename(p)}


def make_hidden_window():
    hinst = k.GetModuleHandleW(None)
    cls = "VerifierProbeWnd"
    # 用 STATIC 类最简单（已注册）
    h = u.CreateWindowExW(0, "STATIC", "verifier", 0x80000000,  # WS_POPUP
                          0, 0, 10, 10, None, None, hinst, None)
    return h


def main():
    c.ensure_dirs()
    c.write_config(mode="taskbar", theme="light")
    c.stop()
    time.sleep(0.3)
    p = c.launch()
    time.sleep(1.7)
    app = c.widget_info()
    out = {"app_hwnd": app["hwnd"], "app_pid": p.pid}

    # 对照图标
    probe = make_hidden_window()
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = probe
    nid.uID = 7
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = 0x0400 + 300
    nid.hIcon = u.LoadIconW(None, wintypes.LPCWSTR(32512))  # IDI_APPLICATION
    nid.szTip = "VERIFIER-TRAY-PROBE"
    ctypes.set_last_error(0)
    ok = bool(sh.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
    out["probe_add"] = {"ok": ok, "last_error": ctypes.get_last_error(),
                        "icon": int(nid.hIcon) if nid.hIcon else None}
    time.sleep(0.5)

    out["probe_icon_rect"] = get_rect(probe, 7)
    out["app_icon_rect"] = get_rect(app["hwnd"], 1)
    out["bogus_hwnd_rect"] = get_rect(c.u32.FindWindowW("Progman", None), 99)
    out["screenshots"] = screenshot("probe-running")

    if ok:
        sh.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
    u.DestroyWindow(probe)
    time.sleep(0.3)
    out["quit"] = {"code": c.stop(wait_exit=p), "pids": c.list_pids()}
    c.save_json(os.path.join(c.DATA, "tray-probe2.json"), out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
