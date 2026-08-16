# 外部AI敵対レビュー記録：src/env_boot.py（round4＝v4「本格改修」再レビュー）

- **日付**：2026-08-15
- **対象**：`src/env_boot.py` v4（読取専用resolve版・SHA256＝`409cd570b77ffaeae34df825af9aeb4a906e9882ae776a6bdc0dbd7958aa551a`）
- **レビュアー**：ブラウザ版 ChatGPT **GPT-5.6 Sol**（推論「高い」・1m56s思考）
- **採録方法**：ブラウザ応答をJS(textContent)で忠実採録。

---

判定：NO-GO　モデル：GPT-5.6 Sol

## [CRITICAL / サイレント失敗・偽陰性] `_snapshot()` が EnumValue の全OSErrorを「列挙終了」と握り潰す
- `except OSError: break` は fail-open。数個読んだ後に EnumValue がI/O異常等を返しても、途中までの snap を
  完全snapshotとして `err=None` で返す→後半の OPENAI_API_KEY 等が missing 扱い、sweep() も exit0 になり得る。
- 列挙終了は **ERROR_NO_MORE_ITEMS(259)** のみ。それ以外のエラーコードと区別すべき。これ単独で NO-GO。

## [HIGH / TOCTOU・非決定性] 「1回スナップショット」契約が build_child_env()/sweep() で不成立
- `resolve_ex(name)` が毎回 `_snapshot()` を呼ぶため、複数キーはキーごとに別時点のHKCUを読む。
  取得中に setx されると世代Aのキーと世代Bのモデルが1つのenvに混在し得る。docstringの「同一snapshot」と実装が矛盾。

## [HIGH / 秘密の過剰伝播] build_child_env() は「必要な秘密だけ」を渡す保証でない
- 既定 `env = dict(os.environ...)` で全os.environをコピー→「その子だけに必要キー」になっていない。

## [HIGH / base契約不整合] build_child_env(base=...) の展開が base でなく global os.environ を見る
- 親 `_ROOT=C:/parent` / base `_ROOT=D:/child` / Registry `KEY=%_ROOT%/key.json` で、
  子envは `_ROOT=D:/child` なのに `KEY=C:/parent/key.json` と自己矛盾。base明示APIとして実バグ。
  `_expand()` 内の `key in snap` も同種の問題（os.environ空文字を未設定に落とす等）。

## [MEDIUM / self-test偽陽性・副作用] `_selftest()` が環境を完全隔離・復元していない
- テストキーの元値を保存せず pop()＝呼出し前の値を破壊。事前除去もしないので、CIに偶然同名があると
  os.environ優先経路に入りテスト結果が変わる＝「決定論的self-test」契約も厳密には不成立。

## [CONTRACT-CRITICAL] 依頼文の「役割」説明と実装が矛盾（＝Claudeの生成器 FILE_NOTES 未更新）
- 依頼文は「os.environ へ注入し _INJECTED で明示」と旧仕様のまま。コードは注入せず _INJECTED も無い。
  → `gen_review_requests.py` の env_boot 役割テキストを現行(read-only resolve版)に更新する必要（実装は正しく、
    説明文の更新漏れ）。

## 帰結
v1〜v3の指摘（空文字・型・注入廃止・旧API削除・展開・不在no-op）は反映済み。しかし v4 で新たに
EnumErrエラー握り潰し(CRITICAL)＋snapshot契約/TOCTOU＋build_child_envの過剰コピー/base不整合＋self-test隔離＋
依頼文役割の旧仕様残り、が出たため NO-GO。
※4ラウンド連続で「実バグ＋契約/実装の食い違い」が出続けている＝env_bootは小さいが登録レジストリ操作の
  エッジが多く、収束に方針判断が要る（要ユーザー：硬化継続 vs 大幅簡素化 vs CRITICAL/HIGHのみ直し残差は人が受理）。
