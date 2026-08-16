# -*- coding: utf-8 -*-
"""外部AI敵対レビュー依頼の生成器（検品コア10ファイル分・自己完結プロンプト）。

なぜ必要か：
  真の外部レビュー強制はCI(GitHub Actions)へ一本化済み。そのCIが検証する
  「署名manifest」に載せるには、各検品コアfileを外部AI(OpenAI必須+強AI)で
  敵対レビューし GO を得て --register する必要がある(手順書 CI_ENFORCEMENT_SETUP.md §3)。
  本スクリプトは、その10ファイル分の "ブラウザに貼れる自己完結レビュー依頼" を
  決定論で生成する（手書きより確実・コード変更時に追随・SHAはgateと同一計算）。

出力：src/checkdata/external_reviews/_requests/review_<basename>.md ×10
使い方：py src/gen_review_requests.py   （引数なしで全10本を再生成）

方針（重要）：CRITICAL_DEFAULT と file_hash は external_review_gate から import して
  「対象集合」「SHA計算」をゲートと絶対に食い違わせない（＝依頼に載るSHAが署名対象と一致）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# ゲートと同一の「正典リスト」「SHA計算」を使う（食い違い防止＝単一ソース）
import external_review_gate as erg

ROOT = erg.ROOT
REQ_DIR = ROOT / "src" / "checkdata" / "external_reviews" / "_requests"

# ---- 各ファイルの役割と "固有の脅威"（レビュアーの注意を実欠陥へ集中させる） ----
FILE_NOTES = {
    "src/check_system.py": {
        "role": "メタ検品。各ゲートのself-test・APIキー・Vertex ADCの生死を診断し、"
                "不全を exit 非0 で表出する（新セッション最初の自己診断）。",
        "threats": [
            "『偽の緑』＝実際は壊れているのに OK と報告してしまう経路はないか。",
            "子プロセス実行時のエンコーディング事故（cp932パイプで UnicodeEncodeError→"
            "rc=1 を『検証失敗』と誤解）。PYTHONIOENCODING=utf-8 の子への継承は正しいか。",
            "except で握りつぶしてインフラ不全を緑にしていないか。",
            "キー『あり』判定と『ライブ疎通あり』を混同していないか（非live判定の偽の緑）。",
        ],
    },
    "src/verify_core.py": {
        "role": "PJ非依存の検証コア。複合指紋(SoT正規化+asset hash+ruleset版+verifier版)・"
                "manifest・stale判定・PASS/WARN/BLOCK/UNKNOWN を提供。",
        "threats": [
            "指紋の決定論：同一入力→必ず同一ハッシュか（辞書順・環境・ロケール・"
            "浮動小数・パス区切りで揺れないか）。",
            "asset hash が本当に指紋へ入っているか（v0の致命欠陥＝assetを見ずstaleを"
            "見逃す、の再発検査）。",
            "台本や素材が変わった後の stale 判定に偽陰性はないか。",
            "UNKNOWN が握りつぶされず必ず人へ上がるか。",
        ],
    },
    "src/pre_submit_gate.py": {
        "role": "最大の検出ゲート(834行)。過去エラー回帰／因果方向／行id連番／"
                "A-8『画像×台詞の機構矛盾』／medsafety／帰属ガード等を決定論で検出。",
        "threats": [
            "医療的な偽陰性（危険な誤り＝週1薬を連日・NEVER経路・作用方向の逆転などの見逃し）。",
            "偽陽性（正しい台本を誤FAIL）。特に帰属ガード（頂端=ペンドリン/受容体=TSH等）の穴。",
            "行id連番チェックの抜け（逆行・重複・X01等の異常番号の取りこぼし）。",
            "正規表現が全角・日本語隣接・表記ゆれで取りこぼす／過検出するケース。",
        ],
    },
    "src/policy_gate.py": {
        "role": "方針の強制簿。各方針に decision(codify/record_only/defer/空) を必須化し、"
                "未決定／有言不実行(codify宣言なのに未実装+期限切れ)／defer期限切れ を FAIL。",
        "threats": [
            "decision 必須の回避経路（空や未知値をすり抜けられないか）。",
            "期限（今日との比較）の境界・タイムゾーン・日付パースの脆さ。",
            "codify 宣言済みなのに未実装、を検知し損ねないか。",
        ],
    },
    "src/ship.py": {
        "role": "出荷ゲート（唯一の正規経路）。policy_gate/裏取り/提出前ゲート/verify_assets/"
                "cinematic を集約し、全緑＋人サインオフで許可証(状態指紋)を発行。"
                "--verify で発行後の改変(MATCH/STALE/NO_PERMIT/BROKEN)を検知。",
        "threats": [
            "迂回（build直叩き・配線削除・TOCTOU）で無許可のまま出荷できないか。",
            "許可証の偽造・複製・使い回しに対する堅牢性。",
            "状態指紋が『実際に表示される成果物』を捉えているか（合成図・音声を含むか）。",
            "サインオフ未記録なのに GO を出す誤りはないか（人の確認の代替をしていないか）。",
        ],
    },
    "src/figlint.py": {
        "role": "図レイアウトの決定論リンター（ラベル重なり／見切れ／小文字／"
                "ラベル×図形WARN／bbox0=未計装FAIL）。毎生成・毎ビルドで実走。",
        "threats": [
            "未計装の図での『偽の緑』（bbox0 検知の穴・計装漏れの見逃し）。",
            "ロケーター／合成カード（_compose_locator 等）の取りこぼし。",
            "図生成時の例外を未検査でスルーして PASS 扱いにしていないか。",
        ],
    },
    "src/run_preship_qa.py": {
        "role": "ep横断の先回りQAオーケストレータ。check_system→figlint→全epゲート→"
                "許可証照合 を集約し、FAIL/柱DOWN/STALE で exit 非0。",
        "threats": [
            "下位チェックの失敗を握りつぶして全体を緑にしていないか。",
            "exit code の正しさ（1つでもFAIL/柱DOWN/STALEなら非0か）。",
            "一部epのスキップ・列挙漏れ（新規epや階層構造の取りこぼし）。",
        ],
    },
    "src/verify_assets.py": {
        "role": "verify_core を本PJへ配線する adapter＋人サインオフ支援。"
                "effective_card_image で『実際に表示される絵』を指紋化し、"
                "text/画像変更で自動 stale 化。--signoff は人のみ。",
        "threats": [
            "行×画像の対応ミス（使われない旧jpgを誤照合＝過去の実バグの再発）。",
            "『Claudeが代理サインオフしない』設計が破れていないか（自己申告の穴）。",
            "text や画像が変わった後に確実に stale（要再確認）へ落ちるか。",
        ],
    },
    "src/env_boot.py": {
        "role": "Windows「setx反映漏れ」対策の**読取専用・per-key最小設計**ヘルパ。os.environ を一切変更せず、"
                "resolve()/resolve_ex() で env優先＋HKCU\\Environment を**1キーずつ RegQueryValueEx で**読む"
                "（値名の大小文字はWindows APIが吸収／REG_EXPAND_SZ は ExpandEnvironmentStrings に委譲／列挙も自前%展開もしない）。"
                "呼び出し側は値を SDK へ api_key= 等で明示渡しする（秘密を os.environ に載せない＝過剰伝播を避ける）。"
                "限界：os.environ とレジストリを外部並行変更に対し原子的に跨ぐ読みはOS上不可能＝単一スレッドimport時前提のbest-effort。",
        "threats": [
            "os.environ を汚さない（＝子プロセスへ秘密を伝播させない）契約が守られているか。",
            "REG_SZ/REG_EXPAND_SZ 以外の型を注入しないか／ExpandEnvironmentStrings 失敗を観測可能にするか。",
            "空文字は「設定済み」として尊重するか／キー・値の不在は正常な no-op か（偽エラーにしない）。",
            "アクセス障害等のインフラ異常を握りつぶさず戻り値の error で観測可能にしているか（グローバル履歴を持たず冪等か）。",
            "Windows以外・レジストリ不在での安全な no-op か。",
            "self-test が実 os.environ / 実レジストリを触らず（注入式で）決定論か。",
        ],
    },
    "src/external_review_gate.py": {
        "role": "本ゲート自身。検品コアの内容ハッシュに外部レビュー記録を束縛し、"
                "レビュー後改変=STALE／無レビュー改変=NO-GO を表出。"
                "--register/--gen-manifest/--baseline/validate を持つ。",
        "threats": [
            "verdict 判定の偽陽性（実レビューの『NO-GO条件に合致しないため判定はGO』を"
            "誤ってFAILさせる）／偽陰性（日本語隣接・全角ＧＯ・GO/NO-GO 併記）。",
            "rename や registry(json) 直編集による『変更なし』偽装のバイパス。",
            "署名のダウングレード（鍵ファイル削除で署名検証をスキップ等）。",
            "TOCTOU（open/hash/use の間の差し替え）。",
        ],
        "known": "※『自己参照パラドックス』と『ローカルで改ざん/バイパス可能』は"
                 "既にCI(GitHub Actions+署名manifest+ブランチ保護)で解決する前提が確定済み。"
                 "それ単体を理由にNO-GOにしないでください。ここで見たいのは"
                 "『このコード自体のロジック欠陥（偽陽性/偽陰性・回帰・TOCTOU等）』です。",
    },
}

CHARTER = """\
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
"""

OUTPUT_TEMPLATE = """\
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
"""


def _sha(rel: str) -> str:
    return erg.file_hash(rel)


def build_one(rel: str) -> str:
    note = FILE_NOTES[rel]
    src = (ROOT / rel).read_text(encoding="utf-8")
    sha = _sha(rel)
    threats = "\n".join(f"{i+1}. {t}" for i, t in enumerate(note["threats"]))
    known = ("\n\n> " + note["known"]) if note.get("known") else ""
    parts = [
        f"# 外部AI敵対レビュー依頼：`{rel}`",
        "",
        "（**自己完結**・ブラウザ版 **OpenAI 必須＋強AI(Gemini/Claude等)追加** で敵対レビュー）",
        "",
        CHARTER,
        "",
        "## このファイルの役割",
        note["role"],
        "",
        "## このファイル固有の脅威（重点的に突く）",
        threats + known,
        "",
        OUTPUT_TEMPLATE,
        "",
        f"## レビュー対象コード：`{rel}`",
        f"- SHA256（改行正規化後・ゲートの署名対象と同一計算）：`{sha}`",
        "- ↓このコード全文をレビューしてください。",
        "",
        "```python",
        src.rstrip("\n"),
        "```",
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for rel in erg.CRITICAL_DEFAULT:
        if rel not in FILE_NOTES:
            print(f"  [WARN] {rel} に固有ノートが無い＝FILE_NOTESを更新せよ（依頼の質が落ちる）")
            continue
        if not (ROOT / rel).exists():
            print(f"  [WARN] {rel} が存在しない＝スキップ")
            continue
        out = REQ_DIR / f"review_{Path(rel).stem}.md"
        out.write_text(build_one(rel), encoding="utf-8")
        written.append(out)

    # 網羅チェック：正典にあるのにノート未整備を明示（サイレント厳禁）
    missing = [r for r in erg.CRITICAL_DEFAULT if r not in FILE_NOTES]
    print("=" * 66)
    print(f"✅ 生成 {len(written)}/{len(erg.CRITICAL_DEFAULT)} 本 → {REQ_DIR}")
    for p in written:
        print(f"   - {p.relative_to(ROOT)}")
    if missing:
        print(f"🔴 ノート未整備 {len(missing)} 件：{missing}")
        return 1
    print("=" * 66)
    print("次：各mdをブラウザ版OpenAI(+強AI)へ貼付→判定を保存→--register→--gen-manifest→署名")
    return 0


if __name__ == "__main__":
    sys.exit(main())
