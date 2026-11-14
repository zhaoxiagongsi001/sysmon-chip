"""左右两端圆角对照图：任务栏左端（外露右边）/ 桌面右下角（外露左边）。"""
import ctypes, time, sys
from ctypes import wintypes
from PIL import ImageGrab

u32 = ctypes.WinDLL("user32")
u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

h = u32.FindWindowW("SysMonChipWnd", None)
if not h:
    print("CHIP_NOT_FOUND")
    raise SystemExit(1)


def rect():
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return r


def cmd(c):
    u32.PostMessageW(h, 0x0111, c, 0)
    time.sleep(0.4)


def grab(tag, pad_l=30, pad_r=60, zoom=2):
    r = rect()
    box = (max(0, r.left - pad_l), r.top - 26, r.right + pad_r, r.bottom + 26)
    img = ImageGrab.grab(bbox=box, all_screens=True)
    img = img.resize((img.width * zoom, img.height * zoom), 0)
    path = f"D:/DSH/sysmon-chip/tools/_mode_{tag}.png"
    img.save(path)
    print(f"{tag}: rect=({r.left},{r.top})-({r.right},{r.bottom}) w={r.right - r.left} -> {path}")


cmd(12)   # 任务栏左端
grab("taskbar_left", pad_l=10, pad_r=70)
cmd(11)   # 桌面右下角
grab("desktop_right", pad_l=70, pad_r=10)
cmd(12)   # 回到任务栏左端
print("restored")
