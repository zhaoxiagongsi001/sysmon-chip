"""截屏并裁剪 SysMonChip 区域。

本机是 225% 缩放，Python 进程若不是 per-monitor DPI aware，GetWindowRect 会返回
逻辑坐标而 ImageGrab 拿到的是物理像素，所以这里显式换算 scale。

用法：
  python capture.py full  <out.png>
  python capture.py chip  <out.png> [--zoom 2]
"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32

# 尽量设为 per-monitor v2（失败也不影响，后面会自己算 scale）
try:
    u.SetProcessDpiAwarenessContext(-4)
except Exception:
    pass

from PIL import ImageGrab  # noqa: E402

EXE = r"D:\DSH\sysmon-chip\发布\SysMonChip.exe"


def scale_factor() -> float:
    """物理像素 / 逻辑像素。"""
    hdc = u.GetDC(0)
    phys_w = gdi.GetDeviceCaps(hdc, 118)  # DESKTOPHORZRES
    u.ReleaseDC(0, hdc)
    logical_w = u.GetSystemMetrics(0)
    if logical_w <= 0:
        return 1.0
    return max(1.0, phys_w / logical_w)


def find_widget():
    return u.FindWindowW("SysMonChipWnd", None)


def ensure_running(exe: str) -> None:
    if find_widget():
        return
    subprocess.Popen([exe], close_fds=True, creationflags=0x00000008)
    time.sleep(1.2)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    mode, out = sys.argv[1], sys.argv[2]
    zoom = 1
    if "--zoom" in sys.argv:
        zoom = int(sys.argv[sys.argv.index("--zoom") + 1])

    im = ImageGrab.grab(all_screens=True)
    if mode == "full":
        im.save(out)
        print(f"saved {out} {im.size}")
        return 0

    h = find_widget()
    if not h:
        ensure_running(EXE)
        h = find_widget()
    if not h:
        print("widget window not found")
        return 1
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    s = scale_factor()
    pad = 24
    box = (
        max(0, int(r.left * s) - pad),
        max(0, int(r.top * s) - pad),
        min(im.width, int(r.right * s) + pad),
        min(im.height, int(r.bottom * s) + pad),
    )
    crop = im.crop(box)
    if zoom != 1:
        crop = crop.resize((crop.width * zoom, crop.height * zoom), 1)
    crop.save(out)
    print(f"saved {out} {crop.size} logical_rect={(r.left, r.top, r.right, r.bottom)} scale={s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
