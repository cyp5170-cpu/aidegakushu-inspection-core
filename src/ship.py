# -*- coding: utf-8 -*-
"""
ship.py ― 出荷ゲート（唯一の正規出荷経路・全チェックを束ね・許可証を発行）。

今日の結論の実体化＝「強制するソフト」。散在するチェックを1コマンドに集約し、
"全部緑＋人のサインオフ"が揃って初めて『出荷許可証(ship_permit.json)』を出す。
＝正規経路を唯一かつ最も楽にして、迂回する動機を消す(＝現実的な最強の強制)。

束ねるチェック（1つでもNGなら GO しない）:
  1) policy_gate       方針の未決定/有言不実行(記録止まり禁止)
  2) check_system keys 裏取り柱(ANTHROPIC/MediSearch/Vertex)の生死
  3) pre_submit_gate   台本の提出前ゲート(A-8含む)＝FAIL0か
  4) verify_assets     画像×台本が全て人にサインオフ済みか(未確認/staleが0か)
  5) cinematic_lint    シネマ調違反/未判定が0か(記録ベース)

★正直な限界：最終MP4はYMM4のGUIで書き出す＝コードで物理的に止められない。
  ship.pyは「GO/NO-GO判定＋許可証」まで。許可証つき.ymmpだけを開いて書き出す規律＋
  最終成果物チェックで補う。"決めて迂回する人"は止められない(人のバックストップが最後に残る)。

使い方:
  py src/ship.py --dir episodes/iodine/ep01           # 出荷可否を判定(発行しない)
  py src/ship.py --dir episodes/iodine/ep01 --permit   # GOなら許可証を発行
戻り値: GOなら0 / NO-GOなら1。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # noqa: F401
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import io
import json
import argparse
import datetime
import contextlib
from pathlib import Path
import verify_core as vc

ROOT = Path(__file__).resolve().parent.parent
SHIP_VER = "ship-gate-v1"


def _policy():
    import policy_gate as pg
    reg = json.load(open(ROOT / "src" / "checkdata" / "policy_enforcement.json", encoding="utf-8"))
    res = pg.evaluate(reg.get("policies", []))
    fails = [pid for lv, pid, _ in res if lv == "FAIL"]
    return (len(fails) == 0), fails


def _keys():
    import check_system as cs
    down = [n for (n, t, ok) in cs.check_keys_only() if t == "REQUIRED" and not ok]
    return (len(down) == 0), down


def _external_review():
    """検品コアが外部AIレビュー未達(STALE/NO-GO/無レビュー改変=FAIL)なら出荷不可＝
    ゲート自身が無レビューで変えられていたらゲートを信用できない。WARN債務(導入前)はブロックしない。"""
    import external_review_gate as er
    data = er.load_registry()
    crit = data["critical_files"]
    cur = {rel: er.file_hash(rel) for rel in crit}
    res = er.evaluate(crit, data["files"], cur)
    fails = [rel for lv, rel, _st, _m in res if lv == "FAIL"]
    return (len(fails) == 0), fails


def _gate(ep_dir):
    import pre_submit_gate as g
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = g.run_gate(str(ep_dir), emit_audit=False)
    return bool(ok)


def _assets(ep_dir):
    import verify_assets as va
    rows, _m, _mode, _cd = va._rows(ep_dir)
    if rows is None:
        return None
    unsigned = sum(1 for r in rows if r["status"] != vc.PASS)   # UNKNOWN/stale=未サインオフ
    return unsigned, len(rows)


def _cinematic(ep_dir):
    import cinematic_lint as cl
    st = cl.status_dir(ep_dir)
    if st is None:
        return None
    viol = sum(1 for _lid, _img, s, _rec in st if s == vc.BLOCK)
    unk = sum(1 for _lid, _img, s, _rec in st if s == vc.UNKNOWN)
    return viol, unk, len(st)


def run(ep_dir: Path, do_permit: bool):
    print("=" * 72)
    print(f"🚢 出荷ゲート ship.py : {ep_dir}")
    print("=" * 72)
    checks = []  # (name, ok, detail)

    pol_ok, pol_fail = _policy()
    checks.append(("方針の強制簿(policy_gate)", pol_ok, "OK" if pol_ok else f"未決定/有言不実行: {pol_fail}"))

    er_ok, er_fail = _external_review()
    checks.append(("検品コアの外部レビュー(external_review_gate)", er_ok,
                   "未達なし(STALE/NO-GO/無レビュー改変=0)" if er_ok else f"未達(要外部レビュー): {er_fail}"))

    key_ok, key_down = _keys()
    checks.append(("裏取り柱(check_system keys)", key_ok, "健全" if key_ok else f"DOWN: {key_down}"))

    gate_ok = _gate(ep_dir)
    checks.append(("提出前ゲート(A-8含む)", gate_ok, "FAIL0" if gate_ok else "FAILあり"))

    a = _assets(ep_dir)
    if a is None:
        checks.append(("画像×台本サインオフ(verify_assets)", False, "script.json無し"))
        as_ok = False
    else:
        unsigned, total = a
        as_ok = (unsigned == 0 and total > 0)
        checks.append(("画像×台本サインオフ(verify_assets)", as_ok,
                       f"全{total}件サインオフ済" if as_ok else f"未サインオフ/stale {unsigned}/{total}"))

    c = _cinematic(ep_dir)
    if c is None:
        checks.append(("シネマ調(cinematic_lint)", False, "script.json無し"))
        ci_ok = False
    else:
        viol, unk, ctot = c
        ci_ok = (viol == 0 and unk == 0)
        checks.append(("シネマ調(cinematic_lint)", ci_ok,
                       "違反0・未判定0" if ci_ok else f"違反{viol}/未判定{unk}(全{ctot})"))

    for name, ok, detail in checks:
        print(f"  {'🟢' if ok else '🔴'} {name}: {detail}")
    go = all(ok for _n, ok, _d in checks)
    print("=" * 72)
    print("🟢 GO ＝ 出荷可（人のサインオフ含め全チェック通過）" if go
          else "🔴 NO-GO ＝ 上記🔴を解消するまで出荷不可")

    if do_permit:
        if not go:
            print("⛔ 許可証は発行しません（NO-GOのため）。")
            return 1
        _emit_permit(ep_dir)
    elif go:
        print("（--permit で出荷許可証を発行できます）")
    return 0 if go else 1


def _emit_permit(ep_dir: Path):
    """GO状態の内容指紋を許可証に固める＝後で成果物がこの状態と一致するか照合できる。"""
    import verify_assets as va
    rows, _m, _mode, _cd = va._rows(ep_dir)
    state = {r["asset_id"]: r["fp"] for r in (rows or [])}
    sj = ep_dir / "script.json"
    script_hash = "sha:" + vc.sha256_hex(sj.read_bytes()) if sj.exists() else "none"
    permit = {
        "episode": ep_dir.name, "ship_version": SHIP_VER,
        "issued_at": datetime.date.today().isoformat(),
        "script_hash": script_hash, "asset_fingerprints": state,
        "note": "全チェック通過＋人サインオフ済で発行。以後 script/画像が変わると照合不一致＝再検証要。",
    }
    out = ep_dir / "ship_permit.json"
    json.dump(permit, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2, sort_keys=True)
    print(f"🪪 出荷許可証を発行: {out}")


def verify_permit(ep_dir: Path):
    """最終成果物チェック＝許可証と"今の状態"が一致するか。
    発行後に台本/画像が1つでも変われば STALE（＝承認は無効・再検証要）。返り値=(code, msg)。"""
    import verify_assets as va
    pp = ep_dir / "ship_permit.json"
    if not pp.exists():
        return "NO_PERMIT", "出荷許可証がない＝未承認（ship.py --permit を経ていない）"
    try:
        permit = json.load(open(pp, encoding="utf-8"))
    except Exception as e:
        return "BROKEN", f"許可証が壊れている: {e}"
    sj = ep_dir / "script.json"
    cur_script = "sha:" + vc.sha256_hex(sj.read_bytes()) if sj.exists() else "none"
    rows, _m, _mode, _cd = va._rows(ep_dir)
    cur_state = {r["asset_id"]: r["fp"] for r in (rows or [])}
    if permit.get("script_hash") != cur_script:
        return "STALE", "許可証発行後に台本(script.json)が変わった＝再検証・再承認が必要"
    if permit.get("asset_fingerprints") != cur_state:
        return "STALE", "許可証発行後に画像/対応が変わった＝再検証・再承認が必要"
    return "MATCH", f"許可証と現状が一致＝{permit.get('issued_at','?')}承認の内容そのまま（出荷可）"


def cmd_verify(ep_dir: Path):
    code, msg = verify_permit(ep_dir)
    mark = "🟢" if code == "MATCH" else "🔴"
    print(f"{mark} [最終成果物チェック] {ep_dir.name}: {code} ＝ {msg}")
    return 0 if code == "MATCH" else 1


def main():
    ap = argparse.ArgumentParser(description="出荷ゲート(全チェック束ね＋許可証＋最終成果物チェック)")
    ap.add_argument("--dir", type=str, required=True)
    ap.add_argument("--permit", action="store_true", help="GOなら出荷許可証を発行")
    ap.add_argument("--verify", action="store_true", help="許可証と現状が一致するか(発行後の改変検知)")
    a = ap.parse_args()
    ep = Path(a.dir) if os.path.isabs(a.dir) else ROOT / a.dir
    if a.verify:
        sys.exit(cmd_verify(ep))
    sys.exit(run(ep, a.permit))


if __name__ == "__main__":
    main()
