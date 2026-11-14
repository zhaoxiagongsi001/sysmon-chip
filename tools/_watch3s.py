"""采样 3 秒窗口可见性，打印跳变时间线。"""
import ctypes, sys, time
from ctypes import wintypes

u32 = ctypes.windll.user32
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.IsWindowVisible.argtypes = [wintypes.HWND]

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
hwnd = u32.FindWindowW("SysMonChipWnd", None)
if not hwnd:
    print("CHIP_NOT_FOUND")
    raise SystemExit(1)

t0 = time.perf_counter()
last = None
samples = []
while time.perf_counter() - t0 < secs:
    v = bool(u32.IsWindowVisible(hwnd))
    if v != last:
        samples.append((round((time.perf_counter() - t0) * 1000, 1), v))
        last = v
    time.sleep(0.02)
print("transitions:", samples)
print("final:", samples[-1][1] if samples else None)
