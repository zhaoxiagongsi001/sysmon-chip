"""量左右内边距：抓窗口区域，按列统计「深色/彩色」像素，找出文字最左/最右列。"""
import ctypes, sys
from ctypes import wintypes
from PIL import Image, ImageGrab

u32 = ctypes.WinDLL("user32")
g32 = ctypes.WinDLL("gdi32")
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
img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).convert("RGB")
w, hh = img.size
px = img.load()

cols = []
for x in range(w):
    dark = 0
    for y in range(hh):
        R, G, B = px[x, y]
        mx, mn = max(R, G, B), min(R, G, B)
        if mx < 170 or (mx - mn) > 60:      # 深色字 or 彩色字
            dark += 1
    cols.append(dark)

first = next((x for x, c in enumerate(cols) if c >= 2), None)
last = next((x for x in range(w - 1, -1, -1) if cols[x] >= 2), None)
print(f"window {w}x{hh}  text first={first} last={last}")
print(f"gap_left={first}px  gap_right={w - 1 - last}px  diff={abs(first - (w - 1 - last))}px")
if first is not None and last is not None:
    print(f"logical: left={first/2.25:.1f} right={(w-1-last)/2.25:.1f}")
out = sys.argv[1] if len(sys.argv) > 1 else "D:/DSH/sysmon-chip/tools/_pad.png"
img.resize((w * 2, hh * 2), 0).save(out)
print("saved", out)
