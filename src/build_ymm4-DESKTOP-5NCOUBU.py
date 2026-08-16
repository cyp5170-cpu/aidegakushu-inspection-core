# -*- coding: utf-8 -*-
"""
build_ymm4.py ― script.json + 実音声 から 黒板レイアウトのYMM4プロジェクトを生成

体制: Gemini=脚本/監督 / Claude Code=実装。既存aishi_sd(既存話専用ハードコード)は
"技術"のみ流用し、本スクリプトが新プロジェクトを組む。

仕様（完成イメージ output/final_chalkboard_mockup.png 準拠）:
  - 1920x1080 / 60fps。木枠付き深緑黒板。
  - タイトル 左上(50,50) 黄チョーク。 立ち絵 左=茜(X50)/右=葵(X1390)。
  - 解説画像=中央カード(600,180 / 720x405)＋赤青マグネットピン。
  - 字幕=下部・半透明漆黒バー＋白44px＋話者カラー縁取り(茜#E63946/葵#0077B6)。
  - 実音声(audio/<id:03d>_<speaker>.wav)を配置＝尺同期。感情モーション。OP/ED全画面カード。
"""
from __future__ import annotations
import json, copy, re, sys, io, wave, contextlib, math, struct, hashlib
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "src" / "_templates"

def _arg_ep(default="02"):
    # --ep NN を先読み（パス定数を確定するため argparse より前に解決）
    for i, a in enumerate(sys.argv):
        if a == "--ep" and i + 1 < len(sys.argv): return sys.argv[i + 1].zfill(2)
        if a.startswith("--ep="): return a.split("=", 1)[1].zfill(2)
    return default

def _arg_dir():
    # --dir episodes/iodine/ep01 形式（シリーズ別親フォルダ階層）。指定時は--epより優先。
    for i, a in enumerate(sys.argv):
        if a == "--dir" and i + 1 < len(sys.argv): return sys.argv[i + 1]
        if a.startswith("--dir="): return a.split("=", 1)[1]
    return None

_DIR = _arg_dir()
if _DIR:
    EP_ROOT = ROOT / _DIR                       # 例: episodes/iodine/ep01（シリーズ別親フォルダ）
    _m = re.search(r"(\d+)", EP_ROOT.name)      # フォルダ名末尾の数字を話数に（"ep01"→"01"）
    EP = (_m.group(1) if _m else "1").zfill(2)
else:
    EP = _arg_ep()                              # 話数("01"/"02"…)。--ep で指定
    EP_ROOT = ROOT / "episodes" / f"ep{EP}"     # 話別ワークスペース（後方互換）
COMMON  = ROOT / "assets" / "common"            # 全話共通素材(OP/ED/アイキャッチ/bg_loop/UI/_fx/_ref)
SCRIPT_JSON = EP_ROOT / "script.json"
IMAGES  = EP_ROOT / "images"                    # その話専用の中央イラスト・写真
CHARS   = ROOT / "assets" / "characters"        # 立ち絵(共通)
AUDIO   = EP_ROOT / "audio"                     # その話の音声wav
OUT     = EP_ROOT / "output" / f"Pharma_Ep{int(EP)}.ymmp"
EFFDIR = Path(r"C:\claude_shared\aishi_sd\effects")

def find_img(name):
    # 素材解決: 話別images → 共通common の順（op_title_card等の共通UIはcommonに集約）
    for base in (IMAGES, COMMON):
        p = base / name
        if p.exists(): return p
    return IMAGES / name

FPS = 60
W, H = 1920, 1080
GAP = 30           # 行間フレーム(0.5s・間を取る／早口感の緩和)
SECTION_GAP = 48   # 章の切れ目に足す間(0.8s・オープニング→本編が唐突な件)
OP_LEN = 240       # OP全画面動画(4.0s@60fps)
ED_LEN = 540       # ED全画面(9.0s)。ユーザー要望で余韻を延長(6→9s)。※ep03が4.44分(444=不吉)になる話数は要確認
CHANNEL_NAME = ""  # チャンネル名（未定）。決まったらここに入れるとED末尾カードの上部に表示される。空なら非表示。

# レイヤー（YMM4は【数字が大きい＝前面】。背景=小/字幕=大）
L_BG, L_AUD, L_TALKBG, L_CARD, L_PIN, L_AK, L_AO, L_EXPR, L_TITLE, L_SUBBAR, L_SUBTXT, L_OPED = 1, 2, 3, 4, 5, 9, 9, 7, 8, 6, 12, 15  # L_SUBBAR=6＝立ち絵(9)より後ろ＝薄い黒背景が立ち絵を隠さない（ユーザー要望）
# 立ち絵(L_AK/L_AO)を9へ＝カード(4)/タイトル(8)/用語解説・豆知識より前面（＝最前で被らない）。字幕(10/12)は可読性のため立ち絵より上に維持。
MAX_LAYER = 18

# --- 音響レイヤ・素材（BGM/SE/アイキャッチ/サムネフック） ---
# 音声(VoiceItem/AudioItem)はL_AUD=2。BGM/SEは占有が被らない別レイヤに置く（同一レイヤ重なり=YMM4で不正）。
L_HOOK, L_SE2, L_BGM, L_SE1 = 11, 17, 13, 14   # SE2は立ち絵に9を明け渡して17へ（音声レイヤーは視覚に影響なし）
BGMDIR = ROOT / "assets" / "bgm"
SEDIR  = ROOT / "assets" / "se"
def bgm_path(name):
    """BGM解決：話数別 episodes/epNN/bgm/ を最優先→無ければ共通 assets/bgm。
    テーマ毎にBGMを変えたい時は epNN/bgm/ に同名ファイルを置くだけで差し替わる（AI歴史流用曲の脱却口）。"""
    if not name: return None
    ep = EP_ROOT / "bgm" / name
    return ep if ep.exists() else (BGMDIR / name)
BGM_VOL, SE_VOL = 4.0, 45.0      # BGMは台詞を邪魔しない低音量(7→4)、SEは控えめ(55→45・少し大きい指摘)
OPED_BGM_VOL = 45.0              # OP/ED専用BGMは台詞が無いので大きめ（BGM_VOL=4だと小さすぎ指摘）
EYE_LEN = 300                    # 中盤アイキャッチ 5.0s @60fps（キャラ登場アニメ素材の尺と一致・ループ無し）

# --- 追加演出レイヤ（タイトル背景パネル/ズーム強調/チャプターバー/ワイプ/感情エフェクト最前面） ---
L_TITLEBG, L_ZOOM, L_CHAP, L_WIPE, L_FX = 5, 7, 8, 15, 16

# --- 追加写真ペタッ（史実写真を既存カードに重ねて貼る） ---
PHOTO_H = 360   # 追加写真の高さpx（右上に大きく＝史実写真を見せる）
PHOTO_SKIP_IDS = set()  # 重複回避はGemini側でタグ管理（似た写真は付けない方針）。必要ならidを追加
# card_br/card_bl はカード下コーナーに小さく（パターンE/F）。黒板注釈(見出しy660〜)より上に収める
PHOTO_POS = {"card_br": (1215, 550), "card_bl": (745, 550), "TR": (1560, 330),
             "TL": (400, 340), "BR": (1470, 640), "BL": (440, 640)}

SUB_FONT = 56.0    # 確定版：スマホ視認性MAXの超極太56px
SUB_Y = 488.0      # 下部シネマシャドウ内の中央／さらに下へ＝ユーザー要望(460→488)
PLATE_Y = 372.0     # 足元ネームプレートのY（中心原点）
NAME = {"akane": "琴葉茜", "aoi": "琴葉葵", "both": "琴葉姉妹"}
BORDER = {"akane": "#FFE63946", "aoi": "#FF0077B6", "both": "#FF9B30D9"}  # both=紫（茜赤+葵青＝二人）
NAME_COLOR = {"akane": "#FFFF7A88", "aoi": "#FF6EC0F0", "both": "#FFF0F0F0"}  # 名前ラベル(明るめ)
SUB_COLOR = {"akane": "#FFFF8FA0", "aoi": "#FF86D0FF", "both": "#FFFEF08A"}   # 字幕本文の話者カラー（茜=淡赤/葵=淡青/both=黄）＝キャラ連動
NAME_X = 70        # 名前ラベルの左端px（固定）
# 字幕バーは以前の「中央だけ・半透明黒バー（全長単一）」＝ユーザー方針（話者連動の色バーは主張が強すぎ却下）。
# 字幕テキストは白＋話者カラー縁取り（BORDER）、話者名は足元ネームプレート。
# --- 左カラム 個別背景色パネル（モック確定・維持） ---
GLOSS_BG, GLOSS_BD = (240, 249, 255, 246), (56, 189, 248, 255)   # 用語解説=スカイミント#f0f9ff/枠#38bdf8
TRIVIA_BG, TRIVIA_BD = (255, 251, 235, 246), (245, 158, 11, 255) # 豆知識=カスタード#fffbeb/枠#f59e0b
CHIBI_H = 400                            # 立ち絵を小さく（学習用＝資料を主役に。500→400）
CHIBI_LEFT_X, CHIBI_RIGHT_X = 30, 1470   # px 左端（確定版：420×420バストアップ）
CARD_PX = (555, 110, 1325, 680)          # x,y,w,h。チャプターバー復活に伴いY30→110へ下げ（上部バーと非干渉）。右寄せは用語解説を空けるため維持
IODINE_LEGEND_KEYS = ("t3_t4", "lego", "tpo")   # image_keywordにこの語を含むカード＝紫球がヨウ素＝「紫球＝ヨウ素」凡例を焼き込む（ユーザー承認2026-08-11）
DB = r"C:\claude_shared\素材DB"   # 全プロジェクト共通の資材DB（単体透過部品・模式図・PDB/AlphaFold実構造・PubChem構造式）。詳細=DB内_README/_検品基準
# 部品合成（compose_figure）＝"正確な図をこちらで組む"。image_keyword→{main:模式図, inset:実構造}。タンパク質は模式図(分かる)＋実構造(正確)の2段構え
COMPOSITIONS = {
    "ep01_nis_pump_automatic_door_3d": {
        "main":  r"医療\細胞_分子\NIS機構_模式図.png",
        "inset": r"医療\細胞_分子\タンパク質構造_PDB_AlphaFold\NIS_pdb7uv0_構造.jpeg",
        "inset_cap": "実測の立体構造（cryo-EM・PDB 7UV0）",  # 実測=実験構造。予測(AlphaFold)は「予測構造」と書き分けること
        "inset_supplement": {"term": "NISの本当の姿", "note": "実際のNISはこんなに複雑な立体構造をしています"},  # オプションA：実構造は本編から外し補足へ
        "labels": [   # tx,ty=指す点／lx,ly=ラベル位置（main画像の割合）。※NIS図はキャリア(交互アクセス)＝左が外向き結合状態
            {"tx": 0.29, "ty": 0.50, "lx": 0.22, "ly": 0.80, "text": "ヨウ素を汲み上げるNIS", "color": "teal"},
            {"tx": 0.32, "ty": 0.33, "lx": 0.50, "ly": 0.06, "text": "ヨウ素", "ion": "I",  "charge": "−", "color": "purple"},
            {"tx": 0.25, "ty": 0.34, "lx": 0.13, "ly": 0.06, "text": "ナトリウム", "ion": "Na", "charge": "＋", "color": "gold"},
        ],
        "zones": [
            {"x": 0.02, "y": 0.40, "text": "血液側"},
            {"x": 0.02, "y": 0.63, "text": "甲状腺の細胞"},
        ],
    },
    # id12：NIS詳細（同じ模式図を再利用し、動力＝Naの濃度差／血中の20〜40倍に超濃縮＝二次性能動輸送を強調）。旧AI画像は英語焼込み＋偽タンパクで差替
    "ep01_nis_pumping_mechanism_detail_3d": {
        "main":  r"医療\細胞_分子\NIS機構_模式図.png",
        "inset": r"医療\細胞_分子\タンパク質構造_PDB_AlphaFold\NIS_pdb7uv0_構造.jpeg",
        "inset_cap": "実測の立体構造（cryo-EM・PDB 7UV0）",
        "inset_supplement": {"term": "NISの本当の姿", "note": "実際のNISはこんなに複雑な立体構造をしています"},
        # 台詞(id11/12)＝「専用の自動ドア(NIS)がナトリウムの流れの勢いを使い、血液の20〜40倍の濃さでヨウ素を吸い込む」。
        # 台詞に無い専門語(二次性能動輸送・濃度勾配・濃度差)は図に出さない＝深い機構は別編(補足編)で扱う
        "labels": [
            {"tx": 0.25, "ty": 0.34, "lx": 0.21, "ly": 0.06, "text": "ナトリウムの勢いが動力", "color": "gold"},
            {"tx": 0.62, "ty": 0.78, "lx": 0.62, "ly": 0.92, "text": "ヨウ素を20〜40倍に濃縮", "color": "purple"},
            {"tx": 0.50, "ty": 0.31, "lx": 0.66, "ly": 0.06, "text": "構造が変わって運ぶ", "color": "teal"},
        ],
        "zones": [
            {"x": 0.02, "y": 0.40, "text": "血液側"},
            {"x": 0.02, "y": 0.63, "text": "甲状腺の細胞"},
        ],
    },
    # id14：TPO（有機化）＝TPOが過酸化水素でヨウ素を活性化し、サイログロブリンのチロシン残基へ付加。実構造=AlphaFold予測(P07202)。AIの偽タンパクを差替
    "ep01_tpo_enzyme_glue_assembly_3d": {
        "main":  r"医療\細胞_分子\TPO機構_模式図.png",
        "inset": r"医療\細胞_分子\タンパク質構造_PDB_AlphaFold\TPO_alphafold_P07202_構造.jpeg",
        "inset_cap": "予測構造（AlphaFold・P07202）",   # 予測=AlphaFold。実測(PDB)と書き分け
        "inset_supplement": {"term": "TPOの本当の姿", "note": "実際のTPOはこんなに複雑な立体構造をしています"},
        # ★半正確版（濾胞ロケーター＋アピカル膜ズーム）に差替＝ラベル/ゾーン/注釈は全てgen_tpo側で焼込み済のためcompose側は空（二重回避）
        "labels": [],
        "zones": [],
    },
    # id8：T3/T4の構造式＝PubChem実データの比較図（T4=ヨウ素4個 / T3=3個）。図中に説明を焼込済みなのでラベル/insetは不要。AIのball-stick偽構造を差替
    "ep01_t3_t4_molecular_lego_3d": {
        "main": r"医療\細胞_分子\T4T3_構造比較_pubchem.png",
    },
    # ── ロケーター型（カード全体がミニ黒板／事実=実物準拠・比喩=様式化の方針）──
    # 位置系＝上半身＋位置円＋リード線＋実物甲状腺ズーム。臓器のみ＝甲状腺を中央に大きく。
    # id2＝冒頭「原発事故時にヨウ素剤を飲む」の話＝原発＋安定ヨウ素剤の2枚並び（実物色に忠実な汎用オリジナル作画・ロゴなし）
    "ep01_thyroid_what_and_where_curious": {
        "layout": "duo",
        "title": "原発事故と「安定ヨウ素剤」", "subtitle": "なぜ薬を飲むと放射線から体を守れる？",
        "left":  r"医療\薬剤_ヨウ素剤\原発_放射線_いらすとや.png",
        "right": r"医療\薬剤_ヨウ素剤\安定ヨウ素剤_3規格_オリジナル.png",
        "left_label": "原発事故", "right_label": "安定ヨウ素剤", "credit": "原発イラスト：いらすとや",
    },
    "ep01_butterfly_thyroid_anatomy_3d": {   # id3：のどの下＋蝶の形（台詞と一致）＝本体ロケーター＋チョーク注記
        "layout": "locator",
        "title": "甲状腺は「のどの下」にある", "subtitle": "羽を広げた蝶のような形の小さな臓器",
        "body": r"医療\解剖_臓器別\上半身_首_大人_透過.png",
        "organ": r"医療\解剖_臓器別\甲状腺_実物リアル_透過.png",
        "mark": [0.5, 0.47], "organ_label": "甲状腺", "locator_label": "のどの下（首の付け根）",
        "note": "羽を広げた蝶のような形",
    },
    "ep01_why_only_thyroid_concentrates_3d": {
        "layout": "locator",
        "title": "なぜ甲状腺だけがヨウ素を溜め込むのか？", "subtitle": "のどの下にある小さな臓器の秘密",
        "body": r"医療\解剖_臓器別\上半身_首_大人_透過.png",
        "organ": r"医療\解剖_臓器別\甲状腺_実物リアル_透過.png",
        "mark": [0.5, 0.47], "organ_label": "甲状腺", "locator_label": "のどの下（首の付け根）",
    },
    "ep01_what_does_thyroid_produce_3d": {   # id4「普段なにをしてるの」＝id3「のどの下」ロケーターをそのまま流す（ユーザー指示）
        "layout": "locator",
        "title": "甲状腺は「のどの下」にある", "subtitle": "羽を広げた蝶のような形の小さな臓器",
        "body": r"医療\解剖_臓器別\上半身_首_大人_透過.png",
        "organ": r"医療\解剖_臓器別\甲状腺_実物リアル_透過.png",
        "mark": [0.5, 0.47], "organ_label": "甲状腺", "locator_label": "のどの下（首の付け根）",
        "note": "羽を広げた蝶のような形",
    },
    "ep01_thyroid_hormone_spark_plug_3d": {  # id5「着火プラグ」も当面id3「のどの下」ロケーターをそのまま流す（ユーザー指示・良い比喩画像が来たら差替）
        "layout": "locator",
        "title": "甲状腺は「のどの下」にある", "subtitle": "羽を広げた蝶のような形の小さな臓器",
        "body": r"医療\解剖_臓器別\上半身_首_大人_透過.png",
        "organ": r"医療\解剖_臓器別\甲状腺_実物リアル_透過.png",
        "mark": [0.5, 0.47], "organ_label": "甲状腺", "locator_label": "のどの下（首の付け根）",
        "note": "羽を広げた蝶のような形",
    },
    "ep01_why_iodine_needed_question": {     # id7「ヨウ素と元気ホルモンの関係」＝ヨウ素が含まれる/使われるものを複数表示（いらすとや・台詞と一致）
        "layout": "gallery",
        "title": "ヨウ素ってどこにあるの？", "subtitle": "海藻に多く、うがい薬などにも使われるミネラル",
        "items": [
            {"image": r"医療\薬剤_ヨウ素剤\コンブ_ヨウ素源_いらすとや.png", "label": "コンブ"},
            {"image": r"医療\薬剤_ヨウ素剤\わかめ_ヨウ素源_いらすとや.png", "label": "わかめ"},
            {"image": r"医療\薬剤_ヨウ素剤\うがい薬_ヨウ素_いらすとや.png", "label": "うがい薬"},
        ],
        "credit": "イラスト：いらすとや",
    },
    "ep01_child_brain_growth_energy_3d": {   # id6「子どもの成長・体温維持」＝成長期イラスト（いらすとや）
        "layout": "single",
        "title": "子どもの成長に絶対に必要", "subtitle": "元気ホルモンが成長と体温維持を支える",
        "image": r"医療\薬剤_ヨウ素剤\子どもの成長期_いらすとや.png",
        "credit": "イラスト：いらすとや",
    },
    "ep01_radiation_threat_bridge_question": {  # id16「なぜ放射線と繋がるの？」＝はてなマーク（いらすとや）で疑問を表現・立ち絵と競合しない
        "layout": "single",
        "title": "なぜ放射線と繋がるの？", "subtitle": "普段の大好物が、なぜおそろしい敵に？",
        "image": r"医療\薬剤_ヨウ素剤\はてなマーク_いらすとや.png",
        "credit": "イラスト：いらすとや",
    },
    "ep01_radiation_iodine_trap_preview": {  # id17「放射性ヨウ素という落とし穴」＝放射性ヨウ素(紫球+放射線)→甲状腺が勘違いして吸収（原発建物は違和感→自作アイコンに）
        "layout": "duo",
        "title": "放射性ヨウ素という落とし穴", "subtitle": "甲状腺は“いつもの大好物”と勘違いして吸い込む",
        "left": r"医療\薬剤_ヨウ素剤\放射性ヨウ素_オリジナル.png",
        "right": r"医療\解剖_臓器別\甲状腺_実物リアル_透過.png",
        "left_label": "放射性ヨウ素", "right_label": "甲状腺が吸収",
    },
}
# 比喩スライドは無理にイラスト化せず「前スライドをそのまま流す」（ユーザー指示）＝同一specで同じ合成図を再利用
COMPOSITIONS["ep01_lego_block_analogy_happy"] = COMPOSITIONS["ep01_t3_t4_molecular_lego_3d"]      # id9レゴ→前=id8 T4/T3
COMPOSITIONS["ep01_vacuum_pump_analogy_shock"] = COMPOSITIONS["ep01_nis_pumping_mechanism_detail_3d"]  # id13バキューム→前=id12 NIS詳細
SHOW_BOARD_CHALK = False                  # 黒板チョーク見出し/箇条書きの表示（カード内に内容があるので既定OFF＝全画面カードを隠さない）。用語解説(term_gloss)/豆知識(trivia)は別＝表示する
SHOW_KEYWORD_POP = False                  # 章頭のキーワードポップ（金チップのscale-in）。ユーザー要望2026-08-11でOFF＝出さない
DIAG_PX = (320, 110, 1280, 720)          # 図解(exp_*/全画面設計1920x1080)用の大型カード枠。フル16:9で最大化。この区間は黒板見出し/箇条書きを非表示にして重なり回避
DIAG_PX_PANEL = (556, 110, 1332, 720)    # 左に用語解説/豆知識パネル(左端X45〜約520)がある行用＝右へ寄せてパネル帯を避ける（資料とパネルのかぶり防止）
TITLE_PX = (50, 50)

MOTION = {"喜び": "jump", "驚き": "shake", "怒り": "shake", "悲しみ": None, "平静": None}
EXPR_MOTION = {"laugh": "jump"}
MAX_SEG, ONE_LINE = 24, 12   # 1行最大字数(30→24・不自然な長い折返しを抑制)
BOUND = "。！？、…」』・"; PARTICLE = "はがをにでともへやのね"
IMAGE_ALIAS = {
    "Talos Greek mythology": "01_talos", "Al-Jazari musical automaton": "02_al_jazari_boat",
    "Chahakobi ningyo karakuri": "03_karakuri_tea", "Ramon Llull Ars Magna": "04_ars_magna",
    "Leibniz Stepped Reckoner": "05_leibniz_calc", "Turing test diagram": "07_turing_test",
    "Dartmouth workshop John McCarthy": "08_dartmouth_conference",
}

_HOME = str(Path.home())
def _expand_home(obj):
    # テンプレJSONの %USERPROFILE% トークンを実ホームへ展開（ユーザー名をハードコードしない）
    if isinstance(obj, str): return obj.replace("%USERPROFILE%", _HOME)
    if isinstance(obj, list): return [_expand_home(x) for x in obj]
    if isinstance(obj, dict): return {k: _expand_home(v) for k, v in obj.items()}
    return obj

def load(p, sig=False):
    return _expand_home(json.load(open(p, encoding="utf-8-sig" if sig else "utf-8")))

IMG_TPL = load(TPL / "image_item.json")
TXT_TPL = load(TPL / "text_item.json")
VID_TPL = load(TPL / "video_item.json")

def anim(v):
    a = copy.deepcopy(IMG_TPL["X"]); a["Values"] = [{"Value": float(v)}]; return a
def anim2(v0, v1, atype="直線移動"):
    """2キーフレームのアニメ値（v0→v1をitem尺全体で線形補間）。AnimationTypeはYMM4実機enum名（"直線移動"）＝MCP採取で確定。ケンバーンズ等に使用。"""
    a = copy.deepcopy(IMG_TPL["X"]); a["Values"] = [{"Value": float(v0)}, {"Value": float(v1)}]
    a["AnimationType"] = atype; return a
def anim_multi(values, atype="直線移動"):
    """多キーフレームのアニメ値（valuesをitem尺全体に等間隔配置し順に線形補間）。上下反復で連続バウンス等に使う。"""
    a = copy.deepcopy(IMG_TPL["X"]); a["Values"] = [{"Value": float(v)} for v in values]
    a["AnimationType"] = atype; return a
def sub_wrap(s, n=14):
    """字幕を必ず2行以内に収める。n文字以下なら1行。超える場合は「両行を全体の半分＋2字以内」に均等分割し、
    その範囲内で助詞・句読点の直後（自然な切れ目）を優先、漢字連続・カタカナ語・英単語の途中は避ける。
    3行化を根絶しつつ、両脇の立ち絵（±800px）と重ならない中央幅に収める（ユーザー要望：字幕は2行まで）。"""
    s = str(s)
    total = len(s)
    if total <= n:
        return s
    mid = total / 2.0
    cap = total // 2 + 2                       # 各行はこの長さ以内＝均等分割を担保（=2行を保証）
    cands = [k for k in range(1, total)
             if max(k, total - k) <= cap
             and s[k] not in _NOHEAD           # 行頭禁則（句読点/閉じ括弧/小書き仮名/長音符…を行頭にしない）
             and s[k - 1] not in _OPEN]        # 行末に開き括弧を置かない
    def _score(k):
        prev, curc = s[k - 1], s[k]
        midword = ((_is_kanji(prev) and _is_kanji(curc)) or
                   (_is_kata(prev) and _is_kata(curc)) or _in_word(s, k))
        sc = abs(k - mid) * 0.1               # 中央からの距離（均等寄せ・軽み）
        if not (prev in BOUND or prev in PARTICLE):
            sc += 2                            # 助詞/句読点の直後でない＝軽ペナルティ
        if midword:
            sc += 5                            # 語の途中は強く回避
        return sc
    k = min(cands, key=_score) if cands else total // 2
    return s[:k] + "\n" + s[k:]

def imgsize(p):
    with Image.open(p) as im: return im.size

def wdur(f):
    try:
        with contextlib.closing(wave.open(str(f), "rb")) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return None

# ---- item builders ----
def _base(tpl, frame, length, layer):
    it = copy.deepcopy(tpl)
    it["Frame"] = int(frame); it["Length"] = max(1, int(length)); it["Layer"] = int(layer)
    it["VideoEffects"] = []; it["Group"] = 0
    return it

def image_item(path, frame, length, layer, x=0.0, y=0.0, zoom=100.0, fade=0.12):
    it = _base(IMG_TPL, frame, length, layer)
    it["FilePath"] = str(path)
    for k in ("X", "Y", "Z", "Rotation"): it[k] = anim({"X": x, "Y": y}.get(k, 0.0))
    it["Zoom"] = anim(zoom); it["Opacity"] = anim(100.0)
    it["FadeIn"] = fade; it["FadeOut"] = fade
    return it

def video_item(path, frame, length, layer, x=0.0, y=0.0, zoom=100.0, fade=0.0):
    it = copy.deepcopy(VID_TPL)
    it["FilePath"] = str(path)
    it["Frame"] = int(frame); it["Length"] = max(1, int(length)); it["Layer"] = int(layer)
    for k in ("X", "Y", "Z", "Rotation"): it[k] = anim({"X": x, "Y": y}.get(k, 0.0))
    it["Zoom"] = anim(zoom); it["Opacity"] = anim(100.0)
    it["Volume"] = anim(100.0); it["Pan"] = anim(0.0)
    it["VideoEffects"] = []; it["Group"] = 0
    it["FadeIn"] = fade; it["FadeOut"] = fade; it["IsLooped"] = False
    return it

def text_item(text, frame, length, layer, x=0.0, y=SUB_Y, size=SUB_FONT,
              basepoint="CenterBottom", color="#FFFFFFFF", style_color="#FF101820", maxw=W-160, fade=0.0, thickness=None):
    it = _base(TXT_TPL, frame, length, layer)
    it["Text"] = text
    for k in ("X", "Y", "Z", "Rotation"): it[k] = anim({"X": x, "Y": y}.get(k, 0.0))
    it["Opacity"] = anim(100.0); it["Zoom"] = anim(100.0)
    it["FontSize"] = anim(size); it["MaxWidth"] = anim(float(maxw))
    it["BasePoint"] = basepoint; it["FontColor"] = color
    it["Style"] = "Border"; it["StyleColor"] = style_color
    if thickness is not None: it["StyleThickness"] = anim(float(thickness))
    it["Bold"] = True; it["IsAlwaysOnTop"] = True
    it["IsDevidedPerCharacter"] = False   # 1文字ずつ表示をやめ、最初から全文表示
    it["DisplayInterval"] = 0.0; it["HideInterval"] = 0.0
    it["FadeIn"] = fade; it["FadeOut"] = fade
    return it

def audio_item(path, frame, length, layer=L_AUD, volume=100.0, loop=False, fade_in=0.0, fade_out=0.0, pan=0.0):
    it = {
        "$type": "YukkuriMovieMaker.Project.Items.AudioItem, YukkuriMovieMaker",
        "FilePath": str(path),
        "Volume": anim(volume), "Pan": anim(pan),
        "PlaybackRate": 100.0, "IsLoopedPlayback": loop,
        "FadeIn": fade_in, "FadeOut": fade_out,
        "Group": 0, "Frame": int(frame), "Layer": int(layer),
        "KeyFrames": {"Frames": [], "Count": 0},
        "Length": max(1, int(length)), "ContentOffset": "00:00:00",
        "Remark": "", "IsLocked": False, "IsHidden": False,
    }
    return it

# ---- モーション ----
def load_eff(n):
    p = EFFDIR / n; return load(p) if p.exists() else None
_jump = load_eff("InOutJumpEffect.json"); _rmove = load_eff("RandomMoveEffect.json")
_rrot = load_eff("RepeatRotateEffect.json")   # キラキラ等をゆっくり回転させる
def motion(kind):
    if kind == "jump" and _jump:
        e = copy.deepcopy(_jump)
        for k, v in (("JumpHeight", 30.0), ("EffectTimeSeconds", 1.0), ("IsOutEffect", False)):
            if k in e: e[k] = v
        if "X" in e and not isinstance(e["X"], dict): e["X"] = 0.0
        return [e]
    if kind == "shake" and _rmove:
        e = copy.deepcopy(_rmove)
        try: e["X"]["Values"][0]["Value"] = 16.0; e["Y"]["Values"][0]["Value"] = 5.0
        except Exception: pass
        return [e]
    return []

# ---- 字幕分割 ----
def phrases(t):
    out, b, depth = [], "", 0
    for ch in t:
        b += ch
        if ch in "「『（【〈《": depth += 1
        elif ch in "」』）】〉》": depth = max(0, depth - 1)
        if ch in BOUND and depth == 0: out.append(b); b = ""   # 括弧の内側では区切らない（閉じ括弧の孤立防止）
    if b: out.append(b)
    return out
def wrap2(s):
    if len(s) <= ONE_LINE: return s
    mid = len(s)//2
    for cand in (BOUND, PARTICLE):
        best, bd = None, 99
        for i, ch in enumerate(s[:-1]):
            if ch in cand and abs(i-mid) < bd: bd = abs(i-mid); best = i+1
        if best and 0 < best < len(s): return s[:best] + "\n" + s[best:]
    return s[:mid] + "\n" + s[mid:]
def _in_word(s, i):
    """s[i]の前後が同じ英数字トークン(Microsoft等)の内部か。"""
    if i <= 0 or i >= len(s): return False
    def al(ch): return ord(ch) < 128 and (ch.isalnum() or ch in "-._'")
    return al(s[i-1]) and al(s[i])

_OPEN, _CLOSE = "「『（【〈《", "」』）】〉》"
# 行頭禁則文字（これらの直前では切らない＝行頭に来させない）：句読点・感嘆/疑問符・閉じ括弧・小書き仮名・長音符・々
_NOHEAD = "。、！？…‥」』）】〉》・ー々っゃゅょぁぃぅぇぉゎッャュョァィゥェォヮ｡｣､ｰたてだ"  # 末尾た/て/だ＝動詞語尾は行頭にしない(「し|た」割れ防止)
def _is_kanji(c): return "一" <= c <= "鿿"
def _is_kata(c): return "゠" <= c <= "ヿ" or c == "ｰ"   # カタカナ＋長音符（半角含む）
def _hardsplit(s, n):
    """句読点の無い長フレーズを n字前後で自然に切る。禁則：括弧内で切らない／閉じ括弧を行頭にしない／
       開き括弧を行末にしない／漢字連続・カタカナ語・英単語の途中で切らない。"""
    def ok(k):
        if k <= 0 or k >= len(s): return False
        if s[k] in _NOHEAD: return False   # 行頭禁則：句読点/感嘆符/閉じ括弧/小書き仮名/長音符を行頭にしない
        if s[k-1] in _OPEN: return False   # 行末禁則：開き括弧を行末にしない
        if _is_kanji(s[k-1]) and _is_kanji(s[k]): return False   # 漢字連続の途中
        if _is_kata(s[k-1]) and _is_kata(s[k]): return False     # カタカナ語(パーセプトロン等)の途中
        if _in_word(s, k): return False                   # 英単語の途中
        return True
    out = []
    while len(s) > n:
        win = list(range(min(len(s) - 1, n + 8), max(3, n - 12), -1))
        cand = None
        # 優先：句読点・接続/主題助詞 → の/ね等 → 格助詞(を/が/に/へ＝直後の動詞と密結合＝行末は不自然)は最後
        for tier in ("、。！？…" + "てでもはとや", "のねよわ", "をがにへ"):   # 「し」は除外(した/しますを割るため)
            for k in win:
                if s[k-1] in tier and ok(k): cand = k; break
            if cand: break
        if cand is None:                                   # 自然な助詞が無い→禁則を守れる最寄り位置
            for k in win:
                if ok(k): cand = k; break
        if cand is None:                                   # それでも無ければ前方へ延長（mid-wordより長い方がマシ）
            k = n
            while k < len(s) and not ok(k): k += 1
            cand = k
        out.append(s[:cand]); s = s[cand:]
    if s: out.append(s)
    return out

def split_sub(t):
    segs, cur = [], ""
    for ph in phrases(t):
        for chunk in (_hardsplit(ph, MAX_SEG) if len(ph) > MAX_SEG else [ph]):
            if cur and len(cur)+len(chunk) > MAX_SEG: segs.append(cur); cur = chunk
            else: cur += chunk
    if cur: segs.append(cur)
    segs = [s.strip() for s in segs if s.strip()]
    # 短すぎる断片（「ん！」「え！？」等の相づち＋記号）を隣の行へ統合＝単独表示を防ぐ（多少MAX超過はOK）
    MIN, CAP = 4, MAX_SEG + 8
    merged = []
    for s in segs:
        if merged and len(s) <= MIN and len(merged[-1]) + len(s) <= CAP:
            merged[-1] += s                      # 直前の行末にくっつける（末尾の「ん！」対策）
        else:
            merged.append(s)
    if len(merged) >= 2 and len(merged[0]) <= MIN and len(merged[0]) + len(merged[1]) <= CAP:
        merged[1] = merged[0] + merged[1]; merged.pop(0)   # 行頭が短い場合は次へ
    return merged

def wrap_bullet(b, n=18):
    """黒板の箇条書きを立ち絵とかぶらない幅で折り返す（継続行は全角空白でインデント）。"""
    b = str(b); mark = "・" if b.startswith("・") else ""
    body = b[len(mark):]
    parts = _hardsplit(body, n) if len(body) > n else [body]
    return "\n".join((mark + p if i == 0 else "　" + p) for i, p in enumerate(parts))

# ---- アセット生成 ----
def make_board():
    p = COMMON / "_board_bg.png"
    im = Image.new("RGB", (W, H), (8, 18, 14))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([int(W*0.18), int(H*0.05), int(W*0.82), int(H*0.98)], fill=95)
    glow = glow.filter(ImageFilter.GaussianBlur(260))
    im = Image.composite(Image.new("RGB", (W, H), (20, 40, 32)), im, glow)   # 確定版：モスグリーン#08120e＋中央グロー・枠撤廃
    im.save(p); return p
def make_op_card(meta):
    """OPタイトルカード（黒板×タイトル）＝AI歴史流用OP動画の置換。話数別にキャッシュ。
    タイトルの【…】(サブタイトル)は白・外側は黄。カテゴリラベルを上部に。"""
    FX.mkdir(exist_ok=True)
    title = (meta.get("title") or "").strip()
    key = re.sub(r"[^\w]+", "_", title)[:24] or "op"
    out = FX / f"_opcard_{key}.png"
    if out.exists(): return out
    im = Image.open(make_board()).convert("RGBA"); d = ImageDraw.Draw(im)
    def wrap(t, f, maxw):
        ls = []; line = ""
        for ch in t:
            if d.textlength(line + ch, font=f) > maxw: ls.append(line); line = ch
            else: line += ch
        if line: ls.append(line)
        return ls
    cat = re.sub(r"^[^\wぁ-んァ-ヶ一-鿿]+", "", meta.get("category_label", "")).strip()  # 先頭絵文字(豆腐化)を除去
    if cat:
        d.text((W/2, 285), cat, font=_ttf(42), fill=(232, 232, 220, 255), anchor="mm")
    bi = title.find("【")
    pre = re.sub(r"^[^\wぁ-んァ-ヶ一-鿿【]+", "", (title[:bi] if bi > 0 else title)).strip()  # 先頭の絵文字(💊等・豆腐化)を除去
    brk = title[bi:] if (bi > 0 and "】" in title) else ""
    y = 420
    fmain = _ttf(78)
    for ln in wrap(pre, fmain, W-300):
        d.text((W/2, y), ln, font=fmain, fill=(255, 225, 77, 255), anchor="mm",
               stroke_width=4, stroke_fill=(19, 49, 42, 255)); y += 96
    if brk:
        y += 24; fsub = _ttf(48)
        for ln in wrap(brk, fsub, W-240):
            d.text((W/2, y), ln, font=fsub, fill=(255, 255, 255, 255), anchor="mm",
                   stroke_width=3, stroke_fill=(19, 49, 42, 255)); y += 62
    im.convert("RGB").save(out); return out
def make_caution_mark():
    """免責カット背景用の注意マーク（黄色い警告三角＋！）＋黄色い発光ハロー。"""
    FX.mkdir(exist_ok=True)
    p = FX / "_caution.png"
    if p.exists(): return p
    S = 460
    tri = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(tri)
    m = 34; top = (S/2, m); bl = (m, S - m); br = (S - m, S - m)
    d.polygon([top, bl, br], fill=(242, 201, 76, 235))                    # 黄色三角
    d.line([top, bl, br, top], fill=(35, 26, 8, 240), width=18, joint="curve")  # 濃い縁
    cx = S/2
    d.rounded_rectangle([cx-18, S*0.36, cx+18, S*0.63], radius=9, fill=(35, 26, 8, 240))  # ！の縦棒
    d.ellipse([cx-19, S*0.68, cx+19, S*0.75], fill=(35, 26, 8, 240))                       # ！の点
    # 発光ハロー（明るい黄色の三角をぼかして背後に敷く）
    B = 90; big = Image.new("RGBA", (S + 2*B, S + 2*B), (0, 0, 0, 0))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    gd.polygon([top, bl, br], fill=(255, 224, 92, 255))
    gbig = Image.new("RGBA", big.size, (0, 0, 0, 0)); gbig.paste(glow, (B, B), glow)
    gbig = gbig.filter(ImageFilter.GaussianBlur(32))
    big = Image.alpha_composite(big, gbig); big = Image.alpha_composite(big, gbig)  # 2回で発光を強く
    big.alpha_composite(tri, (B, B))
    big.save(p); return p
def make_subbar():
    # 立ち絵・字幕の下部エリア用の「薄い黒背景」（全幅）。立ち絵より後ろのレイヤ(L_SUBBAR=6)に置くので立ち絵は隠れない（ユーザー要望）。
    p = COMMON / "_subbar.png"
    Hh = 340
    im = Image.new("RGBA", (W, Hh), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for _y in range(Hh):
        d.line([(0, _y), (W, _y)], fill=(1, 3, 2, int(238 * ((_y / float(Hh)) ** 0.55))))   # 下ほど濃い黒（全幅）＝字幕背景を濃く（ユーザー要望）
    im.save(p); return p
def make_green_bg():
    """免責カット用の緑無地背景（端を少し暗くする微ビネット）。ユーザー要望：免責はAIラボ画像でなく緑無地。"""
    p = COMMON / "_greenbg.png"
    if p.exists(): return p
    im = Image.new("RGB", (W, H), (18, 46, 34))
    v = Image.new("L", (W, H), 0); ImageDraw.Draw(v).ellipse([int(-W*0.2), int(-H*0.2), int(W*1.2), int(H*1.2)], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(200))
    im = Image.composite(im, Image.new("RGB", (W, H), (8, 22, 16)), v)
    im.save(p); return p
def make_keyword_pop(text):
    """キーワードポップ＝重要語を一瞬大きく。金チップ＋白枠＋濃い極太字＋影。用語導入時に短時間だけ表示（必要な所だけ）。"""
    FX.mkdir(exist_ok=True)
    key = re.sub(r"[^\w]+", "_", str(text))[:20] or "x"
    out = FX / f"_kw_{key}.png"
    if out.exists(): return out
    f = _ttf(96); d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = int(d0.textlength(str(text), font=f)); pad = 56; W2 = tw + pad*2; H2 = 200; M = 44
    im = Image.new("RGBA", (W2 + 2*M, H2 + 2*M), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle([M, M+7, M+W2, M+7+H2], radius=36, fill=(0, 0, 0, 165))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(15)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([M, M, M+W2, M+H2], radius=36, fill=(247, 201, 76, 255), outline=(255, 255, 255, 240), width=6)
    d.text((M + W2/2, M + H2/2), str(text), font=f, fill=(28, 22, 8, 255), anchor="mm")
    im.save(out); return out
def make_pin(color, name):
    p = COMMON / f"_pin_{name}.png"
    im = Image.new("RGBA", (40, 40), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([4, 4, 36, 36], fill=color + (255,))
    d.ellipse([11, 10, 21, 20], fill=(255, 255, 255, 160))
    im.save(p); return p

# ---- エフェクト系アセット（PILで焼き込み＝YMM4で確実に表示） ----
FX = COMMON / "_fx"
GLOW_RGB = {"akane": (235, 70, 84), "aoi": (40, 130, 210)}
PLATE_BG = {"akane": (200, 60, 74), "aoi": (30, 100, 175), "both": (90, 90, 110)}

def make_framed_card(src, top_band=True, bot_band=True):
    """解説カード：白マット廃止＝シネマ画像を全面表示。後載せ文字が出る側だけ暗いグラデを焼き込み可読化＋極細フチ＋軽い影。
    top_band/bot_band=Falseで該当帯を出さない＝pins/合成図で見出しを消した側を暗くしない（pinsラベルが暗く沈むのを防ぐ）。"""
    FX.mkdir(exist_ok=True)
    out = FX / f"card_{Path(src).stem}_{int(top_band)}{int(bot_band)}.png"
    if out.exists(): return out
    im = Image.open(src).convert("RGBA"); w, h = im.size
    # 後載せタイトル(上)/キャプション(下)の可読用に、文字が出る側だけ暗いグラデを焼き込む
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0)); gd = ImageDraw.Draw(grad)
    th = int(h * 0.28); bh = int(h * 0.24)      # 帯を広く・濃く＝後載せ文字の可読性を最優先
    if top_band:
        for y in range(th):                      # 上帯：外側40%はほぼ不透明、内側60%でフェード
            t = 1 - y / float(th); a = 236 if t > 0.6 else int(236 * ((t / 0.6) ** 1.15))
            gd.line([(0, y), (w, y)], fill=(2, 6, 4, a))
    if bot_band:
        for y in range(bh):                      # 下帯：同様に下端側をほぼ不透明
            yy = h - bh + y; t = y / float(bh); a = 240 if t > 0.6 else int(240 * ((t / 0.6) ** 1.15))
            gd.line([(0, yy), (w, yy)], fill=(2, 6, 4, a))
    im = Image.alpha_composite(im, grad)
    pad = max(10, w // 90)
    canvas = Image.new("RGBA", (w + 2*pad, h + 2*pad), (0, 0, 0, 0))
    shl = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shl.paste(Image.new("RGBA", (w, h), (0, 0, 0, 120)), (pad + 5, pad + 8))
    shl = shl.filter(ImageFilter.GaussianBlur(10))
    canvas = Image.alpha_composite(canvas, shl)
    canvas.alpha_composite(im, (pad, pad))
    ImageDraw.Draw(canvas).rectangle([pad, pad, pad + w - 1, pad + h - 1], outline=(205, 210, 218, 165), width=2)
    canvas.save(out); return out

# ============ 教科書ラベル＆ヨウ素凡例をカード画像に焼き込む（ユーザー要望2026-08-11）============
# overlayのtext_itemだとケンバーンズ(ズーム/パン)に追従せずズレるため、生画像に合成してからframe化する。
# pins=[{x,y,label,pos?,lx?,ly?}]  x,y=指し示す対象点(生画像の0〜1割合)／pos=ラベル配置隅(tl/tr/bl/br)／lx,lyで明示配置も可。
# iodine_legend=True で「紫球＝ヨウ素」凡例を左下に付与（分子/レゴ/TPO等の紫球カード用）。
_PIN_ACCENT = {"gold": (255, 220, 90), "teal": (120, 240, 220), "purple": (200, 120, 235),
               "iodine": (200, 120, 235), "membrane": (255, 220, 90), "green": (150, 230, 120)}
def _draw_sphere(d, cx, cy, r, base=(180, 40, 210)):
    for i in range(r, 0, -1):
        t = i / r
        col = (int(base[0]*(0.35+0.65*(1-t))+30*t), int(base[1]*(0.35+0.65*(1-t))), int(base[2]*(0.35+0.65*(1-t))+20*t), 255)
        d.ellipse([cx-i, cy-i, cx+i, cy+i], fill=col)
    hl = max(3, int(r*0.35))
    d.ellipse([cx-r*0.4-hl, cy-r*0.45-hl, cx-r*0.4+hl, cy-r*0.45+hl], fill=(255, 220, 255, 190))

ANNOT_VER = "v3"   # 描画仕様の版（v2=白ハロー+不透明箱／v3=位置/場所ラベルはリード線なし）。仕様変更で上げる＝ファイル名が変わりYMM4/FXの画像キャッシュを確実に無効化
def make_annotated_card(src, pins=None, iodine_legend=False):
    import hashlib, json as _json
    FX.mkdir(exist_ok=True)
    sig = hashlib.md5((ANNOT_VER + "|" + Path(src).stem + "|" + _json.dumps(pins or [], ensure_ascii=False, sort_keys=True) + "|" + str(iodine_legend)).encode("utf-8")).hexdigest()[:10]
    out = FX / f"_annot_{Path(src).stem}_{sig}.png"
    if out.exists(): return out
    im = Image.open(src).convert("RGBA"); w, h = im.size
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    fs = max(34, int(w * 0.036)); F = _ttf(fs); pad = max(10, int(fs * 0.34)); bh = fs + pad   # スマホ視認性UP（0.028→0.036）
    # --- pins（リード線＋終点ドット＋角丸ラベル）---
    for pin in (pins or []):
        try:
            fx_, fy_ = float(pin["x"]), float(pin["y"])
        except Exception:
            continue
        if not (0.0 <= fx_ <= 1.0 and 0.0 <= fy_ <= 1.0):   # 契約：x,yは0〜1割合。ピクセル値等はskip（破綻防止）
            print(f"[warn] pin座標が0〜1割合でないためskip: {Path(src).stem} x={pin.get('x')} y={pin.get('y')} label={pin.get('label')}")
            continue
        tx, ty = int(fx_ * w), int(fy_ * h)
        text = str(pin.get("label", "")).strip()
        if not text: continue
        acc = _PIN_ACCENT.get(str(pin.get("color", "gold")), (255, 220, 90))
        pos = str(pin.get("pos", "")).lower()
        tw = d.textlength(text, font=F)
        if "lx" in pin and "ly" in pin:
            ax, ay = int(float(pin["lx"]) * w), int(float(pin["ly"]) * h)
            right = ax > w * 0.5
        else:
            corners = {"tl": (0.03, 0.06, False), "tr": (0.97, 0.06, True),
                       "bl": (0.03, 0.86, False), "br": (0.97, 0.86, True)}
            fx, fy, right = corners.get(pos, (0.03, 0.06, False))
            ax, ay = int(w * fx), int(h * fy)
        x0 = ax - (tw + pad * 2) if right else ax
        y0 = ay; x1 = x0 + tw + pad * 2; y1 = y0 + bh
        lx = x0 + (x1 - x0) / 2
        ly = y1 if ty > y1 else y0
        # 特定の点でなく「位置/場所/全体像」を説明するラベルはリード線＆終点ドットを出さない（pin.line=falseでも明示指定可）
        show_line = pin.get("line", True) and not any(kw in text for kw in ("位置", "場所", "全体", "この図", "エリア", "あたり"))
        if show_line:
            d.line([(lx, ly), (tx, ty)], fill=acc + (255,), width=max(3, fs // 12))
            rr = max(7, fs // 5)
            d.ellipse([tx-rr, ty-rr, tx+rr, ty+rr], outline=acc + (255,), width=max(3, fs//13), fill=(255, 255, 255, 235))
        # 暗い画像の上でも埋もれないよう：外側に白ハロー → 不透明ダーク箱 → 太めのアクセント枠
        rad = max(10, fs//3)
        d.rounded_rectangle([x0-4, y0-4, x1+4, y1+4], radius=rad+4, fill=(255, 255, 255, 210))
        d.rounded_rectangle([x0, y0, x1, y1], radius=rad, fill=(12, 20, 30, 255), outline=acc + (255,), width=max(3, fs//12))
        d.text((x0 + pad, y0 + pad - 2), text, font=F, fill=(255, 255, 255, 255))
    # --- ヨウ素凡例（左下・紫球＋「＝ ヨウ素」）---
    if iodine_legend:
        lf = max(30, int(w * 0.032)); LF = _ttf(lf); sf = _ttf(int(lf * 0.62))
        sph_r = int(lf * 0.72); lab = "＝ ヨウ素"; sub = "（紫の球。元素記号 I）"
        lp = int(lf * 0.5)
        tw = max(d.textlength(lab, font=LF), d.textlength(sub, font=sf))
        cw = int(lp + sph_r * 2 + int(lf * 0.5) + tw + lp); chh = int(lf * 2.9)
        x0, y0 = int(w * 0.03), h - chh - int(h * 0.05)
        d.rounded_rectangle([x0, y0, x0 + cw, y0 + chh], radius=int(lf * 0.5), fill=(6, 16, 12, 210), outline=(212, 175, 90, 255), width=3)
        scx, scy = x0 + lp + sph_r, y0 + chh // 2
        _draw_sphere(d, scx, scy, sph_r)
        iw2 = d.textlength("I", font=sf); d.text((scx - iw2/2, scy - lf*0.42), "I", font=sf, fill=(255, 255, 255, 255))
        tx0 = scx + sph_r + int(lf * 0.5)
        d.text((tx0, y0 + int(lf * 0.42)), lab, font=LF, fill=(255, 255, 255, 255))
        d.text((tx0, y0 + int(lf * 1.5)), sub, font=sf, fill=(214, 226, 220, 255))
    out_im = Image.alpha_composite(im, ov)
    out_im.save(out); return out

def _compose_locator(spec):
    """ロケーター型カード（カード全体をミニ黒板に）：全身/上半身＋位置円＋リード線＋実物臓器ズーム＋チョークラベル。
    事実は実物準拠（body/organはDBの透過素材）。spec: title/subtitle/body/organ/mark/organ_label/locator_label。"""
    import hashlib
    FX.mkdir(exist_ok=True)
    sig = hashlib.md5(repr(sorted(spec.items())).encode("utf-8")).hexdigest()[:10]
    out = FX / f"_locator_{sig}.png"
    if out.exists(): return out
    W2, H2 = 1920, 1080
    SLATE=(26,40,43); WOOD=(96,66,44); WOOD_HI=(142,106,72); WOOD_SH=(64,42,26)
    ACCENT=(210,182,126); CHALK=(236,241,238); CHALK_DIM=(150,168,168); GOLD=(226,194,116)
    base=Image.new("RGBA",(W2,H2),WOOD+(255,)); d=ImageDraw.Draw(base)
    d.rounded_rectangle([5,5,W2-5,H2-5],radius=10,outline=WOOD_HI+(255,),width=3)
    frm=26
    d.rounded_rectangle([frm-5,frm-5,W2-frm+5,H2-frm+5],radius=20,outline=WOOD_SH+(255,),width=4)
    d.rounded_rectangle([frm,frm,W2-frm,H2-frm],radius=18,fill=SLATE+(255,),outline=ACCENT+(170,),width=2)
    ttl=spec.get("title",""); sub=spec.get("subtitle","")
    if ttl: d.text((92,66),ttl,font=_ttf(64),fill=CHALK+(255,))
    if sub: d.text((96,152),sub,font=_ttf(34),fill=CHALK_DIM+(255,))
    if ttl or sub: d.line([(94,196),(W2-94,196)],fill=CHALK+(120,),width=2)
    def _fit(im,bw,bh):
        r=min(bw/im.size[0],bh/im.size[1]); return im.resize((int(im.size[0]*r),int(im.size[1]*r)))
    bp=Path(DB)/spec.get("body",""); op=Path(DB)/spec.get("organ","")
    if not op.exists():
        print(f"[warn] _compose_locator: organ画像が無い {op}"); return None
    has_body = bool(spec.get("body")) and bp.exists()
    ocx,ocy=(1360 if has_body else W2//2),(600 if has_body else 620)
    organ=_fit(Image.open(op).convert("RGBA"),(480 if has_body else 560),(540 if has_body else 640))
    ox0,oy0=ocx-organ.size[0]//2,ocy-organ.size[1]//2
    mx=my=None
    if has_body:
        body=_fit(Image.open(bp).convert("RGBA"),520,600); bx,by=410-body.size[0]//2,620-body.size[1]//2
        base.alpha_composite(body,(bx,by))
        mk=spec.get("mark",[0.5,0.47]); mx=bx+int(mk[0]*body.size[0]); my=by+int(mk[1]*body.size[1])
    base.alpha_composite(organ,(ox0,oy0)); d=ImageDraw.Draw(base)
    pd=30; fx0,fy0,fx1,fy1=ox0-pd,oy0-pd,ox0+organ.size[0]+pd,oy0+organ.size[1]+pd
    d.rounded_rectangle([fx0,fy0,fx1,fy1],radius=16,outline=CHALK+(230,),width=3)
    olabel=spec.get("organ_label","")
    if olabel:
        _of=_ttf(48)                                                # スマホ視認性UP（38→48）
        d.text((fx0+18,fy0+12),olabel,font=_of,fill=CHALK+(255,))
        _ow=d.textlength(olabel,font=_of); d.line([(fx0+18,fy0+70),(fx0+18+_ow,fy0+70)],fill=CHALK+(190,),width=3)
    if mx is not None:
        rad=48
        d.line([(mx+rad,my),(fx0,ocy)],fill=CHALK+(210,),width=3)
        d.ellipse([fx0-6,ocy-6,fx0+6,ocy+6],fill=CHALK+(255,))
        d.ellipse([mx-rad,my-rad,mx+rad,my+rad],outline=GOLD+(255,),width=6)
        d.ellipse([mx-6,my-6,mx+6,my+6],fill=GOLD+(255,))
        llabel=spec.get("locator_label","")
        if llabel:
            lf=_ttf(38); lw=d.textlength(llabel,font=lf); lpad=18; lbh=60   # スマホ視認性UP（28→38）
            lx0=mx-lw/2-lpad; lby=my+rad+40
            d.line([(mx,my+rad),(mx,lby)],fill=CHALK+(200,),width=2)
            d.rounded_rectangle([lx0,lby,lx0+lw+lpad*2,lby+lbh],radius=10,fill=(12,30,24,225),outline=CHALK+(150,),width=2)
            d.text((lx0+lpad,lby+lbh/2-24),llabel,font=lf,fill=CHALK+(255,))
    _note=spec.get("note","")                                     # チョーク注記（例：羽を広げた蝶々のような形）＝臓器枠の下に手書き風
    if _note:
        nf=_ttf(44); nw=d.textlength(_note,font=nf); nx=ocx-nw/2; ny=fy1+28   # スマホ視認性UP（34→44）
        d.text((nx,ny),_note,font=nf,fill=CHALK+(255,))
        _wl=[(nx+int(i*14), ny+50+(3 if i%2 else -3)) for i in range(int(nw//14)+1)]   # 波線の下線（チョーク風）
        if len(_wl)>=2: d.line(_wl,fill=CHALK+(190,),width=3,joint="curve")
    base.save(out); return out

MATOME_VER = "chalk1"   # まとめ描画の版（黒板に直接チョーク書き）。仕様変更で上げてキャッシュ無効化
def make_matome_note(title, points):
    """まとめ＝黒板に直接チョークで書く（紙ノートは廃止・ユーザー指摘）。points=[{head,sub},...]（sub任意）。ミニ黒板の木枠に載せた全画面。"""
    import hashlib
    FX.mkdir(exist_ok=True)
    sig = hashlib.md5((str(title) + repr(points)).encode("utf-8")).hexdigest()[:10]
    out = FX / f"_matome_{MATOME_VER}_{sig}.png"
    if out.exists(): return out
    W2,H2=1920,1080; SLATE=(26,40,43); WOOD=(96,66,44); WOOD_HI=(142,106,72); WOOD_SH=(64,42,26); ACCENT=(210,182,126)
    GOLD=(255,224,130); CHALK=(236,240,246); SUBCHALK=(190,202,212); GREEN=(150,230,180)
    base=Image.new("RGBA",(W2,H2),WOOD+(255,)); d=ImageDraw.Draw(base)
    d.rounded_rectangle([5,5,W2-5,H2-5],radius=10,outline=WOOD_HI+(255,),width=3)
    frm=26; d.rounded_rectangle([frm-5,frm-5,W2-frm+5,H2-frm+5],radius=20,outline=WOOD_SH+(255,),width=4)
    d.rounded_rectangle([frm,frm,W2-frm,H2-frm],radius=18,fill=SLATE+(255,),outline=ACCENT+(170,),width=2)
    # タイトル（黒板に直接＝チョークゴールド＋下線）
    ft=_ttf(72); tt=str(title)[:22]; tw=d.textlength(tt,font=ft); tx=(W2-tw)/2; ty=96
    d.text((tx,ty),tt,font=ft,fill=GOLD+(255,))
    d.line([(tx,ty+88),(tx+tw,ty+88)],fill=ACCENT+(220,),width=5)
    # 要点（チョークのチェック＋head＋sub）を黒板に直接
    pts=(points or [])[:5]; n=max(1,len(pts)); y0=270; lh=min(160,(H2-120-y0)//n)
    fh=_ttf(52); fs=_ttf(32)
    for k,p in enumerate(pts):
        head=p.get("head","") if isinstance(p,dict) else str(p); sub=p.get("sub","") if isinstance(p,dict) else ""
        y=y0+k*lh; cx=250; cy=y+34
        d.ellipse([cx-32,cy-32,cx+32,cy+32],outline=GREEN+(255,),width=5)                       # チョークのチェック丸
        d.line([(cx-15,cy),(cx-3,cy+17)],fill=GREEN+(255,),width=8); d.line([(cx-3,cy+17),(cx+19,cy-15)],fill=GREEN+(255,),width=8)
        d.text((cx+58,y),str(head)[:24],font=fh,fill=CHALK+(255,))
        if sub: d.text((cx+60,y+66),str(sub)[:34],font=fs,fill=SUBCHALK+(255,))
    base.save(out); return out

def _mtime_sig(*paths):
    """元画像の更新時刻を連結。キャッシュキーに含めると元画像を差し替えた時に自動で再生成される
    （2026-08-13：次回予告が旧画像のキャッシュを掴み続けた不具合の根治）。"""
    parts = []
    for p in paths:
        try:
            parts.append(str(int(os.path.getmtime(str(p)))))
        except Exception:
            parts.append("0")
    return "-".join(parts)


def _compose_duo(spec):
    """2枚並びカード（例：原発＋安定ヨウ素剤）＝ミニ黒板に左右2画像＋？矢印＋チョークラベル＋出典。"""
    import hashlib
    FX.mkdir(exist_ok=True)
    _srcs = _mtime_sig(Path(DB) / spec.get("left", ""), Path(DB) / spec.get("right", ""))
    sig = hashlib.md5((repr(sorted(spec.items())) + "|" + _srcs).encode("utf-8")).hexdigest()[:10]
    out = FX / f"_duo_{sig}.png"
    if out.exists(): return out
    W2,H2=1920,1080
    SLATE=(26,40,43); WOOD=(96,66,44); WOOD_HI=(142,106,72); WOOD_SH=(64,42,26)
    ACCENT=(210,182,126); CHALK=(236,241,238); CHALK_DIM=(150,168,168); GOLD=(226,194,116)
    base=Image.new("RGBA",(W2,H2),WOOD+(255,)); d=ImageDraw.Draw(base)
    d.rounded_rectangle([5,5,W2-5,H2-5],radius=10,outline=WOOD_HI+(255,),width=3)
    frm=26
    d.rounded_rectangle([frm-5,frm-5,W2-frm+5,H2-frm+5],radius=20,outline=WOOD_SH+(255,),width=4)
    d.rounded_rectangle([frm,frm,W2-frm,H2-frm],radius=18,fill=SLATE+(255,),outline=ACCENT+(170,),width=2)
    ttl=spec.get("title",""); sub=spec.get("subtitle","")
    if ttl: d.text((92,66),ttl,font=_ttf(64),fill=CHALK+(255,))
    if sub: d.text((96,152),sub,font=_ttf(34),fill=CHALK_DIM+(255,))
    if ttl or sub: d.line([(94,196),(W2-94,196)],fill=CHALK+(120,),width=2)
    def _fit(im,bw,bh):
        r=min(bw/im.size[0],bh/im.size[1]); return im.resize((int(im.size[0]*r),int(im.size[1]*r)))
    lp=Path(DB)/spec.get("left",""); rp=Path(DB)/spec.get("right","")
    if not (lp.exists() and rp.exists()):
        print(f"[warn] _compose_duo: 画像が無い {lp} / {rp}"); return None
    lim=_fit(Image.open(lp).convert("RGBA"),540,470); lcx,lcy=430,560
    base.alpha_composite(lim,(lcx-lim.size[0]//2,lcy-lim.size[1]//2)); d=ImageDraw.Draw(base)
    ll=spec.get("left_label","")
    if ll:
        _lw=d.textlength(ll,font=_ttf(44)); d.text((lcx-_lw//2,lcy+lim.size[1]//2+8),ll,font=_ttf(44),fill=CHALK+(255,))
    d.line([(720,540),(880,540)],fill=CHALK+(210,),width=4); d.polygon([(880,540),(858,528),(858,552)],fill=CHALK+(230,))
    d.text((762,468),"？",font=_ttf(72),fill=GOLD+(255,))
    ril=_fit(Image.open(rp).convert("RGBA"),600,500); pd=26; label_h=58
    fw=ril.size[0]+2*pd; fh=ril.size[1]+2*pd+label_h; fx0,fy0=1360-fw//2,560-fh//2
    d.rounded_rectangle([fx0,fy0,fx0+fw,fy0+fh],radius=16,outline=CHALK+(230,),width=3)
    rl=spec.get("right_label","")
    if rl:
        d.text((fx0+20,fy0+10),rl,font=_ttf(46),fill=CHALK+(255,))
        _rw=d.textlength(rl,font=_ttf(46)); d.line([(fx0+20,fy0+62),(fx0+20+_rw,fy0+62)],fill=CHALK+(190,),width=3)
    base.alpha_composite(ril,(fx0+pd,fy0+label_h+pd)); d=ImageDraw.Draw(base)
    cr=spec.get("credit","")
    if cr:
        _cw=d.textlength(cr,font=_ttf(22)); d.text((W2-_cw-70,H2-72),cr,font=_ttf(22),fill=CHALK_DIM+(255,))
    base.save(out); return out

def _compose_next_thumb(spec):
    """次回予告カード専用サムネ＝説明用の?図ではなく被写体を大きく見せるティザー。
    右に主役(甲状腺)を大きく／左に放射性ヨウ素モチーフを中サイズ／間に光るチョーク矢印。
    左上(▶次回予告タグ域)と下部(キャプション域)は空けておく（make_ed_card側で載せる）。"""
    import hashlib
    FX.mkdir(exist_ok=True)
    _srcs = _mtime_sig(Path(DB) / spec.get("left", ""), Path(DB) / spec.get("right", ""))
    sig = hashlib.md5(("nextthumb1|" + repr(sorted(spec.items())) + "|" + _srcs).encode("utf-8")).hexdigest()[:10]
    out = FX / f"_nextthumb_{sig}.png"
    if out.exists(): return out
    Wt, Ht = 1520, 940
    base = Image.open(make_board()).convert("RGBA").resize((Wt, Ht))
    d = ImageDraw.Draw(base)
    lp = Path(DB) / spec.get("left", ""); rp = Path(DB) / spec.get("right", "")
    def _fit_h(im, h):
        r = h / im.size[1]; return im.resize((max(1, int(im.size[0]*r)), max(1, int(im.size[1]*r)))), (int(im.size[0]*r), int(im.size[1]*r))
    cy = int(Ht*0.55)                                            # 主役の縦中心（下寄せ＝上のタグ域を空ける）
    # 右：主役(甲状腺)を大きく
    if rp.exists():
        rim, (rw, rh) = _fit_h(Image.open(rp).convert("RGBA"), 700)
        base.alpha_composite(rim, (Wt - rw - 120, cy - rh//2))
    # 左：放射性ヨウ素モチーフ 中サイズ
    lcx = 360
    if lp.exists():
        lim, (lw, lh) = _fit_h(Image.open(lp).convert("RGBA"), 420)
        base.alpha_composite(lim, (lcx - lw//2, cy - lh//2))
    # チョーク矢印（左→右＝取り込まれる）
    ax0, ax1 = lcx + 250, lcx + 470
    d.line([(ax0, cy), (ax1, cy)], fill=(236, 241, 238, 240), width=9)
    d.polygon([(ax1, cy), (ax1-28, cy-19), (ax1-28, cy+19)], fill=(236, 241, 238, 240))
    base.convert("RGB").save(out); return out

def _compose_single(spec):
    """1枚のイラスト(いらすとや等フリー素材)をミニ黒板に中央配置＋チョーク見出し。比喩/供給源など単体絵向け。
    spec: title/subtitle/image(DB相対)/credit。"""
    import hashlib
    FX.mkdir(exist_ok=True)
    sig = hashlib.md5(repr(sorted(spec.items())).encode("utf-8")).hexdigest()[:10]
    out = FX / f"_single_{sig}.png"
    if out.exists(): return out
    W2,H2=1920,1080; SLATE=(26,40,43); WOOD=(96,66,44); WOOD_HI=(142,106,72); WOOD_SH=(64,42,26); ACCENT=(210,182,126)
    CHALK=(236,240,246); CHALK_DIM=(190,202,212)
    base=Image.new("RGBA",(W2,H2),WOOD+(255,)); d=ImageDraw.Draw(base)
    d.rounded_rectangle([5,5,W2-5,H2-5],radius=10,outline=WOOD_HI+(255,),width=3)
    frm=26; d.rounded_rectangle([frm-5,frm-5,W2-frm+5,H2-frm+5],radius=20,outline=WOOD_SH+(255,),width=4)
    d.rounded_rectangle([frm,frm,W2-frm,H2-frm],radius=18,fill=SLATE+(255,),outline=ACCENT+(170,),width=2)
    ttl=spec.get("title",""); sub=spec.get("subtitle","")
    if ttl: d.text((92,66),ttl,font=_ttf(64),fill=CHALK+(255,))
    if sub: d.text((96,152),sub,font=_ttf(34),fill=CHALK_DIM+(255,))
    if ttl or sub: d.line([(94,200),(W2-94,200)],fill=CHALK+(120,),width=2)
    ip=Path(DB)/spec.get("image","")
    if ip.exists():
        img=Image.open(ip).convert("RGBA")
        _top=230 if (ttl or sub) else 60
        aw,ah=1040,(H2-_top-70)
        r=min(aw/img.width, ah/img.height); img=img.resize((max(1,int(img.width*r)),max(1,int(img.height*r))))
        ix=(W2-img.width)//2; iy=_top+(ah-img.height)//2
        base.alpha_composite(img,(ix,iy)); d=ImageDraw.Draw(base)
    else:
        print(f"[warn] _compose_single: image無い {ip}")
    cr=spec.get("credit","")
    if cr:
        cf=_ttf(24); cw=d.textlength(cr,font=cf); d.text((W2-cw-70,H2-72),cr,font=cf,fill=CHALK_DIM+(255,))
    base.save(out); return out

def _compose_gallery(spec):
    """複数イラストを横並びでミニ黒板に配置＋各チョークラベル＋見出し。「〜が含まれるもの」等の列挙向け（1枚だと寂しい時）。
    spec: title/subtitle/items:[{image,label}]/credit。"""
    import hashlib, json
    FX.mkdir(exist_ok=True)
    sig = hashlib.md5(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
    out = FX / f"_gallery_{sig}.png"
    if out.exists(): return out
    W2,H2=1920,1080; SLATE=(26,40,43); WOOD=(96,66,44); WOOD_HI=(142,106,72); WOOD_SH=(64,42,26); ACCENT=(210,182,126)
    CHALK=(236,240,246); CHALK_DIM=(190,202,212)
    base=Image.new("RGBA",(W2,H2),WOOD+(255,)); d=ImageDraw.Draw(base)
    d.rounded_rectangle([5,5,W2-5,H2-5],radius=10,outline=WOOD_HI+(255,),width=3)
    frm=26; d.rounded_rectangle([frm-5,frm-5,W2-frm+5,H2-frm+5],radius=20,outline=WOOD_SH+(255,),width=4)
    d.rounded_rectangle([frm,frm,W2-frm,H2-frm],radius=18,fill=SLATE+(255,),outline=ACCENT+(170,),width=2)
    ttl=spec.get("title",""); sub=spec.get("subtitle","")
    if ttl: d.text((92,66),ttl,font=_ttf(64),fill=CHALK+(255,))
    if sub: d.text((96,152),sub,font=_ttf(34),fill=CHALK_DIM+(255,))
    if ttl or sub: d.line([(94,200),(W2-94,200)],fill=CHALK+(120,),width=2)
    items=spec.get("items",[]); n=max(1,len(items))
    top=236 if (ttl or sub) else 70
    area_x0=90; area_w=W2-180; cell_w=area_w//n
    lf=_ttf(42)
    img_max_w=int(cell_w*0.80); img_max_h=int(H2-top-190)
    cyc=top+(H2-top-120)//2
    for k,it in enumerate(items):
        cx=area_x0+cell_w*k+cell_w//2
        ip=Path(DB)/it.get("image","")
        _bottom=cyc
        if ip.exists():
            img=Image.open(ip).convert("RGBA")
            r=min(img_max_w/img.width, img_max_h/img.height); img=img.resize((max(1,int(img.width*r)),max(1,int(img.height*r))))
            ix=cx-img.width//2; iy=cyc-img.height//2-20
            base.alpha_composite(img,(ix,iy)); d=ImageDraw.Draw(base); _bottom=iy+img.height
        else:
            print(f"[warn] _compose_gallery: image無い {ip}")
        lab=it.get("label","")
        if lab:
            lw=d.textlength(lab,font=lf); d.text((cx-lw/2,_bottom+16),lab,font=lf,fill=CHALK+(255,))
    cr=spec.get("credit","")
    if cr:
        cf=_ttf(24); cw=d.textlength(cr,font=cf); d.text((W2-cw-70,H2-72),cr,font=cf,fill=CHALK_DIM+(255,))
    base.save(out); return out

def compose_figure(spec):
    """部品合成：模式図(main)＋実構造インセット(inset)の"2段構え"カードを生成→パス返す。素材DBから読む。
    タンパク質等は『初学者=模式図(分かる)＋深掘り=実構造(PDB/AlphaFold・正確)』で、AIの偽構造を使わず正確さを担保。
    layout=="locator" なら _compose_locator へ委譲（全身＋位置円＋実物臓器のミニ黒板）。"""
    import hashlib
    if spec.get("layout") == "locator":
        return _compose_locator(spec)
    if spec.get("layout") == "duo":
        return _compose_duo(spec)
    if spec.get("layout") == "single":
        return _compose_single(spec)
    if spec.get("layout") == "gallery":
        return _compose_gallery(spec)
    FX.mkdir(exist_ok=True)
    main_p = Path(DB) / spec.get("main", "")
    if not main_p.exists():
        print(f"[warn] compose_figure: main画像が無い {main_p}"); return None
    sig = hashlib.md5(repr(sorted(spec.items())).encode("utf-8")).hexdigest()[:10]
    out = FX / f"_compose_{sig}.png"
    if out.exists(): return out
    base = Image.open(main_p).convert("RGBA"); W0, H0 = base.size
    inset = None if spec.get("inset_supplement") else spec.get("inset")   # 補足へ回す設定なら本編カードには焼き込まない（オプションA）
    if inset:
        ip = Path(DB) / inset
        if ip.exists():
            ins = Image.open(ip).convert("RGBA"); ins.thumbnail((int(W0*0.26), int(W0*0.26)))
            bx = W0 - ins.size[0] - int(W0*0.02); by = int(H0*0.03)
            d = ImageDraw.Draw(base)
            cap = spec.get("inset_cap", "実際の構造")
            fs = max(15, int(W0*0.017))                      # インセット幅に収まるようフォント自動縮小
            while fs > 12 and d.textlength(cap, font=_ttf(fs)) > ins.size[0]-6: fs -= 1
            cf = _ttf(fs); ch = fs + 16
            d.rounded_rectangle([bx-12, by-12, bx+ins.size[0]+12, by+ins.size[1]+ch],
                                radius=14, fill=(255, 255, 255, 236), outline=(120, 140, 160, 255), width=3)
            base.alpha_composite(ins, (bx, by))
            d = ImageDraw.Draw(base); tw = d.textlength(cap, font=cf)
            d.text((bx+ins.size[0]/2-tw/2, by+ins.size[1]+5), cap, font=cf, fill=(40, 60, 90, 255))
        else:
            print(f"[warn] compose_figure: inset実構造が無い {ip}")
    # 部位ラベル（リード線＋角丸・座標はmain画像の割合）＋ゾーン表記。イオンの電荷は上付きで作画（□化け回避）。
    W0f, H0f = base.size
    dd = ImageDraw.Draw(base)
    def _label_width(f, text, ion, charge):
        w = dd.textlength(text, font=f)
        if ion:
            sf = _ttf(int(f.size*0.62))
            w += dd.textlength("（"+ion, font=f) + dd.textlength(charge or "", font=sf) + dd.textlength("）", font=f)
        return w
    for lb in spec.get("labels", []):
        f = _ttf(max(28, int(W0f*0.032)))              # スマホ視認性UP（0.026→0.032・かぶり回避で0.036から微減）
        acc = _PIN_ACCENT.get(lb.get("color", "gold"), (255, 220, 90))
        tx, ty = int(lb["tx"]*W0f), int(lb["ty"]*H0f)
        lx, ly = int(lb["lx"]*W0f), int(lb["ly"]*H0f)
        tw = _label_width(f, lb["text"], lb.get("ion"), lb.get("charge"))
        pad = 16; bh = f.size + 20; box_w = tw + pad*2
        x0 = lx - box_w/2; y0 = ly - bh/2
        x0 = max(24, min(x0, W0f - 24 - box_w))        # ★図の内側にクランプ（見切れ防止＋木枠に寄りすぎない余白24）
        y0 = max(16, min(y0, H0f - 16 - bh))
        lxc = x0 + box_w/2                             # クランプ後の枠中心＝リード線の起点
        ay = y0 + bh if ty > ly else y0
        dd.line([(lxc, ay), (tx, ty)], fill=acc+(255,), width=4)
        dd.ellipse([tx-9, ty-9, tx+9, ty+9], outline=acc+(255,), width=4, fill=(0, 0, 0, 90))
        dd.rounded_rectangle([x0, y0, x0+box_w, y0+bh], radius=13, fill=(6, 14, 20, 228), outline=acc+(255,), width=3)
        cx = x0 + pad; cy = y0 + (bh - f.size)//2 - 2
        dd.text((cx, cy), lb["text"], font=f, fill=(255, 255, 255, 255)); cx += dd.textlength(lb["text"], font=f)
        if lb.get("ion"):
            dd.text((cx, cy), "（"+lb["ion"], font=f, fill=(255, 255, 255, 255)); cx += dd.textlength("（"+lb["ion"], font=f)
            sf = _ttf(int(f.size*0.62)); dd.text((cx, cy-3), lb.get("charge", ""), font=sf, fill=(255, 255, 255, 255)); cx += dd.textlength(lb.get("charge", ""), font=sf)
            dd.text((cx, cy), "）", font=f, fill=(255, 255, 255, 255))
    for z in spec.get("zones", []):
        zf = _ttf(max(26, int(W0f*0.030)))             # スマホ視認性UP（0.024→0.030・かぶり回避で微減）
        zx, zy = int(z["x"]*W0f), int(z["y"]*H0f)
        tw = dd.textlength(z["text"], font=zf); th = zf.size
        zx = max(18, min(zx, W0f - 18 - tw))           # ★図の内側にクランプ（見切れ防止）
        zy = max(10, min(zy, H0f - 14 - th))
        # 明るい下地の帯＋濃紺文字で視認性UP（薄い青背景に埋もれない）
        dd.rounded_rectangle([zx-12, zy-7, zx+tw+12, zy+th+11], radius=11, fill=(255, 255, 255, 214))
        dd.text((zx, zy), z["text"], font=zf, fill=(22, 46, 78, 255))
    _notes = spec.get("note", [])                          # ※やさしい注釈（専門語を初学者向けに）＝右下の隅に小さく
    if _notes:
        nf = _ttf(max(19, int(W0f*0.0205))); _pad = 16; _lh = nf.size + 8
        _nw = max(dd.textlength(t, font=nf) for t in _notes)
        _nx0 = int(W0f - _nw - 2*_pad - 14); _ny0 = int(H0f - len(_notes)*_lh - 2*_pad - 12)
        dd.rounded_rectangle([_nx0, _ny0, W0f-14, H0f-12], radius=12, fill=(8,16,22,225), outline=(120,140,160,200), width=2)
        for _i, _t in enumerate(_notes):
            dd.text((_nx0+_pad, _ny0+_pad+_i*_lh), _t, font=nf, fill=(224,228,234,255))
    base.save(out); return out

def _draw_bell(d, cx, cy, s, fill=(255, 255, 255, 255)):
    d.pieslice([cx-s, cy-s*1.15, cx+s, cy+s*0.85], 180, 360, fill=fill)
    d.rectangle([cx-s, cy-s*0.2, cx+s, cy+s*0.55], fill=fill)
    d.ellipse([cx-s*0.3, cy+s*0.55, cx+s*0.3, cy+s*1.15], fill=fill)
    d.ellipse([cx-s*0.22, cy-s*1.5, cx+s*0.22, cy-s*1.05], fill=fill)   # 取っ手
def _draw_thumb(d, cx, cy, s, fill=(255, 255, 255, 255)):
    d.rounded_rectangle([cx-s*1.1, cy-s*0.1, cx-s*0.4, cy+s], radius=int(s*0.15), fill=fill)  # 手首
    d.rounded_rectangle([cx-s*0.35, cy-s*1.2, cx+s*1.1, cy+s], radius=int(s*0.35), fill=fill)  # 拳
    d.rectangle([cx-s*0.35, cy-s*0.55, cx+s*0.2, cy+s*0.3], fill=fill)
    d.rounded_rectangle([cx-s*0.1, cy-s*1.7, cx+s*0.5, cy-s*0.2], radius=int(s*0.28), fill=fill)  # 親指

def make_ed_card(next_img=None, next_no="", next_sub="", tagline="", channel_name=""):
    """ED末尾のエンドカード（コードUI＝登録ボタン等はUI要素なのでコード描画が適切）。フレーム全体を使い次回予告＋登録CTAを配置。"""
    import hashlib
    FX.mkdir(exist_ok=True)
    sig = hashlib.md5(f"{next_img}|{_mtime_sig(next_img)}|{next_no}|{next_sub}|{tagline}|{channel_name}|edv2board".encode("utf-8")).hexdigest()[:8]
    out = FX / f"_edcard_{sig}.png"
    if out.exists(): return out
    im = Image.open(make_board()).convert("RGBA")   # ★背景をOPと同じ黒板(make_board=深緑黒板)に統一
    d = ImageDraw.Draw(im)
    def ctext(cx, y, t, f, fill, stroke=0):
        w = d.textlength(t, font=f); d.text((cx-w/2, y), t, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
    # 上：チャンネル識別（名は任意）
    yb = 54
    if channel_name:
        ctext(W/2, 54, channel_name, _ttf(40), (255, 236, 150, 255)); yb = 108
    if tagline:
        ctext(W/2, yb, tagline, _ttf(28), (200, 214, 208, 255))
    # 左：次回予告カード
    LX, LY, LW, LH = 150, 250, 760, 470
    d.rounded_rectangle([LX-6, LY-6, LX+LW+6, LY+LH+6], 26, fill=(6, 14, 10, 235), outline=(90, 200, 255, 255), width=4)
    if next_img and Path(next_img).exists():
        th = Image.open(next_img).convert("RGBA"); tw0, th0 = th.size
        sc = max(LW/tw0, LH/th0); th = th.resize((int(tw0*sc), int(th0*sc)))
        mask = Image.new("L", (LW, LH), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, LW-1, LH-1], radius=20, fill=255)
        reg = Image.new("RGBA", (LW, LH), (0, 0, 0, 0)); reg.alpha_composite(th, ((LW-th.size[0])//2, (LH-th.size[1])//2))
        im.paste(reg, (LX, LY), mask); d = ImageDraw.Draw(im)
    d.rounded_rectangle([LX, LY+LH-118, LX+LW, LY+LH], radius=20, fill=(4, 10, 8, 205))
    d.text((LX+30, LY+24), f"▶ {next_no}", font=_ttf(46), fill=(255, 255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    if next_sub:
        _ss = 44                                                # 見切れ防止＝カード幅に収まる最大フォントで全文表示（[:16]切りを廃止）
        while _ss > 22 and d.textlength(next_sub, font=_ttf(_ss)) > LW - 28: _ss -= 2
        ctext(LX+LW/2, LY+LH-84, next_sub, _ttf(_ss), (255, 236, 150, 255), stroke=4)
    # 右：登録CTA
    RX, RY, RW, RH = 1010, 250, 760, 470
    d.rounded_rectangle([RX, RY, RX+RW, RY+RH], 26, fill=(6, 14, 10, 235), outline=(240, 180, 70, 255), width=4)
    bx0, by0, bw, bh = RX+70, RY+66, RW-140, 122
    d.rounded_rectangle([bx0, by0+7, bx0+bw, by0+bh+7], 61, fill=(120, 20, 24, 255))
    d.rounded_rectangle([bx0, by0, bx0+bw, by0+bh], 61, fill=(230, 54, 60, 255))
    _draw_bell(d, bx0+72, by0+bh/2, 26)
    ctext(bx0+bw/2+34, by0+30, "チャンネル登録", _ttf(54), (255, 255, 255, 255))
    # 高評価・通知（ベクターアイコン＋テキスト）
    iy = RY+250; _draw_thumb(d, RX+120, iy, 24); _draw_bell(d, RX+RW-360, iy+4, 24)
    d.text((RX+165, iy-24), "高評価", font=_ttf(38), fill=(255, 255, 255, 255))
    d.text((RX+RW-315, iy-24), "通知ON もぜひ！", font=_ttf(38), fill=(255, 255, 255, 255))
    ctext(RX+RW/2, RY+330, "コメントで質問も待ってます", _ttf(28), (200, 214, 208, 255))
    # 下：御礼
    ctext(W/2, H-108, "ご視聴ありがとうございました！", _ttf(48), (255, 236, 150, 255), stroke=3)
    im.convert("RGB").save(out); return out

def make_tap_arrow():
    """ED登録ボタン強調用の下向き矢印（黄＋黒縁）。境目のない単一シルエット（茎＋頭を一体で描く）。"""
    FX.mkdir(exist_ok=True); out = FX / "_ed_taparrow_v2.png"
    if out.exists(): return out
    S = 220; im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    pts = [(S*0.42, S*0.06), (S*0.58, S*0.06), (S*0.58, S*0.46), (S*0.76, S*0.46),
           (S*0.50, S*0.93), (S*0.24, S*0.46), (S*0.42, S*0.46)]              # 茎＋頭を1つの多角形に（内部の境目なし）
    d.polygon(pts, fill=(255, 210, 60, 255))
    d.line(pts + [pts[0]], fill=(20, 20, 20, 255), width=5, joint="curve")    # 外周だけに連続した黒縁
    im.save(out); return out

def make_cut_from_card(src, key, cx_frac=0.5, cy_frac=0.5, zoomf=2.0):
    """小出しイラスト＝既存カード画像の一部を正方形で切り出し（丸角＋黄発光縁）。0円・画風統一（ユーザー方針：クレジット節約）。"""
    FX.mkdir(exist_ok=True)
    out = FX / f"_cut_{key}.png"
    if out.exists(): return out
    im = Image.open(src).convert("RGBA"); w, h = im.size
    side = max(40, int(h / zoomf))
    cxp = int(cx_frac * w); cyp = int(cy_frac * h)
    x0 = max(0, min(w - side, cxp - side // 2)); y0 = max(0, min(h - side, cyp - side // 2))
    crop = im.crop((x0, y0, x0 + side, y0 + side))
    S = 320; crop = crop.resize((S, S))
    mask = Image.new("L", (S, S), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, S-1, S-1], radius=44, fill=255)
    o = Image.new("RGBA", (S, S), (0, 0, 0, 0)); o.paste(crop, (0, 0), mask)
    # 発光縁＋外側の軽いシャドウ
    B = 24; big = Image.new("RGBA", (S + 2*B, S + 2*B), (0, 0, 0, 0))
    sh = Image.new("RGBA", big.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle([B, B, B+S-1, B+S-1], radius=44, fill=(0, 0, 0, 150))
    big = Image.alpha_composite(big, sh.filter(ImageFilter.GaussianBlur(10)))
    big.alpha_composite(o, (B, B))
    ImageDraw.Draw(big).rounded_rectangle([B+2, B+2, B+S-3, B+S-3], radius=42, outline=(255, 224, 120, 235), width=6)
    big.save(out); return out

def make_slide_card(src):
    """図解カードを『ミニ黒板の木枠』で統一して囲む。_locator_*は自前で木枠済み＝二重にせず影のみ（白フチ廃止）。
    他カードは木枠＋明るめスレートのマットで囲み、全カードの枠を揃える。"""
    FX.mkdir(exist_ok=True)
    out = FX / f"slide_{Path(src).stem}.png"
    if out.exists(): return out
    im = Image.open(src).convert("RGBA"); w, h = im.size
    is_loc = any(k in Path(src).stem for k in ("_locator_","_duo_","_matome_","_single_","_gallery_"))   # 自前で木枠済みのカードは二重にしない
    if is_loc:
        framed = im                                              # 自前で木枠済み＝そのまま（白フチを付けない）
    else:
        WOOD=(96,66,44); WOOD_HI=(142,106,72); ACC=(210,182,126); SLATE=(26,40,43)
        b = max(20, w // 72)                                     # 木枠幅
        framed = Image.new("RGBA", (w + 2*b, h + 2*b), (0,0,0,0)); fd = ImageDraw.Draw(framed)
        fd.rounded_rectangle([0,0,w+2*b-1,h+2*b-1], radius=22, fill=WOOD+(255,), outline=WOOD_HI+(255,), width=3)
        fd.rounded_rectangle([b-6,b-6,b+w+6,b+h+6], radius=13, fill=SLATE+(255,), outline=ACC+(150,), width=2)  # 明るめスレートのマット＋シャンパン見切り
        framed.paste(im, (b, b), im)
    pad = max(10, framed.width // 120)
    canvas = Image.new("RGBA", (framed.width + 2*pad, framed.height + 2*pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    _s = Image.new("RGBA", framed.size, (0,0,0,0)); ImageDraw.Draw(_s).rounded_rectangle([0,0,framed.width-1,framed.height-1], radius=22, fill=(0,0,0,150))
    sh.alpha_composite(_s, (pad + 6, pad + 8)); sh = sh.filter(ImageFilter.GaussianBlur(11))
    canvas = Image.alpha_composite(canvas, sh)
    canvas.alpha_composite(framed, (pad, pad))
    canvas.save(out); return out

def _subtract_ranges(a0, a1, ranges):
    """[a0,a1) から ranges の各区間を除いた残りの部分区間リストを返す（図解区間で見出しを抜くため）。"""
    segs = [(a0, a1)]
    for (r0, r1) in ranges:
        nxt = []
        for (s, e) in segs:
            if r1 <= s or r0 >= e:
                nxt.append((s, e)); continue
            if r0 > s: nxt.append((s, min(r0, e)))
            if r1 < e: nxt.append((max(r1, s), e))
        segs = [(s, e) for (s, e) in nxt if e - s > 0]
    return segs

def make_glow_chibi(src):
    """話者立ち絵にキャラカラー発光を焼き込む（余白paddingあり・zoomは元寸基準で変えない）。"""
    FX.mkdir(exist_ok=True)
    spk = Path(src).parent.name
    out = FX / f"glow_{spk}_{Path(src).stem}.png"
    if out.exists(): return out
    rgb = GLOW_RGB.get(spk, (255, 255, 255))
    im = Image.open(src).convert("RGBA"); w, h = im.size
    p = max(28, h // 10)
    canvas = Image.new("RGBA", (w + 2*p, h + 2*p), (0, 0, 0, 0))
    sil = Image.new("RGBA", (w, h), rgb + (255,)); sil.putalpha(im.split()[3])
    gl = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); gl.paste(sil, (p, p))
    gl = gl.filter(ImageFilter.GaussianBlur(p * 0.55))
    canvas = Image.alpha_composite(canvas, gl); canvas = Image.alpha_composite(canvas, gl)
    canvas.alpha_composite(im, (p, p))
    canvas.save(out); return out

def make_nameplate(spk, label):
    """立ち絵足元のネームプレート（角丸・キャラ色）。"""
    FX.mkdir(exist_ok=True)
    out = FX / f"plate_{spk}.png"
    if out.exists(): return out
    from PIL import ImageFont
    def fnt(s):
        for ff in [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc"]:
            try: return ImageFont.truetype(ff, s)
            except Exception: pass
        return ImageFont.load_default()
    f = fnt(24)
    tw = int(ImageDraw.Draw(Image.new("RGBA", (8, 8))).textlength(label, font=f))
    W2, H2 = tw + 48, 52
    im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([2, 2, W2-3, H2-3], radius=16, fill=PLATE_BG.get(spk, (90, 90, 110)) + (235,),
                        outline=(255, 255, 255, 225), width=3)
    d.text(((W2 - tw)//2, 11), label, font=f, fill=(255, 255, 255, 255))
    im.save(out); return out

def make_konsen():
    """驚き用の集中線オーバーレイ。"""
    FX.mkdir(exist_ok=True); out = FX / "_konsen.png"
    if out.exists(): return out
    S = 1000; im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im); c = S/2; n = 96
    for k in range(n):
        a = k * (2*math.pi/n); r0, r1 = S*0.30, S*0.72; wdt = 9 if k % 2 == 0 else 4
        d.line([c+r0*math.cos(a), c+r0*math.sin(a), c+r1*math.cos(a), c+r1*math.sin(a)],
               fill=(255, 255, 255, 205), width=wdt)
    im.filter(ImageFilter.GaussianBlur(1.0)).save(out); return out

def make_sparkle():
    """喜び用のキラキラ粒子オーバーレイ。"""
    FX.mkdir(exist_ok=True); out = FX / "_sparkle.png"
    if out.exists(): return out
    S = 720; im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    pts = [(0.16, 0.18, 30), (0.82, 0.16, 38), (0.5, 0.07, 22), (0.09, 0.55, 24), (0.9, 0.5, 30),
           (0.28, 0.86, 26), (0.72, 0.82, 22), (0.42, 0.45, 16), (0.62, 0.3, 18), (0.2, 0.35, 14)]
    for fx, fy, s in pts:
        x, y = fx*S, fy*S
        d.polygon([(x, y-s), (x+s*0.2, y-s*0.2), (x+s, y), (x+s*0.2, y+s*0.2),
                   (x, y+s), (x-s*0.2, y+s*0.2), (x-s, y), (x-s*0.2, y-s*0.2)], fill=(255, 250, 190, 235))
        d.ellipse([x-3, y-3, x+3, y+3], fill=(255, 255, 255, 255))
    im.save(out); return out

def make_title_panel():
    """左上タイトル背後の暗パネル（汎用背景の装飾と被っても読めるように）。"""
    FX.mkdir(exist_ok=True); out = FX / "_titlepanel.png"
    if out.exists(): return out
    W2, H2 = 800, 210
    im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, W2-1, H2-1], radius=30, fill=(12, 30, 24, 155))
    im.filter(ImageFilter.GaussianBlur(7)).save(out); return out

def _ttf(size):
    from PIL import ImageFont
    for ff in [r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc"]:
        try: return ImageFont.truetype(ff, size)
        except Exception: pass
    return ImageFont.load_default()

def make_bikkuri():
    """驚き用の『!?』マーク（白フチ赤・太陽/放射バーストなし）。集中線の代替。"""
    FX.mkdir(exist_ok=True); out = FX / "_bikkuri.png"
    if out.exists(): return out
    S = 460; im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    f = _ttf(int(S*0.62)); txt = "!?"; tw = d.textlength(txt, font=f)
    d.text((S/2 - tw/2, S*0.10), txt, font=f, fill=(230, 48, 44, 255),
           stroke_width=12, stroke_fill=(255, 255, 255, 255))   # 白フチ付きの赤「!?」
    im.save(out); return out

def make_chalkdust():
    """黒板消しワイプ用：チョーク粉が舞う半透明オーバーレイ（トピック切替で一瞬表示）。"""
    FX.mkdir(exist_ok=True); out = FX / "_chalkdust.png"
    if out.exists(): return out
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i in range(180):   # 決定論的な粉（randomは使わない＝再現性）
        x = (i*137) % W; y = int(H*0.12) + (i*53) % int(H*0.76); r = 2 + (i % 5)
        al = 70 + (i*11) % 110
        d.ellipse([x-r, y-r, x+r, y+r], fill=(240, 240, 234, al))
    im.filter(ImageFilter.GaussianBlur(1.4)).save(out); return out

def _chap_chip(section):
    """章sectionから『一言ラベル』を機械抽出（chapter_chip未提供時のフォールバック）。
    優先：英字略語(NIS/TPO/Wolff-Chaikoff/ARB等) → 「」『』（）内の核語 → まとめ → 本文先頭句[:10]。"""
    s = re.sub(r"^第\d+章\s*[:：]\s*", "", section or "").strip()
    quoted = re.findall(r"[「『（(]([^」』）)]+)[」』）)]", s)
    for src in quoted + [s]:                                   # 英字略語を最優先
        m = re.search(r"[A-Za-z][A-Za-z0-9\-]{1,}", src)
        if m: return m.group(0)
    core = re.sub(r"[（(].*?[）)]", "", s).strip()
    if core.startswith("まとめ"): return "まとめ"
    if quoted and len(quoted[0]) <= 12: return quoted[0]       # 「命の貯金プログラム」等の核語
    return re.split(r"[、。！？…]", core)[0][:10]

def make_chapterbar(labels, cur):
    """最上部のチャプター進行バー（現在章を金でハイライト）。話数＋章名＋curでキャッシュ。
    ※共通_fxを全話で共有するため、キーに話数と章名ハッシュを含めないと他話の帯を誤再利用する（第2話流用バグの再発防止）。"""
    FX.mkdir(exist_ok=True)
    _key = hashlib.md5(("|".join(labels)).encode("utf-8")).hexdigest()[:8]
    out = FX / f"_chapbar_ep{EP}_{cur}_{_key}.png"
    if out.exists(): return out
    BW, BH = W, 54; im = Image.new("RGBA", (BW, BH), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    PAD = 60
    d.rounded_rectangle([PAD, 6, BW-PAD, BH-6], radius=18, fill=(10, 28, 22, 185))
    n = max(1, len(labels)); inner = BW - 2*PAD - 40; SEP = "  ›  "
    texts = [f"{i+1}.{lab}" for i, lab in enumerate(labels)]
    # 均等分割をやめ、全章を実測幅で詰める。全文が収まる最大フォントを自動選択（省略「…」を出さない＝見切れ防止）。
    fs = 24
    while fs > 14:
        f = _ttf(fs)
        total = sum(d.textlength(t, font=f) for t in texts) + d.textlength(SEP, font=f) * (n - 1)
        if total <= inner: break
        fs -= 1
    f = _ttf(fs); sepw = d.textlength(SEP, font=f)
    total = sum(d.textlength(t, font=f) for t in texts) + sepw * (n - 1)
    x = PAD + 20 + max(0, (inner - total) / 2)   # 中央寄せ（収まらない極端時のみ左詰め）
    ty = BH/2 - fs*0.62
    for i, t in enumerate(texts):
        col = (255, 224, 90, 255) if i == cur else (205, 210, 205, 165)
        d.text((x, ty), t, font=f, fill=col); x += d.textlength(t, font=f)
        if i < n-1:
            d.text((x, ty), SEP, font=f, fill=(175, 182, 175, 150)); x += sepw
    im.save(out); return out

def make_surprise_se():
    """驚き用SE『ポンっ』を合成（既存se_impact.wavは触らず別ファイルへ）。手持ち音源があれば同名で上書き可。"""
    out = SEDIR / "se_surprise.wav"
    if out.exists(): return out
    SEDIR.mkdir(parents=True, exist_ok=True)
    sr = 44100; dur = 0.38; n = int(sr*dur); amp = 18000; frames = bytearray()
    for i in range(n):
        t = i / sr; freq = 420 + 900*(t/dur); env = math.exp(-t*9.0)
        s = math.sin(2*math.pi*freq*t) * env
        s += 0.4 * math.sin(2*math.pi*180*t) * math.exp(-t*14.0)   # 軽い低音ボディ
        frames += struct.pack("<h", int(max(-1, min(1, s)) * amp))
    with contextlib.closing(wave.open(str(out), "wb")) as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(bytes(frames))
    return out

PANEL_VER = "paper2"   # サイドパネル描画の版（3種：用語解説=金/豆知識=黄メモ/補足=水色）。文章連結・左余白統一・種別枠・見出し蛍光ペンに刷新。仕様変更で上げてキャッシュ無効化
PANEL_ACCENT = {"gl": (214,158,45), "tv": (22,150,110), "sp": (22,150,210), "st": (22,150,210)}   # 種別枠の色（用語解説=金/豆知識=緑/補足=青）
PANEL_HL     = {"gl": (255,232,90), "tv": (255,140,180), "sp": (150,228,248), "st": (150,228,248)} # 見出し蛍光ペン（紙の上で映える色：黄/ピンク/水色）
PANEL_TOP = 105        # サイドパネルの通常（単独）上端Y
PANEL_TOP_STACK = 72   # 2枚同時に出す時は上へずらす上端Y（チャプターバー下端66の直下）
def _panel_prose(note):
    """note内の\\n区切り・箇条書き記号を取り払い、1つの地の文へ連結（用語解説/補足を豆知識と同じ文章形式にする）。"""
    raw = [re.sub(r"^[◆・\-–—•●○▸▹\s]+", "", x.strip()) for x in re.split(r"[\n]", str(note or "")) if x.strip()]
    if not raw: return ""
    s = ""
    for b in raw:
        if s and not re.search(r"[。！？、!?]$", s): s += "、"
        s += b
    return s
def _panel(tag, badge, accent, title, sub, note, key, subhead=None, illust_path=None, illust_cap=None):
    """サイドパネル3種：tv=黄メモ／gl=ルーズリーフ(金)／sp,st=キャンバスノート(水色)。
    ・note は _panel_prose で1文に連結（文章形式）／・左余白 ml=72 に統一／・種別カラーで枠囲い／・見出しに蛍光ペン。
    illust_path指定 or IMAGES/gloss_<key>.png があれば下部にイラスト。illust_cap＝画像下キャプション（出典等）。accentは未使用（紙ごとに固有色）。"""
    FX.mkdir(exist_ok=True)
    ck = re.sub(r"[^\w]+", "_", str(key or title))[:20] or "x"
    ill = None
    ill_p = Path(illust_path) if illust_path else (IMAGES / f"gloss_{ck}.png")
    if ill_p.exists():
        try: ill = Image.open(ill_p).convert("RGBA"); ill.thumbnail((410, 190))
        except Exception: ill = None
    out = FX / f"_panel_{PANEL_VER}_{tag}_{ck}_{1 if ill else 0}.png"
    if out.exists(): return out
    style = "memo" if tag == "tv" else ("leaf" if tag == "gl" else "campus")
    ACC = PANEL_ACCENT.get(tag, (120,120,120)); HL = PANEL_HL.get(tag, (255,232,90))
    Wc = 500                                            # DIAG_PX_PANEL(x556〜)のカードと干渉しない幅
    if style == "memo":
        PAPER=(250,226,120); INK=(58,46,18); LINE=(210,178,96); MARGIN=(200,92,74); HEADTXT=(74,58,20); HEADBAND=(245,210,84)
    elif style == "leaf":
        PAPER=(250,250,245); INK=(40,52,74); LINE=(150,182,220); MARGIN=(205,120,116); HEADTXT=(46,70,110); HEADBAND=(226,231,238)
    else:
        PAPER=(252,251,243); INK=(44,54,66); LINE=(150,182,214); MARGIN=(205,120,116); HEADTXT=(52,132,104); HEADBAND=(224,240,236)
    f_title=_ttf(36); f_sub=_ttf(22); f_note=_ttf(27); f_sh=_ttf(24); f_badge=_ttf(28)
    d0 = ImageDraw.Draw(Image.new("RGBA",(8,8)))
    ml = 72                                             # ★左余白を豆知識(72)に統一
    avail = Wc - ml - 28
    note = _panel_prose(note)                           # ★箇条書き→文章連結
    wlines=[]; cur=""
    for ch in str(note):
        if d0.textlength(cur+ch, font=f_note) > avail: wlines.append(cur); cur=ch
        else: cur+=ch
    if cur: wlines.append(cur)
    wlines = wlines[:8]
    capwl=[]
    if ill is not None and illust_cap:
        cf=_ttf(19); cur=""
        for c in str(illust_cap):
            if d0.textlength(cur+c,font=cf)>Wc-40: capwl.append(cur); cur=c
            else: cur+=c
        if cur: capwl.append(cur)
    cap_h=len(capwl)*24+6 if capwl else 0
    ill_h=(ill.height+12+cap_h) if ill is not None else 0
    head_h=84; title_h=54; sub_h=30 if sub else 0; sh_h=34 if (subhead and style!="campus") else 0
    body_top=head_h+title_h+sub_h+sh_h+6
    Hc=body_top+len(wlines)*44+18+ill_h
    im=Image.new("RGBA",(Wc,Hc),(0,0,0,0)); d=ImageDraw.Draw(im)
    sh=Image.new("RGBA",(Wc,Hc),(0,0,0,0)); ImageDraw.Draw(sh).rounded_rectangle([8,12,Wc-3,Hc-3],radius=12,fill=(0,0,0,120))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(11)))
    PW,PH=Wc-6,Hc-6; rad=12
    d.rounded_rectangle([0,0,PW,PH],radius=rad,fill=PAPER+(255,))
    # ヘッダー帯＋種別アイコン（アイコンは文字位置に合わせて上げる）
    d.rounded_rectangle([0,0,PW,70],radius=rad,fill=HEADBAND+(255,)); d.rectangle([0,40,PW,70],fill=HEADBAND+(255,))
    if style=="memo":
        icx,icy=38,32; d.ellipse([icx-14,icy-17,icx+14,icy+11],fill=(255,244,180,255),outline=INK+(255,),width=3)  # 電球
        d.rectangle([icx-6,icy+9,icx+6,icy+18],fill=(190,160,60,255),outline=INK+(255,),width=2)
    elif style=="leaf":
        icx,icy=38,29; d.ellipse([icx-16,icy-16,icx+16,icy+16],fill=HEADTXT+(255,))                                # 情報アイコン(丸i)
        d.ellipse([icx-3,icy-10,icx+4,icy-3],fill=(255,255,255,255)); d.rounded_rectangle([icx-3,icy-1,icx+4,icy+11],radius=2,fill=(255,255,255,255))
    else:
        _bx0,_by0=32,29                                                                                            # 本(辞書)アイコン＝白ページ塗り＋背表紙＋文字罫で明確化
        d.polygon([(_bx0-17,_by0-12),(_bx0-1,_by0-8),(_bx0-1,_by0+12),(_bx0-17,_by0+8)],fill=(255,255,255,255),outline=HEADTXT+(255,),width=2)
        d.polygon([(_bx0+17,_by0-12),(_bx0+1,_by0-8),(_bx0+1,_by0+12),(_bx0+17,_by0+8)],fill=(255,255,255,255),outline=HEADTXT+(255,),width=2)
        d.line([(_bx0,_by0-8),(_bx0,_by0+12)],fill=HEADTXT+(255,),width=3)
        for _ly in (_by0-4,_by0+2):
            d.line([(_bx0-13,_ly),(_bx0-4,_ly-1)],fill=HEADTXT+(200,),width=1); d.line([(_bx0+4,_ly-1),(_bx0+13,_ly)],fill=HEADTXT+(200,),width=1)
    d.text((66,16),badge,font=f_badge,fill=HEADTXT+(255,))
    if style=="campus" and subhead:                                                                                # 補足の副題は括弧でヘッダーへ
        _bx=66+d0.textlength(badge,font=f_badge); d.text((_bx+4,24),"（"+subhead.replace("▼","").replace("　"," ").strip()+"）",font=_ttf(20),fill=HEADTXT+(255,))
    # 罫線（軽く）＋左マージン線（54＝豆知識と同じ）
    yy=body_top-8
    while yy<PH-16: d.line([(20,yy),(PW-20,yy)],fill=LINE+(90,),width=1); yy+=44
    d.line([(54,78),(54,PH-16)],fill=MARGIN+(120,),width=2)
    # ★種別カラーで枠を囲う
    d.rounded_rectangle([1,1,PW-1,PH-1],radius=rad,outline=ACC+(255,),width=4)
    tx = ml
    _tt=str(title)[:16]; _tw=d0.textlength(_tt,font=f_title)
    ov=Image.new("RGBA",im.size,(0,0,0,0)); ImageDraw.Draw(ov).rounded_rectangle([tx-6,head_h+20,tx+_tw+10,head_h+46],radius=6,fill=HL+(150,))  # ★見出し蛍光ペン
    im.alpha_composite(ov); d=ImageDraw.Draw(im)
    d.text((tx, head_h-2), _tt, font=f_title, fill=INK+(255,))
    ty = head_h + title_h - 8
    if sub:
        _rt=(str(sub) if ("（" in str(sub) or "(" in str(sub)) else f"（{sub}）"); _rf=f_sub   # 既に括弧を含むなら二重にしない
        while _rf.size>13 and d0.textlength(_rt,font=_rf) > Wc-ml-20: _rf=_ttf(_rf.size-1)
        d.text((tx, head_h+46), _rt, font=_rf, fill=(120,130,150,255))
    if subhead and style != "campus":
        d.text((tx, ty-8), subhead, font=f_sh, fill=HEADTXT+(255,)); ty += 30
    y = body_top - 6
    for wl in wlines:
        d.text((tx, y), wl, font=f_note, fill=INK+(255,)); y += 44
    if ill is not None:
        _ix=(PW-ill.width)//2; _iy=y+6
        _sh2=Image.new("RGBA",(Wc,Hc),(0,0,0,0)); ImageDraw.Draw(_sh2).rounded_rectangle([_ix-7,_iy-4,_ix+ill.width+9,_iy+ill.height+11],radius=9,fill=(0,0,0,80))
        im.alpha_composite(_sh2.filter(ImageFilter.GaussianBlur(5))); d=ImageDraw.Draw(im)
        d.rounded_rectangle([_ix-8,_iy-8,_ix+ill.width+8,_iy+ill.height+8],radius=9,fill=(255,255,255,255),outline=(178,182,172,255),width=2)  # 図の台紙枠（白背景の浮き防止＝意図的な図枠に）
        im.alpha_composite(ill,(_ix,_iy)); d=ImageDraw.Draw(im)
        cy=_iy+ill.height+16
        for cl in capwl:
            cw=d0.textlength(cl,font=_ttf(19)); d.text(((PW-cw)//2,cy),cl,font=_ttf(19),fill=HEADTXT+(255,)); cy+=24
    im.save(out); return out

def make_sticky(term, note):
    """豆知識パネル（ミント）。"""
    return _panel("tv", "豆知識", (16, 185, 129), term, "", note, term)

def make_termgloss(abbr, full, note):
    """用語解説パネル（金）。台詞に出てくる語の説明。下部に用語イラスト(gloss_<abbr>.png)を差込。"""
    return _panel("gl", "用語解説", (245, 158, 11), abbr, full, note, abbr)

def make_supplement(term, note):
    """補足パネル（スカイ青）。台詞に無い"なぜ？"の深掘りを『もっと知りたい人へ』として任意提示（台詞不変＝再録音不要）。"""
    return _panel("sp", "補足", (14, 165, 233), term, "", note, term, subhead="▼ もっと知りたい人へ")

def make_struct_panel(img_path, term, note, cap):
    """実構造の補足パネル（スカイ青）。本編カードから外した実測/予測構造をここで見せる（オプションA）。構造画像の下に出典キャプション。"""
    return _panel("st", "補足", (14, 165, 233), term, "", note, "struct_" + str(term), subhead="▼ 実際の立体構造", illust_path=str(img_path), illust_cap=cap)

def make_heading_underline(text, size):
    """黒板見出しの下に引く明るいチョーク下線（テキスト幅に合わせる）。"""
    FX.mkdir(exist_ok=True)
    key = re.sub(r"[^\w]+", "_", str(text))[:16] or "x"
    out = FX / f"_ul_{key}_{size}.png"
    if out.exists(): return out
    f = _ttf(size)
    w = int(ImageDraw.Draw(Image.new("RGBA", (8, 8))).textlength(str(text), font=f))
    Wc, Hc = max(80, w), 18; im = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 6, Wc-1, 12], radius=3, fill=(120, 232, 180, 235))   # 明るいチョーク色
    for i in range(0, Wc, 15):                                                    # チョーク粉
        d.ellipse([i, 4, i+3, 15], fill=(210, 255, 230, 110))
    im.filter(ImageFilter.GaussianBlur(0.5)).save(out); return out

def make_photo_paste(src, tilt=-6, caption=None):
    """追加史実写真を『ペタッと貼った』見た目に（白マット枠+テープ+影を少し傾ける）。
       caption があれば下部に『氏名（生没年）』の帯を焼き込む。"""
    FX.mkdir(exist_ok=True)
    ckey = re.sub(r"[^\w]+", "_", str(caption))[:24] if caption else ""
    out = FX / f"photo_{Path(src).stem}_{tilt}{('_' + ckey) if ckey else ''}.png"
    if out.exists(): return out
    base = make_framed_card(src)   # 白マット枠＋立体シャドウ＋角クラフトテープを流用
    im = Image.open(base).convert("RGBA")
    if caption:
        d = ImageDraw.Draw(im); Wc, Hc = im.size
        fs = 52                                     # 見やすいよう大きめ（PHOTO_H縮小後も読める）
        while fs > 34 and d.textlength(caption, font=_ttf(fs)) > Wc - 60: fs -= 2
        f = _ttf(fs); bar_h = fs + 24; y0 = Hc - bar_h - 24
        d.rounded_rectangle([20, y0, Wc - 20, y0 + bar_h], radius=10, fill=(18, 26, 22, 255))
        d.text((Wc / 2, y0 + bar_h / 2), caption, font=f, fill=(255, 240, 205, 255), anchor="mm")
    im = im.rotate(tilt, expand=True, resample=Image.BICUBIC)
    im.save(out); return out

# ==== 口パク/瞬きモード（--lipsync）：TachieItem＋VoiceItem（旧SD_v5/demo_sd実証済を移植） ====
# カード無し(トーク/オープニング)=全身キャラ／解説中(カード表示)=頭だけキャラ、をモードで切替
LS_CHARNAME_BIG   = {"akane": "琴葉茜SD",   "aoi": "琴葉葵SD"}     # 全身（大きく・両脇）
LS_CHARNAME_SMALL = {"akane": "琴葉茜SD頭", "aoi": "琴葉葵SD頭"}   # 頭だけ（小さく・下端）
LS_CHARNAME = LS_CHARNAME_SMALL   # 後方互換の既定
LS_WAVJP = {"akane": "茜", "aoi": "葵"}
# 頭だけキャラ用の配置。動的レイアウト：
#  ・LS_POS_BIG  = 資料(カード)を出してない時＝両脇で大きく（トーク/オープニング/エンディング）
#  ・LS_POS_SMALL= 解説中(カード表示)＝小さく下端へ寄せて資料を主役に
# zoom/位置は頭だけ描画のためYMM4実機で微調整可。
LS_POS_BIG   = {"茜": {"x": -800.0, "y": 500.0, "zoom": 22.0, "flip": True},
               "葵": {"x": 800.0, "y": 500.0, "zoom": 22.0, "flip": False}}   # 免責字幕と被る指摘で zoom30→22・x±800まで両脇へ（中央を字幕に明け渡す）
LS_POS_SMALL = {"茜": {"x": -800.0, "y": 530.0, "zoom": 22.0, "flip": True},
               "葵": {"x": 800.0, "y": 530.0, "zoom": 22.0, "flip": False}}   # 420×420(zoom22)／頭だけ下端寄せ530／x±720→±800（両脇へ）
LS_POS = LS_POS_BIG   # 既定（後方互換）
LS_VOWEL = {"a": "A", "i": "I", "u": "U", "e": "E", "o": "O"}

def _ls_ts(sec):
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = sec % 60
    return f"{h:02d}:{m:02d}:{s:010.7f}"

def _ls_lipsync(lab):
    fr = [{"Time": "00:00:00", "Shape": "Silent"}]
    if not lab or not lab.exists():
        return fr
    for line in lab.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) < 3:
            continue
        t = int(p[0]) * 1e-7; lb = p[2]
        if lb in LS_VOWEL: fr.append({"Time": _ls_ts(t), "Shape": LS_VOWEL[lb]})
        elif lb == "pau": fr.append({"Time": _ls_ts(t), "Shape": "Silent"})
    return fr

def _ls_rawwav(idn, spk):
    cs = sorted(AUDIO.glob(f"琴葉 {LS_WAVJP[spk]}(NV){idn:04d}*.wav"))
    if not cs:
        return None
    withlab = [w for w in cs if w.with_suffix(".lab").exists()]   # .labがある方を優先(OneDrive競合の重複wav対策)
    return withlab[0] if withlab else cs[0]

def load_lipsync_templates():
    # 立ち絵は2系統を埋め込み、行ごとに使い分ける：
    #  ・全身キャラ(琴葉茜SD/葵SD)   ＝カード無し(トーク/オープニング)で大きく（口パクpatch適用）
    #  ・頭だけキャラ(琴葉茜SD頭/葵SD頭)＝解説中(カード表示)で小さく（YMM4登録の実定義。母音口パク対応済）
    V = load(TPL / "sd_voice.json")
    DA = load(TPL / "demo_tachie_琴葉葵SD.json"); dtp = DA["TachieItemParameter"]
    mouth = [(p, l) for p, l in zip(dtp["EnableLayerPaths"], dtp["EnableLayers"]) if "口" in p]
    def patch(tp):
        tp = copy.deepcopy(tp)
        kept = [(p, l) for p, l in zip(tp["EnableLayerPaths"], tp["EnableLayers"]) if "口" not in p]
        kept += mouth
        tp["EnableLayerPaths"] = [p for p, l in kept]; tp["EnableLayers"] = [l for p, l in kept]
        return tp
    # 頭だけ（解説中・小）
    C_head = load(TPL / "head_characters.json")
    tac_head = {}
    for c in C_head:
        nm = c.get("Name", ""); key = "茜" if "茜" in nm else ("葵" if "葵" in nm else None)
        if key and isinstance(c.get("TachieDefaultItemParameter"), dict):
            tac_head[key] = copy.deepcopy(c["TachieDefaultItemParameter"])
    # 全身（トーク・大）：口パクpatch＋名前を全身キャラ名へ
    C_full = load(TPL / "sd_characters.json")
    for c in C_full:
        if c.get("Name") == "茜": c["Name"] = LS_CHARNAME_BIG["akane"]
        elif c.get("Name") == "葵": c["Name"] = LS_CHARNAME_BIG["aoi"]
        di = c.get("TachieDefaultItemParameter")
        if isinstance(di, dict) and "EnableLayerPaths" in di:
            c["TachieDefaultItemParameter"] = patch(di)
    tac_full = {"葵": patch(load(TPL / "sd_tachie_葵.json")["TachieItemParameter"]),
                "茜": patch(load(TPL / "sd_tachie_茜.json")["TachieItemParameter"])}
    C = C_full + C_head   # 両キャラ定義を埋め込む
    return V, C, DA, {"full": tac_full, "head": tac_head}

def ls_voice_item(V, idn, spk, text, frame, length, charname=None):
    v = copy.deepcopy(V); w = _ls_rawwav(idn, spk)
    v["CharacterName"] = charname or LS_CHARNAME[spk]; v["Serif"] = text; v["Hatsuon"] = str(w)
    try: v["Volume"]["Values"][0]["Value"] = 100.0     # 声量フル(1倍)＝小さい対策
    except Exception: v["Volume"] = anim(100.0)
    v["Pronounce"] = {"$type": "YukkuriMovieMaker.Voice.CustomVoice.CustomVoicePronounce, YukkuriMovieMaker",
                      "LipSyncFrames": _ls_lipsync(w.with_suffix(".lab") if w else None)}
    v["LipSyncFrames"] = None; v["VoiceCache"] = None
    v["VoiceLength"] = _ls_ts(wdur(w) or 1.0) if w else "00:00:01.0000000"
    v["JimakuVisibility"] = "Hidden"
    v["Frame"] = int(frame); v["Length"] = max(1, int(length)); v["Layer"] = 2
    return v

def ls_tachie(DA, tacparam, spk, frame, length, layer, motion_kind=None, pos=None, charname=None):
    sister = LS_WAVJP[spk]; t = copy.deepcopy(DA)
    t["CharacterName"] = charname or LS_CHARNAME[spk]; t["TachieItemParameter"] = copy.deepcopy(tacparam[sister])
    t["Frame"] = int(frame); t["Length"] = max(1, int(length)); t["Layer"] = int(layer)
    p = (pos or LS_POS)[sister]
    t["X"] = anim(p["x"]); t["Y"] = anim(p["y"]); t["Zoom"] = anim(p["zoom"])
    t["Rotation"] = anim(0.0); t["Opacity"] = anim(100.0); t["Z"] = anim(0.0)
    t["IsInverted"] = p["flip"]; t["VideoEffects"] = motion(motion_kind) if motion_kind else []
    return t

def disclaimer_bg_path():
    """免責カット専用背景（epNN/images優先→assets/common）。"""
    for base in (IMAGES, COMMON):
        cs = sorted(base.glob("disclaimer_bg.*"))
        if cs: return cs[0]
    return None

def resolve_image(ln):
    kw = ln.get("image_keyword")
    if not kw: return None
    if str(kw).startswith("disclaimer"): return None   # 免責背景はカード扱いしない（別処理で全画面表示）
    # ※旧「curious/question は汎用教室カードなので不使用」除外は撤廃（2026-08-10）。
    #   Gemini再生成で各質問カードも概念固有の高精細画像になったため表示する。
    for stem in (f"img_{ln['id']}", re.sub(r"[^\w\-]+", "_", kw), IMAGE_ALIAS.get(kw), kw):
        if not stem: continue
        for base in (IMAGES, COMMON):
            for c in sorted(base.glob(stem + ".*")):
                if c.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"): return c
    return None

def px_center(x, y): return (x - W/2, y - H/2)

def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--noaudio", action="store_true"); ap.add_argument("--lipsync", action="store_true"); ap.add_argument("--ep", default="02"); ap.add_argument("--dir", default=None)
    a = ap.parse_args(); noaudio = a.noaudio; lipsync = a.lipsync
    out = OUT.with_name(f"{OUT.stem}_lipsync.ymmp") if lipsync else (OUT.with_name(f"{OUT.stem}_noaudio.ymmp") if noaudio else OUT)
    LSV = LSC = LSDA = LSTP = None
    if lipsync:
        LSV, LSC, LSDA, LSTP = load_lipsync_templates()
    out.parent.mkdir(parents=True, exist_ok=True)
    make_surprise_se()   # 驚き用SE（別音源）を用意
    data = load(SCRIPT_JSON); lines = data["lines"] if isinstance(data, dict) else data
    # 免責はscript.jsonの位置（冒頭id1＝OP直後）で表示（ユーザー確定：前の位置でOK）
    meta = data.get("meta", {}) if isinstance(data, dict) else {}

    proj = load(TPL / "base_project.json", sig=True)
    tl = proj["Timelines"][0]
    tl["VideoInfo"]["FPS"] = FPS; tl["VideoInfo"]["Width"] = W; tl["VideoInfo"]["Height"] = H
    tl["VideoInfo"]["BackgroundColor"] = "#FF08120E"   # 確定版：ディープモスグリーン
    tl["LayerSettings"] = None                          # 無題テンプレのlayer15非表示設定を除去
    proj["Characters"] = LSC if lipsync else []; proj["FilePath"] = str(out)

    board = make_board(); subbar = make_subbar()
    pin_r = make_pin((214, 57, 70), "red"); pin_b = make_pin((0, 119, 182), "blue")

    # 立ち絵の位置・ズーム
    chibi = {}
    for spk, leftx in (("akane", CHIBI_LEFT_X), ("aoi", CHIBI_RIGHT_X)):
        w, h = imgsize(CHARS / spk / "normal.png")
        zoom = CHIBI_H / h * 100.0
        dispw = w * CHIBI_H / h
        cx = leftx + dispw/2
        cy = 1040 - CHIBI_H/2
        chibi[spk] = {"x": cx - W/2, "y": cy - H/2, "zoom": round(zoom, 1)}

    # 尺割付（OP → 各行(実音声) → ED）。insert_eyecatchの行の直前にアイキャッチ用の空きを確保
    #  ＝タイムラインに実際の隙間を挿入するので、以降の全アイテムのフレームが自動で後ろへずれる（台詞と被らない）
    eyecatch_vid = COMMON / "eyecatch_jingle.mp4"   # ユーザー要望：アイキャッチは旧jingleに戻す（尺予約と配置951で統一）
    spans = []; frame = OP_LEN; eyecatch_frame = None; prev_sec = None
    for ln in lines:
        sec = ln.get("section")
        if prev_sec is not None and sec != prev_sec:
            frame += SECTION_GAP           # 章の切れ目に間（唐突さ緩和）
        prev_sec = sec
        if eyecatch_frame is None and ln.get("insert_eyecatch") and eyecatch_vid.exists():
            eyecatch_frame = frame
            frame += EYE_LEN + GAP
        spk = ln["speaker"] if ln["speaker"] in ("akane", "aoi") else "aoi"
        wav = AUDIO / f"{ln['id']:03d}_{spk}.wav"
        if lipsync:                       # 口パク版はNV生wav(実再生音声)の尺で割付＝NNNスロー化の影響を受けない
            raww = _ls_rawwav(ln["id"], spk)
            dur = (wdur(raww) if raww else None) or wdur(wav) or 2.0
        else:
            dur = wdur(wav) or 2.0
        length = round(dur * FPS)
        spans.append((ln, spk, wav, frame, length))
        frame += length + GAP
    main_end = frame
    total = main_end + ED_LEN

    items = []
    # 背景（全長）
    items.append(image_item(board, 0, total, L_BG, 0, 0, 100.0, fade=0.0))
    # ※立ち絵は各行ループで「話者=表情+モーション／相手=通常」を区間連続で1体ずつ配置（基底は置かない=ダブり防止）
    # タイトル（左上）＝トーク区間だけ表示・解説中(カード表示)は非表示（情報量が多いので上部を資料に開放）。
    ttl = meta.get("title") or meta.get("category_label", "")
    mm = re.match(r"\s*(第\d+話)\s*[:：]?\s*(.*)$", ttl)
    if mm and mm.group(2).strip():
        t_main = mm.group(1); t_sub = mm.group(2).strip()
    else:
        m = re.match(r"(.*?第\d+話)\s*(.*)", ttl)
        t_main = (m.group(1) if m else ttl).strip()
        t_sub = (m.group(2).strip() if (m and m.group(2).strip()) else "")
    tmx, tmy = px_center(50, 44)
    TITLE_YEL, TITLE_WHT, TITLE_BORDER = "#FFFFE14D", "#FFFFFFFF", "#FF13312A"
    _bi = t_main.find("【")
    def _place_title(rf, rl):
        if _bi > 0 and "】" in t_main:
            pre, brk = t_main[:_bi], t_main[_bi:]
            MAIN_SIZE, SUB_SIZE, GAP, _LIMIT = 50.0, 38.0, 40, 1820  # 左右50px余白内(1920-100)に収める
            _dr = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
            prew = _dr.textlength(pre, font=_ttf(int(MAIN_SIZE)))
            brkw = _dr.textlength(brk, font=_ttf(int(SUB_SIZE)))
            if prew + GAP + brkw > _LIMIT:  # 長いタイトルはmain/subを等倍縮小して1行に収める（右端見切れ防止）
                _sc = _LIMIT / (prew + GAP + brkw)
                MAIN_SIZE *= _sc; SUB_SIZE *= _sc
                prew = _dr.textlength(pre, font=_ttf(int(MAIN_SIZE)))
            items.append(text_item(pre, rf, rl, L_TITLE, tmx, tmy, size=round(MAIN_SIZE, 1),
                                   basepoint="LeftTop", color=TITLE_YEL, style_color=TITLE_BORDER, maxw=1860, fade=0.2))
            bx, bty = px_center(50 + int(prew) + GAP, 44 + (MAIN_SIZE - SUB_SIZE))
            items.append(text_item(brk, rf, rl, L_TITLE, bx, bty, size=round(SUB_SIZE, 1),
                                   basepoint="LeftTop", color=TITLE_WHT, style_color=TITLE_BORDER, maxw=1860, fade=0.2))
        else:
            items.append(text_item(t_main, rf, rl, L_TITLE, tmx, tmy, size=50,
                                   basepoint="LeftTop", color=TITLE_YEL, style_color=TITLE_BORDER, maxw=1200, fade=0.2))
        if t_sub:
            tsx, tsy = px_center(52, 128)
            items.append(text_item(t_sub, rf, rl, L_TITLE, tsx, tsy, size=32,
                                   basepoint="LeftTop", color="#FFF0F0EB", style_color="#FF13312A", maxw=1000, fade=0.2))
    # タイトルは「オープニング」区間だけ表示（エンディングは"そのままEDカード"にしたので出さない＝カードに被らない）。
    _title_ranges = []; _run = None
    for _i, (_l, _s, _w, _ff, _ln) in enumerate(spans):
        _e = spans[_i+1][3] if _i+1 < len(spans) else main_end
        if _l.get("section") in ("オープニング",):
            _run = [_ff, _e] if _run is None else [_run[0], _e]
        elif _run:
            _title_ranges.append(tuple(_run)); _run = None
    if _run: _title_ranges.append(tuple(_run))
    for _rf, _re in _title_ranges:
        if _re > _rf: _place_title(_rf, _re - _rf)
    # 字幕バー（本編中・全長）＝中央だけ・薄型半透明黒バー（単一）。バー下端≒px1043で下部に寄せる。
    items.append(image_item(subbar, OP_LEN, main_end-OP_LEN, L_SUBBAR, 0, 370.0, 100.0, fade=0.0))  # 確定版：下部シネマ影340高

    # OP＝シネマティック動画＋文字オーバーレイ（使い回し可能な文字分離構造）
    # 1. 最優先: 話数専用完全動画 (op_custom.mp4)
    # 2. 標準: シリーズ別/汎用OP背景動画 (op_bg_*.mp4) ＋ 話別文字オーバーレイ (op_title_overlay.png)
    # 3. フォールバック: 静止画カード (make_op_card)
    op_custom = EP_ROOT / "output" / "op_custom.mp4"
    series_name = meta.get("series", "")
    op_series_vid = COMMON / f"op_bg_{series_name}.mp4"
    op_common_vid = COMMON / "op_bg_cinematic.mp4"
    op_overlay = IMAGES / "op_title_overlay.png"

    # ユーザー要望でOPは黒板タイトルカード(make_op_card・Claude生成)に戻す＝Gemini製op_title_overlay.pngは
    # 文字が小さく青バッジに収まらないため不使用。話数専用完成動画(op_custom.mp4)があればそれを優先。
    if op_custom.exists():
        items.append(video_item(op_custom, 0, OP_LEN, L_OPED, 0, 0, 100.0, fade=0.2))
    else:
        op = make_op_card(meta); z = min(W/imgsize(op)[0], H/imgsize(op)[1])*100.0
        items.append(image_item(op, 0, OP_LEN, L_OPED, 0, 0, round(z,1), fade=0.3))
    # ED末尾エンドカード（2026-08-11刷新）：フレーム全体を使い、次回予告(実画像)＋登録CTA＋御礼をコード生成。
    # 旧ed_channel_card.png（平坦・半分空白）を置換。登録ボタン等はUI要素＝コード描画が適切。
    _next_img = None; _next_sub = ""
    for _l in lines:                                   # 次回予告＝preview系image_keywordの行から絵とキャプションを拾う
        _kw = str(_l.get("image_keyword", ""))
        if "preview" in _kw or "yokoku" in _kw or "next" in _kw:
            # 本編カードと同じ合成図(COMPOSITIONS優先)を使う。resolve_imageだとimages/の旧・粗い事前レンダ
            # (金属アイコン等)を拾って次回予告が崩れるため（2026-08-13ユーザー指摘）。
            # ★EDカードは自前で「▶次回予告」見出し＋キャプションを載せる＝説明用の?図を流用すると雑に見える。
            #   duo系は専用ティザーサムネ(_compose_next_thumb)で被写体を大きく・クリーンに組む（2026-08-13ユーザー指摘）。
            if _kw in COMPOSITIONS and COMPOSITIONS[_kw].get("layout") == "duo":
                _p = _compose_next_thumb(COMPOSITIONS[_kw])
            elif _kw in COMPOSITIONS:
                _spec = {k: v for k, v in COMPOSITIONS[_kw].items() if k not in ("title", "subtitle")}
                _p = compose_figure(_spec)
            else:
                _p = resolve_image(_l)
            if _p: _next_img = _p
            _ct = _l.get("card_text") if isinstance(_l.get("card_text"), dict) else {}
            _next_sub = (_ct.get("caption") or (_l.get("board_bullets") or [""])[0] or "").strip()
            break
    _next_no = "次回予告"   # Ep番号は視聴者に出さない（メタ回避）＝「第N話」ではなく中立の「次回予告」
    _tag = ""               # EDの上部タグライン（「薬学生化学マスター」等）は出さない（ユーザー指摘）
    ed_card = make_ed_card(_next_img, _next_no, _next_sub, _tag, CHANNEL_NAME)
    # EDトーク中は「まとめ全画面」を敷かず、直前の話のスライドをそのまま継続表示する（ユーザー指摘2026-08-12）。
    # ＝カードループ側で最後の解説カードを main_end まで延長（_ed_start でクランプしない）ことで実現。まとめ全画面overlayは廃止。
    # （まとめ内容は id15 の summary → make_matome_note カードとして第5章で表示済み＝まとめ自体は残る）
    if ed_card and Path(ed_card).exists():
        z = min(W/imgsize(ed_card)[0], H/imgsize(ed_card)[1])*100.0
        # EDカードは「台詞が終わってから」＝余韻区間(main_end以降)に表示（喋っている最中にEDが被る問題を解消・ユーザー指摘）。
        _ec_start = main_end
        _ec_len = ED_LEN
        items.append(image_item(ed_card, _ec_start, _ec_len, L_OPED, 0, 0, round(z,1), fade=0.3))
        # チャンネル登録ボタンを強調＝下向き矢印を登録ボタン上に重ね、ED尺いっぱい上下に連続バウンス
        _arrow = make_tap_arrow()
        _bx, _by = px_center(1390, 232)
        _ai = image_item(_arrow, _ec_start, _ec_len, 16, _bx, _by, 100.0, fade=0.3)
        _hops = max(8, int(_ec_len / 34))                        # 連続バウンス（回数UP）
        _amp = 52                                                # バウンス振幅UP（34→52・目立たせる）
        _ai["Y"] = anim_multi([(_by if k % 2 == 0 else _by - _amp) for k in range(_hops * 2 + 1)])
        items.append(_ai)

    # 中盤アイキャッチ（1.5s・全画面・自前ジングル音声。予約済みの空き区間に配置）
    eyecatch_vid = COMMON / "eyecatch_jingle.mp4"
    if eyecatch_frame is not None and eyecatch_vid.exists():
        ev = video_item(eyecatch_vid, eyecatch_frame, EYE_LEN, L_OPED, 0, 0, 100.0, fade=0.15)
        ev["IsLooped"] = False
        items.append(ev)

    # トーク背景：オープニング/エンディングの雑談パートだけ bg_loop_talk（動画優先・ループ）を無地黒板の上に重ねる
    # ※トピック解説中（第1〜3章）は重ねない＝無地黒板のまま挿絵カードを引き立てる
    talk_vid = COMMON/"_bg_loop_talk_orig.mp4"; talk_img = find_img("bg_loop_talk.png")  # ユーザー要望：新bg_loop_talk.mp4(机)は使わず旧origに戻す
    def _section_ranges(secname):
        out = []; run = None
        for idx, (ln, _s, _w, ff, _l) in enumerate(spans):
            e = spans[idx+1][3] if idx+1 < len(spans) else main_end
            if ln.get("section") == secname:
                run = [ff, e] if run is None else [run[0], e]
            elif run:
                out.append(run); run = None
        if run: out.append(run)
        return out
    # 汎用背景：中央カードが出るまで(冒頭〜最初のカード)＋エンディング＝中央が空く区間を埋める
    first_card_f = main_end
    for ln2, _s2, _w2, ff2, _l2 in spans:
        if ln2.get("section") not in ("オープニング", "エンディング") and resolve_image(ln2):
            first_card_f = ff2; break
    talk_ranges = [(OP_LEN, first_card_f)]                       # 冒頭〜最初のカード（文字だけの空き区間を埋める）
    for rf, re_ in _section_ranges("エンディング"):
        talk_ranges.append((rf, re_))
    for rf, re_ in talk_ranges:
        if re_ <= rf: continue
        if talk_vid.exists():
            v = video_item(talk_vid, rf, re_-rf, L_TALKBG, 0, 0, 100.0, fade=0.3); v["IsLooped"] = True
            items.append(v)
        elif talk_img.exists():
            items.append(image_item(talk_img, rf, re_-rf, L_TALKBG, 0, 0, 100.0, fade=0.3))

    n_img = 0; unmatched = []
    ccx, ccy = px_center(CARD_PX[0]+CARD_PX[2]/2, CARD_PX[1]+CARD_PX[3]/2)
    # 動的立ち絵：最初のカード出現行を求め、以降の解説行はカード表示中＝立ち絵を小さく下へ。
    # カード無し（オープニング/エンディング/最初のカード前）＝両脇で大きく。
    _first_card_idx = None
    for _i in range(len(spans)):
        if spans[_i][0].get("section") in ("オープニング", "エンディング"): continue
        if resolve_image(spans[_i][0]): _first_card_idx = _i; break
    def _pos_for(idx, ln):
        talk = ln.get("section") in ("オープニング", "エンディング")
        card_on = (_first_card_idx is not None) and (idx >= _first_card_idx) and not talk
        return LS_POS_SMALL if card_on else LS_POS_BIG
    for idx, (ln, spk, wav, f, length) in enumerate(spans):
        seg_len = (spans[idx+1][3] - f) if idx+1 < len(spans) else (main_end - f)
        ls_pos = _pos_for(idx, ln)
        _disc = ln.get("section") == "免責"               # 免責カット＝専用背景で全画面・通常演出なし
        if lipsync:
            _big = ls_pos is LS_POS_BIG                   # カード無し=全身/大 ／ カード表示=頭だけ/小
            ls_charmap = LS_CHARNAME_BIG if _big else LS_CHARNAME_SMALL
            ls_tacp = LSTP["full"] if _big else LSTP["head"]  # 音声と立ち絵のキャラ名を一致させ口パク連動を維持
        # 音声：口パク版=VoiceItem(.lab連動) ／ 通常=AudioItem
        if lipsync:
            items.append(ls_voice_item(LSV, ln["id"], spk, ln["text"], f, length, charname=ls_charmap[spk]))
        elif wav.exists() and not noaudio:
            items.append(audio_item(wav, f, length))
        # both行は茜の音声も重ねて二人の声にする（口パクは葵側／茜はAudioItemで発声のみ）
        if ln["speaker"] == "both" and not noaudio:
            aka = AUDIO / f"{ln['id']:03d}_akane.wav"
            if aka.exists():
                items.append(audio_item(aka, f, length))
        # 免責カット：専用背景を全画面＋注意マークを背景に大きく表示（立ち絵・字幕は出す／カード・タイトルは無し）
        if _disc:
            _dbg = make_green_bg()   # 免責背景＝緑無地（ユーザー要望）。AIラボ画像は不使用。
            items.append(image_item(_dbg, f, seg_len, L_CARD, 0, 0, 100.0, fade=0.3))
            _cau = make_caution_mark()   # 発光ハロー入り・静止（点滅は不要＝ユーザー指摘）
            items.append(image_item(_cau, f, seg_len, L_PIN, *px_center(W/2, 400), 100.0, fade=0.3))
        # 立ち絵：話者=表情+モーション（+発光）／相手=通常。基底なし・区間連続＝ダブり防止
        for who in ("akane", "aoi"):
            c = chibi[who]
            speaking = (ln["speaker"] == who)
            mk = (EXPR_MOTION.get(ln.get("expression")) or MOTION.get(ln.get("emotion", "平静"))) if speaking else None
            if idx == 0: mk = None   # 冒頭一発目のモーションは唐突なので無し
            if lipsync:
                ls_mk = None if mk == "jump" else mk   # ジャンプ(登場退場系)は口パクと干渉するため口パク版では無効化
                items.append(ls_tachie(LSDA, ls_tacp, who, f, seg_len, L_AK, ls_mk, pos=ls_pos, charname=ls_charmap[who]))
            else:
                base = CHARS/who/(f"{ln.get('expression','normal')}.png" if speaking else "normal.png")
                if not base.exists(): base = CHARS/who/"normal.png"
                src = make_glow_chibi(base) if speaking else base
                ci = image_item(src, f, seg_len, L_AK, c["x"], c["y"], c["zoom"], fade=0.0)
                if speaking: ci["VideoEffects"] = motion(mk)
                items.append(ci)
        # 話者名ラベル（足元ネームプレート）は廃止＝ユーザー要望（2026-08-10）。立ち絵で話者は分かるため字幕にキャラ名を出さない。
        # 感情オーバーレイ（話者に：驚き=『！』ポップ／喜び=キラキラ）
        emo = ln.get("emotion", "平静")
        if ln.get("section") in ("オープニング", "エンディング", "免責"):
            ovp = None                       # トーク/免責区間は感情エフェクト(キラキラ/!?)を出さない＝すっきり
        elif emo == "驚き":
            ovp = make_bikkuri(); ov_h = int(CHIBI_H*0.42); yoff = -CHIBI_H*0.62   # 小さめ＆頭上（顔かぶり回避）
        elif emo == "喜び":
            ovp = make_sparkle(); ov_h = int(CHIBI_H*0.65); yoff = -CHIBI_H*0.35   # 小さめ＆立ち絵上＝中央の黒板文字に届かない
        else:
            ovp = None
        if ovp and ln["speaker"] in chibi:
            if lipsync:
                ox = ls_pos[LS_WAVJP[ln["speaker"]]]["x"]; oy = ls_pos[LS_WAVJP[ln["speaker"]]]["y"] + yoff
            else:
                c = chibi[ln["speaker"]]; ox, oy = c["x"], c["y"] + yoff
            oz = round(ov_h / imgsize(ovp)[1] * 100, 1)
            items.append(image_item(ovp, f, seg_len, L_FX, ox, oy, oz, fade=0.15))
        # 字幕（話者カラー縁取り・名前付き）
        # 話者名は足元ネームプレートに一本化（字幕バーの名前ラベルは廃止）
        # ※EDカードは余韻(main_end以降)に移動したので、ed_channel_card行のCTA台詞は通常どおり字幕表示する（まとめ/トーク背景の上）。
        segs = split_sub(ln["text"])
        tot = sum(len(s.replace("\n", "")) for s in segs) or 1
        # 字幕は音声(VoiceItem)の尺=length基準で配分＝セリフと同期（seg_lenだとGAP/章間0.8s分だけ字幕が遅れてずれる）。
        end = f + length; sf = f
        for i, s in enumerate(segs):
            slen = (end - sf) if i == len(segs)-1 else max(int(FPS*0.5), round(length * len(s.replace("\n", "")) / tot))
            items.append(text_item(sub_wrap(s), sf, max(1, slen), L_SUBTXT, 0, SUB_Y, color=SUB_COLOR.get(ln.get("speaker"), "#FFFEF08A"), style_color="#FF000000", maxw=880))  # 話者カラー56px＋黒縁。sub_wrapで全行を短く（YMM4はMaxWidth自動折返しが効かないため明示改行で立ち絵とのかぶり回避）
            sf += slen

    # 解説画像カード＋ピン：出現行から次の画像出現行までトピック持続
    # 解説カードは「画像が変わった行」だけを起点にする（同じ画像が連続する行で再フェード表示＋se_card＋黒板消しワイプが
    # 多重発火して"迷路が何度もSEと共に再表示"していた不具合の修正）。トーク区間(OP/ED)はカードを出さない。
    imaged = []
    for i in range(len(spans)):
        if spans[i][0].get("section") in ("オープニング", "エンディング"): continue
        im = resolve_image(spans[i][0])
        if not im: continue
        if imaged and im == imaged[-1][1]: continue   # 直前と同じ画像＝新カードにしない（前カードが継続）
        imaged.append((i, im))
    diag_ranges = []   # 図解カードの表示区間（この間は黒板見出し/箇条書きを出さない＝重なり回避）
    dcx, dcy = px_center(DIAG_PX[0]+DIAG_PX[2]/2, DIAG_PX[1]+DIAG_PX[3]/2)
    dpcx, dpcy = px_center(DIAG_PX_PANEL[0]+DIAG_PX_PANEL[2]/2, DIAG_PX_PANEL[1]+DIAG_PX_PANEL[3]/2)  # パネル回避（右寄せ）用
    # 本編カードはエンディング開始でクランプ（最後のカードがmain_endまで居座りED=タイトル+全身立ち絵と重なるのを防ぐ）
    _ed_start = next((spans[j][3] for j in range(len(spans)) if spans[j][0].get("section") == "エンディング"), main_end)
    for k, (i, im) in enumerate(imaged):
        f0 = spans[i][3]
        f1 = spans[imaged[k+1][0]][3] if k+1 < len(imaged) else main_end
        if k + 1 < len(imaged):
            f1 = min(f1, _ed_start)                       # 章内カードはED区間へはみ出さない
        # ※最後の解説カードはクランプせず main_end まで延長＝EDトーク中も「直前の話のスライド」をそのまま継続（ユーザー指摘2026-08-12）
        if f1 <= f0: continue
        # 章内(ワイプ無し)のカード切替で背景(黒板)が一瞬見える＝スライドが消える不具合の防止：
        # 章内の次カードへは、出ていくカードをFadeOut=0で消さず次カードのFadeInぶん長く残し"下敷き"に→上に被りクロスフェード。
        # ★章切替(ワイプ)や末尾へは延長しない＝前カードがワイプ後まで居座り"廃止画像が一瞬映る"のを防ぐ（FadeOutで通常に消す）。
        _cur_sec = spans[i][0].get("section")
        _next_sec = spans[imaged[k + 1][0]][0].get("section") if (k + 1 < len(imaged)) else None
        _same_section = (_next_sec is not None) and (_next_sec == _cur_sec) and (f1 < _ed_start)
        _ov = int(FPS * 0.28) if _same_section else 0
        _fadeout = 0.0 if _same_section else 0.25
        _clen = (f1 - f0) + _ov
        _ln = spans[i][0]; _kw = str(_ln.get("image_keyword", ""))
        _summary = _ln.get("summary")                 # まとめ行＝Geminiが summary:[{head,sub},...] を持たせたら「まとめノート」に差し替え
        if isinstance(_summary, list) and _summary:
            _mt = (_ln.get("card_text") or {}).get("title") if isinstance(_ln.get("card_text"), dict) else None
            _mn = make_matome_note(_mt or "今日のまとめ", _summary)
            if _mn: im = _mn
        elif _kw in COMPOSITIONS:                     # 部品合成＝模式図＋実構造(PDB/AlphaFold)の2段構え。正確な図をこちらで組む
            _cf = compose_figure(COMPOSITIONS[_kw])
            if _cf: im = _cf
        iw, ih = imgsize(im)
        # 教科書ラベル(pins)／ヨウ素凡例(iodine_legend)を生画像へ焼き込む（ケンバーンズ追従・座標は生画像基準）
        # ※compose(合成図)時は元画像用のpins座標が合わないのでskip（合成図は自前の模式図＋実構造で説明）
        # 比喩・たとえ絵(analogy/lego等)は"特定パーツ"が存在しない＝pins(矢印)を刺すと誤解を招くので出さない
        _is_analogy = any(kw in _kw for kw in ("analogy", "lego", "vacuum", "spark_plug"))
        _pins = None if (_kw in COMPOSITIONS or _is_analogy) else (_ln.get("pins") if isinstance(_ln.get("pins"), list) else None)
        # 合成図/比喩絵は凡例が重複＆キャプションと衝突するので付けない（比喩の紫球は「ヨウ素」と限らない）
        _leg = (any(key in _kw for key in IODINE_LEGEND_KEYS)) and not _kw.startswith("disclaimer") and (_kw not in COMPOSITIONS) and not _is_analogy
        disp = make_annotated_card(im, pins=_pins, iodine_legend=_leg) if (_pins or _leg) else im
        # 図解判定：ファイル名 exp_* もしくは 全画面設計(幅≥1600の16:9)。→ 細枠の大型スライドカードで大きく表示
        is_diag = Path(im).stem.startswith("exp_") or (iw >= 1600 and 1.70 <= iw/ih <= 1.82)
        if is_diag:
            # 左に用語解説(term_gloss)/豆知識(trivia)パネルが出る行は、diagカードを右寄せ枠にしてパネルとのかぶりを回避
            _has_panel = bool(_ln.get("term_gloss")) or bool(_ln.get("trivia")) or bool(_ln.get("supplement") or _ln.get("補足"))
            _box = DIAG_PX_PANEL if _has_panel else DIAG_PX
            _cx, _cy = (dpcx, dpcy) if _has_panel else (dcx, dcy)
            card = make_slide_card(disp); cw, ch = imgsize(card)
            z = round(min(_box[2]/cw, _box[3]/ch)*100.0, 1)
            _dci = image_item(card, f0, _clen, L_CARD, _cx, _cy, z, fade=0.25); _dci["FadeOut"] = _fadeout
            items.append(_dci)
            diag_ranges.append((f0, f1))
        else:
            # 通常カード＋ケンバーンズ（ゆっくり寄り＋軽いパン・向き交互で単調回避）。微量＝付けすぎない。
            # 後載せ文字が出る側だけ暗グラデを付ける（pins図＝上帯なし＝pinsが沈まない／合成図＝上下なし）。overlay抑制ロジックと一致させる
            _ct2 = _ln.get("card_text") if isinstance(_ln.get("card_text"), dict) else {}
            _show_title = bool(_ct2.get("title") or _ln.get("board_title")) and (_kw not in COMPOSITIONS) and not _pins
            # pins図は下帯もオフ（pinsが下端にも来て沈むため）。キャプションは自前の黒フチで可読
            _show_cap = bool(_ct2.get("caption")) and (_kw not in COMPOSITIONS) and not _pins
            z = round(min(CARD_PX[2]/iw, CARD_PX[3]/ih)*100.0, 1)
            ci = image_item(make_framed_card(disp, top_band=_show_title, bot_band=_show_cap), f0, _clen, L_CARD, ccx, ccy, z, fade=0.25)
            ci["FadeOut"] = _fadeout
            _d = 1 if (k % 2 == 0) else -1
            ci["Zoom"] = anim2(z, round(z * 1.055, 1))
            ci["X"] = anim2(ccx - 9*_d, ccx + 9*_d)
            ci["Y"] = anim2(ccy + 6, ccy - 6)
            items.append(ci)
    n_img = len(imaged)
    unmatched = [(ln["id"], ln["image_keyword"]) for ln, *_ in spans
                 if ln.get("image_keyword") and not str(ln["image_keyword"]).startswith("disclaimer") and not resolve_image(ln)]

    # チョーク注釈：board_title=見出し(大・明るい金) / board_bullets=補足(白)。連続同一はまとめてトピック持続
    hx, hy = px_center(58, 508)      # 見出し位置＝左カラム（用語解説の下・小立ち絵の上）。右の大カードと非干渉
    bxx, byy = px_center(58, 566)    # 箇条書き位置（左カラム）
    i = 0 if SHOW_BOARD_CHALK else len(spans)   # 全画面カード方針＝チョーク見出し/箇条書きは出さない
    while i < len(spans):
        ln = spans[i][0]; bt = ln.get("board_title"); bb = ln.get("board_bullets") or []
        if not (bt or bb):
            i += 1; continue
        j = i
        while j+1 < len(spans) and spans[j+1][0].get("board_title") == bt and (spans[j+1][0].get("board_bullets") or []) == bb:
            j += 1
        # トーク区間(オープニング/エンディング)は黒板注釈を出さない（背景装飾＋フックと三重にかぶるため）
        if ln.get("section") in ("オープニング", "エンディング"):
            i = j + 1; continue
        f0 = spans[i][3]; f1 = spans[j+1][3] if j+1 < len(spans) else main_end
        f0 = max(f0, first_card_f)          # カードが出るまで注釈(文字)は出さない＝「文字だけ」状態を回避
        if f1 <= f0:
            i = j + 1; continue
        if bt:
            hf = 42
            _tw = ImageDraw.Draw(Image.new("RGBA", (8, 8))).textlength(str(bt), font=_ttf(38))
            if _tw > 560: hf = max(26, int(38 * 560 / _tw))    # 左カラム幅560内に収める
            else: hf = 38
            items.append(text_item(bt, f0, f1-f0, L_TITLE, hx, hy, size=hf, basepoint="LeftTop",
                                   color="#FFFFEC66", style_color="#FF0A2016", maxw=560, fade=0.2))
            ul = make_heading_underline(bt, hf); uw, uh = imgsize(ul)
            items.append(image_item(ul, f0, f1-f0, L_TITLE, hx + uw/2, hy + int(hf*1.25), 100.0, fade=0.2))
        if bb:
            bf0 = min(f0 + 24, f1 - 1)   # 見出しの少し後(0.4s)に箇条書き＝カード+見出し+箇条書きが一度に出て情報過多になるのを緩和
            btxt = "\n".join(wrap_bullet(b) for b in bb)
            items.append(text_item(btxt, bf0, f1-bf0, L_TITLE, bxx, byy+14, size=30, basepoint="LeftTop",
                                   color="#FFFFFFFF", style_color="#FF0A2016", maxw=560, fade=0.2))
        i = j + 1

    # ============ 動的文字後載せ（文字なしカード画像の上に card_text を重ねる）============
    # Gemini生成の文字なし画像に、card_text(title/caption)をYMM4テキストで後載せ。サイズは下記定数で調整可。
    CARD_TITLE_SIZE = 48.0   # カード上部タイトル
    CARD_CAP_SIZE   = 34.0   # カード下部キャプション
    _card_top = CARD_PX[1]                    # px（カード上端）
    _card_bot = CARD_PX[1] + CARD_PX[3]       # px（カード下端）
    _card_maxw = int(CARD_PX[2] * 0.86)
    for k, (i, im) in enumerate(imaged):
        ln = spans[i][0]
        if ln.get("section") in ("オープニング", "エンディング", "免責"): continue
        f0 = spans[i][3]
        f1 = spans[imaged[k+1][0]][3] if k+1 < len(imaged) else main_end
        f1 = min(f1, _ed_start)                          # 後載せ文字もED区間へはみ出さない
        if f1 <= f0: continue
        ct = ln.get("card_text") if isinstance(ln.get("card_text"), dict) else {}
        title = ct.get("title") or ln.get("board_title")
        caption = ct.get("caption")
        # まとめ等でキャプションが箇条書きの1個目だけ（例「① 甲状腺＝…」）だと番号が宙に浮く→先頭の①②③等マーカーを除去
        if caption:
            # 先頭の箇条書きマーカーのみ除去（①-⑳、または「1.」「1)」「1、」等の"番号＋区切り"）。"20g"等の裸の数字は消さない
            caption = re.sub(r"^[\s　]*(?:[①-⑳]+|[0-9]+[\.\)．、])[\s　]*", "", str(caption))
        # 自己ラベル型カードは後載せ見出しが図内ラベル/pinsと衝突する→抑制。
        #  ・合成図(COMPOSITION)＝見出しもキャプションも図が自己完結＝両方消す
        #  ・pins図＝pinsがラベルなので上部の見出しだけ消す（キャプションは下部で干渉少なく残す）
        _kw_t = str(ln.get("image_keyword", ""))
        if _kw_t in COMPOSITIONS or (isinstance(ln.get("summary"), list) and ln.get("summary")):
            title = None; caption = None            # 合成図＝図が自己完結／まとめ＝黒板に直接タイトル+要点があるので後載せ見出し・キャプションは出さない（重複防止）
        elif isinstance(ln.get("pins"), list) and ln.get("pins"):
            title = None
        if title:
            items.append(text_item(str(title), f0, f1 - f0, L_TITLE, ccx, (_card_top + 44) - H/2,
                                   size=CARD_TITLE_SIZE, basepoint="CenterTop",
                                   color="#FFFFEC66", style_color="#FF000000", maxw=_card_maxw, fade=0.2, thickness=6.0))
        if caption:
            items.append(text_item(str(caption), f0, f1 - f0, L_TITLE, ccx, (_card_bot - 24) - H/2,
                                   size=CARD_CAP_SIZE, basepoint="CenterBottom",
                                   color="#FFFFFFFF", style_color="#FF000000", maxw=_card_maxw, fade=0.2, thickness=5.0))

    # ============ 小出しイラスト（cut_icons・セリフ連動で順次カットイン）============
    # 各行の cut_icons を、行の尺を等分して1枚ずつ順に表示（非累積＝入れ替わり）。位置はカード左下寄り。
    SHOW_CUT_ICONS = False   # 切り出しは「微妙」（ユーザー指摘）→無効。代わりにポインタ講義スタイル(赤枠＋「これ」)を検討中＝Geminiのpin座標待ち。
    L_CUT = 10; CUT_H = 240.0; _cut_cx, _cut_cy = 760, 600   # レイヤ10(立ち絵より前・字幕より後)／カード上に詳細ズーム風で重ねる
    _cut_focal = [(0.5, 0.42), (0.34, 0.5), (0.66, 0.5), (0.5, 0.62)]
    n_cut = 0
    for _i, (ln, spk, wav, f, length) in enumerate(spans):
        cuts = ln.get("cut_icons") or []
        if not (SHOW_CUT_ICONS and cuts):
            continue
        _cardp = resolve_image(ln)
        if not _cardp:
            continue
        n = len(cuts); seg = length / n
        for ci in range(n):
            cf = int(f + ci * seg); ce = int(f + (ci + 1) * seg) if ci < n - 1 else int(f + length)
            _fx, _fy = _cut_focal[ci % len(_cut_focal)]
            cimg = make_cut_from_card(_cardp, f"{ln['id']:03d}_{ci}", _fx, _fy)
            z = round(CUT_H / imgsize(cimg)[1] * 100.0, 1)
            items.append(image_item(cimg, cf, max(1, ce - cf), L_CUT, _cut_cx - W/2, _cut_cy - H/2, z, fade=0.2))
            n_cut += 1

    # ============ 追加演出：チャプター進行バー / 黒板消しワイプ / ズーム強調 ============
    # チャプター進行バー（最上部・現在章ハイライト）
    # 章名は実データから前方一致で拾う（第1話="第1章" / 第2話="第1章：推論と探索" 等の接尾辞付きにも対応）
    chap_secs = []
    for (ln, *_r) in spans:
        s = ln.get("section") or ""
        if re.match(r"第\d+章", s) and s not in chap_secs: chap_secs.append(s)
    # 章の『一言ラベル』：chapter_chip（Gemini提供・最優先）→ section名から核キーワード自動抽出。
    # ※旧board_title長文由来をやめ、チャプターバーの見切れ（長文）を解消（ユーザー指摘「一言タイトルに」）。
    chip_by_sec = {}
    for (ln, *_r) in spans:
        sec = ln.get("section")
        if sec in chap_secs and sec not in chip_by_sec and ln.get("chapter_chip"):
            chip_by_sec[sec] = str(ln["chapter_chip"]).strip()
    chap_labels = [chip_by_sec.get(sec) or _chap_chip(sec) for sec in chap_secs]
    n_chap = n_wipe = n_zoom = 0
    # 上部チャプター進行バー復活（ユーザー要望2026-08-10）。資料を下げて空いた最上部に配置＝現在章を金でハイライト。
    # 章名は途切れない（make_chapterbarが収まる最大フォントを自動選択・「…」省略なし）。ラベルはchapter_chip(Gemini提供)優先。
    if chap_labels:
        for ci_idx, sec in enumerate(chap_secs):
            cbar = make_chapterbar(chap_labels, ci_idx); _cbw, _cbh = imgsize(cbar)
            _cranges = _section_ranges(sec)
            for rf, re_ in _cranges:
                items.append(image_item(cbar, rf, max(1, re_ - rf), L_CHAP, *px_center(W/2, 12 + _cbh/2), 100.0, fade=0.2)); n_chap += 1
            # 章開始時にその章のキーワードを一瞬ポップ＝章タイトルの announcement（ユーザー要望2026-08-11でOFF）
            if SHOW_KEYWORD_POP and _cranges:
                _kwp = make_keyword_pop(str(chap_labels[ci_idx])[:12])
                _kf = _cranges[0][0]; _kl = int(FPS * 1.5)
                _ki = image_item(_kwp, _kf, _kl, 10, 0, 380 - H/2, 100.0, fade=0.25)
                _ki["Zoom"] = anim2(52, 104)   # スケールイン
                items.append(_ki)

    # 黒板消しワイプ（章=section切替の時だけ。※絵本ペースで毎行画像が変わっても、ワイプは章頭のみ＝賑やかさ回避）
    dust = make_chalkdust(); WIPE_LEN = 22
    for k, (i, im) in enumerate(imaged):
        if k == 0: continue
        if spans[i][0].get("section") == spans[imaged[k-1][0]][0].get("section"): continue  # 同一章内の絵替えではワイプしない
        f0 = spans[i][3]
        items.append(image_item(dust, max(0, f0 - WIPE_LEN//2), WIPE_LEN, L_WIPE, 0, 0, 100.0, fade=0.12)); n_wipe += 1

    # カメラズーム強調（驚きセリフで中央カードへ軽くズームイン＝一瞬の拡大コピー）
    card_ranges = []
    for k, (i, im) in enumerate(imaged):
        cf0 = spans[i][3]; cf1 = min(spans[imaged[k+1][0]][3] if k+1 < len(imaged) else main_end, _ed_start)
        if cf1 <= cf0: continue
        iw, ih = imgsize(im); zc = round(min(CARD_PX[2]/iw, CARD_PX[3]/ih)*100.0, 1)
        card_ranges.append((cf0, cf1, im, zc))
    ZP_LEN = 30
    for (ln, spk, wav, f, length) in spans:
        if ln.get("emotion") != "驚き": continue
        for (cf0, cf1, im, zc) in card_ranges:
            if cf0 <= f < cf1:
                items.append(image_item(make_framed_card(im), f, min(ZP_LEN, length), L_ZOOM, ccx, ccy, round(zc*1.12, 1), fade=0.12)); n_zoom += 1
                break

    # 豆知識ポップアップ（trivia・右上付箋）：読む時間を確保（1行尺だと早すぎ消えるため最低表示時間を設け、
    #   次の付箋/写真/終端の手前まで持続）。一度に大量に出ないよう位置は右上固定・重なりは打ち切りで回避。
    def _read_len(txt):
        return int(FPS * max(5.0, min(12.0, 3.5 + len(str(txt)) / 5.0)))   # 文字数に応じ5〜12秒（早すぎ消え対策で延長）
    _photo_frames = sorted(fr for (l2, s2, w2, fr, ln2) in spans
                           if l2.get("extra_photo") and l2.get("id") not in PHOTO_SKIP_IDS)
    # 用語解説/豆知識が全身立ち絵(トーク/オープニング)区間に食い込むと重なるため、全身区間の手前で表示を切る。
    _big_starts = sorted(spans[i][3] for i in range(len(spans)) if _pos_for(i, spans[i][0]) is LS_POS_BIG)
    def _clip_big(_s, _e):
        for _bs in _big_starts:
            if _s < _bs < _e: return _bs
        return _e
    # 話題(section)が変わるフレーム境界。用語解説/豆知識は「次が出るか話題が変わるまで」持続させる（ユーザー要望）。
    _sec_bounds = []; _prev_sec = object()
    for (_l2, _s2, _w2, _fr2, _len2) in spans:
        _sc = _l2.get("section")
        if _sc != _prev_sec: _sec_bounds.append(_fr2)
        _prev_sec = _sc
    def _sec_end(_of):                    # _of以降で最初のsection境界（=話題が変わるフレーム）
        for _b in _sec_bounds:
            if _b > _of: return _b
        return main_end
    _triv = []
    for _i, (ln, spk, wav, f, length) in enumerate(spans):
        tv = ln.get("trivia")
        _photo_shown = ln.get("extra_photo") and ln.get("id") not in PHOTO_SKIP_IDS
        if not tv or ln.get("section") in ("オープニング", "エンディング") or _photo_shown or _pos_for(_i, ln) is LS_POS_BIG: continue  # トーク/全身立ち絵区間・写真表示行は出さない
        term = tv.get("term") if isinstance(tv, dict) else str(tv)
        note = tv.get("note", "") if isinstance(tv, dict) else ""
        _triv.append((f, term, note))
    POPUP_DELAY = int(FPS * 1.0)   # 「機を見計らって出す」：トピック頭で一気に出さず約1.0秒後に登場（表示時間確保のため1.5→1.0）
    # 用語解説の表示区間＋高さを先に算出（豆知識の配置判定用）
    _glraw = []
    for _gi, (ln, spk, wav, f, length) in enumerate(spans):
        tg = ln.get("term_gloss")
        if not tg or ln.get("section") in ("オープニング", "エンディング") or _pos_for(_gi, ln) is LS_POS_BIG: continue
        if ln.get("trivia"): continue
        _ab = tg.get("abbr", "") if isinstance(tg, dict) else str(tg)
        _fu = tg.get("full", "") if isinstance(tg, dict) else ""
        _no = tg.get("note", "") if isinstance(tg, dict) else ""
        _glraw.append((f, _ab, _fu, _no))
    # 用語解説・豆知識は「次のパネル(用語/豆どちらでも)が出る or 話題変化」で終了＝2枚同時表示による左カラムの重なりを防止（ユーザー指摘）。
    # 補足パネル（supplement・台詞に無い深掘り／用語解説・豆知識が無い行のみ＝1行1枚）
    _supraw = []
    for _si, (ln, spk, wav, f, length) in enumerate(spans):
        sp = ln.get("supplement") or ln.get("補足")
        if not sp or ln.get("section") in ("オープニング", "エンディング") or _pos_for(_si, ln) is LS_POS_BIG: continue
        # 補足は用語解説/豆知識と共存可（下段にスタック表示）
        _st = sp.get("term") if isinstance(sp, dict) else str(sp)
        _sn = sp.get("note", "") if isinstance(sp, dict) else ""
        _supraw.append((f, _st, _sn))
    # 実構造補足（オプションA）＝COMPOSITIONにinset_supplementがある行で、用語解説の"後"に切替表示（同じ左上枠を時間差で使う＝重なり回避）
    _structraw = []
    _imgframes = sorted([spans[ii][3] for (ii, _im) in imaged]) + [_ed_start]
    for _ci, (ln, spk, wav, f, length) in enumerate(spans):
        _cmp = COMPOSITIONS.get(str(ln.get("image_keyword", "")))
        if not _cmp or not _cmp.get("inset_supplement"): continue
        if ln.get("section") in ("オープニング", "エンディング") or _pos_for(_ci, ln) is LS_POS_BIG: continue
        _cend = min(next((fr for fr in _imgframes if fr > f), _ed_start), _ed_start)
        _dur = max(1, _cend - f)
        _sstart = min(f + int(_dur * 0.6), _cend - int(FPS * 2.2))   # 用語解説にカード尺の約6割、実構造は後半(最低約2.2s)
        _sstart = max(_sstart, f + int(FPS * 1.5))
        _isup = _cmp["inset_supplement"]
        _structraw.append((_sstart, str(Path(DB) / _cmp["inset"]),
                           _isup.get("term", "実際の構造"), _isup.get("note", ""), _cmp.get("inset_cap", "")))
    _panel_starts = sorted([_g[0] for _g in _glraw] + [_tv[0] for _tv in _triv] + [_s[0] for _s in _supraw] + [_x[0] for _x in _structraw])
    def _next_panel(_of):
        for _b in _panel_starts:
            if _b > _of: return _b
        return main_end
    # 補足の表示区間を先に算出（用語解説/豆知識の上端を「2枚同時なら上へ」判定するため）
    _sup_iv = []
    for _si2, (f, term, note) in enumerate(_supraw):
        _nx = _supraw[_si2 + 1][0] if _si2 + 1 < len(_supraw) else main_end
        _lim = min(_nx, main_end)
        _sf = min(f + POPUP_DELAY, max(f, _lim - int(FPS * 2.0)))
        _se = _clip_big(_sf, min(_lim, _sec_end(f), _next_panel(f)))
        if _se > _sf: _sup_iv.append((_sf, _se))
    def _has_sup(a, b): return any(s < b and a < e for (s, e) in _sup_iv)   # [a,b)に補足が重なるか（2枚同時＝上へずらす条件）
    _gl_iv = []                                                   # (開始f, 終了f, パネル高px, 上端Y)
    for _t, (f, _ab, _fu, _no) in enumerate(_glraw):
        _nx = _glraw[_t + 1][0] if _t + 1 < len(_glraw) else main_end
        _lim = min(_nx, main_end)
        _gf = min(f + POPUP_DELAY, max(f, _lim - int(FPS * 2.0)))
        _ge = _clip_big(_gf, min(_lim, _sec_end(f), _next_panel(f)))   # 次パネル/話題変化で終了
        _gtopY = PANEL_TOP_STACK if _has_sup(_gf, _ge) else PANEL_TOP   # 補足と同時なら上へ
        _gl_iv.append((_gf, _ge, imgsize(make_termgloss(_ab, _fu, _no))[1], _gtopY))
    n_trivia = 0
    _tv_iv = []                                                  # (開始f, 終了f, 下端y)＝補足を下段スタックする基準
    for t, (f, term, note) in enumerate(_triv):
        nxt = _triv[t + 1][0] if t + 1 < len(_triv) else main_end
        npho = next((pf for pf in _photo_frames if pf > f), main_end)
        lim = min(nxt, npho, main_end)
        tf = min(f + POPUP_DELAY, max(f, lim - int(FPS * 2.0)))    # 遅延登場（ただし最低2sは出せる位置に）
        end = _clip_big(tf, min(lim, _sec_end(f), _next_panel(f)))   # 次パネル(用語/豆)/写真/話題変化/全身立ち絵まで持続＝2枚同時の重なり防止
        _sk = make_sticky(term, note); _sw, _sh = imgsize(_sk)
        # 補足が同時なら上端を上へ(72)。用語解説が同時に出ている時はその下段へ。立ち絵に被らないよう下端は頭打ち。
        _base = PANEL_TOP_STACK if _has_sup(tf, end) else PANEL_TOP
        _gtop = _base
        for (_gs, _ge2, _gh, _gtopY) in _gl_iv:
            if _gs < end and tf < _ge2: _gtop = max(_gtop, _gtopY + _gh + 28)   # パネル間隔（12→28）
        _ty = _base if _gtop == _base else max(_base, min(_gtop, 852 - _sh))
        items.append(image_item(_sk, tf, max(1, end - tf), L_CHAP, *px_center(45 + _sw/2, _ty + _sh/2), 100.0, fade=0.25)); n_trivia += 1  # Y=補足/用語解説連動（72 or 105 or 下段）
        _tv_iv.append((tf, end, _ty + _sh))

    # 追加写真ペタッ（各行 extra_photo:{file,pos,tilt} があれば既存カードに重ねて貼る＋貼付SE）。無ければ0
    n_photo = 0; photo_se = []
    for i, (ln, spk, wav, f, length) in enumerate(spans):
        ep = ln.get("extra_photo")
        if not ep or ln.get("id") in PHOTO_SKIP_IDS:   # 重複する追加写真は出さない
            continue
        fn2 = ep.get("file", "") if isinstance(ep, dict) else str(ep)
        p = find_img(fn2)
        if not p.exists():
            continue
        pos = PHOTO_POS.get(ep.get("pos", "card_br") if isinstance(ep, dict) else "card_br", PHOTO_POS["card_br"])
        tilt = int(ep.get("tilt", -6)) if isinstance(ep, dict) else -6
        seg = (spans[i+1][3] - f) if i+1 < len(spans) else (main_end - f)
        # キャプション：extra_photo.name（人名）＋ years（生没年）／単独 caption も可。「何の写真か」を明示
        cap = None
        if isinstance(ep, dict):
            nm = ep.get("name") or ep.get("caption"); yr = ep.get("years")
            if nm: cap = f"{nm}（{yr}）" if yr else str(nm)
        photo = make_photo_paste(p, tilt, cap)
        iw, ih = imgsize(photo); z = round(PHOTO_H/ih*100.0, 1)
        items.append(image_item(photo, f, seg, L_EXPR, *px_center(1600, 330), z, fade=0.28))  # 右上に大きく（豆知識と同じ位置）
        photo_se.append(f)                      # 貼付タイミングのSE
        n_photo += 1

    # 左スペースの用語解説パネル（term_gloss・左上）：読む時間を確保（最低表示時間・次の用語/終端の手前まで持続）
    _gl = []
    for _i, (ln, spk, wav, f, length) in enumerate(spans):
        tg = ln.get("term_gloss")
        if not tg or ln.get("section") in ("オープニング", "エンディング") or _pos_for(_i, ln) is LS_POS_BIG:
            continue
        if ln.get("trivia"):        # 同じ行に豆知識があれば重複回避で用語解説は出さない
            continue
        abbr = tg.get("abbr", "") if isinstance(tg, dict) else str(tg)
        full = tg.get("full", "") if isinstance(tg, dict) else ""
        note = tg.get("note", "") if isinstance(tg, dict) else ""
        _gl.append((f, abbr, full, note))
    n_gloss = 0
    for t, (f, abbr, full, note) in enumerate(_gl):
        nxt = _gl[t + 1][0] if t + 1 < len(_gl) else main_end
        lim = min(nxt, main_end)
        gf = min(f + POPUP_DELAY, max(f, lim - int(FPS * 2.0)))    # 機を見計らって遅延登場（トピック頭の情報過多を回避）
        end = _clip_big(gf, min(lim, _sec_end(f), _next_panel(f)))   # 次パネル(用語/豆)/話題変化/全身立ち絵まで持続＝2枚同時の重なり防止
        gimg = make_termgloss(abbr, full, note); gw, gh = imgsize(gimg)
        _gtopY = PANEL_TOP_STACK if _has_sup(gf, end) else PANEL_TOP   # 補足と同時なら上へ(72)、単独なら105
        items.append(image_item(gimg, gf, max(1, end - gf), L_CHAP, *px_center(45 + gw/2, _gtopY + gh/2), 100.0, fade=0.3))  # 用語解説 X45（2枚同時は上ずらし）
        n_gloss += 1
    # 補足パネル（スカイ・左カラム）＝用語解説/豆知識が同時に出ていればその下段へスタック（無ければY105）
    n_sup = 0
    for t, (f, term, note) in enumerate(_supraw):
        nxt = _supraw[t + 1][0] if t + 1 < len(_supraw) else main_end
        lim = min(nxt, main_end)
        sf = min(f + POPUP_DELAY, max(f, lim - int(FPS * 2.0)))
        end = _clip_big(sf, min(lim, _sec_end(f), _next_panel(f)))
        simg = make_supplement(term, note); sw, sh = imgsize(simg)
        _sty = PANEL_TOP
        for (_gs, _ge2, _gh, _gtopY) in _gl_iv:                  # 用語解説の下（用語解説は2枚同時で上ずらし済＝その下端の下）
            if _gs < end and sf < _ge2: _sty = max(_sty, _gtopY + _gh + 28)   # パネル間隔（12→28）
        for (_ts, _te2, _tbot) in _tv_iv:                        # 豆知識の下
            if _ts < end and sf < _te2: _sty = max(_sty, _tbot + 28)
        _sty = PANEL_TOP if _sty == PANEL_TOP else max(PANEL_TOP_STACK, min(_sty, 852 - sh))   # 立ち絵回避で下端頭打ち
        items.append(image_item(simg, sf, max(1, end - sf), L_CHAP, *px_center(45 + sw/2, _sty + sh/2), 100.0, fade=0.3))
        n_sup += 1
    # 実構造補足（オプションA）＝用語解説の後に切替表示（同じ左上枠）。startは既に用語解説の後になるよう遅延済み
    n_struct = 0
    for t, (sf0, img, term, note, cap) in enumerate(_structraw):
        nxt = _structraw[t + 1][0] if t + 1 < len(_structraw) else main_end
        end = _clip_big(sf0, min(nxt, main_end, _sec_end(sf0), _next_panel(sf0)))
        if end <= sf0: continue
        stimg = make_struct_panel(img, term, note, cap); stw, sth = imgsize(stimg)
        items.append(image_item(stimg, sf0, max(1, end - sf0), L_CHAP, *px_center(45 + stw/2, 105 + sth/2), 100.0, fade=0.3))
        n_struct += 1

    # ============ 音響：BGM（場面別ループ）＋ SE（イベント連動）＋ サムネ連動フック ============
    n_bgm = n_se = 0
    # BGM：連続する bgm_track 単位で1本ずつ・低音量ループ（場面切替でフェード交代）。OP/EDの動画音声とは重ねない
    bi = 0
    while bi < len(spans):
        trk = spans[bi][0].get("bgm_track")
        bj = bi
        while bj+1 < len(spans) and spans[bj+1][0].get("bgm_track") == trk:
            bj += 1
        p = bgm_path(trk)
        if p and p.exists():
            f0 = spans[bi][3]
            f1 = spans[bj+1][3] if bj+1 < len(spans) else main_end
            items.append(audio_item(p, f0, f1-f0, layer=L_BGM, volume=BGM_VOL, loop=True, fade_in=0.6, fade_out=0.8))
            n_bgm += 1
        bi = bj + 1

    # OP/ED 専用BGM：OP動画区間(0..OP_LEN)とED動画区間(main_end..total)は動画が無音なので専用曲を敷く。
    #   専用ファイル(bgm_op_intro.mp3 / bgm_ed_outro.mp3)があれば使用、無ければ雑談BGMで代用。
    #   時間帯が本編BGM(OP_LEN..main_end)と重ならないので同レイヤL_BGMでOK。
    op_bgm = bgm_path("bgm_op_intro.mp3")
    if not op_bgm.exists(): op_bgm = bgm_path("bgm_op_talk.mp3")
    if op_bgm.exists() and OP_LEN > 0:
        items.append(audio_item(op_bgm, 0, OP_LEN, layer=L_BGM, volume=OPED_BGM_VOL, loop=True, fade_in=0.3, fade_out=0.6)); n_bgm += 1
    ed_bgm = bgm_path("bgm_ed_outro.mp3")
    if not ed_bgm.exists(): ed_bgm = bgm_path("bgm_op_talk.mp3")
    if ed_bgm.exists() and ED_LEN > 0:
        items.append(audio_item(ed_bgm, main_end, ED_LEN, layer=L_BGM, volume=OPED_BGM_VOL, loop=True, fade_in=0.6, fade_out=0.8)); n_bgm += 1

    # SE：カード=se_card（章=section切替の時だけ。絵本ペースで毎行鳴らさない）/ チョーク注釈=se_chalk / ジャンプ=se_jump / 驚き=se_impact
    se_specs = [(spans[i][3], "se_card.wav") for k, (i, _im) in enumerate(imaged)
                if k == 0 or spans[i][0].get("section") != spans[imaged[k-1][0]][0].get("section")]
    si = 0
    while si < len(spans):
        ln = spans[si][0]; bt = ln.get("board_title"); bb = ln.get("board_bullets") or []
        if not (bt or bb):
            si += 1; continue
        sj = si
        while sj+1 < len(spans) and spans[sj+1][0].get("board_title") == bt and (spans[sj+1][0].get("board_bullets") or []) == bb:
            sj += 1
        if ln.get("section") not in ("オープニング", "エンディング"):   # 注釈を出す区間だけチョーク音
            se_specs.append((spans[si][3], "se_chalk.wav"))
        si = sj + 1
    for (ln, spk, wav, f, length) in spans:
        mk = EXPR_MOTION.get(ln.get("expression")) or MOTION.get(ln.get("emotion", "平静"))
        if mk == "jump": se_specs.append((f, "se_jump.wav"))
        if ln.get("emotion") == "驚き": se_specs.append((f, "se_surprise.wav"))
    for fr in photo_se:                              # 追加写真の貼付音（ペタッ）
        se_specs.append((fr, "se_card.wav"))
    # 2レイヤの占有管理で同時刻SEの重なりを回避（両方埋まっていれば間引く）
    se_layers = [[L_SE1, -1], [L_SE2, -1]]   # [レイヤ, 最終終了フレーム]
    for fr, fn in sorted(se_specs, key=lambda t: t[0]):
        p = SEDIR / fn
        if not p.exists(): continue
        ln_f = max(1, round((wdur(p) or 0.5) * FPS))
        for row in se_layers:
            if row[1] <= fr:
                items.append(audio_item(p, fr, ln_f, layer=row[0], volume=SE_VOL, loop=False, fade_out=0.05))
                row[1] = fr + ln_f; n_se += 1
                break

    # サムネ連動フック：オープニング区間に大チョーク見出し（黒板だけで寂しい間を埋める）
    hook = (lines[0].get("thumb_hook_text") or "").strip()
    _opr = _section_ranges("オープニング")
    if hook and _opr:
        hf0, hf1 = _opr[0]
        hy = px_center(0, 372)[1]
        items.append(text_item(hook, hf0, hf1-hf0, L_HOOK, 0.0, hy, size=50,
                               color="#FFFFE14D", style_color="#FF13312A", maxw=1480, fade=0.3))

    # アイキャッチ区間は他の視覚要素を出さない（クリーンな中割り＝タイトル/黒板注釈/字幕/立ち絵/カード等の映り込み防止）。
    #   背景(L_BG)とアイキャッチ動画と音声系(BGM/SE/Voice)は残し、視覚アイテムは区間外だけに分割。
    if eyecatch_frame is not None:
        ef2, ee2 = eyecatch_frame, eyecatch_frame + EYE_LEN
        clipped = []
        for it in items:
            t = it.get("$type", ""); fp = (it.get("FilePath") or "").lower()
            f0 = it.get("Frame", 0); l0 = it.get("Length", 0); f1 = f0 + l0
            if ("Audio" in t or "Voice" in t or it.get("Layer", 0) == L_BG
                    or "eyecatch" in fp or f1 <= ef2 or f0 >= ee2):
                clipped.append(it); continue
            if f0 < ef2:                                   # 区間より前の部分を残す
                a = copy.deepcopy(it); a["Length"] = ef2 - f0; clipped.append(a)
            if f1 > ee2:                                   # 区間より後の部分を残す
                b = copy.deepcopy(it); b["Frame"] = ee2; b["Length"] = f1 - ee2; clipped.append(b)
        items = clipped

    tl["Items"] = items; tl["Length"] = total; tl["MaxLayer"] = MAX_LAYER; tl["CurrentFrame"] = 0
    with open(out, "w", encoding="utf-8-sig") as fp:
        json.dump(proj, fp, ensure_ascii=False, indent=1)

    dur = total/FPS
    n_aud = 0 if noaudio else sum(1 for s in spans if s[2].exists())
    eye = "有" if eyecatch_frame is not None else "無"
    print(f"行{len(lines)} item{len(items)} 画像{n_img} 音声{n_aud} BGM{n_bgm} SE{n_se} アイキャッチ{eye} チャプター{n_chap} ワイプ{n_wipe} ズーム{n_zoom} 豆知識{n_trivia} 追加写真{n_photo} 用語{n_gloss} 尺{dur:.1f}s({dur/60:.2f}分)")
    if unmatched: print("画像未解決:", unmatched)
    print("出力:", out)

if __name__ == "__main__":
    main()
