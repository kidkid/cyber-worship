# -*- coding: utf-8 -*-
"""量一下每个展示素材的 alpha 分布，确认内容是否在 PNG 里居中。"""
import os, glob
import numpy as np
from PIL import Image

IMG = r"E:\workbuddy\2026-09-17-10-38-17\cyber-worship\assets\images"
out = []
for p in sorted(glob.glob(os.path.join(IMG, "*.png"))):
    im = Image.open(p).convert("RGBA")
    a = np.asarray(im)[:, :, 3].astype(np.float32) / 255.0
    h, w = a.shape
    ys, xs = np.where(a > 0.08)
    if len(xs) == 0:
        out.append("%-16s EMPTY" % os.path.basename(p)); continue
    bx0, bx1 = xs.min(), xs.max()
    by0, by1 = ys.min(), ys.max()
    colsum = a.sum(axis=0)
    cen = (colsum * np.arange(w)).sum() / colsum.sum()
    # 按能量算 5% / 95% 分位，比包围盒更能反映"视觉重心"
    c = np.cumsum(colsum) / colsum.sum()
    lo = int(np.searchsorted(c, 0.05)); hi = int(np.searchsorted(c, 0.95))
    out.append("%-16s %3dx%-3d  bbox x %3d..%3d (mid %5.1f = %.2fw)  centroid %.2fw  energy5-95 %3d..%3d (mid %5.1f = %.2fw)"
               % (os.path.basename(p), w, h, bx0, bx1, (bx0 + bx1) / 2, (bx0 + bx1) / 2 / w,
                  cen / w, lo, hi, (lo + hi) / 2, (lo + hi) / 2 / w))

# 三帧磕头统一看：相对整体包围盒的位置
ks = [Image.open(os.path.join(IMG, "kowtow_%d.png" % i)).convert("RGBA") for i in (1, 2, 3)]
out.append("")
for i, im in enumerate(ks, 1):
    a = np.asarray(im)[:, :, 3].astype(np.float32) / 255.0
    h, w = a.shape
    ys, xs = np.where(a > 0.08)
    out.append("kowtow_%d %3dx%-3d bbox x %3d..%3d mid %5.1f = %.3fw  y %3d..%3d" % (
        i, w, h, xs.min(), xs.max(), (xs.min() + xs.max()) / 2, (xs.min() + xs.max()) / 2 / w,
        ys.min(), ys.max()))

with open(r"E:\workbuddy\2026-09-17-10-38-17\_measure.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("ok")
