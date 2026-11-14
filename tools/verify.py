"""SysMonChip 真机自检：布局自适应 / 左右留白 / 圆角区域 / 托盘显隐。

用法：
    python tools/verify.py            # 跑除 shot 外的全部检查
    python tools/verify.py layout     # 只跑某一项：layout | padding | region | tray | shot
    python tools/verify.py shot out.png

依赖运行中的 SysMonChipLite（窗口类名 SysMonChipWnd）。退出码 0 = 全过，1 = 有失败。
菜单命令通过 PostMessage(WM_COMMAND, id) 触发，等价于用户点右键菜单：
    1 CPU / 2 MEM / 3 DISK / 4 网速；11 桌面右下角 / 12 任务栏左端。
"""
import ctypes
import sys
import time
from ctypes import wintypes

from PIL import Image, ImageGrab

u32 = ctypes.WinDLL("user32")
g32 = ctypes.WinDLL("gdi32")

# 高 DPI 进程：否则 GetWindowRect 拿到的是被系统缩放过的逻辑坐标
u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE]
u32.GetWindowRgn.restype = ctypes.c_int
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.PostMessageW.restype = wintypes.BOOL
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.GetDpiForWindow.argtypes = [wintypes.HWND]
u32.GetDpiForWindow.restype = wintypes.UINT
u32.GetSystemMetrics.argtypes = [ctypes.c_int]
u32.GetSystemMetrics.restype = ctypes.c_int
g32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
g32.CreateRectRgn.restype = wintypes.HANDLE
g32.GetRgnBox.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.RECT)]
g32.DeleteObject.argtypes = [wintypes.HANDLE]

WM_COMMAND = 0x0111
WM_APP = 0x8000
TRAY_CB = WM_APP + 1   # 托盘回调（WM_APP+1）
WM_SHOW_CHIP = WM_APP + 4   # 应用内「复位手动隐藏并显示」
WM_LBUTTONUP = 0x0202
SM_CXSCREEN = 0

CMD_NET, CMD_DISK = 4, 3
CMD_DESKTOP, CMD_TASKBAR = 11, 12

TICK = 0.005


def window():
    h = u32.FindWindowW("SysMonChipWnd", None)
    return h or None


def rect(h):
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return r


def box(h):
    r = rect(h)
    return r.left, r.top, r.right, r.bottom


def size(h):
    l, t, r_, b = box(h)
    return r_ - l, b - t


def scale_of(h):
    dpi = u32.GetDpiForWindow(h) or 96
    return dpi / 96.0


def cmd(h, cid, wait=0.35):
    if not u32.PostMessageW(h, WM_COMMAND, cid, 0):
        raise RuntimeError(f"PostMessageW(WM_COMMAND {cid}) failed, err={ctypes.get_last_error()}")
    time.sleep(wait)


def toggle_off(h, cid):
    """按一次菜单项，返回面板是否真的变窄（即该项原本是开的）。"""
    before = size(h)[0]
    cmd(h, cid)
    return size(h)[0] < before


def grab(h):
    l, t, r_, b = box(h)
    return ImageGrab.grab(bbox=(l, t, r_, b), all_screens=True).convert("RGB"), (l, t, r_, b)


# ---------------------------------------------------------------- layout
def check_layout(h):
    """: 关掉指标后面板变窄、贴屏侧不动；两种模式的对齐边固定在屏幕边。"""
    fails = []

    def width():
        return size(h)[0]

    screen_w = u32.GetSystemMetrics(SM_CXSCREEN)
    was_desktop = box(h)[2] == screen_w
    cmd(h, CMD_TASKBAR)
    w_all = width()
    left_all = box(h)[0]
    if not toggle_off(h, CMD_NET):
        fails.append("起始状态里「网速」本来就是关的（配置不是四项全开），本次布局检查未生效")
        # toggle_off 已经把「网速」打开了，撤销这次切换，并把模式还原，
        # 否则后面的检查会拿错误的面板状态当基准
        cmd(h, CMD_NET)
        if was_desktop:
            cmd(h, CMD_DESKTOP)
        return fails
    w_net_off = width()
    cmd(h, CMD_DISK)
    w_both_off = width()
    print(f"  widths: all-on={w_all} net-off={w_net_off} net+disk-off={w_both_off}")
    if not (w_all > w_net_off > w_both_off):
        fails.append("关指标后面板没有逐级变窄")

    if box(h)[0] != left_all:
        fails.append("任务栏左端模式下左缘移动了（应固定）")

    cmd(h, CMD_DESKTOP)
    screen_w = u32.GetSystemMetrics(SM_CXSCREEN)
    r = box(h)
    print(f"  desktop-right rect={r} screen_w={screen_w}")
    if r[2] != screen_w:
        fails.append("桌面右下角模式下右缘没贴住屏幕右缘")

    # 恢复全开
    cmd(h, CMD_DISK)
    cmd(h, CMD_NET)
    cmd(h, CMD_TASKBAR)
    if width() != w_all:
        fails.append(f"恢复后宽度 {width()} != 初始 {w_all}")
    return fails


# ---------------------------------------------------------------- padding
def text_columns(img):
    """按列统计「深色字或彩色字」的像素数，返回 (first, last)；面板空白返回 (None, None)。"""
    w, h = img.size
    px = img.load()
    cols = []
    for x in range(w):
        n = 0
        for y in range(h):
            r, g, b = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx < 170 or (mx - mn) > 60:
                n += 1
        cols.append(n)
    # 抗锯齿噪点：一列至少 2 个像素才算有字
    first = next((x for x, n in enumerate(cols) if n >= 2), None)
    last = next((x for x in range(w - 1, -1, -1) if cols[x] >= 2), None)
    return first, last


def measure_padding(h):
    img, _ = grab(h)
    w, _h = img.size
    first, last = text_columns(img)
    if first is None or last is None:
        return None
    return w, img.size[1], first, w - 1 - last


def check_padding(h):
    """: 左右留白基本对称（v0.9.1 把右侧多余的 24 px 吃了回去）。

    切模式/重排之后立刻抓屏会抓到半帧（右侧凭空多出 10px 空白），
    因此先等一个刷新周期再量；仍不对称就复测，最多三次都不对称才判失败。
    """
    got = None
    for _ in range(3):
        time.sleep(0.35)
        got = measure_padding(h)
        if got:
            _w, _h, gap_l, gap_r = got
            if abs(gap_l - gap_r) <= 2:
                return []
    if not got:
        return ["面板是空白：没有找到任何文字像素"]
    w, _hh, gap_l, gap_r = got
    sc = scale_of(h)
    print(f"  window={w}x{_hh} gap_left={gap_l}px gap_right={gap_r}px "
          f"(logical {gap_l / sc:.1f} / {gap_r / sc:.1f}, diff={abs(gap_l - gap_r)}px)")
    # 允许 2 物理 px 的字形两侧抗锯齿差
    return [] if abs(gap_l - gap_r) <= 2 else [f"左右留白差 {abs(gap_l - gap_r)}px（要求 ≤2px）"]


# ---------------------------------------------------------------- region
def check_region(h):
    """: 外露的那条竖边带圆角——区域类型是 COMPLEXREGION，角落像素露出桌面。"""
    fails = []
    rgn = g32.CreateRectRgn(0, 0, 1, 1)
    kind = u32.GetWindowRgn(h, rgn)
    rb = wintypes.RECT()
    g32.GetRgnBox(rgn, ctypes.byref(rb))
    g32.DeleteObject(rgn)
    print(f"  GetWindowRgn type={kind} box=({rb.left},{rb.top})-({rb.right},{rb.bottom})")
    if kind != 3:  # COMPLEXREGION：圆角 + 方角拼接
        fails.append(f"窗口区域类型是 {kind}，不是 3（COMPLEXREGION）")

    img, (l, t, r_, b) = grab(h)
    w, hh = img.size
    px = img.load()
    # 面板底色 = 出现最多的颜色
    counts = {}
    for x in range(0, w, 3):
        for y in range(0, hh, 3):
            c = px[x, y]
            counts[c] = counts.get(c, 0) + 1
    bg = max(counts, key=counts.get)
    screen_w = u32.GetSystemMetrics(SM_CXSCREEN)
    outward_right = (l + w // 2) < screen_w // 2  # 贴左边 -> 圆角在右边
    ex = w - 2 if outward_right else 1
    mx = w - 2 if outward_right else 1
    corner = px[ex, 1]
    middle = px[mx, hh // 2]
    print(f"  bg={bg} outward={'right' if outward_right else 'left'} "
          f"corner={corner} middle={middle}")
    if corner == bg:
        fails.append("外露竖边的角上还是面板底色（圆角没生效）")
    if middle != bg:
        fails.append("外露竖边的中段不是面板底色（区域被切多了）")
    return fails


# ---------------------------------------------------------------- tray
def check_tray(h):
    """: 托盘左键隐藏后必须稳住（v0.8 修的就是 0.7s 后自动复现）。"""
    fails = []
    if not u32.IsWindowVisible(h):
        # 用户可能用托盘把它关着；WM_SHOW_CHIP 会复位 hidden_by_user 再显示
        u32.PostMessageW(h, WM_SHOW_CHIP, 0, 0)
        time.sleep(0.4)
        if not u32.IsWindowVisible(h):
            return ["面板当前不可见，无法测托盘显隐"]
    for expect_visible, label in ((False, "click#1 -> HIDE"), (True, "click#2 -> SHOW")):
        if not u32.PostMessageW(h, TRAY_CB, 0, WM_LBUTTONUP):
            fails.append(f"{label}: PostMessageW 失败 err={ctypes.get_last_error()}")
            break
        t0 = time.perf_counter()
        samples, last = [], None
        while time.perf_counter() - t0 < 1.5:
            v = bool(u32.IsWindowVisible(h))
            if v != last:
                samples.append((round((time.perf_counter() - t0) * 1000, 1), v))
                last = v
            time.sleep(TICK)
        print(f"  {label} transitions={samples}")
        if len(samples) != 2 or samples[-1][1] != expect_visible:
            fails.append(f"{label}: 期望最终 visible={expect_visible}，实际 {samples}")
    return fails


# ---------------------------------------------------------------- main
CHECKS = {
    "layout": check_layout,
    "padding": check_padding,
    "region": check_region,
    "tray": check_tray,
}


def main(argv):
    h = window()
    if not h:
        print("CHIP_NOT_FOUND：先启动 SysMonChipLite.exe")
        return 1

    if argv and argv[0] == "shot":
        out = argv[1] if len(argv) > 1 else "D:/DSH/sysmon-chip/tools/shot.png"
        img, _ = grab(h)
        img.resize((img.size[0] * 2, img.size[1] * 2), Image.LANCZOS).save(out)
        print(f"saved {out} ({img.size[0]}x{img.size[1]} @2x)")
        return 0

    names = argv if argv else list(CHECKS)
    bad = []
    for name in names:
        fn = CHECKS.get(name)
        if not fn:
            print(f"unknown check: {name}")
            return 2
        print(f"[{name}]")
        try:
            fails = fn(h)
        except RuntimeError as e:
            fails = [str(e)]
        for f in fails:
            print(f"  FAIL: {f}")
        if not fails:
            print("  ok")
        bad.extend(f"{name}: {f}" for f in fails)

    print("\nRESULT:", "PASS" if not bad else f"FAIL ({len(bad)})")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
