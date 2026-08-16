# -*- coding: utf-8 -*-
r"""
gen_iodine_tablet_fig.py ― 安定ヨウ素剤(ヨウ化カリウム)の「年齢別 用法用量」図（自作・コード描画・大文字）。
添付文書(ヨウ化カリウム内用ゼリー/丸「日医工」2024/12改訂 第3版)の用法用量に厳密準拠：
  新生児(〜1ヶ月)=ゼリー16.3mg／1ヶ月〜3歳未満=ゼリー32.5mg／3〜13歳未満=丸1丸(50mg)／13歳以上=丸2丸(100mg)。原則単回。
※旧図は「丸50mg(3歳以上)」だけで13歳以上=2丸100mgが抜け、"3歳以上一律50mg"と誤読しうる不正確があった→是正。スマホ可読性で文字大。
出力: C:\claude_shared\素材DB\医療\薬剤_ヨウ素剤\安定ヨウ素剤_3規格_オリジナル.png
"""
from PIL import Image, ImageDraw, ImageFont

OUT = r"C:\claude_shared\素材DB\医療\薬剤_ヨウ素剤\安定ヨウ素剤_3規格_オリジナル.png"
W, H = 1240, 900
im = Image.new("RGBA", (W, H), (255, 255, 255, 0))
d = ImageDraw.Draw(im)


def F(px, bold=True):
    for ff in ([r"C:\Windows\Fonts\YuGothB.ttc"] if bold else [r"C:\Windows\Fonts\YuGothM.ttc"]):
        try:
            return ImageFont.truetype(ff, px)
        except Exception:
            pass
    return ImageFont.load_default()


PINK, PINKD = (232, 96, 140), (198, 66, 108)
BLUE, BLUED = (64, 138, 212), (40, 108, 178)
GOLD, GOLDD = (214, 170, 46), (176, 134, 22)
INK = (40, 44, 52)


def pill(cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(122, 76, 54), outline=(92, 56, 40), width=3)
    d.ellipse([cx - r * 0.4 - 8, cy - r * 0.4 - 8, cx - r * 0.4 + 8, cy - r * 0.4 + 8], fill=(212, 192, 172, 230))


def jelly(cx, cy, col, cold):
    # 内用ゼリーの実剤形＝スティック分包（細長いパウチ・上下クリンプシール）。瓶に見えないよう細長く。
    w, h = 40, 150
    x0, y0, x1, y1 = cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2
    seal = 15                                                                 # 上下シール帯
    d.rectangle([x0, y0 + seal, x1, y1 - seal], fill=col, outline=cold)       # 中央のゼリー部
    d.rectangle([x0 - 6, y0, x1 + 6, y0 + seal], fill=cold)                   # 上シール（少し横広）
    d.rectangle([x0 - 6, y1 - seal, x1 + 6, y1], fill=cold)                   # 下シール
    for sx in range(x0 - 6, x1 + 6, 7):                                       # クリンプ（ギザギザ外縁）
        d.polygon([(sx, y0), (sx + 3, y0 - 6), (sx + 7, y0)], fill=cold)
        d.polygon([(sx, y1), (sx + 3, y1 + 6), (sx + 7, y1)], fill=cold)
    d.line([(x0 + 9, y0 + seal + 6), (x0 + 9, y1 - seal - 6)], fill=(255, 255, 255), width=4)  # 縦ハイライト（つや）


# ※内部ヘッダは削除（カード側の「安定ヨウ素剤」タイトルと重複＋薄くなるため。ユーザー指摘）。用量表を大きく。
rows = [
    ("新生児（生後1ヶ月未満）", "内用ゼリー", "16.3mg", "jelly", PINK, PINKD),
    ("生後1ヶ月〜3歳未満",     "内用ゼリー", "32.5mg", "jelly", BLUE, BLUED),
    ("3歳〜13歳未満",          "丸　1丸",   "50mg",   "pill1", GOLD, GOLDD),
    ("13歳以上",               "丸　2丸",   "100mg",  "pill2", GOLD, GOLDD),
]
y = 40
rh = 200
for age, form, dose, kind, col, cold in rows:
    d.rounded_rectangle([28, y, W - 28, y + rh - 20], radius=20, fill=(248, 250, 253), outline=cold, width=3)
    cy = y + (rh - 20) // 2
    # 左：年齢
    d.text((56, cy - 26), age, font=F(44), fill=INK)
    # 中：アイコン
    ix = 620
    if kind == "jelly":
        jelly(ix, cy, col, cold)
    elif kind == "pill1":
        pill(ix, cy, 30)
    else:
        pill(ix - 26, cy, 30); pill(ix + 26, cy, 30)
    # 右：剤形＋用量（大きく）
    d.text((720, cy - 40), form, font=F(40), fill=cold)
    d.text((720, cy + 4), dose, font=F(58), fill=cold)
    y += rh

d.text((28, H - 56), "※放射性ヨウ素による甲状腺の内部被曝の予防・低減。原則1回。〔添付文書（日医工）準拠〕", font=F(26), fill=(90, 96, 104))

im.save(OUT)
print("[ok]", OUT, im.size)
