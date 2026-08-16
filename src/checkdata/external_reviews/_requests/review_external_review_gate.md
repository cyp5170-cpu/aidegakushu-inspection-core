# 外部AI敵対レビュー依頼：`src/external_review_gate.py`

（**自己完結**・ブラウザ版 **OpenAI 必須＋強AI(Gemini/Claude等)追加** で敵対レビュー）

## これは何か（背景・必読）
「AIで学習」＝薬学・病態の**解説動画を自動制作**するプロジェクトの、**検品(QA)システム**の一部です。
このシステムは「重要な方針は"記録(メモリ/MD)"では無視され得る→"コードのゲート(exit非0)"にする→"
さらに外部AIレビュー自体をコード強制する"」という思想で作られています。

いま依頼するのは次の一点です：
> **このファイルのコードを敵対的にレビューし、"CIで署名・強制する信頼できる検証コード"として GO / NO-GO を判定してください。**

## 既に確定している前提（蒸し返し不要）
- **ローカルの自己参照ゲートは原理的に「強制」になり得ない**（過去3回の敵対レビューで収束）。
  だから**真の強制は GitHub Actions（改ざん不能）＋署名manifest＋ブランチ保護へ一本化済み**です。
- したがって「**ローカルで改ざん/バイパスできる**」だけを理由に NO-GO にしないでください（それはCIで解決）。
- あなたの任務は、**このファイル固有のロジック欠陥**＝検出の**偽陰性/偽陽性**、**サイレント失敗**、
  **エンコーディング/TOCTOU/非決定性**、**契約違反**など"実際のバグ"を突くことです。

## 敵対レビューの共通観点（ルーブリック）
1. **偽陰性**：本来FAILにすべき危険/誤りを見逃す入力はあるか（具体例で）。
2. **偽陽性**：正しいものを誤ってFAILさせる入力はあるか（回帰の温床）。
3. **サイレント失敗**：例外の握りつぶし・非0で表出しない・"偽の緑"はないか。
4. **エンコーディング契約**：cp932パイプ・PYTHONIOENCODING・親子のI/O契約は堅いか。
5. **決定論/鮮度**：同一入力→同一結果か。キャッシュ・stale・TOCTOU の穴はないか。
6. **信頼基点**：measurement==measured（自分で自分を測る）に依存していないか。
7. **このファイル固有の脅威**（下記）。


## このファイルの役割
本ゲート自身。検品コアの内容ハッシュに外部レビュー記録を束縛し、レビュー後改変=STALE／無レビュー改変=NO-GO を表出。--register/--gen-manifest/--baseline/validate を持つ。

## このファイル固有の脅威（重点的に突く）
1. verdict 判定の偽陽性（実レビューの『NO-GO条件に合致しないため判定はGO』を誤ってFAILさせる）／偽陰性（日本語隣接・全角ＧＯ・GO/NO-GO 併記）。
2. rename や registry(json) 直編集による『変更なし』偽装のバイパス。
3. 署名のダウングレード（鍵ファイル削除で署名検証をスキップ等）。
4. TOCTOU（open/hash/use の間の差し替え）。

> ※『自己参照パラドックス』と『ローカルで改ざん/バイパス可能』は既にCI(GitHub Actions+署名manifest+ブランチ保護)で解決する前提が確定済み。それ単体を理由にNO-GOにしないでください。ここで見たいのは『このコード自体のロジック欠陥（偽陽性/偽陰性・回帰・TOCTOU等）』です。

## 回答フォーマット（この形で返してください＝そのまま登録に使います）
先頭行に必ず次のどちらかを書いてください（機械が判定語を拾います）：

    判定：GO
    または
    判定：NO-GO

続けて：
- **モデル正式名**（例：GPT-5.6 Sol / Gemini 3.1 Pro など、版まで）
- **最重要の欠陥**（重大度つき・"どんな入力/状態→どんな誤結果"を具体で）
- **修正提案**（あれば）
- GO の場合も「このコードを署名・CI強制の対象にしてよい理由」を1〜2行で。

> 保存：この回答**全文**を
> `src/checkdata/external_reviews/2026-08-15_<ファイル名>_<provider>.md` として保存し、
> `py src/external_review_gate.py --register --file <path> --verdict <GO|NO-GO> --model "<版>" --record <保存先>`
> で登録します（登録はユーザーが実施）。


## レビュー対象コード：`src/external_review_gate.py`
- SHA256（改行正規化後・ゲートの署名対象と同一計算）：`a80c41afb553b79a37feb2126e7ff579b04da6dc165710e6b2aacf105b50bb0d`
- ↓このコード全文をレビューしてください。

```python
# -*- coding: utf-8 -*-
"""
external_review_gate.py ― 「重要物は必ず外部AIで敵対レビュー」を"記録止まり"にさせない強制ゲート。

契機（2026-08-15 ユーザー指示「他AIを使うというのを必ず実行するよう強制して」）:
  恒久ルール[[feedback_multiai_browser_enforcement]]＝重要物はブラウザ版他AI(OpenAI必須+強AI)で敵対レビュー。
  だが「メモリ/MDに書いた方針は強制力ゼロ(無視され得る)」を私(Claude)自身が実演した
  （3行の小修正を"重要でない"と自己判断して外部レビューを飛ばし、GPTが【高】級の欠陥を複数発見＝NO-GO）。
  → policy_gate と同じ思想で、"検品コア"の変更は外部AIレビュー記録が無ければ🔴で出続けるようにする。

強制の対象（人＝トラストアンカーが決めた範囲＝「検品システムのコア」・2026-08-15）:
  critical_files（下記CRITICAL_DEFAULT）。＝検品を支えるsrc。ここを外部レビューなしに変えられなくする。

判定ロジック（純関数 evaluate＝self-testで守る。current_hash＝いま現在の内容ハッシュ）:
  ● review 済 & reviewed_sha==current & verdict=GO      → 🟢OK
  ● review の verdict=NO-GO                              → 🔴FAIL（不合格を出荷しない）
  ● review 済 だが reviewed_sha≠current                 → 🔴FAIL STALE（レビュー後に改変＝再レビュー必須）
  ● 未review & baseline_sha==current（導入前から在る）   → 🟡WARN（外部レビュー債務・可視化して忘れさせない）
  ● 未review & baseline_sha≠current                     → 🔴FAIL（＝核心を無レビューで触った）
  ● エントリ無し（新規critical file）                    → 🔴FAIL（baseline登録して外部レビューへ）

★機械化できるのは「レビューを必ずさせる/迂回を🔴にする」まで。
  "何がcriticalか"と"実際に外部AIへ出して結果を貼る"のは人（委譲不能・トラストアンカー）。
  ＝Claudeが「レビューした事にする」自己申告を避けるため、registerは実在の記録ファイルパスを要求する。

★★塞いだ穴（2026-08-15 OpenAI GPT-5.6 Sol + Gemini 3.1 Pro拡張の敵対レビューを受けた強化）:
  ・--baselineのグランドファーザリング廃止（既存baselineは不変・"改ざん→baseline→WARN→出荷"の完全バイパスを封鎖）。
  ・レビュー記録の"中身"検査（validate_record＝最小分量/verdict語一致/対象file言及/model言及/gpg署名）。
    ＝存在確認だけでは空ファイル・別コードのレビュー・NO-GO本文なのにregistry=GO を素通りさせていた穴を封鎖。
  ・TRUST_PUBKEY(信頼公開鍵)があればgpg署名を必須化（秘密鍵はユーザー保持＝Claudeは署名しない）。
★★ローカルでは原理的に塞げない残穴（＝真の強制にはCI＋読取専用ストレージが必須。両AIが一致指摘）:
  ・新規ファイル追加/rename/動的import・exec・eval/生成コードはこの静的hash監視の外（import-graph/CI側フルスキャンが要る）。
  ・registry(external_reviews.json)やこのコード自体をローカルで直接書き換えられる（＝信頼基点がローカルにある限り無効化可能）。
  ・check_system/ship.pyの配線コード削除・ship.pyを通らない出荷経路・TOCTOU。
  → これらは「GitHub Actions(ローカル外の実行環境)＋ブランチ保護＋署名検証」でのみ強制になる。ローカル版は
    "事故・怠慢・うっかり"を止める層であり、"決めて迂回する人"は人のバックストップが最後（ship.pyの限界と同じ）。

使い方:
  py src/external_review_gate.py                 評価（STALE/NO-GO/無レビュー改変で exit 1）
  py src/external_review_gate.py --self-test
  py src/external_review_gate.py --baseline      全critical fileのbaseline_shaを現在値で確定（導入時に1回）
  py src/external_review_gate.py --register --file src/verify_core.py --verdict GO \
        --model "ChatGPT(...)" --record "src/checkdata/external_reviews/xxx.md" [--reviewer "..."]
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # noqa: F401
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import re
import shutil
import hashlib
import argparse
import datetime
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REGISTRY = HERE / "checkdata" / "external_reviews.json"
# 署名対象の構造化manifest（CI phaseの信頼基点。CIが公開鍵で署名検証し、各critical fileのsha一致を必須化）。
# ＝両AIが示した正解：本文grepでなくmanifestごと署名。gate自身のshaも含むので改ざんは不一致で露見。
MANIFEST = HERE / "checkdata" / "external_reviews_manifest.json"
# レビュー記録の最小分量（空/ダミーを弾く。GPT/Gemini指摘=存在確認だけでは偽装が通る）。
MIN_RECORD_BYTES = 400
# 信頼する公開鍵(gpg)。存在すればレビュー記録に有効な署名を必須化＝ローカル書換偽装を防ぐ。
# 秘密鍵はユーザーが保持（Claudeは署名しない＝自己申告防止）。無ければ署名検証はスキップし内容検査のみ。
TRUST_PUBKEY = HERE / "checkdata" / "trusted_reviewers.asc"

# 検品を支えるsrc（＝人が決めた強制対象。増減はこのリストを編集）。
CRITICAL_DEFAULT = [
    "src/check_system.py",
    "src/verify_core.py",
    "src/pre_submit_gate.py",
    "src/policy_gate.py",
    "src/ship.py",
    "src/figlint.py",
    "src/run_preship_qa.py",
    "src/verify_assets.py",
    "src/env_boot.py",
    "src/external_review_gate.py",
]

VALID_VERDICT = {"GO", "NO-GO"}


def file_hash(relpath: str) -> str:
    """内容ハッシュ。改行差(CRLF/LF)だけは正規化し、それ以外の変更は全て別ハッシュ＝要再レビュー。
    ファイルが無ければ空文字（＝評価側で『無し』として扱う）。"""
    p = ROOT / relpath
    if not p.exists():
        return ""
    raw = p.read_bytes()
    norm = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(norm).hexdigest()


def _gpg_ok(record_path: Path) -> bool:
    """gpg署名検証。TRUST_PUBKEY(信頼公開鍵)が無ければ"検証不能"としてスキップ(True扱いは呼び側で判断)。
    署名ファイル= <record>.sig or <record>.asc（detached）。gpg未導入や署名欠落はFalse。"""
    if not TRUST_PUBKEY.exists() or not shutil.which("gpg"):
        return True  # 署名運用が未導入＝内容検査のみで判定（呼び側でREQUIRE_SIGは別途）
    sig = None
    for ext in (".sig", ".asc"):
        c = record_path.with_suffix(record_path.suffix + ext)
        if c.exists():
            sig = c
            break
    if sig is None:
        return False
    try:
        # 一時keyringにTRUST_PUBKEYを取り込み、detached署名を検証（システムkeyringを汚さない）。
        p = subprocess.run(["gpg", "--no-default-keyring", "--keyring", str(TRUST_PUBKEY),
                            "--verify", str(sig), str(record_path)],
                           capture_output=True, text=True, timeout=30)
        return p.returncode == 0
    except Exception:
        return False


def validate_record(rel: str, review: dict):
    """レビュー記録が"実体のある外部レビュー"かを検査（存在確認だけでは偽装が通る=両AI指摘）。
    返り値=(ok, reason)。ok=Falseなら登録済みでも🔴に落とす（登録後に空にする等の改ざんも捕捉）。"""
    rec = (review or {}).get("record", "")
    if not rec:
        return False, "record未指定"
    p = ROOT / rec.replace("\\", "/")
    if not p.exists():
        return False, f"記録ファイルが無い: {rec}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"記録が読めない: {e}"
    if len(text.encode("utf-8")) < MIN_RECORD_BYTES:
        return False, f"記録が短すぎる(<{MIN_RECORD_BYTES}B)＝空/ダミーの疑い"
    verdict = (review.get("verdict") or "").upper()
    # 記録本文に登録verdictと同じ語があるか（NO-GO本文なのにregistry=GOのすり替えを弾く）。
    if verdict == "GO":
        if not re.search(r"\bGO\b", text) or re.search(r"NO[- ]?GO", text):
            return False, "verdict=GOだが記録本文がGOを支持していない(NO-GO語がある/GO語が無い)"
    # 対象ファイル名が記録に出てくるか（別コードのレビューを流用する誤りを弾く）。
    if Path(rel).name not in text:
        return False, f"記録に対象ファイル名『{Path(rel).name}』の言及が無い(別コードのレビュー?)"
    # モデル名が記録にあるか（真正性の最低限）。
    model = (review.get("model") or "").strip()
    if model and model.split("(")[0].strip() and model.split("(")[0].strip() not in text:
        return False, f"記録にモデル名『{model}』の言及が無い"
    # 署名運用が導入済みなら有効署名を必須化。
    if TRUST_PUBKEY.exists():
        if not _gpg_ok(p):
            return False, "有効なgpg署名が無い(信頼公開鍵は導入済＝署名必須)"
    return True, "OK"


def _today() -> str:
    return datetime.date.today().isoformat()


def load_registry() -> dict:
    if not REGISTRY.exists():
        return {"critical_files": list(CRITICAL_DEFAULT), "files": {}}
    data = json.load(open(REGISTRY, encoding="utf-8"))
    data.setdefault("critical_files", list(CRITICAL_DEFAULT))
    data.setdefault("files", {})
    return data


def save_registry(data: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    json.dump(data, open(REGISTRY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def evaluate(critical_files, files, current_hashes, record_valid=None):
    """純関数＝self-test対象。各critical fileを判定 → (level, relpath, status, msg)。
    files          : registry['files']（relpath→{baseline_sha256, review}）
    current_hashes : relpath→現在ハッシュ（''はファイル欠落）
    record_valid   : relpath→bool（レビュー記録の中身検査結果。Noneなら"検査省略=有効扱い"＝self-test用）"""
    rv = record_valid or {}
    out = []
    for rel in critical_files:
        cur = current_hashes.get(rel, "")
        ent = files.get(rel)
        if cur == "":
            out.append(("FAIL", rel, "MISSING", "critical fileが存在しない（削除/移動なら対象リストを更新）"))
            continue
        if not ent:
            out.append(("FAIL", rel, "UNTRACKED", "未追跡の新規critical file＝--baseline後に外部レビューへ"))
            continue
        review = ent.get("review")
        base = ent.get("baseline_sha256", "")
        if review:
            verdict = (review.get("verdict") or "").upper()
            rsha = review.get("reviewed_sha256", "")
            if verdict == "NO-GO":
                out.append(("FAIL", rel, "NO-GO",
                            f"外部レビュー不合格(model={review.get('model','?')})＝直して再レビュー"))
            elif rsha != cur:
                out.append(("FAIL", rel, "STALE",
                            "外部レビュー後にコードが変わった＝再レビュー必須(古い合格を無効化)"))
            elif verdict == "GO" and rv.get(rel, True) is False:
                # 登録はGOだが記録の中身が実体を欠く/改ざん(空・別コード・NO-GO本文・署名無し)＝合格を無効化。
                out.append(("FAIL", rel, "RECORD-INVALID",
                            "レビュー記録が実体を欠く(空/別コード/verdict不一致/署名無し)＝GO登録を信用しない"))
            elif verdict == "GO":
                out.append(("OK", rel, "REVIEWED",
                            f"外部レビュー合格・現行一致・記録有効(model={review.get('model','?')}, {review.get('reviewed_at','?')})"))
            else:
                out.append(("FAIL", rel, "BAD-VERDICT", f"verdict不正『{verdict}』"))
        else:
            if base == cur:
                out.append(("WARN", rel, "UNREVIEWED",
                            "外部AI敵対レビュー未実施の債務（導入前から在るコード・触ったら🔴に落ちる）"))
            else:
                out.append(("FAIL", rel, "CHANGED-UNREVIEWED",
                            "baselineから変更されたのに外部レビュー無し＝核心を無レビューで改変"))
    return out


def run():
    data = load_registry()
    crit = data["critical_files"]
    files = data["files"]
    cur = {rel: file_hash(rel) for rel in crit}
    # GO登録された行は記録の中身も検査（存在確認だけでは偽装が通る＝両AI指摘）。
    rvalid = {}
    for rel in crit:
        ent = files.get(rel) or {}
        rev = ent.get("review")
        if rev and (rev.get("verdict") or "").upper() == "GO":
            ok, _reason = validate_record(rel, rev)
            rvalid[rel] = ok
    res = evaluate(crit, files, cur, record_valid=rvalid)
    print("=" * 74)
    print("🛡 外部AI敵対レビューの強制（検品コアを無レビューで変えさせない）")
    print("=" * 74)
    nf = nw = 0
    for level, rel, status, msg in res:
        mark = {"FAIL": "🔴", "WARN": "🟡", "OK": "🟢"}[level]
        print(f"  {mark} [{status:<18}] {rel}: {msg}")
        nf += level == "FAIL"
        nw += level == "WARN"
    print("=" * 74)
    if nf:
        print(f"🔴 外部レビュー未達 {nf}件（債務 {nw}）＝該当を外部AI(OpenAI必須+強AI)で敵対レビューし --register せよ。")
    elif nw:
        print(f"🟡 外部レビュー債務 {nw}件＝導入前コード。順次 外部レビュー→--register で消す。")
    else:
        print("🟢 検品コアは全て外部レビュー合格・現行一致。")
    print(f"[SUMMARY] fail={nf} warn={nw}")   # check_system等が拾う機械可読行
    return 1 if nf else 0


def cmd_baseline():
    """★グランドファーザリング廃止（両AIが指摘した致命的バイパスの根治）：
    baselineは"まだエントリの無い新規ファイル"にだけ与える。既存baselineは決して動かさない。
    ＝「コード改ざん→--baselineで基準上書き→WARN→出荷」の完全バイパスを封じる。
    一度baselineした後にファイルを変えたら、その行はCHANGED-UNREVIEWED(🔴)のまま＝--register(実レビュー)でしか緑にできない。"""
    data = load_registry()
    seeded, skipped = [], []
    for rel in data["critical_files"]:
        ent = data["files"].get(rel)
        if ent and ent.get("baseline_sha256"):
            skipped.append(rel)   # 既存baselineは不変（黙ってWARNへ戻せない）
            continue
        data["files"][rel] = {"baseline_sha256": file_hash(rel), "review": None}
        seeded.append(rel)
    save_registry(data)
    print(f"✅ baseline確定：新規{len(seeded)}件をseed／既存{len(skipped)}件は不変(黙って上書きしない)。")
    if skipped:
        print("   既存baselineを変えたい場合は"
              "『実レビュー→--register』のみ（--baselineでは動かせない＝グランドファーザリング禁止）。")
    return 0


def cmd_gen_manifest():
    """署名対象の構造化manifestを生成（CI phaseの信頼基点）。全critical fileの現sha＋registryのレビュー情報を束ねる。
    ★これ自体を人が秘密鍵でdetached署名(gpg --armor --detach-sign)し、公開鍵と共にcommit。
      CIは①公開鍵で署名検証②各fileのsha一致③verdict=GOを必須化＝gate自身のshaも入るので改ざんはCIで露見。
    決定論JSON(sort_keys)＝署名が安定する。"""
    data = load_registry()
    files = {}
    for rel in data["critical_files"]:
        ent = data["files"].get(rel) or {}
        rev = ent.get("review") or {}
        rec = rev.get("record", "")
        rec_sha = file_hash(rec) if rec and (ROOT / rec.replace("\\", "/")).exists() else ""
        files[rel] = {
            "sha256": file_hash(rel),
            "verdict": (rev.get("verdict") or "UNREVIEWED"),
            "model": rev.get("model", ""),
            "review_record": rec,
            "review_record_sha256": rec_sha,
            "reviewed_at": rev.get("reviewed_at", ""),
        }
    manifest = {
        "version": "erg-manifest-v1",
        "note": "署名対象。CI(GitHub Actions)が公開鍵で署名検証し、各critical fileのsha256一致＋verdict=GOを必須化する。"
                "gate自身(external_review_gate.py)のshaも含むので、gate改ざん(return True挿入等)はCIで不一致→ブロック。",
        "files": files,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    go = sum(1 for v in files.values() if v["verdict"] == "GO")
    print(f"✅ manifest生成：{MANIFEST}（{len(files)}ファイル・GO={go}）")
    print("   次：人が秘密鍵で署名 → `gpg --armor --detach-sign "
          f"{MANIFEST.relative_to(ROOT)}` → 公開鍵と共にcommit（署名はClaudeがしない＝トラストアンカーは人）。")
    print("   ⚠この状態(GO=0)ではCIは全ファイルをブロックする＝各critical fileを外部レビューしregisterしてから再生成すること。")
    return 0


def cmd_register(args):
    if not args.file or not args.verdict:
        print("🔴 --file と --verdict は必須")
        return 1
    verdict = args.verdict.upper()
    if verdict not in VALID_VERDICT:
        print(f"🔴 verdictは {VALID_VERDICT} のいずれか")
        return 1
    rel = args.file.replace("\\", "/")
    cur = file_hash(rel)
    if cur == "":
        print(f"🔴 対象ファイルが無い: {rel}")
        return 1
    # ★実在する記録ファイルを要求＝「レビューした事にする」自己申告を防ぐ（人/外部AIの実出力を貼ること）。
    if not args.record or not (ROOT / args.record.replace("\\", "/")).exists():
        print(f"🔴 --record に実在するレビュー記録ファイルのパスを指定せよ（外部AIの実出力）。指定={args.record}")
        return 1
    if not args.model:
        print("🔴 --model（使用モデル版）は必須＝恒久ルール『モデル版必ず記録』")
        return 1
    review = {
        "verdict": verdict,
        "reviewed_sha256": cur,
        "model": args.model,
        "reviewers": args.reviewer or [],
        "record": args.record.replace("\\", "/"),
        "reviewed_at": _today(),
    }
    # ★記録の"中身"を検査してから登録＝存在確認だけでは空/ダミー/別コード/verdict不一致/未署名が通る(両AI指摘)。
    if verdict == "GO":
        ok, reason = validate_record(rel, review)
        if not ok:
            print(f"🔴 GO登録を拒否：レビュー記録が実体を欠く＝{reason}")
            print("   （記録本文にGO判定・対象ファイル名・モデル名を含め、署名運用時は署名を添えること）")
            return 1
    data = load_registry()
    ent = data["files"].setdefault(rel, {"baseline_sha256": cur, "review": None})
    ent["baseline_sha256"] = cur
    ent["review"] = review
    save_registry(data)
    print(f"✅ 登録：{rel} ← verdict={verdict} model={args.model} record={args.record}")
    print("   （以後このファイルを1バイトでも変えると STALE=🔴 に落ちる＝再レビュー強制）")
    return 0


# ---- self-test（評価ロジックが壊れていないか決定論で守る）----
def self_test():
    print("=" * 74)
    print("🧪 external_review_gate self-test（未レビュー/STALE/NO-GO/無レビュー改変の検知）")
    print("=" * 74)
    crit = ["a", "b", "c", "d", "e", "f", "g"]
    files = {
        "a": {"baseline_sha256": "h1", "review": {"verdict": "GO", "reviewed_sha256": "h1", "model": "m"}},
        "b": {"baseline_sha256": "h1", "review": {"verdict": "GO", "reviewed_sha256": "hOLD", "model": "m"}},
        "c": {"baseline_sha256": "h1", "review": {"verdict": "NO-GO", "reviewed_sha256": "h1", "model": "m"}},
        "d": {"baseline_sha256": "h1", "review": None},
        "e": {"baseline_sha256": "hOLD", "review": None},
        # f: エントリ無し（未追跡）
        "g": {"baseline_sha256": "h1", "review": {"verdict": "GO", "reviewed_sha256": "h1", "model": "m"}},
    }
    cur = {"a": "h1", "b": "h1", "c": "h1", "d": "h1", "e": "h1", "f": "h1", "g": "h1"}
    # g=GO&一致だが記録の中身検査に落ちた(record_valid=False)→RECORD-INVALIDでFAIL(登録GOを信用しない)
    rvalid = {"a": True, "g": False}
    want = {"a": "OK", "b": "FAIL", "c": "FAIL", "d": "WARN", "e": "FAIL", "f": "FAIL", "g": "FAIL"}
    got = {rel: lvl for lvl, rel, _st, _m in evaluate(crit, files, cur, record_valid=rvalid)}
    ok = True
    for rel in crit:
        good = got.get(rel) == want[rel]
        ok = ok and good
        print(f"  {'✓' if good else '✗'} {rel}: 期待{want[rel]} 実際{got.get(rel)}")
    # 欠落ファイルはFAIL(MISSING)
    miss = evaluate(["z"], {"z": {"baseline_sha256": "h", "review": None}}, {"z": ""})
    good = miss and miss[0][0] == "FAIL" and miss[0][2] == "MISSING"
    ok = ok and good
    print(f"  {'✓' if good else '✗'} z(欠落): 期待FAIL/MISSING 実際{miss[0][0]}/{miss[0][2] if miss else '-'}")
    print("🟢 external_review_gate self-test PASS" if ok else "🔴 external_review_gate self-test FAIL")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--gen-manifest", dest="gen_manifest", action="store_true",
                    help="署名対象の構造化manifestを生成(CI信頼基点)")
    ap.add_argument("--file")
    ap.add_argument("--verdict")
    ap.add_argument("--model")
    ap.add_argument("--record")
    ap.add_argument("--reviewer", action="append")
    a = ap.parse_args()
    if a.self_test:
        return 0 if self_test() else 1
    if a.baseline:
        return cmd_baseline()
    if a.gen_manifest:
        return cmd_gen_manifest()
    if a.register:
        return cmd_register(a)
    return run()


if __name__ == "__main__":
    sys.exit(main())
```
