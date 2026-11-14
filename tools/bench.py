"""运行时占用基准：工作集 / 私有 / 句柄 / GDI+USER / 线程 / CPU / 冷启动。

用法：
  python tools/bench.py --seconds 60          # 测已运行实例
  python tools/bench.py --launch --seconds 30 # 先冷启动再测，顺带测启动耗时
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

k32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.c_void_p] * 4
k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
user32.GetGuiResources.restype = wintypes.DWORD
user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def cpu_s(h):
    c, e, k, u = (wintypes.FILETIME() for _ in range(4))
    k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
    t = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime
    return (t(k) + t(u)) / 1e7


def snapshot(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    hc = wintypes.DWORD()
    k32.GetProcessHandleCount(h, ctypes.byref(hc))
    d = dict(
        ws=pmc.WorkingSetSize, private=pmc.PrivateUsage, paged=pmc.QuotaPagedPoolUsage,
        nonpaged=pmc.QuotaNonPagedPoolUsage, handles=hc.value,
        user=user32.GetGuiResources(h, 1), gdi=user32.GetGuiResources(h, 0),
        threads=ctypes.windll.kernel32.GetProcessHandleCount and 0,
        cpu=cpu_s(h),
    )
    k32.CloseHandle(h)
    return d


def find_pid():
    hwnd = user32.FindWindowW("SysMonChipWnd", None)
    if not hwnd:
        return None, None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value, hwnd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--exe", default=r"D:/DSH/.rust/target/release/SysMonChipLite.exe")
    a = ap.parse_args()

    start_ms = None
    if a.launch:
        t0 = time.perf_counter()
        subprocess.Popen([a.exe], close_fds=True)
        while time.perf_counter() - t0 < 15:
            pid, hwnd = find_pid()
            if hwnd:
                start_ms = (time.perf_counter() - t0) * 1000
                break
            time.sleep(0.002)
        print(f"cold_start_to_window_ms={start_ms:.1f}" if start_ms else "cold_start=FAIL")

    pid, hwnd = find_pid()
    if not pid:
        print("CHIP_NOT_FOUND")
        return 1
    print(f"pid={pid} hwnd={hwnd}")

    s0 = snapshot(pid)
    time.sleep(a.seconds)
    s1 = snapshot(pid)
    busy = s1["cpu"] - s0["cpu"]
    print(f"seconds={a.seconds:.0f} cpu_ms_total={busy*1000:.1f} "
          f"cpu_pct_of_one_core={busy*100/a.seconds:.3f}% cpu_us_per_sec={busy*1e6/a.seconds:.0f}")
    print(f"ws_kb={s1['ws']/1024:.0f} private_kb={s1['private']/1024:.0f} "
          f"paged_kb={s1['paged']/1024:.0f} nonpaged_kb={s1['nonpaged']/1024:.0f}")
    print(f"handles={s1['handles']} user_objects={s1['user']} gdi_objects={s1['gdi']}")
    print(f"ws_delta_kb={(s1['ws']-s0['ws'])/1024:+.0f} private_delta_kb={(s1['private']-s0['private'])/1024:+.0f}")
    return 0


sys.exit(main())
