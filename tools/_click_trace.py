"""点击任务栏期间的完整时间线：tray 是否 topmost、chip/tray z 序、前台窗口类名。"""
import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
k = ctypes.windll.kernel32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x8

u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0

PINVOKE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def snapshot():
    order = []
    u.EnumWindows(PINVOKE(lambda h, _: (order.append(h), True)[1]), 0)
    return order


def cls(h):
    b = ctypes.create_unicode_buffer(96)
    n = u.GetClassNameW(h, b, 96)
    return b.value if n else "?"


t0 = time.perf_counter()
prev = None
while time.perf_counter() - t0 < dur:
    z = snapshot()
    tray = u.FindWindowW("Shell_TrayWnd", None)
    chip = u.FindWindowW("SysMonChipWnd", None)
    if not chip or not tray:
        print("window missing", flush=True)
        break
    try:
        cz, tz = z.index(chip), z.index(tray)
    except ValueError:
        time.sleep(0.005)
        continue
    ttop = bool(u.GetWindowLongPtrW(tray, GWL_EXSTYLE) & WS_EX_TOPMOST)
    fg = cls(u.GetForegroundWindow())
    st = (cz < tz, ttop, fg)
    if st != prev:
        print(f"{(time.perf_counter()-t0)*1000:7.1f}ms chip_z={cz:>3} tray_z={tz:>3} "
              f"chipOnTop={cz < tz} trayTopmost={ttop} fg={fg}", flush=True)
        prev = st
    time.sleep(0.005)
print("done", flush=True)
