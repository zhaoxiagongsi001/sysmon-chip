"""探针：验证本机 Win11 对无边框置顶窗口是否支持真模糊（GPU 亚克力）。
两种路线各建一个窗口，截图对比模糊效果，用完销毁。"""
import ctypes, ctypes.wintypes as wt, time, sys

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32
dwm = ctypes.windll.dwmapi

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u.DefWindowProcW.restype = ctypes.c_ssize_t


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


def make_class(name):
    @WNDPROC
    def proc(h, m, w, l):
        if m == 0x0014:  # WM_ERASEBKGND -> 不填背景
            return 1
        return u.DefWindowProcW(h, m, w, l)

    wc = WNDCLASSEX()
    wc.cbSize = ctypes.sizeof(WNDCLASSEX)
    wc.lpfnWndProc = proc
    wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc.lpszClassName = name
    u.RegisterClassExW(ctypes.byref(wc))
    return proc


class AccentPolicy(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                ("gradient", ctypes.c_uint), ("anim", ctypes.c_int)]


class WinCompAttr(ctypes.Structure):
    _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


u.SetWindowCompositionAttribute.argtypes = [wt.HWND, ctypes.POINTER(WinCompAttr)]


def acrylic(hwnd, tint=0xCCF3F3F3):
    pol = AccentPolicy(4, 2, tint, 0)
    data = WinCompAttr(19, ctypes.cast(ctypes.byref(pol), ctypes.c_void_p), ctypes.sizeof(AccentPolicy))
    return u.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))


def make_window(name, x, y, w, h):
    WS_POPUP = 0x80000000
    WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
    return u.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        name, None, WS_POPUP | 0x10000000,
        x, y, w, h, None, None, ctypes.windll.kernel32.GetModuleHandleW(None), None)


def backdrop(hwnd, kind=3):
    # DWMWA_SYSTEMBACKDROP_TYPE = 38; 2=mainwindow(mica) 3=transient(acrylic) 4=tabbed
    v = ctypes.c_int(kind)
    return dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(v), 4)


proc_a = make_class("ProbeAcrylic")
proc_b = make_class("ProbeBackdrop")

# 覆盖在任务栏左端上方（那里有天气部件，容易看出模糊）
x, y, w, h = 0, 1980, 700, 170
a = make_window("ProbeAcrylic", x, y, w, h)
b = make_window("ProbeBackdrop", x, y + 0, w, h)

print("set composition acrylic:", acrylic(a))
print("set dwm backdrop:", backdrop(b, 3))
time.sleep(1.2)

from PIL import ImageGrab
im = ImageGrab.grab()
im.crop((0, 1960, 800, 2160)).save(r"D:\DSH\sysmon-chip\screenshots\probe-blur.png")
print("saved probe")

u.DestroyWindow(a)
u.DestroyWindow(b)
