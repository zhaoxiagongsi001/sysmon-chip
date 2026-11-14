"""SysMonChip Lite v2.0 独立复核：公共工具（verifier 自写，不引用 tools/ 下既有脚本）。

要点：
- 进程强制 per-monitor DPI aware V2，窗口矩形 / 截屏统一物理像素（本机 225%）。
- 两版 exe 共用单实例互斥 `Local\\SysMonChip.v1` 与窗口类 `SysMonChipWnd`，
  任何测试前必须 ensure_clean()：对两版各发一次 --quit，等窗口消失 + 0.7s。
- 配置固定写到 APPDATA=D:/DSH/sysmon-chip/.appdata-test。
"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE_LITE = os.path.join(ROOT, "发布", "SysMonChipLite.exe")
EXE_STD = os.path.join(ROOT, "发布", "SysMonChip.exe")
APPDATA_TEST = os.path.join(ROOT, ".appdata-test")
CFG_DIR = os.path.join(APPDATA_TEST, "SysMonChip")
CFG_PATH = os.path.join(CFG_DIR, "config.ini")
SHOTS = os.path.join(ROOT, "screenshots")
ACC = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ACC, "data")

CLASS = "SysMonChipWnd"
MUTEX_NAME = r"Local\SysMonChip.v1"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# ---------------------------------------------------------------- DPI aware
u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
u32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
try:
    DPI_AWARE = bool(u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
except Exception:
    DPI_AWARE = False

# ---------------------------------------------------------------- prototypes
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowExW.restype = wintypes.HWND
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowRect.restype = wintypes.BOOL
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongPtrW.restype = ctypes.c_longlong
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
u32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
u32.GetGuiResources.restype = wintypes.DWORD
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.PostMessageW.restype = wintypes.BOOL

g32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
g32.GetDeviceCaps.restype = ctypes.c_int

k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k32.GetProcessHandleCount.restype = wintypes.BOOL
k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.c_void_p]
k32.GetProcessTimes.restype = wintypes.BOOL
k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
k32.Process32FirstW.restype = wintypes.BOOL
k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
k32.Process32NextW.restype = wintypes.BOOL
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                   ctypes.POINTER(wintypes.HICON),
                                   ctypes.POINTER(wintypes.HICON), wintypes.UINT]
shell32.ExtractIconExW.restype = wintypes.UINT

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GR_GDIOBJECTS, GR_USEROBJECTS = 0, 1
DESKTOPHORZRES = 118
TH32CS_SNAPPROCESS = 0x2


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


# ---------------------------------------------------------------- 环境 / 几何
def dpi_scale():
    hdc = u32.GetDC(None)
    phys = g32.GetDeviceCaps(hdc, DESKTOPHORZRES)
    u32.ReleaseDC(None, hdc)
    logical = u32.GetSystemMetrics(0)
    if logical <= 0 or phys <= 0:
        return 1.0
    return max(1.0, phys / logical)


def screen_physical():
    return (u32.GetSystemMetrics(0), u32.GetSystemMetrics(1))


def _phys(r):
    s = dpi_scale()
    return (int(round(r.left * s)), int(round(r.top * s)),
            int(round(r.right * s)), int(round(r.bottom * s)))


def monitor_rects_physical():
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    mon = u32.MonitorFromPoint(wintypes.POINT(0, 0), 1)
    u32.GetMonitorInfoW(mon, ctypes.byref(mi))
    return _phys(mi.rcMonitor), _phys(mi.rcWork)


def taskbar_rect_physical():
    h = u32.FindWindowW("Shell_TrayWnd", None)
    if not h:
        return None
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return _phys(r)


def tray_rect_physical():
    tb = u32.FindWindowW("Shell_TrayWnd", None)
    if not tb:
        return None
    h = u32.FindWindowExW(tb, None, "TrayNotifyWnd", None)
    if not h:
        return None
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return _phys(r)


# ---------------------------------------------------------------- 窗口 / 进程
def find_widget():
    return u32.FindWindowW(CLASS, None)


def window_pid(hwnd):
    d = wintypes.DWORD(0)
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(d))
    return d.value


def window_info():
    h = find_widget()
    if not h:
        return None
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return {
        "hwnd": int(h), "pid": window_pid(h),
        "visible": bool(u32.IsWindowVisible(h)),
        "rect": _phys(r),
        "style": int(u32.GetWindowLongPtrW(h, -16)) & 0xFFFFFFFF,
        "exstyle": int(u32.GetWindowLongPtrW(h, -20)) & 0xFFFFFFFF,
    }


def wait_widget(pid=None, timeout=8.0, visible=True):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        h = find_widget()
        if h and (not visible or u32.IsWindowVisible(h)):
            if pid is None or window_pid(h) == pid:
                return h
        time.sleep(0.0005)
    return None


def list_pids(name):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    pids, e = [], PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if k32.Process32FirstW(snap, ctypes.byref(e)):
            while True:
                if e.szExeFile.lower() == name.lower():
                    pids.append(int(e.th32ProcessID))
                if not k32.Process32NextW(snap, ctypes.byref(e)):
                    break
    finally:
        k32.CloseHandle(snap)
    return pids


def chip_pids():
    return {"lite": list_pids("SysMonChipLite.exe"), "std": list_pids("SysMonChip.exe")}


def proc_stats(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
        n = wintypes.DWORD(0)
        hok = k32.GetProcessHandleCount(h, ctypes.byref(n))
        return {"ws_mb": round(pmc.WorkingSetSize / 1048576.0, 4) if ok else None,
                "priv_mb": round(pmc.PrivateUsage / 1048576.0, 4) if ok else None,
                "handles": n.value if hok else None,
                "gdi": u32.GetGuiResources(h, GR_GDIOBJECTS),
                "user": u32.GetGuiResources(h, GR_USEROBJECTS)}
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
        return ((k.dwHighDateTime << 32) | k.dwLowDateTime) / 1e7 + \
               ((u.dwHighDateTime << 32) | u.dwLowDateTime) / 1e7
    finally:
        k32.CloseHandle(h)


# ---------------------------------------------------------------- 配置
KEY_ORDER = ("mode", "x", "y", "interval", "cpu", "mem", "disk", "net",
             "theme", "locked", "hide_fs", "autostart")
DEFAULT_CFG = {"mode": "taskbar", "x": 0, "y": 0, "interval": 1000,
               "cpu": 1, "mem": 1, "disk": 1, "net": 1,
               "theme": "auto", "locked": 0, "hide_fs": 1, "autostart": 0}


def write_config(**kw):
    c = dict(DEFAULT_CFG)
    c.update(kw)
    os.makedirs(CFG_DIR, exist_ok=True)
    lines = ["; SysMonChip config (verifier lite-acceptance)"]
    lines += [f"{k}={c[k]}" for k in KEY_ORDER]
    with open(CFG_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return c


def remove_config():
    try:
        os.remove(CFG_PATH)
    except OSError:
        pass


def read_config_text():
    try:
        with open(CFG_PATH, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def read_config_dict():
    d = {}
    for line in (read_config_text() or "").splitlines():
        line = line.strip()
        if not line or line[0] in "#;" or "=" not in line:
            continue
        k, v = line.split("=", 1)
        d[k.strip()] = v.strip()
    return d


# ---------------------------------------------------------------- 启动 / 退出
def _env():
    return dict(os.environ, APPDATA=APPDATA_TEST)


def launch(exe, args=(), wait=True, timeout=8.0):
    """启动 exe；wait=True 时等到本进程窗口可见，返回 (Popen, 外部耗时秒/None)。"""
    p = subprocess.Popen([exe, *args], env=_env(), close_fds=True,
                         creationflags=0x00000008)  # DETACHED_PROCESS
    if not wait:
        return p, None
    t0 = time.perf_counter()
    h = wait_widget(pid=p.pid, timeout=timeout)
    dt = time.perf_counter() - t0
    if h is None:
        return p, None
    return p, dt


def wait_no_window(timeout=6.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if find_widget() is None:
            return True
        time.sleep(0.02)
    return False


def quit_exe(exe, settle=0.7, timeout=8.0):
    """用 <exe> --quit 关闭已运行实例；等窗口消失 + settle 秒。返回 --quit 退出码。"""
    try:
        r = subprocess.run([exe, "--quit"], env=_env(), capture_output=True, timeout=timeout)
        code = r.returncode
    except subprocess.TimeoutExpired:
        code = None
    wait_no_window(timeout=timeout)
    time.sleep(settle)
    return code


def ensure_clean(timeout=6.0):
    """两版各发 --quit，确认无窗口、无进程；返回清理后状态。"""
    for _ in range(3):
        quit_exe(EXE_LITE, settle=0.05)
        quit_exe(EXE_STD, settle=0.05)
        if find_widget() is None and not any(chip_pids().values()):
            time.sleep(0.2)
            return {"clean": True, "pids": chip_pids()}
    return {"clean": find_widget() is None and not any(chip_pids().values()),
            "pids": chip_pids(), "window": window_info()}


def run_cli(exe, args, timeout=25):
    """跑一次性 CLI（--dump/--trace 之外的 --selftest 等），返回退出码/耗时/stdout。"""
    t0 = time.perf_counter()
    try:
        r = subprocess.run([exe, *args], env=_env(), capture_output=True, timeout=timeout)
        return {"code": r.returncode, "wall_s": round(time.perf_counter() - t0, 3),
                "stdout": r.stdout.decode("utf-8", "replace")[:2000],
                "stderr": r.stderr.decode("utf-8", "replace")[:2000]}
    except subprocess.TimeoutExpired:
        return {"code": None, "wall_s": round(time.perf_counter() - t0, 3), "timeout": True}


# ---------------------------------------------------------------- 临时文件输出
def temp_file(name):
    """%TEMP%\\<name>；子进程继承本进程 TEMP，与 GetTempPathW 一致。"""
    return os.path.join(os.environ.get("TEMP", ""), name)


def clear_temp(name):
    p = temp_file(name)
    try:
        os.remove(p)
    except OSError:
        pass
    return p


def read_temp(name, retries=20, interval=0.02):
    p = temp_file(name)
    for _ in range(retries):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            if txt:
                return txt
        except OSError:
            pass
        time.sleep(interval)
    return None


def parse_kv(text):
    d = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def run_dump(exe):
    clear_temp("sysmonchip-dump.txt")
    r = run_cli(exe, ["--dump"], timeout=20)
    txt = read_temp("sysmonchip-dump.txt", retries=30, interval=0.02)
    r["raw"] = txt
    r["map"] = parse_kv(txt)
    return r


def run_trace_start(exe, timeout=8.0):
    """--trace 冷启动一次：返回外部耗时、自报 startup_ms 等。"""
    clear_temp("sysmonchip-trace.txt")
    p, ext = launch(exe, ["--trace"], wait=True, timeout=timeout)
    txt = read_temp("sysmonchip-trace.txt", retries=60, interval=0.01)
    return {"pid": p.pid, "external_ms": round(ext * 1000, 2) if ext else None,
            "trace": parse_kv(txt), "raw_trace": txt}


# ---------------------------------------------------------------- 截屏
def grab():
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=True)


def grab_crop(rect, pad=0, path=None):
    im = grab()
    x0 = max(0, rect[0] - pad)
    y0 = max(0, rect[1] - pad)
    x1 = min(im.width, rect[2] + pad)
    y1 = min(im.height, rect[3] + pad)
    c = im.crop((x0, y0, x1, y1))
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        c.save(path)
    return c


def shot(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = grab()
    im.save(path)
    return im


# ---------------------------------------------------------------- 档案 / IO
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save_json(name, obj):
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(f"[saved] {p}")
    return p


def load_json(name):
    with open(os.path.join(DATA, name), "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dirs():
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(SHOTS, exist_ok=True)


def exe_size(path):
    return os.path.getsize(path)


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return None
    if len(s) == 1:
        return s[0]
    idx = (len(s) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


if __name__ == "__main__":
    ensure_dirs()
    print(json.dumps({
        "root": ROOT, "dpi_aware": DPI_AWARE, "dpi_scale": dpi_scale(),
        "screen": screen_physical(), "screenshot": list(grab().size),
        "monitor_work": monitor_rects_physical(), "taskbar": taskbar_rect_physical(),
        "tray": tray_rect_physical(), "temp": os.environ.get("TEMP"),
        "exe_lite": [exe_size(EXE_LITE), sha256(EXE_LITE)[:16]],
        "exe_std": [exe_size(EXE_STD), sha256(EXE_STD)[:16]],
        "cfg": read_config_dict(), "clean": ensure_clean(),
    }, ensure_ascii=False, indent=2))
