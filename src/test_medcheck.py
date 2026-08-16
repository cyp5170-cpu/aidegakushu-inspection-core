# -*- coding: utf-8 -*-
"""medcheck 回帰テスト（APIキー不要・純関数）＝既知失敗の再発防止。
実行: python src/test_medcheck.py  （FAILがあれば非ゼロ終了）"""
import sys
import os
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xml.etree.ElementTree as ET
import medcheck as m

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok  {name}")
    else:
        FAIL += 1; print(f" FAIL {name}")


# --- HIGH-1: 逐語照合が「その出典の抄録」に紐付く（出典すり替え検出） ---
A = {"abstract": "The sodium iodide symporter transports iodide across the basolateral membrane of thyrocytes."}
B = {"abstract": "Thyroid peroxidase catalyzes organification at the apical membrane of the follicular cell."}
check("HIGH-1 自出典に一致", m._quote_grounded("transports iodide across the basolateral membrane", A) is True)
check("HIGH-1 別出典すり替えを弾く", m._quote_grounded("transports iodide across the basolateral membrane", B) is False)
check("HIGH-1 短い引用(<15字)を弾く", m._quote_grounded("basolateral", A) is False)
check("HIGH-1 空白ゆらぎに頑健", m._quote_grounded("transports  iodide  across the basolateral membrane", A) is True)

# --- B1: 臨床の問いをコード側でも検出（LLM自己申告のごまかし対策） ---
check("clinical 治療語を検出", m._looks_clinical("この薬は不安を減らす") is True)
check("clinical 機構は非臨床", m._looks_clinical("NISは甲状腺の基底膜にある") is False)

# --- C1: 撤回・懸念・動物の検出 ---
check("撤回 PublicationType", m.is_retracted({"pubtypes": ["Journal Article", "Retracted Publication"], "refflags": []}) is True)
check("撤回 RetractionIn(refflag)", m.is_retracted({"pubtypes": ["Journal Article"], "refflags": ["RetractionIn"]}) is True)
check("撤回 正常はFalse", m.is_retracted({"pubtypes": ["Review"], "refflags": []}) is False)
check("懸念表明 EoC", m.has_concern({"refflags": ["ExpressionOfConcernIn"]}) is True)
check("動物のみ検出", m.is_animal_only({"mesh": ["Animals", "Rats"]}) is True)
check("ヒト含むは動物のみでない", m.is_animal_only({"mesh": ["Animals", "Humans"]}) is False)

# --- エビデンス階層・教科書 ---
check("tier SR/メタ最上位", m._tier_rank(["Meta-Analysis"]) == 0)
check("tier 教科書は強い二次", m._tier_rank(["Textbook"]) == 1)
check("hint 教科書表示", m._evidence_hint(["Textbook"]) == "教科書(二次)")
check("tier 症例報告は弱い", m._tier_rank(["Case Reports"]) == 5)

# --- 教科書(PubmedBookArticle)パース＝機構の権威が脱落しない ---
book_xml = ("<PubmedBookArticle><BookDocument><PMID>1</PMID>"
            "<ArticleTitle>Physiology, Thyroid Hormone</ArticleTitle>"
            "<Abstract><AbstractText>Iodide is taken up by NIS at the basolateral membrane.</AbstractText></Abstract>"
            "<Book><BookTitle>StatPearls</BookTitle></Book></BookDocument></PubmedBookArticle>")
ba = m._parse_article(ET.fromstring(book_xml), is_book=True)
check("book: Textbookタグ付与", "Textbook" in ba["pubtypes"])
check("book: 抄録取得", "basolateral membrane" in ba["abstract"])
check("book: tier上位(1)", m._tier_rank(ba["pubtypes"]) == 1)

# --- 撤回検出のXML経路（CommentsCorrections） ---
art_xml = ("<PubmedArticle><MedlineCitation><PMID>2</PMID>"
           "<Article><ArticleTitle>Some study</ArticleTitle>"
           "<Abstract><AbstractText>Result text here for testing purposes only.</AbstractText></Abstract></Article>"
           "<CommentsCorrectionsList><CommentsCorrections RefType='RetractionIn'><PMID>999</PMID></CommentsCorrections>"
           "</CommentsCorrectionsList></MedlineCitation></PubmedArticle>")
aa = m._parse_article(ET.fromstring(art_xml), is_book=False)
check("XML撤回: refflag抽出", "RetractionIn" in aa["refflags"])
check("XML撤回: is_retracted=True", m.is_retracted(aa) is True)

print(f"\n== {PASS} passed / {FAIL} failed ==")
sys.exit(1 if FAIL else 0)
