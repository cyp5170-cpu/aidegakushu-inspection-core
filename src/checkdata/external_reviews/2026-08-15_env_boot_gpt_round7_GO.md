# 外部AI敵対レビュー記録：src/env_boot.py（round7＝v7・**GO**）

- **日付**：2026-08-15
- **対象**：`src/env_boot.py` v7（per-key最小設計・SHA256＝`cb5a48b50715ad166c76f29ad7a421bc3950affb52616cd97aba6478471063b8`）
- **レビュアー**：ブラウザ版 ChatGPT **GPT-5.6 Sol**（推論「高い」・1m54s思考）
- **判定：GO**（7ラウンド目。round1〜6の全指摘＝空文字/型/注入廃止/旧API/case/列挙TOCTOU/REG_EXPAND stale/
  resolve握り潰し/self-test境界 を反映し収束）

---

判定：GO　モデル：GPT-5.6 Sol

## 残差（いずれもGO非阻害）
- **[MEDIUM] self-test の「副作用ゼロ」検査に import-time の盲点**：`_selftest()` 冒頭で `env_before=dict(os.environ)`
  を取るため、将来モジュールトップレベルに `os.environ[...]=...` の回帰が入っても、書換え後に env_before を取るので
  末尾比較が一致し PASS し得る。＝「この版が read-only」は確認できるが「将来の import-time 汚染を必ず検出」は保証しない。
  （現在の実装自体には os.environ 書換えは無い。）
- **[LOW] resolve_ex の (value,error) 契約は"あらゆる"レジストリ障害を tuple 化はしない**：OpenKey/QueryValueEx の通常失敗は
  OSError 系で妥当に捕捉。ただし Python audit hook 等が非OSError(RuntimeError等)を投げると resolve_ex から例外として漏れる。
  偽の緑にはならず fail-closed なので重大性は低い。

## 重点観点の合格確認（GPT明記）
- 偽陰性：危険なレジストリ型・アクセス障害を正常値扱いする経路なし。REG_EXPAND_SZ とその他型は明示的に拒否。
- 偽陽性：値/Environmentキー不在は FileNotFoundError→(None,None) で正しく"未設定"化。
- 空文字：env の "" も registry の "" も"設定済み"として保持。

## 帰結
現SHA `cb5a48b5…` は GPT-5.6 Sol が **GO**。恒久ルール（OpenAI必須＋強AI）に基づき、次は Gemini の第2意見を取り、
両GOなら `--register`→`--gen-manifest`→署名 の段へ。MEDIUM/LOW は将来の軽微強化として記録（本GOは非阻害）。
