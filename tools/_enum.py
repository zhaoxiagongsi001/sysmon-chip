import ctypes
from ctypes import wintypes
u=ctypes.windll.user32
u.EnumWindows.argtypes=[ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM),wintypes.LPARAM]
pid=int(20072)
found=[]
def cb(h,lp):
    p=wintypes.DWORD()
    u.GetWindowThreadProcessId(h,ctypes.byref(p))
    if p.value==pid:
        b=ctypes.create_unicode_buffer(256); u.GetClassNameW(h,b,256)
        found.append((h,b.value,bool(u.IsWindowVisible(h))))
    return True
u.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)(cb),0)
print("windows:",found)
