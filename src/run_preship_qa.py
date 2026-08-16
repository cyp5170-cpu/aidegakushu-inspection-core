# -*- coding: utf-8 -*-
"""run_preship_qa ― ep横断の"先回りQA"ランナー（Claude専有・多AI提言E/2026-08-15）。

思想：**「ユーザーが最初の指摘者」になる事故を、公開/レビュー前に潰す。**
1話ずつ手で回すと取りこぼす → 全エピソードを一括で機械にかけ、ep別に集約する。

流れ：
  ① check_system のキー健全性（裏取り柱が生きているか。死んでいれば"未検証"と明示）
  ② figlint（図レイアウトの決定論・グローバル1回）
  ③ 各ep の pre_submit_gate（内容の静的ゲート）を一括実行しFAIL/WARN/INFOを集約
レポート＝`episodes/_preship_report.md`。FAILが1件でもあれば exit 1（緑を騙らない）。

用法：py src/run_preship_qa.py            （全ep）
      py src/run_preship_qa.py iodine     （シリーズ名で絞り込み）
"""
import os, sys, glob, subprocess, re

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
PY = sys.executable
FILTER = next((a for a in sys.argv[1:] if not a.startswith("-")), None)


def _run(args, timeout=300):
    # 親が子のI/O契約を固定（PYTHONIOENCODING=utf-8で子stdout/stderr両方をUTF-8化＝親のutf-8デコードと一致）。
    # cp932パイプでのエンコード事故を1箇所で根絶。{**os.environ}複製でenv_boot注入鍵を子へ引き継ぐ。
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        p = subprocess.run([PY] + args, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", env=env, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 999, f"実行不能: {e}"


def main():
    print("=" * 70)
    print("🛡  ep横断 先回りQA（公開/レビュー前に機械で洗う）" + (f"  [filter={FILTER}]" if FILTER else ""))
    print("=" * 70)

    # ① キー健全性（裏取り柱の生死）
    sys.path.insert(0, SRC)
    down = []
    try:
        import check_system as cs
        keys = cs.check_keys_only()
        print("\n■ 裏取り柱の健全性（check_system）")
        for name, tier, ok in keys:
            mark = "🟢" if ok else ("🔴" if tier == "REQUIRED" else "🟡")
            print(f"   {mark} [{tier}] {name}: {'OK' if ok else 'DOWN'}")
            if tier == "REQUIRED" and not ok:
                down.append(name)
    except Exception as e:
        print(f"   [warn] check_system不可: {e}")

    # ② figlint（図レイアウト・グローバル）
    print("\n■ 図レイアウト（figlint・全図）")
    fl_rc, fl_out = _run(["src/figlint.py"])
    m = re.search(r"figlint: FAIL (\d+) / WARN (\d+)", fl_out)
    fl_fail = int(m.group(1)) if m else -1
    print(f"   {'🟢' if fl_rc == 0 else '🔴'} figlint FAIL={fl_fail if fl_fail>=0 else '?'}  (rc={fl_rc})")
    for ln in fl_out.splitlines():
        if "[FAIL/" in ln or "[WARN/" in ln:
            print("     " + ln.strip())

    # ③ 各ep gate
    eps = sorted(glob.glob(os.path.join(ROOT, "episodes", "*", "ep*", "script.json")))
    if FILTER:
        eps = [e for e in eps if FILTER in e]
    print(f"\n■ 各エピソードの提出前ゲート（{len(eps)}話）")
    rows = []
    for sj in eps:
        ep_dir = os.path.dirname(sj)
        rel = os.path.relpath(ep_dir, ROOT).replace("\\", "/")
        rc, out = _run(["src/pre_submit_gate.py", "--dir", rel])
        mm = re.search(r"検出 FAIL (\d+)・WARN (\d+)・INFO (\d+)", out)
        f, w, i = (int(mm.group(1)), int(mm.group(2)), int(mm.group(3))) if mm else (-1, -1, -1)
        fails = [l.strip() for l in out.splitlines() if l.strip().startswith("✗")]
        warns = [l.strip() for l in out.splitlines() if l.strip().startswith("!")]
        rows.append({"ep": rel, "F": f, "W": w, "I": i, "fails": fails, "warns": warns})
        mark = "🔴" if f > 0 else ("🟡" if w > 0 else "🟢")
        print(f"   {mark} {rel:34} FAIL={f} WARN={w} INFO={i}")
        for fl in fails[:6]:
            print(f"       ✗ {fl.lstrip('✗ ').split(chr(10))[0][:90]}")

    # ⑤ 出荷許可証の照合（最終成果物チェック＝発行後の改変検知・ship.pyをpreship経路へ配線）
    from pathlib import Path as _P
    n_stale = 0
    print("\n■ 出荷許可証の照合（最終成果物チェック）")
    try:
        import ship as _ship
        for sj in eps:
            ep_dir = os.path.dirname(sj)
            rel = os.path.relpath(ep_dir, ROOT).replace("\\", "/")
            code, _msg = _ship.verify_permit(_P(ep_dir))
            mk = {"MATCH": "🟢", "NO_PERMIT": "⬜"}.get(code, "🔴")
            if code not in ("MATCH", "NO_PERMIT"):
                n_stale += 1
            print(f"   {mk} {rel:34} {code}")
        print("   （⬜=未承認/未出荷＝正常・🔴STALE=承認後に改変＝再承認要）")
    except Exception as e:
        print(f"   [warn] ship照合不可: {e}")

    # ④ レポート
    total_fail = sum(r["F"] for r in rows if r["F"] > 0)
    report = ["# ep横断 先回りQAレポート", "",
              "> 公開/レビュー前に全話を機械で洗った結果。**FAILはユーザーが見る前に潰す**。",
              f"> 生成＝`py src/run_preship_qa.py`（このファイルは自動生成・手編集しない）", ""]
    report.append("## 裏取り柱")
    if down:
        report.append(f"- 🔴 **稼働不能: {' / '.join(down)}** → 該当epのAI裏取りは『未検証』（合格を名乗れない）")
    else:
        report.append("- 🟢 ANTHROPIC/MediSearch/Vertex は健全")
    report.append(f"- 図レイアウト figlint: {'🟢 合格' if fl_rc==0 else '🔴 FAILあり（上記）'}")
    report.append("")
    report.append("## エピソード別")
    report.append("| ep | FAIL | WARN | INFO |")
    report.append("|---|---|---|---|")
    for r in rows:
        report.append(f"| {r['ep']} | {r['F']} | {r['W']} | {r['I']} |")
    report.append("")
    for r in rows:
        if r["fails"] or r["warns"]:
            report.append(f"### {r['ep']}")
            for x in r["fails"]:
                report.append(f"- 🔴 {x.lstrip('✗ ')}")
            for x in r["warns"][:12]:
                report.append(f"- 🟡 {x.lstrip('! ')}")
            report.append("")
    rp = os.path.join(ROOT, "episodes", "_preship_report.md")
    open(rp, "w", encoding="utf-8").write("\n".join(report))

    print("\n" + "=" * 70)
    print(f"📝 レポート: {os.path.relpath(rp, ROOT)}")
    bad = (total_fail > 0) or (fl_rc != 0) or bool(down) or (n_stale > 0)
    if bad:
        print(f"🔴 先回りQA: 要対応（gate FAIL={total_fail} / figlint={'NG' if fl_rc else 'OK'} / 柱DOWN={len(down)} / 許可証STALE={n_stale}）")
    else:
        print("🟢 先回りQA: 全話クリア（裏取り柱も健全）")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
