#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pre_submit_gate.py  ―  提出前ゲート（多AI予測＋敵対レビューを統合した先回り検知器）

目的（ユーザー恒久指示 2026-08-13）:
  「エラーが起きてからではなく、あらかじめ起こりうるエラーをあらゆる角度から予想して検知する。
   予測だけでなく“過去に実際に起きたエラー”も必ず検知する。」

構成:
  4体のAI予測（医学/視覚/初学者/プロセス法務）＋別モデルGemini＋実装後の敵対的コード/検知レビューを反映。
  静的に自動判定できる分を1本のゲートに集約。実データ(対照表)は src/checkdata/*.json に外出し＝育てられる。

主な検知:
  FAIL … 危険な断定/効能・色誤り・機構カテゴリ取り違え・局在誤り・比喩不整合・過去エラー回帰
  WARN … 最上級・特殊集団断定・効能言い切り・用量域外/単位・因果方向逆転・数値不整合・免責不足
  INFO … 方向語・比喩マーカー・擬人化・定量裏取り・未登録略語・パネル尺・未スキャン領域・stale

使い方:
  py src/pre_submit_gate.py --ep 01
  py src/pre_submit_gate.py --dir episodes/iodine/ep01
  py src/pre_submit_gate.py --self-test

出力: 標準出力レポート ＋ <ep_dir>/audit.json（監査証跡: 入力ハッシュ紐付け）。FAILがあれば終了コード1。
"""

import os
import re
import sys
import json
import glob
import hashlib
import argparse

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "checkdata")

# ---- 正規化（漢数字割・全角・パーセント表記を算用%へ。表記替えでの検知回避を防ぐ FN-5）----
_Z2H = str.maketrans("０１２３４５６７８９％～", "0123456789%~")
_KANJI = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _wari(m):
    d = m.group(1)
    n = int(d) if d.isdigit() else _KANJI.get(d, 0)
    return f"{n * 10}%"


def normalize(text):
    if not text:
        return ""
    t = text.translate(_Z2H)
    t = t.replace("パーセント", "%").replace("percent", "%")
    t = re.sub(r"([0-9一二三四五六七八九])\s*割", _wari, t)
    return t


# ---- 否定・限定・対比・肯定強調のガード（FP-1/2/4/5, FN-8）----
NEG_MARKERS = ["ではない", "ではなく", "でなく", "じゃない", "ではありませ", "ではなし",
               "ない", "なし", "とは異な", "と違っ"]
LIMIT_SUFFIX = ["とは限", "わけではない", "わけでない", "とは言えない", "とは言え",
                "こともあ", "場合があ", "人もい", "個人差", "とはいえ"]
POS_EMPH = ["過言ではない", "に他ならない", "と言わざるを得", "ないとは言えない", "ないとは限らない"]
CONTRAST = ["一方", "別物", "とは別", "に対し", "違って", "と違い", "のに対して", "と異なり", "ではなく"]
FOLLOW_EXCLUDE = {"無害": "化"}  # 「無害化(解毒)」は誤爆させない
SEG_SPLIT = re.compile(r"[。！？\n]")
_NEG_RE = re.compile(r"とは.{0,4}(異な|違)")


def segments(text):
    return [s for s in SEG_SPLIT.split(text) if s.strip()]


def _tail(seg, w):
    idx = seg.find(w)
    while idx != -1:
        yield idx, seg[idx + len(w): idx + len(w) + 18]
        idx = seg.find(w, idx + 1)


def looks_asserted(seg, w):
    """seg中のwが『生きた断定』としてあるならTrue（否定/限定/無害化ならFalse）。"""
    found_any = False
    for idx, tail in _tail(seg, w):
        found_any = True
        exc = FOLLOW_EXCLUDE.get(w)
        if exc and seg[idx + len(w):].startswith(exc):
            continue
        if any(p in tail for p in POS_EMPH):
            return True
        if any(n in tail for n in NEG_MARKERS) or _NEG_RE.search(tail) or any(l in tail for l in LIMIT_SUFFIX):
            continue
        return True
    return False if not found_any else False


def occurrence_status(seg, w):
    """color/protein用。'assert'(FAIL)/'contrast'(WARN)/'skip'(否定)を返す。"""
    result = "skip"
    for idx, tail in _tail(seg, w):
        if any(p in tail for p in POS_EMPH):
            return "assert"
        if any(n in tail for n in NEG_MARKERS) or _NEG_RE.search(tail):
            continue
        if any(c in seg for c in CONTRAST):
            result = "contrast"
            continue
        return "assert"
    return result


def snippet(text, kw, width=28):
    idx = text.find(kw)
    if idx == -1:
        return text[:width].replace("\n", " ")
    a = max(0, idx - width // 3)
    return text[a: a + width].replace("\n", " ")


# ---- データ読み込み（起動時に1回・正規表現は事前コンパイル）----
def load_json(name, required=True):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        if required:
            raise FileNotFoundError(path)
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_tables():
    t = {
        "lex": load_json("lexicon.json"),
        "color": load_json("substance_color.json"),
        "protein": load_json("protein_class.json"),
        "past": load_json("past_errors.json"),
        "dose": load_json("dose_range.json", required=False),
        "causal": load_json("causal_direction.json", required=False),
        "numeric_topics": load_json("numeric_topics.json", required=False),
        "medsafety": load_json("medsafety.json", required=False),
        "imgconflict": load_json("image_text_conflict.json", required=False),
    }
    for key in ("past", "causal"):
        tbl = t.get(key)
        if tbl:
            for e in tbl.get("entries", []):
                try:
                    e["_re"] = re.compile(e["pattern"])
                except re.error as ex:
                    print(f"⚠ 正規表現エラー {key} {e.get('id')}: {ex}")
                    e["_re"] = None
    return t


# ---- フィールド収集（表示テキストを全部・正規化）----
CONTENT_KEYS = {"text", "board_title", "board_bullets", "thumb_hook_text",
                "clinical_caution", "trivia", "term_gloss", "supplement", "card_text"}
STRUCT_KEYS = {"id", "section", "speaker", "emotion", "expression", "image_keyword",
               "bgm_track", "guideline_ref", "extra_photo", "chapter_chip", "pins",
               "cut_icons", "board_bullets", "image", "images", "layout", "duration"}


def collect_fields(line):
    out = []

    def add(fname, val):
        if isinstance(val, str) and val.strip():
            out.append((fname, normalize(val)))

    add("text", line.get("text"))
    add("board_title", line.get("board_title"))
    add("thumb_hook_text", line.get("thumb_hook_text"))
    for i, b in enumerate(line.get("board_bullets") or []):
        add(f"board_bullets[{i}]", b)
    for key in ("trivia", "term_gloss", "supplement"):
        obj = line.get(key)
        if isinstance(obj, dict):
            add(f"{key}.note", obj.get("note"))
            add(f"{key}.term", obj.get("term"))
            add(f"{key}.abbr", obj.get("abbr"))
            add(f"{key}.full", obj.get("full"))
    cc = line.get("clinical_caution")
    if isinstance(cc, dict):
        add("clinical_caution.title", cc.get("title"))
        add("clinical_caution.text", cc.get("text"))
    ct = line.get("card_text")
    if isinstance(ct, dict):
        add("card_text.title", ct.get("title"))
        add("card_text.caption", ct.get("caption"))
        for i, lb in enumerate(ct.get("labels") or []):
            add(f"card_text.labels[{i}]", lb)
    return out


# ================= 各検知モジュール =================

def check_lexicon(lid, fields, lex, findings):
    for cat, spec in lex.items():
        if cat.startswith("_"):
            continue
        level, cls, reason = spec["level"], spec["class"], spec["reason"]
        suppress = spec.get("suppress_near", [])
        for fname, text in fields:
            for seg in segments(text):
                if suppress and any(s in seg for s in suppress):
                    continue
                for w in spec["words"]:
                    if w in seg and looks_asserted(seg, w):
                        findings.append({"level": level, "class": cls, "line": lid, "field": fname,
                                         "hit": w, "snippet": snippet(seg, w), "reason": reason})


def check_quantitative_overreach(lid, fields, findings):
    pct = re.compile(r"(\d{1,3})\s*%")
    ge = ("以上", "に達", "を超え", "上回")
    hi_say = ("ほぼ", "近い", "達し")
    for fname, text in fields:
        for seg in segments(text):
            hedge = any(h in seg for h in ("約", "およそ", "〜", "～", "~", "程度", "ほど", "前後"))
            imminent = any(k in seg for k in ("直前", "直後", "被ばく前", "被曝前", "同時", "曝露前"))  # 直前投与文脈＝95〜99%は台帳確定(2026-08-14薬剤師サインオフ)
            has_ge = any(g in seg for g in ge)
            for m in pct.finditer(seg):
                val = int(m.group(1))
                if has_ge and val >= 90 and not hedge:
                    if imminent and val <= 99:               # 直前〜直後投与の理想条件は文献上95〜99%で妥当→WARNでなくINFO
                        findings.append({"level": "INFO", "class": "A-1 定量(直前投与文脈=許容)", "line": lid,
                                         "field": fname, "hit": f"{val}%", "snippet": seg[:44],
                                         "reason": "直前〜直後投与の理想条件は文献上95〜99%(台帳確定2026-08-14)。出典明記で可。"})
                    else:
                        findings.append({"level": "WARN", "class": "A-1 定量過大の疑い", "line": lid,
                                         "field": fname, "hit": f"{val}%以上級", "snippet": seg[:44],
                                         "reason": "高%を言い切り(ヘッジ無し)。範囲(約A〜B%)＋一次資料で裏取り。"})
                elif has_ge or "未満" in seg:
                    findings.append({"level": "INFO", "class": "A-1 定量+比較語", "line": lid,
                                     "field": fname, "hit": f"{val}%", "snippet": seg[:44],
                                     "reason": "定量+比較語。出典で裏取りし過大に断定しない。"})
            # 「以上」なしでも ほぼ100%/99%に達する 等
            if not has_ge:
                for m in pct.finditer(seg):
                    val = int(m.group(1))
                    if val >= 95 and any(h in seg for h in hi_say):
                        findings.append({"level": "WARN", "class": "A-1 定量過大(言い切り)", "line": lid,
                                         "field": fname, "hit": f"{val}%", "snippet": seg[:44],
                                         "reason": "『ほぼ/に達する』＋高%の言い切り。範囲＋出典で裏取り。"})


# 帰属ガード：wrong語(局在/受容体)が"別の分子/別の受容体"に付いている行を誤検知しない
# （FP対策・iodine_supplement/ep01で判明＝「基底膜NISから頂端膜ペンドリンへ」「TSH受容体に結合しNIS発現」等は正しい文）
_APICAL_MOLS = ("ペンドリン", "pendrin", "slc26a4", "ano1", "tpo", "duox")
_KNOWN_RECEPTORS = ("tsh受容体", "trh受容体", "インスリン受容体", "アセチルコリン受容体", "ホルモン受容体", "核内受容体", "gpcr")


def _wrong_belongs_to_other(seg, ww, own_names):
    """wrong語が『別の分子/別の受容体』に帰属していれば True＝このタンパクの誤りではない（＝誤検知）。
    真の誤り（例「NISは頂端膜」「NISは受容体」＝NIS自身に直結）は False を返して検出を残す。"""
    low = seg.lower()
    if ww == "受容体":                                             # 『TSH受容体』等の既知受容体に帰属し、NISが受容体語に直結していなければ別物
        if any(k in low for k in _KNOWN_RECEPTORS):
            for m in re.finditer("受容体", seg):
                pre = seg[max(0, m.start() - 4):m.start()]
                if any(n in pre for n in own_names):               # 直前がNIS系＝真の「NISは受容体」誤り→残す
                    return False
            return True
        return False
    for m in re.finditer(re.escape(ww), seg):                       # 局在語(頂端/アピカル/コロイド側/管腔側)の直後に別のアピカル分子→その分子の局在
        after = low[m.end(): m.end() + 12]
        if any(a in after for a in _APICAL_MOLS):
            return True
    return False


def _class_field_scan(lid, fname, text, entry, kinds, cls, findings, note_key="note"):
    """name/aliasが出た文＋隣接文でwrong語を探す(文跨ぎ対応 FN-3/4)。否定=skip・対比=WARN降格。
    帰属ガード：wrong語が別分子/別受容体に帰属する行は誤検知として除外（_wrong_belongs_to_other）。"""
    segs = segments(text)
    label = entry.get("name") or entry.get("substance")
    names = [n for n in ([label] + entry.get("aliases", [])) if n]
    name_idxs = [i for i, s in enumerate(segs) if any(n in s for n in names)]
    if not name_idxs:
        return
    seen = set()
    for kind_label, words, extra_reason in kinds:
        for i in name_idxs:
            for j in (i, i + 1):
                if j >= len(segs):
                    continue
                seg = segs[j]
                for ww in words:
                    if ww not in seg or (ww, j) in seen:
                        continue
                    st = occurrence_status(seg, ww)
                    if st == "skip":
                        continue
                    if kind_label == "localization" or ww == "受容体":     # 帰属ガード：別分子/別受容体に付く語は誤検知
                        if _wrong_belongs_to_other(seg, ww, names):
                            continue
                    seen.add((ww, j))
                    level = "WARN" if st == "contrast" else "FAIL"
                    findings.append({"level": level, "class": cls, "line": lid, "field": fname,
                                     "hit": f"{entry.get('name') or entry.get('substance')}×{ww}",
                                     "snippet": seg[:44],
                                     "reason": f"{extra_reason} {entry.get(note_key, '')}"})


def check_protein_class(lid, fields, table, findings):
    for fname, text in fields:
        for e in table["entries"]:
            kinds = [
                ("category", e.get("wrong_words", []), "機構カテゴリ取り違え。"),
                ("metaphor", e.get("wrong_metaphors", []), "比喩の機構不一致。"),
                ("localization", e.get("wrong_localization", []),
                 f"局在誤り(正:{e.get('correct_localization', '')})。"),
            ]
            _class_field_scan(lid, fname, text, e, kinds, "C-1/2 機構・局在", findings)


def check_substance_color(lid, fields, table, findings):
    for fname, text in fields:
        for e in table["entries"]:
            kinds = [("color", e.get("wrong", []), f"色の取り違え(正:{'/'.join(e.get('correct', []))})。")]
            _class_field_scan(lid, fname, text, e, kinds, "G-1 色の取り違え", findings)


def check_past_errors(lid, fields, table, findings):
    for fname, text in fields:
        for e in table["entries"]:
            rx = e.get("_re")
            if not rx:
                continue
            m = rx.search(text)
            if not m:
                continue
            if e.get("context_all") and not all(c in text for c in e["context_all"]):
                continue
            if e.get("context_any") and not any(c in text for c in e["context_any"]):
                continue
            if e.get("exclude") and any(c in text for c in e["exclude"]):
                continue
            findings.append({"level": e["level"], "class": e["class"], "line": lid, "field": fname,
                             "hit": f"{e['id']}:{m.group(0)}", "snippet": snippet(text, m.group(0)),
                             "reason": e["reason"]})


_DOSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|μg|㎍|mcg|ug|g|mL|ml|IU)")
_UNIT_NORM = {"mcg": "μg", "ug": "μg", "㎍": "μg", "ml": "mL"}


def check_dose(lid, fields, table, findings):
    if not table:
        return
    for fname, text in fields:
        drugs = [e for e in table["entries"]
                 if any(a in text for a in [e["drug"]] + e.get("aliases", []))]
        if not drugs:
            continue
        for m in _DOSE_RE.finditer(text):
            val = float(m.group(1))
            unit = _UNIT_NORM.get(m.group(2), m.group(2))
            for e in drugs:
                exp = e["unit_expected"]
                if unit not in exp:
                    cmp = val * 1000 if (unit == "g" and "mg" in exp) else None
                    extra = f"(mg換算{cmp:g})" if cmp else ""
                    findings.append({"level": "WARN", "class": "A-3/4 単位・桁の疑い", "line": lid,
                                     "field": fname, "hit": f"{e['drug']} {m.group(0)}{extra}",
                                     "snippet": snippet(text, m.group(0)),
                                     "reason": f"想定単位{'/'.join(exp)}と不一致。{e.get('ref', '')}"})
                elif val < e["min"] or val > e["max"]:
                    findings.append({"level": "WARN", "class": "A-4 用量域外の疑い", "line": lid,
                                     "field": fname, "hit": f"{e['drug']} {m.group(0)}",
                                     "snippet": snippet(text, m.group(0)),
                                     "reason": f"常用域 約{e['min']}〜{e['max']}{exp[0]} を外れる。{e.get('ref', '')}"})


def check_causal(lid, fields, table, findings):
    if not table:
        return
    for fname, text in fields:
        for e in table["entries"]:
            rx = e.get("_re")
            if rx and rx.search(text):
                findings.append({"level": "WARN", "class": "C-3/J 因果・方向逆転の疑い", "line": lid,
                                 "field": fname, "hit": e["id"], "snippet": snippet(text, ""),
                                 "reason": e["reason"]})


def check_image_text_conflict(lid, line, table, findings):
    """画像(image_keyword)が描く機構と台詞(text)の機構が矛盾していないかを確定論で検知。
    ＝『textは直したが絵は旧機構のまま』のサイレント事故を強制FAILで止める(ep02 id12実発生)。
    データ駆動＝checkdata/image_text_conflict.json のルールで育てる。純関数寄り＝self-test対象。"""
    if not table:
        return
    kw = (line.get("image_keyword") or "").lower()
    if not kw:
        return
    blob = " ".join(t for _, t in collect_fields(line))
    for rule in table.get("rules", []):
        if not any(str(tok).lower() in kw for tok in rule.get("image_any", [])):
            continue
        if rule.get("text_any") and not any(tok in blob for tok in rule["text_any"]):
            continue
        if any(tok in blob for tok in rule.get("text_not", [])):
            continue
        findings.append({"level": rule.get("level", "FAIL"),
                         "class": rule.get("class", "A-8 画像×台詞の機構不整合"),
                         "line": lid, "field": "image_keyword", "hit": kw,
                         "snippet": rule.get("message", ""), "reason": rule.get("reason", "")})


def check_unscanned_fields(lid, line, findings):
    """未知キーに日本語本文が入っていたら全検知を回避しうる(FN-11)。INFOで警告。"""
    known = CONTENT_KEYS | STRUCT_KEYS
    jp = re.compile(r"[぀-ヿ一-鿿]")
    for k, v in line.items():
        if k in known:
            continue
        if isinstance(v, str) and len(v) >= 8 and jp.search(v):
            findings.append({"level": "INFO", "class": "カバレッジ 未スキャン領域", "line": lid,
                             "field": k, "hit": k, "snippet": v[:30],
                             "reason": "未知キーに本文らしき日本語。collect_fieldsの対象に追加するか確認。"})


def check_med_safety(lid, fields, ms, findings):
    """多AI(臨床薬剤師/コンプラ)由来のP0致死・違法級の静的検知。週1薬×連日・経路NEVER・販売名・否定済み定説。"""
    if not ms:
        return
    wk, rn, bn, db = ms["weekly_drugs"], ms["route_never"], ms["brand_names"], ms["debunked"]
    for fname, text in fields:
        for seg in segments(text):
            hw = [d for d in wk["drugs"] if d in seg]
            hd = [w for w in wk["daily_words"] if w in seg]
            if hw and hd:
                findings.append({"level": wk["level"], "class": wk["class"], "line": lid, "field": fname,
                                 "hit": f"{hw[0]}×{hd[0]}", "snippet": seg[:50], "reason": wk["reason"]})
            for rule in rn["rules"]:
                d = next((x for x in rule["drug"] if x in seg), None)
                n = next((x for x in rule["never"] if x in seg), None)
                if d and n:
                    findings.append({"level": rn["level"], "class": rn["class"], "line": lid, "field": fname,
                                     "hit": f"{d}×{n}", "snippet": seg[:50], "reason": rule["note"]})
            for brand, generic in bn["map"].items():
                if brand in seg:
                    findings.append({"level": bn["level"], "class": bn["class"], "line": lid, "field": fname,
                                     "hit": f"{brand}→{generic}", "snippet": seg[:44], "reason": bn["reason"]})
            for item in db["items"]:
                if item in seg:
                    findings.append({"level": db["level"], "class": db["class"], "line": lid, "field": fname,
                                     "hit": item, "snippet": seg[:44], "reason": db["reason"]})


def check_action_class(lines, ms, findings):
    """作用クラスの相加（高K/QT/セロトニン）＝個別禁忌でなくても複数登場で相加リスク。話単位で検知。"""
    if not ms:
        return
    ac = ms["action_class"]
    blob = " ".join(t for l in lines for _, t in collect_fields(l))
    for cls, drugs in ac["classes"].items():
        present = sorted(set(d for d in drugs if d in blob))
        if len(present) >= 2:
            findings.append({"level": ac["level"], "class": ac["class"], "line": "-",
                             "field": f"作用クラス:{cls}", "hit": " / ".join(present[:5]), "snippet": "",
                             "reason": ac["reason"]})


def check_numeric_consistency(lines, tables, findings):
    topics = (tables.get("numeric_topics") or {}).get("entries", [])
    if not topics:
        return
    rng = re.compile(r"(\d{1,3})\s*%?\s*[〜～~\-–—]\s*(\d{1,3})\s*%")
    single = re.compile(r"(\d{1,3})\s*%")

    def extract(seg):
        nums = []
        for m in rng.finditer(seg):
            nums += [int(m.group(1)), int(m.group(2))]
        for m in single.finditer(seg):
            nums.append(int(m.group(1)))
        return nums

    def match_topic(seg, t):
        if not all(w in seg for w in t.get("require_all", [])):
            return False
        for grp in t.get("require_any_groups", []):
            if not any(w in seg for w in grp):
                return False
        return True

    def consistent(ranges):
        rs = list(ranges)

        def contains(a, b):
            return a[0] <= b[0] and b[1] <= a[1]
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if not (contains(rs[i], rs[j]) or contains(rs[j], rs[i])):
                    return False
        return True

    for t in topics:
        items = []
        for line in lines:
            lid = line.get("id")
            for fname, text in collect_fields(line):
                for seg in segments(text):
                    if match_topic(seg, t):
                        nums = extract(seg)
                        if nums:
                            items.append((lid, fname, (min(nums), max(nums))))
        ranges = {r for _, _, r in items}
        if len(ranges) > 1 and not consistent(ranges):
            detail = "; ".join(f"line{l}<{f}>:{a}〜{b}%" for l, f, (a, b) in items)
            findings.append({"level": "WARN", "class": "5 数値不整合(図間/フィールド間)", "line": "-",
                             "field": t["name"], "hit": " / ".join(f"{a}〜{b}%" for a, b in sorted(ranges)),
                             "snippet": detail[:90],
                             "reason": f"『{t['name']}』の%が箇所で食い違う。1つの正値(出典)に統一。改稿の波及漏れの疑い。"})


def check_disclaimer(lines, findings):
    blob = " ".join(t for l in lines for _, t in collect_fields(l))
    advisor = [k for k in ("主治医", "薬剤師", "医師", "医療機関") if k in blob]
    action = [k for k in ("相談", "受診", "確認くださ") if k in blob]
    if not (advisor and action):
        findings.append({"level": "WARN", "class": "F-6 免責・受診勧奨の不足", "line": "-",
                         "field": "(全体)", "hit": f"勧奨先{advisor}/行動{action}", "snippet": "",
                         "reason": "『医師/薬剤師 等へ相談/受診』の定型免責が不足。学習用免責＋受診勧奨を明示。"})


def check_reading_dict(lines, findings):
    rd_path = os.path.join(HERE, "reading_dict.json")
    known = set()
    if os.path.exists(rd_path):
        with open(rd_path, "r", encoding="utf-8") as f:
            rd = json.load(f)
        for it in rd.get("dict", []):
            known.add(it.get("surface"))
        for it in rd.get("tts_replace", []):
            known.add(it.get("find"))
    abbr = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}")
    seen = set()
    for l in lines:
        t = l.get("text", "") or ""
        for m in abbr.findall(t):
            if m in known or m.isdigit() or m in seen:
                continue
            seen.add(m)
            findings.append({"level": "INFO", "class": "K-2 未登録略語(読み)", "line": l.get("id"),
                             "field": "text", "hit": m, "snippet": snippet(t, m),
                             "reason": "reading_dict.json未登録の英字。読み(TTS)を登録すると誤読防止。"})


def check_panel_duration(lid, line, findings):
    for key in ("term_gloss", "trivia", "supplement"):
        obj = line.get(key)
        if isinstance(obj, dict) and obj.get("note"):
            note = obj["note"]
            longest = max((len(s) for s in note.split("\n")), default=0)
            total = len(note.replace("\n", ""))
            if total > 140 or longest > 52:
                findings.append({"level": "INFO", "class": "尺 パネル可読性", "line": lid,
                                 "field": f"{key}.note", "hit": f"{total}字/最長{longest}字",
                                 "snippet": note[:40],
                                 "reason": "パネルが長め。スマホで読める表示尺を確保(短すぎ厳禁だが情報過多も可読性低下)。"})


def check_stale(ep_dir, findings):
    sj = os.path.join(ep_dir, "script.json")
    if not os.path.exists(sj):
        return
    s_m = os.path.getmtime(sj)
    # review_log（Gemini敵対的医学レビュー）の鮮度＝台本がreviewより新しければ"旧版を褒めている"＝WARN（多AI提言G/2026-08-15）
    rl = os.path.join(ep_dir, "review_log.md")
    if os.path.exists(rl) and os.path.getmtime(rl) < s_m:
        findings.append({"level": "WARN", "class": "A-6 review_log旧版(敵対レビュー鮮度)", "line": "-",
                         "field": "review_log.md", "hit": "stale",
                         "reason": "台本がreview_logより新しい＝Gemini敵対的医学レビューが旧版の台本を見ている。現行版で再レビュー(Gemini手貼り)して更新を。"})
    for base in ("assets/common/_fx", os.path.join(ep_dir, "assets", "_fx"),
                 os.path.join(HERE, "..", "assets", "common", "_fx")):
        hit = False
        for p in glob.glob(os.path.join(base, "_panel_*.png")):
            if os.path.getmtime(p) < s_m:
                findings.append({"level": "INFO", "class": "A-1 staleパネルキャッシュ", "line": "-",
                                 "field": os.path.basename(p), "hit": "cache<script.json", "snippet": "",
                                 "reason": "パネルキャッシュがscript.jsonより古い。note変更したら該当_panel_*.pngを削除→再ビルド。"})
                hit = True
                break
        if hit:
            break
    aud = os.path.join(ep_dir, "audio")
    if os.path.isdir(aud):
        wavs = [w for w in glob.glob(os.path.join(aud, "*.wav")) if "_旧テイク" not in w]
        old = [os.path.basename(w) for w in wavs if os.path.getmtime(w) < s_m]
        if old:
            findings.append({"level": "INFO", "class": "A-4 音声がscript.jsonより古い", "line": "-",
                             "field": "audio/", "hit": f"{len(old)}本", "snippet": ",".join(old[:5]),
                             "reason": "セリフ(text)を変えた行があれば要再録。text不変(note修正のみ)なら再利用でOK。"})


# ---- 検査パイプライン（run_gate と self_test で共有＝乖離防止）----
def run_line_checks(lid, line, tables, findings):
    fields = collect_fields(line)
    check_past_errors(lid, fields, tables["past"], findings)
    check_lexicon(lid, fields, tables["lex"], findings)
    check_substance_color(lid, fields, tables["color"], findings)
    check_protein_class(lid, fields, tables["protein"], findings)
    check_quantitative_overreach(lid, fields, findings)
    check_dose(lid, fields, tables.get("dose"), findings)
    check_causal(lid, fields, tables.get("causal"), findings)
    check_med_safety(lid, fields, tables.get("medsafety"), findings)
    check_image_text_conflict(lid, line, tables.get("imgconflict"), findings)
    check_panel_duration(lid, line, findings)
    check_unscanned_fields(lid, line, findings)


def check_line_id_sequence(lines, findings):
    """行id＝NV番号一致の暗黙契約を守る＝逆行/重複はFAIL、桁飛び(欠番)はWARN。
    lipsync/音声・字幕割当のズレ地雷（例:高血圧ep05で id列に1401/1402が混入）を先回り検知。多AI提言J/2026-08-15。"""
    ids = [l.get("id") for l in lines if isinstance(l.get("id"), int)]
    seen = set(); prev = None
    for i in ids:
        if i in seen:
            findings.append({"level": "FAIL", "class": "A-5 行id重複", "line": i,
                             "field": "id", "hit": str(i), "snippet": "同じidが複数行",
                             "reason": "行id=NV番号の一意契約違反＝音声/字幕の割当が衝突する。連番へ修正。"})
        seen.add(i)
        if prev is not None:
            if i <= prev:
                findings.append({"level": "FAIL", "class": "A-5 行id逆行/非単調", "line": i,
                                 "field": "id", "hit": f"{prev}→{i}", "snippet": f"idが {prev} の後に {i}（増加していない）",
                                 "reason": "行id=NV番号一致の暗黙契約違反。lipsync/音声ズレの地雷(ep04既往)。連番に直す。"})
            elif i - prev > 1:
                findings.append({"level": "WARN", "class": "A-5 行id桁飛び(欠番)", "line": i,
                                 "field": "id", "hit": f"{prev}→{i}", "snippet": f"idが {prev} から {i} へ飛ぶ(欠番)",
                                 "reason": "欠番＝録音/字幕の番号ズレの兆候。意図的でなければ連番へ。"})
        prev = i


def run_global_checks(lines, ep_dir, tables, findings):
    check_numeric_consistency(lines, tables, findings)
    check_action_class(lines, tables.get("medsafety"), findings)
    check_disclaimer(lines, findings)
    check_reading_dict(lines, findings)
    check_line_id_sequence(lines, findings)
    if ep_dir:
        check_stale(ep_dir, findings)


# ================= 実行 =================
def run_gate(ep_dir, emit_audit=True):
    sj = os.path.join(ep_dir, "script.json")
    if not os.path.exists(sj):
        print(f"❌ script.json が無い: {sj}")
        return False
    with open(sj, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as ex:
        print(f"❌ script.json が壊れています(JSON解析失敗): {ex}")
        return False

    lines = [l for l in (data.get("lines") or []) if isinstance(l, dict)]
    tables = load_tables()

    findings = []
    for line in lines:
        run_line_checks(line.get("id"), line, tables, findings)
    run_global_checks(lines, ep_dir, tables, findings)

    return _report(ep_dir, data, lines, findings, raw, emit_audit)


def _report(ep_dir, data, lines, findings, raw, emit_audit):
    fails = [f for f in findings if f["level"] == "FAIL"]
    warns = [f for f in findings if f["level"] == "WARN"]
    infos = [f for f in findings if f["level"] == "INFO"]
    title = (data.get("meta") or {}).get("title", "")

    print("=" * 70)
    print(f"🚦 提出前ゲート: {ep_dir}")
    print(f"   {title}")
    print(f"   行数 {len(lines)} / 検出 FAIL {len(fails)}・WARN {len(warns)}・INFO {len(infos)}")
    print("=" * 70)

    def dump(bucket, mark):
        for f in bucket:
            print(f"{mark} [{f['class']}] line {f['line']} <{f['field']}>  hit=「{f['hit']}」")
            if f.get("snippet"):
                print(f"      …{f['snippet']}…")
            print(f"      → {f['reason']}")

    if fails:
        print("\n🔴 FAIL（提出不可・要修正）")
        dump(fails, "  ✗")
    if warns:
        print("\n🟡 WARN（要確認）")
        dump(warns, "  !")
    if infos:
        print("\n🔵 INFO（リマインダ・裏取り推奨）")
        dump(infos, "  ·")

    input_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    if emit_audit:
        audit = {
            "ep_dir": ep_dir.replace("\\", "/"),
            "script_input_hash": input_hash,
            "counts": {"FAIL": len(fails), "WARN": len(warns), "INFO": len(infos)},
            "verdict": "FAIL" if fails else ("WARN" if warns else "PASS"),
            "findings": [{k: v for k, v in f.items()} for f in findings],
            "note": "この監査はscript.jsonの入力ハッシュに紐づく。改稿したら再実行し現行ハッシュで上書きすること(stale監査防止)。",
        }
        with open(os.path.join(ep_dir, "audit.json"), "w", encoding="utf-8") as f:
            json.dump(audit, f, ensure_ascii=False, indent=2)
        print(f"\n📝 監査証跡: {os.path.join(ep_dir, 'audit.json')}  (input_hash={input_hash})")

    print("\n" + "=" * 70)
    if fails:
        print("🔴 判定: 不合格 — FAILを修正するまで提出/ビルド不可。")
        return False
    if warns:
        print("🟡 判定: 警告あり — WARNを確認のうえ提出可。")
        return True
    print("🟢 判定: 合格 — 自動検知クラスはクリア（最終は薬剤師サインオフ＋figcheck/medisearch）。")
    return True


# ---- self-test（既知エラー＋誤検知の両方を回帰）----
SELF_TEST = [
    # 既知エラー(検知されるべき)
    {"id": 901, "text": "この薬は無害で、甲状腺ホルモンを作る唯一の原材料やで。",
     "term_gloss": {"note": "放射性ヨウ素の侵入を99%以上ブロック！"}, "expect": ">=3"},
    {"id": 902, "text": "NISは自動ドアみたいにヨウ素を取り込む。TPOは接着剤みたいにくっつける。", "expect": ">=2"},
    {"id": 903, "text": "体内ヨウ素の80%以上が甲状腺に集中して蓄えられる。", "expect": ">=1"},
    {"id": 904, "text": "うがい薬について。あれは紫色の液体です。", "expect": ">=1"},  # 文跨ぎ色誤り FN-4
    {"id": 905, "text": "NISについて説明します。これはチャネルの一種です。", "expect": ">=1"},  # 文跨ぎ機構 FN-3
    {"id": 906, "text": "遮断率は九割以上、いや99パーセント以上ブロックします。", "expect": ">=1"},  # 表記替え FN-5
    {"id": 907, "text": "妊婦さんでも安心して飲めます。", "expect": ">=1"},  # 特殊集団 FN-2
    {"id": 908, "text": "NISはアピカル膜にあってヨウ素を取り込む。", "expect": ">=1"},  # 局在 FN-9
    {"id": 960, "text": "メトトレキサートを毎日1錠飲んでください。", "expect": ">=1"},  # 週1薬×連日=致死
    {"id": 961, "text": "ビンクリスチンを髄腔内に投与します。", "expect": ">=1"},  # 経路NEVER=致死
    {"id": 962, "text": "ノルバスクは高血圧のお薬です。", "expect": ">=1"},  # 販売名→一般名(薬機法)
    {"id": 963, "text": "MMRワクチンと自閉症には関連があると言われます。", "expect": ">=1"},  # 否定済み定説
    # 誤検知しないべき
    {"id": 950, "text": "NISはチャネルではないので念のため。", "expect": "==0"},
    {"id": 951, "text": "がんは完治しないこともあります。", "expect": "==0"},  # 否定/限定 FP-1
    {"id": 952, "text": "肝臓が毒物を無害化する仕組みです。", "expect": "==0"},  # 無害化 FP-2
    {"id": 953, "text": "服薬の変更や中止は必ず主治医や薬剤師にご相談ください。", "expect": "==0"},  # 免責の必ず
    {"id": 954, "text": "基底膜のNISで血液から吸い込んで、反対側の頂端膜にあるペンドリンからコロイドへ送り出す。", "expect": "==0"},  # 帰属ガード：頂端はペンドリンのもの(NISの誤局在でない) FP
    {"id": 955, "text": "甲状腺のTSH受容体に結合し、NIS発現・ヨウ素取り込みを促進する。", "expect": "==0"},  # 帰属ガード：受容体はTSHのもの(NISは受容体でない) FP
    {"id": 956, "text": "被ばく直前に飲めば、放射性ヨウ素の取り込みを99%以上遮断できる。", "expect": "==0"},  # 直前投与文脈は95〜99%許容(2026-08-14サインオフ・PE-01 exclude)
    {"id": 970, "text": "ACE阻害薬は血圧を上げる薬です。", "expect": ">=1"},  # 高血圧 作用の逆 PE-HT-1
    {"id": 971, "text": "利尿薬はナトリウムの再吸収を促進します。", "expect": ">=1"},  # 高血圧 向き逆 PE-HT-2
    {"id": 972, "text": "ACE阻害薬は血圧を下げ、利尿薬はナトリウムの再吸収を抑制する。", "expect": "==0"},  # 正しい＝誤検知しないこと(両パターンのexclude)
    {"id": 973, "text": "降圧薬の自己判断中止は急激な血圧上昇（リバウンド）を招く。", "expect": "==0"},  # 中止で上昇は正しい＝PE-HT-1の誤検知を回帰で固定(2026-08-15 実話ep05で発見)
    # A-8 画像×台詞の機構不整合（2026-08-15 ep02 id12実発生＝取り込み阻害の絵×有機化の台詞）
    {"id": 980, "image_keyword": "ep02_door_shut_factory_shutdown_3d",
     "text": "ホルモンを組み立てる加工ラインの安全ブレーカーを落として、もうホルモンに加工・固定されなくなる。", "expect": ">=1"},
    {"id": 981, "image_keyword": "ep02_first_barrier_full_seat_analogy_3d",
     "text": "先に安全なヨウ素で席を満席にして放射性ヨウ素の取り込みを防ぐ満席作戦。", "expect": "==0"},  # 満席作戦の絵×取り込みの台詞＝整合(誤検知しない)
]


def self_test():
    tables = load_tables()
    print("=" * 70)
    print("🧪 self-test（既知エラー検知＋誤検知しないこと の両面回帰）")
    print("=" * 70)
    ok = True
    for case in SELF_TEST:
        findings = []
        run_line_checks(case["id"], case, tables, findings)
        # INFO(比喩/方向/未スキャン)はノイズなのでFAIL/WARNのみ数える
        sig = [f for f in findings if f["level"] in ("FAIL", "WARN")]
        n = len(sig)
        exp = case["expect"]
        passed = (n >= int(exp[2:]) if exp.startswith(">=") else n == int(exp[2:]))
        ok = ok and passed
        mark = "✓" if passed else "✗"
        print(f"\n{mark} line {case['id']} (期待{exp}) 実FAIL/WARN{n}件")
        for f in sig:
            print(f"     [{f['level']}] {f['class']} | {f['hit']}")
        if not passed:
            print(f"     🔴 期待外れ")
    print("\n" + ("🟢 self-test PASS（全ケース合格）" if ok else "🔴 self-test FAIL（上の✗を確認）"))
    return ok


def _ep_key(s):
    m = re.search(r"\d+", s or "")
    return f"ep{int(m.group()):02d}" if m else (s or "")


def main():
    ap = argparse.ArgumentParser(description="提出前ゲート（多AI予測統合の先回り検知器）")
    ap.add_argument("--ep", type=str, default=None)
    ap.add_argument("--dir", type=str, default=None)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if self_test() else 1)

    if args.dir:
        ep_dir = args.dir
    elif args.ep:
        key = _ep_key(args.ep)
        cand = [root for root, _, files in os.walk("episodes")
                if "script.json" in files and _ep_key(os.path.basename(root)) == key]
        if len(cand) > 1:
            print(f"⚠ 複数一致: {cand} → 先頭を使用")
        ep_dir = cand[0] if cand else os.path.join("episodes", args.ep)
    else:
        eps = sorted(root for root, _, files in os.walk("episodes") if "script.json" in files)
        allok = True
        for ed in eps:
            if not run_gate(ed, emit_audit=not args.no_audit):
                allok = False
        sys.exit(0 if allok else 1)

    if not os.path.isdir(ep_dir):
        print(f"❌ ディレクトリが無い: {ep_dir}")
        sys.exit(1)
    sys.exit(0 if run_gate(ep_dir, emit_audit=not args.no_audit) else 1)


if __name__ == "__main__":
    main()
