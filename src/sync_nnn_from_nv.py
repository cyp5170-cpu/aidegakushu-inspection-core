# -*- coding: utf-8 -*-
"""
sync_nnn_from_nv.py ― A.I.VOICE2の生wav(琴葉 X(NV)NNNN...)から NNN_speaker.wav を作り直す

PNG版build_ymm4は audio/NNN_speaker.wav を参照する。これはNV生wavのコピー。
A.I.VOICE2で録り直したら本スクリプトでNNN側を再同期する（口パク版はNV直参照なので不要）。

🔴恒久の安全網（2026-08-15追加）＝旧テイク混在事故の再発防止:
  同一NV番号のwavが複数あると、旧版は sorted() の"最後"を黙って採用し、
  誤って旧テイクを配線する事故が起きた（ep02 id2で実発生）。本版は
  「重複NVを検出→WARN表示→**台本(script.json)の該当行textと照合して正テイクを優先採用**」。
  照合で決められない時は最新mtimeを採るが、必ずWARNで人に知らせる（サイレント厳禁）。
"""
from __future__ import annotations
import re, shutil, sys, json
from pathlib import Path

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
EP_ROOT = (ROOT / _DIR) if _DIR else (ROOT / "episodes" / f"ep{_arg_ep()}")
AUDIO = EP_ROOT / "audio"
BLOCKMAP = EP_ROOT / "output" / "aieprojx_blockmap.json"
SCRIPT = EP_ROOT / "script.json"
PAT = re.compile(r"琴葉\s*(茜|葵)\(NV\)(\d{3,4})(.*?)\s*\.wav$")   # (話者, NV番号, 本文プレフィックス)
JP2SPK = {"茜": "akane", "葵": "aoi"}


def _norm(s: str) -> str:
    """照合用の正規化：空白・記号・鉤括弧・波ダッシュ等を除去（音声読みの表記ゆれを吸収）。"""
    return re.sub(r"[\s『』「」！？!?、。，．・（）\(\)\.…〜~ー－\-]+", "", str(s or ""))


def _load_script_text_by_id():
    """script.json から {id: text} を返す（無ければ空dict＝照合スキップ）。"""
    if not SCRIPT.exists():
        return {}
    try:
        d = json.load(open(SCRIPT, encoding="utf-8"))
        return {ln.get("id"): (ln.get("text", "") or "") for ln in d.get("lines", [])}
    except Exception as e:
        print(f"[warn] script.json読込失敗（テキスト照合なしで続行）: {e}")
        return {}


def _pick_correct(cands, target_text):
    """複数テイクから正テイクを選ぶ。返り値=(選択file, 理由, 手動確認要フラグ)。
    ① target_textにファイル名プレフィックスが前方一致するものを優先（音声=台本の裏取り）。
    ② 決められなければ最新mtimeを採るが needs_review=True（人に確認を促す）。"""
    nt = _norm(target_text)
    matched = []
    for prefix, w in cands:
        pfx = _norm(prefix.rstrip("…"))
        if len(pfx) >= 4 and nt and nt.startswith(pfx):
            matched.append(w)
    if len(matched) == 1:
        return matched[0], "台本一致", False
    # 台本照合で一意に決まらない → 最新mtime（+要確認）
    newest = max((w for _, w in cands), key=lambda w: w.stat().st_mtime)
    reason = "台本一致0件→最新mtime" if not matched else f"台本一致{len(matched)}件→最新mtime"
    return newest, reason, True


def main():
    bmap = None
    if BLOCKMAP.exists():
        try:
            bmap = json.load(open(BLOCKMAP, encoding="utf-8"))
        except Exception as e:
            print(f"[warn] blockmap読込失敗（従来方式で続行）: {e}")
    text_by_id = _load_script_text_by_id()

    # NV番号ごとにファイルをまとめる（重複検出のため）
    from collections import defaultdict
    groups = defaultdict(list)   # num -> [(prefix, path), ...]
    for nv in sorted(AUDIO.glob("琴葉 *(NV)*.wav")):
        m = PAT.search(nv.name)
        if not m:
            print(f"[skip] 命名不一致: {nv.name}"); continue
        groups[m.group(2)].append((m.group(1), m.group(3), nv))

    n = 0; n_dup = 0; n_review = 0
    for numstr in sorted(groups, key=lambda s: int(s)):
        items = groups[numstr]
        num = int(numstr)
        # NV番号→(id, 話者)。blockmapがあればそれで解決（both行対応）。
        if bmap and 1 <= num <= len(bmap):
            idn = bmap[num - 1]["id"]; spk = bmap[num - 1]["speaker"]
        else:
            idn = num; spk = JP2SPK[items[0][0]]
        target_text = text_by_id.get(idn, "")

        if len(items) == 1:
            chosen = items[0][2]
        else:
            n_dup += 1
            chosen, reason, needs_review = _pick_correct([(p, w) for _, p, w in items], target_text)
            mark = "🔴要確認" if needs_review else "🟡採用"
            print(f"[dup] NV{num:04d}(id{idn}): {len(items)}テイク重複 → {mark}={chosen.name[:30]}（{reason}）")
            for _, _p, w in items:
                if w != chosen:
                    print(f"        skip: {w.name[:30]}")
            if needs_review:
                n_review += 1
                print(f"        ⚠台本と照合できず。台本id{idn}=「{(target_text or '')[:28]}」を目視で確認してください。")

        dst = AUDIO / f"{idn:03d}_{spk}.wav"
        shutil.copy2(chosen, dst); n += 1

    tail = "（blockmap使用）" if bmap else ""
    print(f"[OK] NV生wav → NNN_speaker.wav を {n}本 同期{tail}"
          + (f" ／ 重複NV {n_dup}件を解決" if n_dup else "")
          + (f"（うち🔴要確認 {n_review}件）" if n_review else ""))
    if n_review:
        print("🔴 台本照合で正テイクを断定できなかったNVがあります。上記を確認し、旧テイクは退避(_old_takes)推奨。")


if __name__ == "__main__":
    main()
