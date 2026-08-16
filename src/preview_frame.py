# -*- coding: utf-8 -*-
"""
preview_frame.py ― ymmpの指定フレームをPILで簡易合成して確認用PNGを出す（YMM4代理検証）

YMM4を起動せずにレイアウト（かぶり/前後関係/位置）を目視するための近似レンダラ。
ImageItem/TextItem を Layer昇順（大きいほど前面）で重ね描き。VideoItemはffmpegで1枚抜く。
TachieItem(口パクSD)は合成対象外＝代わりにグレー枠で位置だけ示す。

使い方:  py src/preview_frame.py <ymmp> <frame> [出力png]
"""
from __future__ import annotations
import sys, json, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080

def _font(size):
    for ff in [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc"]:
        try: return ImageFont.truetype(ff, int(size))
        except Exception: pass
    return ImageFont.load_default()

def _argb(s, default=(255, 255, 255, 255)):
    if not s or not s.startswith("#") or len(s) < 9: return default
    a = int(s[1:3], 16); r = int(s[3:5], 16); g = int(s[5:7], 16); b = int(s[7:9], 16)
    return (r, g, b, a)

def _val(node, d=0.0):
    try: return float(node["Values"][0]["Value"])
    except Exception: return d

_ANCHOR = {"LeftTop": "la", "CenterBottom": "md", "CenterCenter": "mm", "CenterTop": "ma", "MiddleCenter": "mm"}

def video_frame(fp):
    try:
        tmp = Path(tempfile.gettempdir()) / ("pv_" + Path(fp).stem + ".png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(fp), "-frames:v", "1", str(tmp)],
                       capture_output=True)
        if tmp.exists(): return Image.open(tmp).convert("RGBA")
    except Exception: pass
    return None

def render_image(ymmp, frame, skip_substr=None):
    d = json.load(open(ymmp, encoding="utf-8-sig"))
    tl = d["Timelines"][0]; items = tl["Items"]
    bg = _argb(tl["VideoInfo"].get("BackgroundColor", "#FF202B25"))
    canvas = Image.new("RGBA", (W, H), bg[:3] + (255,))
    active = [x for x in items if x.get("Frame", 0) <= frame < x.get("Frame", 0) + x.get("Length", 0)
              and not (skip_substr and skip_substr in x.get("FilePath", ""))]
    active.sort(key=lambda x: (x.get("Layer", 0), items.index(x)))
    dr = ImageDraw.Draw(canvas)
    for x in active:
        t = x.get("$type", "")
        X = _val(x.get("X", {})); Y = _val(x.get("Y", {})); zoom = _val(x.get("Zoom", {}), 100.0)
        cx = W/2 + X; cy = H/2 + Y
        if "ImageItem" in t:
            fp = x.get("FilePath")
            if not fp or not Path(fp).exists(): continue
            im = Image.open(fp).convert("RGBA")
            nw = max(1, int(im.width*zoom/100)); nh = max(1, int(im.height*zoom/100))
            im = im.resize((nw, nh))
            canvas.alpha_composite(im, (int(cx-nw/2), int(cy-nh/2)))
        elif "VideoItem" in t:
            im = video_frame(x.get("FilePath"))
            if im is None:
                dr.rectangle([cx-200, cy-120, cx+200, cy+120], outline=(120,120,120,255), width=3)
                dr.text((cx-190, cy-10), f"[VIDEO {Path(x.get('FilePath','')).name}]", font=_font(22), fill=(160,160,160,255))
                continue
            z = zoom/100 if zoom else min(W/im.width, H/im.height)
            nw, nh = int(im.width*z), int(im.height*z); im = im.resize((max(1,nw), max(1,nh)))
            canvas.alpha_composite(im, (int(cx-nw/2), int(cy-nh/2)))
        elif "TextItem" in t:
            txt = x.get("Text", ""); size = _val(x.get("FontSize", {}), 44.0)
            col = _argb(x.get("FontColor", "#FFFFFFFF")); bcol = _argb(x.get("StyleColor", "#FF101820"))
            anc = _ANCHOR.get(x.get("BasePoint", "CenterBottom"), "md")
            f = _font(size)
            sw = 3 if x.get("Style") == "Border" else 0
            al_h = "left" if anc.startswith("l") else "center"   # BasePointに合わせた整列(YMM4準拠)
            mw = _val(x.get("MaxWidth", {}), 0.0)                 # MaxWidthで折返し（YMM4準拠の近似）＝字幕幅を正確に
            if mw and "\n" not in txt:
                _ls, _cur = [], ""
                for _ch in txt:
                    if dr.textlength(_cur + _ch, font=f) > mw and _cur: _ls.append(_cur); _cur = _ch
                    else: _cur += _ch
                if _cur: _ls.append(_cur)
                txt = "\n".join(_ls)
            dr.multiline_text((cx, cy), txt, font=f, fill=col, anchor=anc, align=al_h,
                              stroke_width=sw, stroke_fill=bcol, spacing=6)
        elif "TachieItem" in t:
            # 口パクSDは合成不可→位置ガイド枠のみ。zoomに連動して実サイズ相当の枠を描く（基準:zoom22→約420×520px）
            zt = zoom if zoom else 22.0
            hw = int(265 * zt / 22.0); hh = int(320 * zt / 22.0)   # 実機実測に合わせた係数（z22で約530幅）
            dr.rectangle([cx-hw, cy-hh, cx+hw, cy+hh], outline=(90,200,120,180), width=3)
            dr.text((cx-hw+8, cy-hh+4), f"[立ち絵 z{int(zt)}]", font=_font(18), fill=(90,200,120,220))
    return canvas

def render(ymmp, frame, out):
    canvas = render_image(ymmp, frame)
    canvas.convert("RGB").save(out)
    print(f"frame {frame} -> {out}")

if __name__ == "__main__":
    ymmp = sys.argv[1]; frame = int(sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else "output/preview_frame.png"
    render(ymmp, frame, out)
