"""A3b：网速数值正确性对照（本机 Get-NetAdapterStatistics 被沙箱拒绝，改用等价 PDH 计数器）。

做法：
- 后台 typeperf 采 "\\Network Interface(*)\\Bytes Received/sec|Bytes Sent/sec"（逐网卡实例）；
- 同时连续跑 6 次 `SysMonChip.exe --dump`（每次内部窗口 ≈1 s，窗口右端 = dump 文件写入时刻）；
- 用 dumped 文件 mtime 对齐 typeperf 的 1 s 区间做重叠加权；
- 分别与「全部实例求和」「Wi-Fi 单实例」对照，给出误差。

产出：data/a3b-net.json + data/a3b-typeperf-net.csv
用法：python a3b_net.py
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

INST_RE = re.compile(r"\\Network Interface\((.*)\)\\Bytes (Received|Sent)/sec$")


def parse_typeperf_net(path):
    """-> (instances, rows[{ts, recv:{inst:val}, sent:{inst:val}}])"""
    instances = []
    rows = []
    if not os.path.exists(path):
        return instances, rows
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\r\n") for ln in f if ln.strip()]
    if not lines:
        return instances, rows
    header = [x.strip('"') for x in lines[0].split('","')]
    meta = []
    for i, h in enumerate(header):
        m = INST_RE.search(h)
        if m:
            meta.append((i, m.group(1), m.group(2)))
            if m.group(1) not in instances:
                instances.append(m.group(1))
    for line in lines[1:]:
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) < 2:
            continue
        try:
            ts = datetime.strptime(parts[0], "%m/%d/%Y %H:%M:%S.%f").timestamp()
        except ValueError:
            continue
        row = {"ts": ts, "recv": {}, "sent": {}}
        for i, inst, kind in meta:
            if i >= len(parts):
                continue
            try:
                v = float(parts[i])
            except ValueError:
                continue
            row["recv" if kind == "Received" else "sent"][inst] = v
        rows.append(row)
    return instances, rows


def window_avg(rows, inst, kind, win0, win1):
    num = den = 0.0
    for row in rows:
        a, b = row["ts"] - 1.0, row["ts"]
        ov = min(b, win1) - max(a, win0)
        if ov > 0 and inst in row[kind]:
            num += row[kind][inst] * ov
            den += ov
    return round(num / den) if den > 0 else None


def main():
    c.ensure_dirs()
    c.stop()
    time.sleep(0.4)
    csv_path = os.path.join(c.DATA, "a3b-typeperf-net.csv")
    if os.path.exists(csv_path):
        os.remove(csv_path)  # typeperf 对已存在的输出文件会交互式询问是否覆盖 -> 会挂住
    tp = subprocess.Popen(
        ["typeperf", r"\Network Interface(*)\Bytes Received/sec",
         r"\Network Interface(*)\Bytes Sent/sec",
         "-sc", "16", "-si", "1", "-f", "CSV", "-o", csv_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    dumps = []
    for i in range(8):
        p = c.dump_path()
        if os.path.exists(p):
            os.remove(p)
        env = dict(os.environ, APPDATA=c.APPDATA_TEST)
        t0 = time.time()
        subprocess.run([c.EXE, "--dump"], env=env, capture_output=True, timeout=20)
        t1 = time.time()
        mtime = os.path.getmtime(p) if os.path.exists(p) else None
        m = {}
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        m[k] = v.strip()
        dumps.append({"i": i + 1, "t0": t0, "t1": t1, "mtime": mtime,
                      "up": int(m.get("up", -1)), "down": int(m.get("down", -1)),
                      "if_seen": int(m.get("if_seen", -1))})
    tp.wait(timeout=40)
    instances, rows = parse_typeperf_net(csv_path)
    wifi = [x for x in instances if re.search(r"wi-?fi|wlan|ax201|wireless", x, re.I)]
    wifi_inst = wifi[0] if wifi else None

    for d in dumps:
        w0, w1 = d["mtime"] - 1.0, d["mtime"]
        d["window"] = [round(w0, 3), round(w1, 3)]
        d["tp_recv_all"] = sum(v for inst in instances
                               if (v := window_avg(rows, inst, "recv", w0, w1)) is not None)
        d["tp_sent_all"] = sum(v for inst in instances
                               if (v := window_avg(rows, inst, "sent", w0, w1)) is not None)
        d["per_inst_recv"] = {inst: window_avg(rows, inst, "recv", w0, w1)
                              for inst in instances}
        if wifi_inst:
            d["tp_recv_wifi"] = window_avg(rows, wifi_inst, "recv", w0, w1)
            d["tp_sent_wifi"] = window_avg(rows, wifi_inst, "sent", w0, w1)
            d["down_err_vs_wifi_pct"] = (round((d["down"] - d["tp_recv_wifi"]) /
                                               d["tp_recv_wifi"] * 100, 1)
                                         if d["tp_recv_wifi"] else None)
            d["up_err_vs_wifi_pct"] = (round((d["up"] - d["tp_sent_wifi"]) /
                                             d["tp_sent_wifi"] * 100, 1)
                                       if d["tp_sent_wifi"] else None)
        d["down_err_vs_all_pct"] = (round((d["down"] - d["tp_recv_all"]) /
                                          d["tp_recv_all"] * 100, 1)
                                    if d["tp_recv_all"] else None)

    def errs(key):
        vals = [d[key] for d in dumps if d.get(key) is not None]
        return {"n": len(vals), "mean": round(sum(vals) / len(vals), 1) if vals else None,
                "mae": round(sum(abs(v) for v in vals) / len(vals), 1) if vals else None,
                "max_abs": round(max(abs(v) for v in vals), 1) if vals else None}

    out = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "instances": instances,
        "wifi_instance": wifi_inst,
        "dumps": dumps,
        "errors": {
            "down_vs_wifi_pct": errs("down_err_vs_wifi_pct"),
            "up_vs_wifi_pct": errs("up_err_vs_wifi_pct"),
            "down_vs_all_pct": errs("down_err_vs_all_pct"),
        },
        "note": "typeperf 为 PDH 逐网卡实例口径；Get-NetAdapterStatistics 在本沙箱被拒（Access denied），"
                "PDH 计数器为其等价替代。窗口右端取 dump 文件写入时刻，内部窗口≈1.000 s。",
    }
    c.save_json(os.path.join(c.DATA, "a3b-net.json"), out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
