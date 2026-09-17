# -*- coding: utf-8 -*-
"""
赛博朝拜 - 素材预处理
1376x768 白底 JPEG 素材 -> 透明 PNG（保留柔光外发光）+ 磕头序列帧切片 + icon.ico
"""
import os
import glob
import atexit
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "_raw")
OUT = os.path.join(ROOT, "assets")
IMG = os.path.join(ROOT, "_full")     # 全尺寸抠图产物，供 optimize_assets.py 再做展示优化
PREV = os.path.join(ROOT, "_preview")
LOGF = os.path.join(ROOT, "_build_assets.log")
for d in (OUT, os.path.join(OUT, "images"), IMG, PREV):
    os.makedirs(d, exist_ok=True)

_logs = []
def log(*a):
    _logs.append(" ".join(str(x) for x in a))

# 失败时也要落盘日志，方便排查
atexit.register(lambda: open(LOGF, "w", encoding="utf-8").write("\n".join(_logs)))

# ------------------------------------------------------------------ 工具

def load(part):
    hits = [p for p in glob.glob(os.path.join(RAW, "*.jpeg"))
            if part.lower() in os.path.basename(p).lower()]
    if not hits:
        raise FileNotFoundError(part)
    return Image.open(hits[0]).convert("RGB")

def flood_from_border(mask, scale=2, refine=14):
    """从四边泛洪返回可达区域。降采样加速 + 全分辨率精修，避免 PIL floodfill 在大图上的性能问题。"""
    h, w = mask.shape
    small = mask[::scale, ::scale]
    cur = np.zeros_like(small)
    cur[0, :] = small[0, :]
    cur[-1, :] = small[-1, :]
    cur[:, 0] = small[:, 0]
    cur[:, -1] = small[:, -1]
    while True:
        nxt = cur.copy()
        nxt[1:, :] |= cur[:-1, :]
        nxt[:-1, :] |= cur[1:, :]
        nxt[:, 1:] |= cur[:, :-1]
        nxt[:, :-1] |= cur[:, 1:]
        nxt &= small
        if np.array_equal(nxt, cur):
            break
        cur = nxt
    up = np.asarray(Image.fromarray((cur * 255).astype(np.uint8), "L")
                    .resize((w, h), Image.NEAREST)) > 0
    up &= mask
    for _ in range(refine):
        nxt = up.copy()
        nxt[1:, :] |= up[:-1, :]
        nxt[:-1, :] |= up[1:, :]
        nxt[:, 1:] |= up[:, :-1]
        nxt[:, :-1] |= up[:, 1:]
        nxt &= mask
        if np.array_equal(nxt, up):
            break
        up = nxt
    return up

def key_out_white(im, strict=0.985, loose=0.80, feather=0.6):
    """
    白场抠图：
      纯白区域(>strict)             -> 全透明
      外发光带(loose<w<strict)      -> 按 w 线性渐隐，保留神圣光晕
      角色本体 / 被描边包住的浅色区  -> 完全不透明（靠泛洪连通性判定，不会误伤皮肤和白眼白）
    """
    rgb = np.asarray(im, dtype=np.float32)
    w = rgb.min(axis=2) / 255.0
    bg_strict = flood_from_border(w > strict)
    bg_loose = flood_from_border(w > loose)
    solid = ~bg_loose

    a = np.zeros(w.shape, dtype=np.float32)
    band = bg_loose & (~bg_strict)
    a[band] = np.clip((strict - w[band]) / (strict - loose), 0.0, 1.0)
    a[solid] = 1.0

    if feather:
        a = np.asarray(Image.fromarray((a * 255).astype(np.uint8), "L")
                       .filter(ImageFilter.GaussianBlur(feather)), dtype=np.float32) / 255.0
    return Image.fromarray(np.dstack([rgb, a * 255.0]).astype(np.uint8), "RGBA")

def autotrim(im, pad=2, thr=6):
    a = np.asarray(im)[:, :, 3]
    ys, xs = np.where(a > thr)
    if len(xs) == 0:
        return im
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
    x1 = min(im.width, x1 + pad); y1 = min(im.height, y1 + pad)
    return im.crop((x0, y0, x1, y1))

def save(im, name):
    p = os.path.join(IMG, name)
    im.save(p)
    log("saved", name, im.size)

def checkerboard(w, h, cell=16):
    yy, xx = np.mgrid[0:h, 0:w]
    m = ((yy // cell + xx // cell) % 2).astype(np.uint8)
    base = 205 + m * 40
    return Image.fromarray(np.dstack([base, base, base]).astype(np.uint8), "RGB")

def preview(images, cols, cell, outname):
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
    for i, im in enumerate(images):
        t = im.copy()
        t.thumbnail((cell - 10, cell - 10), Image.LANCZOS)
        x = (i % cols) * cell + (cell - t.width) // 2
        y = (i // cols) * cell + (cell - t.height) // 2
        bg = checkerboard(t.width, t.height, 12)
        bg.paste(t, (0, 0), t)
        sheet.paste(bg, (x, y))
    sheet.save(os.path.join(PREV, outname))
    log("preview", outname, sheet.size)

def runs(profile, thr=0, min_len=1):
    idx = np.where(profile > thr)[0]
    res = []
    if len(idx) == 0:
        return res
    s = p = idx[0]
    for y in idx[1:]:
        if y == p + 1:
            p = y
        else:
            if p - s + 1 >= min_len:
                res.append((int(s), int(p)))
            s = p = y
    if p - s + 1 >= min_len:
        res.append((int(s), int(p)))
    return res

# ------------------------------------------------------------------ 1. 抠图

SINGLES = [
    ("Chibi_Caishen", "god_caishen.png"),
    ("Red_bull_deity", "god_bull.png"),
    ("Chibi_deity_holding_giant_peach", "god_shouxing.png"),
    ("Chibi_Emperor_Wenchang", "god_wenchang.png"),
    ("Altar_table_with_incense_burner", "altar_wealth.png"),
    ("Futuristic_altar_and_coffee", "altar_stock.png"),
    ("Altar_table_with_offerings", "altar_health.png"),
    ("Desk_altar_game_icon", "altar_study.png"),
    ("Incense_smoke_curling", "smoke.png"),
    ("Golden_coin_game_icon", "coin.png"),
]

cut_results = []
for part, outname in SINGLES:
    im = autotrim(key_out_white(load(part)))
    save(im, outname)
    cut_results.append(im)
preview(cut_results, cols=5, cell=300, outname="cutout_check.png")

# ------------------------------------------------------------------ 2. 磕头序列帧

MAT_RGB = np.array([155.0, 161.0, 172.0], dtype=np.float32)   # 实测跪垫填充色

def dilate(mask, r=1):
    m = mask
    for _ in range(r):
        n = m.copy()
        n[1:, :] |= m[:-1, :]
        n[:-1, :] |= m[1:, :]
        n[:, 1:] |= m[:, :-1]
        n[:, :-1] |= m[:, 1:]
        m = n
    return m

def box_count(mask, k):
    """用积分图统计每个像素周围 (2k+1)^2 窗口内的像素数，用来区分"成片区域"和"零散噪点"。"""
    m = mask.astype(np.int32)
    ii = np.cumsum(np.cumsum(m, axis=0), axis=1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    h, w = mask.shape
    ys = np.arange(h); xs = np.arange(w)
    y1 = np.clip(ys + k + 1, 0, h); y0 = np.clip(ys - k, 0, h)
    x1 = np.clip(xs + k + 1, 0, w); x0 = np.clip(xs - k, 0, w)
    return (ii[np.ix_(y1, x1)] - ii[np.ix_(y0, x1)]
            - ii[np.ix_(y1, x0)] + ii[np.ix_(y0, x0)])

def remove_mat(rgb, alpha, outline_reach=8):
    """
    去掉跪垫（蓝灰色填充 + 黑色外框）。
      1) 填充：低饱和 + 中亮度 + 颜色接近实测垫色，再按"局部密度"只保留成片区域，
         丢掉散落在角色身上的同色噪点
      2) 外框：紧贴填充的纯黑像素（mx<40，深 navy 西装 mx≈71 不受影响），
         且只在垫子所在的行区间内剔除，免得削掉人物上半身的轮廓线
    外框在整图分辨率下与角色连通（鞋底压在垫子上），所以无法用连通域分离。
    """
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    d = np.sqrt(((rgb - MAT_RGB) ** 2).sum(axis=2))
    cand = ((mx - mn) < 34) & (mx > 86) & (mx < 248) & (d < 32) & (alpha > 0)
    fill = cand & (box_count(cand, 10) > 90)
    if not fill.any():
        return fill
    fy = np.where(fill.any(axis=1))[0]
    y_lo = max(0, int(fy.min()) - 6)
    y_hi = min(alpha.shape[0], int(fy.max()) + 7)
    rows = np.zeros_like(fill)
    rows[y_lo:y_hi, :] = True
    ring = dilate(fill, outline_reach) & (~fill) & rows
    outline = ring & (mx < 40) & (alpha > 0)
    log("   mat cand=%d fill=%d outline=%d rows %d..%d"
        % (int(cand.sum()), int(fill.sum()), int(outline.sum()), y_lo, y_hi))
    return fill | outline

def flood_from_seed(mask, seed, max_iter=4000):
    """从单个种子点在 mask 内做 4-邻域泛洪，返回连通域。"""
    cur = np.zeros_like(mask)
    if not mask[seed]:
        return cur
    cur[seed] = True
    for _ in range(max_iter):
        nxt = cur.copy()
        nxt[1:, :] |= cur[:-1, :]
        nxt[:-1, :] |= cur[1:, :]
        nxt[:, 1:] |= cur[:, :-1]
        nxt[:, :-1] |= cur[:, 1:]
        nxt &= mask
        if np.array_equal(nxt, cur):
            break
        cur = nxt
    return cur

def slice_kowtow():
    src = load("Office_worker_performing_kowtow")

    # 用底部数字标签 1/2/3 的横向位置作为三个姿势的中心参考
    raw = np.asarray(src).astype(np.int32)
    nonwhite = raw.min(axis=2) < 235
    rblocks = runs(nonwhite.sum(axis=1), 0, 2)
    body_b = max(rblocks, key=lambda b: b[1] - b[0])
    label_rows = [b for b in rblocks if b[0] > body_b[1]]
    digit_runs = runs(nonwhite[label_rows[0][0]:label_rows[-1][1] + 1, :].sum(axis=0), 0, 4)
    centers = [(r[0] + r[1]) / 2.0 for r in digit_runs][:3]
    log("digit runs:", digit_runs, "pose centers:", centers)
    if len(centers) < 3:
        raise RuntimeError("无法定位三个姿势的标签位置")

    rgba = key_out_white(src, strict=0.985, loose=0.78, feather=0)
    arr = np.asarray(rgba).astype(np.float32)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]

    mat = remove_mat(rgb, alpha)
    log("mat pixels removed:", int(mat.sum()))
    alpha[mat] = 0
    arr[:, :, 3] = alpha
    clean = Image.fromarray(arr.astype(np.uint8), "RGBA")

    a = alpha > 30
    row_blocks = runs(a.sum(axis=1), 0, 4)
    log("row blocks (after mat removal):", row_blocks)
    body = max(row_blocks, key=lambda b: b[1] - b[0])
    by0, by1 = body[0], body[1] + 1

    # 三个姿势是彼此独立的图形 -> 用连通域精确分离（头发在 x 上和邻座重叠也不受影响）
    frames, knees = [], []
    for i, cx in enumerate(centers):
        col = np.where(a[by0:by1, int(cx)])[0]
        if len(col) == 0:
            raise RuntimeError("姿势 %d 在 x=%d 处没有内容" % (i + 1, cx))
        seed = (by0 + int(col[len(col) // 2]), int(cx))
        comp = flood_from_seed(a, seed)
        log("  comp %d seed%s size=%d" % (i + 1, seed, int(comp.sum())))
        if comp.sum() < 2000:
            raise RuntimeError("姿势 %d 连通域过小" % (i + 1))

        ys = np.where(comp.any(axis=1))[0]
        xs = np.where(comp.any(axis=0))[0]
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1

        # 只保留本姿势的像素，避免邻座头发等落在同一包围盒里
        own = np.zeros_like(alpha)
        own[y0:y1, x0:x1] = np.where(comp[y0:y1, x0:x1], alpha[y0:y1, x0:x1], 0.0)
        frame = Image.fromarray(np.dstack([rgb, own]).astype(np.uint8), "RGBA")
        f = autotrim(frame.crop((x0, y0, x1, y1)), pad=1, thr=20)
        frames.append(f)
        log("  frame %d bbox%s -> %s" % (i + 1, (x0, y0, x1, y1), f.size))

        fa = np.asarray(f)
        fh, fw = fa.shape[0], fa.shape[1]
        # 取最底部一条带（贴地部分：鞋/胫/膝），用深色像素确定"落地点"
        band = fa[int(fh * 0.90):fh, :, :]
        bdark = (band[:, :, 3] > 40) & (band[:, :, :3].astype(np.float32).max(axis=2) < 160)
        if bdark.sum() > 20:
            bx = np.where(bdark.any(axis=0))[0]
            toe = float(np.percentile(bx, 3))
            heel = float(np.percentile(bx, 97))
            knees.append((toe, heel))
        else:
            knees.append((fw * 0.25, fw * 0.75))
        log("  frame %d size=%s floorband toe=%.1f heel=%.1f" % (i + 1, f.size, knees[-1][0], knees[-1][1]))
    log("floor anchors:", [(round(a, 1), round(b, 1)) for a, b in knees], "widths:", [f.width for f in frames])
    log("heights:", [f.height for f in frames])

    # 每帧的 alpha 质心（"视觉重心"），用于对齐方案对比
    cents = []
    for f in frames:
        fa = np.asarray(f)[:, :, 3].astype(np.float32) / 255.0
        cs = fa.sum(axis=0)
        cents.append(float((cs * np.arange(len(cs))).sum() / max(cs.sum(), 1e-6)))
    log("centroids:", [round(c, 1) for c in cents])

    # ---- 对齐方案对比图：脚尖对齐 / 折中 / 重心居中 ----
    def strip_for(blend, name, label):
        offs = []
        for i, f in enumerate(frames):
            offA = -knees[i][0]                 # 脚尖落在同一点
            offB = 210.0 - cents[i]             # 重心落在同一中心
            offs.append((1 - blend) * offA + blend * offB)
        mino = min(offs)
        placed = [o - mino + 8 for o in offs]
        W = int(max(p + f.width for p, f in zip(placed, frames)) + 8)
        H = max(f.height for f in frames) + 10
        st = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for p, f in zip(placed, frames):
            st.alpha_composite(f, (int(p), 0))
        bg = checkerboard(W, H, 14).convert("RGBA")
        bg.alpha_composite(st)
        dd = ImageDraw.Draw(bg)
        for i, p in enumerate(placed):
            dd.line([(p + cents[i], 0), (p + cents[i], H)], fill=(220, 40, 160, 255), width=1)
            dd.line([(p + knees[i][0], 0), (p + knees[i][0], H)], fill=(30, 150, 60, 255), width=1)
        bg.convert("RGB").save(os.path.join(PREV, name))
        shift = max(p + cents[i] for i, p in enumerate(placed)) - min(p + cents[i] for i, p in enumerate(placed))
        log("   align %-18s canvas_w=%d centroid_shift=%.1fpx" % (label, W, shift))

    for bl, nm, lb in ((0.0, "align_A_toe.png", "toe-anchored"),
                       (0.45, "align_B_blend45.png", "blend45"),
                       (0.8, "align_C_blend80.png", "blend80"),
                       (1.0, "align_D_centroid.png", "centroid-centered")):
        strip_for(bl, nm, lb)

    # 把每帧的原始（未对齐）图也存下来，方便反复调参
    RAWFR = os.path.join(ROOT, "_frames_raw")
    os.makedirs(RAWFR, exist_ok=True)
    for i, f in enumerate(frames, 1):
        f.save(os.path.join(RAWFR, "kowtow_raw_%d.png" % i))
    with open(os.path.join(RAWFR, "metrics.json"), "w", encoding="utf-8") as fh:
        import json as _json
        fh.write(_json.dumps({"toe": [k[0] for k in knees], "heel": [k[1] for k in knees],
                              "centroid": cents}, ensure_ascii=False))

    # 最终采用的对齐：脚尖对齐（身体绕膝盖前倾，脚不离地）
    ALIGN = 0.0
    offs = []
    for i, f in enumerate(frames):
        offA = -knees[i][0]
        offB = 210.0 - cents[i]
        offs.append((1 - ALIGN) * offA + ALIGN * offB)
    mino = min(offs)
    placed = [o - mino + 8 for o in offs]
    cw = int(max(p + f.width for p, f in zip(placed, frames)) + 8)
    ch = max(f.height for f in frames) + 16
    out = []
    for f, p in zip(frames, placed):
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas.alpha_composite(f, (int(p), ch - f.height))
        out.append(canvas)
    log("kowtow canvas:", (cw, ch), "ALIGN=%.2f" % ALIGN, "offsets:", [int(p) for p in placed])
    return out

kframes = slice_kowtow()
for i, f in enumerate(kframes, 1):
    save(f, "kowtow_%d.png" % i)

if kframes:
    cw, ch = kframes[0].size
    strip = Image.new("RGBA", (cw * len(kframes), ch), (0, 0, 0, 0))
    for i, f in enumerate(kframes):
        strip.alpha_composite(f, (i * cw, 0))
    bg = checkerboard(strip.width, strip.height, 12).convert("RGBA")
    bg.alpha_composite(strip)
    d = ImageDraw.Draw(bg)
    # 红=每帧脚尖落点，蓝=帧分界，绿=地面线
    for i, f in enumerate(kframes):
        fa = np.asarray(f)[:, :, 3]
        band = fa[int(fa.shape[0] * 0.93):, :]
        bx = np.where((band > 90).any(axis=0))[0]
        if len(bx):
            d.line([(i * cw + int(bx.min()), 0), (i * cw + int(bx.min()), ch)],
                   fill=(255, 0, 0, 255), width=1)
        if i:
            d.line([(i * cw, 0), (i * cw, ch)], fill=(0, 120, 255, 255), width=1)
    d.line([(0, ch - 2), (bg.width, ch - 2)], fill=(0, 200, 0, 255), width=2)
    bg.convert("RGB").save(os.path.join(PREV, "kowtow_align_check.png"))
    log("preview kowtow_align_check.png", bg.size)

# ------------------------------------------------------------------ 3. 图标

src = autotrim(key_out_white(load("Chibi_Caishen")), pad=4)
w, h = src.size
cx = w // 2
side = min(w, h)
sq = src.crop((max(0, cx - side // 2), 0, min(w, cx + side // 2), side)).resize((440, 440), Image.LANCZOS)

icon = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
d = ImageDraw.Draw(icon)
d.ellipse((4, 4, 507, 507), fill=(24, 16, 10, 255), outline=(236, 178, 58, 255), width=9)
d.ellipse((20, 20, 491, 491), outline=(126, 88, 28, 255), width=4)
icon.alpha_composite(sq, (36, 46))
icon.save(os.path.join(OUT, "icon.png"))
icon.save(os.path.join(OUT, "icon.ico"),
          sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
icon.resize((64, 64), Image.LANCZOS).save(os.path.join(OUT, "images", "tray.png"))
log("icon.ico + tray.png written")

with open(os.path.join(ROOT, "_build_assets.log"), "w", encoding="utf-8") as f:
    f.write("\n".join(_logs))
print("done")
