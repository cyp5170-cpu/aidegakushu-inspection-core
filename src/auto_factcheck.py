# -*- coding: utf-8 -*-
r"""
auto_factcheck.py ― 台本から「主張」を自動抽出し、MediSearch(医療特化AI)で出典付きに自動裏取り。

目的（ユーザー恒久方針 2026-08-13）＝**人(薬剤師)の記憶に頼らず、外部の権威(文献/ガイドライン)で検知する**。
台本の 用量/数値/禁忌 等の主張を機械が拾い、1件ずつ「支持/不支持/不明＋出典」で返す。
人は"知識で探す"のでなく"出典を見てGO/NO-GO"すればよい。

★注意＝country-specific(日本の添付文書)の用量は、国際文献(MediSearch)と数値が違うことがある。
   ＝機構/一般EBMはMediSearch、日本固有の用量は添付文書(用量台帳)が権威。両方で見るのが正。

使い方:
  python src/auto_factcheck.py --dir episodes/iodine/ep03 --max 4
  python src/auto_factcheck.py --dir episodes/iodine/ep03 --types dose,number --max 3
要 MEDISEARCH_API_KEY / pip install --user medisearch-client
"""
import os, sys, re, json, uuid, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # 鍵は env_boot.resolve() で読取専用取得（env優先＋レジストリ補完・os.environ非汚染・#3）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

EBM_SOURCES = ["scientificArticles", "internationalHealthGuidelines", "medicineGuidelines", "books"]
SEG = re.compile(r"[。！？\n]")

CLAIM_PATTERNS = {
    "dose":   re.compile(r"(\d+(?:\.\d+)?\s*(?:mg|μg|グラム))|丸\s*\d|ゼリー|\d+\s*丸|半量|16\.3|32\.5"),
    "number": re.compile(r"\d+\s*[%％]|\d+\s*倍|\d+\s*時間|\d+\s*mSv|半減期|\d+日"),
    "contra": re.compile(r"禁忌|過敏|慎重投与|妊婦|授乳|バセドウ|橋本|全摘|交付不可|アレルギ"),
    "mech":   re.compile(r"NIS|TPO|Wolff|有機化|濃縮|二次性能動輸送|甲状腺ホルモン|ブロック"),
}


def fields(l):
    out = []
    def add(v):
        if isinstance(v, str) and v.strip(): out.append(v)
    add(l.get("text"))
    for b in (l.get("board_bullets") or []): add(b)
    for k in ("trivia", "term_gloss", "supplement"):
        o = l.get(k)
        if isinstance(o, dict): add(o.get("note"))
    return out


def extract_claims(ep_dir, types):
    p = os.path.join(ep_dir, "script.json")
    data = json.load(open(p, encoding="utf-8"))
    seen, claims = set(), []
    for l in data.get("lines", []):
        lid = l.get("id")
        for t in fields(l):
            for seg in SEG.split(t):
                seg = seg.strip()
                if len(seg) < 8:
                    continue
                for ty in types:
                    if CLAIM_PATTERNS[ty].search(seg):
                        key = re.sub(r"\s+", "", seg)[:40]
                        if key in seen:
                            break
                        seen.add(key)
                        claims.append({"line": lid, "type": ty, "claim": seg})
                        break
    # 用量→数値→禁忌→機構 の優先で並べる
    order = {ty: i for i, ty in enumerate(["dose", "number", "contra", "mech"])}
    claims.sort(key=lambda c: order.get(c["type"], 9))
    return claims


def verify(client, Settings, Filters, claim, model, lang):
    filters = Filters(sources=EBM_SOURCES, article_types=None)
    settings = Settings(
        language=lang, filters=filters, model_type=model,
        system_prompt=("与えられた記述の医学的な正誤を、出典に厳密に基づいて判定する。"
                       "回答の冒頭で必ず【支持】【不支持】【不明】のいずれかを明記し、"
                       "続けて根拠を2〜3文で簡潔に。数値は出典の値を示す。過大な断定は避け、"
                       "出典で確認できない点は【不明】とする。日本語で。"),
    )
    q = f"次の記述は医学的に正しいですか。出典に基づき判定してください：「{claim}」"
    events = client.send_message(conversation=[q], conversation_id=uuid.uuid4().hex,
                                 settings=settings, should_stream_response=False)
    ans, arts = None, []
    for ev in events:
        if ev.get("event") == "llm_response": ans = ev.get("data")
        elif ev.get("event") == "articles": arts = ev.get("data") or []
        elif ev.get("event") == "error": return "不明", f"[error] {ev.get('data')}", []
    verdict = "不明"
    if ans:
        head = ans[:40]
        if "不支持" in head: verdict = "不支持"
        elif "支持" in head: verdict = "支持"
        elif "不明" in head: verdict = "不明"
    return verdict, ans, arts


def main():
    ap = argparse.ArgumentParser(description="台本の主張を自動抽出→MediSearchで出典付き自動裏取り")
    ap.add_argument("--dir", required=True, help="episodes/<series>/<ep>")
    ap.add_argument("--types", default="dose,number,contra", help="dose,number,contra,mech")
    ap.add_argument("--max", type=int, default=4, help="裏取りする主張の上限(API節約)")
    ap.add_argument("--model", default="pro")
    ap.add_argument("--lang", default="Japanese")
    ap.add_argument("--dry", action="store_true", help="抽出のみ(API呼ばない)")
    args = ap.parse_args()

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    claims = extract_claims(args.dir, types)
    print("=" * 70)
    print(f"🔎 主張の自動抽出: {args.dir}  抽出{len(claims)}件（種別={','.join(types)}）")
    print("=" * 70)
    for i, c in enumerate(claims, 1):
        print(f"  [{i}] ({c['type']}) line{c['line']}: {c['claim'][:70]}")
    if args.dry:
        return

    key = env_boot.resolve("MEDISEARCH_API_KEY")  # env優先＋HKCU\Environment補完を一本化（読取専用・#3）
    if not key:
        print("\n[fail] MEDISEARCH_API_KEY 未設定（環境変数・レジストリとも無し）"); sys.exit(2)
    try:
        from medisearch_client import MediSearchClient, Settings, Filters
    except ImportError:
        print("[skip] pip install --user medisearch-client"); sys.exit(2)
    client = MediSearchClient(api_key=key)

    target = claims[:args.max]
    print(f"\n🧪 MediSearchで自動裏取り（上限{args.max}件）… 各10〜30秒\n")
    results = []
    for i, c in enumerate(target, 1):
        print(f"── [{i}/{len(target)}] ({c['type']}) 「{c['claim'][:56]}」")
        try:
            v, ans, arts = verify(client, Settings, Filters, c["claim"], args.model, args.lang)
        except Exception as e:
            v, ans, arts = "不明", f"[error] {e}", []
        mark = {"支持": "🟢支持", "不支持": "🔴不支持", "不明": "🟡不明"}.get(v, v)
        print(f"   → {mark}")
        if ans: print("   " + (ans[:280].replace("\n", "\n   ")))
        for j, a in enumerate(arts[:3], 1):
            print(f"     [{j}] {a.get('title','?')[:60]}｜{a.get('journal','')} {a.get('year','')}｜{a.get('url','')}")
        print()
        results.append({"line": c["line"], "type": c["type"], "claim": c["claim"],
                        "verdict": v, "answer": ans, "citations": [a.get("url") for a in arts[:3]]})

    out = os.path.join(args.dir, "factcheck.json")
    json.dump({"dir": args.dir, "results": results}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    ng = [r for r in results if r["verdict"] == "不支持"]
    print("=" * 70)
    print(f"📝 {out}  ／ 支持{sum(r['verdict']=='支持' for r in results)}・不支持{len(ng)}・不明{sum(r['verdict']=='不明' for r in results)}")
    if ng:
        print("🔴 不支持（要確認）:")
        for r in ng: print(f"   line{r['line']}: {r['claim'][:60]}")
    print("※MediSearchも生成AI＝補助。日本固有の用量は添付文書(用量台帳)が権威。最終GOは出典を見て判断。")


if __name__ == "__main__":
    main()
