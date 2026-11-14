"""测消息循环延迟：post WM_Z_EVENT 后，标题变成 Z 要多久（空闲态）。"""
import ctypes
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

chip = u.FindWindowW("SysMonChipWnd", None)
print(f"chip=0x{chip:x}")

for i in range(5):
    b = ctypes.create_unicode_buffer(64)
    u.GetWindowTextW(chip, b, 64)
    before = b.value
    t0 = time.perf_counter()
    u.PostMessageW(chip, 0x8003, 0, 0)
    seen = None
    while time.perf_counter() - t0 < 1.0:
        u.GetWindowTextW(chip, b, 64)
        if b.value != before:
            seen = (time.perf_counter() - t0) * 1000
            break
        time.sleep(0.001)
    print(f"#{i}: before={before!r} -> {b.value!r} latency={seen if seen is None else round(seen,1)}ms", flush=True)
    time.sleep(0.9)
