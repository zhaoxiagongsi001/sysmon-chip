"""探针：采样 SysMonChip 窗口的可见性与 z 序，定位「点任务栏后消失 0.5s」的机制。

判定口径：
  - cover  : 窗口仍可见（style 有 WS_VISIBLE），但在枚举 z 序里被 Shell_TrayWnd 压住 → 被盖住
  - hidden : style 的 WS_VISIBLE 掉了 → 程序自己 ShowWindow(SW_HIDE)
"""
import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32

try:
    u.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2：坐标=物理像素
except Exception:
    pass

u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.GetWindowLongPtrW.restype = ctypes.c_longlong
u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetForegroundWindow.restype = wintypes.HWND
u.WindowFromPoint.restype = wintypes.HWND
u.WindowFromPoint.argtypes = [wintypes.POINT]
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.GetAncestor.restype = wintypes.HWND
u.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_VISIBLE = 0x1000_0000
WS_EX_TOPMOST = 0x0000_0008

ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    if h:
        u.GetClassNameW(h, b, 256)
    return b.value


def zorder():
    """返回 {hwnd: 索引}；索引越小越靠前（顶层 z 序）。"""
    order = []

    def cb(h, lp):
        order.append(h)
        return True

    u.EnumWindows(ENUMPROC(cb), 0)
    return {h: i for i, h in enumerate(order)}


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    chip = u.FindWindowW("SysMonChipWnd", None)
    tray = u.FindWindowW("Shell_TrayWnd", None)
    if not chip:
        print("CHIP_NOT_FOUND")
        return 1
    rc = wintypes.RECT()
    u.GetWindowRect(chip, ctypes.byref(rc))
    rt = wintypes.RECT()
    u.GetWindowRect(tray, ctypes.byref(rt))
    print(f"chip rect=({rc.left},{rc.top})-({rc.right},{rc.bottom})", flush=True)
    print(f"tray rect=({rt.left},{rt.top})-({rt.right},{rt.bottom})", flush=True)
    print(f"chip ex={u.GetWindowLongPtrW(chip, GWL_EXSTYLE):#x} "
          f"topmost={bool(u.GetWindowLongPtrW(chip, GWL_EXSTYLE) & WS_EX_TOPMOST)}", flush=True)
    print(f"tray ex={u.GetWindowLongPtrW(tray, GWL_EXSTYLE):#x} "
          f"topmost={bool(u.GetWindowLongPtrW(tray, GWL_EXSTYLE) & WS_EX_TOPMOST)}", flush=True)

    Z0 = zorder()
    print(f"baseline: chip_z={Z0.get(chip)} tray_z={Z0.get(tray)} "
          f"fg={cls(u.GetForegroundWindow())}", flush=True)

    t0 = time.perf_counter()
    prev = None
    while time.perf_counter() - t0 < dur:
        t = (time.perf_counter() - t0) * 1000
        vis = bool(u.GetWindowLongPtrW(chip, GWL_STYLE) & WS_VISIBLE)
        z = zorder()
        cz, tz = z.get(chip, -1), z.get(tray, -1)
        cover = vis and cz > tz
        cx, cy = (rc.left + rc.right) // 2, (rc.top + rc.bottom) // 2
        top = u.GetAncestor(u.WindowFromPoint(wintypes.POINT(cx, cy)), 2)  # GA_ROOT
        state = "ok" if vis and not cover else ("cover" if vis else "hidden")
        fg = cls(u.GetForegroundWindow())
        rec = (state, fg, cls(top))
        if rec != prev:
            print(f"{t:7.1f}ms {state:6s} chip_z={cz:3d} tray_z={tz:3d} "
                  f"fg={fg!r} at_center={cls(top)!r}", flush=True)
            prev = rec
        time.sleep(0.008)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
