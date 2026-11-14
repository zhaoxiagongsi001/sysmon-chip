"""A/B 交替基准：轮换两个 exe，抵消机器负载漂移，输出中位数。

每轮开始前杀掉所有 SysMonChip* 进程：单实例互斥会让新 exe 静默退出，
残留实例还会污染下一次读数（踩过：bench.py --launch 不会自己收尸）。

用法：python tools/ab_bench.py <A.exe> <B.exe> [--rounds 4] [--seconds 25]
"""
import argparse
import ctypes
import os
import statistics
import subprocess
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(HERE, "bench.py")
KEYS = ("cold_start_to_window_ms", "cpu_us_per_sec", "ws_kb", "private_kb")

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD)]
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.OpenProcess.restype = wintypes.HANDLE


def kill_all():
    """杀掉所有 SysMonChip* 进程。

    不用 tasklist/taskkill：沙箱里它们会被拒绝（ERROR: Access denied）。
    """
    buf = (wintypes.DWORD * 2048)()
    need = wintypes.DWORD()
    if not _psapi.EnumProcesses(buf, ctypes.sizeof(buf), ctypes.byref(need)):
        return
    for pid in list(buf)[: need.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        h = _k32.OpenProcess(0x0001 | 0x1000, False, pid)  # TERMINATE | QUERY_LIMITED_INFORMATION
        if not h:
            continue
        path = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        ok = _k32.QueryFullProcessImageNameW(h, 0, path, ctypes.byref(size))
        if ok and path.value.replace("/", "\\").rsplit("\\", 1)[-1].lower().startswith("sysmonchip"):
            _k32.TerminateProcess(h, 1)
        _k32.CloseHandle(h)
    time.sleep(0.5)


def sample(exe, seconds):
    proc = subprocess.run(
        [sys.executable, BENCH, "--launch", "--seconds", str(seconds), "--exe", exe],
        capture_output=True, text=True,
    )
    vals = {}
    # bench.py 把多个键打在同一行（`seconds=8 cpu_ms_total=… cpu_us_per_sec=…`），按 token 取
    for tok in proc.stdout.replace("\n", " ").split():
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        if k in KEYS:
            try:
                vals[k] = float(v)
            except ValueError:
                pass
    if "cpu_us_per_sec" not in vals:
        print("    bench said:", " | ".join(proc.stdout.split())[:160], file=sys.stderr)
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--seconds", type=int, default=25)
    args = ap.parse_args()
    acc = {"A": [], "B": []}
    for i in range(args.rounds):
        order = (("A", args.a), ("B", args.b)) if i % 2 == 0 else (("B", args.b), ("A", args.a))
        for tag, exe in order:
            kill_all()
            v = sample(exe, args.seconds)
            if "cpu_us_per_sec" not in v:
                print(f"  round{i} {tag} SKIP", flush=True)
                continue
            acc[tag].append(v)
            print(f"  round{i} {tag} cpu={v['cpu_us_per_sec']:.0f} ws={v['ws_kb']:.0f} "
                  f"cold={v.get('cold_start_to_window_ms')}", flush=True)
    kill_all()
    print()
    med = {}
    for tag, exe in (("A", args.a), ("B", args.b)):
        if not acc[tag]:
            print(f"{tag} {os.path.basename(exe)}: 无有效读数")
            continue
        cpu = statistics.median(x["cpu_us_per_sec"] for x in acc[tag])
        ws = statistics.median(x["ws_kb"] for x in acc[tag])
        cold = statistics.median(x.get("cold_start_to_window_ms", 0) for x in acc[tag])
        med[tag] = cpu
        print(f"{tag} {os.path.basename(exe):30} cpu_med={cpu:7.0f} us/s  ws_med={ws:6.0f} KB  "
              f"cold_med={cold:6.1f} ms")
    if "A" in med and "B" in med:
        print(f"CPU B/A = {med['B']/med['A']:.3f} ({100*(med['B']-med['A'])/med['A']:+.1f}%)")


if __name__ == "__main__":
    main()
