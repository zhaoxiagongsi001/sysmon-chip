"""lite-7：Lite 版 10 分钟稳定性（每 2 s 采样，判泄漏）。

采样：工作集 WS / 私有内存 / GDI / USER / 句柄 / 累计 CPU 时间 / 窗口存活。
判定：
- 线性回归斜率（每小时）与首尾 10% 均值差；
- GDI/USER/句柄：全程增长 ≤2 判无泄漏；WS 斜率在噪声量级（<0.1 MB/min）判平稳；
- CPU：累计 CPU 时间差 / 墙钟 → 单核占用百分比。
结束时 --quit 收尾并确认无残留。CSV 逐行落盘，防中断丢数据。
"""
import csv
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_common as L

DURATION_S = 600
INTERVAL_S = 2.0
N = int(DURATION_S / INTERVAL_S)          # 300 拍
CSV_PATH = os.path.join(L.DATA, "lite-7-stability.csv")
OUT = {}


def slope_per_hour(xs, ys):
    """最小二乘斜率（y 单位/小时）。"""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den) * 3600.0


def main():
    L.ensure_dirs()
    L.ensure_clean()
    L.write_config(mode="taskbar", theme="light")
    p, ext = L.launch(L.EXE_LITE, ["--trace"])
    info = L.window_info()
    if not info:
        raise SystemExit("lite 未启动窗口")
    pid = info["pid"]
    rect = info["rect"]
    t0 = time.perf_counter()
    cpu0 = L.proc_cpu_seconds(pid)
    rows = []
    shot_start = f"lite-verify-perf-start.png"
    shot_end = f"lite-verify-perf-end.png"
    L.grab_crop(rect, path=os.path.join(L.SHOTS, shot_start))
    print(f"启动 pid={pid} rect={rect} trace={L.read_temp('sysmonchip-trace.txt')!r}")
    os.makedirs(L.DATA, exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["i", "t_s", "ws_mb", "priv_mb", "gdi", "user", "handles",
                    "cpu_cum_s", "cpu_pct_avg", "window_alive"])
        for i in range(N):
            target = t0 + (i + 1) * INTERVAL_S
            while time.perf_counter() < target:
                time.sleep(max(0.0, min(0.05, target - time.perf_counter())))
            st = L.proc_stats(pid)
            cpu = L.proc_cpu_seconds(pid)
            alive = L.find_widget() is not None
            t = time.perf_counter() - t0
            if st is None:
                w.writerow([i, round(t, 3), "", "", "", "", "", "", "", alive])
                f.flush()
                break
            cpu_delta = (cpu - cpu0) if (cpu is not None and cpu0 is not None) else None
            row = {"i": i, "t_s": t, "ws_mb": st["ws_mb"], "priv_mb": st["priv_mb"],
                   "gdi": st["gdi"], "user": st["user"], "handles": st["handles"],
                   "cpu_cum_s": cpu, "cpu_pct_avg": (cpu_delta / t * 100.0)
                   if (cpu_delta is not None and t > 0) else None,
                   "window_alive": alive}
            rows.append(row)
            w.writerow([i, round(t, 3), st["ws_mb"], st["priv_mb"], st["gdi"],
                        st["user"], st["handles"],
                        round(cpu, 4) if cpu is not None else "",
                        round(row["cpu_pct_avg"], 4) if row["cpu_pct_avg"] else "",
                        alive])
            f.flush()
            if (i + 1) % 30 == 0:
                print(f"  {i+1}/{N} 拍  WS={st['ws_mb']}MB gdi={st['gdi']} "
                      f"user={st['user']} handles={st['handles']} "
                      f"cpu_itv={row['cpu_pct_avg']:.3f}% alive={alive}")
            if not alive:
                print("  !! 窗口中途消失（进程异常）")
                break
    wall = time.perf_counter() - t0
    cpu1 = L.proc_cpu_seconds(pid)
    alive_end = L.find_widget() is not None
    if alive_end:
        L.grab_crop(rect, path=os.path.join(L.SHOTS, shot_end))
    code = L.quit_exe(L.EXE_LITE)
    time.sleep(0.3)
    pids_after = L.chip_pids()
    OUT["meta"] = {"duration_s": round(wall, 2), "samples": len(rows), "pid": pid,
                   "rect": rect, "alive_end": alive_end,
                   "quit_code": code, "pids_after": pids_after,
                   "shots": [shot_start, shot_end]}
    valid = [r for r in rows if r["ws_mb"] is not None]
    if valid:
        xs = [r["i"] for r in valid]
        def stats(key):
            vs = [r[key] for r in valid]
            return {"min": round(min(vs), 4), "avg": round(statistics.mean(vs), 4),
                    "max": round(max(vs), 4),
                    "slope_per_hour": round(slope_per_hour(xs, vs), 4)}
        n10 = max(1, len(valid) // 10)
        first = valid[:n10]
        last = valid[-n10:]
        def tail(key):
            a = statistics.mean(r[key] for r in first)
            b = statistics.mean(r[key] for r in last)
            return {"first10_avg": round(a, 4), "last10_avg": round(b, 4),
                    "delta": round(b - a, 4)}
        cpu_total = (cpu1 - cpu0) if (cpu1 is not None and cpu0 is not None) else None
        OUT["metrics"] = {k: stats(k) for k in ("ws_mb", "priv_mb", "gdi", "user", "handles")}
        OUT["tails"] = {k: tail(k) for k in ("ws_mb", "priv_mb", "gdi", "user", "handles")}
        OUT["cpu"] = {"total_cpu_s": round(cpu_total, 4) if cpu_total is not None else None,
                      "wall_s": round(wall, 2),
                      "single_core_pct": round(cpu_total / wall * 100.0, 4)
                      if cpu_total is not None else None,
                      "per_2s_pct_min": round(min(r["cpu_pct_avg"] for r in valid if r["cpu_pct_avg"]), 4),
                      "per_2s_pct_max": round(max(r["cpu_pct_avg"] for r in valid if r["cpu_pct_avg"]), 4)}
        # 泄漏判定
        h, g, u = OUT["metrics"]["handles"], OUT["metrics"]["gdi"], OUT["metrics"]["user"]
        d_h = OUT["tails"]["handles"]["delta"]
        d_g = OUT["tails"]["gdi"]["delta"]
        d_u = OUT["tails"]["user"]["delta"]
        ws_slope = OUT["metrics"]["ws_mb"]["slope_per_hour"]
        verdict = {
            "handles_growth": h["slope_per_hour"],
            "gdi_growth_per_hour": g["slope_per_hour"],
            "user_growth_per_hour": u["slope_per_hour"],
            "handle_tail_delta": d_h, "gdi_tail_delta": d_g, "user_tail_delta": d_u,
            "ws_slope_mb_per_hour": ws_slope,
            # 判据：句柄/GDI/USER 首尾差 ≤2，且 WS 斜率 < 12 MB/h（10 分钟 <2MB 漂移）
            "no_leak": (abs(d_h) <= 2 and abs(d_g) <= 2 and abs(d_u) <= 2
                        and abs(ws_slope) < 12.0),
            "alive_all": all(r["window_alive"] for r in valid),
            "quit_ok": code == 0,
            "no_residual": not any(pids_after.values()),
        }
        OUT["verdict"] = verdict
        print("\n== 10 分钟稳定性摘要 ==")
        for k in ("ws_mb", "priv_mb", "gdi", "user", "handles"):
            m = OUT["metrics"][k]
            t = OUT["tails"][k]
            print(f"  {k}: min={m['min']} avg={m['avg']} max={m['max']} "
                  f"slope/h={m['slope_per_hour']} tail_delta={t['delta']}")
        print(f"  CPU: {OUT['cpu']['single_core_pct']}% 单核（{OUT['cpu']['total_cpu_s']}s / "
              f"{OUT['cpu']['wall_s']}s），2s 区间 {OUT['cpu']['per_2s_pct_min']}–"
              f"{OUT['cpu']['per_2s_pct_max']}%")
        print(f"  结论: no_leak={verdict['no_leak']} alive_all={verdict['alive_all']} "
              f"quit_ok={verdict['quit_ok']} no_residual={verdict['no_residual']}")
    L.save_json("lite-7-stability.json", OUT)
    print("CSV:", CSV_PATH)
    print("最终环境:", json.dumps(L.ensure_clean(), ensure_ascii=False))


if __name__ == "__main__":
    main()
