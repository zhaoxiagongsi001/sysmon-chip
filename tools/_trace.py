"""合并时间线：2ms 采样 覆盖状态 + 窗口标题（Z/G/R），点击前后各截一段。"""
import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindow.restype = wintypes.HWND
u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GW_HWNDPREV = 3

dur = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
t0 = time.perf_counter()
prev = None
while time.perf_counter() - t0 < dur:
    chip = u.FindWindowW("SysMonChipWnd", None)
    tray = u.FindWindowW("Shell_TrayWnd", None)
    if not chip:
        print("no window", flush=True)
        break
    dist = -1
    h = chip
    for i in range(64):
        h = u.GetWindow(h, GW_HWNDPREV)
        if not h:
            break
        if h == tray:
            dist = i + 1
            break
    b = ctypes.create_unicode_buffer(32)
    u.GetWindowTextW(chip, b, 32)
    state = (dist > 0, b.value)
    if state != prev:
        t = (time.perf_counter() - t0) * 1000
        print(f"{t:7.1f}ms covered={state[0]} dist={dist:>3} title={b.value!r}", flush=True)
        prev = state
    time.sleep(0.002)
print("done", flush=True)
