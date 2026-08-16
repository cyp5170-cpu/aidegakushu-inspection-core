# 外部AI敵対レビュー記録：src/env_boot.py（round2＝#1-#5修正後の再レビュー）

- **日付**：2026-08-15
- **対象**：`src/env_boot.py`（修正版・SHA256 改行正規化後＝`c121788af18ba3c981efbbbec35eda624b0ff0860204ccee59d37d7f14bb587c`）
- **レビュアー**：ブラウザ版 ChatGPT **GPT-5.6 Sol**（推論「高い」・1m35s思考）
- **依頼文**：`src/checkdata/external_reviews/_requests/review_env_boot.md`
- **採録方法**：ブラウザ応答をJS(textContent)で忠実採録。

---

判定：NO-GO　モデル：GPT-5.6 Sol

## [CRITICAL] #1 旧APIが「全秘密の一括注入」を再開通させている
- コメントは「旧API名（引数なしは何もしないよう変更）」だが**実装は逆**：
  ```python
  def hydrate_from_registry(keys=KEYS):
      return hydrate(keys)
  ```
- 旧コードに `hydrate_from_registry()` が1箇所でも残れば、KEYS 全ての未設定キーを再び os.environ に注入。
  env= を明示せず起動した子プロセス(git/ffmpeg)は親環境を継承（subprocess仕様）。
- **今回の主眼 #2（必要キーのみhydrate）を後方互換APIがそのまま迂回。コメントと実装が正反対で見落としやすい危険な回帰。**

## [HIGH] #2 TOCTOU（#5）は「緩和」だけで保証は不成立
- `if name in os.environ: continue` の2回目チェックと代入も別操作。
  Thread A:2回目 in→False／Thread B:`os.environ[name]="explicit"`／Thread A:`os.environ[name]=registry値` で上書きし得る。
- 「絶対に上書きしない」を強い契約と称するなら不十分。

## [MEDIUM] #3 encoding：env_boot単体では完全なI/O契約でない
- 「子だけUTF-8」はproducer/consumer mismatchに置き換わるだけ。self-testの機械判定部はASCII限定にし stdout.reconfigure 不要にするのが頑健。親側 subprocess(encoding="utf-8") までCIで固定すべき。

## [MEDIUM] #4 _ERRORS が「現在状態」でなく「履歴」＝stale errorで偽陽性
- transient error→回復後も `_ERRORS` に旧エラーが残る。`if env_boot._ERRORS: FAIL` とすると現在正常でもFAIL。同一入力でも過去依存＝非決定。
- 「last operation snapshot」と「history」を分離すべき。エラーは呼び出しの戻り値で返すのが本筋。

## [MEDIUM] #5 inject=False の「副作用なし」がdocと不一致
- docstringは「副作用なしの点検用」だが、エラー時 `_ERRORS.append(...)` を実行＝モジュール状態を変更。pureだと思って何度も呼ぶと履歴依存の回帰要因。

## [MEDIUM] #6 CLIは実レジストリ障害を検出しても exit 0
- 通常実行は `if _ERRORS: print(...)` だけで非0にしない。全OpenKey障害でも rc=0。

## 追加すべきself-test
- `hydrate_from_registry()`（実装後）が _from_registry を呼ばないTOCTOU競合テスト／inject=Falseの状態非変更テスト／transient error→success で stale error が残らないテスト／REG_SZ・REG_EXPAND_SZ・unsupported type の _read_value 実テスト／CLI infra error→exit nonzero テスト。

## 総括
空文字バグ・型制限・import時自動注入廃止は反映済み。しかし **hydrate_from_registry(keys=KEYS) が過剰伝播対策を直接迂回**していることと、**二重inがTOCTOU保証になっていない**ことの2点で、現SHA `c121788a…` を「CIで署名・強制する信頼できる版」として登録するのは **NO-GO**。
