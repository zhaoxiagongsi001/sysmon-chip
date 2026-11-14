"""lite-5：--dump 数值正确性（Lite 为主，Std 交叉）。

- CPU：进程内 PDH 计数器 \\Processor(_Total)\\% Processor Time（1 s 窗口），
       与 lite `--dump`（内部也是 1 s 差分）对齐；失败时回退 PowerShell Get-Counter。
- 内存：PowerShell Win32_OperatingSystem（1 - Free/Total）。
- 磁盘：PowerShell Get-PSDrive C（Used/(Used+Free)）。
- 网速：python requests 连续下载 npm registry tarball 造真实流量，同时跑两次
       `--dump`，并与 PowerShell Get-NetAdapterStatistics 的 ReceivedBytes 增量对照，
       给量级一致性（时长对齐误差 ±0.2 s，允许 ±50% 量级）。
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time

import lite_common as L

pdh = ctypes.WinDLL("pdh", use_last_error=True)
PDH_FMT_DOUBLE = 0x00000200


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]

class PDH_ITEM(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", PDH_FMT_COUNTERVALUE)]


def pdh_net_open():
    hq = ctypes.c_void_p()
    hc = ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, 0, ctypes.byref(hq)):
        return None, None, "open failed"
    if pdh.PdhAddEnglishCounterW(hq, r"\Network Interface(*)\Bytes Received/sec", 0,
                                ctypes.byref(hc)):
        pdh.PdhCloseQuery(hq)
        return None, None, "add counter failed"
    return hq, hc, None


def pdh_net_sum(hc):
    """返回 (总接收 B/s, 各实例明细)。调用前需已 CollectQueryData。"""
    size = ctypes.c_ulong(0)
    cnt = ctypes.c_ulong(0)
    pdh.PdhGetFormattedCounterArrayW(hc, PDH_FMT_DOUBLE, ctypes.byref(size),
                                     ctypes.byref(cnt), None)
    if size.value == 0:
        return None, []
    buf = ctypes.create_string_buffer(size.value)
    pdh.PdhGetFormattedCounterArrayW(hc, PDH_FMT_DOUBLE, ctypes.byref(size),
                                     ctypes.byref(cnt), buf)
    items = ctypes.cast(buf, ctypes.POINTER(PDH_ITEM))
    tot, det = 0.0, []
    for i in range(cnt.value):
        v = items[i].FmtValue.doubleValue
        tot += v
        det.append([items[i].szName, round(v)])
    return round(tot), det




pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
pdh.PdhOpenQueryW.restype = ctypes.c_ulong
pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_size_t,
                                      ctypes.POINTER(ctypes.c_void_p)]
pdh.PdhAddEnglishCounterW.restype = ctypes.c_ulong
pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
pdh.PdhCollectQueryData.restype = ctypes.c_ulong
pdh.PdhGetFormattedCounterValue.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                            ctypes.POINTER(ctypes.c_ulong),
                                            ctypes.POINTER(PDH_FMT_COUNTERVALUE)]
pdh.PdhGetFormattedCounterValue.restype = ctypes.c_ulong
pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                             ctypes.POINTER(ctypes.c_ulong),
                                             ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]

COUNTER = r"\Processor(_Total)\% Processor Time"
PW = ["pwsh", "-NoProfile", "-NonInteractive", "-Command"]
OUT = {}


def ps(cmd, timeout=90):
    t0 = time.perf_counter()
    r = subprocess.run(PW + [cmd], capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return {"code": r.returncode, "out": (r.stdout or "").strip(),
            "err": (r.stderr or "").strip()[:300],
            "wall_s": round(time.perf_counter() - t0, 2)}


def pdh_cpu_window(seconds=1.0):
    """返回 (cpu%, 错误)。PDH 两次采集的 1 s 窗口。"""
    hq = ctypes.c_void_p()
    hc = ctypes.c_void_p()
    err = pdh.PdhOpenQueryW(None, 0, ctypes.byref(hq))
    if err:
        return None, f"PdhOpenQuery err={err}"
    err = pdh.PdhAddEnglishCounterW(hq, COUNTER, 0, ctypes.byref(hc))
    if err:
        pdh.PdhCloseQuery(hq)
        return None, f"PdhAddEnglishCounter err={err}"
    try:
        if pdh.PdhCollectQueryData(hq):
            return None, "collect1 failed"
        time.sleep(seconds)
        if pdh.PdhCollectQueryData(hq):
            return None, "collect2 failed"
        val = PDH_FMT_COUNTERVALUE()
        err = pdh.PdhGetFormattedCounterValue(hc, PDH_FMT_DOUBLE, None, ctypes.byref(val))
        if err:
            return None, f"GetFormatted err={err}"
        return float(val.doubleValue), None
    finally:
        pdh.PdhCloseQuery(hq)


def ps_cpu_fallback():
    r = ps("(Get-Counter '\\Processor(_Total)\\% Processor Time' "
           "-SampleInterval 1 -MaxSamples 1).CounterSamples[0].CookedValue")
    try:
        return float(r["out"]), None
    except Exception:
        return None, f"fallback failed: {r['out'][:100]} {r['err'][:100]}"


def cpu_round(exe, round_i):
    """对齐：先起 --dump 进程，然后立刻开 PDH 1 s 窗口。"""
    L.ensure_clean()
    L.write_config(mode="taskbar", theme="light")
    time.sleep(0.6)
    L.clear_temp("sysmonchip-dump.txt")
    p = subprocess.Popen([exe, "--dump"], env=L._env(),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    cpu_pdh, pdh_err = pdh_cpu_window(1.0)
    if cpu_pdh is None:
        cpu_pdh, pdh_err = ps_cpu_fallback()
    p.wait(timeout=20)
    txt = L.read_temp("sysmonchip-dump.txt", retries=20)
    m = L.parse_kv(txt)
    return {"round": round_i, "exe": os.path.basename(exe),
            "dump_cpu": int(m["cpu"]) if m.get("cpu") else None,
            "pdh_cpu": round(cpu_pdh, 2) if cpu_pdh is not None else None,
            "pdh_err": pdh_err,
            "diff_pp": round(int(m["cpu"]) - cpu_pdh, 2) if m.get("cpu") and cpu_pdh is not None else None,
            "dump": m}


# ---------------------------------------------------------------- 网络
class Downloader:
    def __init__(self, url="https://registry.npmjs.org/typescript/-/typescript-5.6.3.tgz"):
        self.url = url
        self.stop = threading.Event()
        self.bytes = 0
        self.t_first = None
        self.t_last = None
        self.error = None
        self.th = None

    def _run(self):
        import requests
        sess = requests.Session()
        while not self.stop.is_set():
            try:
                r = sess.get(self.url, stream=True, timeout=15)
                r.raise_for_status()
                for chunk in r.iter_content(65536):
                    if not chunk:
                        continue
                    now = time.perf_counter()
                    if self.t_first is None:
                        self.t_first = now
                    self.bytes += len(chunk)
                    self.t_last = now
                    if self.stop.is_set():
                        break
                r.close()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                return

    def start(self, wait_first=True, timeout=8.0):
        self.th = threading.Thread(target=self._run, daemon=True)
        self.th.start()
        t0 = time.perf_counter()
        while wait_first and not self.stop:
            if self.bytes > 0 or self.error:
                return self.bytes > 0
            if time.perf_counter() - t0 > timeout:
                return False
            time.sleep(0.01)
        return True

    def snapshot(self):
        return {"t": time.perf_counter(), "bytes": self.bytes}

    def rate(self):
        if self.t_first is None or self.t_last is None or self.t_last <= self.t_first:
            return None
        return self.bytes / (self.t_last - self.t_first)

    def finish(self):
        self.stop.set()
        if self.th:
            self.th.join(timeout=10)
        return {"bytes": self.bytes, "error": self.error,
                "seconds": round((self.t_last - self.t_first), 3) if self.t_first and self.t_last else None,
                "rate_Bps": round(self.rate()) if self.rate() else None}


def net_round(exe):
    """用 PDH \\Network Interface(*)\\Bytes Received/sec 当独立基准，与 --dump down 同窗对照。

    本机只有 1 个非回环接口（Wi-Fi），dump 的 if_seen 也是 1，口径可对齐。
    PowerShell Get-NetAdapterStatistics 在低完整性沙箱被拒绝访问（实测记录）。
    """
    L.ensure_clean()
    L.write_config(mode="taskbar", theme="light")
    ps_net = ps("Get-NetAdapterStatistics | Measure-Object -Property ReceivedBytes -Sum", timeout=30)
    dl = Downloader()
    dl.start(wait_first=True, timeout=8.0)
    time.sleep(1.2)   # 让 TCP 进入稳定传输（首包/TLS 开销跳过）
    hq, hc, err = pdh_net_open()
    pairs = []
    if hq:
        for i in range(2):
            pdh.PdhCollectQueryData(hq)          # 窗口起点
            L.clear_temp("sysmonchip-dump.txt")
            r = subprocess.run([exe, "--dump"], env=L._env(), capture_output=True, timeout=20)
            m = L.parse_kv(L.read_temp("sysmonchip-dump.txt", retries=20))
            pdh.PdhCollectQueryData(hq)          # 窗口终点
            total, det = pdh_net_sum(hc)
            down = int(m.get("down", 0)) if m.get("down") else None
            pairs.append({"i": i + 1, "exit": r.returncode,
                          "dump_down_Bps": down, "dump_up_Bps": int(m.get("up", 0) or 0),
                          "if_seen": m.get("if_seen"), "pdh_rx_Bps": total,
                          "pdh_instances": det,
                          "ratio": round(down / total, 3) if (down and total) else None})
        pdh.PdhCloseQuery(hq)
    dl_info = dl.finish()
    result = {"exe": os.path.basename(exe), "pdh_error": err, "pairs": pairs,
              "ps_net": {"code": ps_net["code"], "err": ps_net["err"][:120]},
              "downloader": dl_info}
    ratios = [p["ratio"] for p in pairs if p.get("ratio")]
    if ratios:
        result["ratio_min_max"] = [min(ratios), max(ratios)]
    return result


def mem_total_bytes():
    """GlobalMemoryStatusEx 的 ullTotalPhys（只用于给 PDH AvailableMBytes 折算百分比）。"""
    class MSX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MSX()
    m.dwLength = ctypes.sizeof(MSX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullTotalPhys, m.ullAvailPhys


def main():
    L.ensure_dirs()
    print("初始环境:", json.dumps(L.ensure_clean(), ensure_ascii=False))
    # 1) CPU / MEM / DISK 三轮（lite），另 std 一轮对照
    rounds = []
    # 内存：CIM 在低完整性沙箱被拒绝访问（实测），改用 PDH Available MBytes +
    # GlobalMemoryStatusEx TotalPhys 折算，仍属独立于 App 的观测通道。
    ps_avail = ps("(Get-Counter '\\Memory\\Available MBytes').CounterSamples[0].CookedValue")
    total_phys, _ = mem_total_bytes()
    try:
        avail_mb = float(ps_avail["out"])
    except Exception:
        avail_mb = None
    mem_ps = round(100.0 * (1.0 - avail_mb / (total_phys / 1048576.0)), 2) if avail_mb else None
    ps_disk = ps("$d=Get-PSDrive -Name C;"
                 "[math]::Round($d.Used/($d.Used+$d.Free)*100,2)")
    print("PDH Available MBytes:", avail_mb, " TotalPhys GB:", round(total_phys / 2**30, 2),
          " -> mem% =", mem_ps, " PS 磁盘%:", ps_disk["out"],
          " wall:", ps_avail["wall_s"])
    disk_ps = float(ps_disk["out"]) if ps_disk["out"] else None
    for i in range(4):
        r = cpu_round(L.EXE_LITE, i + 1)
        r["mem_ps"] = mem_ps
        r["mem_diff_pp"] = round(int(r["dump"]["mem"]) - mem_ps, 2) if (r["dump"].get("mem") and mem_ps is not None) else None
        r["disk_ps"] = disk_ps
        r["disk_diff_pp"] = round(int(r["dump"]["disk"]) - disk_ps, 2) if (r["dump"].get("disk") and disk_ps is not None) else None
        rounds.append(r)
        print(f"  lite#{i+1}: cpu dump={r['dump_cpu']} pdh={r['pdh_cpu']} diff={r['diff_pp']}pp  "
              f"mem={r['dump'].get('mem')} vs {mem_ps}  disk={r['dump'].get('disk')} vs {disk_ps}")
    r = cpu_round(L.EXE_STD, 9)
    r["mem_ps"] = mem_ps
    r["mem_diff_pp"] = round(int(r["dump"]["mem"]) - mem_ps, 2) if (r["dump"].get("mem") and mem_ps is not None) else None
    r["disk_ps"] = disk_ps
    r["disk_diff_pp"] = round(int(r["dump"]["disk"]) - disk_ps, 2) if (r["dump"].get("disk") and disk_ps is not None) else None
    rounds.append(r)
    print(f"  std : cpu dump={r['dump_cpu']} pdh={r['pdh_cpu']} diff={r['diff_pp']}pp")
    OUT["cpu_mem_disk"] = {"rounds": rounds, "ps_mem_pct": mem_ps, "ps_disk_pct": disk_ps,
                           "ps_cmd": {"mem_available_mbytes": ps_avail["out"], "disk": ps_disk["out"]},
                           "mem_source": "PDH Available MBytes + GlobalMemoryStatusEx TotalPhys (CIM 被沙箱拒绝)"}
    lite_r = [x for x in rounds if x["exe"].startswith("SysMonChipLite")]
    cpu_diffs = [x["diff_pp"] for x in lite_r if x["diff_pp"] is not None]
    OUT["summary"] = {
        "lite_cpu_rounds": len(lite_r),
        "cpu_abs_diff_pp_max": round(max(abs(v) for v in cpu_diffs), 2) if cpu_diffs else None,
        "mem_abs_diff_pp_max": round(max(abs(x["mem_diff_pp"]) for x in lite_r
                                         if x["mem_diff_pp"] is not None), 2) if mem_ps is not None else None,
        "disk_abs_diff_pp_max": round(max(abs(x["disk_diff_pp"]) for x in lite_r
                                          if x["disk_diff_pp"] is not None), 2) if disk_ps is not None else None,
    }
    print("  CPU 摘要:", json.dumps(OUT["summary"], ensure_ascii=False))

    # 2) 网速量级
    print("\n[网速量级] 真实下载 + 两次 --dump + PowerShell 网卡计数")
    net = net_round(L.EXE_LITE)
    OUT["net_lite"] = net
    for pr in net.get("pairs", []):
        print(f"   pair#{pr['i']}: dump_down={pr['dump_down_Bps']} B/s  "
              f"pdh_rx={pr['pdh_rx_Bps']} B/s  ratio={pr['ratio']}  "
              f"if_seen={pr['if_seen']} inst={pr['pdh_instances']}")
    print("  ps_net(沙箱拒绝):", net["ps_net"]["err"][:80], " ratio:", net.get("ratio_min_max"))
    if not net.get("pairs") or not net.get("ratio_min_max"):
        print("  !! 网络量级未取得有效对照，记录为部分覆盖")
    OUT["final_clean"] = L.ensure_clean()
    L.save_json("lite-5-accuracy.json", OUT)
    print("最终环境:", json.dumps(OUT["final_clean"], ensure_ascii=False))


if __name__ == "__main__":
    main()
