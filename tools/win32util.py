"""Win32 小工具（给验收脚本用）：正确的 ctypes 原型 + 截屏裁剪。"""
import ctypes
import subprocess
import time
from ctypes import wintypes

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32

try:
    u.SetProcessDpiAwarenessContext(-4)
except Exception:
    pass

u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindowRect.restype = wintypes.BOOL
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.IsWindowVisible.restype = wintypes.BOOL
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u.SetWindowRgn.restype = ctypes.c_int
u.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
u.GetWindowRgn.restype = ctypes.c_int
u.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN]
u.SetWindowPos.restype = wintypes.BOOL
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.GetTopWindow.restype = wintypes.HWND
u.GetTopWindow.argtypes = [wintypes.HWND]
u.GetWindow.restype = wintypes.HWND
u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
u.GetClassNameW.restype = ctypes.c_int
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowTextW.restype = ctypes.c_int
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetSystemMetrics.restype = ctypes.c_int
u.GetSystemMetrics.argtypes = [ctypes.c_int]
u.GetDC.restype = wintypes.HDC
u.GetDC.argtypes = [wintypes.HWND]
u.ReleaseDC.restype = ctypes.c_int
u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
u.FindWindowExW.restype = wintypes.HWND

gdi.GetDeviceCaps.restype = ctypes.c_int
gdi.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
gdi.CreateRectRgn.restype = wintypes.HRGN
gdi.CreateRectRgn.argtypes = [ctypes.c_int] * 4

EXE = r"D:\DSH\sysmon-chip\发布\SysMonChip.exe"
CLASS = "SysMonChipWnd"
HWND_TOPMOST = wintypes.HWND(-1)


def scale_factor() -> float:
    hdc = u.GetDC(None)
    phys = gdi.GetDeviceCaps(hdc, 118)  # DESKTOPHORZRES
    u.ReleaseDC(None, hdc)
    logical = u.GetSystemMetrics(0)
    return max(1.0, phys / logical) if logical else 1.0


def find_widget():
    return u.FindWindowW(CLASS, None)


def ensure_running(wait_s: float = 1.2):
    h = find_widget()
    if h:
        return h
    subprocess.run(["taskkill", "/F", "/IM", "SysMonChip.exe"], capture_output=True)
    time.sleep(0.2)
    subprocess.Popen([EXE], close_fds=True, creationflags=0x00000008)
    time.sleep(wait_s)
    return find_widget()


def widget_rect_physical():
    """返回窗口在屏幕上的物理像素矩形；正确换算 225% 缩放。"""
    h = find_widget()
    if not h:
        return None
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    s = scale_factor()
    # 若调用进程确实是 DPI aware，GetWindowRect 已是物理坐标，scale 会算成 1.0
    return (int(r.left * s), int(r.top * s), int(r.right * s), int(r.bottom * s))


def grab():
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=True)
