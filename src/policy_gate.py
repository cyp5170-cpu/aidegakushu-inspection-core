# -*- coding: utf-8 -*-
"""
policy_gate.py ― 「方針を"記録止まり"にさせない」強制ゲート。

今日の議論の集大成＝メモリ/MDに書いた方針は強制力ゼロ(無視され得る)。
そこで各方針に必ず『決定(decision)』を持たせ、この評価器が:
  ● decision が空(未決定) → 🔴FAIL（人が決めるまで緑にしない＝"コード化する?"を必ず突きつける）
  ● decision=codify なのに enforced_by 空 かつ due 期限切れ → 🔴FAIL（有言不実行を許さない）
  ● decision=codify で enforced_by 空 だが due 未到来 → 🟡WARN（追随債務として可視化）
  ● decision=record_only → 🟢OK（人が明示的に"記録のまま"と決めた・ログ）
  ● decision=defer で due 期限切れ → 🔴FAIL（保留の逃げ得を許さない）
検品自身はcheck_systemの決定論self-testで守る(enforcerのenforcer=信頼基点)。

★機械化できるのは「決定を必ずさせる」まで。「何がcriticalか/印を付けるか」は人(委譲不能)。
使い方: py src/policy_gate.py         (評価・FAILで exit 1)
        py src/policy_gate.py --self-test
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # noqa: F401
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "checkdata" / "policy_enforcement.json"
VALID = {"codify", "record_only", "defer", ""}


def _today():
    return datetime.date.today()


def _past(due: str) -> bool:
    """due(YYYY-MM-DD)が今日より前か。空/不正は"期限なし"扱い(False)。"""
    if not due:
        return False
    try:
        return datetime.date.fromisoformat(due) < _today()
    except Exception:
        return False


def evaluate(policies):
    """各方針を判定 → (level, id, msg) のリストを返す。level=FAIL/WARN/OK。純関数＝self-test対象。"""
    out = []
    for p in policies:
        pid = p.get("id", "?")
        dec = (p.get("decision") or "").strip()
        enf = (p.get("enforced_by") or "").strip()
        due = (p.get("due") or "").strip()
        crit = p.get("criticality", "important")
        if dec not in VALID:
            out.append(("FAIL", pid, f"decisionが不正値『{dec}』(codify/record_only/defer/空 のみ)"))
            continue
        if dec == "":
            out.append(("FAIL", pid, "未決定＝人が『コード化する/しない』を決めていない。決めるまで緑にしない"))
        elif dec == "codify" and not enf:
            if _past(due):
                out.append(("FAIL", pid, f"codify宣言なのに未実装＋期限切れ(due={due})＝有言不実行"))
            else:
                out.append(("WARN", pid, f"codify宣言・未実装(due={due or '未設定'})＝追随債務(期限までに実装)"))
        elif dec == "defer" and _past(due):
            out.append(("FAIL", pid, f"保留の期限切れ(due={due})＝再決定せよ(逃げ得禁止)"))
        elif dec == "record_only":
            out.append(("OK", pid, f"記録のまま(人の明示決定・{crit})＝コード強制外(忘却リスクは残る)"))
        else:
            out.append(("OK", pid, f"{dec}" + (f" → {enf}" if enf else "")))
    return out


def run():
    if not REGISTRY.exists():
        print(f"🔴 policy登録簿が無い: {REGISTRY}")
        return 1
    try:
        data = json.load(open(REGISTRY, encoding="utf-8"))
    except Exception as e:
        print(f"🔴 policy_enforcement.json 解析失敗: {e}")
        return 1
    policies = data.get("policies", [])
    res = evaluate(policies)
    print("=" * 70)
    print("🛡 方針の強制簿（記録止まりを許さない＝未決定/有言不実行を🔴表出）")
    print("=" * 70)
    nf = nw = 0
    for level, pid, msg in res:
        mark = {"FAIL": "🔴", "WARN": "🟡", "OK": "🟢"}[level]
        print(f"  {mark} {pid}: {msg}")
        nf += level == "FAIL"
        nw += level == "WARN"
    print("=" * 70)
    if nf:
        print(f"🔴 未決定/有言不実行 {nf}件（WARN {nw}）＝方針を放置している。決定 or 実装せよ。")
    elif nw:
        print(f"🟡 追随債務 {nw}件（期限内）＝期限までにコード化を。")
    else:
        print("🟢 全方針に決定あり・追随債務なし。")
    print(f"[SUMMARY] fail={nf} warn={nw}")   # 機械可読(check_system等が拾う)
    return 1 if nf else 0


# ---- self-test（enforcerのenforcer＝この評価ロジックが壊れていないか決定論で守る）----
SELF = [
    ({"id": "t_undecided", "decision": "", "enforced_by": "", "due": ""}, "FAIL"),
    ({"id": "t_bad", "decision": "GREEN", "enforced_by": "", "due": ""}, "FAIL"),
    ({"id": "t_codify_ok", "decision": "codify", "enforced_by": "gate:x", "due": ""}, "OK"),
    ({"id": "t_codify_debt", "decision": "codify", "enforced_by": "", "due": "2099-12-31"}, "WARN"),
    ({"id": "t_codify_overdue", "decision": "codify", "enforced_by": "", "due": "2000-01-01"}, "FAIL"),
    ({"id": "t_record", "decision": "record_only", "enforced_by": "", "due": ""}, "OK"),
    ({"id": "t_defer_overdue", "decision": "defer", "enforced_by": "", "due": "2000-01-01"}, "FAIL"),
]


def self_test():
    print("=" * 70)
    print("🧪 policy_gate self-test（未決定/有言不実行/期限切れの検知が正しいか）")
    print("=" * 70)
    ok = True
    for spec, want in SELF:
        got = evaluate([spec])[0][0]
        good = got == want
        ok = ok and good
        print(f"  {'✓' if good else '✗'} {spec['id']}: 期待{want} 実際{got}")
    print("🟢 policy_gate self-test PASS" if ok else "🔴 policy_gate self-test FAIL")
    return ok


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    sys.exit(run())
