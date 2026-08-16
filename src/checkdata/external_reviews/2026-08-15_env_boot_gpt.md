# 外部AI敵対レビュー記録：src/env_boot.py

- **日付**：2026-08-15
- **対象**：`src/env_boot.py`（SHA256 改行正規化後＝`c4092572da9f3a89658f86975b305d93c133af41997a1f4a121b8091f53a3493`）
- **レビュアー**：ブラウザ版 ChatGPT **GPT-5.6 Sol**（推論「高い」・55s思考）
- **依頼文**：`src/checkdata/external_reviews/_requests/review_env_boot.md`
- **採録方法**：ブラウザ応答をget_page_text/JS抽出で忠実採録（Claudeが手貼りで転記したものではない）。

---

判定：NO-GO

モデル正式名：GPT-5.6 Sol

## 最重要の欠陥：HIGH — 「既存の環境変数は上書きしない」という明示契約を破る
- 判定が `if os.environ.get(name):` になっているため、**キーは存在するが値が空文字 `""` の場合を「存在しない」と誤判定**する。
- 具体例：`os.environ["OPENAI_API_KEY"] = ""` かつ HKCU\Environment の `OPENAI_API_KEY` に実キーがある状態。
- 本来の契約では「プロセス環境に既にキーがあるので何もしない」であるべきところ、実装は**レジストリの秘密値を os.environ に注入**する。
- したがって、意図的に空値を設定して「このプロセスでは OpenAI を無効化する」という**上位側の意思まで破壊**できる。
- **修正必須**：
  ```python
  if name in os.environ:
      continue
  ```
  「存在」と「truthy」を混同してはいけない。

## 追加の欠陥

### HIGH — 秘密の子プロセスへの過剰伝播
- import しただけで `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` 等を**グローバルな os.environ に一括注入**する。
- その後このプロセスが起動する git / ffmpeg / テストツール / AI CLI / 任意の補助スクリプト等は、`env=` を明示的に絞らない限りそれらを継承する。
- 「必要な provider のキーだけ」でなく `KEYS` 全体を hydrate するので、OpenAI しか使わない処理が Anthropic/Gemini の資格情報まで子へ渡す状態になり得る。＝重点脅威(3)は不合格。
- 修正案：グローバル hydrate ではなく「必要なキーのみ指定」、可能なら dict を返して必要な subprocess の env にだけ合成する設計にする。

### MEDIUM — レジストリアクセス異常が安全な no-op と区別不能（サイレント失敗）
- `except Exception: return []`（winreg import）／`except OSError: continue`（QueryValueEx）／`except OSError: return injected`（OpenKey）が**すべて無言で []/continue に潰れる**。
- 「HKCU\Environment が存在しない」と「アクセス拒否」「レジストリ I/O 異常」「想定外の winreg import 異常」が、呼び出し側から同じ `_INJECTED == []` に見える。
- FileNotFoundError とその他の OSError を分離し、後者を観測可能に。`except Exception` は撤去または極小化する。

### MEDIUM — レジストリ型を完全に無視
- `REG_DWORD` 等が誤登録されていても `"123"` のように文字列化し、`_INJECTED` に正常注入として記録される。
- `REG_EXPAND_SZ` に `%USERPROFILE%\...` の値が入るケースは生値が入り得る。特に `GOOGLE_APPLICATION_CREDENTIALS` で壊れたパスになる可能性。
- 許容型を `REG_SZ`/`REG_EXPAND_SZ` に限定し、後者は展開規則を明文化。異常型を「注入成功」にしない。

### MEDIUM — check→QueryValueEx→set に TOCTOU
- 存在確認後から代入までの間に別スレッド等が `os.environ[name]` を設定すると、その新値をレジストリ値で上書きできる。
- `hydrate_from_registry()` は公開関数として再実行可能なので、「絶対に上書きしない」という強い契約には反する。
- 少なくとも QueryValueEx 後にもう一度 `if name in os.environ: continue` と確認すべき。

### MEDIUM — 「注入を必ず明示」はこのファイル単独では保証していない
- `_INJECTED` にキー名を残すのは観測可能にしただけで、表示を強制していない。呼び出し側が無視すれば無言で注入され得る。

## 結論
最重要保証「既にある環境変数は上書きしない」が**反例1つ（空文字）で破れる**ため、署名manifestに固定しCIで「信頼できる検証コード」として強制する段階には達していない。まず `os.environ.get()` による存在判定を修正した版を再レビュー対象にすべき。**＝NO-GO。**
