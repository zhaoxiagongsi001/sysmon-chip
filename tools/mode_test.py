"""外观/模式验收：三种位置 + 明暗主题截图，验证窗口与任务栏几何关系。

用 exe 自己的 --quit 关掉旧实例（沙箱里 taskkill 会被拒）。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import win32util as w  # noqa: E402

EXE = w.EXE
APPDATA = r"D:\DSH\sysmon-chip\.appdata-test"
OUT = r"D:\DSH\sysmon-chip\screenshots"
CFG_DIR = os.path.join(APPDATA, "SysMonChip")

u = ctypes.windll.user32
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

CASES = [
    ("desktop-light", "mode=desktop\ntheme=light\n"),
    ("desktop-dark", "mode=desktop\ntheme=dark\n"),
    ("taskbar-light", "mode=taskbar\ntheme=light\n"),
    ("taskbar-dark", "mode=taskbar\ntheme=dark\n"),
    ("free-light", "mode=free\nx=300\ny=400\ntheme=light\n"),
]


def stop():
    subprocess.run([EXE, "--quit"], capture_output=True, timeout=10)
    time.sleep(0.7)


def write_cfg(body: str):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(os.path.join(CFG_DIR, "config.ini"), "w", encoding="utf-8") as f:
        f.write(body)


def launch():
    env = dict(os.environ, APPDATA=APPDATA)
    return subprocess.Popen([EXE], env=env, close_fds=True, creationflags=0x00000008)


def wait_fresh_window(pid, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = w.find_widget()
        if h:
            owner = wintypes.DWORD(0)
            u.GetWindowThreadProcessId(h, ctypes.byref(owner))
            if owner.value == pid:
                return h
        time.sleep(0.05)
    return None


def taskbar_rect():
    h = u.FindWindowW("Shell_TrayWnd", None)
    if not h:
        return None
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    s = w.scale_factor()
    return (int(r.left * s), int(r.top * s), int(r.right * s), int(r.bottom * s))


def main():
    os.makedirs(OUT, exist_ok=True)
    stop()
    for name, body in CASES:
        write_cfg(body)
        p = launch()
        h = wait_fresh_window(p.pid)
        time.sleep(1.2)  # 等首帧 + 定位
        if not h:
            print(name, "NO WINDOW, exit", p.poll())
            continue
        rect = w.widget_rect_physical()
        im = w.grab()
        pad = 30
        box = (max(0, rect[0] - pad), max(0, rect[1] - pad),
               min(im.width, rect[2] + pad), min(im.height, rect[3] + pad))
        im.crop(box).save(os.path.join(OUT, f"mode-{name}.png"))
        bg = im.getpixel((rect[0] + 4, rect[1] + 4))
        print(f"{name:14s} rect={rect} bg={bg}")
        if name == "desktop-light":
            second = launch()
            time.sleep(1.2)
            print("single-instance: second exit code =", second.poll())
        stop()
    print("taskbar physical rect:", taskbar_rect())
    print("saved mode-*.png")


if __name__ == "__main__":
    main()
