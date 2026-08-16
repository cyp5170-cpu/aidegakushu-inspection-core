# -*- coding: utf-8 -*-
r"""
pmda_index.py ― PMDA添付文書XML(約17000製剤)を **YJコード**で索引化。
YJコード=12桁 個別医薬品コード（XMLファイル名の第2セグメント）。上7桁=成分コード＝後発品をまとめる鍵。
出力: src/checkdata/pmda_index.json  ＝ {成分コード7: {ingredient, products[], yj[], sample_xml}}
これにより「フォルダ名の部分一致(ファジー)」でなく、成分コードで一意・確実に紐づけできる（ユーザー指摘2026-08-13）。
版ずれ注意：ローカルはDL時点。改訂追従は定期再DL＋この索引の再生成で。
"""
import os, re, glob, json, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PMDA = r"C:\pmda\SGML_XML"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkdata", "pmda_index.json")
YJ_RE = re.compile(r"_([0-9A-Za-z]{12})_")


def ingredient_of(path):
    try:
        t = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return None
    m = re.search(r"<ActiveIngredientName\b[^>]*>(.*?)</ActiveIngredientName>", t, re.S)
    if not m:
        return None
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", m.group(1))) or None


def build():
    files = glob.glob(os.path.join(PMDA, "*", "*.xml"))
    print(f"PMDA XML: {len(files)}件 を索引化…")
    idx = {}
    t0 = time.time()
    for f in files:
        base = os.path.basename(f)
        m = YJ_RE.search(base)
        if not m:
            continue
        yj = m.group(1); s7 = yj[:7]
        folder = os.path.basename(os.path.dirname(f))
        e = idx.get(s7)
        if e is None:
            e = idx[s7] = {"seihun_code": s7, "ingredient": None,
                           "products": [], "yj": [], "sample_xml": os.path.relpath(f, PMDA)}
            e["ingredient"] = ingredient_of(f)   # 成分コードごと1回だけ読む＝高速
        if folder not in e["products"]:
            e["products"].append(folder)
        if yj not in e["yj"]:
            e["yj"].append(yj)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(idx, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"完了: {len(idx)}成分 / {sum(len(v['yj']) for v in idx.values())}製剤 → {OUT}  ({time.time()-t0:.1f}s)")
    return idx


if __name__ == "__main__":
    build()
