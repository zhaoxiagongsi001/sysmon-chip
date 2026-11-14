"""截取资源条右端附近屏幕区域并放大，检查圆角是否真空出来（露出下面的桌面/任务栏）。"""
import ctypes, sys
from ctypes import wintypes
from PIL import ImageGrab

u32 = ctypes.WinDLL("user32")
u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

h = u32.FindWindowW("SysMonChipWnd", None)
if not h:
    print("CHIP_NOT_FOUND")
    raise SystemExit(1)
r = wintypes.RECT()
u32.GetWindowRect(h, ctypes.byref(r))
pad = 40
box = (max(0, r.right - 80), r.top - pad, r.right + pad, r.bottom + pad)
img = ImageGrab.grab(bbox=box, all_screens=True)
img = img.resize((img.width * 3, img.height * 3), 0)  # NEAREST
out = sys.argv[1] if len(sys.argv) > 1 else "D:/DSH/sysmon-chip/tools/_corner.png"
img.save(out)
print(f"rect=({r.left},{r.top})-({r.right},{r.bottom}) crop={box} -> {out} {img.size}")

# 采样圆角外接框内四点的颜色：用来判断是露出桌面还是仍是面板底色
px = img.load()
w, hh = img.size
print("corner px (scaled):", [px[x, y] for x, y in ((0, 0), (w - 1, 0), (0, hh - 1), (w - 1, hh - 1))])
