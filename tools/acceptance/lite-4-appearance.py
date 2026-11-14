"""lite-4：界面一致性（Lite vs Std 逐像素；与 ref-widget.png 布局对比）。

方法：
1) --demo 固定最坏读数（cpu=100 mem=99 disk=100 up=999999 down=12345678），
   两版在完全相同配置下各截一张 chip，逐像素比较（容差 ≤2/255）。
2) 实时读数各截一张：读数本身不同，只统计差异像素占比与差异区域，
   并单独比较「标签行」这种与读数无关的区域。
3) ref-widget.png（437×81，MangoDisk 参考条）与本工具（446×81）比较：
   底色、文字行带、四列起始位置（归一化 + 绝对），给列位偏差。
产物：screenshots/lite-verify-pixel-*.png, lite-verify-ref-*.png；data/lite-4-appearance.json。
"""
import json
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_common as L

REF = os.path.join(L.SHOTS, "ref-widget.png")
SHOT = lambda n: os.path.join(L.SHOTS, n)
OUT = {}


def capture(exe, mode="desktop", theme="light", args=("--demo",), settle=1.7,
            name=None):
    L.ensure_clean()
    L.write_config(mode=mode, theme=theme, x=300, y=400)
    p, ext = L.launch(exe, args)
    time.sleep(settle)
    info = L.window_info()
    crop = None
    if info:
        path = SHOT(name) if name else None
        crop = L.grab_crop(info["rect"], path=path)
        crop = crop.convert("RGB")
    code = L.quit_exe(exe)
    return {"crop": crop, "rect": info["rect"] if info else None,
            "pid": info["pid"] if info else None, "quit_code": code,
            "file": name}


def compare(a, b, tag):
    """逐像素比较两张 RGB，返回统计并保存 diff/叠加图。"""
    A = np.asarray(a).astype(int)
    B = np.asarray(b).astype(int)
    h = min(A.shape[0], B.shape[0])
    w = min(A.shape[1], B.shape[1])
    A, B = A[:h, :w], B[:h, :w]
    d = np.abs(A - B)
    per_px = d.max(axis=2)
    bad = per_px > 2
    ys, xs = np.where(bad)
    diff = (d.sum(axis=2)).astype(np.uint8)
    # diff 可视化：红=超过容差，灰=0–2 差异
    vis = np.zeros((h, w, 3), np.uint8)
    vis[..., 0] = np.where(bad, 255, np.clip(diff * 40, 0, 120))
    vis[..., 1] = np.clip(diff * 10, 0, 100)
    Image.fromarray(vis).save(SHOT(f"lite-verify-pixel-diff-{tag}.png"))
    # 左侧 12px 是圆角/DWM 合成边缘，单独统计内部差异
    cut = min(12, w)
    interior_bad = bad[:, cut:]
    # 叠加：lite 红通道 + std 绿通道（相同→黄，不同→红/绿）
    blend = np.zeros((h, w, 3), np.uint8)
    blend[..., 0] = A.mean(axis=2).astype(np.uint8)
    blend[..., 1] = B.mean(axis=2).astype(np.uint8)
    Image.fromarray(blend).save(SHOT(f"lite-verify-pixel-blend-{tag}.png"))
    # 并排（2x）上下堆叠
    scale = 2
    side = Image.new("RGB", (w * scale, h * scale * 2 + 4), (255, 0, 255))
    side.paste(a.resize((w * scale, h * scale), Image.NEAREST), (0, 0))
    side.paste(b.resize((w * scale, h * scale), Image.NEAREST), (0, h * scale + 4))
    side.save(SHOT(f"lite-verify-pixel-side-{tag}.png"))
    return {
        "size": [w, h], "pixels": w * h,
        "diff_pixels_gt2": int(bad.sum()),
        "diff_pct": round(100.0 * bad.sum() / (w * h), 4),
        "interior_x_ge": cut,
        "diff_pixels_gt2_interior": int(interior_bad.sum()),
        "interior_pixels": int(interior_bad.size),
        "interior_diff_pct": round(100.0 * interior_bad.sum() / interior_bad.size, 4),
        "max_channel_diff": int(d.max()),
        "mean_abs_diff": round(float(d.mean()), 4),
        "pixels_identical": int((per_px == 0).sum()),
        "identical_pct": round(100.0 * (per_px == 0).sum() / (w * h), 3),
        "diff_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        if bad.any() else None,
        "diff_rows": sorted({int(y) for y in ys})[:12],
        "diff_cols": sorted({int(x) for x in xs})[:12],
        "files": {"diff": f"lite-verify-pixel-diff-{tag}.png",
                  "blend": f"lite-verify-pixel-blend-{tag}.png",
                  "side": f"lite-verify-pixel-side-{tag}.png"},
    }


def layout(img, bg=(243, 243, 243)):
    """给一张 chip RGB，返回底色统计 / 行带 / 每行四列起始 x。"""
    a = np.asarray(img.convert("RGB")).astype(int)
    h, w = a.shape[:2]
    from collections import Counter
    cnt = Counter(map(tuple, a.reshape(-1, 3)))
    top = cnt.most_common(3)
    bgc = np.array(top[0][0])
    mask = np.abs(a - bgc).max(axis=2) > 20
    # 过滤单像素噪声：要求该行/列至少 2 个像素
    row_has = mask.sum(axis=1) >= 2
    bands = []
    start = None
    for y in range(h):
        if row_has[y] and start is None:
            start = y
        if not row_has[y] and start is not None:
            if y - start >= 2:
                bands.append([start, y - 1])
            start = None
    if start is not None and h - start >= 2:
        bands.append([start, h - 1])
    bands = [b for b in bands if b[1] - b[0] >= 6]   # 只保留文字行（≥7px 高）
    cols = {}
    for bi, (y0, y1) in enumerate(bands):
        m = mask[y0:y1 + 1]
        col_has = m.sum(axis=0) >= 1
        xs = np.where(col_has)[0]
        groups = []
        if len(xs):
            s = prev = int(xs[0])
            for x in xs[1:]:
                x = int(x)
                if x - prev > 4:
                    groups.append([s, prev])
                    s = x
                prev = x
            groups.append([s, prev])
        cols[f"row{bi+1}_y{y0}-{y1}"] = groups
    return {"size": [w, h], "top_colors": [[list(c), n] for c, n in top],
            "bg": list(bgc), "text_bands": bands, "col_groups": cols,
            "content_bbox": [int(np.where(mask.any(axis=0))[0].min()),
                             int(np.where(mask.any(axis=1))[0].min()),
                             int(np.where(mask.any(axis=0))[0].max()),
                             int(np.where(mask.any(axis=1))[0].max())]
            if mask.any() else None}


def main():
    L.ensure_dirs()
    print("== A. --demo 同读数逐像素（light/dark）==")
    for theme in ("light", "dark"):
        caps = {}
        for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
            name = f"lite-verify-pixel-{theme}-{label}.png"
            c = capture(exe, theme=theme, name=name, settle=1.8)
            caps[label] = c
            print(f"  {theme}-{label}: rect={c['rect']} file={name}")
        if caps["lite"]["crop"] and caps["std"]["crop"]:
            OUT[f"demo_{theme}"] = compare(caps["lite"]["crop"], caps["std"]["crop"],
                                           f"demo-{theme}")
            OUT[f"demo_{theme}"]["lite_file"] = caps["lite"]["file"]
            OUT[f"demo_{theme}"]["std_file"] = caps["std"]["file"]
            d = OUT[f"demo_{theme}"]
            print(f"  -> diff>2: {d['diff_pixels_gt2']} px ({d['diff_pct']}%), "
                  f"identical {d['identical_pct']}%, max={d['max_channel_diff']}, "
                  f"bbox={d['diff_bbox']}")

    print("== B. 实时读数对照（读数不同，只看差异范围）==")
    caps = {}
    for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
        name = f"lite-verify-live-{label}.png"
        c = capture(exe, mode="taskbar", theme="light", args=(), settle=1.8, name=name)
        caps[label] = c
        print(f"  live-{label}: rect={c['rect']} file={name}")
    if caps["lite"]["crop"] and caps["std"]["crop"]:
        OUT["live"] = compare(caps["lite"]["crop"], caps["std"]["crop"], "live")
        OUT["live"]["lite_file"] = caps["lite"]["file"]
        OUT["live"]["std_file"] = caps["std"]["file"]
        d = OUT["live"]
        print(f"  -> diff>2: {d['diff_pixels_gt2']} px ({d['diff_pct']}%), "
              f"bbox={d['diff_bbox']}, rows={d['diff_rows']}")

    print("== C. 与 ref-widget.png 布局对比 ==")
    ref = Image.open(REF).convert("RGB")
    ours = caps["lite"]["crop"] or Image.open(SHOT("lite-verify-pixel-light-lite.png")).convert("RGB")
    ref_layout = layout(ref)
    our_layout = layout(ours)
    OUT["ref_layout"] = ref_layout
    OUT["our_layout"] = our_layout
    print("  ref:", json.dumps(ref_layout["size"]), "bg=", ref_layout["bg"],
          "bands=", ref_layout["text_bands"], "bbox=", ref_layout["content_bbox"])
    print("  our:", json.dumps(our_layout["size"]), "bg=", our_layout["bg"],
          "bands=", our_layout["text_bands"], "bbox=", our_layout["content_bbox"])

    # 列起始位置对比：两行分别取 4 个簇（行1=标签，行2=数值/箭头）
    cmp = {"ref_width": ref.width, "our_width": ours.width,
           "width_delta_px": ours.width - ref.width,
           "width_delta_pct": round(100.0 * (ours.width - ref.width) / ref.width, 2),
           "bg_equal": ref_layout["bg"] == our_layout["bg"],
           "rows": {}}
    for key in ("row1", "row2"):
        rk = next((k for k in ref_layout["col_groups"] if k.startswith(key)), None)
        ok = next((k for k in our_layout["col_groups"] if k.startswith(key)), None)
        rg = ref_layout["col_groups"].get(rk, [])
        og = our_layout["col_groups"].get(ok, [])
        cmp["rows"][key] = {"ref_groups": rg, "our_groups": og,
                            "ref_starts": [g[0] for g in rg],
                            "our_starts": [g[0] for g in og]}
    OUT["ref_compare"] = cmp
    # 行带 y 对比
    OUT["row_band_compare"] = {
        "ref": ref_layout["text_bands"], "our": our_layout["text_bands"],
        "ref_row_heights": [b[1] - b[0] + 1 for b in ref_layout["text_bands"]],
        "our_row_heights": [b[1] - b[0] + 1 for b in our_layout["text_bands"]],
    }
    # 拼图：ref / lite / std 三者 2x 堆叠（含 4px 洋红分隔）
    imgs = [("ref", ref), ("lite-demo-light", Image.open(SHOT("lite-verify-pixel-light-lite.png")).convert("RGB")),
            ("std-demo-light", Image.open(SHOT("lite-verify-pixel-light-std.png")).convert("RGB"))]
    W = max(i.width for _, i in imgs) * 2
    H = sum(i.height * 2 + 4 for _, i in imgs) + 4
    canvas = Image.new("RGB", (W, H), (255, 0, 255))
    y = 0
    for name, im in imgs:
        im2 = im.resize((im.width * 2, im.height * 2), Image.NEAREST)
        canvas.paste(im2, (0, y))
        y += im2.height + 4
    canvas.save(SHOT("lite-verify-ref-compare.png"))
    OUT["files"] = {"ref_compare": "lite-verify-ref-compare.png"}

    # 结论摘要
    print("\n== 摘要 ==")
    for theme in ("light", "dark"):
        d = OUT.get(f"demo_{theme}")
        if d:
            print(f"  demo-{theme}: 逐像素差异 {d['diff_pct']}%（>2/255），"
                  f"完全相同像素 {d['identical_pct']}%")
    print(f"  宽度: ref {ref.width} vs our {ours.width} "
          f"(+{ours.width-ref.width}px, {cmp['width_delta_pct']}%)，底色一致={cmp['bg_equal']}")
    L.save_json("lite-4-appearance.json", OUT)


if __name__ == "__main__":
    main()
