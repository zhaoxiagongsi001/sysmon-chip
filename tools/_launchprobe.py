"""起一次 SysMonChipLite，20ms 粒度记录：窗口出现/消失、进程存活、退出码。"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

exe = sys.argv[1] if len(sys.argv) > 1 else r"D:\DSH\sysmon-chip\发布\SysMonChipLite.exe"
args = sys.argv[2:] or []

p = subprocess.Popen([exe] + args, close_fds=True, creationflags=0x00000008)
t0 = time.perf_counter()
seen = 0
while time.perf_counter() - t0 < 4.0:
    t = (time.perf_counter() - t0) * 1000
    h = u.FindWindowW("SysMonChipWnd", None)
    if h and not seen:
        r = wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        print(f"{t:7.1f}ms hwnd={h} rect=({r.left},{r.top})-({r.right},{r.bottom})", flush=True)
        seen = h
    if not h and seen:
        print(f"{t:7.1f}ms window gone", flush=True)
        seen = 0
    if p.poll() is not None:
        print(f"{t:7.1f}ms process exit={p.returncode}", flush=True)
        break
    time.sleep(0.02)
else:
    print(f"still running pid={p.pid} window={seen}", flush=True)
    p.terminate()
