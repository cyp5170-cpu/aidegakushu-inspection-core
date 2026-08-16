# 外部AI敵対レビュー記録：src/env_boot.py（round3＝v3再レビュー）

- **日付**：2026-08-15
- **対象**：`src/env_boot.py` v3（SHA256 改行正規化後＝`ffb4a0a1bca5cb577fc076311664a44d45a2a1bae0500ff5812657ed98a985a1`）
- **レビュアー**：ブラウザ版 ChatGPT **GPT-5.6 Sol**（推論「高い」・1m18s思考）
- **採録方法**：ブラウザ応答をJS(textContent)で忠実採録。

---

判定：NO-GO　モデル：GPT-5.6 Sol

## [HIGH / 偽陽性・契約違反] 「レジストリ不在は安全な no-op」を実装が破る
- Windows で `HKCU\Environment` 自体が無い状態で `hydrate(["OPENAI_API_KEY"])` を呼ぶと、
  `_from_registry()` が `(None, "no-Environment-key")` を返し、正常な「補完元なし」が errors 扱いに。
  CLI `sweep()` ではエラーとなり **exit 1**。docの「レジストリ不在での安全な no-op」と正面矛盾。
- 修正：`except FileNotFoundError:` は `return None, None` にすべき。

## [HIGH / 偽陰性・stale] REG_EXPAND_SZ の展開が「古いプロセス環境」に依存し得る
- `winreg.ExpandEnvironmentStrings()` は %NAME% を"その時点のプロセス環境変数値"で展開する。
  例：レジストリ `BASE=C:\new` / `GAC=%BASE%\key.json` でも、古い親が `BASE=C:\old` を保持していると
  `C:\old\key.json` を「正常値」として注入し得る（＝まさに直したい stale 環境で汚染）。
  未定義 %NAME% も未展開のまま正常文字列として受理してしまう。
- 修正：ExpandEnvironmentStrings任せにせず、HKCU Environment を1回スナップショット化し、既存os.environ優先＋
  不足値を同一snapshotから明示展開。循環参照・未解決 %VAR% は error に。

## [HIGH / 秘密伝播面の拡大] hydrate() は秘密を親 os.environ に恒久注入する
- 対象subprocessだけでなく、その後親が起動する全ての通常子プロセスへ継承され得る。
- 修正：秘密用途は os.environ 直接変更を主経路にせず、`build_child_env(names)` のように**対象subprocessにだけ渡す
  env dict を返す**設計を推奨。os.environ 注入を残すなら「以後すべての通常子プロセスへ継承され得る」と契約上明示。

## [MEDIUM] self-test は #1/#2 を検出できず（検出力不足）／実レジストリ統合テストが無い
- Windows runner 上で一時キー/値を使い REG_SZ・REG_EXPAND_SZ・キー不在・値不在・非文字列型・既存env優先 を通すべき。

## [MEDIUM] 通常CLIのエンコーディング契約
- --self-test はASCII化済みだが、通常CLIは stdout を UTF-8 強制後に日本語出力。親が cp932 の subprocess(text=True) だと
  decode failure/mojibake の余地。通常CLIも全経路ASCIIにするか UTF-8 を明示的外部契約に。

## その他の修正提案
- `resolve()` は削除するか、error時に例外を送出する fail-closed に（無視したい呼出しだけ resolve_ex の error を捨てる形）。

## 帰結
v1/v2 の指摘（空文字・型・import自動注入廃止・旧API削除）は反映済み。しかし
**(a) レジストリ不在の誤エラー化(#1)** と **(b) os.environ 注入による子への伝播という設計の芯(#3)**、
**(c) REG_EXPAND_SZ の stale 展開(#2)** が残るため v3 SHA `ffb4a0a1…` は NO-GO。
※(#3) は「Windows登録レジストリ→os.environ注入でSDKに読ませる」という env_boot の設計思想そのものへの根本問い＝
  build_child_env 方式へ寄せる大きめの設計変更を要する。要ユーザー判断。
