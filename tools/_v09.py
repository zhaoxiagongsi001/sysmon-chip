"""v0.9 验证：开关指标时窗口宽度自适应、贴屏侧不动、外露竖边圆角（区域裁剪）。

用 PostMessage(WM_COMMAND, id) 直接触发菜单命令，避免真点。
"""
import ctypes, time
from ctypes import wintypes

u32 = ctypes.windll.user32
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.WindowFromPoint.restype = wintypes.HWND
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE]
u32.GetWindowDC.restype = wintypes.HDC
u32.GetWindowDC.argtypes = [wintypes.HWND]

WM_COMMAND = 0x0111


def rect(h):
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return r


def hit(x, y, h):
    got = u32.WindowFromPoint(wintypes.POINT(x, y))
    return "chip" if got == h else f"other({got})"


def describe(tag, h):
    r = rect(h)
    now = u32.WindowFromPoint(wintypes.POINT(r.left + 2, r.top + 2))
    return (
        f"{tag}: rect=({r.left},{r.top})-({r.right},{r.bottom}) "
        f"w={r.right - r.left} h={r.bottom - r.top} "
        f"point(2,2)->{'chip' if now == h else 'other'}"
    )


def corner_probe(tag, h):
    r = rect(h)
    ym = (r.top + r.bottom) // 2
    print(f"  {tag}: TR(inner)={hit(r.right - 2, r.top + 2, h)}  "
          f"BR(inner)={hit(r.right - 2, r.bottom - 3, h)}  "
          f"TL(inner)={hit(r.left + 2, r.top + 2, h)}  "
          f"BL(inner)={hit(r.left + 2, r.bottom - 3, h)}  "
          f"mid-right={hit(r.right - 2, ym, h)}  mid-left={hit(r.left + 2, ym, h)}")


def cmd(h, c):
    u32.PostMessageW(h, WM_COMMAND, c, 0)
    time.sleep(0.35)


def main():
    h = u32.FindWindowW("SysMonChipWnd", None)
    if not h:
        print("CHIP_NOT_FOUND")
        return 1

    print(describe("all-on", h))
    corner_probe("all-on", h)

    cmd(h, 4)  # 关网速
    print(describe("net off", h))
    corner_probe("net off", h)

    cmd(h, 3)  # 再关磁盘
    print(describe("net+disk off", h))

    cmd(h, 12)  # 任务栏左端（左对齐）
    print(describe("mode=taskbar-left", h))

    cmd(h, 11)  # 桌面右下角（右对齐）
    print(describe("mode=desktop-right", h))
    corner_probe("mode=desktop-right", h)

    cmd(h, 3)  # 恢复
    cmd(h, 4)
    cmd(h, 12)
    print(describe("restored all-on", h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
