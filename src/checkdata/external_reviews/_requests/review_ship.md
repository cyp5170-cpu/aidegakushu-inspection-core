# 外部AI敵対レビュー依頼：`src/ship.py`

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
出荷ゲート（唯一の正規経路）。policy_gate/裏取り/提出前ゲート/verify_assets/cinematic を集約し、全緑＋人サインオフで許可証(状態指紋)を発行。--verify で発行後の改変(MATCH/STALE/NO_PERMIT/BROKEN)を検知。

## このファイル固有の脅威（重点的に突く）
1. 迂回（build直叩き・配線削除・TOCTOU）で無許可のまま出荷できないか。
2. 許可証の偽造・複製・使い回しに対する堅牢性。
3. 状態指紋が『実際に表示される成果物』を捉えているか（合成図・音声を含むか）。
4. サインオフ未記録なのに GO を出す誤りはないか（人の確認の代替をしていないか）。

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


## レビュー対象コード：`src/ship.py`
- SHA256（改行正規化後・ゲートの署名対象と同一計算）：`b732ec4cdbd0352389d57b43d8e7b744248c477ea33819dc1726ec3f13261d14`
- ↓このコード全文をレビューしてください。

```python
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
```
