"""v0.9 圆角区域取证（DPI 感知）：打印窗口区域形状的 ASCII 图，并截图存 PNG。"""
import ctypes
from ctypes import wintypes

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)

u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2

u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRgn.restype = ctypes.c_int
u32.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN]
u32.GetWindowDC.restype = wintypes.HDC
u32.GetWindowDC.argtypes = [wintypes.HWND]
u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
u32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]

g32.CreateRectRgn.restype = wintypes.HRGN
g32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
g32.PtInRegion.restype = wintypes.BOOL
g32.PtInRegion.argtypes = [wintypes.HRGN, ctypes.c_int, ctypes.c_int]
g32.GetRgnBox.argtypes = [wintypes.HRGN, ctypes.POINTER(wintypes.RECT)]
g32.CreateCompatibleDC.restype = wintypes.HDC
g32.CreateCompatibleDC.argtypes = [wintypes.HDC]
g32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
g32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
g32.SelectObject.restype = wintypes.HGDIOBJ
g32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
g32.DeleteDC.argtypes = [wintypes.HDC]
g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
g32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def main(png=None):
    h = u32.FindWindowW("SysMonChipWnd", None)
    if not h:
        print("CHIP_NOT_FOUND")
        return 1
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    w, ht = r.right - r.left, r.bottom - r.top

    hrgn = g32.CreateRectRgn(0, 0, 1, 1)
    kind = u32.GetWindowRgn(h, hrgn)
    box = wintypes.RECT()
    g32.GetRgnBox(hrgn, ctypes.byref(box))
    print(f"rect=({r.left},{r.top})-({r.right},{r.bottom}) w={w} h={ht} | rgnType={kind} box=({box.left},{box.top})-({box.right},{box.bottom})")

    def inside(x, y):
        return bool(g32.PtInRegion(hrgn, x, y))

    span_y = min(ht, 22)
    span_x = 26
    print("左上角:")
    for y in range(span_y):
        print("  " + "".join("#" if inside(x, y) else "." for x in range(span_x)))
    print("右上角:")
    for y in range(span_y):
        print("  " + "".join("#" if inside(w - span_x + x, y) else "." for x in range(span_x)))

    if png:
        save_png(h, w, ht, png)
    return 0


def save_png(h, w, ht, path):
    from PIL import Image
    src = u32.GetWindowDC(h)
    hdc = g32.CreateCompatibleDC(src)
    hbmp = g32.CreateCompatibleBitmap(src, w, ht)
    g32.SelectObject(hdc, hbmp)
    u32.PrintWindow(h, hdc, 3)
    bi = BMIH(biSize=ctypes.sizeof(BMIH), biWidth=w, biHeight=-ht, biPlanes=1,
              biBitCount=32, biCompression=0)
    buf = ctypes.create_string_buffer(w * ht * 4)
    rows = g32.GetDIBits(hdc, hbmp, 0, ht, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGBA", (w, ht), buf, "raw", "BGRA", 0, 1).convert("RGB")
    img.save(path)
    print("saved", path, img.size, "rows", rows)
    g32.DeleteObject(hbmp)
    g32.DeleteDC(hdc)
    u32.ReleaseDC(h, src)


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
