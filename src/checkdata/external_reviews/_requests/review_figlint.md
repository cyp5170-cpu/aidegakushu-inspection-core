# 外部AI敵対レビュー依頼：`src/figlint.py`

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
図レイアウトの決定論リンター（ラベル重なり／見切れ／小文字／ラベル×図形WARN／bbox0=未計装FAIL）。毎生成・毎ビルドで実走。

## このファイル固有の脅威（重点的に突く）
1. 未計装の図での『偽の緑』（bbox0 検知の穴・計装漏れの見逃し）。
2. ロケーター／合成カード（_compose_locator 等）の取りこぼし。
3. 図生成時の例外を未検査でスルーして PASS 扱いにしていないか。

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


## レビュー対象コード：`src/figlint.py`
- SHA256（改行正規化後・ゲートの署名対象と同一計算）：`40a8f54a33d312d7f4766d8f099d6737318fec6e3f05233b1c8c96cbf7eefe4b`
- ↓このコード全文をレビューしてください。

```python
# -*- coding: utf-8 -*-
"""figlint ― 図レイアウトの決定論リンター（Claude専有・src/）。

目的＝「ラベルが重なる/隠れる/見切れる/小さすぎる」クラスを、私の記憶や目視でなく
**機械が毎回止める**強制チェックにする（受動的な文書頼みを卒業。2026-08-14 ユーザー要望）。
LLM(figcheck)と違い決定論・無料・高速で、同じ入力に同じ判定。

仕組み：gen_medical_schematics の `lbox`/`ball_lbl` が描画時にbbox(枠)を`_LINT`へ記録。
figlintはlint対象のgen関数を録画モードで呼び、集めたbboxで下記を判定する。

検知クラス：
  [FAIL] label_overlap  … ラベル同士が有意に重なる（例：細胞内 × TPO（酵素））
  [FAIL] label_covers_atom … ラベルが元素球を覆う（例：ヨウ素ラベルが I- 球に被る）
  [FAIL] clipped        … ラベル枠がキャンバス外へ見切れる
  [WARN] small_font     … ラベル文字がスマホ可読の下限未満

限界（正直に）：ラベルと"任意の描画図形(環/膜/酵素本体)"の重なりは未追跡＝figcheck(LLM視覚)で補完。
用法：py src/figlint.py            （TPO/NIS簡易図をlint・FAILがあればexit 1）
      py src/figlint.py --adversarial  （わざと壊した図で検知力を自己テスト）
"""
import os, sys, itertools

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windowsコンソール(cp932)で✓/絵文字が化けないように
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_medical_schematics as G

W, H = 1600, 900            # 簡易図のキャンバス
OVL_TOL = 80.0              # ラベル同士：この面積(px^2)超の重なりでFAIL（微接触は許容）
ATOM_COVER = 0.30           # ラベルが原子面積のこの割合超を覆えばFAIL
MIN_FONT = 22               # スマホ可読の下限(px)
MARGIN = 1.0                # キャンバス見切れ判定の許容


def _area(b):
    return max(0.0, b[2]-b[0]) * max(0.0, b[3]-b[1])

def _ovl(a, b):
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1-ix0) * (iy1-iy0)


def lint_boxes(boxes, w=W, h=H):
    """記録されたbboxリストからfindingsを返す。各finding=(sev, cls, msg)。"""
    labels = [b for b in boxes if b["kind"] == "label"]
    atoms  = [b for b in boxes if b["kind"] == "atom"]
    out = []
    # ① ラベル同士の重なり
    for a, b in itertools.combinations(labels, 2):
        ar = _ovl(a["box"], b["box"])
        if ar > OVL_TOL:
            out.append(("FAIL", "label_overlap",
                        f"ラベルが重なる: 「{a['text']}」×「{b['text']}」(重なり{int(ar)}px²)"))
    # ② ラベルが原子球を覆う
    for lb in labels:
        for at in atoms:
            aa = _area(at["box"])
            if aa <= 0:
                continue
            if _ovl(lb["box"], at["box"]) > ATOM_COVER * aa:
                out.append(("FAIL", "label_covers_atom",
                            f"ラベルが原子を覆う: 「{lb['text']}」が球「{at['text']}」に被る"))
    # ③ 見切れ（キャンバス外）
    for lb in labels:
        x0, y0, x1, y1 = lb["box"]
        if x0 < -MARGIN or y0 < -MARGIN or x1 > w+MARGIN or y1 > h+MARGIN:
            out.append(("FAIL", "clipped",
                        f"ラベルが見切れ(枠外): 「{lb['text']}」box=({int(x0)},{int(y0)},{int(x1)},{int(y1)}) / canvas={w}x{h}"))
    # ④ 小さすぎる文字
    for lb in labels:
        if 0 < lb["font"] < MIN_FONT:
            out.append(("WARN", "small_font",
                        f"文字が小さい: 「{lb['text']}」{lb['font']}px < {MIN_FONT}px(スマホ可読)"))
    # ⑤ ラベルが図形(臓器/環/膜等)に被る＝WARN（意匠上の軽い重なりは許容するため閾値高め・FAILにしない）
    shapes = [b for b in boxes if b["kind"] == "shape"]
    for lb in labels:
        for sh in shapes:
            ov = _ovl(lb["box"], sh["box"])
            if ov > OVL_TOL * 2:
                out.append(("WARN", "label_over_shape",
                            f"ラベルが図形に被る: 「{lb['text']}」が「{sh['text']}」に重なる(重なり{int(ov)}px²)"))
    return out


def lint_figure(gen_func, name):
    """gen関数を録画モードで呼び、findingsを返す。gen関数は図PNGも保存する（副作用・冪等）。"""
    G._LINT["on"] = True
    G._LINT["nosave"] = True     # lint中は図PNGを保存しない＝mtimeを乱さず合成キャッシュを無効化しない
    G._lint_reset()
    err = None
    try:
        gen_func()
    except Exception as e:       # 図生成が壊れても"未検査でスルー"にせず、FAILとして表に出す（敵対的レビューで発見）
        err = e
    finally:
        boxes = list(G._LINT["boxes"])
        G._LINT["on"] = False
        G._LINT["nosave"] = False
    findings = lint_boxes(boxes)
    if err is not None:
        findings.insert(0, ("FAIL", "gen_crashed", f"図生成が例外で失敗＝レイアウト未検査: {err}"))
    if not boxes and err is None:   # bbox0＝この図は未計装/未検査＝"偽の緑"を防ぐためFAIL（多AI提言・2026-08-15）
        findings.insert(0, ("FAIL", "no_coverage", "bbox 0件＝figlint未計装/未検査。『緑』を信用不可（figcheck+人で検品）"))
    return {"name": name, "n_label": sum(1 for b in boxes if b["kind"] == "label"),
            "n_atom": sum(1 for b in boxes if b["kind"] == "atom"),
            "findings": findings}


def lint_locator_cards():
    """ロケーターカード(build_ymm4._compose_locator)もlint＝"偽の緑"潰し。代表specで検査。
    _compose_locatorのラベル/臓器図bboxは build_ymm4 が gen_medical_schematics._lintreg 経由で記録する。"""
    import sys as _sys
    # build_ymm4の中から呼ばれた場合は__main__がそれ＝再importしない（再import はstdout閉鎖等の副作用を起こす）
    BW = _sys.modules.get("build_ymm4")
    if BW is None:
        _main = _sys.modules.get("__main__")
        if _main is not None and hasattr(_main, "_compose_locator") and hasattr(_main, "COMPOSITIONS"):
            BW = _main
    if BW is None:   # 単体起動(py src/figlint.py)＝新規import
        _saved = _sys.argv
        try:
            _sys.argv = ["figlint", "--dir", "episodes/iodine/ep01"]   # EP_ROOT解決用（_compose_locatorはDB参照のみ）
            import build_ymm4 as BW
        except Exception as e:
            return [{"name": "ロケーターカード", "n_label": 0, "n_atom": 0,
                     "findings": [("WARN", "import_fail", f"build_ymm4 import不可でロケーター未検査: {e}")]}]
        finally:
            _sys.argv = _saved
    targets = [("ロケーター:甲状腺(のどの下)", "ep01_butterfly_thyroid_anatomy_3d"),
               ("ロケーター:甲状腺(なぜ濃縮)", "ep01_why_only_thyroid_concentrates_3d")]
    reports = []
    for name, kw in targets:
        spec = BW.COMPOSITIONS.get(kw)
        if not spec:
            continue
        G._LINT["on"] = True; G._LINT["nosave"] = True; G._lint_reset()
        err = None
        try:
            BW._compose_locator(spec)
        except Exception as e:
            err = e
        finally:
            boxes = list(G._LINT["boxes"]); G._LINT["on"] = False; G._LINT["nosave"] = False
        findings = lint_boxes(boxes, w=1920, h=1080)   # ロケーターは1920x1080で合成（簡易図の1600x900と別）
        if err is not None:
            findings.insert(0, ("FAIL", "gen_crashed", f"合成が例外＝未検査: {err}"))
        if not boxes and err is None:
            findings.insert(0, ("FAIL", "no_coverage", "bbox 0件＝未計装/未検査"))
        reports.append({"name": name,
                        "n_label": sum(1 for b in boxes if b["kind"] == "label"),
                        "n_atom": sum(1 for b in boxes if b["kind"] == "atom"),
                        "findings": findings})
    return reports


# ビルド/ゲートから呼ぶ対象＝本編で使う簡易図
BUILD_FIGURES = [("TPO機構_模式図_simple", "gen_tpo_simple"),
                 ("NIS機構_模式図_simple", "gen_nis_simple")]


def lint_build_figures():
    """(ok, reports) を返す。okはFAILゼロ。"""
    reports = []
    for name, fn in BUILD_FIGURES:
        gen = getattr(G, fn, None)
        if gen is None:
            reports.append({"name": name, "n_label": 0, "n_atom": 0,
                            "findings": [("WARN", "missing_gen", f"{fn} が無い")]})
            continue
        reports.append(lint_figure(gen, name))
    reports.extend(lint_locator_cards())   # ロケーターカードも検査（"偽の緑"潰し）
    ok = not any(s == "FAIL" for r in reports for (s, _c, _m) in r["findings"])
    return ok, reports


def _print_reports(reports):
    n_fail = n_warn = 0
    for r in reports:
        print(f"\n■ {r['name']}  (label {r['n_label']} / atom {r['n_atom']})")
        if not r["findings"]:
            print("   ✅ レイアウトOK（重なり/見切れ/小文字なし）")
        for sev, cls, msg in r["findings"]:
            mark = "🔴" if sev == "FAIL" else "🟡"
            print(f"   {mark} [{sev}/{cls}] {msg}")
            n_fail += (sev == "FAIL"); n_warn += (sev == "WARN")
    print("\n" + "="*60)
    print(f"figlint: FAIL {n_fail} / WARN {n_warn}")
    # 誤った安心の防止＝守備範囲を毎回明示（緑でも"全図OK"ではない）
    print("※守備範囲＝gen_medical_schematicsのTPO/NIS簡易図の[ラベル重なり/見切れ/小文字](決定論)。")
    print("  対象外＝ロケーター/duo等のカード(build_ymm4)・文字コントラスト・ラベルと図形(環/膜等)の重なり・配色の妥当性")
    print("  →これらは figcheck(Vertex/LLM) と人の目で（例:『甲状腺』ラベルのコントラストはfiglint対象外）。")
    return n_fail


def _adversarial():
    """自己テスト＝わざと壊したbboxで、各検知クラスが確実に発火するか（＋クリーンは素通り）を検証。"""
    print("===== figlint 敵対的自己テスト =====")
    cases = [
        ("clean(重ならない2ラベル)", [
            {"kind": "label", "box": (100, 100, 300, 160), "text": "A", "font": 30},
            {"kind": "label", "box": (100, 200, 300, 260), "text": "B", "font": 30},
        ], {"label_overlap": 0, "label_covers_atom": 0, "clipped": 0, "small_font": 0}),
        ("label_overlap", [
            {"kind": "label", "box": (100, 100, 300, 160), "text": "細胞内", "font": 30},
            {"kind": "label", "box": (150, 120, 350, 180), "text": "TPO（酵素）", "font": 30},
        ], {"label_overlap": 1}),
        ("label_covers_atom", [
            {"kind": "label", "box": (700, 300, 900, 340), "text": "ヨウ素（I-）", "font": 30},
            {"kind": "atom", "box": (780, 300, 824, 344), "text": "I-", "font": 0},
        ], {"label_covers_atom": 1}),
        ("clipped(枠外)", [
            {"kind": "label", "box": (-40, 820, 120, 860), "text": "細", "font": 30},
        ], {"clipped": 1}),
        ("small_font", [
            {"kind": "label", "box": (100, 100, 300, 130), "text": "小さい注記", "font": 16},
        ], {"small_font": 1}),
        ("atom同士は許容(クラスタOK)", [
            {"kind": "atom", "box": (800, 350, 844, 394), "text": "I-", "font": 0},
            {"kind": "atom", "box": (820, 350, 864, 394), "text": "I-", "font": 0},
        ], {"label_overlap": 0, "label_covers_atom": 0}),
        ("label_over_shape(ラベルが臓器図に被る)", [
            {"kind": "label", "box": (1000, 300, 1200, 360), "text": "甲状腺", "font": 30},
            {"kind": "shape", "box": (1050, 320, 1400, 700), "text": "臓器図", "font": 0},
        ], {"label_over_shape": 1}),
    ]
    allok = True
    for title, boxes, expect in cases:
        got = lint_boxes(boxes)
        cnt = {}
        for _sev, cls, _msg in got:
            cnt[cls] = cnt.get(cls, 0) + 1
        ok = all(cnt.get(k, 0) == v for k, v in expect.items())
        allok &= ok
        print(f"  {'✓' if ok else '✗'} {title}: 期待{expect} 実{cnt}")
    print("\n" + ("🟢 敵対的自己テスト PASS" if allok else "🔴 敵対的自己テスト FAIL"))
    return allok


if __name__ == "__main__":
    if "--adversarial" in sys.argv:
        sys.exit(0 if _adversarial() else 1)
    ok, reports = lint_build_figures()
    nf = _print_reports(reports)
    print("🟢 図レイアウト合格" if nf == 0 else "🔴 図レイアウトに要修正（上記FAIL）")
    sys.exit(0 if nf == 0 else 1)
```
