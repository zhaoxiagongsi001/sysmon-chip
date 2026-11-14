"""受控实验：外部把任务栏提到 chip 之上，再单独验证 app 的两条提层路径。
1) 手动 PostMessage(WM_Z_EVENT)  -> 钩子回调那条路
2) 等 1.5s                       -> 1s 定时器那条路
"""
import ctypes
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.SetWindowPos.restype = wintypes.BOOL
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.PostMessageW.restype = wintypes.BOOL

ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
HWND_TOPMOST = wintypes.HWND(-1)
FLAGS = 0x2 | 0x1 | 0x10


def z():
    order = []
    u.EnumWindows(ENUMPROC(lambda h, lp: order.append(h) or True), 0)
    zm = {h: i for i, h in enumerate(order)}
    chip = u.FindWindowW("SysMonChipWnd", None)
    tray = u.FindWindowW("Shell_TrayWnd", None)
    st = "ok" if zm.get(chip, 0) < zm.get(tray, 0) else "COVER"
    return chip, tray, f"chip_z={zm.get(chip)} tray_z={zm.get(tray)} {st}"


chip, tray, s = z()
print("start   ", s, flush=True)
ok = u.SetWindowPos(tray, HWND_TOPMOST, 0, 0, 0, 0, FLAGS)
time.sleep(0.05)
print(f"tray->topmost ok={ok}", z()[2], flush=True)

r = u.PostMessageW(chip, 0x8003, 0, 0)
time.sleep(0.06)
print(f"post WM_Z_EVENT r={r}", z()[2], flush=True)

time.sleep(1.6)
print("after 1.6s  ", z()[2], flush=True)
