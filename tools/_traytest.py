import ctypes, time
import ctypes.wintypes as wt

u = ctypes.windll.user32
u.FindWindowW.restype = ctypes.c_void_p
u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t]
u.IsWindowVisible.argtypes = [ctypes.c_void_p]

WM_APP = 0x8000
tray_cb = WM_APP + 1
WM_LBUTTONUP = 0x0202

h = u.FindWindowW("SysMonChipWnd", None)
print("hwnd =", h, "visible =", u.IsWindowVisible(h))

# 模拟托盘图标左键点击（与 on_tray 收到的消息同参）
u.PostMessageW(h, tray_cb, 0, WM_LBUTTONUP)

t0 = time.perf_counter()
prev = None
for _ in range(60):
    v = bool(u.IsWindowVisible(h))
    if v != prev:
        print("  %7.1f ms visible=%s" % ((time.perf_counter() - t0) * 1000, v))
        prev = v
    time.sleep(0.05)
print("final visible =", bool(u.IsWindowVisible(h)))
