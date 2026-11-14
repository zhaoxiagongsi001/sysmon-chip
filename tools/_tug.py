"""外部"抢层器"：每 8ms 检查一次，被任务栏盖住就立即 HWND_TOPMOST 提回来。
用来判断「我们提层到底能不能赢过 explorer 的动画期」。
"""
import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.SetWindowPos.restype = wintypes.BOOL

ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
HWND_TOPMOST = wintypes.HWND(-1)
FLAGS = 0x2 | 0x1 | 0x10  # NOMOVE|NOSIZE|NOACTIVATE

dur = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
t0 = time.perf_counter()
covers = 0
raises = 0
cur_run = 0
max_run = 0
run_start = 0.0
last_report = 0.0

while time.perf_counter() - t0 < dur:
    order = []
    u.EnumWindows(ENUMPROC(lambda h, lp: order.append(h) or True), 0)
    zm = {h: i for i, h in enumerate(order)}
    chip = u.FindWindowW("SysMonChipWnd", None)
    tray = u.FindWindowW("Shell_TrayWnd", None)
    t = (time.perf_counter() - t0) * 1000
    covered = zm.get(chip, 0) > zm.get(tray, 0)
    if covered:
        covers += 1
        if cur_run == 0:
            run_start = t
        cur_run += 1
        if cur_run > max_run:
            max_run = cur_run
        if u.SetWindowPos(chip, HWND_TOPMOST, 0, 0, 0, 0, FLAGS):
            raises += 1
    else:
        if cur_run:
            print(f"{t:7.1f}ms cover-run ended, {cur_run} samples, ~{t-run_start:.0f}ms", flush=True)
        cur_run = 0
    if t - last_report > 2000:
        last_report = t
        print(f"{t:7.1f}ms covers={covers} raises={raises}", flush=True)
    time.sleep(0.008)

print(f"done covers={covers} raises={raises} max_run={max_run}", flush=True)
