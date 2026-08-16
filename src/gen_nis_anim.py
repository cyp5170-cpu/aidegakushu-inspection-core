# -*- coding: utf-8 -*-
"""NIS機構図のアニメーション版（Claude専有・src/）。

承認済みの静止画 gen_medical_schematics.gen_nis_simple() のレイアウト・座標系を
そのまま踏襲し、「流れ」だけを時間発展させた3秒シームレスループを生成する。

動きの物語（1ループ）:
  ① Na/K-ATPase が拍動（Na+を外へ3・K+を中へ2）＝Na+勾配を維持＝動力
  ② 血液側で Na+・I- が運び屋(NIS)に結合
  ③「構造変化」の光が弧を左→右へ走る
  ④ 細胞側で放出
  ⑤ I- が濃縮（呼吸するように脈動）
  ・血液側 Na+勾配クラスタはシマー

設計方針:
  - 静止画生成 gen_nis_simple() は温存（このファイルは import して定数/ヘルパを流用）。
  - 静的要素はベース画像を1回だけ描画→各フレームで動く要素のみ重ねる（高速・決定的）。
  - phase p∈[0,1) を全モーションの周期パラメータにし、末尾→先頭が連続＝シームレス。

出力:
  py src/gen_nis_anim.py            → MP4(ループ) + APNG を素材DBへ
  py src/gen_nis_anim.py --preview  → 軽量GIF(モック確認用)をscratchpadへ
"""
import os, sys, math
from PIL import Image, ImageDraw

# 承認済み静止画ジェネレータから定数・ヘルパを流用（__main__ガード有りなので副作用なし）
from gen_medical_schematics import (
    _vgrad, _font, _membrane, _arrow_head, BG_TOP, BG_BOT, IODINE, IODINE_D, MOL,
)

# ---- 静止画 gen_nis_simple と完全一致の配色・寸法 ---------------------------
W, H = 1600, 900
CHALK=(232,238,246); DARK=(66,48,42)
COLLOID=(236,222,212); CELLPINK=(238,198,192); NUC=(188,118,108)
NA=(245,165,60); NA_D=(205,130,35); K=(90,200,150); K_D=(55,150,110)
TEAL_=(72,176,164); TEALD_=(40,130,120); PUMP=(70,120,195); PUMPD=(45,85,150)
FUN=(194,203,214); FUNFILL=(42,52,59)
BLOOD=(138,60,62); CAP=(214,86,78)

gpx,gpy,tw = 64,120,86
ccx,ccy = 246,300
mfx,mfy,mfr = ccx-40, ccy+40, 25
fcx,fcy,R = 160,590,120; rin=R-42
PX0,PX1 = 430,1575; BOXT,BOXB = 150,860
mem_y0 = 430; band_h = 88; mid = mem_y0+band_h//2
px = 640            # Na/K-ATPase ポンプ中心
lx2, rx2 = 1080, 1420   # 運び屋：血液側で結合 / 細胞側で放出

# 弧（構造変化）の楕円パラメータ  d.arc([lx2+40,308,rx2-40,478],180,360)
_ax0,_ay0,_ax1,_ay1 = lx2+40,308,rx2-40,478
arc_cx,arc_cy = (_ax0+_ax1)/2,(_ay0+_ay1)/2
arc_rx,arc_ry = (_ax1-_ax0)/2,(_ay1-_ay0)/2

FRAMES = 90        # 3.0s @30fps
FPS = 30


def _fonts():
    return dict(fTitle=_font(38), fL2=_font(32), fS=_font(28), fXS=_font(23), fLoc=_font(29))


# ---- 描画ヘルパ（gen_nis_simple 準拠、alpha対応を追加） --------------------
def _ctext(d, cx, y, t, f, fill, a=255):
    w=d.textlength(t,font=f); d.text((cx-w/2,y),t,font=f,fill=fill+(a,)); return w


def _lbox(d, cx, cy, t, f, tip=None, fill=(8,16,22), txt=CHALK, oc=(150,166,182), ow=2):
    w=d.textlength(t,font=f); h=f.size; pad=13
    if tip:
        d.line([(cx,cy),tip],fill=(150,166,182,255),width=3)
        d.ellipse([tip[0]-6,tip[1]-6,tip[0]+6,tip[1]+6],fill=(150,166,182,255))
    d.rounded_rectangle([cx-w/2-pad,cy-h/2-8,cx+w/2+pad,cy+h/2+10],radius=11,fill=fill+(236,),outline=oc+(255,),width=ow)
    d.text((cx-w/2,cy-h/2-1),t,font=f,fill=txt+(255,))


def _ball_lbl(d, cx, cy, r, col, cold, lab, a=255):
    """ラベル付き球（alpha対応）。"""
    d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=col+(a,),outline=cold+(a,),width=2)
    sz=int(r*1.15); bf=_font(sz,bold=True); bb=d.textbbox((0,0),lab,font=bf)
    while sz>9 and (bb[2]-bb[0])>2*r-5:
        sz-=1; bf=_font(sz,bold=True); bb=d.textbbox((0,0),lab,font=bf)
    d.text((cx-(bb[2]-bb[0])/2, cy-(bb[3]-bb[1])/2-bb[1]), lab, font=bf, fill=(255,255,255,a))


def _mini_follicle(d, cx, cy, r):
    d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=CELLPINK+(255,),outline=(198,140,128,255),width=2)
    ri=r*0.6; d.ellipse([cx-ri,cy-ri,cx+ri,cy+ri],fill=COLLOID+(255,),outline=(210,152,124,255),width=2)
    for ang in range(0,360,51):
        nx=cx+math.cos(math.radians(ang))*(r-4); ny=cy+math.sin(math.radians(ang))*(r-4)
        d.ellipse([nx-3,ny-3,nx+3,ny+3],fill=NUC+(255,))


def _carrier_body(d, cx, open_up):
    bw,top,bot=76,mem_y0-52,mem_y0+band_h+52
    d.rounded_rectangle([cx-bw,top,cx+bw,bot],radius=30,fill=TEAL_+(255,),outline=TEALD_+(255,),width=6)
    if open_up: cav=[(cx-48,top-2),(cx+48,top-2),(cx+20,mid+12),(cx-20,mid+12)]
    else:       cav=[(cx-48,bot+2),(cx+48,bot+2),(cx+20,mid-12),(cx-20,mid-12)]
    d.polygon(cav,fill=(30,20,22,255) if open_up else CELLPINK+(255,))


def _pump_body(d, cx):
    fS=_fonts()['fL2']
    d.rounded_rectangle([cx-78,mem_y0-58,cx+78,mem_y0+band_h+58],radius=30,fill=PUMP+(255,),outline=PUMPD+(255,),width=6)
    d.ellipse([cx-26,mid-26,cx+26,mid+26],fill=(40,80,140,255))
    _ctext(d,cx,mid-16,"P",fS,(240,205,110))


# ---- 静的ベース（毎フレーム不変な要素をすべて描画） -----------------------
def build_base():
    im=_vgrad(W,H,BG_TOP,BG_BOT); d=ImageDraw.Draw(im)
    F=_fonts(); fTitle,fL2,fS,fXS,fLoc=F['fTitle'],F['fL2'],F['fS'],F['fXS'],F['fLoc']

    _ctext(d,W/2,16,"NIS（Na+/I-シンポーター）＝基底膜の運び屋。動力＝Na/K-ATPase",fTitle,CHALK)

    # --- 入れ子ロケーター（甲状腺→濾胞→膜） ---
    try:
        thy=Image.open(r"C:\claude_shared\素材DB\医療\解剖_臓器別\甲状腺_servier模式図.png").convert("RGBA")
        th=int(thy.height*tw/thy.width); thy=thy.resize((tw,th))
    except Exception:
        thy=None; th=84
    gbx,gby=gpx+tw//2+13,gpy+th//2
    zbx,zby=fcx+math.cos(math.radians(-6))*(R-6),fcy+math.sin(math.radians(-6))*(R-6)
    d.polygon([(gbx-12,gby+11),(ccx-94,ccy-46),(ccx+94,ccy-46),(gbx+12,gby+11)],fill=FUNFILL)
    d.polygon([(mfx-mfr-3,mfy+mfr+3),(fcx-R,fcy-R+4),(fcx+R,fcy-R+4),(mfx+mfr+3,mfy+mfr+3)],fill=FUNFILL)
    d.polygon([(zbx+32,zby-24),(430,300),(430,842),(zbx+32,zby+24)],fill=FUNFILL)
    for (a,b) in [((gbx-12,gby+11),(ccx-94,ccy-46)),((gbx+12,gby+11),(ccx+94,ccy-46)),
                  ((mfx-mfr-3,mfy+mfr+3),(fcx-R,fcy-R+4)),((mfx+mfr+3,mfy+mfr+3),(fcx+R,fcy-R+4)),
                  ((zbx+32,zby-24),(430,300)),((zbx+32,zby+24),(430,842))]:
        d.line([a,b],fill=FUN+(255,),width=3)
    if thy is not None: im.paste(thy,(gpx,gpy),thy)
    d.rectangle([gbx-12,gby-11,gbx+12,gby+11],outline=FUN+(255,),width=3)
    for (dx,dy,rr) in [(0,-6,30),(-54,-13,22),(52,-9,25),(35,40,22),(2,50,20),(65,27,17)]:
        _mini_follicle(d,ccx+dx,ccy+dy,rr)
    _mini_follicle(d,mfx,mfy,mfr); d.rectangle([mfx-mfr-3,mfy-mfr-3,mfx+mfr+3,mfy+mfr+3],outline=FUN+(255,),width=3)
    d.ellipse([fcx-R,fcy-R,fcx+R,fcy+R],fill=CELLPINK+(255,),outline=(198,140,128,255),width=3)
    d.ellipse([fcx-rin,fcy-rin,fcx+rin,fcy+rin],fill=COLLOID+(255,),outline=(210,152,124,255),width=3)
    for ang in range(0,360,28):
        nx=fcx+math.cos(math.radians(ang))*(R-20); ny=fcy+math.sin(math.radians(ang))*(R-20)
        d.ellipse([nx-6,ny-6,nx+6,ny+6],fill=NUC+(255,))
    for ang in range(0,360,24):
        cx2=fcx+math.cos(math.radians(ang))*(R+26); cy2=fcy+math.sin(math.radians(ang))*(R+26)
        d.ellipse([cx2-7,cy2-7,cx2+7,cy2+7],fill=CAP+(255,),outline=(150,45,42,255),width=1)
    d.rectangle([zbx-32,zby-24,zbx+32,zby+24],outline=FUN+(255,),width=4)
    _ctext(d,gpx+tw//2,92,"甲状腺",fLoc,CHALK)
    _ctext(d,232,236,"濾胞の集まり（組織）",fLoc,CHALK)
    _ctext(d,fcx,fcy-8,"コロイド",fLoc,DARK)
    _ctext(d,fcx,fcy+R+58,"濾胞（1個）",fLoc,CHALK)
    _lgy=fcy+R+112
    d.ellipse([76-11,_lgy-11,76+11,_lgy+11],fill=CAP+(255,),outline=(150,45,42,255),width=2)
    d.text((96,_lgy-16),"＝毛細血管（血液）",font=fS,fill=(255,200,200,255))

    # --- 膜ボックス（血液/細胞ゾーン＋リン脂質） ---
    mem_y0_=mem_y0
    d.rounded_rectangle([PX0,BOXT,PX1,BOXB],radius=18,outline=FUN+(255,),width=4)
    d.rectangle([PX0+4,BOXT+3,PX1-4,mem_y0_+4],fill=BLOOD+(255,))
    d.rectangle([PX0+4,mem_y0_+band_h-4,PX1-4,BOXB-3],fill=CELLPINK+(255,))
    _membrane(d,mem_y0_,PX1-4,band_h,x0=PX0+4)

    # --- ポンプ本体＋方向矢印＋ラベル（球は動くのでベースには入れない） ---
    _pump_body(d,px)
    _arrow_head(d,(px-34,mem_y0-150),(px-34,mem_y0+30),16,NA); d.line([(px-34,mem_y0+30),(px-34,mem_y0-150)],fill=NA+(255,),width=6)
    _arrow_head(d,(px+40,mem_y0+band_h+150),(px+40,mem_y0+band_h-20),16,K); d.line([(px+40,mem_y0+band_h-20),(px+40,mem_y0+band_h+150)],fill=K+(255,),width=6)
    _ctext(d,px,mid+30,"ATP→ADP",fXS,(240,205,110))
    _lbox(d,px,mem_y0-244,"Na/K-ATPase（動力源）",fS,tip=(px,mem_y0-58),txt=(180,210,255),oc=PUMP,ow=3)
    _ctext(d,px-128,mem_y0-206,"Na+を外へ(3)",fXS,(250,190,120))
    _ctext(d,px+152,mem_y0+band_h+108,"K+を中へ(2)",fXS,(60,175,125))

    # --- 運び屋の本体（左=血液側で結合 / 右=細胞側で放出）＋ラベル ---
    _carrier_body(d,lx2,True)
    _carrier_body(d,rx2,False)
    # 構造変化の弧（薄い下地。走光は動的に重ねる）
    d.arc([_ax0,_ay0,_ax1,_ay1],start=180,end=360,fill=(CHALK[0],CHALK[1],CHALK[2],70),width=10)
    _arrow_head(d,(rx2-44,400),(rx2-90,346),24,CHALK)
    _ctext(d,(lx2+rx2)//2,280,"構造変化",fS,CHALK)
    _lbox(d,lx2,mem_y0-170,"①血液側で結合",fS,tip=(lx2,mem_y0-40),txt=(238,214,250))
    _lbox(d,rx2,mem_y0-170,"②細胞側で放出",fS,tip=(rx2,mem_y0-40),txt=(238,214,250))
    _lbox(d,(lx2+rx2)//2,mem_y0-224,"NIS（運び屋）＝2Na+:1I-",fS,txt=(150,222,206),oc=TEAL_,ow=3)

    # --- 勾配ラベル・濃縮ラベル・ゾーン名（球は動的） ---
    _lbox(d,844,262,"Na+が多い＝動力",fXS,fill=(112,46,48),txt=(255,214,166),ow=0)
    _lbox(d,1200,mem_y0+band_h+250,"I-が血液側より20〜40倍に濃縮",fS,fill=(202,152,160),txt=(88,46,116),ow=0)
    _lbox(d,506,BOXB-42,"細胞内",fS,txt=(226,196,248))
    _lbox(d,1516,176,"血液",fS,txt=(255,200,200))
    _lbox(d,858,mem_y0+band_h+34,"基底膜",fS,tip=(858,mem_y0+band_h),txt=CHALK)
    return im.convert("RGBA")


# ---- イージング/ユーティリティ -------------------------------------------
def _ease(t):  # smoothstep
    t=max(0.0,min(1.0,t)); return t*t*(3-2*t)

def _win(p, a, b):  # p が [a,b] にある割合(0..1)、範囲外は None
    if a<=p<=b: return (p-a)/max(1e-6,(b-a))
    return None

def _fade(u, fin=0.15, fout=0.15):  # 端で透明にして出入りを柔らかく
    if u<fin: return u/fin
    if u>1-fout: return (1-u)/fout
    return 1.0


# ---- 動く要素（1フレーム分をベースの複製に重ねる） ------------------------
def draw_movers(base, p):
    im=base.copy(); d=ImageDraw.Draw(im,"RGBA")

    # ① ポンプ：Na+を外へ(3) 細胞→血液（上昇）
    y_cell, y_blood = mem_y0+30, mem_y0-176
    for i in range(3):
        pi=(p+i/3.0)%1.0
        y=y_cell+(y_blood-y_cell)*_ease(pi)
        a=int(255*_fade(pi))
        _ball_lbl(d, px-34+math.sin(pi*math.pi)* -6, y, 17, NA, NA_D, "Na+", a)
    # ① ポンプ：K+を中へ(2) 血液側→細胞（下降）
    y_ks, y_ke = mem_y0+band_h-20, mem_y0+band_h+176
    for i in range(2):
        pi=(p+i/2.0)%1.0
        y=y_ks+(y_ke-y_ks)*_ease(pi)
        a=int(255*_fade(pi))
        _ball_lbl(d, px+40+math.sin(pi*math.pi)*6, y, 15, K, K_D, "K+", a)

    # 血液側 Na+勾配クラスタ（シマー＝わずかに明滅＋上下）
    grad=[(824,320),(876,304),(928,322),(858,352),(910,354)]
    for i,(bx,by) in enumerate(grad):
        ph=p*2*math.pi + i*1.3
        a=int(210+45*math.sin(ph))
        _ball_lbl(d, bx, by+math.sin(ph)*2.0, 15, NA, NA_D, "Na+", min(255,a))

    # ② 血液側で結合：Na+,Na+,I- が上から運び屋(左)へ降りて結合
    left_targets=[(lx2-22,mem_y0-4,20,NA,NA_D,"Na+"),
                  (lx2+22,mem_y0-2,20,NA,NA_D,"Na+"),
                  (lx2,   mem_y0+22,22,IODINE,IODINE_D,"I-")]
    u=_win(p,0.00,0.42)
    if u is not None:
        for (tx,ty,r,c,cd,lab) in left_targets:
            sy=ty-150
            y=sy+(ty-sy)*_ease(u)
            _ball_lbl(d, tx, y, r, c, cd, lab, 255)
    else:
        # 結合後の保持（構造変化が右へ渡るまで席に留まる）
        u2=_win(p,0.42,0.62)
        if u2 is not None:
            for (tx,ty,r,c,cd,lab) in left_targets:
                _ball_lbl(d, tx, ty, r, c, cd, lab, int(255*(1-_ease(u2))))

    # ③ 構造変化：弧に沿って光点が左→右へ走る（結合後〜放出前）
    u=_win(p,0.40,0.72)
    if u is not None:
        ang=math.radians(180+180*_ease(u))
        gx=arc_cx+arc_rx*math.cos(ang); gy=arc_cy+arc_ry*math.sin(ang)
        for rr,aa in [(18,60),(12,120),(6,235)]:
            d.ellipse([gx-rr,gy-rr,gx+rr,gy+rr],fill=(CHALK[0],CHALK[1],CHALK[2],aa))
        # 走光に合わせて弧を明るくなぞる
        d.arc([_ax0,_ay0,_ax1,_ay1],start=180,end=int(180+180*_ease(u)),fill=CHALK+(255,),width=10)

    # ④ 細胞側で放出：Na+,Na+,I- が右運び屋から細胞へ落ちる
    right_src=[(rx2-22,mem_y0+band_h+20,20,NA,NA_D,"Na+"),
               (rx2+22,mem_y0+band_h+16,20,NA,NA_D,"Na+"),
               (rx2,   mem_y0+band_h+52,22,IODINE,IODINE_D,"I-")]
    u=_win(p,0.62,1.00)
    if u is not None:
        for j,(sx,sy,r,c,cd,lab) in enumerate(right_src):
            y=sy+(120+j*10)*_ease(u)
            a=int(255*(1-_ease(max(0.0,(u-0.5)/0.5))))
            _ball_lbl(d, sx+math.sin(u*math.pi)*(6-j*4), y, r, c, cd, lab, a)

    # ⑤ I- プール（20〜40倍濃縮）：呼吸する脈動
    breathe=1.0+0.10*math.sin(p*2*math.pi)
    for i in range(10):
        pxc=980+(i%5)*90+((i//5)*44); pyc=mem_y0+band_h+150+((i//5)*46)
        ph=p*2*math.pi + i*0.6
        r=int(18*breathe); yy=pyc+math.sin(ph)*2.0
        _ball_lbl(d, pxc, yy, r, IODINE, IODINE_D, "I-", 255)

    return im.convert("RGB")


# ---- 出力 -----------------------------------------------------------------
def render_frames():
    base=build_base()
    return [draw_movers(base, i/FRAMES) for i in range(FRAMES)]


def save_preview_gif(path, scale=0.5, step=2, fps=15):
    frames=render_frames()
    sz=(int(W*scale),int(H*scale))
    small=[f.resize(sz, Image.LANCZOS) for f in frames[::step]]
    small[0].save(path, save_all=True, append_images=small[1:],
                  duration=int(1000/fps), loop=0, optimize=True,
                  disposal=2)
    print("preview GIF:", path, sz, len(small), "frames")


def save_mp4_apng():
    import imageio.v2 as imageio
    frames=render_frames()
    mp4=os.path.join(MOL,"NIS機構_模式図_anim.mp4")
    w=imageio.get_writer(mp4, fps=FPS, codec="libx264", quality=8,
                         macro_block_size=1, pixelformat="yuv420p",
                         ffmpeg_params=["-loop","0"])
    for f in frames: w.append_data(imageio.core.util.Array(_to_np(f)))
    w.close()
    print("MP4:", mp4)
    apng=os.path.join(MOL,"NIS機構_模式図_anim.png")
    frames[0].save(apng, save_all=True, append_images=frames[1:],
                   duration=int(1000/FPS), loop=0, disposal=0)
    print("APNG:", apng)
    return mp4, apng


def _to_np(pil):
    import numpy as np
    return np.asarray(pil.convert("RGB"))


if __name__ == "__main__":
    if "--preview" in sys.argv:
        import tempfile
        scratch=os.path.join(tempfile.gettempdir(), "aigaku_preview")
        os.makedirs(scratch, exist_ok=True)
        save_preview_gif(os.path.join(scratch,"nis_anim_mock.gif"))
    else:
        os.makedirs(MOL, exist_ok=True)
        save_mp4_apng()
