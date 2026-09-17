# -*- coding: utf-8 -*-
"""
把 _full/ 里的全尺寸抠图压成展示用的 assets/images/，并生成 hitmaps.js。

两个关键点：
1) 白场抠图会在四周留下"肉眼几乎看不见但 alpha 不为 0"的柔光外缘，
   直接缩放会让可见内容在 PNG 里跑到一边去。所以要先按 alpha>10% 裁掉外缘，
   再让内容在画布中居中。
2) 不要用调色板量化：Pillow 的 quantize 对 RGBA 只支持二值透明，
   会把柔光边缘的渐变 alpha 压没。只做 LANCZOS 缩放 + optimize 存 PNG。

磕头三帧必须共用同一个裁剪框，否则会破坏已经调好的对齐。
"""
import os
import glob
import json
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FULL = os.path.join(ROOT, "_full")
OUT = os.path.join(ROOT, "assets", "images")
os.makedirs(OUT, exist_ok=True)

# 每张图的展示宽度（PNG 像素）。CSS 里用一半，保证 2x 屏清晰。
TARGET_W = {
    "god_caishen": 300, "god_bull": 480, "god_shouxing": 300, "god_wenchang": 260,
    "altar_wealth": 480, "altar_stock": 480, "altar_health": 500, "altar_study": 440,
    "smoke": 180, "coin": 120,
}
KOWTOW_W = 436          # 磕头帧画布展示宽度
KOWTOW_TRIM = False     # 画布本身已经是居中的（三帧并集），不再裁

ALPHA_THR = 26          # 10% 不透明度以下视为不可见
BBOX_FRAC = 0.006       # 行/列里可见像素占比超过该值才算"真的有内容"（滤掉 JPEG 噪点）
HIT_COLS = 40
HIT_COVER = 0.34


def shake_specks(im, thr=ALPHA_THR, min_neighbor=1):
    """清掉孤立噪点：一个可见像素如果 8 邻域里可见像素太少，就当作噪点抹掉。"""
    arr = np.asarray(im).astype(np.uint8).copy()
    m = arr[:, :, 3] > thr
    n = np.zeros(m.shape, dtype=np.int16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            n += np.roll(np.roll(m, dy, axis=0), dx, axis=1)
    kill = m & (n <= min_neighbor)
    arr[kill, 3] = 0
    return Image.fromarray(arr, "RGBA")


def robust_bbox(images, thr=ALPHA_THR, frac=BBOX_FRAC):
    """按行/列廓形取包围盒，避免零散噪点把框撑到整张图。"""
    x0s, y0s, x1s, y1s = [], [], [], []
    for im in images:
        m = np.asarray(im)[:, :, 3] > thr
        h, w = m.shape
        rows = m.sum(axis=1)
        cols = m.sum(axis=0)
        ry = np.where(rows > max(1.0, w * frac))[0]
        rx = np.where(cols > max(1.0, h * frac))[0]
        if len(ry) == 0 or len(rx) == 0:
            continue
        y0s.append(ry.min()); y1s.append(ry.max() + 1)
        x0s.append(rx.min()); x1s.append(rx.max() + 1)
    if not x0s:
        return 0, 0, images[0].width, images[0].height
    return int(min(x0s)), int(min(y0s)), int(max(x1s)), int(max(y1s))


def prepare(source_keys, target_w, do_trim=True):
    """source_keys: _full 下的文件名（不含扩展名）。返回处理好的同尺寸 RGBA 列表。"""
    imgs = [Image.open(os.path.join(FULL, k + ".png")).convert("RGBA") for k in source_keys]
    imgs = [shake_specks(im) for im in imgs]
    if do_trim:
        box = robust_bbox(imgs)
        imgs = [im.crop(box) for im in imgs]
    base = imgs[0]
    h = max(1, int(round(base.height * target_w / base.width)))
    return [im.resize((target_w, h), Image.LANCZOS) for im in imgs]


def mask_for(im, cols=HIT_COLS):
    a = np.asarray(im)[:, :, 3].astype(np.float32) / 255.0
    h, w = a.shape
    rows = max(1, int(round(cols * h / w)))
    ys = np.linspace(0, h, rows + 1).astype(int)
    xs = np.linspace(0, w, cols + 1).astype(int)
    cell = np.zeros((rows, cols), dtype=np.float32)
    for r in range(rows):
        for c in range(cols):
            blk = a[ys[r]:max(ys[r] + 1, ys[r + 1]), xs[c]:max(xs[c] + 1, xs[c + 1])]
            if blk.size:
                cell[r, c] = (blk > 0.35).mean()
    return (cell > HIT_COVER).astype(int)


hitmaps = {}
report = []

# ---- 磕头三帧：共用裁剪框，保持对齐 ----
kf = prepare(["kowtow_1", "kowtow_2", "kowtow_3"], KOWTOW_W, do_trim=KOWTOW_TRIM)
for i, im in enumerate(kf, 1):
    stem = "kowtow_%d" % i
    im.save(os.path.join(OUT, stem + ".png"), optimize=True)
    m = mask_for(im)
    hitmaps[stem] = {"w": int(m.shape[1]), "h": int(m.shape[0]),
                     "rows": ["".join(str(v) for v in row) for row in m]}
    report.append("%-16s -> %4dx%-4d  %7.1f KB  mask %dx%d" % (
        stem, im.width, im.height, os.path.getsize(os.path.join(OUT, stem + ".png")) / 1024,
        m.shape[1], m.shape[0]))

# ---- 其余单图 ----
for stem, tw in TARGET_W.items():
    if not os.path.exists(os.path.join(FULL, stem + ".png")):
        continue
    im = prepare([stem], tw, do_trim=True)[0]
    im.save(os.path.join(OUT, stem + ".png"), optimize=True)
    m = mask_for(im)
    hitmaps[stem] = {"w": int(m.shape[1]), "h": int(m.shape[0]),
                     "rows": ["".join(str(v) for v in row) for row in m]}
    report.append("%-16s -> %4dx%-4d  %7.1f KB  mask %dx%d" % (
        stem, im.width, im.height, os.path.getsize(os.path.join(OUT, stem + ".png")) / 1024,
        m.shape[1], m.shape[0]))

with open(os.path.join(ROOT, "hitmaps.js"), "w", encoding="utf-8") as f:
    f.write("// 由 tools/optimize_assets.py 自动生成，请勿手改。\n")
    f.write("// 每张图的低分辨率 alpha 掩码：运行时据此判断鼠标是否落在可见像素上。\n")
    f.write("window.HITMAPS = " + json.dumps(hitmaps, ensure_ascii=False, separators=(",", ":")) + ";\n")

with open(os.path.join(ROOT, "_optimize.log"), "w", encoding="utf-8") as f:
    f.write("\n".join(report))
print("ok")
