"""点击后高频采样：从 chip 沿 GW_HWNDPREV 走 64 层，记录任务栏在第几层。"""
import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindow.restype = wintypes.HWND
u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GW_HWNDPREV = 3

dur = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
t0 = time.perf_counter()
last = None
while time.perf_counter() - t0 < dur:
    chip = u.FindWindowW("SysMonChipWnd", None)
    tray = u.FindWindowW("Shell_TrayWnd", None)
    h = chip
    dist = -1
    names = []
    for i in range(64):
        h = u.GetWindow(h, GW_HWNDPREV)
        if not h:
            break
        if h == tray:
            dist = i + 1
            break
        if i < 14:
            b = ctypes.create_unicode_buffer(96)
            u.GetClassNameW(h, b, 96)
            names.append(b.value)
    t = (time.perf_counter() - t0) * 1000
    if dist != last:
        print(f"{t:7.1f}ms tray_dist={dist} (<=12? {0 < dist <= 12}) first14={names[:6]}", flush=True)
        last = dist
    time.sleep(0.005)
print("done", flush=True)
