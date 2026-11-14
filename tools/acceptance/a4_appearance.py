"""A4：外观验收（三位置 × 明暗主题截图 + 几何断言 + 与 ref-widget.png 像素对照）。

产出：
  screenshots/verify-<case>.png          窗口精确裁剪（437×81 物理像素）
  screenshots/verify-<case>-context.png  窗口 + 24px 上下文
  screenshots/verify-compare-side-by-side.png / -diff.png / -blend.png
  screenshots/verify-modes-montage.png
  data/a4-appearance.json                几何/配色/像素差数字

用法：python a4_appearance.py
"""
import json
import os
import sys
import time
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

REF = os.path.join(c.SHOTS, "ref-widget.png")
W, H = 437, 81
DPI = 216


def scale(v):
    return (v * DPI + 48) // 96


CASES = [
    ("desktop-light", {"mode": "desktop", "theme": "light"}),
    ("desktop-dark", {"mode": "desktop", "theme": "dark"}),
    ("taskbar-light", {"mode": "taskbar", "theme": "light"}),
    ("taskbar-dark", {"mode": "taskbar", "theme": "dark"}),
    ("free-light", {"mode": "free", "x": 300, "y": 400, "theme": "light"}),
    ("free-dark", {"mode": "free", "x": 300, "y": 400, "theme": "dark"}),
]


def expected_rect(mode, cfg):
    work_mon, work = c.monitor_rects_physical()
    bar = c.taskbar_rect_physical()
    if mode == "desktop":
        m = scale(8)
        return (work[2] - W - m, work[3] - H - m), {"work_area": work, "margin_phys": m}
    if mode == "taskbar":
        pad = scale(4)
        bh = bar[3] - bar[1]
        return (bar[0] + pad, bar[1] + (bh - H) // 2), {"taskbar": bar, "pad": pad,
                                                        "bar_h": bh}
    return (cfg["x"], cfg["y"]), {"configured": [cfg["x"], cfg["y"]]}


def font(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def dominant_color(im, exclude_corner=12):
    a = np.array(im.convert("RGB"))
    a = a[exclude_corner:a.shape[0] - exclude_corner, exclude_corner:a.shape[1] - exclude_corner]
    cnt = Counter(map(tuple, a.reshape(-1, 3)))
    best = cnt.most_common(1)[0][0]
    return [int(x) for x in best], cnt


def ink_mask(im, bg, thr=40):
    a = np.array(im.convert("RGB")).astype(np.int16)
    d = np.abs(a - np.array(bg, dtype=np.int16)).max(axis=2)
    return d > thr, a


def clusters(profile, min_gap=5, min_len=2):
    """一维墨迹剖面 -> [(start,end)]，空白 >= min_gap 视为分隔。"""
    idx = np.where(profile > 0)[0]
    if len(idx) == 0:
        return []
    out = []
    s = prev = int(idx[0])
    for x in idx[1:]:
        x = int(x)
        if x - prev - 1 >= min_gap:
            if prev - s + 1 >= min_len:
                out.append((s, prev))
            s = x
        prev = x
    if prev - s + 1 >= min_len:
        out.append((s, prev))
    return out


def bbox(mask):
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return {"x0": int(xs.min()), "y0": int(ys.min()),
            "x1": int(xs.max()), "y1": int(ys.max())}


def compare(ref_im, our_im):
    res = {}
    ref = np.array(ref_im.convert("RGB")).astype(np.int16)
    our = np.array(our_im.convert("RGB")).astype(np.int16)
    if ref.shape != our.shape:
        return {"error": f"shape mismatch ref={ref.shape} ours={our.shape}"}
    diff = np.abs(ref - our)
    res["mae_all"] = round(float(diff.mean()), 2)
    res["mae_channels"] = [round(float(diff[:, :, i].mean()), 2) for i in range(3)]
    res["px_gt16"] = round(float((diff.max(axis=2) > 16).mean() * 100), 2)
    top = diff[:40]
    res["mae_top40"] = round(float(top.mean()), 2)

    ref_bg, _ = dominant_color(ref_im)
    our_bg, _ = dominant_color(our_im)
    res["bg_ref"] = list(ref_bg)
    res["bg_ours"] = list(our_bg)
    res["bg_diff"] = [int(our_bg[i]) - int(ref_bg[i]) for i in range(3)]

    # 圆角区域（窗口外，露出桌面）不参与墨迹/像素统计：屏蔽四角 12×12
    corner = np.zeros(ref.shape[:2], dtype=bool)
    k = 12
    for ys in (slice(0, k), slice(-k, None)):
        for xs in (slice(0, k), slice(-k, None)):
            corner[ys, xs] = True
    ref_ink, _ = ink_mask(ref_im, ref_bg)
    our_ink, _ = ink_mask(our_im, our_bg)
    ref_ink &= ~corner
    our_ink &= ~corner
    res["ink_bbox_ref"] = bbox(ref_ink)
    res["ink_bbox_ours"] = bbox(our_ink)
    res["ink_px_ref"] = int(ref_ink.sum())
    res["ink_px_ours"] = int(our_ink.sum())
    inter = int((ref_ink & our_ink).sum())
    union = int((ref_ink | our_ink).sum())
    res["ink_iou"] = round(inter / union, 4) if union else None

    # 背景区（两边都不是墨迹、非圆角）的平均绝对差：背景/底色是否一致
    bgmask = ~ref_ink & ~our_ink & ~corner
    res["mae_background_only"] = round(float(diff[bgmask].mean()), 2) if bgmask.any() else None
    res["bg_ratio_ref"] = round(float((~ref_ink & ~corner).mean()) * 100, 2)
    res["bg_ratio_ours"] = round(float((~our_ink & ~corner).mean()) * 100, 2)

    # 行/列文本包围盒
    ref_rows = clusters(ref_ink.sum(axis=1) > 0, min_gap=3, min_len=2)
    our_rows = clusters(our_ink.sum(axis=1) > 0, min_gap=3, min_len=2)
    res["rows_ref"] = ref_rows
    res["rows_ours"] = our_rows
    ref_cols = clusters((ref_ink[:40].sum(axis=0) > 0).astype(int), min_gap=6, min_len=2)
    our_cols = clusters((our_ink[:40].sum(axis=0) > 0).astype(int), min_gap=6, min_len=2)
    res["cols_top_ref"] = ref_cols
    res["cols_top_ours"] = our_cols
    n = min(len(ref_cols), len(our_cols))
    pairs = []
    for i in range(n):
        r0, r1 = ref_cols[i]
        o0, o1 = our_cols[i]
        pairs.append({"i": i, "ref": [r0, r1], "ours": [o0, o1],
                      "dx0": o0 - r0, "dx1": o1 - r1,
                      "dw": (o1 - o0) - (r1 - r0)})
    res["col_pairs"] = pairs
    res["col_alignment_max_abs_dx"] = max([abs(p["dx0"]) for p in pairs], default=None)
    if pairs:
        res["col_alignment_mean_abs_dx"] = round(
            sum(abs(p["dx0"]) for p in pairs) / len(pairs), 2)
        res["col_width_ratio_mean"] = round(
            sum((p["ours"][1] - p["ours"][0]) / max(1, p["ref"][1] - p["ref"][0])
                for p in pairs) / len(pairs), 3)

    row_pairs = []
    for i in range(min(len(ref_rows), len(our_rows))):
        r0, r1 = ref_rows[i]
        o0, o1 = our_rows[i]
        row_pairs.append({"i": i, "ref": [r0, r1], "ours": [o0, o1],
                          "dy0": o0 - r0, "dy1": o1 - r1,
                          "dh": (o1 - o0) - (r1 - r0)})
    res["row_pairs"] = row_pairs
    if row_pairs:
        res["row_alignment_max_abs_dy"] = max(abs(p["dy0"]) for p in row_pairs)
        res["row_height_ratio_mean"] = round(
            sum((p["ours"][1] - p["ours"][0]) / max(1, p["ref"][1] - p["ref"][0])
                for p in row_pairs) / len(row_pairs), 3)

    # 设计稿配色是否能在参考图里找到：每个设计色的最近邻色距
    DESIGN_LIGHT = {"label": (0, 0, 0), "up": (253, 80, 93), "down": (22, 139, 253),
                    "green": (24, 120, 62), "amber": (166, 77, 0), "red": (200, 30, 30),
                    "bg": (243, 243, 243)}
    ref_px = np.array(ref_im.convert("RGB")).reshape(-1, 3).astype(np.int16)
    our_px = np.array(our_im.convert("RGB")).reshape(-1, 3).astype(np.int16)
    res["design_palette_nearest"] = {}
    for name, col in DESIGN_LIGHT.items():
        cvec = np.array(col, dtype=np.int16)
        dref = int(np.abs(ref_px - cvec).max(axis=1).min())
        dour = int(np.abs(our_px - cvec).max(axis=1).min())
        res["design_palette_nearest"][name] = {"design": list(col),
                                               "dist_ref": dref, "dist_ours": dour}
    return res


def make_composites(ref_im, our_im):
    draw_pairs = [("参考 MangoDisk 资源条", ref_im), ("SysMonChip 复刻（desktop-light）", our_im)]
    label_h = 26
    im2 = Image.new("RGB", (W * 2 + 16, len(draw_pairs) * (label_h + H * 2 + 6) + 8),
                    (255, 255, 255))
    d = ImageDraw.Draw(im2)
    f = font(16)
    y = 4
    for i, (label, im) in enumerate(draw_pairs):
        d.text((8, y), label, fill=(20, 20, 20), font=f)
        y += label_h
        im2.paste(im.resize((W * 2, H * 2), Image.NEAREST), (8, y))
        y += H * 2 + 6
    out = os.path.join(c.SHOTS, "verify-compare-side-by-side.png")
    im2.save(out)

    ref = np.array(ref_im.convert("RGB")).astype(np.int16)
    our = np.array(our_im.convert("RGB")).astype(np.int16)
    diff = np.abs(ref - our).astype(np.uint8)
    amp = np.clip(diff.astype(np.int16) * 3, 0, 255).astype(np.uint8)
    heat = Image.fromarray(amp).resize((W * 2, H * 2), Image.NEAREST)
    d2 = ImageDraw.Draw(heat)
    d2.text((4, 2), "逐像素 |Δ| ×3 放大（黑=一致，越亮差异越大）", fill=(255, 255, 255), font=f)
    heat.save(os.path.join(c.SHOTS, "verify-compare-diff.png"))

    blend = Image.blend(ref_im, our_im, 0.5)
    blend.resize((W * 2, H * 2), Image.NEAREST).save(
        os.path.join(c.SHOTS, "verify-compare-blend.png"))
    return out


def montage(case_paths):
    label_h = 24
    im = Image.new("RGB", (W * 2 + 16, (H * 2 + label_h) * len(case_paths) + 8),
                   (250, 250, 250))
    d = ImageDraw.Draw(im)
    f = font(15)
    y = 4
    for name, path in case_paths:
        d.text((6, y + 4), name, fill=(10, 10, 10), font=f)
        y += label_h
        img = Image.open(path).convert("RGB").resize((W * 2, H * 2), Image.NEAREST)
        im.paste(img, (8, y))
        y += H * 2 + 2
    out = os.path.join(c.SHOTS, "verify-modes-montage.png")
    im.save(out)
    return out


def main():
    c.ensure_dirs()
    c.stop()
    time.sleep(0.4)
    results = {"cases": [], "expected": {}, "dpi_scale": c.dpi_scale(),
               "screen_physical": c.screen_physical(),
               "screenshot_size": list(c.grab().size)}
    case_shots = []
    for name, cfg in CASES:
        c.write_config(**cfg)
        c.stop()
        time.sleep(0.3)
        p = c.launch()
        time.sleep(1.5)  # 等首帧 + 第 1 个定时器刷新
        info = c.widget_info()
        if info is None:
            results["cases"].append({"case": name, "error": "no window"})
            c.stop(wait_exit=p)
            continue
        rect = info["rect"]
        exp, exp_detail = expected_rect(cfg["mode"], cfg)
        dx, dy = rect[0] - exp[0], rect[1] - exp[1]
        shot = os.path.join(c.SHOTS, f"verify-{name}.png")
        crop = c.grab_crop(rect, pad=0, path=shot)
        ctx = os.path.join(c.SHOTS, f"verify-{name}-context.png")
        c.grab_crop(rect, pad=24, path=ctx)
        case_shots.append((name, shot))
        bg, _ = dominant_color(crop)
        case = {
            "case": name, "config": cfg, "rect": rect,
            "expected": list(exp), "expected_detail": exp_detail,
            "delta": [dx, dy], "size": [rect[2] - rect[0], rect[3] - rect[1]],
            "visible": info["visible"], "style": hex(info["style"]),
            "exstyle": hex(info["exstyle"]),
            "topmost": bool(info["exstyle"] & 0x0008),
            "toolwindow": bool(info["exstyle"] & 0x0080),
            "bg_dominant": list(bg),
            "shot": os.path.basename(shot),
            "quit_exit": c.stop(wait_exit=p),
        }
        results["cases"].append(case)
        print(f"{name:14s} rect={rect} exp={exp} d=({dx:+d},{dy:+d}) bg={bg}")

    # 参考图对照：desktop-light 必须是 437×81 才能逐像素比
    ref_path = REF
    our_path = os.path.join(c.SHOTS, "verify-desktop-light.png")
    if os.path.exists(ref_path) and os.path.exists(our_path):
        ref_im = Image.open(ref_path).convert("RGB")
        our_im = Image.open(our_path).convert("RGB")
        if ref_im.size != our_im.size:
            results["compare_error"] = f"size {ref_im.size} vs {our_im.size}"
        else:
            results["compare"] = compare(ref_im, our_im)
            results["compare"]["side_by_side"] = os.path.basename(make_composites(ref_im, our_im))
    results["montage"] = os.path.basename(montage(case_shots)) if case_shots else None
    results["residual_pids"] = c.list_pids()
    c.save_json(os.path.join(c.DATA, "a4-appearance.json"), results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
