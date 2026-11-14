"""外部抢层测试：造一个覆盖资源条的 topmost 测试窗，把它提到最前，
测量资源条多久重新回到它上面（验证 WinEvent 钩子的纠正延迟）。"""
import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]

HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOACTIVATE = 0x0010


def zorder():
    order = []
    PINVOKE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        order.append(h)
        return True
    u.EnumWindows(PINVOKE(cb), 0)
    return order


u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
tray = u.FindWindowW("Shell_TrayWnd", None)
chip = u.FindWindowW("SysMonChipWnd", None)
if not chip:
    print("chip not found", flush=True)
    sys.exit(1)

# 造测试窗口：盖住资源条那一块
hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
hbr = ctypes.windll.gdi32.CreateSolidBrush(0x0000FF)
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
proc = WNDPROC(lambda h, m, w, l: ctypes.windll.user32.DefWindowProcW(h, m, w, l))

class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

wc = WNDCLASS()
wc.lpfnWndProc = proc
wc.hInstance = hinst
wc.hbrBackground = hbr
wc.lpszClassName = "AggressorTestWnd"
u.RegisterClassW(ctypes.byref(wc))
agg = u.CreateWindowExW(0x00000008 | 0x00000080, "AggressorTestWnd", "agg", 0x80000000,
                        0, 2052, 400, 108, None, None, hinst, None)
u.ShowWindow(agg, 8)  # SW_SHOWNA
time.sleep(0.05)

# 让测试窗升到带顶
u.SetWindowPos(agg, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOACTIVATE)
t_raise = time.perf_counter()
z = zorder()
print(f"raise: agg_z={z.index(agg)} chip_z={z.index(chip)}", flush=True)

recovered = None
t0 = time.perf_counter()
while time.perf_counter() - t0 < 5.0:
    z = zorder()
    try:
        if z.index(chip) < z.index(agg):
            recovered = (time.perf_counter() - t0) * 1000
            break
    except ValueError:
        pass
    time.sleep(0.002)
print(f"chip back on top after {recovered:.1f}ms" if recovered else "NOT recovered in 5s", flush=True)
u.DestroyWindow(agg)
