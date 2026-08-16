# -*- coding: utf-8 -*-
"""check_system ― 検品システム自体の検品（メタ検品・Claude専有）。

思想（2026-08-14 ユーザー要望）：
  ・**検品システムが壊れていること自体を"サイレント"にしない**。各柱が生きているか自己診断し、
    壊れ/未設定を**明示ERROR＋exit非ゼロ**で検知する（＝"検品が動いていないのに緑"を防ぐ）。
  ・APIキー未設定・インフラ故障は「まあいっか」で流さず、必ず表に出す。

診断する柱：
  [CRITICAL] 提出前ゲート self-test（既知エラー回帰）   … API不要・必ず通るべき
  [CRITICAL] figlint 敵対的自己テスト（図レイアウト検知） … API不要・必ず通るべき
  [CRITICAL] figlint 実図（TPO/NIS の重なり/見切れ）      … API不要・FAILゼロであるべき
  [REQUIRED] medcheck の判定脳＝ANTHROPIC_API_KEY         … 無ければ判定不能＝ERROR
  [REQUIRED] MediSearch＝MEDISEARCH_API_KEY               … 無ければ医療AI裏取り不能＝ERROR
  [REQUIRED] figcheck(Vertex)＝ADC認証                     … 無ければ図の視覚検品不能＝ERROR
  [OPTIONAL] OpenAI相互検証＝OPENAI_API_KEY               … 無ければcrossはブラウザ代替＝WARN

判定：CRITICALのFAIL または REQUIREDのDOWN が1つでもあれば **exit 1**（検知可能なエラー）。
用法：py src/check_system.py            （--live で各APIに実接続の疎通も試す＝軽微課金）
"""
import os, sys, subprocess, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # noqa: F401  Windows: setx反映漏れ対策＝レジストリからキー補完

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SRC = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
LIVE = "--live" in sys.argv

results = []   # (tier, name, status, detail)  status: OK/WARN/ERROR


def _child_env():
    # 親が子プロセスのI/O契約を固定する（境界での恒久策・GPT敵対レビュー2026-08-15）。
    # PYTHONIOENCODING=utf-8で子のstdout"と"stderr両方をUTF-8にし、親のencoding="utf-8"デコードと一致させる。
    # ＝cp932パイプで「子がUnicodeEncodeError」or「日本語stderr→親がUnicodeDecodeError」になる事故クラスを、
    #   各スクリプトに散らさず1箇所で根絶（＝モグラ叩きの回避）。子には非対称を作らない。
    # ★{**os.environ}を必ず複製：env_bootがos.environへ注入したAPIキー等を子にも渡すため（envで丸ごと差替えると鍵が消える）。
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run(args, timeout=180):
    try:
        p = subprocess.run([PY] + args, cwd=os.path.dirname(SRC),
                           capture_output=True, text=True, encoding="utf-8",
                           env=_child_env(), timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 999, f"実行不能: {e}"


def check_gate_selftest():
    rc, out = _run(["src/pre_submit_gate.py", "--self-test"])
    ok = (rc == 0) and ("self-test PASS" in out)
    results.append(("CRITICAL", "提出前ゲート self-test", "OK" if ok else "ERROR",
                    "既知エラーの回帰検知が両方向で正常" if ok else f"self-test失敗(rc={rc})＝ゲートが壊れている可能性"))


def check_policy_selftest():
    rc, out = _run(["src/policy_gate.py", "--self-test"])
    ok = (rc == 0) and ("self-test PASS" in out)
    results.append(("CRITICAL", "policy_gate self-test(方針強制の検知)", "OK" if ok else "ERROR",
                    "未決定/有言不実行/期限切れの検知が正常" if ok else f"方針強制器が壊れている(rc={rc})"))


def check_policy_enforcement():
    rc, out = _run(["src/policy_gate.py"])
    m = re.search(r"\[SUMMARY\]\s+fail=(\d+)\s+warn=(\d+)", out)
    nwarn = int(m.group(2)) if m else out.count("🟡")
    if rc != 0:
        results.append(("REQUIRED", "方針の強制簿(記録止まり禁止)", "ERROR",
                        "未決定 or 有言不実行あり＝方針を放置＝`py src/policy_gate.py`で決定/実装せよ"))
    else:
        results.append(("REQUIRED", "方針の強制簿(記録止まり禁止)", "OK" if nwarn == 0 else "WARN",
                        "全方針に決定あり・追随債務なし" if nwarn == 0
                        else f"追随債務{nwarn}件(codify宣言・期限内未実装)＝期限までにコード化を"))


def check_verify_core():
    rc, out = _run(["src/verify_core.py"])
    ok = (rc == 0) and ("self-test PASS" in out)
    results.append(("CRITICAL", "verify_core self-test(複合指紋/stale)", "OK" if ok else "ERROR",
                    "複合指紋の決定論・asset差替検知・stale/判定語彙が正常" if ok
                    else f"検証コアが壊れている可能性(rc={rc})"))


def check_figlint_adv():
    rc, out = _run(["src/figlint.py", "--adversarial"])
    ok = (rc == 0) and ("PASS" in out)
    results.append(("CRITICAL", "figlint 敵対的自己テスト", "OK" if ok else "ERROR",
                    "図レイアウト検知が両方向で正常" if ok else f"figlint検知力が壊れている(rc={rc})"))


def check_figlint_figures():
    rc, out = _run(["src/figlint.py"])
    ok = (rc == 0)
    # FAIL件数を抽出
    detail = "TPO/NIS図レイアウトOK(重なり/見切れ/小文字なし)" if ok else "実図にレイアウトFAILあり＝要修正"
    results.append(("CRITICAL", "figlint 実図(TPO/NIS)", "OK" if ok else "ERROR", detail))


def check_external_review():
    # 「重要物は必ず外部AIで敵対レビュー」の強制（検品コアを無レビューで触らせない）。
    # fail>0(STALE/NO-GO/無レビュー改変)=🔴ERROR／debtのみ=🟡WARN。＝記録止まりにさせない。
    rc, out = _run(["src/external_review_gate.py"])
    m = re.search(r"\[SUMMARY\]\s+fail=(\d+)\s+warn=(\d+)", out)
    nf = int(m.group(1)) if m else (0 if rc == 0 else 1)
    nw = int(m.group(2)) if m else 0
    if nf:
        results.append(("REQUIRED", "外部AIレビュー強制(検品コア)", "ERROR",
                        f"検品コアが外部レビュー未達{nf}件(STALE/NO-GO/無レビュー改変)＝外部AIで敵対レビューし--register"))
    elif nw:
        results.append(("REQUIRED", "外部AIレビュー強制(検品コア)", "WARN",
                        f"外部レビュー債務{nw}件(導入前コード)＝順次 外部レビュー→--registerで消す"))
    else:
        results.append(("REQUIRED", "外部AIレビュー強制(検品コア)", "OK",
                        "検品コアは全て外部レビュー合格・現行一致"))


def _key(name):
    # resolve＝os.environ優先・無ければレジストリを見る（注入しない＝os.environを汚さない・過剰伝播#2回避）。
    v = env_boot.resolve(name)
    return bool(v and v.strip())


def check_anthropic():
    have = _key("ANTHROPIC_API_KEY") or _key("ANTHROPIC_AUTH_TOKEN")
    if not have:
        results.append(("REQUIRED", "medcheck判定脳(ANTHROPIC_API_KEY)", "ERROR",
                        "未設定＝medcheckの判定が下せず『未検証』で止まる。setxで設定しClaude Code再起動。"))
        return
    if LIVE:
        rc, out = _run(["src/medcheck.py", "NISは基底膜に局在する",
                        "--pubmed-query", "sodium iodide symporter basolateral", "--n", "2"], timeout=200)
        ok = rc == 0 and ("判定" in out) and ("skip" not in out)
        results.append(("REQUIRED", "medcheck(ANTHROPIC・実接続)", "OK" if ok else "ERROR",
                        "判定が返った" if ok else f"キーはあるが判定不能(残高/障害?)(rc={rc})"))
    else:
        # 偽の緑つぶし：キーがあってもanthropic/pydantic SDKが無いと判定は動かない(実害を確認済)。
        missing = []
        for mod in ("anthropic", "pydantic"):
            try:
                __import__(mod)
            except Exception:
                missing.append(mod)
        if missing:
            results.append(("REQUIRED", "medcheck判定脳(ANTHROPIC_API_KEY)", "ERROR",
                            "キーはあるがSDK未導入＝判定不能(偽の緑)。`py -m pip install "
                            + " ".join(missing) + "`"))
        else:
            results.append(("REQUIRED", "medcheck判定脳(ANTHROPIC_API_KEY)", "OK",
                            "キーあり＋SDK(anthropic/pydantic)導入済(--liveで実接続疎通も可)"))


def check_medisearch():
    if not _key("MEDISEARCH_API_KEY"):
        results.append(("REQUIRED", "MediSearch(MEDISEARCH_API_KEY)", "ERROR", "未設定＝医療AI裏取り不能"))
        return
    results.append(("REQUIRED", "MediSearch(MEDISEARCH_API_KEY)", "OK", "キーあり"))


def check_vertex():
    # ADC認証ファイルの存在＝figcheck(Vertex)が使える最低条件
    adc = os.path.join(os.environ.get("APPDATA", ""), "gcloud", "application_default_credentials.json")
    genv = env_boot.resolve("GOOGLE_APPLICATION_CREDENTIALS")
    ok = os.path.exists(adc) or (genv and os.path.exists(genv))
    results.append(("REQUIRED", "figcheck(Vertex ADC)", "OK" if ok else "ERROR",
                    "ADC認証あり＝図の視覚検品可" if ok else "ADC未認証＝`gcloud auth application-default login`要"))


def check_openai():
    have = _key("OPENAI_API_KEY")
    results.append(("OPTIONAL", "OpenAI相互検証(OPENAI_API_KEY)", "OK" if have else "WARN",
                    "キーあり" if have else "未設定＝--cross openaiはブラウザ版ChatGPTで代替(残高ゼロ既知)"))


def check_keys_only():
    """キー/認証の生死だけを高速に返す（gate/figlint self-testは走らせない）。
    build前プリフライト用＝毎ビルドで裏取り柱の稼働を頭出しし、サイレント劣化を防ぐ。
    返り値: list[(name, tier, ok)]。"""
    out = []
    out.append(("medcheck(ANTHROPIC)", "REQUIRED", _key("ANTHROPIC_API_KEY") or _key("ANTHROPIC_AUTH_TOKEN")))
    out.append(("MediSearch", "REQUIRED", _key("MEDISEARCH_API_KEY")))
    adc = os.path.join(os.environ.get("APPDATA", ""), "gcloud", "application_default_credentials.json")
    genv = env_boot.resolve("GOOGLE_APPLICATION_CREDENTIALS")
    out.append(("figcheck(Vertex ADC)", "REQUIRED", os.path.exists(adc) or bool(genv and os.path.exists(genv))))
    out.append(("OpenAI(cross)", "OPTIONAL", _key("OPENAI_API_KEY")))
    return out


def main():
    print("=" * 66)
    print("🩺 検品システムの自己診断（メタ検品）" + ("  [--live: 実接続あり]" if LIVE else ""))
    print("=" * 66)
    # 透明性：環境変数に無くレジストリ(HKCU\Environment)からのみ解決できるキーを明示（サイレント厳禁）。
    #   env_boot は import副作用で注入しなくなった(#2)ため、sweep(副作用なし)で"補完解決"と異常を検出して表示する。
    try:
        s = env_boot.sweep()
        if s["registry"]:
            print("  ℹ レジストリから補完解決したキー: " + ", ".join(s["registry"])
                  + "（＝環境変数としては未設定。恒久はsetx後にClaude Code再起動で解消）")
        if s["errors"]:  # レジストリI/O異常はサイレントにしない(#3)
            print("  🔴 レジストリ読取の異常: " + ", ".join(f"{k}:{r}" for k, r in s["errors"]))
    except Exception:
        pass
    for fn in (check_gate_selftest, check_verify_core, check_policy_selftest, check_policy_enforcement,
               check_external_review, check_figlint_adv, check_figlint_figures,
               check_anthropic, check_medisearch, check_vertex, check_openai):
        try:
            fn()
        except Exception as e:
            results.append(("CRITICAL", fn.__name__, "ERROR", f"診断自体が例外: {e}"))

    n_err = n_warn = 0
    for tier, name, status, detail in results:
        mark = {"OK": "🟢", "WARN": "🟡", "ERROR": "🔴"}[status]
        print(f"  {mark} [{tier:8}] {name}: {detail}")
        n_err += (status == "ERROR"); n_warn += (status == "WARN")

    print("=" * 66)
    if n_err:
        print(f"🔴 検品システムに {n_err} 件の不全（WARN {n_warn}）＝**この状態で『検品済み』を名乗ってはいけない**。上記ERRORを解消。")
    else:
        print(f"🟢 検品システム 正常（WARN {n_warn}）＝各柱が生きている。")
    # サイレント厳禁：不全があれば非ゼロ終了で外形に出す
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
