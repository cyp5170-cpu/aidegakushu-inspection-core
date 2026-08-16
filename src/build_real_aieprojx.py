# -*- coding: utf-8 -*-
"""
build_real_aieprojx.py ― A.I.VOICE2 正本(.aieprojx)のキャラクター名(character)完全切り替え修正
"""
import os
import sys
import re
import json
import copy
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def _arg_ep(default="02"):
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

ROOT = Path(__file__).resolve().parent.parent
_DIR = _arg_dir()
if _DIR:
    EP_ROOT = ROOT / _DIR
    _m = re.search(r"(\d+)", EP_ROOT.name); EP = (_m.group(1) if _m else "1").zfill(2)
else:
    EP = _arg_ep()
    EP_ROOT = ROOT / "episodes" / f"ep{EP}"
SCRIPT_JSON = EP_ROOT / "script.json"
OUTPUT_DIR = EP_ROOT / "output"

# パスはユーザーのホーム基準で構築（環境変数で上書き可・ユーザー名をハードコードしない）
_DESKTOP = Path(os.environ.get("AIGAKU_DESKTOP", Path.home() / "OneDrive" / "デスクトップ"))
TEMPLATE_AIE = os.environ.get("AIE_TEMPLATE", str(_DESKTOP / "projects" / "琴葉茜葵_設定学習データ" / "95_A.I.VOICE2プロジェクト" / "test3_感情注入済.aieprojx"))

# ============ 怪しい読みの矯正（事象登録・単一ソース= src/reading_dict.json）============
# 2区分：
#  ・dict         → A.I.VOICE2ユーザー辞書(user.wdic)へ登録（`py src/update_aivoice_dict.py`）。読みを恒久修正。
#  ・tts_replace  → A.I.VOICE2へ渡すテキストだけ置換（**字幕=script.json原文は不変**）。
#                   「英語（カナ）」の二重読みなど、辞書では消せないケース用。
# 詳細は 読み辞書_運用.md。
READING_DICT_FILE = Path(__file__).resolve().parent / "reading_dict.json"

def _load_tts_replace():
    reps = []
    try:
        d = json.load(open(READING_DICT_FILE, encoding="utf-8"))
        for e in (d.get("tts_replace", []) if isinstance(d, dict) else []):
            if e.get("find"):
                reps.append((e["find"], e.get("replace", "")))
        reps.sort(key=lambda x: -len(x[0]))   # 長い一致を優先（部分一致で崩れないように）
    except Exception as ex:
        print(f"[warn] tts_replace 読込失敗（置換なしで続行）: {ex}")
    return reps

TTS_REPLACE = _load_tts_replace()

def fix_tts(t: str) -> str:
    for a, b in TTS_REPLACE:
        t = t.replace(a, b)
    return t

# ============ プリフライト：読み対策(step0)の飛ばし検知 ============
# 台本(text)に誤読しやすい語（英字略語・『表記（かな）』二重読み）があるのに
# reading_dict.json 未対策なら、生成前に一覧を出して知らせる（手順飛ばし事故の再発防止）。
_ALWAYS_OK = {"AI", "PC", "OS", "NEC", "IBM", "CPU", "GPU"}  # ほぼ確実に正しく読める頻出語（誤警告の抑制）
_RE_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")                    # 英字略語・製品名（2文字以上）
_RE_FURIGANA = re.compile(r"[A-Za-z一-鿿ァ-ヶ]+（[ぁ-ゖァ-ヶー・\s]+）")  # 漢字/英字＋（かな）＝二重読み

def _load_reading_surfaces():
    """『対策済み/許容』の表記集合を返す（dict.surface＋tts_replace.find＋任意ok_asis）。"""
    known = set(_ALWAYS_OK)
    try:
        d = json.load(open(READING_DICT_FILE, encoding="utf-8"))
        for e in d.get("dict", []):
            if e.get("surface"): known.add(e["surface"])
        for e in d.get("tts_replace", []):
            if e.get("find"): known.add(e["find"])
        for s in d.get("ok_asis", []):    # 対策不要と確認済みの語（任意・単一ソースで抑制）
            if s: known.add(s)
    except Exception as ex:
        print(f"[warn] reading_dict.json 読込失敗（読みチェックは簡易のみ）: {ex}")
    return known

def _is_covered(token, known):
    return any(token in k or k in token for k in known)

def preflight_reading_check(lines, strict=False):
    """未対策の誤読候補を一覧提示。strict時は未対策があれば中断（sys.exit）。"""
    known = _load_reading_surfaces()
    latin, dbl = {}, {}
    for l in lines:
        t = l.get("text", ""); lid = l.get("id")
        for m in _RE_LATIN.finditer(t):
            tok = m.group()
            if not _is_covered(tok, known): latin.setdefault(tok, set()).add(lid)
        for m in _RE_FURIGANA.finditer(t):
            frag = m.group()
            if not _is_covered(frag, known): dbl.setdefault(frag, set()).add(lid)
    if not latin and not dbl:
        print("[preflight] 読みチェックOK（未対策の英字略語・二重読みは検出されず）")
        return
    print("=" * 70)
    print("⚠ [preflight] 読み対策(step0)が未反映の可能性（reading_dict.json 未登録）")
    if latin:
        print("  ● 英字略語/製品名（letter読み・崩れの恐れ）:")
        for tok, ids in sorted(latin.items(), key=lambda x: min(x[1])):
            print(f"     - {tok}  (id {', '.join(map(str, sorted(ids)))})")
    if dbl:
        print("  ● 『表記（かな）』＝括弧内も読む二重読みの恐れ:")
        for frag, ids in sorted(dbl.items(), key=lambda x: min(x[1])):
            print(f"     - {frag}  (id {', '.join(map(str, sorted(ids)))})")
    print("  → src/reading_dict.json に dict/tts_replace 追記 → update_aivoice_dict.py → A.I.VOICE2再起動")
    print("     対策不要な語は reading_dict.json の \"ok_asis\" に列挙で抑制可。")
    print("  ※tts_replace を足したら本スクリプト再実行が必要（生成時に焼き込むため）。")
    print("=" * 70)
    if strict:
        sys.exit("[abort] --strict 指定のため中断（読み対策後に再実行）。")

# ⚠A.I.VOICE2 sliderの volume/speed/pitch/emph は「0.0=標準(1.0倍)」のオフセット値。
#   GUI表示倍率 = 1.0 + 値。旧テーブルは1.1前後を入れていたため話速2.1倍/高さ2.0倍の“おかしい声”になっていた。
#   (speed_offset, emph_offset, style_key, style_val)。style_valは絶対値(0〜1)。
# 話速オフセット0.0=話速1.0倍（標準）。GUI倍率=1.0+値。高さ/音量は0.0(標準)固定、抑揚は控えめ。
EMOTION_RULE = {
    "akane": {
        "平静":   ( 0.00, 0.05, None, 0.0),
        "喜び":   ( 0.03, 0.12, "J", 0.45),
        "驚き":   ( 0.06, 0.16, "J", 0.45),
        "悲しみ": (-0.04, 0.00, "S", 0.45),
        "怒り":   ( 0.04, 0.12, "A", 0.40),
    },
    "aoi": {
        "平静":   ( 0.00, 0.05, None, 0.0),
        "喜び":   ( 0.03, 0.10, "J", 0.28),
        "驚き":   ( 0.05, 0.14, "J", 0.30),
        "悲しみ": (-0.04, 0.00, "S", 0.28),
        "怒り":   ( 0.03, 0.10, "A", 0.26),
    }
}

def main():
    print("Fixing speaker character assignment in .aieprojx...")
    if not os.path.exists(TEMPLATE_AIE):
        raise FileNotFoundError(f"Template {TEMPLATE_AIE} not found.")

    with open(TEMPLATE_AIE, "r", encoding="utf-8-sig") as f:
        template_json = json.load(f)

    with open(SCRIPT_JSON, "r", encoding="utf-8") as f:
        script_data = json.load(f)

    lines = script_data.get("lines", [])

    # step0の飛ばし検知（未対策の誤読候補を提示。--strict で未対策時に中断）
    preflight_reading_check(lines, strict=("--strict" in sys.argv))

    sample_items = template_json.get("textblocks", [])
    if not sample_items:
        raise ValueError("No textblocks found in template.")

    akane_sample = None
    aoi_sample = None

    for item in sample_items:
        char = item.get("character", "")
        if "茜" in char and not akane_sample:
            akane_sample = item
        elif "葵" in char and not aoi_sample:
            aoi_sample = item

    if not akane_sample:
        akane_sample = sample_items[0]
    if not aoi_sample:
        aoi_sample = sample_items[0]

    def make_block(spk, text, emotion):
        base_sample = akane_sample if spk == "akane" else aoi_sample
        item = copy.deepcopy(base_sample)
        item["character"] = "琴葉 茜(NV)" if spk == "akane" else "琴葉 葵(NV)"
        item["text"] = fix_tts(text)   # 字幕は原文のまま／TTSテキストだけ置換（二重読み等の回避）
        if "imkana" in item:           # 固定imkanaを削除して自動再読み上げ（辞書適用）を有効化
            del item["imkana"]
        speed, emph, style_key, style_val = EMOTION_RULE[spk].get(emotion, EMOTION_RULE[spk]["平静"])
        if "tuning" in item and "slider" in item["tuning"]:
            item["tuning"]["slider"]["speed"] = speed
            item["tuning"]["slider"]["emph"] = emph
            item["tuning"]["slider"]["pitch"] = 0.0
            item["tuning"]["slider"]["volume"] = 0.0
            if "styles" in item["tuning"]["slider"]:
                for k in ["J", "A", "S", "C"]:
                    if k in item["tuning"]["slider"]["styles"]:
                        item["tuning"]["slider"]["styles"][k]["value"] = 0.0
                if style_key and style_key in item["tuning"]["slider"]["styles"]:
                    item["tuning"]["slider"]["styles"][style_key]["value"] = style_val
        return item

    new_items = []
    block_map = []   # ブロック順に {id, speaker}。both行は 葵→茜 の2ブロック＝番号≠idになるためsyncが参照
    for line in lines:
        speaker = line.get("speaker", "akane")
        emotion = line.get("emotion", "平静"); text = line["text"]
        spks = ["aoi", "akane"] if speaker == "both" else [("akane" if speaker == "akane" else "aoi")]
        for spk in spks:
            new_items.append(make_block(spk, text, emotion))
            block_map.append({"id": line["id"], "speaker": spk})

    template_json["textblocks"] = new_items

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / f"Pharma_Ep{int(EP)}_genuine.aieprojx"
    with open(out_file, "w", encoding="utf-8-sig") as f:
        json.dump(template_json, f, ensure_ascii=False, indent=1)
    with open(OUTPUT_DIR / "aieprojx_blockmap.json", "w", encoding="utf-8") as f:
        json.dump(block_map, f, ensure_ascii=False, indent=1)

    n_both = sum(1 for l in lines if l.get("speaker") == "both")
    print(f"[SUCCESS] aieprojx生成: 全{len(new_items)}ブロック（both行{n_both}件は葵＋茜の2声）: {out_file}")

if __name__ == "__main__":
    main()
