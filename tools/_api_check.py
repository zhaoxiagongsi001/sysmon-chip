import ctypes

u = ctypes.windll.user32
k = ctypes.windll.kernel32
u.FindWindowW.restype = ctypes.c_void_p
u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
k.GetModuleHandleW.restype = ctypes.c_void_p
k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
k.GetProcAddress.restype = ctypes.c_void_p
k.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
u.GetWindowLongW.restype = ctypes.c_long
u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]

h = k.GetModuleHandleW("user32.dll")
ansi = k.GetProcAddress(h, b"SetWindowCompositionAttribute")
utf16_as_ansi = k.GetProcAddress(h, "SetWindowCompositionAttribute".encode("utf-16-le")[:1] + b"\0")
print("GetProcAddress ansi name        =", ansi)
print("GetProcAddress utf16-first-byte =", utf16_as_ansi)

w = u.FindWindowW("SysMonChipWnd", None)
print("chip hwnd =", w)
if w:
    ex = u.GetWindowLongW(w, -20) & 0xFFFFFFFF
    st = u.GetWindowLongW(w, -16) & 0xFFFFFFFF
    print("exstyle = 0x%08X  layered = %s  toolwindow = %s  noactivate = %s  topmost = %s" % (
        ex, bool(ex & 0x80000), bool(ex & 0x80), bool(ex & 0x8000000), bool(ex & 0x8)))
    print("style   = 0x%08X  popup = %s  visible = %s" % (st, bool(st & 0x80000000), bool(st & 0x10000000)))
    r = ctypes.wintypes.RECT() if hasattr(ctypes, "wintypes") else None
    import ctypes.wintypes as wt
    rc = wt.RECT()
    u.GetWindowRect(w, ctypes.byref(rc))
    print("rect    = (%d,%d)-(%d,%d) size %dx%d" % (rc.left, rc.top, rc.right, rc.bottom, rc.right - rc.left, rc.bottom - rc.top))
