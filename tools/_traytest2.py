"""v0.8 托盘左键显隐验证：点一次应保持隐藏，再点一次应保持显示。

用法: python _traytest2.py     # 退出码 0 = 通过，1 = 失败
"""
import ctypes, time
from ctypes import wintypes

u32 = ctypes.windll.user32

u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.PostMessageW.restype = wintypes.BOOL
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

WM_APP = 0x8000
TRAY_CB = WM_APP + 1
WM_LBUTTONUP = 0x0202
SETTLE_S = 3.0
TICK_S = 0.02


def main():
    hwnd = u32.FindWindowW("SysMonChipWnd", None)
    if not hwnd:
        print("CHIP_NOT_FOUND")
        return 1
    print(f"hwnd={hwnd} visible_now={bool(u32.IsWindowVisible(hwnd))}")

    failed = 0
    for phase, label in ((0, "click#1 -> expect HIDE"), (1, "click#2 -> expect SHOW")):
        if not u32.PostMessageW(hwnd, TRAY_CB, 0, WM_LBUTTONUP):
            print(f"\n{label}\n  PostMessageW failed, err={ctypes.get_last_error()}")
            return 1
        t0 = time.perf_counter()
        samples = []
        last = None
        while time.perf_counter() - t0 < SETTLE_S:
            v = bool(u32.IsWindowVisible(hwnd))
            if v != last:
                samples.append((round((time.perf_counter() - t0) * 1000, 1), v))
                last = v
            time.sleep(TICK_S)
        print(f"\n{label}")
        print(f"  transitions: {samples}")
        # 旧状态 1 个样本 + 一次跳变 = 2 个样本；跳变后再没变化就说明状态稳住了
        desired = phase == 1  # phase 0 期望隐藏(False)，phase 1 期望显示(True)
        ok = len(samples) == 2 and samples[-1][1] == desired
        print(f"  settled and stayed ({SETTLE_S:.0f}s): {ok}")
        if not ok:
            failed += 1

    print("\nRESULT:", "PASS" if failed == 0 else "FAIL")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
