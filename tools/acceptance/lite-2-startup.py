"""lite-2：冷启动计时（Lite vs Std 各 10 次）。

口径：
- 外部秒表 = Popen 返回到 FindWindowW 找到本进程窗口且 IsWindowVisible 为真
  （含进程创建 + Python 轮询 0.5ms 间隔误差）；
- 自报 = --trace 写出的 startup_ms（WinMain 起始 → 首帧 + ShowWindow/UpdateWindow）。
每轮结束用 `exe --quit` 收尾并确认无残留。
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_common as L

N = 10


def batch(label, exe):
    L.remove_config()          # 冷启动 = 首跑（无配置，走默认值+读注册表主题）
    runs = []
    for i in range(N):
        L.ensure_clean()
        r = L.run_trace_start(exe)
        tr = r["trace"]
        row = {
            "i": i + 1,
            "external_ms": r["external_ms"],
            "startup_ms": round(float(tr["startup_ms"]), 2) if tr.get("startup_ms") else None,
            "dpi": int(tr["dpi"]) if tr.get("dpi") else None,
            "w": int(tr["w"]) if tr.get("w") else None,
            "h": int(tr["h"]) if tr.get("h") else None,
            "pid": r["pid"],
        }
        code = L.quit_exe(exe)
        row["quit_code"] = code
        row["window_gone"] = L.find_widget() is None
        row["pids_after"] = L.chip_pids()
        runs.append(row)
        print(f"  {label} #{i+1}: ext={row['external_ms']} ms  trace={row['startup_ms']} ms "
              f"dpi={row['dpi']} {row['w']}x{row['h']} quit={code} gone={row['window_gone']}")
    ext = [r["external_ms"] for r in runs if r["external_ms"] is not None]
    sel = [r["startup_ms"] for r in runs if r["startup_ms"] is not None]
    summ = {
        "n": N, "runs": runs,
        "external": {"min": min(ext), "p50": round(statistics.median(ext), 2),
                     "max": max(ext), "mean": round(statistics.mean(ext), 2)},
        "selftrace": {"min": min(sel), "p50": round(statistics.median(sel), 2),
                      "max": max(sel), "mean": round(statistics.mean(sel), 2)},
    }
    print(f"[{label}] 外部秒表 min/P50/max = {summ['external']['min']:.2f} / "
          f"{summ['external']['p50']:.2f} / {summ['external']['max']:.2f} ms；"
          f"自报 min/P50/max = {summ['selftrace']['min']:.2f} / "
          f"{summ['selftrace']['p50']:.2f} / {summ['selftrace']['max']:.2f} ms")
    return summ


def main():
    L.ensure_dirs()
    clean0 = L.ensure_clean()
    print("初始环境:", json.dumps(clean0, ensure_ascii=False))
    out = {"order": ["lite", "std"], "n": N}
    out["lite"] = batch("lite", L.EXE_LITE)
    out["std"] = batch("std", L.EXE_STD)
    out["final_clean"] = L.ensure_clean()
    # 启动 10 次期间是否出现崩溃退出（quit_code 全 0 且窗口都出现）
    for k in ("lite", "std"):
        bad = [r for r in out[k]["runs"] if r["external_ms"] is None or r["quit_code"] != 0]
        out[k]["failures"] = bad
        print(f"[{k}] 失败轮次: {len(bad)}")
    L.save_json("lite-2-startup.json", out)


if __name__ == "__main__":
    main()
