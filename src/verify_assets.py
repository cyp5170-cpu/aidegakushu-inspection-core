# -*- coding: utf-8 -*-
"""
verify_assets.py ― verify_core を「AIで学習」に配線する adapter(P0)＋人のサインオフ支援。

思想（多AI4周レビューの結論・軽量版）：
  ● 台本の各行(SoT=text)と、その行の画像(派生物)を、verify_coreの"複合指紋"で結ぶ。
  ● 状態を平易に表示：確認済み / 未確認(UNKNOWN) / ⚠台本変更後・未再確認(stale)。
  ● 人が確認した行を --signoff で記録 → 後で台本や画像が変わると自動でstaleに落ちる
     ＝「textだけ直して絵が古い」(ep02実発生)を機械が必ず拾う。
  ● 知識でなく"照合"でGO/NO-GOできる＝浅い知識でもサインオフが堅くなる。
  ● 機械は「正しい」と言わない。未確認は"無視可能"にせず UNKNOWN として人へ回す。

使い方:
  py src/verify_assets.py --dir episodes/iodine/ep02            # 状態一覧
  py src/verify_assets.py --dir episodes/iodine/ep02 --signoff 5 12   # 行5,12を確認済み記録
  py src/verify_assets.py --dir episodes/iodine/ep02 --signoff-all    # 現在の全画像を一括確認済み
戻り値: staleが1件でもあれば exit 1（＝"変わったのに未再確認"を出荷前に止める土台）。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # noqa: F401
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import re
import json
import argparse
import datetime
from pathlib import Path
import verify_core as vc

ROOT = Path(__file__).resolve().parent.parent
CHECKDATA = ROOT / "src" / "checkdata"
VERIFIER = "human-signoff-v1"   # サインオフ運用の版。運用ルールを変えたら上げる。


def _ep_root(args):
    if args.dir:
        return ROOT / args.dir
    return ROOT / "episodes" / f"ep{str(args.ep).zfill(2)}"


def _ruleset_fp():
    # 実ルール(checkdata)の内容から版指紋を導出（バンプ忘れ対策）。
    paths = sorted(str(p) for p in CHECKDATA.glob("*.json")) if CHECKDATA.exists() else []
    return vc.ruleset_fingerprint(paths)


def resolve_image(images_dir: Path, line: dict):
    """行→画像ファイルを解決（build_ymm4.resolve_imageの軽量版・エピソードimages/のみ）。"""
    kw = line.get("image_keyword")
    if not kw or str(kw).startswith("disclaimer"):
        return None
    for stem in (f"img_{line.get('id')}", re.sub(r"[^\w\-]+", "_", str(kw)), str(kw)):
        if not stem:
            continue
        for c in sorted(images_dir.glob(stem + ".*")):
            if c.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                return c
    return None


def _resolver(ep_root: Path, images_dir: Path):
    """行→"実際に画面へ出る絵"を返す関数を用意する。
    ★build_ymm4.effective_card_image を使う＝COMPOSITION(合成図)は合成PNGを、
      それ以外は images/ を返す＝ビルドの表示規則と一致（"使われない旧jpg"を誤照合しない）。
    import不能時のみ images/ 解決にフォールバック（その旨を警告＝サイレントにしない）。"""
    try:
        import build_ymm4 as _b   # sys.argvの--dirを読むので、verify_assetsと同じepを解決
        return _b.effective_card_image, "effective(COMPOSITION対応)"
    except Exception as e:
        print(f"[warn] build_ymm4を読めずimages/のみで照合(合成図は未対象): {e}")
        return (lambda ln: (resolve_image(images_dir, ln) if images_dir.exists() else None)), "images/のみ(縮退)"


def _is_code_drawn(ln):
    """その行が"コード描画"(外部画像を使わない)か。＝verify対象外(台本から自動生成される絵)。
    ・summaryリストあり → make_matome_note(まとめ黒板)。
    ・image_keywordが ed_channel_card / ed_ 系 → ED登録カード(コードUI)。
    build_ymm4の実表示規則に合わせ、"使われない旧jpg"を誤って検証対象にしない(実バグ修正)。"""
    if isinstance(ln.get("summary"), list) and ln.get("summary"):
        return "まとめ(make_matome_note)"
    kw = str(ln.get("image_keyword") or "")
    if kw == "ed_channel_card" or kw.startswith("ed_"):
        return "ED登録カード(コード描画)"
    return None


def _rows(ep_root: Path):
    """(rows, man, mode, code_drawn) を返す。rowsは外部画像を持つ行のみ。code_drawnは対象外行。"""
    sj = ep_root / "script.json"
    if not sj.exists():
        print(f"❌ script.json が無い: {sj}")
        return None, None, None, None
    lines = json.load(open(sj, encoding="utf-8")).get("lines", [])
    images_dir = ep_root / "images"
    man = vc.Manifest(str(ep_root / "verify_manifest.json"))
    ruleset = _ruleset_fp()
    resolve_fn, mode = _resolver(ep_root, images_dir)
    rows = []
    code_drawn = []
    for ln in lines:
        cd = _is_code_drawn(ln)
        if cd:
            code_drawn.append((ln.get("id"), cd))
            continue
        try:
            img = resolve_fn(ln)
        except Exception:
            img = None
        if not img:
            continue
        img = Path(img)
        asset_id = f"asset:{ln.get('id')}"
        fp = vc.verification_fingerprint([ln.get("text", "")], asset_path=str(img),
                                         ruleset_version=ruleset, verifier_version=VERIFIER)
        rec = man.get(asset_id)
        status = man.status(asset_id, fp)     # PASS / UNKNOWN
        rows.append({"asset_id": asset_id, "line": ln, "img": img, "fp": fp,
                     "status": status, "has_record": bool(rec)})
    return rows, man, mode, code_drawn


def _label(row):
    if row["status"] == vc.PASS:
        return "🟢 確認済み"
    if row["has_record"]:
        return "⚠🔴 台本/画像が変わった→要再確認(stale)"   # 記録はあるが指紋不一致＝ドリフト
    return "⬜ 未確認(UNKNOWN)"


def cmd_report(rows, mode, code_drawn):
    print("=" * 74)
    print("🔎 画像×台本 検証状態（機械は「正しい」と言わない＝下限保証。最終は人のGO/NO-GO）")
    print(f"   照合対象＝実際に表示される絵: {mode}")
    print("=" * 74)
    n_ok = n_unknown = n_stale = 0
    for r in rows:
        ln = r["line"]
        lab = _label(r)
        if r["status"] == vc.PASS:
            n_ok += 1
        elif r["has_record"]:
            n_stale += 1
        else:
            n_unknown += 1
        kw = ln.get("image_keyword", "") or ""
        is_comp = ("_compose_" in r["img"].name) or ("_locator_" in r["img"].name)
        mark = "[合成図]" if is_comp else "[画像]"
        print(f"  行{ln.get('id'):>2} {lab}")
        print(f"       {mark} {kw[:38]} → {r['img'].name[:30]}")
        print(f"       台詞: {(ln.get('text','') or '')[:36]}")
    if code_drawn:
        print("-" * 74)
        print(f"  🧩 コード描画（台本から自動生成・外部画像なし＝検証対象外）{len(code_drawn)}件:")
        for cid, why in code_drawn:
            print(f"       行{cid}: {why}")
    print("-" * 74)
    print(f"  検証対象 {len(rows)}件 ＝ 🟢確認済 {n_ok} / ⬜未確認 {n_unknown} / 🔴要再確認(stale) {n_stale}"
          + (f"（＋🧩コード描画{len(code_drawn)}件は対象外）" if code_drawn else ""))
    if n_stale:
        print("  🔴 staleあり＝『台本や画像を変えたのに再確認していない』行です。中身を見て --signoff で再確認を。")
    if n_unknown:
        print("  ⬜ 未確認＝まだ一度も人が照合していない行。出典と突き合わせて --signoff を。")
    return 1 if n_stale else 0


def cmd_signoff(rows, man, ids, all_):
    today = datetime.date.today().isoformat()
    target = set()
    if all_:
        target = {r["asset_id"] for r in rows}
    else:
        want = {f"asset:{i}" for i in ids}
        target = {r["asset_id"] for r in rows if r["asset_id"] in want}
        missing = want - {r["asset_id"] for r in rows}
        for m in missing:
            print(f"[skip] 対象に表示画像が無い: {m}")
    n = 0
    for r in rows:
        if r["asset_id"] in target:
            man.record(r["asset_id"], r["fp"], vc.PASS,
                       verifier_version=VERIFIER, verified_at=today, note="human sign-off")
            n += 1
            print(f"  ✅ 記録: 行{r['line'].get('id')} を確認済みに（{today}）")
    man.save()
    print(f"[OK] {n}件をサインオフ記録。以後、台本/画像が変わるとその行はstale(要再確認)に自動で落ちます。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="画像×台本の検証状態表示＋人のサインオフ記録(verify_core adapter)")
    ap.add_argument("--dir", type=str, default=None)
    ap.add_argument("--ep", type=str, default=None)
    ap.add_argument("--signoff", type=int, nargs="*", default=None, help="確認済みにする行id（複数可）")
    ap.add_argument("--signoff-all", action="store_true", help="現在解決できる全画像を確認済みに")
    args = ap.parse_args()
    ep_root = _ep_root(args)
    rows, man, mode, code_drawn = _rows(ep_root)
    if rows is None:
        sys.exit(2)
    if not rows:
        print("（検証対象の外部画像を持つ行が見つかりませんでした）")
        sys.exit(0)
    if args.signoff is not None or args.signoff_all:
        sys.exit(cmd_signoff(rows, man, args.signoff or [], args.signoff_all))
    sys.exit(cmd_report(rows, mode, code_drawn))


if __name__ == "__main__":
    main()
