"""lite-6：风险核查（重启循环 / 快速重启 / 并发启动 / 极端读数）。

1) 模式×主题 重启循环：5 轮 × 3 模式 = 15 次重启，light/dark/auto 各出现 5 次；
2) 快速重启 10 次：启动后 ~80 ms 立刻 --quit；
3) 并发启动 3 轮 × 5 进程：只应存活 1 个实例，其余 exit 0；
4) --demo 连续 10 次；
5) 全程记录崩溃（退出码、窗口是否出现、残留进程），结束确认无残留。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_common as L

OUT = {}


def one_cycle(exe, cfg, tags):
    L.ensure_clean()
    L.write_config(**cfg)
    p, ext = L.launch(exe, ["--trace"])
    w = L.window_info()
    time.sleep(0.25)
    alive = w is not None and L.find_widget() is not None
    code = L.quit_exe(exe, settle=0.05)
    gone = L.wait_no_window(timeout=3)
    pids = L.chip_pids()
    return {"tag": tags, "visible_ms": round(ext * 1000, 2) if ext else None,
            "window": bool(w), "alive": alive, "quit_code": code,
            "gone": gone, "pids_after": pids,
            "ok": bool(w) and alive and code == 0 and gone and not any(pids.values())}


def main():
    L.ensure_dirs()
    print("初始环境:", json.dumps(L.ensure_clean(), ensure_ascii=False))

    # 1) 模式×主题 15 次
    modes = ["taskbar", "desktop", "free"]
    themes = ["light", "dark", "auto"]
    cycles = []
    for r in range(5):
        for m in modes:
            theme = themes[r % 3]
            cfg = dict(mode=m, theme=theme, x=300, y=400)
            res = one_cycle(L.EXE_LITE, cfg, f"r{r+1}-{m}-{theme}")
            cycles.append(res)
            print(f"  cycle {res['tag']}: ok={res['ok']} vis={res['visible_ms']}ms "
                  f"quit={res['quit_code']} gone={res['gone']} pids={res['pids_after']}")
    OUT["cycles"] = {"n": len(cycles), "ok": sum(1 for c in cycles if c["ok"]),
                     "fail": [c for c in cycles if not c["ok"]], "runs": cycles}

    # 2) 快速重启 10 次
    rapid = []
    for i in range(10):
        L.ensure_clean()
        L.write_config(mode="taskbar", theme="light")
        p, _ = L.launch(L.EXE_LITE, [], wait=False)
        time.sleep(0.08)
        code = L.quit_exe(L.EXE_LITE, settle=0.05)
        time.sleep(0.05)
        gone = L.find_widget() is None
        pids = L.chip_pids()
        rapid.append({"i": i + 1, "quit_code": code, "gone": gone,
                      "pids": pids, "ok": code == 0 and gone and not any(pids.values())})
        print(f"  rapid #{i+1}: quit={code} gone={gone} pids={pids}")
    OUT["rapid_restart"] = {"n": len(rapid), "ok": sum(1 for x in rapid if x["ok"]),
                            "fail": [x for x in rapid if not x["ok"]], "runs": rapid}

    # 3) 并发启动 5 个（3 轮）
    storm = []
    for r in range(3):
        L.ensure_clean()
        L.write_config(mode="taskbar", theme="light")
        procs = [L.launch(L.EXE_LITE, [], wait=False)[0] for _ in range(5)]
        time.sleep(1.2)
        pids = L.chip_pids()["lite"]
        win = L.window_info()
        # 等多余进程退出
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 5:
            if len(L.chip_pids()["lite"]) <= 1:
                break
            time.sleep(0.02)
        codes = []
        for p in procs:
            try:
                codes.append(p.wait(timeout=3))
            except Exception:
                codes.append(None)
        info = {"round": r + 1, "pids_while": pids, "pids_final": L.chip_pids(),
                "windows": 1 if win else 0, "exit_codes": codes,
                "ok": len(pids) == 1 and win is not None and len(L.chip_pids()["lite"]) <= 1}
        storm.append(info)
        L.quit_exe(L.EXE_LITE, settle=0.05)
        print(f"  storm r{r+1}: pids_while={pids} exit_codes={codes} "
              f"final={L.chip_pids()} ok={info['ok']}")
    OUT["concurrent_launch"] = {"rounds": storm,
                                "ok": sum(1 for x in storm if x["ok"])}

    # 4) --demo 连续 10 次
    demos = []
    for i in range(10):
        L.ensure_clean()
        L.write_config(mode="desktop", theme="dark" if i % 2 else "light")
        p, ext = L.launch(L.EXE_LITE, ["--demo"])
        time.sleep(0.12)
        alive = L.find_widget() is not None
        code = L.quit_exe(L.EXE_LITE, settle=0.03)
        demos.append({"i": i + 1, "visible": alive, "quit_code": code,
                      "ok": alive and code == 0})
        print(f"  demo #{i+1}: alive={alive} quit={code}")
    OUT["demo_repeat"] = {"n": len(demos), "ok": sum(1 for d in demos if d["ok"]),
                          "fail": [d for d in demos if not d["ok"]]}

    # 5) 最终残留
    L.ensure_clean()
    final = {"window": L.find_widget() is not None, "pids": L.chip_pids()}
    final["clean"] = final["window"] is False and not any(final["pids"].values())
    OUT["final"] = final
    OUT["summary"] = {
        "cycles_ok": OUT["cycles"]["ok"] == OUT["cycles"]["n"],
        "rapid_ok": OUT["rapid_restart"]["ok"] == OUT["rapid_restart"]["n"],
        "storm_ok": OUT["concurrent_launch"]["ok"] == 3,
        "demo_ok": OUT["demo_repeat"]["ok"] == 10,
        "no_residual": final["clean"],
    }
    print("\n摘要:", json.dumps(OUT["summary"], ensure_ascii=False))
    print("最终环境:", json.dumps(final, ensure_ascii=False))
    L.save_json("lite-6-stress.json", OUT)


if __name__ == "__main__":
    main()

