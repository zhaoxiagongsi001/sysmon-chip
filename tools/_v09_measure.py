import ctypes
from ctypes import wintypes
g32 = ctypes.WinDLL("gdi32"); u32 = ctypes.WinDLL("user32")
u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
hdc = g32.CreateCompatibleDC(None)
face = "Segoe UI"
def font(h, w):
    return g32.CreateFontW(h,0,0,0,w,0,0,0,1,0,0,4,0,face)
def wid(f, s):
    g32.SelectObject(hdc, f)
    sz = wintypes.SIZE()
    g32.GetTextExtentPoint32W(hdc, s, len(s), ctypes.byref(sz))
    return sz.cx
fl = font(-31, 400); fv = font(-34, 600)
samples = ["0 B/s","9.8 KB/s","246 KB/s","999 KB/s","1.9 MB/s","12.4 MB/s","999.9 MB/s","1023 KB/s"]
print("label row (up):", [(s, wid(fl,s)) for s in samples])
print("value row (down):", [(s, wid(fv,s)) for s in samples])
mx_l = max(wid(fl,s) for s in samples); mx_v = max(wid(fv,s) for s in samples)
print("max label", mx_l, "-> logical", round(mx_l/2.25,1), "| max value", mx_v, "-> logical", round(mx_v/2.25,1))
