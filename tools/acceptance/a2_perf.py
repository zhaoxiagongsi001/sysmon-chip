"""A2：长时稳定性曲线（默认 10 分钟、每 2 s 采样）。

指标：WS / 私有内存 / 句柄 / GDI / USER / 累计 CPU 时间。
产出：data/perf-10min.csv + data/perf-10min-summary.json + screenshots/verify-perf-*.png

用法：python a2_perf.py [--seconds 600] [--interval 2.0] [--label 10min]
"""
import argparse
import csv
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402


def linreg(xs, ys):
    """最小二乘斜率 + 截距 + R²。"""
    n = len(xs)
    if n < 3:
        return {"slope": None, "intercept": None, "r2": None}
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return {"slope": 0.0, "intercept": my, "r2": 0.0}
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 0.0 if ss_tot == 0 else 1.0 - ss_res / ss_tot
    return {"slope": slope, "intercept": intercept, "r2": r2}


def summarize(rows, seconds):
    ss = [r for r in rows if r["t_s"] >= 10.0] or rows
    out = {}
    for key in ("ws_mb", "priv_mb", "gdi", "user", "handles"):
        vals = [r[key] for r in rows if r[key] is not None]
        ssv = [r[key] for r in ss if r[key] is not None]
        if not vals:
            continue
        out[key] = {
            "all_min": round(min(vals), 3), "all_max": round(max(vals), 3),
            "steady_min": round(min(ssv), 3), "steady_avg": round(sum(ssv) / len(ssv), 3),
            "steady_max": round(max(ssv), 3),
        }
    # CPU：累计 CPU 秒 / 墙钟
    if rows and rows[-1]["cpu_total_s"] is not None:
        wall = rows[-1]["t_s"] - rows[0]["t_s"]
        cpu = rows[-1]["cpu_total_s"] - rows[0]["cpu_total_s"]
        ncores = os.cpu_count() or 1
        out["cpu"] = {
            "total_s": round(cpu, 4),
            "wall_s": round(wall, 1),
            "pct_one_core": round(cpu / wall * 100, 4) if wall else None,
            "pct_whole_system": round(cpu / wall * 100 / ncores, 5) if wall else None,
            "logical_cores": ncores,
        }
    # 趋势：全程斜率（每小时）+ 首尾 10% 均值差
    xs = [r["t_s"] for r in ss]
    for key in ("ws_mb", "priv_mb", "handles", "gdi", "user"):
        ys = [r[key] for r in ss if r[key] is not None]
        xv = [r["t_s"] for r in ss if r[key] is not None]
        lr = linreg(xv, ys)
        slope = lr["slope"]
        out.setdefault("trend", {})[key] = {
            "slope_per_min": None if slope is None else round(slope * 60, 4),
            "slope_per_10min": None if slope is None else round(slope * seconds, 4),
            "r2": None if lr["r2"] is None else round(lr["r2"], 3),
        }
        n = len(ys)
        if n >= 10:
            k = max(3, n // 10)
            head = ys[:k]
            tail = ys[-k:]
            out["trend"][key]["head10pct_avg"] = round(sum(head) / len(head), 3)
            out["trend"][key]["tail10pct_avg"] = round(sum(tail) / len(tail), 3)
            out["trend"][key]["delta_tail_head"] = round(
                sum(tail) / len(tail) - sum(head) / len(head), 3)
    # 泄漏判定阈值（10 分钟）
    flags = {}
    trend = out.get("trend", {})
    ws10 = trend.get("ws_mb", {}).get("slope_per_10min")
    pr10 = trend.get("priv_mb", {}).get("slope_per_10min")
    hd10 = trend.get("handles", {}).get("slope_per_10min")
    gd = trend.get("gdi", {}).get("delta_tail_head")
    us = trend.get("user", {}).get("delta_tail_head")
    flags["ws_growth"] = None if ws10 is None else ws10 > 3.0
    flags["priv_growth"] = None if pr10 is None else pr10 > 0.5
    flags["handles_growth"] = None if hd10 is None else hd10 > 10
    flags["gdi_growth"] = None if gd is None else gd > 2
    flags["user_growth"] = None if us is None else us > 2
    out["leak_flags"] = flags
    out["leak_detected"] = any(v is True for v in flags.values())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--label", default="10min")
    args = ap.parse_args()
    c.ensure_dirs()
    c.write_config(mode="desktop", theme="light")
    c.stop()
    time.sleep(0.5)

    p = c.launch()
    hwnd = c.find_widget()
    geom = c.window_rect_physical(hwnd)
    shots = {}
    s1 = os.path.join(c.SHOTS, f"verify-perf-{args.label}-start.png")
    c.grab_crop(geom, pad=24, path=s1)
    shots["start"] = os.path.basename(s1)

    rows = []
    t_start = time.perf_counter()
    cpu0 = c.proc_cpu_seconds(p.pid)
    last_cpu = cpu0
    last_t = 0.0
    next_tick = 0.0
    while True:
        next_tick += args.interval
        dt = next_tick - (time.perf_counter() - t_start)
        if dt > 0:
            time.sleep(dt)
        t = time.perf_counter() - t_start
        if t > args.seconds:
            break
        st = c.proc_stats(p.pid)
        cpu = c.proc_cpu_seconds(p.pid)
        if st is None or cpu is None:
            rows.append({"t_s": round(t, 1), "ws_mb": None, "priv_mb": None,
                         "gdi": None, "user": None, "handles": None,
                         "cpu_total_s": None, "cpu_pct_interval": None})
            if p.poll() is not None:
                print("!! process exited early at t=%.1fs code=%s" % (t, p.returncode))
                break
            continue
        dcpu = cpu - last_cpu
        dtd = t - last_t
        rows.append({
            "t_s": round(t, 1),
            "ws_mb": round(st["ws_mb"], 3),
            "priv_mb": round(st["priv_mb"], 3),
            "gdi": st["gdi"], "user": st["user"], "handles": st["handles"],
            "cpu_total_s": round(cpu, 4),
            "cpu_pct_interval": round(dcpu / dtd * 100, 3) if dtd > 0 else None,
        })
        last_cpu, last_t = cpu, t
        if len(rows) % 30 == 0:
            print(f"  t={t:6.1f}s ws={st['ws_mb']:.2f} priv={st['priv_mb']:.2f} "
                  f"hd={st['handles']} gdi={st['gdi']} usr={st['user']}", flush=True)

    s2 = os.path.join(c.SHOTS, f"verify-perf-{args.label}-end.png")
    try:
        c.grab_crop(c.window_rect_physical(c.find_widget()), pad=24, path=s2)
        shots["end"] = os.path.basename(s2)
    except Exception:
        shots["end"] = None

    summary = summarize(rows, args.seconds)
    summary.update({
        "label": args.label,
        "seconds_requested": args.seconds,
        "interval_s": args.interval,
        "samples": len(rows),
        "window_rect": geom,
        "shots": shots,
        "process_exit_code": p.returncode,
    })
    csv_path = os.path.join(c.DATA, f"perf-{args.label}.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    c.save_json(os.path.join(c.DATA, f"perf-{args.label}-summary.json"), summary)

    code = c.stop(wait_exit=p)
    summary["quit_exit_code"] = code
    summary["residual_pids_after_quit"] = c.list_pids()
    c.save_json(os.path.join(c.DATA, f"perf-{args.label}-summary.json"), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
