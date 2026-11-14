import ctypes, time

u = ctypes.windll.user32
u.FindWindowW.restype = ctypes.c_void_p
u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]

N = 20000
for _ in range(200):
    u.FindWindowW("Shell_TrayWnd", None)
t0 = time.perf_counter()
for _ in range(N):
    u.FindWindowW("Shell_TrayWnd", None)
dt = time.perf_counter() - t0
print("FindWindowW avg = %.1f us  (%d calls in %.3f s)" % (dt / N * 1e6, N, dt))

u.GetForegroundWindow.restype = ctypes.c_void_p
t0 = time.perf_counter()
for _ in range(N):
    u.GetForegroundWindow()
print("GetForegroundWindow avg = %.1f us" % ((time.perf_counter() - t0) / N * 1e6))

gwl = ctypes.windll.user32.GetWindowLongPtrW
gwl.restype = ctypes.c_void_p
gwl.argtypes = [ctypes.c_void_p, ctypes.c_int]
h = u.FindWindowW("SysMonChipWnd", None)
t0 = time.perf_counter()
for _ in range(N):
    gwl(h, -20)
print("GetWindowLongPtrW avg = %.1f us" % ((time.perf_counter() - t0) / N * 1e6))
