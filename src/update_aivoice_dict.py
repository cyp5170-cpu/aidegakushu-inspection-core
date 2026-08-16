# -*- coding: utf-8 -*-
"""
update_aivoice_dict.py ― reading_dict.json を A.I.VOICE2 ユーザー辞書(user.wdic)へ反映（GUI不要）

user.wdic 形式（UTF-8 BOM・1行1語）:
    # ComponentName="AITalk6" ... Type="Word" Version="4.1" Language="Japanese" Count="N"
    品詞;表記;コスト;読み(カタカナ);アクセント:*
既存語は保持し、reading_dict.json の未登録surfaceだけ追記する（冪等）。
反映後、A.I.VOICE2を再起動（または辞書再読込）すると user.dic に再コンパイルされる。
"""
import json, sys, io, shutil, datetime, re
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 🔴🔴辞書破損の第2要因（2026-08-09 第1話で発生）＝表記に半角英字を含む語。
# A.I.VOICE2の単語辞書コンパイラは半角英字/記号混じりの表記(KI, SGLT2, DPP-4, HbA1c…)を
# 弾き、1語でも混じると「単語辞書読み込み失敗」で辞書全体が読めなくなる。
# 英字略語は reading_dict.json の tts_replace が担う（TTSテキストに直接焼き込み・字幕不変）ため、
# ユーザー辞書には登録しない＝ここでスキップする。日本語表記(かな/漢字)の語だけ辞書へ。
_RE_HALF_LATIN = re.compile(r"[A-Za-z]")   # 半角英字を含む表記は辞書登録から除外
def _is_latin_surface(surf: str) -> bool:
    return bool(_RE_HALF_LATIN.search(surf or ""))

DICT = Path(__file__).resolve().parent / "reading_dict.json"
# ユーザー名をハードコードしない（ホーム基準で構築）
WDIC = Path.home() / "OneDrive" / "ドキュメント" / "AI" / "A.I.VOICE Editor" / "2.0" / "UserDic" / "WordDictionaries" / "user.wdic"

# --- 辞書破損の防止 ---
# A.I.VOICE2のアクセントは「核位置-モーラ数」。モーラ数が読みの実拍数と一致しないと
# 辞書コンパイルに失敗し『辞書が読み込めない』状態になる（2026-08-09 渕一博等で実際に発生）。
# 品詞も動作実績のある値へ限定する。壊れた値が来ても user.wdic を破損させない。
_SMALL_KANA = set("ぁぃぅぇぉゃゅょゎァィゥェォャュョ")   # 小書き=前の拍に融合（モーラを増やさない）
_SAFE_POS = {"名詞-一般"}   # user.wdicで動作実績のある品詞（未実績はこれへフォールバック）

def _mora_count(kana: str) -> int:
    return sum(0 if ch in _SMALL_KANA else 1 for ch in kana)

def _normalize_entry(surf, kana, accent, pos):
    """モーラ数・品詞を正規化して (pos, accent, warns) を返す。辞書破損の根絶用。"""
    warns = []
    m = _mora_count(kana)
    a = 0
    if accent and "-" in str(accent):
        head = str(accent).split("-", 1)[0]
        if head.lstrip("-").isdigit():
            a = int(head)
    if a < 0 or a > m:
        warns.append(f"アクセント核位置{a}→0(平板)へ補正（拍数{m}超）")
        a = 0
    fixed = f"{a}-{m}"
    if str(accent) != fixed:
        warns.append(f"アクセント {accent} → {fixed}（実拍数{m}に一致・辞書破損防止）")
    if pos not in _SAFE_POS:
        warns.append(f"品詞 {pos} → 名詞-一般（未実績品詞のフォールバック）")
        pos = "名詞-一般"
    return pos, fixed, warns

def main():
    if not WDIC.exists():
        print(f"[error] user.wdic が見つかりません: {WDIC}")
        print("        A.I.VOICE2の設定(app_settings.json)のuserdic.wdic.pathを確認してください。")
        return 1
    _d = json.load(open(DICT, encoding="utf-8"))
    data = _d.get("dict", []) if isinstance(_d, dict) else _d   # 新構造{dict,tts_replace} / 旧フラットlist両対応
    raw = WDIC.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    entries = [l for l in lines if l.strip() and not l.startswith("#")]
    surfaces = {e.split(";")[1] for e in entries if len(e.split(";")) >= 2}

    added = 0
    skipped_latin = 0
    for e in data:
        surf, kana = e.get("surface"), e.get("kana")
        if not surf or not kana or surf in surfaces:
            continue
        if _is_latin_surface(surf):   # 半角英字表記は辞書破損要因＝tts_replaceに任せてスキップ
            skipped_latin += 1
            print(f"  - skip(半角英字→tts_replace担当): {surf}")
            continue
        pos, acc, warns = _normalize_entry(surf, kana, e.get("accent"), e.get("pos", "名詞-一般"))
        for w in warns:
            print(f"    ⚠ {surf}: {w}")
        entries.append(f"{pos};{surf};2000;{kana};{acc}:*")
        surfaces.add(surf); added += 1
        print(f"  + {surf} → {kana} ({acc})")

    if added == 0:
        print(f"[OK] 追記なし（全て登録済み／半角英字スキップ{skipped_latin}件はtts_replace担当）"); return 0

    # バックアップしてから書き戻し
    shutil.copy2(WDIC, WDIC.with_suffix(".wdic.bak"))
    now = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S.%f")[:-3]
    header = (f'# ComponentName="AITalk6" ComponentVersion="1.0.0.0" UpdateDateTime="{now}" '
              f'Type="Word" Version="4.1" Language="Japanese" Count="{len(entries)}"')
    WDIC.write_text(header + "\n" + "\n".join(entries) + "\n", encoding="utf-8-sig")
    print(f"[OK] user.wdic 更新: +{added}件 / 計{len(entries)}件（半角英字スキップ{skipped_latin}件=tts_replace担当・バックアップ: user.wdic.bak）")
    print("※A.I.VOICE2を再起動（または辞書の再読込）すると user.dic に反映されます")
    return 0

if __name__ == "__main__":
    sys.exit(main())
