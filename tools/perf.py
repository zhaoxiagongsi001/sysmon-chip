"""性能与冷启动测量（验收用，无第三方依赖）。

用法：python perf.py [--seconds 60] [--interval 1]
输出：screenshots/perf.csv + 汇总表；启动耗时来自 exe 自己的 --trace。
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EXE = r"D:\DSH\sysmon-chip\发布\SysMonChip.exe"
APPDATA_TEST = r"D:\DSH\sysmon-chip\.appdata-test"
OUT = r"D:\DSH\sysmon-chip\screenshots"

k32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
user32 = ctypes.windll.user32

k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.c_void_p] * 4
k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
user32.GetGuiResources.restype = wintypes.DWORD
user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def open_proc(pid, access=PROCESS_QUERY_LIMITED_INFORMATION):
    return k32.OpenProcess(access, False, pid)


def cpu_seconds(pid):
    h = open_proc(pid)
    if not h:
        return 0.0
    creation, exit_, kernel, usertime = (wintypes.FILETIME() for _ in range(4))
    ok = k32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_),
                             ctypes.byref(kernel), ctypes.byref(usertime))
    k32.CloseHandle(h)
    if not ok:
        return 0.0

    def ft(t):
        return ((t.dwHighDateTime << 32) | t.dwLowDateTime) / 1e7

    return ft(kernel) + ft(usertime)


def mem(pid):
    h = open_proc(pid)
    if not h:
        return 0.0, 0.0
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), ctypes.sizeof(PMC))
    k32.CloseHandle(h)
    if not ok:
        return 0.0, 0.0
    return pmc.WorkingSetSize / 1024 / 1024, pmc.PrivateUsage / 1024 / 1024


def handle_count(pid):
    h = open_proc(pid)
    if not h:
        return -1
    n = wintypes.DWORD(0)
    ok = k32.GetProcessHandleCount(h, ctypes.byref(n))
    k32.CloseHandle(h)
    return n.value if ok else -1


def gui_objects(pid, flag):
    h = open_proc(pid)
    if not h:
        return -1
    n = user32.GetGuiResources(h, flag)
    k32.CloseHandle(h)
    return n


def kill_all():
    subprocess.run(["taskkill", "/F", "/IM", "SysMonChip.exe"], capture_output=True)
    time.sleep(0.3)


def startup_probe():
    kill_all()
    env = dict(os.environ, APPDATA=APPDATA_TEST)
    trace = os.path.join(os.environ.get("TEMP", ""), "sysmonchip-trace.txt")
    if os.path.exists(trace):
        os.remove(trace)
    p = subprocess.Popen([EXE, "--trace"], env=env, close_fds=True, creationflags=0x00000008)
    time.sleep(1.5)
    p.terminate()
    time.sleep(0.2)
    kill_all()
    if os.path.exists(trace):
        return open(trace, encoding="utf-8").read().strip()
    return "no trace"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    os.makedirs(APPDATA_TEST, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    print("== startup ==")
    print(startup_probe())
    print("exe_bytes", os.path.getsize(EXE))

    kill_all()
    env = dict(os.environ, APPDATA=APPDATA_TEST)
    p = subprocess.Popen([EXE], env=env, close_fds=True, creationflags=0x00000008)
    time.sleep(2.0)
    if p.poll() is not None:
        print("app exited early:", p.returncode)
        return 1

    rows = []
    t0 = time.time()
    cpu0 = cpu_seconds(p.pid)
    while time.time() - t0 < args.seconds:
        time.sleep(args.interval)
        if p.poll() is not None:
            print("process exited during run")
            break
        ws, priv = mem(p.pid)
        rows.append({
            "t": round(time.time() - t0, 1),
            "ws_mb": round(ws, 2),
            "priv_mb": round(priv, 2),
            "handles": handle_count(p.pid),
            "gdi": gui_objects(p.pid, 0),
            "user": gui_objects(p.pid, 1),
        })
    elapsed = time.time() - t0
    cpu1 = cpu_seconds(p.pid)
    kill_all()

    if not rows:
        print("no samples")
        return 1

    csv_path = os.path.join(OUT, "perf.csv")
    keys = list(rows[0].keys())
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(",".join(keys) + "\n")
        for r in rows:
            f.write(",".join(str(r[k]) for k in keys) + "\n")

    def stat(key):
        vals = [r[key] for r in rows]
        return min(vals), sum(vals) / len(vals), max(vals)

    ws = stat("ws_mb"); priv = stat("priv_mb")
    gdi = stat("gdi"); usr = stat("user"); hnd = stat("handles")
    ncpu = os.cpu_count() or 1
    cpu_one = (cpu1 - cpu0) / elapsed * 100 if elapsed else 0
    print(f"\n=== samples={len(rows)} over {elapsed:.1f}s ===")
    print(f"WS       min {ws[0]:.2f}  avg {ws[1]:.2f}  max {ws[2]:.2f} MB")
    print(f"private  min {priv[0]:.2f}  avg {priv[1]:.2f}  max {priv[2]:.2f} MB")
    print(f"GDI      min {gdi[0]}  max {gdi[2]};  USER min {usr[0]} max {usr[2]}")
    print(f"handles  min {hnd[0]}  max {hnd[2]}")
    print(f"CPU      {cpu_one:.3f}% of one core / {cpu_one / ncpu:.3f}% of system ({ncpu} cores)")
    print("csv:", csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
