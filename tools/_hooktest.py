"""低完整性进程里装 WinEvent 钩子，验证能不能收到 explorer 的重排/前台事件。"""
import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32

WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
)
u.SetWinEventHook.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
]
u.SetWinEventHook.restype = wintypes.HANDLE

counts = {}
t0 = time.perf_counter()


def cb(hook, event, hwnd, idobj, idchild, thread, t):
    n = counts.get(event, 0) + 1
    counts[event] = n
    cls = ctypes.create_unicode_buffer(96)
    if hwnd:
        u.GetClassNameW(hwnd, cls, 96)
    if n <= 40:
        print(f"{(time.perf_counter()-t0)*1000:7.1f}ms event=0x{event:04x} cls={cls.value!r}", flush=True)


proc = WINEVENTPROC(cb)
for ev in (0x8004, 0x0003):  # OBJECT_REORDER, SYSTEM_FOREGROUND
    h = u.SetWinEventHook(ev, ev, None, proc, 0, 0, 0x0002)
    print(f"hook 0x{ev:04x} -> {int(h) if h else 0}", flush=True)

if not any(True for _ in ()):
    pass

MSG = wintypes.MSG
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
end = time.perf_counter() + dur
while time.perf_counter() < end:
    m = MSG()
    while u.PeekMessageW(ctypes.byref(m), None, 0, 0, 1):
        pass
    time.sleep(0.01)

print("counts:", {hex(k): v for k, v in counts.items()}, flush=True)
