# -*- coding: utf-8 -*-
"""
preview_surprise_options.py ― 驚き演出の代替案を立ち絵に合成した比較画像を出力

「！」以外の候補を目視選択するため。output/surprise_options.png に2x3グリッドで書き出す。
"""
from __future__ import annotations
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
CHARS = ROOT / "assets" / "characters"
OUT = ROOT / "output" / "surprise_options.png"

def ttf(s):
    for ff in [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc"]:
        try: return ImageFont.truetype(ff, s)
        except Exception: pass
    return ImageFont.load_default()

E = 300  # 効果キャンバス

def e_konsen():   # A: 集中線
    im = Image.new("RGBA", (E, E), (0,0,0,0)); d = ImageDraw.Draw(im); c = E/2; n = 72
    for k in range(n):
        a = k*(2*math.pi/n); r0, r1 = E*0.30, E*0.50; w = 7 if k%2==0 else 3
        d.line([c+r0*math.cos(a), c+r0*math.sin(a), c+r1*math.cos(a), c+r1*math.sin(a)], fill=(255,255,255,220), width=w)
    return im

def e_bikkuri2():  # B: ！？二重マーク
    im = Image.new("RGBA", (E, E), (0,0,0,0)); d = ImageDraw.Draw(im); f = ttf(int(E*0.7))
    d.text((E*0.16, E*0.06), "!?", font=f, fill=(230,48,44,255), stroke_width=10, stroke_fill=(255,255,255,255))
    return im

def e_shock():    # C: 稲妻ショック
    im = Image.new("RGBA", (E, E), (0,0,0,0)); d = ImageDraw.Draw(im); c = E/2
    for a0 in (0.15, 2.2, 4.3):
        pts=[]; a=a0
        for i in range(5):
            r = E*0.22 if i%2==0 else E*0.42
            pts.append((c+r*math.cos(a), c*0.9+r*math.sin(a))); a += 0.5
        d.line(pts, fill=(255,214,56,255), width=10, joint="curve")
    d.ellipse([c-14,c*0.9-14,c+14,c*0.9+14], fill=(255,255,255,255))
    return im

def e_don():      # D: ドーン！文字
    im = Image.new("RGBA", (E, E), (0,0,0,0)); d = ImageDraw.Draw(im); f = ttf(int(E*0.30))
    txt="ドーン！"; tw=d.textlength(txt,font=f)
    d.text((E/2-tw/2, E*0.36), txt, font=f, fill=(255,70,60,255), stroke_width=9, stroke_fill=(255,240,180,255))
    return im

def e_sweat():    # E: びっくり＋汗
    im = Image.new("RGBA", (E, E), (0,0,0,0)); d = ImageDraw.Draw(im); f = ttf(int(E*0.6))
    d.text((E*0.30, E*0.05), "!", font=f, fill=(230,48,44,255), stroke_width=9, stroke_fill=(255,255,255,255))
    for (x,y,s) in [(E*0.70,E*0.30,26),(E*0.78,E*0.52,20)]:   # 汗
        d.ellipse([x-s*0.7,y,x+s*0.7,y+s*1.6], fill=(120,200,255,235), outline=(255,255,255,220), width=2)
    return im

def e_flash():    # F: 白フラッシュ枠
    im = Image.new("RGBA", (E, E), (0,0,0,0)); d = ImageDraw.Draw(im); c=E/2
    for r,al in [(E*0.48,60),(E*0.40,110),(E*0.30,200)]:
        d.ellipse([c-r,c-r,c+r,c+r], fill=(255,255,240,al))
    return im.filter(ImageFilter.GaussianBlur(6))

OPTIONS = [("A: 集中線", e_konsen), ("B: !? マーク", e_bikkuri2), ("C: 稲妻ショック", e_shock),
           ("D: ドーン！文字", e_don), ("E: びっくり＋汗", e_sweat), ("F: 白フラッシュ", e_flash)]

def main():
    ch = CHARS/"akane"/"surprise.png"
    if not ch.exists(): ch = CHARS/"akane"/"normal.png"
    chara = Image.open(ch).convert("RGBA")
    CH = 300; cw = int(chara.width*CH/chara.height); chara = chara.resize((cw, CH))
    CW, CHH = 380, 460; cols = 3; rows = 2
    grid = Image.new("RGB", (CW*cols, CHH*rows), (16,62,48))
    for idx,(label,fn) in enumerate(OPTIONS):
        cell = Image.new("RGBA", (CW, CHH), (16,62,48,255)); dd=ImageDraw.Draw(cell)
        dd.rectangle([0,0,CW-1,CHH-1], outline=(120,84,46), width=6)
        cell.alpha_composite(chara, ((CW-cw)//2, CHH-CH-10))
        eff = fn(); es = 250; eff = eff.resize((es,es))
        cell.alpha_composite(eff, ((CW-es)//2, 40))   # 頭上
        dd.text((14,10), label, font=ttf(30), fill=(255,224,90,255))
        grid.paste(cell.convert("RGB"), ((idx%cols)*CW, (idx//cols)*CHH))
    grid.save(OUT); print("出力:", OUT)

if __name__ == "__main__":
    main()
