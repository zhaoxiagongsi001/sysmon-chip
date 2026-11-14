"""lite-3：功能对照（Lite vs Std）。

覆盖：默认位置、三模式 geometry、明暗主题底色、单实例、--quit、--dump、--trace、
--demo（截图 + 存活）、配置持久化、--selftest（lite 特有配置往返）。
每步之前 ensure_clean()，之后用 --quit 收尾；结束时确认无残留进程。
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_common as L

RESULTS = {}
SCREEN = L.screen_physical()
WORK = L.monitor_rects_physical()
TASKBAR = L.taskbar_rect_physical()
SHOT = lambda name: os.path.join(L.SHOTS, name)


def rec(section, key, value):
    RESULTS.setdefault(section, {})[key] = value
    print(f"  [{section}] {key}: {json.dumps(value, ensure_ascii=False)}")


def launch_rect(exe, settle=0.35):
    L.ensure_clean()
    p, ext = L.launch(exe)
    time.sleep(settle)
    info = L.window_info()
    return p, info


def close(exe):
    code = L.quit_exe(exe)
    time.sleep(0.05)
    return {"quit_code": code, "window_gone": L.find_widget() is None,
            "pids": L.chip_pids()}


# ---------------------------------------------------------------- 1 默认位置
def t_default_position():
    print("\n[1] 默认位置（无配置文件）")
    exp = (9, 2065, 454, 2146)   # 工单预期（225% / 445×81）
    for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
        L.ensure_clean()
        L.remove_config()
        p, info = launch_rect(exe)
        rect = info["rect"] if info else None
        crop = L.grab_crop(rect, pad=0, path=SHOT(f"lite-verify-default-{label}.png")) if rect else None
        c = close(exe)
        rec("default_position", label, {
            "rect": rect, "size": [rect[2] - rect[0], rect[3] - rect[1]] if rect else None,
            "expected_rect": list(exp),
            "dx_right_vs_ticket": rect[2] - exp[2] if rect else None,
            "dy_bottom": rect[3] - exp[3] if rect else None,
            "crop_file": f"lite-verify-default-{label}.png",
            "quit": c})
        print(f"   {label}: rect={rect}  size={rect[2]-rect[0]}x{rect[3]-rect[1]}")


# ---------------------------------------------------------------- 2 三模式
def t_modes():
    print("\n[2] 三模式 geometry")
    cases = [("taskbar", dict(mode="taskbar", theme="light")),
             ("desktop", dict(mode="desktop", theme="light")),
             ("free", dict(mode="free", theme="light", x=300, y=400))]
    for mode, cfg in cases:
        for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
            L.ensure_clean()
            L.write_config(**cfg)
            p, info = launch_rect(exe)
            rect = info["rect"] if info else None
            shot = None
            if rect:
                name = f"lite-verify-mode-{mode}-{label}.png"
                L.grab_crop(rect, pad=8, path=SHOT(name))
                shot = name
            c = close(exe)
            rec("modes", f"{mode}-{label}", {"rect": rect, "crop_file": shot, "quit": c})
    # 期望校验
    lite = {k.split("-")[0]: RESULTS["modes"][k]["rect"] for k in RESULTS["modes"]
            if k.endswith("-lite")}
    checks = {
        "taskbar_tickets": {"got": lite.get("taskbar"), "expect_left_x": 9,
                            "expect_width": 446, "expect_bottom_margin": 14},
        "desktop_right_aligned": {"got": lite.get("desktop"),
                                  "expect_right": SCREEN[0], "expect_bottom": TASKBAR[1]},
        "free_exact": {"got": lite.get("free"), "expect": [300, 400, 746, 481],
                       "expect_origin_from_config": True},
    }
    rec("modes_checks", "screen", list(SCREEN))
    rec("modes_checks", "taskbar", list(TASKBAR) if TASKBAR else None)
    rec("modes_checks", "work", [list(w) for w in WORK])
    for k, v in checks.items():
        rec("modes_checks", k, v)
    # lite vs std 差异
    for mode in ("taskbar", "desktop", "free"):
        a = RESULTS["modes"][f"{mode}-lite"]["rect"]
        b = RESULTS["modes"][f"{mode}-std"]["rect"]
        rec("modes", f"{mode}-diff_lite_std", None if (a is None or b is None)
            else [b[i] - a[i] for i in range(4)])


# ---------------------------------------------------------------- 3 明暗主题
def t_themes():
    print("\n[3] 明暗主题底色")
    expect = {"light": (243, 243, 243), "dark": (32, 32, 32)}
    for theme in ("light", "dark"):
        for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
            L.ensure_clean()
            L.write_config(mode="desktop", theme=theme)
            p, info = launch_rect(exe, settle=0.5)
            rect = info["rect"] if info else None
            res = {"rect": rect}
            if rect:
                name = f"lite-verify-theme-{theme}-{label}.png"
                crop = L.grab_crop(rect, path=SHOT(name)).convert("RGB")
                w, h = crop.size
                px = crop.load()
                from collections import Counter
                cnt = Counter(crop.getdata())
                res["mode_color"] = list(cnt.most_common(1)[0][0])
                res["mode_color_share"] = round(cnt.most_common(1)[0][1] / (w * h), 4)
                res["samples"] = {"top_center": list(px[w // 2, 1]),
                                  "bottom_center": list(px[w // 2, h - 2]),
                                  "right_mid": list(px[w - 3, h // 2])}
                res["expect_bg"] = list(expect[theme])
                res["bg_ok"] = all(list(res["samples"][k]) == list(expect[theme])
                                   for k in res["samples"])
                res["crop_file"] = name
                # 背景占比（宽松：非文本像素应 > 60%）
                res["bg_share_ge_60pct"] = res["mode_color_share"] >= 0.60
            c = close(exe)
            res["quit"] = c
            rec("themes", f"{theme}-{label}", res)
            print(f"   {theme}-{label}: mode_color={res.get('mode_color')} "
                  f"share={res.get('mode_color_share')} samples_ok={res.get('bg_ok')}")


# ---------------------------------------------------------------- 4 单实例 / 5 --quit
def t_single_and_quit():
    print("\n[4] 单实例")
    for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
        L.ensure_clean()
        L.write_config(mode="taskbar", theme="light")
        p, info = launch_rect(exe)
        pid1 = info["pid"] if info else None
        t0 = time.perf_counter()
        try:
            r = subprocess.run([exe], env=L._env(), capture_output=True, timeout=6)
            code, dt = r.returncode, time.perf_counter() - t0
        except subprocess.TimeoutExpired:
            code, dt = None, time.perf_counter() - t0
        pids = L.chip_pids()[label]
        info2 = L.window_info()
        c = close(exe)
        rec("single_instance", label, {
            "first_pid": pid1, "second_exit_code": code,
            "second_wall_s": round(dt, 3), "one_window": info2 is not None,
            "pids_while_running": pids, "window_still_visible": bool(info2 and info2["visible"]),
            "quit": c})
        print(f"   {label}: 2nd exit={code} in {dt*1000:.0f} ms; pids={pids}")

    print("\n[5] --quit")
    for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
        L.ensure_clean()
        p, info = launch_rect(exe)
        pid = info["pid"] if info else None
        t0 = time.perf_counter()
        r = subprocess.run([exe, "--quit"], env=L._env(), capture_output=True, timeout=8)
        dt = time.perf_counter() - t0
        gone = L.wait_no_window(timeout=4)
        time.sleep(0.7)
        pids = L.chip_pids()
        alive = pid in pids[label] if pid else None
        # 再次 --quit（幂等）
        r2 = subprocess.run([exe, "--quit"], env=L._env(), capture_output=True, timeout=8)
        rec("quit", label, {
            "pid": pid, "quit_code": r.returncode, "quit_wall_s": round(dt, 3),
            "window_gone": gone, "pid_alive_after": alive,
            "second_quit_code": r2.returncode, "pids_after": pids})
        print(f"   {label}: code={r.returncode} wall={dt*1000:.0f} ms gone={gone} "
              f"alive={alive} pids={pids}")


# ---------------------------------------------------------------- 6 --dump / 7 --trace
def t_dump_trace():
    print("\n[6] --dump")
    for mode in ("taskbar", "free"):
        for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
            L.ensure_clean()
            L.write_config(mode=mode, theme="light", x=300, y=400)
            r = L.run_dump(exe)
            m = r["map"]
            rec("dump", f"{mode}-{label}", {
                "exit_code": r["code"], "wall_s": r["wall_s"],
                "keys": sorted(m.keys()),
                "key_set_ok": sorted(m.keys()) == sorted(
                    ["cpu", "mem", "disk", "up", "down", "if_seen", "mode"]),
                "mode_field": m.get("mode"), "mode_ok": m.get("mode") == mode,
                "values": m, "raw": r["raw"]})
            print(f"   {mode}-{label}: code={r['code']} {m}")

    print("\n[7] --trace 字段")
    for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
        L.ensure_clean()
        L.write_config(mode="taskbar", theme="light")
        tr = L.run_trace_start(exe)
        t = tr["trace"]
        L.quit_exe(exe)
        rec("trace", label, {"external_ms": tr["external_ms"], "raw": tr["raw_trace"],
                             "fields": sorted(t.keys()),
                             "dpi": t.get("dpi"), "w": t.get("w"), "h": t.get("h"),
                             "dpi_ok": t.get("dpi") == "216",
                             "wh_ok": (t.get("w"), t.get("h")) == ("446", "81")})
        print(f"   {label}: {t} ext={tr['external_ms']} ms")


# ---------------------------------------------------------------- 8 --demo
def t_demo():
    print("\n[8] --demo 最坏读数（存活 + 截图）")
    for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
        L.ensure_clean()
        L.write_config(mode="desktop", theme="light")
        p, ext = L.launch(exe, ["--demo"])
        time.sleep(1.6)   # 等 1s 定时器把 demo 读数刷上屏
        info = L.window_info()
        alive = info is not None
        name = f"lite-verify-demo-{label}.png"
        if info:
            L.grab_crop(info["rect"], path=SHOT(name))
        stats = L.proc_stats(info["pid"]) if info else None
        c = close(exe)
        rec("demo", label, {"alive_after_1.6s": alive, "window": info and info["rect"],
                            "proc": stats, "crop_file": name, "quit": c})
        print(f"   {label}: alive={alive} rect={info and info['rect']} proc={stats}")


# ---------------------------------------------------------------- 9 selftest / 10 持久化
def t_selftest_and_persist():
    print("\n[9] --selftest（lite 特有：配置写/读往返）")
    L.ensure_clean()
    L.clear_temp("sysmonchip-selftest.txt")
    before = L.read_config_text()
    r = L.run_cli(L.EXE_LITE, ["--selftest"])
    time.sleep(0.05)
    txt = L.read_temp("sysmonchip-selftest.txt")
    m = L.parse_kv(txt)
    cfgd = L.read_config_dict()
    window_after = L.find_widget()
    rec("selftest", "lite", {
        "exit_code": r["code"], "wall_s": r["wall_s"], "raw": txt,
        "fields": m, "roundtrip_ok": m.get("config_roundtrip") == "ok",
        "mode": m.get("mode"), "x": m.get("x"), "y": m.get("y"), "theme": m.get("theme"),
        "config_after": cfgd,
        "config_matches": (cfgd.get("mode") == "free" and cfgd.get("x") == "1234"
                           and cfgd.get("y") == "567" and cfgd.get("theme") == "dark"),
        "window_created": window_after is not None})
    print(f"   selftest={txt and txt.strip()} config={cfgd}")
    # 用 selftest 落盘的配置启动，验证配置真的生效（free 模式 → (1234,567)）
    L.ensure_clean()
    p, info = launch_rect(L.EXE_LITE)
    rect_after_selftest = info["rect"] if info else None
    c1 = close(L.EXE_LITE)
    rec("selftest", "lite_config_effective", {"rect": rect_after_selftest,
                                              "expect": [1234, 567, 1680, 648],
                                              "quit": c1})
    print(f"   selftest 配置启动: rect={rect_after_selftest}")

    print("\n[10] 配置持久化（写 config → 重启仍生效）")
    for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
        L.ensure_clean()
        L.write_config(mode="free", x=300, y=400, theme="dark", interval=2000)
        p, info1 = launch_rect(exe, settle=0.6)
        rect1 = info1["rect"] if info1 else None
        c1 = close(exe)
        cfg1 = L.read_config_dict()
        L.ensure_clean()
        p, info2 = launch_rect(exe, settle=0.6)
        rect2 = info2["rect"] if info2 else None
        # 主题应为 dark：采样背景
        dark_bg = None
        if info2:
            cr = L.grab_crop(info2["rect"]).convert("RGB")
            dark_bg = list(cr.getpixel((cr.width // 2, 1)))
        c2 = close(exe)
        rec("persist", label, {
            "config_written": {"mode": "free", "x": "300", "y": "400",
                               "theme": "dark", "interval": "2000"},
            "config_after_run": cfg1,
            "rect_run1": rect1, "rect_run2": rect2,
            "rect_stable": rect1 == rect2,
            "expect_origin": [300, 400],
            "dark_bg_sample": dark_bg, "theme_effective": dark_bg == [32, 32, 32],
            "quit": [c1, c2]})
        print(f"   {label}: rect1={rect1} rect2={rect2} theme_sample={dark_bg} cfg={cfg1}")


def main():
    L.ensure_dirs()
    print("初始环境:", json.dumps(L.ensure_clean(), ensure_ascii=False))
    t_default_position()
    t_modes()
    t_themes()
    t_single_and_quit()
    t_dump_trace()
    t_demo()
    t_selftest_and_persist()
    # 收尾：恢复默认配置，确认无残留
    L.ensure_clean()
    L.write_config()
    final = L.ensure_clean()
    rec("final", "clean", final)
    rec("final", "config_restored", L.read_config_dict())
    L.save_json("lite-3-functional.json", RESULTS)
    print("\n最终环境:", json.dumps(final, ensure_ascii=False))


if __name__ == "__main__":
    main()
