"""把资源条用托盘左键隐藏（模拟），打印点击前后的可见性。"""
import ctypes, time
from ctypes import wintypes

u32 = ctypes.windll.user32
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

hwnd = u32.FindWindowW("SysMonChipWnd", None)
if not hwnd:
    print("CHIP_NOT_FOUND")
    raise SystemExit(1)
before = bool(u32.IsWindowVisible(hwnd))
u32.PostMessageW(hwnd, 0x8000 + 1, 0, 0x0202)
time.sleep(0.3)
after = bool(u32.IsWindowVisible(hwnd))
print(f"visible before={before} after={after}")
raise SystemExit(0 if (before and not after) else 2)
