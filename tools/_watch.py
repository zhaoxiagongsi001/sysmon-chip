import ctypes, sys, time
from ctypes import wintypes
u = ctypes.windll.user32
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 14.0
t0 = time.perf_counter(); last = None; covlast = None; beat = 0.0
while time.perf_counter() - t0 < dur:
    chip = u.FindWindowW("SysMonChipWnd", None); tray = u.FindWindowW("Shell_TrayWnd", None)
    if not chip: print("no window", flush=True); break
    b = ctypes.create_unicode_buffer(64); u.GetWindowTextW(chip, b, 64)
    order = []; u.EnumWindows(ENUMPROC(lambda h, lp: order.append(h) or True), 0)
    zm = {h: i for i, h in enumerate(order)}
    cov = zm.get(chip, 0) > zm.get(tray, 0)
    t = (time.perf_counter() - t0) * 1000
    if cov != covlast:
        print(f"{t:7.1f}ms {'COVER' if cov else 'ok'} (chip_z={zm.get(chip)} tray_z={zm.get(tray)})", flush=True); covlast = cov
    if b.value != last:
        print(f"{t:7.1f}ms title={b.value!r}", flush=True); last = b.value
    if t - beat > 1000:
        beat = t; print(f"{t:7.1f}ms heartbeat cov={cov} title={b.value!r}", flush=True)
    time.sleep(0.005)
print("done", flush=True)
