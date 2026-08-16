# -*- coding: utf-8 -*-
r"""
pmda_check.py ― PMDA添付文書XML(機械可読)から薬剤の"正典値"（効能/用法用量/禁忌/相互作用/警告）を引く。
台本の薬剤主張を、人(薬剤師)の記憶でなく**添付文書(法的権威)**で照合する一次資料レーン。

紐づけは **YJコード(12桁)/成分コード(上7桁)** で確実に（ユーザー指摘2026-08-13）。
事前に `python src/pmda_index.py` で `checkdata/pmda_index.json`（成分コード→製剤・YJ・sample_xml）を作る。
薬剤名は index の製剤名に**前方一致**で紐づけ＝カタカナ誤検出(アルコール/ナトリウム等)を排除。

データ源＝`C:\pmda\SGML_XML`（PMDA一括DL）。★版ずれ注意：定期再DL＋索引再生成で改訂追従。

使い方:
  python src/pmda_check.py --drug アムロジピン
  python src/pmda_check.py --dir episodes/hypertension/ep05
"""
import os, sys, re, json, argparse
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PMDA = r"C:\pmda\SGML_XML"
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkdata", "pmda_index.json")
FIELDS = [
    ("効能効果", ["IndicationsOrEfficacy"]),
    ("用法用量", ["DoseAdmin", "InfoPrecautionsDosage", "DosageAndAdministration"]),
    ("禁忌",   ["ContraIndications", "ContraIndication"]),
    ("相互作用", ["DrugAndDrugInteractions", "Interactions", "ContraIndicatedCombinations"]),
    ("警告",   ["Warnings", "Warning"]),
]
_IDX = None


def idx():
    global _IDX
    if _IDX is None:
        if not os.path.exists(INDEX):
            print(f"[fail] 索引が無い。先に: python src/pmda_index.py"); sys.exit(2)
        _IDX = json.load(open(INDEX, encoding="utf-8"))
    return _IDX


def _grab(t, tags):
    for tag in tags:
        m = re.search(r"<" + tag + r"\b[^>]*>(.*?)</" + tag + r">", t, re.S)
        if m:
            v = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
            if v:
                return v
    return None


def find_entries(name):
    """製剤名が name で始まる成分コード・エントリを返す（YJ成分コードで一意・後発品集約）。"""
    return [v for v in idx().values() if any(p.startswith(name) for p in v["products"])]


def lookup(name):
    ents = find_entries(name)
    if not ents:
        return {"drug": name, "found": False}
    e = ents[0]   # 代表1成分
    xml = os.path.join(PMDA, e["sample_xml"])
    rec = {"drug": name, "found": True, "seihun_code": e["seihun_code"],
           "yj": e["yj"][0], "n_products": len(e["yj"]),
           "product": e["products"][0], "fields": {}}
    try:
        t = open(xml, encoding="utf-8", errors="ignore").read()
        for label, tags in FIELDS:
            v = _grab(t, tags)
            if v:
                rec["fields"][label] = v
    except Exception as ex:
        rec["error"] = str(ex)
    return rec


def drugs_in_script(ep_dir):
    data = json.load(open(os.path.join(ep_dir, "script.json"), encoding="utf-8"))
    blob = []
    for l in data.get("lines", []):
        blob.append(l.get("text") or "")
        blob += [b for b in (l.get("board_bullets") or []) if isinstance(b, str)]
        for k in ("term_gloss", "trivia", "supplement"):
            o = l.get(k)
            if isinstance(o, dict) and o.get("note"):
                blob.append(o["note"])
    cands = sorted(set(re.findall(r"[ア-ンヴー]{4,12}", " ".join(blob))))
    found = [w for w in cands if find_entries(w)]                       # 索引の製剤名に前方一致するものだけ
    found = [w for w in found if not any(w != o and o.startswith(w) for o in found)]  # 短い前方部分を除く
    return found


def _print(rec):
    if not rec["found"]:
        print(f"\n🔴 {rec['drug']}：PMDAローカルに該当なし（web取得 or 別名の可能性）")
        return
    print(f"\n💊 {rec['drug']}（YJ成分コード{rec['seihun_code']}／{rec['n_products']}製剤／例YJ={rec['yj']}）")
    for label, _ in FIELDS:
        v = rec["fields"].get(label)
        if v:
            print(f"   ■ {label}：{v[:230]}")


def main():
    ap = argparse.ArgumentParser(description="PMDA添付文書XMLから薬剤の正典値を引く（YJコード紐づけ）")
    ap.add_argument("--drug")
    ap.add_argument("--dir")
    args = ap.parse_args()

    if args.drug:
        _print(lookup(args.drug))
    elif args.dir:
        drugs = drugs_in_script(args.dir)
        print("=" * 70)
        print(f"🔎 台本の薬剤（PMDA照合・YJ成分コード紐づけ）: {args.dir}")
        print(f"   検出: {', '.join(drugs) or '(なし)'}")
        print("=" * 70)
        recs = [lookup(d) for d in drugs]
        for r in recs:
            _print(r)
        out = os.path.join(args.dir, "pmda_check.json")
        json.dump({"dir": args.dir, "drugs": recs}, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"\n📝 {out}")
        print("※PMDA添付文書の『正典値』。台本の主張がこれと一致するかを照合（人の記憶に依存しない）。版ずれ注意＝定期再DL＋索引再生成。")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
