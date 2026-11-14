"""探针2：逐个验证无边框置顶窗口的真模糊路线，每个变体单独截图。"""
import ctypes, ctypes.wintypes as wt, time

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32
dwm = ctypes.windll.dwmapi
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u.DefWindowProcW.restype = ctypes.c_ssize_t


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


bar = {"on": False}


@WNDPROC
def proc(h, m, w, l):
    if m == 0x0014:  # WM_ERASEBKGND
        return 1
    if m == 0x000F and bar["on"]:  # WM_PAINT: 画 1px 品红边框，确认窗口存在
        ps = ctypes.create_string_buffer(72)
        hdc = u.BeginPaint(h, ps)
        br = gdi.CreateSolidBrush(0x00FF00FF)
        gdi.FrameRect(hdc, ctypes.byref(wt.RECT(0, 0, 800, 200)), br)
        gdi.DeleteObject(br)
        u.EndPaint(h, ps)
        return 0
    return u.DefWindowProcW(h, m, w, l)


class AccentPolicy(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                ("gradient", ctypes.c_uint), ("anim", ctypes.c_int)]


class WinCompAttr(ctypes.Structure):
    _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


u.SetWindowCompositionAttribute.argtypes = [wt.HWND, ctypes.POINTER(WinCompAttr)]


def make_window(cls="ProbeBlur2"):
    WS_POPUP, WS_VISIBLE = 0x80000000, 0x10000000
    ex = 0x8 | 0x80 | 0x08000000
    hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEX()
    wc.cbSize = ctypes.sizeof(WNDCLASSEX)
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.lpszClassName = cls
    u.RegisterClassExW(ctypes.byref(wc))
    return u.CreateWindowExW(ex, cls, None, WS_POPUP | WS_VISIBLE, 250, 1870, 800, 200,
                             None, None, hinst, None)


def acrylic(hwnd, tint=0xCCF3F3F3):
    pol = AccentPolicy(4, 2, tint, 0)
    data = WinCompAttr(19, ctypes.cast(ctypes.byref(pol), ctypes.c_void_p), ctypes.sizeof(AccentPolicy))
    return u.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))


def backdrop(hwnd, kind):
    v = ctypes.c_int(kind)
    return dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(v), 4)


class MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


def extend_frame(hwnd):
    m = MARGINS(-1, -1, -1, -1)
    return dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))


def shot(tag):
    from PIL import ImageGrab
    time.sleep(1.0)
    ImageGrab.grab().crop((200, 1840, 1150, 2100)).save(
        rf"D:\DSH\sysmon-chip\screenshots\probe2-{tag}.png")
    print("shot", tag)


variants = []
h = make_window()
shot("00-plain")
print("backdrop3:", backdrop(h, 3))
shot("01-backdrop3")
print("extendframe:", extend_frame(h))
shot("02-backdrop3-frame")
print("acrylic:", acrylic(h))
shot("03-backdrop3-frame-acrylic")
u.DestroyWindow(h)
