"""把 chip / tray 两侧的 GetWindow 链都打出来，确认 GW_HWNDPREV 的方向。"""
import ctypes
from ctypes import wintypes

u = ctypes.windll.user32
u.GetWindow.restype = wintypes.HWND
u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

GW_HWNDNEXT, GW_HWNDPREV = 2, 3


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    t = ctypes.create_unicode_buffer(64)
    u.GetWindowTextW(h, t, 64)
    return f"{b.value!r}/{t.value[:20]!r}"


def walk(h, cmd, name):
    out = []
    cur = u.GetWindow(h, cmd)
    for _ in range(6):
        if not cur:
            out.append("<null>")
            break
        out.append(f"0x{cur:x} {cls(cur)}")
        cur = u.GetWindow(cur, cmd)
    print(f"{name}: " + (" -> ".join(out) if out else "<none>"))


chip = u.FindWindowW("SysMonChipWnd", None)
tray = u.FindWindowW("Shell_TrayWnd", None)
print(f"chip=0x{chip:x} tray=0x{tray:x}")
walk(chip, GW_HWNDPREV, "chip PREV(front?)")
walk(chip, GW_HWNDNEXT, "chip NEXT(back?) ")
walk(tray, GW_HWNDPREV, "tray PREV(front?)")
