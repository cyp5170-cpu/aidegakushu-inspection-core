# 外部AI敵対レビュー記録：src/env_boot.py（round5＝v5再レビュー）

- **日付**：2026-08-15
- **対象**：`src/env_boot.py` v5（SHA256＝`f506e3a0ccb9e0195c0bc7ef9d4b060fb39d3a5dabc8859bba10a953afcf3c90`）
- **レビュアー**：ブラウザ版 ChatGPT **GPT-5.6 Sol（OpenAI）**（推論「高い」・1m53s思考）

---

判定：NO-GO

## [CRITICAL] 環境変数名を case-sensitive dict で扱い、合法な設定を missing 誤判定（★修正可）
- Windowsの環境変数名は case-insensitive（os.environも大文字化）。`snap[name]`/`snap.get(name)` が完全一致検索のため、
  レジストリ `OpenAI_Api_Key` を `resolve_ex("OPENAI_API_KEY")` が拾えず `(None,None)`＝正常な未設定に偽装した偽陰性。
  `_expand()` の `snap.get(key)` も同様。→ snap を case-insensitive（キー正規化）にする。

## [HIGH] 列挙TOCTOU（★原理的に不可避）
- round4で「259のみ正常終了」は途中APIエラーには強くなったが、**列挙中に別プロセスの setx/installer が HKCU\Environment を
  追加削除**すると index 配置が変わり、最後に正常な259を受けて incomplete/mixed snapshot を「完全」と返し得る。
  MSは「列挙中に対象キーを変更するな」と明記＝これはRegEnumValue仕様から直接生じるTOCTOUで、**単一プロセスのコードでは
  完全には除去できない**（レジストリの外部変更は制御不能）。

## [HIGH] os.environ を各キーで live read＝1スナップショットになっていない（★一部不可避）
- `sweep()` は `if name in os.environ` をキー毎に、`_expand()` も置換毎に live 読み。途中で環境変数が変わると
  KEY_A=変更前 / KEY_B=変更後 の混合結果になり得る。os.environ を1回コピーして使えば緩和できるが、
  **レジストリとos.environを"跨いで"原子的にスナップショットする手段は無い**（跨源の原子性は不可避の限界）。

## [MEDIUM] _expand の _MAX_EXPAND=16 は深さ制限で、cycle検出でない＝長い正常鎖を誤FAIL（★修正可）
- A01→A02→…→A17 の合法acyclic鎖が16回で打ち切られ未解決扱い。seen集合/依存グラフでcycle検出＋別途DoS用の長さ/参照上限に。

## [MEDIUM] 単なる `%` まで unresolved 扱い（★修正可）
- `C:\data\100%\credentials.json` は _VAR に1件もマッチしなくても `if "%" in val` でエラー。判定は「未解決の _VAR が残るか」にすべき。

## [MEDIUM] _selftest がテスト中 os.environ を変更（本物の OPENAI_API_KEY を一時除去）＝契約を試験中に破る（★修正可）
- finally復元でも実行中は実キーを消す。os.environ をパラメータ注入する形にして本物を触らない設計に。

## 帰結（重要な質的変化）
CRITICAL（case）と MEDIUM 3件は修正可。しかし **HIGH 2件（列挙TOCTOU／跨源スナップショット）は原理的に不可避**＝
「レジストリと環境変数を外部の並行変更に対して原子的に読む」手段がOSに無い。＝ここから先、敵対レビューは
**不可避の並行レースを指摘し続け得る**ため、"全指摘ゼロ"は登録レジストリreaderでは到達不能の可能性が高い。
＝プロジェクト自身の結論「完璧な検証は原理的に不可能→人間バックストップ／強制範囲を狭く」の実演。要ユーザー再判断。
