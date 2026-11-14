"""调试：启动 SysMonChip，打印窗口状态，并用 PrintWindow 抓它自己的画面。

用法：python debug_win.py [out_prefix]
"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32
try:
    u.SetProcessDpiAwarenessContext(-4)
except Exception:
    pass

from PIL import Image, ImageGrab  # noqa: E402

EXE = r"D:\DSH\sysmon-chip\发布\SysMonChip.exe"
CLASS = "SysMonChipWnd"


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def print_window(hwnd, out_png):
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = u.GetWindowDC(hwnd)
    mem = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
    gdi.SelectObject(mem, bmp)
    ok = u.PrintWindow(hwnd, mem, 1)  # PW_CLIENTONLY
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(out_png)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    u.ReleaseDC(hwnd, hdc)
    return ok, (w, h)


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else r"D:\DSH\sysmon-chip\screenshots\dbg"
    subprocess.run(["taskkill", "/F", "/IM", "SysMonChip.exe"], capture_output=True)
    time.sleep(0.3)
    p = subprocess.Popen([EXE], close_fds=True, creationflags=0x00000008)
    time.sleep(1.3)
    hwnd = u.FindWindowW(CLASS, None)
    print("alive:", p.poll() is None, "hwnd:", hex(hwnd) if hwnd else None)
    if not hwnd:
        return 1
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    print("rect:", (r.left, r.top, r.right, r.bottom), "visible:", bool(u.IsWindowVisible(hwnd)))
    print("exstyle:", hex(u.GetWindowLongPtrW(hwnd, -20) & 0xFFFFFFFF))
    above = u.GetWindow(hwnd, 3)  # GW_HWNDPREV
    print("window above:", hex(above) if above else None)
    if above:
        b = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(above, b, 256)
        t = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(above, t, 256)
        print("  above class:", b.value, "title:", t.value[:60])
    ok, size = print_window(hwnd, prefix + "-printwindow.png")
    print("printwindow:", ok, size)
    im = ImageGrab.grab(all_screens=True)
    im.save(prefix + "-desktop.png")
    print("desktop:", im.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
