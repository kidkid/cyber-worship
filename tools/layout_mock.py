# -*- coding: utf-8 -*-
"""
版式模拟：用与 renderer.js / styles.css / main.js 完全相同的版面常量，
把场景合成到"浅色桌面"背景上，用于在启动 Electron 之前先肉眼校验构图。

构图立意（2026-09-17 改版）：
  素材里的人物是**侧面朝右**的跪姿（磕头时身体向右前方俯下），
  所以神位与香案必须摆在人物的**右前方**，他才是"朝着神拜"；
  原先把神位/香案摆在他正上方，看起来就成了往右边拜。

改这里的常量时，必须同步改：
  - main.js        WIN_W / WIN_H / BASE_W / BASE_H
  - styles.css     :root --w / --h / --person-* / --badge-*
  - renderer.js    GOD_CX / GOD_BOTTOM_Y / ALTAR_CX / ALTAR_BOTTOM_Y / PERSON_*
"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "assets", "images")
OUTDIR = os.path.join(ROOT, "_preview")
os.makedirs(OUTDIR, exist_ok=True)

# ===================== 版面常量（唯一真源） =====================
W, H = 400, 460
GOD_CX, GOD_BOTTOM_Y = 248, 190        # 神像：水平中心 / 底边
ALTAR_CX, ALTAR_BOTTOM_Y = 248, 420    # 香案：水平中心 / 底边
PERSON_LEFT, PERSON_TOP, PERSON_W = 14, 220, 194    # 人物画布左上角与宽度
PERSON_H = round(PERSON_W * 450 / 436)             # 帧画布 436x450
SHADOW_CX, SHADOW_TOP, SHADOW_W = 78, 406, 112
SMOKE_W, SMOKE_H = 78, 150
BADGE_RIGHT, BADGE_BOTTOM = 12, 12
CHIPS_TOP, CHIPS_LEFT = 12, 12
TOOLS_TOP, TOOLS_RIGHT = 12, 12

SCENES = [
    dict(key="wealth", label="财运", name="财运 · 财神爷", god="god_caishen", godW=150,
         altar="altar_wealth", altarW=206, accent=(242, 199, 92), chips=("财运", "涨停", "健康", "考研"),
         smoke=(0.470, 0.296)),
    dict(key="stock", label="涨停", name="涨停 · 暴富牛神", god="god_bull", godW=212,
         altar="altar_stock", altarW=214, accent=(226, 69, 60), chips=("财运", "涨停", "健康", "考研"),
         smoke=(0.156, 0.280)),
    dict(key="health", label="健康", name="健康 · 长寿星", god="god_shouxing", godW=146,
         altar="altar_health", altarW=216, accent=(70, 192, 138), chips=("财运", "涨停", "健康", "考研"),
         smoke=(0.710, 0.308)),
    dict(key="study", label="考研", name="考研 · 文昌帝君", god="god_wenchang", godW=134,
         altar="altar_study", altarW=198, accent=(90, 169, 242), chips=("财运", "涨停", "健康", "考研"),
         smoke=(0.381, 0.316)),
]
# ==============================================================


def font(sz, bold=False):
    for p in ((r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
              r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def load(name):
    return Image.open(os.path.join(IMG, name + ".png")).convert("RGBA")


def fit(im, css_w):
    h = max(1, round(im.height * css_w / im.width))
    return im.resize((int(css_w), int(h)), Image.LANCZOS)


def desktop_bg(seed):
    yy = np.linspace(0, 1, H)[:, None]
    base = np.zeros((H, W, 3), dtype=np.float32)
    base[:, :, 0] = 226 - yy * 26
    base[:, :, 1] = 231 - yy * 28
    base[:, :, 2] = 239 - yy * 24
    base += np.random.default_rng(seed).normal(0, 2.0, base.shape)
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def shadow():
    im = Image.new("L", (SHADOW_W * 2, 30), 0)
    d = ImageDraw.Draw(im)
    for i in range(30):
        t = abs(i - 15) / 15.0
        d.line([(0, i), (SHADOW_W * 2, i)], fill=int(120 * (1 - t) ** 1.5))
    im = im.filter(ImageFilter.GaussianBlur(6))
    out = Image.new("RGBA", (SHADOW_W * 2, 30), (0, 0, 0, 0))
    out.putalpha(im)
    return out


SH = shadow()


def scene_panel(sc, frame_idx, ui=True):
    canvas = desktop_bg(7 + frame_idx)
    god = fit(load(sc["god"]), sc["godW"])
    altar = fit(load(sc["altar"]), sc["altarW"])
    person = fit(load("kowtow_%d" % frame_idx), PERSON_W)

    ax = ALTAR_CX - altar.width / 2
    ay = ALTAR_BOTTOM_Y - altar.height
    sx = ax + altar.width * sc["smoke"][0]
    sy = ay + altar.height * sc["smoke"][1]

    def paste(im, x, y):
        canvas.alpha_composite(im, (int(round(x)), int(round(y))))

    # 真实层级：佛光(0) -> 香烟(1) -> 神像(2) -> 香案(4) -> 影子(5) -> 人(6)
    smoke = fit(load("smoke"), SMOKE_W)
    smoke.putalpha(smoke.getchannel("A").point(lambda v: int(v * 0.42)))
    paste(smoke, sx - SMOKE_W / 2, sy - SMOKE_H)
    paste(god, GOD_CX - god.width / 2, GOD_BOTTOM_Y - god.height)
    paste(altar, ax, ay)
    paste(SH, SHADOW_CX - SH.width / 2, SHADOW_TOP)
    paste(person, PERSON_LEFT, PERSON_TOP)

    d = ImageDraw.Draw(canvas)

    if ui:
        x = CHIPS_LEFT
        for label in sc["chips"]:
            f = font(12)
            tw = d.textlength(label, font=f)
            cw = int(tw + 22)
            on = (label == sc["label"])
            d.rounded_rectangle((x, CHIPS_TOP, x + cw, CHIPS_TOP + 26), 13,
                                fill=(242, 199, 92, 235) if on else (18, 15, 26, 215),
                                outline=(242, 199, 92, 110))
            d.text((x + 11, CHIPS_TOP + 6), label, font=f,
                   fill=(26, 18, 6) if on else (244, 234, 214))
            x += cw + 6

        f = font(12)
        y = TOOLS_TOP
        for label in ("上香", "缩小", "放大", "退出"):
            tw = d.textlength(label, font=f)
            d.rounded_rectangle((W - TOOLS_RIGHT - tw - 25, y, W - TOOLS_RIGHT, y + 26), 8,
                                fill=(30, 24, 42, 240), outline=(242, 199, 92, 90))
            d.text((W - TOOLS_RIGHT - tw - 12, y + 6), label, font=f, fill=(244, 234, 214))
            y += 32

        f = font(11); fb = font(18, True)
        t1, t2 = "真人 · 总功德", "128,880"
        bw = int(d.textlength(t1, font=f) + d.textlength(t2, font=fb) + 34)
        bx = W - BADGE_RIGHT - bw
        by = H - BADGE_BOTTOM - 30
        d.rounded_rectangle((bx, by, W - BADGE_RIGHT, by + 30), 15,
                            fill=(30, 23, 12, 240), outline=(242, 199, 92, 140))
        d.text((bx + 13, by + 9), t1, font=f, fill=(200, 190, 170))
        d.text((bx + 13 + d.textlength(t1, font=f) + 8, by + 3), t2, font=fb, fill=(242, 199, 92))

        f = font(11, True)
        s = "点小人磕头 · 空格同效 · 右键换朝拜对象"
        tw = d.textlength(s, font=f)
        d.text((CHIPS_LEFT, H - BADGE_BOTTOM - 16), s, font=f, fill=(120, 105, 80))

        ff = font(18, True)
        d.text((PERSON_LEFT + 96, PERSON_TOP + 20), sc["label"] + " +1", font=ff, fill=sc["accent"])
        coin = fit(load("coin"), 32)
        paste(coin, PERSON_LEFT + 78, PERSON_TOP + 34)

    # 窗口边框 + 中线 + 地面
    d.rectangle((0, 0, W - 1, H - 1), outline=(255, 0, 200, 255), width=1)
    d.line([(W // 2, 0), (W // 2, H)], fill=(255, 0, 200, 55), width=1)
    d.line([(0, ALTAR_BOTTOM_Y), (W, ALTAR_BOTTOM_Y)], fill=(0, 200, 0, 120), width=1)

    # 香烟落点校验：红十字 = renderer.js 里 smokeLayer 的 (left+width/2, top+height)
    d.ellipse((sx - 10, sy - 10, sx + 10, sy + 10), outline=(255, 0, 200, 255), width=2)
    d.line([(sx - 16, sy), (sx + 16, sy)], fill=(255, 0, 0, 255), width=1)
    d.line([(sx, sy - 16), (sx, sy + 16)], fill=(255, 0, 0, 255), width=1)
    return canvas


# 1) 单张全尺寸（最常用）——财运 / 第 1 帧
scene_panel(SCENES[0], 1).convert("RGB").save(os.path.join(OUTDIR, "layout_mock_1.png"))
# 2) 四个场景并排
panels = [scene_panel(sc, 1) for sc in SCENES]
gap = 14
sheet = Image.new("RGB", (W * len(panels) + gap * (len(panels) - 1), H), (250, 250, 252))
for i, p in enumerate(panels):
    sheet.paste(p.convert("RGB"), (i * (W + gap), 0))
sheet.save(os.path.join(OUTDIR, "layout_mock.png"))
# 3) 同一场景三个磕头帧并排，检查动作位移
kpanels = [scene_panel(SCENES[0], i, ui=False) for i in (1, 2, 3)]
ksheet = Image.new("RGB", (W * 3 + gap * 2, H), (250, 250, 252))
for i, p in enumerate(kpanels):
    ksheet.paste(p.convert("RGB"), (i * (W + gap), 0))
ksheet.save(os.path.join(OUTDIR, "layout_mock_frames.png"))

# 4) 无 UI 的纯净版（看构图本身）
scene_panel(SCENES[0], 1, ui=False).convert("RGB").save(os.path.join(OUTDIR, "layout_clean.png"))

# 5) 抽烟图层诊断：烟雾满不透明 + 红框标出图层范围，确认素材与落点
sc = SCENES[0]
altar = fit(load(sc["altar"]), sc["altarW"])
ax = ALTAR_CX - altar.width / 2
ay = ALTAR_BOTTOM_Y - altar.height
bx = ax + altar.width * sc["smoke"][0]
by = ay + altar.height * sc["smoke"][1]
dbg = desktop_bg(9)
smoke = fit(load("smoke"), SMOKE_W)
dbg.alpha_composite(smoke, (int(bx - SMOKE_W / 2), int(by - SMOKE_H)))
dbg.alpha_composite(altar, (int(ax), int(ay)))
d = ImageDraw.Draw(dbg)
d.rectangle((bx - SMOKE_W / 2, by - SMOKE_H, bx + SMOKE_W / 2, by), outline=(255, 0, 200), width=1)
d.line([(bx - 14, by), (bx + 14, by)], fill=(255, 0, 0), width=1)
d.line([(bx, by - 14), (bx, by + 14)], fill=(255, 0, 0), width=1)
dbg.convert("RGB").save(os.path.join(OUTDIR, "smoke_layer_check.png"))

print("ok", W, H, "person", PERSON_W, "x", PERSON_H)
