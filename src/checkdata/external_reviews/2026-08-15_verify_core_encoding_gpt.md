# 外部AI敵対レビュー記録：verify_core エンコーディング修正

- **日付**：2026-08-15
- **レビュアー**：ブラウザ版 ChatGPT（OpenAI・推論設定「高い」／Web検索でPython3.14公式仕様を裏取り）
  - ⚠**正式モデルIDは未確認**（会話ヘッダーが折りたたまれモデルセレクタをツリーから読めず。憶測回避のため未記載＝恒久ルール「モデル版必ず記録」に対する既知の穴。次回セレクタを開いて確定する）
- **対象**：`src/verify_core.py`（検証強制フレームワークのプロジェクト非依存コア＝「純粋・移植可」契約）
- **依頼者の自己レビュー**：Claude（Opus 4.8）が先に自己敵対レビューし「import時副作用＝純粋契約違反」1件を発見・是正した上で外部レビューへ回した。

## 元のバグ
CLI self-testが絵文字🧪をprintするが、**stdoutがパイプ（cp932ロケール）だとUnicodeEncodeErrorでクラッシュ→rc=1**。
親のメタ検品`check_system`がsubprocess(text=True, encoding="utf-8")で呼び「検証コアが壊れている(rc=1)」と誤検知していた。実際は検証ロジックは健全＝出力エンコーディング事故。

## 却下した修正（Claude第1案）
モジュール冒頭に `try: sys.stdout.reconfigure(encoding="utf-8") except Exception: pass` →import時副作用で純粋契約違反。自己レビューで却下。

## 採用しようとした修正（Claude第2案）＝**GPT判定：NO-GO**
`if __name__ == "__main__":` 内に `reconfigure` を移動＋`except Exception: pass`。

## GPTの指摘（重大度付き）
| 重大度 | 指摘 |
|---|---|
| 🔴高 | `_selftest()`をimportして呼ぶ経路は未修正＝そこでは依然クラッシュ |
| 🔴高 | **stderr未UTF-8化**。親がstdout/stderr両方をutf-8デコードするのに子はstdoutのみ→tracebackの日本語がcp932バイトで出て**親がUnicodeDecodeError**（子のEncodeErrorを親のDecodeErrorにすり替えるだけ） |
| 🔴高 | `except Exception: pass`が**インフラ不全(flush I/O障害等)をvalidation失敗と混同して黙殺**。修正失敗を検知したのに修正前と同じ危険経路へ進む |
| 🔴高 | **rc=1が「検証失敗」と「出力エンコード事故」を混同**＝本当の設計事故。`0=PASS/1=self-test FAIL/2=infra ERROR`へ分離すべき |
| 🔴高 | 個別ファイル修正はモグラ叩き。恒久策は**「親(check_system)が子の`PYTHONIOENCODING=utf-8`を固定」**（stdout/stderr両方・全CLIに一律） |
| 中 | `reconfigure`はfd直書き/buffer.writeを防げない／親の`errors="replace"`は文字化けを正常化する悪手（`UnicodeDecodeError→HARNESS_FAILURE`と明示分類を） |
| 低 | `errors='strict'`のままではlone surrogateで再発／SystemExit後のflush失敗でexit codeが120に化ける |
| 論破 | Claude提案「絵文字printの静的lint」は**対症療法**。`print('検証完了')`は絵文字なしでもcp932↔utf-8ミスマッチで壊れる＝根因は絵文字でなくI/O契約 |
| 重要 | Python3.14ではWindowsの**対話コンソールはUTF-8**、**PIPE等の非コンソール出力はロケール(cp932)**＝今回は「コンソール事故」でなく「PIPE事故」 |

**GPT優先修正順**：①`_selftest()`からprint排除(純粋・表示はCLI adapter) ②check_system側で子`PYTHONIOENCODING=utf-8`固定 ③exit code分離 ④`except Exception: pass`削除。PYTHONUTF8=1は範囲広すぎ(filesystem/open()も変わる)で後回し。

## 判定：**NO-GO**（第2案）

## Claudeの対応（2026-08-15）
GPT最優先②を採用＝**境界での恒久策**を実装：
- `check_system._run` / `run_preship_qa._run` に `env={**os.environ, "PYTHONIOENCODING":"utf-8"}`（子stdout/stderr両方をUTF-8化＝親のutf-8デコードと一致。`{**os.environ}`複製でenv_boot注入鍵を子へ継承）。
- `verify_core`の第2案を**撤回**し純粋モジュールへ復帰（printのエンコーディングは親が契約を固定する設計）。
- 検証：`check_system`でverify_core🟢・medcheck🟢（鍵継承）・exit0。

## 未対応（follow-up＝正直な残債）
- GPTは**第2案**をレビューした。**最終の境界修正コード（上記）はまだGPT再レビュー未実施**＝external_review_gateではWARN債務として表出させる。
- exit code 0/1/2分離／`_selftest()`のprint→return純粋化は未実装（設計として妥当・別タスク）。
