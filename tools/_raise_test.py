"""直接对 chip 调 SetWindowPos，验证「插到任务栏上方」到底要传哪个句柄。"""
import ctypes
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindow.restype = wintypes.HWND
u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.SetWindowPos.restype = wintypes.BOOL

ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]

GW_HWNDPREV, GWL_EXSTYLE, WS_EX_TOPMOST = 3, -20, 0x8
SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x2, 0x1, 0x10


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def zmap():
    order = []
    u.EnumWindows(ENUMPROC(lambda h, lp: order.append(h) or True), 0)
    return {h: i for i, h in enumerate(order)}


def show(tag, chip, tray, zm):
    print(f"{tag}: chip_z={zm.get(chip)} tray_z={zm.get(tray)}")


chip = u.FindWindowW("SysMonChipWnd", None)
tray = u.FindWindowW("Shell_TrayWnd", None)
show("before", chip, tray, zmap())

front = u.GetWindow(tray, GW_HWNDPREV)
ex = u.GetWindowLongPtrW(front, GWL_EXSTYLE) & 0xFFFFFFFF
print(f"tray.PREV=0x{front:x} {cls(front)!r} ex=0x{ex:08x} topmost={bool(ex & WS_EX_TOPMOST)}")

ok = u.SetWindowPos(chip, front, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
show(f"after insert-after=tray.PREV ok={ok}", chip, tray, zmap())
time.sleep(0.3)
show("after 300ms", chip, tray, zmap())

ok = u.SetWindowPos(chip, wintypes.HWND(-1), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
show(f"after HWND_TOPMOST ok={ok}", chip, tray, zmap())
time.sleep(0.3)
show("after 300ms", chip, tray, zmap())
