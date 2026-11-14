"""A1：exe 体积 + PE 基本属性 + 冷启动（10 次，--trace 自报 + 外部秒表双口径）。

用法：python a1_size_startup.py [--runs 10]
输出：data/a1-size-startup.json，控制台表格。
"""
import argparse
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

SUBSYSTEM = {2: "WINDOWS_GUI", 3: "WINDOWS_CUI", 9: "WINDOWS_GUI(9)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    args = ap.parse_args()
    c.ensure_dirs()
    c.stop()
    time.sleep(0.5)

    size = os.path.getsize(c.EXE)
    with open(c.EXE, "rb") as f:
        head = f.read(1024)
    e_lfanew = struct.unpack_from("<I", head, 0x3C)[0]
    magic = struct.unpack_from("<H", head, e_lfanew + 24)[0]
    # OptionalHeader 中 Subsystem 偏移：PE32=64 / PE32+=68
    sub_off = 68 if magic == 0x20B else 64
    subsystem = struct.unpack_from("<H", head, e_lfanew + 24 + sub_off)[0]
    nsect = struct.unpack_from("<H", head, e_lfanew + 6)[0]
    ts = struct.unpack_from("<I", head, e_lfanew + 8)[0]
    exe_info = {
        "bytes": size,
        "kb": round(size / 1024, 1),
        "mb": round(size / 1048576, 2),
        "pe_magic": hex(magic),
        "subsystem": subsystem,
        "subsystem_name": SUBSYSTEM.get(subsystem, str(subsystem)),
        "sections": nsect,
        "timestamp": ts,
        "icons": c.exe_icon_count(),
        "plan_ceiling_kb": 250,
        "over_ceiling_kb": round(size / 1024 - 250, 1),
    }

    runs = []
    for i in range(args.runs):
        c.stop()
        time.sleep(0.35)
        tp = c.trace_path()
        if os.path.exists(tp):
            os.remove(tp)
        t0 = time.perf_counter()
        env = dict(os.environ, APPDATA=c.APPDATA_TEST)
        import subprocess
        p = subprocess.Popen([c.EXE, "--trace"], env=env, close_fds=True,
                             creationflags=0x00000008)
        h = None
        external_ms = None
        while time.perf_counter() - t0 < 6.0:
            h = c.find_widget()
            if h and c.u32.IsWindowVisible(h) and c.window_pid(h) == p.pid:
                external_ms = (time.perf_counter() - t0) * 1000.0
                break
            time.sleep(0.005)
        time.sleep(0.35)
        tr = {}
        if os.path.exists(tp):
            with open(tp, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        tr[k] = v
        st = c.proc_stats(p.pid) if p.poll() is None else None
        runs.append({
            "i": i + 1,
            "external_ms_to_visible": None if external_ms is None else round(external_ms, 2),
            "trace_startup_ms": round(float(tr["startup_ms"]), 2) if "startup_ms" in tr else None,
            "trace_dpi": tr.get("dpi"),
            "trace_wxh": [tr.get("w"), tr.get("h")],
            "eye_sample_ws_mb": None if not st else round(st["ws_mb"], 2),
            "x_quit": c.stop(wait_exit=p),
        })

    def stat(key):
        vals = [r[key] for r in runs if r[key] is not None]
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        return {
            "n": n,
            "min": round(vals_sorted[0], 2),
            "median": round(vals_sorted[n // 2], 2),
            "avg": round(sum(vals_sorted) / n, 2),
            "max": round(vals_sorted[-1], 2),
        }

    out = {
        "exe": exe_info,
        "runs": runs,
        "trace_stats": stat("trace_startup_ms"),
        "external_stats": stat("external_ms_to_visible"),
        "first_run": runs[0],
        "note": "首轮为文件缓存最冷；后续轮次受 NTFS/内存缓存影响，耗时偏低。",
        "no_residual_process": len(c.list_pids()) == 0,
    }
    c.save_json(os.path.join(c.DATA, "a1-size-startup.json"), out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
