import ctypes
from ctypes import wintypes
g32 = ctypes.WinDLL("gdi32"); u32 = ctypes.WinDLL("user32")
u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
hdc = g32.CreateCompatibleDC(None)
fl = g32.CreateFontW(-31,0,0,0,400,0,0,0,1,0,0,4,0,"Segoe UI")
fv = g32.CreateFontW(-34,0,0,0,600,0,0,0,1,0,0,4,0,"Segoe UI")
def wid(f,s):
    g32.SelectObject(hdc,f); sz=wintypes.SIZE()
    g32.GetTextExtentPoint32W(hdc,s,len(s),ctypes.byref(sz)); return sz.cx
D=2.25
for s in ["CPU","MEM","DISK","100%","58%","100.0%","MB/s","1.9 MB/s","792 KB/s","↑"]:
    print(f"{s!r:12} label={wid(fl,s):3d} ({wid(fl,s)/D:.1f})  value={wid(fv,s):3d} ({wid(fv,s)/D:.1f})")
