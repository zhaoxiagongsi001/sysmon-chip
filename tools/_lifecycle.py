"""长时间观察 SysMonChipLite 生命周期：窗口出现/消失、进程退出码、退出耗时。"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

exe = sys.argv[1] if len(sys.argv) > 1 else r"D:\DSH\sysmon-chip\发布\SysMonChipLite.exe"
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

p = subprocess.Popen([exe], close_fds=True, creationflags=0x00000008)
t0 = time.perf_counter()
cur = None
while time.perf_counter() - t0 < dur:
    t = (time.perf_counter() - t0) * 1000
    h = u.FindWindowW("SysMonChipWnd", None)
    if h != cur:
        print(f"{t:8.1f}ms window={h or 0}", flush=True)
        cur = h
    rc = p.poll()
    if rc is not None:
        print(f"{t:8.1f}ms EXIT code={rc} (0x{rc & 0xFFFFFFFF:08X}) after {t/1000:.2f}s", flush=True)
        break
    time.sleep(0.1)
else:
    print(f"alive {dur}s pid={p.pid}", flush=True)
    p.terminate()
