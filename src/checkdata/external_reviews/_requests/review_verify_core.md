# 外部AI敵対レビュー依頼：`src/verify_core.py`

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
PJ非依存の検証コア。複合指紋(SoT正規化+asset hash+ruleset版+verifier版)・manifest・stale判定・PASS/WARN/BLOCK/UNKNOWN を提供。

## このファイル固有の脅威（重点的に突く）
1. 指紋の決定論：同一入力→必ず同一ハッシュか（辞書順・環境・ロケール・浮動小数・パス区切りで揺れないか）。
2. asset hash が本当に指紋へ入っているか（v0の致命欠陥＝assetを見ずstaleを見逃す、の再発検査）。
3. 台本や素材が変わった後の stale 判定に偽陰性はないか。
4. UNKNOWN が握りつぶされず必ず人へ上がるか。

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


## レビュー対象コード：`src/verify_core.py`
- SHA256（改行正規化後・ゲートの署名対象と同一計算）：`ec24c62a183269661ee5b8cf8857dc694b11753a5a67ad163687f5fb4163fb4c`
- ↓このコード全文をレビューしてください。

```python
# -*- coding: utf-8 -*-
"""
verify_core.py ― 検証強制フレームワークの「プロジェクト非依存コア」(P0)。

設計＝7モデル敵対レビュー(GPT×2/Gemini×2/DeepSeek/Grok/Opus5)＋CS文献グラウンディングで収束した確定案。
正本＝C:\\claude_shared\\検証強制フレームワーク_設計案_v0.md (§4-B〜4-K)。

このモジュールが担うのは"確定した最優先(P0)"だけ：
  ● 検証インプット閉包の複合指紋(verification_fingerprint)
      = sha256( 正規化SoT claims + asset本体hash + ruleset版 + verifier版 )
      → v0の致命欠陥「asset hash欠落」(SoT不変でも成果物差し替えで素通り)を是正。
      → 単一のSoT行hashでは "粗すぎ×細かすぎ" になる問題も、閉包でまとめて指紋化して緩和。
  ● manifest(json)で {asset_id: {fingerprint, verdict, verified_at, ...}} を管理。
  ● is_stale(): 現在の複合指紋 != 記録 → 再検証を強制（stale＝要再検証）。
  ● 判定語彙は PASS/WARN/BLOCK/UNKNOWN（"合格"と"未検証(UNKNOWN)"を絶対に混同しない）。

※本モジュールは純粋(副作用は明示的なsave時のみ)・PJ非依存＝将来そのまま他PJへ移植可。
  PJ固有(何がSoTか/asset対応/検証実行)は adapter 側に置く（未実装＝次段階）。
  未実装で意図的に外したもの(次段階)：署名アテステーション(in-toto/SLSA)、出荷経路の迂回禁止、
  L2=反証Assertion生成→L0突合、依存グラフ/影響解析、メタ検品の信頼基点。設計書に記載。
"""
from __future__ import annotations
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

# 判定語彙（"合格"と"未検証"を混同しないための固定enum相当）
PASS = "PASS"        # 検証を通過（＝現行の複合指紋で検証済み）
WARN = "WARN"        # 通せるが要確認
BLOCK = "BLOCK"      # 出荷不可（重大矛盾を1つでも検出）
UNKNOWN = "UNKNOWN"  # 未検証／判定不能（★PASSと絶対に別物）
VERDICTS = (PASS, WARN, BLOCK, UNKNOWN)

# ルールセット版＝L0/決定論ルールを変えたら上げる（＝閉包に含めて再検証を強制）
# ⚠手動文字列は「ルールを変えたのにバンプし忘れ→stale素通り」の穴。実運用では
#   ruleset_fingerprint(実ルールファイル群) を使い"内容から自動導出"すること（下記）。
RULESET_VERSION = "vc-ruleset-2026.08.15"


def ruleset_fingerprint(rule_paths: Iterable[str]) -> str:
    """ルールの"実ファイル内容"から版指紋を導出（手動バンプ忘れの穴を塞ぐ）。
    レッドチーム#R1対策＝ruleset_versionを人手管理にしない。存在しないパスも指紋に反映。"""
    h = hashlib.sha256()
    for p in sorted(str(x) for x in (rule_paths or [])):
        h.update(p.encode("utf-8"))
        fp = Path(p)
        if fp.exists() and fp.is_file():
            h.update(fp.read_bytes())
        else:
            h.update(b"\x00MISSING")
    return "rs1:" + h.hexdigest()


def normalize_claim(text: str) -> str:
    """SoT claimの保守的正規化。NFKC＋空白圧縮のみ（"意味的等価"には踏み込まない）。
    ＝全角半角/合成文字/余分な空白の差でstale乱発するのを抑えるが、語の変化は必ず検知する。"""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    return " ".join(s.split())


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _asset_hash(asset_path: Optional[str], asset_bytes: Optional[bytes]) -> str:
    """成果物本体のhash。v0欠落の是正＝SoTが不変でも成果物が変われば指紋が変わる。"""
    if asset_bytes is not None:
        return sha256_hex(asset_bytes)
    if asset_path:
        p = Path(asset_path)
        if p.exists() and p.is_file():
            return sha256_hex(p.read_bytes())
        return "MISSING:" + str(asset_path)   # 欠落も指紋に反映（黙って通さない）
    return "NO_ASSET"


def verification_fingerprint(
    sot_claims: Iterable[str],
    asset_path: Optional[str] = None,
    asset_bytes: Optional[bytes] = None,
    ruleset_version: str = RULESET_VERSION,
    verifier_version: str = "none",
) -> str:
    """検証インプット閉包の複合指紋。SoT/asset/ruleset/verifierのいずれが変わっても変化する。
    決定論：claimsは正規化後にソートせず"順序保持"で連結（順序も意味なので保持）。"""
    parts = {
        "sot": [normalize_claim(c) for c in (sot_claims or [])],
        "asset": _asset_hash(asset_path, asset_bytes),
        "ruleset": str(ruleset_version),
        "verifier": str(verifier_version),
    }
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "vf1:" + sha256_hex(blob.encode("utf-8"))


class Manifest:
    """検証記録(json)。{asset_id: {fingerprint, verdict, verifier_version, verified_at, note}}。
    ※verified_atは呼び出し側が渡す（このコアは時刻を生成しない＝決定論/再現性のため）。"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.data = {}
        if self.path.exists():
            try:
                self.data = json.load(open(self.path, encoding="utf-8"))
            except Exception:
                self.data = {}

    def get(self, asset_id: str) -> Optional[dict]:
        return self.data.get(asset_id)

    def record(self, asset_id: str, fingerprint: str, verdict: str,
               verifier_version: str = "none", verified_at: str = "", note: str = "") -> None:
        assert verdict in VERDICTS, f"未知のverdict: {verdict}"
        self.data[asset_id] = {
            "fingerprint": fingerprint, "verdict": verdict,
            "verifier_version": verifier_version, "verified_at": verified_at, "note": note,
        }

    def status(self, asset_id: str, current_fp: str) -> str:
        """現行指紋に対する状態を判定語彙で返す。
        - 記録なし → UNKNOWN（未検証＝PASSではない）
        - 指紋不一致 → UNKNOWN（stale＝再検証必須。過去のPASSは無効）
        - 一致 → 記録されたverdict（PASS/WARN/BLOCK）"""
        rec = self.data.get(asset_id)
        if not rec:
            return UNKNOWN
        if rec.get("fingerprint") != current_fp:
            return UNKNOWN
        v = rec.get("verdict")
        return v if v in VERDICTS else UNKNOWN

    def is_stale(self, asset_id: str, current_fp: str) -> bool:
        rec = self.data.get(asset_id)
        return (not rec) or (rec.get("fingerprint") != current_fp)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(self.data, open(self.path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2, sort_keys=True)


def _selftest() -> bool:
    print("=" * 64)
    print("🧪 verify_core self-test（複合指紋の決定論＋stale検知＋判定語彙）")
    print("=" * 64)
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and cond
        print(("  ✓ " if cond else "  ✗ ") + name)

    base = dict(sot_claims=["NISは基底膜に局在する", "2Na:1I"],
                asset_bytes=b"IMG_v1", ruleset_version="r1", verifier_version="opus5")
    fp0 = verification_fingerprint(**base)
    # 1. 決定論（同入力→同指紋）
    check("同入力は同指紋", fp0 == verification_fingerprint(**base))
    # 2. SoT変更で指紋変化
    b2 = dict(base); b2["sot_claims"] = ["NISは基底膜に局在する", "1Na:1I"]
    check("SoT(数)変更→指紋変化", fp0 != verification_fingerprint(**b2))
    # 3. asset変更で指紋変化（v0致命欠陥の是正＝SoT不変でも成果物差し替えを検知）
    b3 = dict(base); b3["asset_bytes"] = b"IMG_v2_wrong"
    check("SoT不変でもasset差し替え→指紋変化(★v0欠陥是正)", fp0 != verification_fingerprint(**b3))
    # 4. ruleset/verifier変更で指紋変化
    b4 = dict(base); b4["ruleset_version"] = "r2"
    check("ruleset変更→指紋変化", fp0 != verification_fingerprint(**b4))
    b5 = dict(base); b5["verifier_version"] = "gpt5.6"
    check("verifier版変更→指紋変化", fp0 != verification_fingerprint(**b5))
    # 5. NFKC/空白差では指紋不変（stale乱発の抑制）
    b6 = dict(base); b6["sot_claims"] = ["ＮＩＳは基底膜に局在する", "2Na:1I"]  # 全角NIS
    check("全角/空白差では指紋不変(過検知抑制)", fp0 == verification_fingerprint(**b6))
    # 6. manifest: 未記録=UNKNOWN / 一致=記録verdict / stale=UNKNOWN
    import tempfile, os
    tmp = os.path.join(tempfile.gettempdir(), "vc_selftest_manifest.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    m = Manifest(tmp)
    check("未記録はUNKNOWN(≠PASS)", m.status("a1", fp0) == UNKNOWN)
    m.record("a1", fp0, PASS, verifier_version="opus5", verified_at="2026-08-15")
    check("記録一致でPASS", m.status("a1", fp0) == PASS)
    check("asset差し替え後はstale=UNKNOWN(過去PASS無効)", m.status("a1", verification_fingerprint(**b3)) == UNKNOWN)
    check("is_stale(不一致)=True", m.is_stale("a1", verification_fingerprint(**b3)) is True)
    check("不正verdictは拒否", _rejects_bad_verdict(m, fp0))
    print("=" * 64)
    print("🟢 verify_core self-test PASS" if ok else "🔴 verify_core self-test FAIL")
    return ok


def _rejects_bad_verdict(m: "Manifest", fp: str) -> bool:
    try:
        m.record("bad", fp, "GREEN")   # VERDICTSにない
        return False
    except AssertionError:
        return True


if __name__ == "__main__":
    import sys
    # 出力エンコーディング(cp932パイプでの🧪クラッシュ)は"親が子のI/O契約を固定"で解く設計＝
    # 本モジュール側では何もしない（純粋・移植可契約を維持）。enforced経路(check_system/run_preship_qa/ship)が
    # PYTHONIOENCODING=utf-8を子環境に設定する。手動でパイプ実行する時は同env変数を付ける。
    sys.exit(0 if _selftest() else 1)
```
