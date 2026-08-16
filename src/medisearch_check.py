# -*- coding: utf-8 -*-
r"""
medisearch_check.py ― 医療特化AI「MediSearch」で医学的な問い/主張を裏取り（citation-first・出典付き）。
medcheck(自前PubMed RAG)/figcheck(画像)に続く"第3の検品ツール"。MediSearchが科学文献/ガイドラインをRAGし、
出典[1][2]…付きの回答を返す。出典種別を scientificArticles/guidelines に限定＝EBM厳格（healthBlogs除外）。

要 APIキー（無料）：https://medisearch.io/developers/signup で取得 → setx MEDISEARCH_API_KEY <key>
要 パッケージ：pip install --user medisearch-client

使い方:
  python src/medisearch_check.py "安定ヨウ素剤は放射性ヨウ素の甲状腺への取り込みをブロックするか？"
  python src/medisearch_check.py "TPOはヨウ化物を酸化しサイログロブリンのチロシンに付加するか" --article-types reviews,metaAnalysis
"""
import os
import sys
import argparse
import uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # 鍵は env_boot.resolve() で読取専用取得（os.environ非汚染・過剰伝播#3回避）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

EBM_SOURCES = ["scientificArticles", "internationalHealthGuidelines", "medicineGuidelines", "books"]  # healthBlogs除外＝EBM厳格


def main():
    ap = argparse.ArgumentParser(description="MediSearch（医療特化AI・citation-first）で医学的な問い/主張を裏取り")
    ap.add_argument("question", help="医学的な問い or 主張（日本語可）")
    ap.add_argument("--sources", default=",".join(EBM_SOURCES), help=f"出典種別（カンマ区切り）。有効={EBM_SOURCES}+healthBlogs")
    ap.add_argument("--article-types", default="", help="論文種別で絞る＝metaAnalysis,reviews,clinicalTrials,observationalStudies,other")
    ap.add_argument("--year-start", type=int, default=None, help="この年以降の文献に限定")
    ap.add_argument("--model", default="pro", help="pro/standard/max_deep/max/lightning 等")
    ap.add_argument("--lang", default="Japanese", help="回答言語")
    args = ap.parse_args()

    key = env_boot.resolve("MEDISEARCH_API_KEY")  # 読取専用（env優先・無ければレジストリ・os.environ非汚染）
    if not key:
        print("[fail] MEDISEARCH_API_KEY 未設定。https://medisearch.io/developers/signup で無料取得 → setx MEDISEARCH_API_KEY <key>")
        sys.exit(2)
    try:
        from medisearch_client import MediSearchClient, Settings, Filters
    except ImportError:
        print("[skip] pip install --user medisearch-client")
        sys.exit(2)

    client = MediSearchClient(api_key=key)
    filters = Filters(
        sources=[s.strip() for s in args.sources.split(",") if s.strip()],
        year_start=args.year_start,
        article_types=[a.strip() for a in args.article_types.split(",") if a.strip()] or None,
    )
    settings = Settings(
        language=args.lang, filters=filters, model_type=args.model,
        system_prompt="出典に厳密に基づき、断定しすぎず、エビデンスの強さ（総説/RCT/観察等）にも触れて簡潔に。不確実な点は不確実と明示。",
    )
    cid = uuid.uuid4().hex
    print(f"■ MediSearch 問い: {args.question}\n■ 出典限定: {args.sources}"
          + (f" / 論文種別: {args.article_types}" if args.article_types else "") + f" / model={args.model}\n")

    try:
        events = client.send_message(conversation=[args.question], conversation_id=cid,
                                     settings=settings, should_stream_response=False)
    except Exception as e:
        print(f"[error] MediSearch呼び出し失敗: {e}")
        sys.exit(2)

    answer, articles = None, []
    for ev in events:
        et = ev.get("event")
        if et == "llm_response":
            answer = ev.get("data")
        elif et == "articles":
            articles = ev.get("data") or []
        elif et == "error":
            print(f"[error] {ev.get('data')}"); sys.exit(2)

    print("=" * 64)
    print(answer or "(回答が取得できませんでした)")
    print("\n── 出典（[n]は本文の[n]に対応）──")
    if not articles:
        print("(出典なし)")
    for i, a in enumerate(articles, 1):
        au = a.get("authors") or []
        au = (au[0] + " et al." if au else "")
        print(f"[{i}] {a.get('title', '?')}｜{a.get('journal', '')} {a.get('year', '')} {au}｜{a.get('url', '')}")
    print("\n※MediSearchも生成AI＝補助。最終は薬剤師＋一次資料（添付文書/ガイドライン原文）で確定。")


if __name__ == "__main__":
    main()
