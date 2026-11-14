import ctypes, time
from ctypes import wintypes
u32 = ctypes.WinDLL("user32")
u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
h = u32.FindWindowW("SysMonChipWnd", None)
assert h, "CHIP_NOT_FOUND"
r = wintypes.RECT(); u32.GetWindowRect(h, ctypes.byref(r))
print("before:", r.right - r.left)
u32.PostMessageW(h, 0x0111, 4, 0)   # 4 = 网速
time.sleep(0.4)
u32.GetWindowRect(h, ctypes.byref(r))
print("after toggle net:", r.right - r.left)
