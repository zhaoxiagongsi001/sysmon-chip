"""v0.8 托盘左键显隐验证：点一次应保持隐藏，再点一次应保持显示。

用法: python _traytest2.py
"""
import ctypes, time
from ctypes import wintypes

u32 = ctypes.windll.user32

u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

WM_APP = 0x8000
TRAY_CB = WM_APP + 1
WM_LBUTTONUP = 0x0202


def main():
    hwnd = u32.FindWindowW("SysMonChipWnd", None)
    if not hwnd:
        print("CHIP_NOT_FOUND")
        return 1
    print(f"hwnd={hwnd} visible_now={bool(u32.IsWindowVisible(hwnd))}")

    for phase, label in ((0, "click#1 -> expect HIDE"), (1, "click#2 -> expect SHOW")):
        u32.PostMessageW(hwnd, TRAY_CB, 0, WM_LBUTTONUP)
        t0 = time.perf_counter()
        samples = []
        last = None
        while time.perf_counter() - t0 < 3.0:
            v = bool(u32.IsWindowVisible(hwnd))
            if v != last:
                samples.append((round((time.perf_counter() - t0) * 1000, 1), v))
                last = v
            time.sleep(0.02)
        print(f"\n{label}")
        print(f"  transitions: {samples}")
        # 旧状态 1 个样本 + 一次跳变 = 2 个样本；跳变后再没变化就说明状态稳住了
        desired = phase == 1  # phase 0 期望隐藏(False)，phase 1 期望显示(True)
        ok = len(samples) == 2 and samples[-1][1] is desired
        print(f"  settled and stayed (3s): {ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
