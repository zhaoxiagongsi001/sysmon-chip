"""SysMonChip 独立验收公共工具（verifier 自写，不依赖 tools/ 下既有脚本）。

内容：
- 强制进程 per-monitor DPI aware V2，GetWindowRect / 截屏统一用物理像素；
- 窗口发现 / 物理矩形 / 工作区 / 任务栏矩形；
- 进程指标：WS、私有、GDI、USER、句柄、累计 CPU 时间；
- 配置写入、启动 / --quit 收尾、--dump / --trace 读取、截屏。

所有脚本共用，路径固定到 D:\\DSH\\sysmon-chip。
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.join(ROOT, "发布", "SysMonChip.exe")
APPDATA_TEST = os.path.join(ROOT, ".appdata-test")
CFG_DIR = os.path.join(APPDATA_TEST, "SysMonChip")
CFG_PATH = os.path.join(CFG_DIR, "config.ini")
SHOTS = os.path.join(ROOT, "screenshots")
ACC = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ACC, "data")

CLASS = "SysMonChipWnd"
WM_QUIT_APP = 0x8000 + 2
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
adv32 = ctypes.WinDLL("advapi32", use_last_error=True)

# ---------------------------------------------------------------- DPI aware
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
u32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
try:
    DPI_AWARE = bool(u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
except Exception:
    DPI_AWARE = False

# ---------------------------------------------------------------- prototypes
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowW.restype = wintypes.HWND
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRect.restype = wintypes.BOOL
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongPtrW.restype = ctypes.c_longlong
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.GetDC.argtypes = [wintypes.HWND]
u32.GetDC.restype = wintypes.HDC
u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
u32.ReleaseDC.restype = ctypes.c_int
u32.GetSystemMetrics.argtypes = [ctypes.c_int]
u32.GetSystemMetrics.restype = ctypes.c_int
u32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
u32.MonitorFromPoint.restype = wintypes.HANDLE
u32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
u32.GetMonitorInfoW.restype = wintypes.BOOL
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.PostMessageW.restype = wintypes.BOOL
u32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
u32.RegisterWindowMessageW.restype = wintypes.UINT
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.SendMessageW.restype = ctypes.c_longlong
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.SetCursorPos.restype = wintypes.BOOL
u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
u32.GetCursorPos.restype = wintypes.BOOL
u32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
u32.GetGuiResources.restype = wintypes.DWORD

g32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
g32.GetDeviceCaps.restype = ctypes.c_int

shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                   ctypes.POINTER(wintypes.HICON),
                                   ctypes.POINTER(wintypes.HICON), wintypes.UINT]
shell32.ExtractIconExW.restype = wintypes.UINT

k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
k32.Process32FirstW.restype = wintypes.BOOL
k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
k32.Process32NextW.restype = wintypes.BOOL
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k32.GetProcessHandleCount.restype = wintypes.BOOL
k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_void_p]
k32.GetProcessTimes.restype = wintypes.BOOL
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GR_GDIOBJECTS, GR_USEROBJECTS = 0, 1
DESKTOPHORZRES = 118


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


# ---------------------------------------------------------------- 几何
def dpi_scale():
    """物理 / 逻辑 比例。per-monitor aware 进程应为 1.0。"""
    hdc = u32.GetDC(None)
    phys = g32.GetDeviceCaps(hdc, DESKTOPHORZRES)
    u32.ReleaseDC(None, hdc)
    logical = u32.GetSystemMetrics(0)
    if logical <= 0 or phys <= 0:
        return 1.0
    return max(1.0, phys / logical)


def _phys_rect(r):
    s = dpi_scale()
    return (int(round(r.left * s)), int(round(r.top * s)),
            int(round(r.right * s)), int(round(r.bottom * s)))


def screen_physical():
    return (u32.GetSystemMetrics(0), u32.GetSystemMetrics(1))


def monitor_rects_physical():
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    mon = u32.MonitorFromPoint(wintypes.POINT(0, 0), 1)  # MONITOR_DEFAULTTOPRIMARY
    u32.GetMonitorInfoW(mon, ctypes.byref(mi))
    return _phys_rect(mi.rcMonitor), _phys_rect(mi.rcWork)


def taskbar_rect_physical():
    h = u32.FindWindowW("Shell_TrayWnd", None)
    if not h:
        return None
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return _phys_rect(r)


def find_widget():
    return u32.FindWindowW(CLASS, None)


def window_pid(hwnd):
    d = wintypes.DWORD(0)
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(d))
    return d.value


def window_rect_physical(hwnd):
    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return _phys_rect(r)


def widget_info():
    h = find_widget()
    if not h:
        return None
    style = u32.GetWindowLongPtrW(h, -16)   # GWL_STYLE
    ex = u32.GetWindowLongPtrW(h, -20)      # GWL_EXSTYLE
    return {
        "hwnd": int(h),
        "pid": window_pid(h),
        "visible": bool(u32.IsWindowVisible(h)),
        "rect": window_rect_physical(h),
        "style": int(style) & 0xFFFFFFFF,
        "exstyle": int(ex) & 0xFFFFFFFF,
    }


# ---------------------------------------------------------------- 进程指标
def proc_stats(pid):
    """WS(MB) / 私有(MB) / 句柄 / GDI / USER 对象。"""
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
        n = wintypes.DWORD(0)
        hok = k32.GetProcessHandleCount(h, ctypes.byref(n))
        return {
            "ws_mb": pmc.WorkingSetSize / 1048576.0 if ok else None,
            "priv_mb": pmc.PrivateUsage / 1048576.0 if ok else None,
            "handles": n.value if hok else None,
            "gdi": u32.GetGuiResources(h, GR_GDIOBJECTS),
            "user": u32.GetGuiResources(h, GR_USEROBJECTS),
        }
    finally:
        k32.CloseHandle(h)


def proc_cpu_seconds(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                   ctypes.byref(k), ctypes.byref(u)):
            return None

        def ft(t):
            return ((t.dwHighDateTime << 32) | t.dwLowDateTime) / 1e7
        return ft(k) + ft(u)
    finally:
        k32.CloseHandle(h)


def exe_icon_count(path=EXE):
    n = wintypes.HICON()
    try:
        return int(shell32.ExtractIconExW(path, -1, None, None, 0))
    except Exception:
        return -1


# ---------------------------------------------------------------- 配置 / 启动
DEFAULT_CFG = {
    "mode": "desktop", "x": 0, "y": 0, "interval": 1000,
    "cpu": 1, "mem": 1, "disk": 1, "net": 1,
    "theme": "light", "locked": 0, "hide_fs": 1, "autostart": 0,
}


def write_config(**kw):
    c = dict(DEFAULT_CFG)
    c.update(kw)
    os.makedirs(CFG_DIR, exist_ok=True)
    lines = ["; SysMonChip 配置（verifier 写入）"]
    for k in ("mode", "x", "y", "interval", "cpu", "mem", "disk", "net",
              "theme", "locked", "hide_fs", "autostart"):
        lines.append(f"{k}={c[k]}")
    with open(CFG_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return c


def read_config_text():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def read_config_dict():
    txt = read_config_text() or ""
    d = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        k, v = line.split("=", 1)
        d[k.strip()] = v.strip()
    return d


def launch(extra_args=(), wait_visible=True, timeout=8.0):
    """启动 exe，APPDATA 指向 .appdata-test；返回 Popen。"""
    env = dict(os.environ, APPDATA=APPDATA_TEST)
    p = subprocess.Popen([EXE, *extra_args], env=env, close_fds=True,
                         creationflags=0x00000008)  # DETACHED_PROCESS
    if wait_visible:
        if not wait_widget(pid=p.pid, timeout=timeout):
            raise RuntimeError(f"widget window not visible for pid {p.pid}, "
                               f"exit={p.poll()}")
    return p


def wait_widget(pid=None, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = find_widget()
        if h and u32.IsWindowVisible(h):
            if pid is None or window_pid(h) == pid:
                return h
        time.sleep(0.01)
    return None


def stop(wait_exit=None, timeout=6.0):
    """用 exe --quit 收尾；若给了 Popen，则等它真正退出。返回退出码。"""
    subprocess.run([EXE, "--quit"], capture_output=True, timeout=10)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if find_widget() is None:
            break
        time.sleep(0.02)
    code = None
    if wait_exit is not None:
        try:
            code = wait_exit.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
    # 兜底：再发一次 --quit，确认窗口消失
    if find_widget() is not None:
        subprocess.run([EXE, "--quit"], capture_output=True, timeout=10)
        time.sleep(0.3)
    return code


def trace_path():
    return os.path.join(os.environ.get("TEMP", ""), "sysmonchip-trace.txt")


def dump_path():
    return os.path.join(os.environ.get("TEMP", ""), "sysmonchip-dump.txt")


def run_dump():
    """执行 --dump 并把解析后的 dict 返回（附带原始文本、耗时）。"""
    p = dump_path()
    if os.path.exists(p):
        os.remove(p)
    env = dict(os.environ, APPDATA=APPDATA_TEST)
    t0 = time.time()
    subprocess.run([EXE, "--dump"], env=env, capture_output=True, timeout=20)
    wall = time.time() - t0
    txt = None
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
    out = {}
    if txt:
        for line in txt.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return {"raw": txt, "map": out, "wall_s": round(wall, 3)}


def proc_alive(pid):
    """进程是否仍存活（toolhelp 快照，比 OpenProcess 可靠）。"""
    return pid in list_pids()


def list_pids(name="SysMonChip.exe"):
    """枚举指定 exe 名的活动进程 PID（toolhelp32）。"""
    TH32CS_SNAPPROCESS = 0x2
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    pids = []
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if k32.Process32FirstW(snap, ctypes.byref(e)):
            while True:
                if e.szExeFile.lower() == name.lower():
                    pids.append(int(e.th32ProcessID))
                if not k32.Process32NextW(snap, ctypes.byref(e)):
                    break
    finally:
        k32.CloseHandle(snap)
    return pids


# ---------------------------------------------------------------- 截屏
def grab():
    from PIL import ImageGrab
    im = ImageGrab.grab(all_screens=True)
    return im


def grab_crop(rect, pad=0, path=None):
    """按物理矩形截屏裁剪（pad 为额外像素留白）。"""
    im = grab()
    x0 = max(0, rect[0] - pad)
    y0 = max(0, rect[1] - pad)
    x1 = min(im.width, rect[2] + pad)
    y1 = min(im.height, rect[3] + pad)
    c = im.crop((x0, y0, x1, y1))
    if path:
        c.save(path)
    return c


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dirs():
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(SHOTS, exist_ok=True)


if __name__ == "__main__":
    # 自检：输出当前环境事实
    ensure_dirs()
    print(json.dumps({
        "exe": EXE,
        "exe_bytes": os.path.getsize(EXE),
        "exe_icons": exe_icon_count(),
        "dpi_aware": DPI_AWARE,
        "dpi_scale": dpi_scale(),
        "screen_physical": screen_physical(),
        "screenshot_size": list(grab().size),
        "monitor_work": monitor_rects_physical(),
        "taskbar_rect": taskbar_rect_physical(),
        "temp": os.environ.get("TEMP"),
        "widget": widget_info(),
    }, ensure_ascii=False, indent=2))
