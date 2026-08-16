# -*- coding: utf-8 -*-
"""医療模式図ジェネレータ（Claude専有・src/）。
共有資材DB(C:\\claude_shared\\素材DB\\医療\\細胞_分子)へ"正確な自作模式図"を出力する。
- NIS機構_模式図.png と同じフラット・クリーン様式（文字は焼き込まず、ラベルはbuild_ymm4のcompose_figureで後載せ＝文字分離）。
- TPO機構_模式図.png ＝ 有機化(organification)：TPOがH2O2でヨウ素(I-)を活性化し、サイログロブリンのチロシン残基へ付加。
- T4T3_構造比較_pubchem.png ＝ PubChem実構造(T4=ヨウ素4個 / T3=3個)を並べた教科書調の比較図（構造は実データ＝AI偽構造を使わない）。
再現手順: py src/gen_medical_schematics.py
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

DB = r"C:\claude_shared\素材DB"
MOL = os.path.join(DB, "医療", "細胞_分子")
PUB = os.path.join(MOL, "構造式_pubchem")
SS = 2  # スーパーサンプリング倍率（滑らかさ）

# 背景は黒板調スレートに統一（ミニ黒板カードに馴染ませる＝今後デフォルト）。旧ライトブルーは廃止。
BG_TOP    = (32, 48, 51)      # 上（明るめスレート）
BG_BOT    = (20, 32, 35)      # 下（暗めスレート）
LIPID     = (108, 168, 224)   # リン脂質ヘッド（青）
LIPID_TL  = (150, 196, 236)   # 尾
TEAL      = (60, 168, 156)    # 酵素/輸送体（ティール）
TEAL_D    = (38, 132, 122)
IODINE    = (176, 108, 220)   # ヨウ素（紫）
IODINE_D  = (140, 78, 186)
H2O2      = (238, 120, 132)   # 過酸化水素（ピンク）
TG        = (196, 186, 174)   # サイログロブリン（ベージュグレー）
TG_D      = (150, 140, 128)
TYR       = (238, 232, 220)   # チロシン残基
INK       = (44, 62, 84)


# ── 図レイアウトの決定論リンター（figlint.pyが利用）＝ラベル/原子のbboxを記録し重なり・見切れ・小文字を機械検知 ──
#    受動的な"記憶頼み"でなく、図を作るたびに機械が止める強制チェックにするための土台（2026-08-14 ユーザー要望）。
_LINT = {"on": False, "boxes": []}
def _lint_reset():
    _LINT["boxes"] = []
def _lintreg(kind, x0, y0, x1, y1, text="", font=0):
    """kind='label'(枠付きラベル) / 'atom'(元素球)。onの時だけbboxを記録。"""
    if _LINT.get("on"):
        _LINT["boxes"].append({"kind": kind,
                               "box": (float(min(x0, x1)), float(min(y0, y1)), float(max(x0, x1)), float(max(y0, y1))),
                               "text": str(text), "font": int(font)})


def _font(px, bold=True):
    for ff in ([r"C:\Windows\Fonts\YuGothB.ttc"] if bold else [r"C:\Windows\Fonts\YuGothM.ttc"]):
        try: return ImageFont.truetype(ff, px)
        except Exception: pass
    return ImageFont.load_default()


def _vgrad(w, h, top, bot):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return im.convert("RGBA")


def _ball(d, cx, cy, r, col, cold):
    """原子/イオンの丸。NIS図(gen_nis_simpleのball_lbl)と同じフラット様式に統一
    ＝本体＋暗い縁のみ（大きな白ハイライトは廃止・ユーザー要望2026-08-14「すべての原子の丸をNISと同じに」）。"""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col + (255,), outline=cold + (255,), width=max(2, r // 8))


def _tail(d, x, y_start, h, down=True, col=None, width=3):
    """リン脂質の疎水尾（1本）。ゆるく波打たせて脂肪酸鎖らしく。"""
    import math
    col = col or LIPID_TL
    sign = 1 if down else -1
    n = 7; pts = []
    for i in range(n + 1):
        t = i / n
        yy = y_start + sign * h * t
        xx = x + math.sin(t * math.pi * 2.2) * 2.3
        pts.append((xx, yy))
    d.line(pts, fill=col + (255,), width=width, joint="curve")


def _membrane(d, y0, w, band_h, head_r=13, cols=None, x0=0):
    """脂質二重層。リン脂質1個＝頭部(球)＋疎水尾2本。上下2リーフレットの尾を中央(疎水コア)で向き合わせる。
    x0を指定するとその位置から描画開始（部分パネル用）。"""
    cols = cols or LIPID
    step = int(head_r * 2.15)
    tail_h = band_h // 2 - head_r
    toff = head_r * 0.42                              # 2本尾の左右オフセット
    for x in range(x0 + head_r, w, step):
        # 上リーフレット：頭部＋尾2本（下向き）
        d.ellipse([x - head_r, y0 - head_r, x + head_r, y0 + head_r], fill=cols + (255,))
        _tail(d, x - toff, y0 + head_r - 1, tail_h, down=True)
        _tail(d, x + toff, y0 + head_r - 1, tail_h, down=True)
        # 下リーフレット：頭部＋尾2本（上向き）
        yb = y0 + band_h
        d.ellipse([x - head_r, yb - head_r, x + head_r, yb + head_r], fill=cols + (255,))
        _tail(d, x - toff, yb - head_r + 1, tail_h, down=False)
        _tail(d, x + toff, yb - head_r + 1, tail_h, down=False)


def _blob(d, cx, cy, rx, ry, col, cold, seed=0):
    """有機的な丸みのタンパク質塊（円の重ね合わせ）。"""
    import math
    pts = []
    n = 22
    for i in range(n):
        a = 2 * math.pi * i / n
        wob = 1.0 + 0.12 * math.sin(a * 3 + seed) + 0.07 * math.cos(a * 5 + seed * 1.7)
        pts.append((cx + math.cos(a) * rx * wob, cy + math.sin(a) * ry * wob))
    d.polygon(pts, fill=col + (255,), outline=cold + (255,))


def _tyr(d, x, y, s, iodine=0):
    """チロシン残基を構造的に正確に：フェノール環(ベンゼン六角＋二重結合)＋4位OH＋側鎖。
    ヨウ素はOHの両隣＝3,5位に付く（MIT＝1個/DIT＝2個）。iodine=付いたヨウ素の数(0/1/2)。"""
    import math
    r = s * 0.62
    ring = [(x + math.cos(math.radians(60 * k - 90)) * r, y - s * 0.55 + math.sin(math.radians(60 * k - 90)) * r) for k in range(6)]
    # k0=上(4位/OH側), k1=右上(3位), k2=右下, k3=下(1位/側鎖), k4=左下, k5=左上(5位)
    d.line([ring[3], (x, y + s * 0.62)], fill=(120, 110, 96, 255), width=max(3, s // 6))   # 側鎖(下)＝アミノ酸骨格へ
    d.polygon(ring, fill=(250, 246, 236, 255), outline=(96, 86, 72, 255))
    for _e in range(6):
        d.line([ring[_e], ring[(_e + 1) % 6]], fill=(96, 86, 72, 255), width=max(3, s // 22))
    for _e in (0, 2, 4):                                                            # 芳香環の二重結合（内側の短線）
        a, b = ring[_e], ring[(_e + 1) % 6]
        ax, ay = (a[0] * 0.78 + x * 0.22, a[1] * 0.78 + (y - s * 0.55) * 0.22)
        bx, by = (b[0] * 0.78 + x * 0.22, b[1] * 0.78 + (y - s * 0.55) * 0.22)
        d.line([(ax, ay), (bx, by)], fill=(96, 86, 72, 255), width=max(2, s // 30))
    tv = ring[0]; ov = (tv[0], tv[1] - s * 0.42)                                    # 4位OH（フェノール性水酸基）
    d.line([tv, ov], fill=(96, 86, 72, 255), width=max(3, s // 20))
    of = _font(int(s * 0.44))
    d.text((ov[0] - of.size * 0.55, ov[1] - of.size * 1.02), "OH", font=of, fill=(200, 60, 60, 255))
    _cx0, _cy0 = x, y - s * 0.55                                                   # ベンゼン環の中心
    for k in range(min(iodine, 2)):                                                # ヨウ素＝3,5位(OHの両隣の"環炭素")＝ring[1],ring[5]
        vx, vy = ring[1] if k == 0 else ring[5]
        _dx, _dy = vx - _cx0, vy - _cy0                                            # 環中心→頂点の"外向き"に結合＝環炭素に付くと明確化(OHへの誤読防止・figcheck R3)
        _L = math.hypot(_dx, _dy) or 1.0
        ox, oy = vx + _dx / _L * (s * 0.5), vy + _dy / _L * (s * 0.5)
        d.line([(vx, vy), (ox, oy)], fill=(120, 110, 96, 255), width=max(2, s // 24))
        _ball(d, int(ox), int(oy), int(s * 0.33), IODINE, IODINE_D)


# ---------------------------------------------------------------- TPO 模式図（半正確版）
def gen_tpo():
    """有機化(organification)を"数"まで正確に：アピカル膜に埋まったTPOが、コロイド側でサイログロブリンの
    チロシン残基にヨウ素を付ける＝【1個＝MIT】【2個＝DIT】。※本編は数を正確に。H2O2・カップリング(→T3/T4)は補足編。
    （旧版は"職人が土台にペタペタ"の比喩で、ヨウ素の数が装飾＝不正確だったため差替）"""
    import math
    W, H = 1600, 900
    im = _vgrad(W, H, BG_TOP, BG_BOT); d = ImageDraw.Draw(im)
    CELLPINK = (238, 198, 192); COLLOID = (236, 222, 212); NUC = (188, 118, 108); CAP = (224, 100, 84)
    CHALK = (232, 238, 246); DARK = (66, 48, 42); ORANGE = (255, 152, 64)
    fT = _font(32); fN = _font(28); fS = _font(25)  # スマホ視聴前提で拡大(A追加ルール2026-08-12対応・ユーザー指摘「TPO」等が小さい)

    def ctext(cx, y, t, f, fill):
        w = d.textlength(t, font=f); d.text((cx - w / 2, y), t, font=f, fill=fill + (255,)); return w

    def lbox(cx, cy, t, f, tip=None, fill=(8, 16, 22), txt=CHALK):
        w = d.textlength(t, font=f); h = f.size; pad = 12
        if tip:
            d.line([(cx, cy), tip], fill=(150, 166, 182, 255), width=3)
            d.ellipse([tip[0] - 6, tip[1] - 6, tip[0] + 6, tip[1] + 6], fill=(150, 166, 182, 255))
        d.rounded_rectangle([cx - w / 2 - pad, cy - h / 2 - 7, cx + w / 2 + pad, cy + h / 2 + 9], radius=10,
                            fill=fill + (232,), outline=(150, 166, 182, 255), width=2)
        d.text((cx - w / 2, cy - h / 2 - 1), t, font=f, fill=txt + (255,))

    def dashed(p0, p1, col):
        dx = p1[0] - p0[0]; dy = p1[1] - p0[1]; L = math.hypot(dx, dy); n = max(2, int(L / 18))
        for i in range(0, n, 2):
            a = i / n; b = min((i + 1) / n, 1.0)
            d.line([(p0[0] + dx * a, p0[1] + dy * a), (p0[0] + dx * b, p0[1] + dy * b)], fill=col + (255,), width=5)  # figcheck指摘：細くて途切れて見えるため太く(3→5)

    # ============ 左：入れ子ロケーター（甲状腺→濾胞の集まり→濾胞1個→アピカル膜）============
    def mini_follicle(cx, cy, r):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CELLPINK + (255,), outline=(198, 140, 128, 255), width=2)
        ri = r * 0.60
        d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=COLLOID + (255,), outline=(210, 152, 124, 255), width=2)
        for a in range(0, 360, 51):
            nx = cx + math.cos(math.radians(a)) * (r - 5); ny = cy + math.sin(math.radians(a)) * (r - 5)
            d.ellipse([nx - 3.5, ny - 3.5, nx + 3.5, ny + 3.5], fill=NUC + (255,))

    # (1) 甲状腺（臓器）＝Servier模式図（正確・CC BY・透過）
    from PIL import Image as _PILImage
    _thy = _PILImage.open(r"C:\claude_shared\素材DB\医療\解剖_臓器別\甲状腺_servier模式図.png").convert("RGBA")
    _tw = 116; _th = int(_thy.height * _tw / _thy.width)
    _thy = _thy.resize((_tw, _th), _PILImage.LANCZOS)
    gx, gy = 106, 120
    im.paste(_thy, (int(gx - _tw / 2), int(gy - _th / 2)), _thy)
    ctext(gx, gy - _th // 2 - 26, "甲状腺（首の前）", fS, CHALK)
    gbx, gby = gx + 24, gy + 8
    d.rectangle([gbx - 13, gby - 12, gbx + 13, gby + 12], outline=ORANGE + (255,), width=3)             # 拡大マーカー

    # (2) 濾胞の集まり（組織）＝甲状腺の中はこの袋がぎっしり
    ccx, ccy = 348, 132
    for (dx, dy, rr) in [(0, -6, 36), (-60, -16, 27), (58, -12, 30), (40, 44, 27), (2, 54, 25), (72, 28, 21)]:
        mini_follicle(ccx + dx, ccy + dy, rr)
    mfx, mfy, mfr = ccx - 42, ccy + 40, 30
    mini_follicle(mfx, mfy, mfr)
    d.rectangle([mfx - mfr - 3, mfy - mfr - 3, mfx + mfr + 3, mfy + mfr + 3], outline=ORANGE + (255,), width=3)  # 拡大マーカー
    ctext(ccx, 40, "濾胞の集まり（組織）", fS, CHALK)

    # (3) 濾胞（1個）ロケーター＝1つの袋の壁を拡大
    fcx, fcy, R = 220, 452, 132
    d.ellipse([fcx - R, fcy - R, fcx + R, fcy + R], fill=CELLPINK + (255,), outline=(198, 140, 128, 255), width=3)
    rin = R - 46
    d.ellipse([fcx - rin, fcy - rin, fcx + rin, fcy + rin], fill=COLLOID + (255,), outline=(210, 152, 124, 255), width=4)
    for a in range(0, 360, 26):
        nx = fcx + math.cos(math.radians(a)) * (R - 24); ny = fcy + math.sin(math.radians(a)) * (R - 24)
        d.ellipse([nx - 7, ny - 7, nx + 7, ny + 7], fill=NUC + (255,))
    for a in range(16, 360, 46):
        cx2 = fcx + math.cos(math.radians(a)) * (R + 16); cy2 = fcy + math.sin(math.radians(a)) * (R + 16)
        d.ellipse([cx2 - 6, cy2 - 6, cx2 + 6, cy2 + 6], fill=CAP + (255,))
    fS2 = _font(20)  # 左下の狭い余白専用（拡大したfSだと注釈ボックスと衝突するため小さめを維持）
    ctext(fcx, fcy - 12, "コロイド", fS2, DARK)
    ctext(fcx, fcy + R + 12, "濾胞（1個）＝甲状腺の小さな袋", fS2, CHALK)
    _lgy = 636                                                                 # 粒の凡例（1行・注釈の上）＝「血液側」をやさしく言い換え
    d.ellipse([46 - 8, _lgy - 8, 46 + 8, _lgy + 8], fill=CAP + (255,))
    d.text((64, _lgy - 13), "＝毛細血管（血液が流れる）", font=fS2, fill=CHALK + (255,))
    d.ellipse([348 - 8, _lgy - 8, 348 + 8, _lgy + 8], fill=NUC + (255,))
    d.text((366, _lgy - 13), "＝濾胞細胞の核", font=fS2, fill=CHALK + (255,))
    zbx, zby = fcx + math.cos(math.radians(-42)) * (rin + 4), fcy + math.sin(math.radians(-42)) * (rin + 4)
    d.rectangle([zbx - 38, zby - 26, zbx + 38, zby + 26], outline=ORANGE + (255,), width=4)
    dashed((gbx + 13, gby + 4), (ccx - 92, ccy - 6), ORANGE)                       # 甲状腺 → 濾胞の集まり
    dashed((mfx - mfr + 2, mfy + mfr), (fcx + 20, fcy - R + 16), ORANGE)           # 濾胞の集まり → 濾胞1個
    dashed((zbx + 38, zby - 22), (612, 66), ORANGE); dashed((zbx + 38, zby + 22), (612, 620), ORANGE)  # 濾胞1個 → アピカル膜

    # ============ 右：アピカル膜（コロイド側）のズーム ============
    PX0, PX1 = 612, 1566
    d.rounded_rectangle([PX0, 60, PX1, 628], radius=16, outline=ORANGE + (210,), width=3)
    mem_y0, band_h = 452, 74
    d.rectangle([PX0 + 3, 63, PX1 - 3, mem_y0 + 4], fill=COLLOID + (255,))     # コロイド（上・淡色）
    d.rectangle([PX0 + 3, mem_y0 + band_h - 4, PX1 - 3, 625], fill=CELLPINK + (255,))  # 濾胞細胞の中（細胞質）＝ロケーターの濾胞細胞と同色ピンク
    _membrane(d, mem_y0, PX1 - 4, band_h, x0=PX0 + 3)                          # アピカル膜
    tcx = 740                                                                  # TPO（1回膜貫通型の酵素。触媒ドメインの大部分はコロイド側）
    # 2026-08-13再設計（Claude-A独立レビュー指摘対応）：旧デザイン(膜を貫通する角丸長方形)はNISの
    # 輸送体シルエットと酷似し「酵素でなく輸送体」に誤読されていた。TPOは実際には1回膜貫通型の膜結合酵素で、
    # 大きな触媒ドメインは膜のコロイド側にほぼ丸ごと乗り、細いアンカー(膜貫通ヘリックス)1本だけが膜を貫く
    # ＝NIS(膜を貫通する箱形)とは形そのものが違う、という事実に忠実な描き方に変更。
    e_l, e_r, e_t, e_b = tcx - 75, tcx + 75, mem_y0 - 155, mem_y0 - 15         # 触媒ドメイン(球状・コロイド側)
    d.ellipse([e_l, e_t, e_r, e_b], fill=TEAL + (255,), outline=TEAL_D + (255,), width=6)
    d.rounded_rectangle([tcx - 15, e_b - 4, tcx + 15, mem_y0 + band_h + 26], radius=8,
                        fill=TEAL + (255,), outline=TEAL_D + (255,), width=5)  # アンカー(1本の膜貫通ヘリックス)
    d.polygon([(tcx - 28, mem_y0 - 78), (tcx + 32, mem_y0 - 78), (tcx + 13, mem_y0 - 20), (tcx - 13, mem_y0 - 20)], fill=COLLOID + (255,))  # 活性部位の切れ込み(触媒クレフト)
    # コロイドのヨウ化物イオン(I-)＝TPOの基質。Pendrinで供給。TPOがH2O2で酸化・活性化→活性ヨウ素→チロシンに結合(有機化)。※膜は越えない＝輸送体でない。
    def activated_iodine(cx, cy, r):                                            # 活性ヨウ素＝I-とは別状態（酸化された反応種）を橙の輪＋スパイクで強調
        d.ellipse([cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7], outline=(255, 176, 44, 255), width=3)
        for k in range(12):
            ang = math.radians(k * 30)
            d.line([(cx + math.cos(ang) * (r + 3), cy + math.sin(ang) * (r + 3)),
                    (cx + math.cos(ang) * (r + 15), cy + math.sin(ang) * (r + 15))], fill=(255, 168, 36, 255), width=4)
        _ball(d, cx, cy, r, IODINE, IODINE_D)
    for (x, y) in [(1168, 150), (1216, 138), (1264, 150)]:  # コロイドの遊離I-プール（環から離す＝チロシンの数を崩さない）
        _ball(d, x, y, 18, IODINE, IODINE_D)
    d.line([(tcx + 2, mem_y0 - 150), (tcx + 2, mem_y0 - 86)], fill=IODINE + (255,), width=5)   # I-が活性部位へ（コロイド側から・膜を越えない）
    _arrow_head(d, (tcx + 2, mem_y0 - 80), (tcx + 2, mem_y0 - 150), 13, IODINE)
    _ball(d, tcx + 2, mem_y0 - 168, 15, IODINE, IODINE_D)  # 基質I-（酸化される前）
    activated_iodine(tcx + 2, mem_y0 - 56, 16)            # 活性部位で酸化された＝活性ヨウ素（次に②で結合）
    # H2O2＝TPOの酸化反応に必須の共同基質。今まで文章のみだったのを描画に追加（Aからの指摘対応）。
    H2O2C, H2O2C_D = (235, 120, 70), (185, 85, 45)
    hx, hy = tcx - 104, mem_y0 - 34
    d.ellipse([hx - 8, hy - 8, hx + 8, hy + 8], fill=H2O2C + (255,), outline=H2O2C_D + (255,), width=2)
    d.ellipse([hx + 8, hy - 8, hx + 24, hy + 8], fill=H2O2C + (255,), outline=H2O2C_D + (255,), width=2)
    ctext(hx + 8, hy + 12, "H2O2（過酸化水素）", fS2, H2O2C)
    d.line([(hx + 22, hy - 2), (tcx - 34, mem_y0 - 58)], fill=H2O2C + (255,), width=4)
    _arrow_head(d, (tcx - 34, mem_y0 - 58), (hx + 22, hy - 2), 10, H2O2C)
    bby = 300                                                                  # サイログロブリン骨格＋チロシン3種（バラ→MIT→DIT）
    _bx0, _bx1, _by = tcx + 30, PX1 - 40, bby + 132                            # Tg骨格＝うねった1本の長いタンパク質の鎖（環はその枝＝残基）
    _bpts = []; _x = _bx0
    while _x <= _bx1:
        _bpts.append((_x, _by + math.sin((_x - _bx0) / 36.0) * 16)); _x += 10
    d.line(_bpts, fill=(150, 132, 96, 255), width=12, joint="curve")
    _tyr(d, 980, bby + 96, 58, iodine=0); _tyr(d, 1210, bby + 96, 58, iodine=1); _tyr(d, 1440, bby + 96, 58, iodine=2)
    for (xa, xb) in [(1058, 1132), (1288, 1362)]:                             # ＋ヨウ素の進行矢印
        d.line([(xa, bby + 40), (xb, bby + 40)], fill=(88, 74, 60, 255), width=6); _arrow_head(d, (xb + 2, bby + 40), (xa, bby + 40), 16, (88, 74, 60))
    # ②活性ヨウ素 → チロシン残基へまっすぐ結合（有機化）。着地点は最初のチロシン環の左端。
    _c2 = (86, 74, 62)
    d.line([(tcx + 24, mem_y0 - 64), (936, bby + 62)], fill=_c2 + (255,), width=5)
    _arrow_head(d, (946, bby + 64), (tcx + 24, mem_y0 - 64), 17, _c2)

    # ============ ラベル（焼込み・重なり無し）============
    ctext(950, 82, "コロイド（濾胞の中身）", fN, DARK)  # 文字拡大でヨウ素ラベルと重なったため左へ
    lbox(tcx, mem_y0 + band_h + 86, "TPO（酵素）", fN, tip=(tcx, mem_y0 + band_h + 22))
    lbox(662, mem_y0 - 120, "①酸化→活性ヨウ素", fS, tip=(tcx - 12, mem_y0 - 64), txt=(238, 214, 250))
    ctext(905, bby, "②結合（有機化）", fS, DARK)
    lbox(756, 158, "サイログロブリン(Tg)＝この長い鎖", fS, tip=(880, bby + 136))  # チロシンボックス(y232)と重なっていたため上へ退避
    lbox(1300, 102, "ヨウ素（I-）", fS, tip=(1216, 120), txt=(238, 214, 250))  # 文字拡大で左の「コロイド」ラベル・上の外枠と衝突→右下へ調整
    lbox(980, 232, "チロシン", fN, tip=(980, bby + 40))
    lbox(1210, 232, "MIT（1個）", fN, tip=(1210, bby + 40), txt=(255, 220, 250))
    lbox(1440, 232, "DIT（2個）", fN, tip=(1440, bby + 40), txt=(255, 220, 250))
    lbox(1190, 566, "アピカル膜（＝コロイド側の細胞膜）", fS, tip=(1190, 500))
    ctext(1130, 596, "この膜より下＝甲状腺の濾胞細胞の中", fS2, DARK)  # 外枠下端(628)と接触していたため上へ・小さめフォントに変更

    # ============ ※やさしい注釈（隅・初学者向け）============
    notes = ["※濾胞＝甲状腺の中にある小さな袋。中身がコロイド",
             "※コロイド＝濾胞を満たすゼリー状の貯蔵物。ホルモンの材料(Tg)を蓄える場所",
             "※サイログロブリン＝チロシンが多数並ぶ大きなタンパク質",
             "※チロシン＝アミノ酸の部品。MIT／DIT＝ヨウ素が1個／2個ついた形",
             "※ヨウ素(I-)はPendrinでコロイド側へ運ばれる（NISは血液側の膜）",
             "※TPOはH2O2でI-を酸化・活性化し、チロシンに結合＝有機化",
             "※この有機化が抗甲状腺薬(PTU/チアマゾール)・抗TPO抗体の標的"]
    nf = _font(23); nx0, ny0 = 40, H - len(notes) * 31 - 16   # スマホ視聴前提で拡大(左の凡例と衝突しない範囲に調整)
    nx1 = nx0 + max(d.textlength(t, font=nf) for t in notes) + 24  # 枠幅は最長行の実測幅から算出(固定760pxだと「コロイド」行がはみ出ていたため)
    d.rounded_rectangle([nx0 - 12, ny0 - 12, nx1, H - 12], radius=12, fill=(8, 16, 22, 232), outline=(120, 140, 160, 200), width=2)
    for i, t in enumerate(notes):
        d.text((nx0, ny0 + i * 31), t, font=nf, fill=(224, 228, 234, 255))

    out = os.path.join(MOL, "TPO機構_模式図.png")
    im.save(out)
    print("TPO 模式図(濾胞ロケーター＋アピカル膜ズーム):", out, im.size)
    return out


def _arrow_head(d, tip, frm, size, col):
    """普通の矢印の先（塗りつぶし三角）。"""
    import math
    ang = math.atan2(tip[1] - frm[1], tip[0] - frm[0])
    left  = (tip[0] - math.cos(ang - 0.5) * size, tip[1] - math.sin(ang - 0.5) * size)
    right = (tip[0] - math.cos(ang + 0.5) * size, tip[1] - math.sin(ang + 0.5) * size)
    d.polygon([tip, left, right], fill=col + (255,))


# ---------------------------------------------------------------- T4/T3 比較
def _detect_iodines(png):
    """PubChem構造式PNGから紫(マゼンタ)の『I』ラベル位置を検出。推測でなく実画像の色から座標を取る。
    戻り値: (元画像size, [(x,y), ...] 読み順ソート済)。"""
    import numpy as np
    im = Image.open(png).convert("RGB")
    a = np.asarray(im)
    m = (a[:, :, 0] > 150) & (a[:, :, 2] > 150) & (a[:, :, 1] < 110)
    ys, xs = np.where(m)
    clusters = []
    for x, y in zip(xs.tolist(), ys.tolist()):
        best = None
        for c in clusters:
            if (x - c["cx"]) ** 2 + (y - c["cy"]) ** 2 <= 28 ** 2:
                best = c; break
        if best:
            best["px"].append((x, y))
            best["cx"] = sum(p[0] for p in best["px"]) / len(best["px"])
            best["cy"] = sum(p[1] for p in best["px"]) / len(best["px"])
        else:
            clusters.append({"px": [(x, y)], "cx": x, "cy": y})
    cents = sorted([(c["cx"], c["cy"]) for c in clusters], key=lambda t: (t[1], t[0]))
    return im.size, cents


def _chalk_transparent(png, size):
    """PubChem構造式(黒線＋色付き原子・白背景)を、白背景を透過＋黒線をチョーク白化して黒板に直接載せられる形にする。
    色付き原子(O赤/N青/I紫)は残す。アンチエイリアス縁は部分透過で滑らかに。"""
    import numpy as np
    im = Image.open(png).convert("RGB").resize((size, size), Image.LANCZOS)
    a = np.asarray(im).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a.max(2); mn = a.min(2); sat = mx - mn
    lum = (0.299 * r + 0.587 * g + 0.114 * b)
    alpha = np.clip(255 - lum, 0, 255)                     # 白→透明・黒→不透明
    alpha = np.maximum(alpha, np.clip((sat - 30) * 5, 0, 255))                   # 色付き原子は残す
    alpha[(lum > 236) & (sat < 40)] = 0                    # 近白の下地は完全透過（薄い四角残り防止）
    alpha = alpha.astype(np.uint8)
    out = a.copy()
    gray = sat < 48                                        # 無彩色(黒/灰=結合線・炭素)→チョーク白へ
    out[gray] = np.array([228, 234, 242])
    out = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([out, alpha]), "RGBA")


def gen_t4t3():
    W, H = 1600, 900
    im = _vgrad(W, H, BG_TOP, BG_BOT)                      # ★背景を黒板スレートに
    d = ImageDraw.Draw(im)

    def panel(x0, title, sub, count_txt, png, accent, expected):
        pw = 660; y0 = 118
        # 見出し（白カード廃止＝黒板に直接）＝アクセント色のチョーク見出し＋下線
        f1 = _font(48); tw = d.textlength(title, font=f1)
        d.text((x0 + pw / 2 - tw / 2, y0), title, font=f1, fill=accent + (255,))
        d.line([(x0 + pw / 2 - tw / 2, y0 + 60), (x0 + pw / 2 + tw / 2, y0 + 60)], fill=accent + (200,), width=4)
        # 構造式（PubChem実データ）＝透過チョーク化して黒板に直接貼る
        DISP = 460
        mx, my = x0 + pw // 2 - DISP // 2, y0 + 104
        mol = _chalk_transparent(png, DISP)
        im.alpha_composite(mol, (mx, my))
        # ヨウ素(I)を検出→構造式上に番号付き丸囲み（一目で数えられる）
        (ow, oh), cents = _detect_iodines(png)
        if len(cents) != expected:
            print(f"[warn] {os.path.basename(png)} 検出ヨウ素={len(cents)} 期待={expected}")
        sc = DISP / ow
        dd = ImageDraw.Draw(im)
        for i, (cx, cy) in enumerate(cents, 1):
            px, py = mx + cx * sc, my + cy * sc
            r = 26
            # 紫の丸囲み（構造の I を強調）
            dd.ellipse([px - r, py - r, px + r, py + r], outline=IODINE + (255,), width=6)
            # 右上に番号バッジ
            bx, by = px + r * 0.72, py - r * 1.05
            br = 17
            dd.ellipse([bx - br, by - br, bx + br, by + br], fill=IODINE + (255,), outline=(255, 255, 255, 255), width=3)
            nf = _font(24); ns = str(i); nw = dd.textlength(ns, font=nf)
            dd.text((bx - nw / 2, by - 15), ns, font=nf, fill=(255, 255, 255, 255))
        # サブ名（チョーク薄色）
        f2 = _font(26, bold=False); sw = d.textlength(sub, font=f2)
        d.text((x0 + pw / 2 - sw / 2, y0 + 580), sub, font=f2, fill=(206, 216, 228, 255))
        # 個数バッジ（大）
        bw, bh = 300, 70
        bx2 = x0 + pw // 2 - bw // 2; by2 = y0 + 628
        d.rounded_rectangle([bx2, by2, bx2 + bw, by2 + bh], radius=35, fill=IODINE + (255,))
        f4 = _font(42); cw = d.textlength(count_txt, font=f4)
        d.text((bx2 + bw / 2 - cw / 2, by2 + 10), count_txt, font=f4, fill=(255, 255, 255, 255))

    panel(70, "T4（サイロキシン）", "3,5,3',5'-テトラヨードサイロニン", "ヨウ素 4 個",
          os.path.join(PUB, "T4_thyroxine_pubchem.png"), (120, 185, 245), expected=4)
    panel(870, "T3（トリヨードサイロニン）", "3,5,3'-トリヨードサイロニン", "ヨウ素 3 個",
          os.path.join(PUB, "T3_liothyronine_pubchem.png"), (245, 176, 96), expected=3)

    # 中央：T4 →(−1個)→ T3 の矢印。ヨウ素が1個外れる
    ax, ay = W / 2, 430
    d.line([(ax - 46, ay), (ax + 46, ay)], fill=(214, 224, 236, 255), width=12)
    _arrow_head(d, (ax + 58, ay), (ax - 46, ay), 30, (214, 224, 236))
    _ball(d, int(ax), int(ay - 70), 26, IODINE, IODINE_D)
    fl = _font(22); lt = "外れるヨウ素"                          # 中央の紫丸の凡例（figcheck：未説明要素→明示）
    d.text((ax - d.textlength(lt, font=fl) / 2, ay - 70 - 44), lt, font=fl, fill=(232, 204, 250, 255))
    fm = _font(40); mt = "−1個"
    d.text((ax - d.textlength(mt, font=fm) / 2, ay + 22), mt, font=fm, fill=(255, 150, 150, 255))
    # 図の下部：凡例＋5'位脱ヨウ素の明示（figcheck：紫丸の凡例なし／どのヨウ素が外れるか不明）
    _nt = _font(24); _ntxt = "※ 紫の丸＝ヨウ素原子。T4→T3はヨウ素が1個外れる（5'位の脱ヨウ素）"
    d.text((W / 2 - d.textlength(_ntxt, font=_nt) / 2, 842), _ntxt, font=_nt, fill=(206, 216, 228, 255))

    # 上部の要点メモ
    f = _font(34)
    note = "ちがいは『ヨウ素の数』だけ（4個 → 3個）"
    nw = d.textlength(note, font=f)
    d.rounded_rectangle([W / 2 - nw / 2 - 30, 26, W / 2 + nw / 2 + 30, 92], radius=33,
                        fill=(16, 28, 30, 255), outline=(210, 182, 126, 220), width=2)
    d.text((W / 2 - nw / 2, 40), note, font=f, fill=(255, 236, 150, 255))
    # 出典
    f5 = _font(24, bold=False); src = "構造式：PubChem（実データ）"
    d.text((W - d.textlength(src, font=f5) - 28, H - 40), src, font=f5, fill=(150, 166, 184, 255))

    out = os.path.join(MOL, "T4T3_構造比較_pubchem.png")
    im.convert("RGB").save(out)
    print("T4/T3 比較:", out, im.size)
    return out


def gen_radioactive_iodine():
    """放射性ヨウ素の透過アイコン＝紫のヨウ素球クラスタ＋黄色い放射線バースト（原発建物は使わない・違和感解消）。
    出力先はヨウ素剤フォルダ（オリジナル作画）。"""
    import math
    IOD_DIR = os.path.join(DB, "医療", "薬剤_ヨウ素剤")
    os.makedirs(IOD_DIR, exist_ok=True)
    S = 560; SSx = 2; W = H = S * SSx
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    cx, cy = W // 2, H // 2 + int(20 * SSx)
    # 放射線バースト（黄オレンジの二重線）
    for a in range(0, 360, 30):
        r = math.radians(a)
        x1 = cx + math.cos(r) * 150 * SSx; y1 = cy + math.sin(r) * 150 * SSx
        x2 = cx + math.cos(r) * 235 * SSx; y2 = cy + math.sin(r) * 235 * SSx
        d.line([(x1, y1), (x2, y2)], fill=(255, 208, 60, 235), width=int(12 * SSx))
        xm = cx + math.cos(r) * 205 * SSx; ym = cy + math.sin(r) * 205 * SSx
        d.ellipse([xm - 7 * SSx, ym - 7 * SSx, xm + 7 * SSx, ym + 7 * SSx], fill=(255, 232, 120, 235))
    # 紫のヨウ素球クラスタ（Iラベル付き）
    f = _font(int(46 * SSx))
    for (dx, dy, rr) in [(-58, -8, 62), (56, -2, 60), (2, 66, 56)]:
        bx, by, br = cx + int(dx * SSx), cy + int(dy * SSx), int(rr * SSx)
        _ball(d, bx, by, br, IODINE, IODINE_D)
        iw = d.textlength("I", font=f); d.text((bx - iw / 2, by - int(30 * SSx)), "I", font=f, fill=(255, 255, 255, 255))
    im = im.resize((S, S), Image.LANCZOS)
    out = os.path.join(IOD_DIR, "放射性ヨウ素_オリジナル.png")
    im.save(out)
    print("放射性ヨウ素:", out, im.size)
    return out


def gen_nis():
    """NIS＝Na+/I- シンポーター（二次性能動輸送）の模式図。
    ★チャネル(開いた孔)ではなくキャリア(交互アクセス)＝【外向きで結合】→【構造変化】→【内向きで放出】を2状態で描く。
    背景は黒板スレート。文字は焼き込まずcompose_figureで後載せ。"""
    import math
    W, H = 1600, 900
    im = _vgrad(W, H, BG_TOP, BG_BOT); d = ImageDraw.Draw(im)
    NA = (245, 165, 60); NA_D = (205, 130, 35)
    TEAL_ = (72, 176, 164); TEALD_ = (40, 130, 120)
    CHALK = (228, 234, 242); SLATE = (24, 38, 41)
    mem_y0 = 405; band_h = 96
    _membrane(d, mem_y0, W, band_h)                       # 脂質二重層（全幅）
    mid = mem_y0 + band_h // 2

    def carrier(cx, open_up):
        """キャリア本体（開口部は上=血液側 or 下=細胞側の片側だけ＝交互アクセス。貫通した孔は描かない）。"""
        bw, top, bot = 96, mem_y0 - 58, mem_y0 + band_h + 58
        d.rounded_rectangle([cx - bw, top, cx + bw, bot], radius=36, fill=TEAL_ + (255,), outline=TEALD_ + (255,), width=6)
        if open_up:                                       # 上（血液側）に開いたカップ＝結合ポケット
            cav = [(cx - 58, top - 2), (cx + 58, top - 2), (cx + 24, mid + 14), (cx - 24, mid + 14)]
        else:                                             # 下（細胞側）に開いたカップ＝放出
            cav = [(cx - 58, bot + 2), (cx + 58, bot + 2), (cx + 24, mid - 14), (cx - 24, mid - 14)]
        d.polygon(cav, fill=SLATE + (255,))
        return cx

    # 左：外向き（血液側に開く）＝Na+2 と I-1 を結合（ローディング）
    lx = 470; carrier(lx, True)
    _ball(d, lx - 24, mem_y0 - 6, 24, NA, NA_D); _ball(d, lx + 26, mem_y0 - 2, 24, NA, NA_D)
    _ball(d, lx, mem_y0 + 26, 26, IODINE, IODINE_D)
    for (dx, dy, c, cd, r) in [(-74, -96, NA, NA_D, 20), (44, -112, IODINE, IODINE_D, 22), (-28, -128, NA, NA_D, 18)]:
        _ball(d, lx + dx, mem_y0 + dy, r, c, cd)          # 血液側は少ししかない（希薄）

    # 右：内向き（細胞側に開く）＝Na+2 と I-1 を放出
    rx = 1130; carrier(rx, False)
    _ball(d, rx - 26, mem_y0 + band_h + 22, 24, NA, NA_D); _ball(d, rx + 24, mem_y0 + band_h + 18, 24, NA, NA_D)
    _ball(d, rx, mem_y0 + band_h + 60, 26, IODINE, IODINE_D)
    # 細胞内はヨウ素が20〜40倍＝密なクラスタ（勾配に逆らって濃縮）
    for i in range(12):
        px = 720 + (i % 6) * 150 + ((i // 6) * 70)
        py = mem_y0 + band_h + 132 + (i % 3) * 40 + ((i // 6) * 30)
        _ball(d, px, py, 21, IODINE, IODINE_D)

    # 構造変化の矢印（上をアーチする曲線＋三角）＝「開いて通す」でなく「形が変わって運ぶ」
    d.arc([560, 280, 1040, 470], start=180, end=360, fill=CHALK + (255,), width=12)
    _arrow_head(d, (1046, 392), (1006, 336), 30, CHALK)

    out = os.path.join(MOL, "NIS機構_模式図.png")
    im.convert("RGB").save(out)
    print("NIS(キャリア):", out, im.size)
    return out


def gen_tpo_simple():
    """TPO機構の「簡易・拡大版」（本編用 main_simple）。※注記を省いた分の縦スペースを使い、
    入れ子ロケーター（甲状腺→濾胞の集まり→濾胞1個→アピカル膜）と機構図・ラベルを大きく描く。
    拡大表現は医療図風＝明るめグレーの枠＋細い誘導線＋淡い面のファンアウトで統一（ユーザー承認2026-08-14）。
    出力: TPO機構_模式図_simple.png（compose_figureがmain_simpleとして優先使用）。"""
    import math
    from PIL import Image, ImageDraw
    W, H = 1600, 900
    im = _vgrad(W, H, BG_TOP, BG_BOT); d = ImageDraw.Draw(im)
    CHALK = (232, 238, 246); DARK = (66, 48, 42)
    COLLOID = (236, 222, 212); CELLPINK = (238, 198, 192); NUC = (188, 118, 108)
    fTitle = _font(46); fL = _font(40); fL2 = _font(36); fS = _font(30); fXS = _font(24); fLoc = _font(31)
    FUN = (194, 203, 214); FUNFILL = (42, 52, 59)   # 明るめグレー（枠＋誘導線を統一色に）

    def ctext(cx, y, t, f, fill):
        w = d.textlength(t, font=f); d.text((cx - w/2, y), t, font=f, fill=fill + (255,)); return w
    def lbox(cx, cy, t, f, tip=None, fill=(8,16,22), txt=CHALK):
        w = d.textlength(t, font=f); h = f.size; pad = 14
        if tip:
            d.line([(cx, cy), tip], fill=(150,166,182,255), width=3)
            d.ellipse([tip[0]-6, tip[1]-6, tip[0]+6, tip[1]+6], fill=(150,166,182,255))
        d.rounded_rectangle([cx-w/2-pad, cy-h/2-8, cx+w/2+pad, cy+h/2+10], radius=12,
                            fill=fill+(236,), outline=(150,166,182,255), width=2)
        d.text((cx-w/2, cy-h/2-1), t, font=f, fill=txt+(255,))
        _lintreg("label", cx-w/2-pad, cy-h/2-8, cx+w/2+pad, cy+h/2+10, t, f.size)
    def ahead(tip, frm, size, col): _arrow_head(d, tip, frm, size, col)
    def mini_follicle(cx, cy, r):
        d.ellipse([cx-r,cy-r,cx+r,cy+r], fill=CELLPINK+(255,), outline=(198,140,128,255), width=2)
        ri=r*0.6
        d.ellipse([cx-ri,cy-ri,cx+ri,cy+ri], fill=COLLOID+(255,), outline=(210,152,124,255), width=2)
        for a in range(0,360,51):
            nx=cx+math.cos(math.radians(a))*(r-4); ny=cy+math.sin(math.radians(a))*(r-4)
            d.ellipse([nx-3,ny-3,nx+3,ny+3], fill=NUC+(255,))
    def ball_lbl(cx, cy, r, col, cold, lab):   # NIS図と同じ＝フラット球＋中に元素ラベル（原子の丸を全図で統一）
        d.ellipse([cx-r,cy-r,cx+r,cy+r], fill=col+(255,), outline=cold+(255,), width=2)
        sz=int(r*1.1); bf=_font(sz,bold=True); bb=d.textbbox((0,0),lab,font=bf)
        while sz>9 and (bb[2]-bb[0])>2*r-6:
            sz-=1; bf=_font(sz,bold=True); bb=d.textbbox((0,0),lab,font=bf)
        d.text((cx-(bb[2]-bb[0])/2, cy-(bb[3]-bb[1])/2-bb[1]), lab, font=bf, fill=(255,255,255,255))
        _lintreg("atom", cx-r, cy-r, cx+r, cy+r, lab, 0)

    ctext(W/2, 20, "TPO（甲状腺ペルオキシダーゼ）＝コロイド側で働く酵素", fTitle, CHALK)
    # 左：入れ子ロケーター（座標を先に決定）
    gpx, gpy, tw = 64, 132, 94
    try:
        thy = Image.open(r"C:\claude_shared\素材DB\医療\解剖_臓器別\甲状腺_servier模式図.png").convert("RGBA")
        th = int(thy.height*tw/thy.width); thy = thy.resize((tw, th))
    except Exception as e:
        thy = None; th = 92; print("thy skip", e)
    gbx, gby = gpx+tw//2+14, gpy+th//2
    ccx, ccy = 254, 340
    mfx, mfy, mfr = ccx-42, ccy+42, 27
    fcx, fcy, R = 172, 636, 132; rin = R-46
    zbx, zby = fcx+math.cos(math.radians(-6))*(rin+2), fcy+math.sin(math.radians(-6))*(rin+2)
    # (A) 拡大コーン（淡い面＋細い誘導線・全3段を分離）
    d.polygon([(gbx-13,gby+12),(ccx-100,ccy-50),(ccx+100,ccy-50),(gbx+13,gby+12)], fill=FUNFILL)
    d.polygon([(mfx-mfr-3,mfy+mfr+3),(fcx-R,fcy-R+4),(fcx+R,fcy-R+4),(mfx+mfr+3,mfy+mfr+3)], fill=FUNFILL)
    d.polygon([(zbx+34,zby-26),(430,344),(430,852),(zbx+34,zby+26)], fill=FUNFILL)
    for (a,b) in [((gbx-13,gby+12),(ccx-100,ccy-50)),((gbx+13,gby+12),(ccx+100,ccy-50)),
                  ((mfx-mfr-3,mfy+mfr+3),(fcx-R,fcy-R+4)),((mfx+mfr+3,mfy+mfr+3),(fcx+R,fcy-R+4)),
                  ((zbx+34,zby-26),(430,344)),((zbx+34,zby+26),(430,852))]:
        d.line([a,b], fill=FUN+(255,), width=3)
    # (B) 各段の要素（コーンの上）
    if thy is not None: im.paste(thy, (gpx, gpy), thy)
    d.rectangle([gbx-13,gby-12,gbx+13,gby+12], outline=FUN+(255,), width=3)
    for (dx,dy,rr) in [(0,-6,32),(-58,-14,24),(56,-10,27),(38,44,24),(2,54,22),(70,30,18)]:
        mini_follicle(ccx+dx, ccy+dy, rr)
    mini_follicle(mfx, mfy, mfr)
    d.rectangle([mfx-mfr-3,mfy-mfr-3,mfx+mfr+3,mfy+mfr+3], outline=FUN+(255,), width=3)
    d.ellipse([fcx-R,fcy-R,fcx+R,fcy+R], fill=CELLPINK+(255,), outline=(198,140,128,255), width=3)
    d.ellipse([fcx-rin,fcy-rin,fcx+rin,fcy+rin], fill=COLLOID+(255,), outline=(210,152,124,255), width=3)
    for a in range(0,360,28):
        nx=fcx+math.cos(math.radians(a))*(R-22); ny=fcy+math.sin(math.radians(a))*(R-22)
        d.ellipse([nx-7,ny-7,nx+7,ny+7], fill=NUC+(255,))
    d.rectangle([zbx-34,zby-26,zbx+34,zby+26], outline=FUN+(255,), width=4)
    # (C) ラベル
    ctext(gpx+tw//2, 96, "甲状腺", fLoc, CHALK)
    ctext(238, 248, "濾胞の集まり（組織）", fLoc, CHALK)
    ctext(fcx, fcy-58, "コロイド", fLoc, DARK)
    ctext(fcx, fcy+R+10, "濾胞（1個）", fLoc, CHALK)
    # 右：アピカル膜ズーム（大きく・縦に展開）
    PX0, PX1 = 430, 1575; BOXT, BOXB = 160, 862
    d.rounded_rectangle([PX0, BOXT, PX1, BOXB], radius=18, outline=FUN+(255,), width=4)
    mem_y0 = 636; band_h = 92
    d.rectangle([PX0+4, BOXT+3, PX1-4, mem_y0+4], fill=COLLOID+(255,))
    d.rectangle([PX0+4, mem_y0+band_h-4, PX1-4, BOXB-3], fill=CELLPINK+(255,))
    _membrane(d, mem_y0, PX1-4, band_h, x0=PX0+4)
    # ①酸化ゾーン／②有機化ゾーン＝背景を別色で薄く塗り分け（ユーザー要望2026-08-14）。コロイド面の上に淡いオーバーレイ。
    _zx = 905   # ①と②の境界X
    _ov = Image.new("RGBA", (W, H), (0,0,0,0)); _od = ImageDraw.Draw(_ov)
    _od.rounded_rectangle([PX0+8, BOXT+8, _zx, mem_y0-6], radius=16, fill=(255,150,60,34))    # ①酸化＝暖色(オレンジ)
    _od.rounded_rectangle([_zx+10, BOXT+8, PX1-8, mem_y0-6], radius=16, fill=(90,200,150,30))  # ②有機化＝寒色(緑)
    im.alpha_composite(_ov); d = ImageDraw.Draw(im)
    # ゾーンラベル（NIS図と同じ＝左端の枠でコロイド側／細胞内を明示）
    lbox(512, 192, "コロイド内", fS, fill=(206,192,174), txt=(58,42,28))   # ゾーン=左上角・コロイド色寄せの明色背景で他ラベルと区別
    lbox(1474, 828, "濾胞細胞内", fS, fill=(210,172,168), txt=(70,38,38))   # ゾーン=右下角・細胞色寄せの明色背景で他ラベルと区別
    tcx = 620
    e_l, e_r, e_t, e_b = tcx-100, tcx+100, mem_y0-210, mem_y0-18
    d.ellipse([e_l, e_t, e_r, e_b], fill=TEAL+(255,), outline=TEAL_D+(255,), width=7)
    d.rounded_rectangle([tcx-20, e_b-4, tcx+20, mem_y0+band_h+30], radius=10, fill=TEAL+(255,), outline=TEAL_D+(255,), width=6)
    d.polygon([(tcx-36, mem_y0-108),(tcx+42, mem_y0-108),(tcx+18, mem_y0-28),(tcx-18, mem_y0-28)], fill=COLLOID+(255,))
    lbox(tcx, mem_y0+band_h+92, "TPO（酵素）", fL, tip=(tcx, mem_y0+band_h+30), txt=(150,230,220))
    for (x,y) in [(792,368),(840,352),(884,372)]:
        ball_lbl(x, y, 22, IODINE, IODINE_D, "I-")
    lbox(760, 298, "ヨウ素（I-）", fS, tip=(792,354), txt=(238,214,250))
    d.line([(tcx+2, mem_y0-210),(tcx+2, mem_y0-118)], fill=IODINE+(255,), width=6)
    ahead((tcx+2, mem_y0-112),(tcx+2, mem_y0-210), 16, IODINE)
    ball_lbl(tcx+2, mem_y0-232, 20, IODINE, IODINE_D, "I-")
    ax, ay, ar = tcx+2, mem_y0-70, 20
    d.ellipse([ax-ar-8, ay-ar-8, ax+ar+8, ay+ar+8], outline=(255,176,44,255), width=4)
    for k in range(12):
        an=math.radians(k*30)
        d.line([(ax+math.cos(an)*(ar+4), ay+math.sin(an)*(ar+4)),(ax+math.cos(an)*(ar+18), ay+math.sin(an)*(ar+18))], fill=(255,168,36,255), width=4)
    ball_lbl(ax, ay, ar, IODINE, IODINE_D, "I-")
    lbox(tcx-30, mem_y0-392, "①酸化→活性ヨウ素", fS, tip=(ax, ay), fill=(150,82,28), txt=(255,226,186))   # ①=種別:酸化＝暖色(オレンジ)背景で区別
    bby = 430; bx0, bx1 = tcx+70, PX1-70
    pts=[]; x=bx0
    while x<=bx1:
        pts.append((x, bby+120+math.sin((x-bx0)/40.0)*18)); x+=10
    d.line(pts, fill=(150,132,96,255), width=14, joint="curve")
    RX = [960, 1215, 1470]
    _tyr(d, RX[0], bby+80, 78, iodine=0); _tyr(d, RX[1], bby+80, 78, iodine=1); _tyr(d, RX[2], bby+80, 78, iodine=2)
    for (xa,xb) in [(RX[0]+106, RX[1]-106),(RX[1]+106, RX[2]-106)]:   # 結合要素(環＋ヨウ素)から矢印を十分離す(ユーザー要望2026-08-14)
        d.line([(xa, bby+20),(xb, bby+20)], fill=(88,74,60,255), width=7); ahead((xb+2,bby+20),(xa,bby+20),18,(88,74,60))
    d.line([(tcx+40, mem_y0-88),(RX[0]-98, bby+36)], fill=(86,74,62,255), width=6)   # TPO→チロシンの矢印もチロシン環から離す
    ahead((RX[0]-88, bby+38),(tcx+40, mem_y0-88), 18, (86,74,62))
    lbox(1085, 258, "②結合（有機化）", fS, fill=(28,104,76), txt=(202,240,222))   # ②=種別:有機化＝寒色(緑)背景で区別・図形と重ならない位置へ
    lbox(RX[0], 190, "チロシン", fL2, tip=(RX[0], bby+20), txt=(244,238,226))
    lbox(RX[1], 190, "MIT（1個）", fL2, tip=(RX[1], bby+20), txt=(238,214,250))
    lbox(RX[2], 190, "DIT（2個）", fL2, tip=(RX[2], bby+20), txt=(238,214,250))
    lbox(1085, 598, "サイログロブリン(Tg)", fS, tip=(1085, 558), txt=(216,198,162))
    lbox(1230, mem_y0+band_h+40, "アピカル膜（＝コロイド側の細胞膜）", fS, tip=(1230, mem_y0+band_h))
    # 旧「この膜より下＝甲状腺の濾胞細胞の中」注記は、右下角の「濾胞細胞内」ゾーンラベル＋アピカル膜ラベルに集約したため削除
    out = os.path.join(MOL, "TPO機構_模式図_simple.png")
    if not _LINT.get("nosave"):
        im.save(out); print("TPO 簡易・拡大版:", out, im.size)
    return out


def gen_nis_simple():
    """NISの「簡易・動力込み版」（本編用 main_simple）＝入れ子ロケーター＋NIS 2状態キャリア＋Na/K-ATPaseポンプ(動力源)。
    「Na+勾配を作る本体＝ポンプ」を明示し二次性能動輸送の全体像を1枚に（ユーザー承認2026-08-14）。
    出力: NIS機構_模式図_simple.png（compose_figureがmain_simpleとして優先使用）。"""
    import math
    from PIL import Image, ImageDraw
    W, H = 1600, 900
    im = _vgrad(W, H, BG_TOP, BG_BOT); d = ImageDraw.Draw(im)
    CHALK=(232,238,246); DARK=(66,48,42)
    COLLOID=(236,222,212); CELLPINK=(238,198,192); NUC=(188,118,108)
    NA=(245,165,60); NA_D=(205,130,35); K=(90,200,150); K_D=(55,150,110)
    TEAL_=(72,176,164); TEALD_=(40,130,120); PUMP=(70,120,195); PUMPD=(45,85,150)
    FUN=(194,203,214); FUNFILL=(42,52,59)
    fTitle=_font(38); fL2=_font(32); fS=_font(28); fXS=_font(23); fLoc=_font(29)
    def ctext(cx,y,t,f,fill):
        w=d.textlength(t,font=f); d.text((cx-w/2,y),t,font=f,fill=fill+(255,)); return w
    def lbox(cx,cy,t,f,tip=None,fill=(8,16,22),txt=CHALK,oc=(150,166,182),ow=2):
        w=d.textlength(t,font=f); h=f.size; pad=13
        if tip:
            d.line([(cx,cy),tip],fill=(150,166,182,255),width=3); d.ellipse([tip[0]-6,tip[1]-6,tip[0]+6,tip[1]+6],fill=(150,166,182,255))
        d.rounded_rectangle([cx-w/2-pad,cy-h/2-8,cx+w/2+pad,cy+h/2+10],radius=11,fill=fill+(236,),outline=oc+(255,),width=ow)
        d.text((cx-w/2,cy-h/2-1),t,font=f,fill=txt+(255,))
        _lintreg("label", cx-w/2-pad, cy-h/2-8, cx+w/2+pad, cy+h/2+10, t, f.size)
    def ahead(tip,frm,size,col): _arrow_head(d,tip,frm,size,col)
    def ball_lbl(cx,cy,r,col,cold,lab):
        d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=col+(255,),outline=cold+(255,),width=2)
        sz=int(r*1.15); bf=_font(sz,bold=True); bb=d.textbbox((0,0),lab,font=bf)
        while sz>9 and (bb[2]-bb[0])>2*r-5:
            sz-=1; bf=_font(sz,bold=True); bb=d.textbbox((0,0),lab,font=bf)
        d.text((cx-(bb[2]-bb[0])/2, cy-(bb[3]-bb[1])/2-bb[1]), lab, font=bf, fill=(255,255,255,255))
        _lintreg("atom", cx-r, cy-r, cx+r, cy+r, lab, 0)
    def mini_follicle(cx,cy,r):
        d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=CELLPINK+(255,),outline=(198,140,128,255),width=2)
        ri=r*0.6; d.ellipse([cx-ri,cy-ri,cx+ri,cy+ri],fill=COLLOID+(255,),outline=(210,152,124,255),width=2)
        for a in range(0,360,51):
            nx=cx+math.cos(math.radians(a))*(r-4); ny=cy+math.sin(math.radians(a))*(r-4); d.ellipse([nx-3,ny-3,nx+3,ny+3],fill=NUC+(255,))
    ctext(W/2,16,"NIS（Na+/I-シンポーター）＝基底膜の運び屋。動力＝Na/K-ATPase",fTitle,CHALK)
    gpx,gpy,tw=64,120,86
    try:
        thy=Image.open(r"C:\claude_shared\素材DB\医療\解剖_臓器別\甲状腺_servier模式図.png").convert("RGBA")
        th=int(thy.height*tw/thy.width); thy=thy.resize((tw,th))
    except Exception: thy=None; th=84
    gbx,gby=gpx+tw//2+13,gpy+th//2
    ccx,ccy=246,300; mfx,mfy,mfr=ccx-40,ccy+40,25
    fcx,fcy,R=160,590,120; rin=R-42
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
        mini_follicle(ccx+dx,ccy+dy,rr)
    mini_follicle(mfx,mfy,mfr); d.rectangle([mfx-mfr-3,mfy-mfr-3,mfx+mfr+3,mfy+mfr+3],outline=FUN+(255,),width=3)
    d.ellipse([fcx-R,fcy-R,fcx+R,fcy+R],fill=CELLPINK+(255,),outline=(198,140,128,255),width=3)
    d.ellipse([fcx-rin,fcy-rin,fcx+rin,fcy+rin],fill=COLLOID+(255,),outline=(210,152,124,255),width=3)
    for a in range(0,360,28):
        nx=fcx+math.cos(math.radians(a))*(R-20); ny=fcy+math.sin(math.radians(a))*(R-20); d.ellipse([nx-6,ny-6,nx+6,ny+6],fill=NUC+(255,))
    CAP=(214,86,78)
    for a in range(0,360,24):
        cx2=fcx+math.cos(math.radians(a))*(R+26); cy2=fcy+math.sin(math.radians(a))*(R+26); d.ellipse([cx2-7,cy2-7,cx2+7,cy2+7],fill=CAP+(255,),outline=(150,45,42,255),width=1)
    d.rectangle([zbx-32,zby-24,zbx+32,zby+24],outline=FUN+(255,),width=4)
    ctext(gpx+tw//2,92,"甲状腺",fLoc,CHALK)
    ctext(232,236,"濾胞の集まり（組織）",fLoc,CHALK)
    ctext(fcx,fcy-8,"コロイド",fLoc,DARK)
    ctext(fcx,fcy+R+58,"濾胞（1個）",fLoc,CHALK)
    _lgy=fcy+R+112
    d.ellipse([76-11,_lgy-11,76+11,_lgy+11],fill=CAP+(255,),outline=(150,45,42,255),width=2)
    d.text((96,_lgy-16),"＝毛細血管（血液）",font=fS,fill=(255,200,200,255))
    PX0,PX1=430,1575; BOXT,BOXB=150,860
    mem_y0=430; band_h=88
    BLOOD=(138,60,62)
    d.rounded_rectangle([PX0,BOXT,PX1,BOXB],radius=18,outline=FUN+(255,),width=4)
    d.rectangle([PX0+4,BOXT+3,PX1-4,mem_y0+4],fill=BLOOD+(255,))
    d.rectangle([PX0+4,mem_y0+band_h-4,PX1-4,BOXB-3],fill=CELLPINK+(255,))
    _membrane(d,mem_y0,PX1-4,band_h,x0=PX0+4)
    mid=mem_y0+band_h//2
    def pump(cx):
        d.rounded_rectangle([cx-78,mem_y0-58,cx+78,mem_y0+band_h+58],radius=30,fill=PUMP+(255,),outline=PUMPD+(255,),width=6)
        d.ellipse([cx-26,mid-26,cx+26,mid+26],fill=(40,80,140,255)); ctext(cx,mid-16,"P",fL2,(240,205,110))
    px=640; pump(px)
    ahead((px-34,mem_y0-150),(px-34,mem_y0+30),16,NA); d.line([(px-34,mem_y0+30),(px-34,mem_y0-150)],fill=NA+(255,),width=6)
    for (dx,dy) in [(-34,-176),(-62,-140),(-8,-140)]: ball_lbl(px+dx,mem_y0+dy,17,NA,NA_D,"Na+")
    ahead((px+40,mem_y0+band_h+150),(px+40,mem_y0+band_h-20),16,K); d.line([(px+40,mem_y0+band_h-20),(px+40,mem_y0+band_h+150)],fill=K+(255,),width=6)
    for (dx,dy) in [(40,176),(66,142)]: ball_lbl(px+dx,mem_y0+band_h+dy,15,K,K_D,"K+")
    ctext(px,mid+30,"ATP→ADP",fXS,(240,205,110))
    lbox(px,mem_y0-244,"Na/K-ATPase（動力源）",fS,tip=(px,mem_y0-58),txt=(180,210,255),oc=PUMP,ow=3)
    ctext(px-128,mem_y0-206,"Na+を外へ(3)",fXS,(250,190,120)); ctext(px+152,mem_y0+band_h+108,"K+を中へ(2)",fXS,(60,175,125))
    def carrier(cx,open_up):
        bw,top,bot=76,mem_y0-52,mem_y0+band_h+52
        d.rounded_rectangle([cx-bw,top,cx+bw,bot],radius=30,fill=TEAL_+(255,),outline=TEALD_+(255,),width=6)
        if open_up: cav=[(cx-48,top-2),(cx+48,top-2),(cx+20,mid+12),(cx-20,mid+12)]
        else: cav=[(cx-48,bot+2),(cx+48,bot+2),(cx+20,mid-12),(cx-20,mid-12)]
        d.polygon(cav,fill=(30,20,22,255) if open_up else CELLPINK+(255,))
    lx2=1080; carrier(lx2,True)
    ball_lbl(lx2-22,mem_y0-4,20,NA,NA_D,"Na+"); ball_lbl(lx2+22,mem_y0-2,20,NA,NA_D,"Na+"); ball_lbl(lx2,mem_y0+22,22,IODINE,IODINE_D,"I-")
    rx2=1420; carrier(rx2,False)
    ball_lbl(rx2-22,mem_y0+band_h+20,20,NA,NA_D,"Na+"); ball_lbl(rx2+22,mem_y0+band_h+16,20,NA,NA_D,"Na+"); ball_lbl(rx2,mem_y0+band_h+52,22,IODINE,IODINE_D,"I-")
    d.arc([lx2+40,308,rx2-40,478],start=180,end=360,fill=CHALK+(255,),width=10); ahead((rx2-44,400),(rx2-90,346),24,CHALK)
    ctext((lx2+rx2)//2,280,"構造変化",fS,CHALK)
    lbox(lx2,mem_y0-170,"①血液側で結合",fS,tip=(lx2,mem_y0-40),txt=(238,214,250))
    lbox(rx2,mem_y0-170,"②細胞側で放出",fS,tip=(rx2,mem_y0-40),txt=(238,214,250))
    lbox((lx2+rx2)//2,mem_y0-224,"NIS（運び屋）＝2Na+:1I-",fS,txt=(150,222,206),oc=TEAL_,ow=3)
    for (bx,by) in [(824,320),(876,304),(928,322),(858,352),(910,354)]: ball_lbl(bx,by,15,NA,NA_D,"Na+")
    lbox(844,262,"Na+が多い＝動力",fXS,fill=(112,46,48),txt=(255,214,166),ow=0)
    for i in range(10):
        pxc=980+(i%5)*90+((i//5)*44); pyc=mem_y0+band_h+150+((i//5)*46)
        ball_lbl(pxc,pyc,18,IODINE,IODINE_D,"I-")
    lbox(1200,mem_y0+band_h+250,"I-が血液側より20〜40倍に濃縮",fS,fill=(202,152,160),txt=(88,46,116),ow=0)
    lbox(506,BOXB-42,"細胞内",fS,txt=(226,196,248))
    lbox(1516,176,"血液",fS,txt=(255,200,200))
    lbox(858,mem_y0+band_h+34,"基底膜",fS,tip=(858,mem_y0+band_h),txt=CHALK)
    out=os.path.join(MOL,"NIS機構_模式図_simple.png")
    if not _LINT.get("nosave"):
        im.save(out); print("NIS 簡易・動力込み版:", out, im.size)
    return out


if __name__ == "__main__":
    os.makedirs(MOL, exist_ok=True)
    gen_tpo()
    gen_tpo_simple()
    gen_t4t3()
    gen_radioactive_iodine()
    gen_nis()
    gen_nis_simple()
    print("done")
    # 図レイアウトの決定論チェック（figlint）＝生成のたびに機械が重なり/見切れ/小文字を検査（記憶頼みでなく強制）
    try:
        import figlint
        _ok, _reports = figlint.lint_build_figures()
        figlint._print_reports(_reports)
        if not _ok:
            print("🔴 figlint FAIL＝図のラベルに重なり/見切れあり。上記を修正して再生成すること。")
    except Exception as _e:
        print(f"[warn] figlint実行不可（レイアウト未検査）: {_e}")
