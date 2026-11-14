"""A3：数值正确性对照（--dump 读数 vs 独立外部测量）。

口径：
- CPU：typeperf "\\Processor(_Total)\\% Processor Time"（PDH，1 s 采样，按窗口重叠加权）
- MEM：Get-Counter "\\Memory\\Available MBytes" + 物理内存总量 -> 物理占用%；另给
       "\\Memory\\% Committed Bytes In Use"（提交口径，概念不同，仅参考）
- DISK：Get-PSDrive C 的 Used/(Used+Free)
- if_seen：netsh interface show interface 的「已连接」接口数

网速对照见 a3b_net.py（typeperf 网卡收发速率，同一接口口径）。
产出：data/a3-metrics.json
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402


def ps(cmd, timeout=60):
    p = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return p.stdout.strip(), p.stderr.strip(), p.returncode


def get_counter(path, samples=1, interval=1):
    cmd = (f"(Get-Counter '{path}' -SampleInterval {interval} "
           f"-MaxSamples {samples}).CounterSamples | ForEach-Object {{ $_.CookedValue }}")
    out, err, rc = ps(cmd, timeout=interval * samples + 30)
    vals = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            vals.append(float(line.replace(",", ".")))
        except ValueError:
            pass
    return vals


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def total_phys_bytes():
    c.k32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
    c.k32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not c.k32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None, None
    return m.ullTotalPhys, m.ullAvailPhys


def disk_psdrive():
    out, err, rc = ps("Get-PSDrive C | Select-Object Used,Free | ConvertTo-Json -Compress")
    try:
        d = json.loads(out)
        return float(d["Used"]), float(d["Free"])
    except Exception:
        return None, None


def parse_typeperf(path):
    """返回 [(epoch_ts, value)]。"""
    samples = []
    if not os.path.exists(path):
        return samples
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = [x.strip('"') for x in line.strip().split('","')]
            if len(parts) < 2:
                continue
            try:
                ts = datetime.strptime(parts[0], "%m/%d/%Y %H:%M:%S.%f").timestamp()
                val = float(parts[1])
            except ValueError:
                continue
            samples.append((ts, val))
    return samples


def main():
    c.ensure_dirs()
    c.stop()
    time.sleep(0.5)
    result = {"ts": datetime.now().isoformat(timespec="seconds")}

    # -- 1. dump 可用性 + 配置读取
    c.write_config(mode="taskbar", theme="dark")
    c.stop()
    time.sleep(0.3)
    d0 = c.run_dump()
    result["dump"] = {"raw": d0["raw"], "map": d0["map"], "wall_s": d0["wall_s"]}
    result["dump"]["cfg_dir_ok"] = (
        d0["map"].get("cfg_dir", "").lower() == c.CFG_DIR.lower())
    result["dump"]["mode_readback"] = d0["map"].get("mode")
    result["dump"]["theme_readback"] = d0["map"].get("theme")

    # -- 2. CPU：typeperf 并行 + 8 次 dump
    cpu_csv = os.path.join(c.DATA, "a3-typeperf-cpu.csv")
    if os.path.exists(cpu_csv):
        os.remove(cpu_csv)  # typeperf 对已存在的输出文件会交互式询问是否覆盖 -> 会挂住
    tp = subprocess.Popen(
        ["typeperf", r"\Processor(_Total)\% Processor Time", "-sc", "14", "-si", "1",
         "-f", "CSV", "-o", cpu_csv],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.4)
    dumps = []
    for i in range(8):
        w0 = time.time()
        d = c.run_dump()
        w1 = time.time()
        dumps.append({"i": i + 1, "start": w0, "end": w1,
                      "cpu": int(d["map"].get("cpu", -1)),
                      "mem": int(d["map"].get("mem", -1)),
                      "disk": int(d["map"].get("disk", -1)),
                      "up": int(d["map"].get("up", -1)),
                      "down": int(d["map"].get("down", -1))})
    tp.wait(timeout=30)

    samples = parse_typeperf(cpu_csv)
    cpu_pairs = []
    for d in dumps:
        win0, win1 = d["start"], d["end"]
        num = den = 0.0
        for ts, val in samples:
            a, b = ts - 1.0, ts
            ov = min(b, win1) - max(a, win0)
            if ov > 0:
                num += val * ov
                den += ov
        d["cpu_perf"] = round(num / den, 2) if den > 0 else None
        if d["cpu_perf"] is not None:
            d["cpu_diff"] = round(d["cpu"] - d["cpu_perf"], 2)
            cpu_pairs.append((d["cpu"], d["cpu_perf"]))
    result["cpu"] = {
        "dumps": dumps,
        "typeperf_samples": [{"t": round(t, 3), "v": v} for t, v in samples],
        "pair_count": len(cpu_pairs),
        "avg_dump": round(sum(a for a, _ in cpu_pairs) / len(cpu_pairs), 2) if cpu_pairs else None,
        "avg_perf": round(sum(b for _, b in cpu_pairs) / len(cpu_pairs), 2) if cpu_pairs else None,
        "bias_dump_minus_perf": round(sum(a - b for a, b in cpu_pairs) / len(cpu_pairs), 2) if cpu_pairs else None,
        "mae": round(sum(abs(a - b) for a, b in cpu_pairs) / len(cpu_pairs), 2) if cpu_pairs else None,
        "per_pair": [[a, round(b, 2), round(a - b, 2)] for a, b in cpu_pairs],
    }

    # -- 3. MEM / DISK（同一时刻 dump + 外部读数）
    avail = get_counter(r"\Memory\Available MBytes", samples=1)
    commit = get_counter(r"\Memory\% Committed Bytes In Use", samples=1)
    total_phys, avail_phys = total_phys_bytes()
    used, free = disk_psdrive()
    d1 = c.run_dump()
    mem = int(d1["map"].get("mem", -1))
    disk = int(d1["map"].get("disk", -1))
    mem_exp = None
    if avail and total_phys:
        mem_exp = round((total_phys - avail[0] * 1048576) / total_phys * 100)
    disk_exp = round(used / (used + free) * 100) if used is not None else None
    result["mem"] = {
        "dump_mem": mem,
        "available_mb": avail[0] if avail else None,
        "total_phys_gb": round(total_phys / 2**30, 2) if total_phys else None,
        "expected_physical_pct": mem_exp,
        "diff": None if mem_exp is None else mem - mem_exp,
        "committed_pct": round(commit[0], 1) if commit else None,
        "note": "dump 用 GlobalMemoryStatusEx.dwMemoryLoad（物理内存占用），"
                "与 % Committed Bytes In Use（提交电荷）不是同一口径。",
    }
    result["disk"] = {
        "dump_disk": disk,
        "psdrive_used_bytes": used,
        "psdrive_free_bytes": free,
        "expected_pct": disk_exp,
        "diff": None if disk_exp is None else disk - disk_exp,
    }

    # -- 4. if_seen：netsh 列接口（独立工具）
    out, err, rc = ps("netsh interface show interface")
    conn = [ln for ln in out.splitlines() if "已连接" in ln or "Connected" in ln]
    result["if_seen"] = {
        "dump_if_seen": d1["map"].get("if_seen"),
        "netsh_connected_lines": conn,
        "netsh_connected_count": len(conn),
    }

    c.save_json(os.path.join(c.DATA, "a3-metrics.json"), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
