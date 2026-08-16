# -*- coding: utf-8 -*-
"""
preview_photo_patterns.py ― 追加写真の配置パターン比較画像を出力

本編フレーム（写真抜き）を土台に、写真を複数の位置/サイズ/傾きで合成して2x3グリッド表示。
output/photo_patterns.png に書き出す。
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_ymm4 as B                 # make_photo_paste / IMAGES を流用
from preview_frame import render_image, W, H

YMMP = HERE.parent / "output" / "AI_History_Ep1.ymmp"
OUT = HERE.parent / "output" / "photo_patterns.png"
PHOTO = "photo_karakuri.jpg"           # 見本に使う写真（id18）

def ttf(s):
    for ff in [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc"]:
        try: return ImageFont.truetype(ff, s)
        except Exception: pass
    return ImageFont.load_default()

# (ラベル, 中心px(x,y), 高さpx, 傾き)
PATTERNS = [
    ("A 右下に重ね(大)",   (1150, 500), 280, -6),
    ("B 左下に重ね(大)",   (770, 500),  280,  5),
    ("C カード上の空き帯", (1075, 150), 190, -5),
    ("D 中央に大きく重ね", (960, 450),  300, -4),
    ("E 右下コーナー小",   (1215, 560), 200, -7),
    ("F 左下コーナー小",   (745, 560),  200,  6),
]

def photo_frame():
    d = json.load(open(YMMP, encoding="utf-8-sig"))
    for x in d["Timelines"][0]["Items"]:
        if "karakuri" in x.get("FilePath", "") and "photo_" in x.get("FilePath", ""):
            return x.get("Frame", 0) + 90
    return 13900

def main():
    fr = photo_frame()
    base = render_image(YMMP, fr, skip_substr="photo_").convert("RGBA")   # 写真抜きの土台
    src = B.IMAGES / PHOTO
    cols, rows = 3, 2
    cw, ch = 620, 349                     # セル(縮小フレーム)サイズ
    pad_top = 40
    grid = Image.new("RGB", (cw*cols, (ch+pad_top)*rows), (25, 25, 28))
    gd = ImageDraw.Draw(grid)
    for idx, (label, (px, py), hpx, tilt) in enumerate(PATTERNS):
        frame = base.copy()
        photo = Image.open(B.make_photo_paste(src, tilt)).convert("RGBA")
        z = hpx / photo.height
        photo = photo.resize((max(1, int(photo.width*z)), max(1, int(photo.height*z))))
        frame.alpha_composite(photo, (int(px - photo.width/2), int(py - photo.height/2)))
        cell = frame.convert("RGB").resize((cw, ch))
        ox, oy = (idx % cols)*cw, (idx//cols)*(ch+pad_top)
        gd.rectangle([ox, oy, ox+cw, oy+pad_top], fill=(16, 62, 48))
        gd.text((ox+12, oy+6), label, font=ttf(26), fill=(255, 224, 90))
        grid.paste(cell, (ox, oy+pad_top))
    grid.save(OUT); print("出力:", OUT)

if __name__ == "__main__":
    main()
