# env_boot 外部AI敵対レビュー：**両AI GO**（登録用まとめ）

- **対象ファイル**：`src/env_boot.py` v7（per-key最小設計・SHA256＝`cb5a48b50715ad166c76f29ad7a421bc3950affb52616cd97aba6478471063b8`）
- **判定：GO**（OpenAI必須＋強AIの両方で独立に一致）
- **モデル名（登録記録用の正式表記）**：GPT-5.6 Sol / Gemini Pro

## レビュアーと判定
- **ChatGPT GPT-5.6 Sol**：**GO**（7ラウンドで収束）。記録＝`2026-08-15_env_boot_gpt_round7_GO.md`
  （残差 MEDIUM/LOW のみ・GO非阻害。偽陰性なし／REG_EXPAND_SZ拒否／空文字尊重／不在→(None,None) を明記合格）
- **Gemini Pro**（self-report 1.5 Pro）：**GO**。記録＝`2026-08-15_env_boot_gemini_GO.md`
  （残差 LOW のみ・GO非阻害。check-then-get の KeyError 競合＝単一スレッドimport前提で緩和）

## 収束の経緯（監査用）
round1〜6 の全指摘（空文字契約・型検証・os.environ注入廃止・旧API削除・case非依存・列挙TOCTOU・
REG_EXPAND stale・resolve握り潰し・self-test境界）を反映。**per-key最小設計**（1キーずつ RegQueryValueEx・
REG_SZのみ許可・自前展開/列挙を撤廃）への作り直しが収束の決め手。記録＝`2026-08-15_env_boot_gpt_round{1..7}*.md`。

## 残差（両GO非阻害・将来の軽微強化）
- [MEDIUM] self-test の env_before 取得タイミング（import-time 汚染の将来回帰を検出しきれない）。
- [LOW] resolve_ex の os.environ アクセスを `.get()` にすると check-then-get の KeyError 競合を塞げる。
- [LOW] 非OSError（audit hook 等）は resolve_ex から例外として漏れ得る（fail-closed なので低）。
→ これらは次回 env_boot に手を入れる際にまとめて対応（対応すると再レビュー要のため、本GO SHA は現状維持）。
