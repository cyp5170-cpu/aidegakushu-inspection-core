#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
medical_adversarial_check.py
医療・病態・薬学・一般健康解説動画 台本の敵対的安全性・コンプライアンス静的検証ツール

対象カテゴリ:
- pharma: 薬学・薬理マスター（用量・禁忌・副作用・相互作用・シックデイ）
- pathology: 病態・病理マスター（メカニズム・診断基準・検査値・短絡的自己診断防止）
- general: 一般医学・ヘルスケア（生活習慣・俗説排除・フードファディズム防止）

検証項目:
1. 禁忌・誇大広告・危険断定ワードの検出（薬機法・医療法・YouTube医療ポリシー違反リスク）
2. 医療免責・受診勧奨アナウンスの配置チェック
3. 臨床安全タグ（clinical_caution / guideline_ref）の付与状況
4. 未登録の英字略語・難読用語の抽出（reading_dict.jsonとの照合）
"""

import os
import sys
import re
import json
import glob
import argparse

# Windowsコンソール文字化け・絵文字対策
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 警告・禁止ワードリスト（敵対的フィルター）
FORBIDDEN_PATTERNS = [
    (r"絶対(に)?治る", "「絶対に治る」等の断定的な治療効果の保証（薬機法・医療法違反）"),
    (r"必ず効く", "「必ず効く」等の効果確約表現（薬機法違反）"),
    (r"(薬を)?(勝手に)?やめて(も)?いい", "自己判断による服薬中断の助長（危険・患者安全性違反）"),
    (r"副作用(は|が)全くない", "副作用ゼロの断定（虚偽・誇大表現）"),
    (r"飲むだけで痩せる", "未承認の痩身目的等の不適切使用助長（適応外プロモーション禁止）"),
    (r"誰でも飲める", "禁忌・慎重投与を無視した全対象化表現（危険）"),
    (r"これだけ食べれば(安心|大丈夫)", "フードファディズム・極端な偏食助長（一般健康ガイドライン違反）"),
    (r"医者は必要ない", "医療機関受診の否定（重大な医療ポリシー違反）")
]

# 免責・受診勧奨の必須キーワード
DISCLAIMER_KEYWORDS = [
    "相談", "主治医", "医師", "薬剤師", "自己判断", "学習", "医療機関"
]

CATEGORY_LABELS = {
    "pharma": "💊 薬学・薬理マスター",
    "pathology": "🧬 病態・病理マスター",
    "general": "🩺 一般医学・ヘルスケア"
}

def check_script(ep_dir):
    script_path = os.path.join(ep_dir, "script.json")
    if not os.path.exists(script_path):
        print(f"❌ エラー: 台本ファイルが見つかりません: {script_path}")
        return False

    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    category = meta.get("category", "pharma")
    cat_label = meta.get("category_label", CATEGORY_LABELS.get(category, category))
    title = meta.get("title", "無題")

    lines = data.get("lines", [])
    if not lines:
        print("❌ エラー: lines が空です。")
        return False

    print("=" * 65)
    print(f"🛡️ 医療・病態・薬学 敵対的安全性チェック: {ep_dir}")
    print(f"   カテゴリ: {cat_label}")
    print(f"   タイトル: {title}")
    print(f"   総行数: {len(lines)} 行")
    print("=" * 65)

    has_errors = False
    has_warnings = False

    # 1. 禁忌・危険ワードの検査
    print("\n🔍 [1/4] 危険ワード・誇大表現・俗説チェック...")
    forbidden_hits = []
    for line in lines:
        lid = line.get("id")
        text = line.get("text", "")
        for pat, reason in FORBIDDEN_PATTERNS:
            if re.search(pat, text):
                forbidden_hits.append((lid, text, reason))

    if forbidden_hits:
        print("❌ 以下の行で重大なリスク表現が検出されました（要修正）:")
        for lid, text, reason in forbidden_hits:
            print(f"   - Line {lid}: 「{text}」")
            print(f"     ➔ 理由: {reason}")
        has_errors = True
    else:
        print("  ✅ 危険ワード・誇大表現は検出されませんでした。")

    # 2. 免責・受診勧奨アナウンスの検査（セリフ分離免責・テロップ・clinical_caution対応）
    print("\n⚖️ [2/4] 医療免責・受診勧奨アナウンスチェック...")
    all_texts = []
    for l in lines:
        all_texts.append(l.get("text", ""))
        if l.get("disclaimer_text"):
            all_texts.append(l.get("disclaimer_text"))
        if l.get("clinical_caution") and isinstance(l.get("clinical_caution"), dict):
            all_texts.append(l.get("clinical_caution").get("text", ""))
            all_texts.append(l.get("clinical_caution").get("title", ""))
    full_search_text = " ".join(all_texts)
    found_disclaimers = [kw for kw in DISCLAIMER_KEYWORDS if kw in full_search_text]
    
    if len(found_disclaimers) >= 2:
        print(f"  ✅ 医療免責・受診勧奨キーワードを確認しました ({', '.join(found_disclaimers)})")
    else:
        print("  ⚠️ 警告: 医療免責や主治医・薬剤師・医療機関への相談を促すアナウンスが不足している可能性があります。")
        has_warnings = True

    # 3. 臨床安全タグの付与状況
    print("\n⚠️ [3/4] 安全タグ (clinical_caution / guideline_ref) チェック...")
    caution_count = sum(1 for l in lines if l.get("clinical_caution"))
    guideline_count = sum(1 for l in lines if l.get("guideline_ref"))
    gloss_count = sum(1 for l in lines if l.get("term_gloss"))

    print(f"   - 臨床安全・注意警告 (clinical_caution): {caution_count} 箇所")
    print(f"   - ガイドライン・文献参照 (guideline_ref): {guideline_count} 箇所")
    print(f"   - 用語解説ノート (term_gloss): {gloss_count} 箇所")

    if category == "pharma" and caution_count == 0:
        print("  ⚠️ 警告 (pharma): clinical_caution（副作用・禁忌・落とし穴）のタグが1件もありません。")
        has_warnings = True

    # 4. 英字略語・難読語の辞書照合
    print("\n📖 [4/4] 専門略語・難読用語の読み辞書照合...")
    reading_dict_path = os.path.join(os.path.dirname(__file__), "reading_dict.json")
    known_surfaces = set()
    if os.path.exists(reading_dict_path):
        with open(reading_dict_path, "r", encoding="utf-8") as f:
            rdict = json.load(f)
            for item in rdict.get("dict", []):
                known_surfaces.add(item.get("surface"))
            for item in rdict.get("tts_replace", []):
                known_surfaces.add(item.get("find"))

    abbr_pattern = re.compile(r"[A-Z0-9]{2,}")
    unregistered_abbrs = set()

    for line in lines:
        text = line.get("text", "")
        matches = abbr_pattern.findall(text)
        for m in matches:
            if m not in known_surfaces and not m.isdigit():
                unregistered_abbrs.add(m)

    if unregistered_abbrs:
        print(f"  ⚠️ 未登録の可能性のある英字略語が見つかりました（reading_dict.jsonへの登録を推奨）:")
        for abbr in sorted(unregistered_abbrs):
            print(f"     - {abbr}")
        has_warnings = True
    else:
        print("  ✅ 検出された英字略語はすべて辞書に登録済みです。")

    print("\n" + "=" * 65)
    if has_errors:
        print("🔴 判定: 不合格 (FAIL) - 危険ワードを修正してください。")
        return False
    elif has_warnings:
        print("🟡 判定: 警告あり (PASS with WARNING) - 必要に応じて調整してください。")
        return True
    else:
        print(f"🟢 判定: 完全合格 (PERFECT PASS) - 【{cat_label}】の敵対的安全基準をすべてクリアしました！")
        return True

def main():
    parser = argparse.ArgumentParser(description="医療・病態・薬学台本の敵対的安全性・コンプライアンス静的チェッカー")
    parser.add_argument("--ep", type=str, default=None, help="話数番号 (例: 01, ep01, iodine_ep01, hypertension_ep01)")
    parser.add_argument("--dir", type=str, default=None, help="エピソードディレクトリパス")
    args = parser.parse_args()

    if args.dir:
        ep_dir = args.dir
    elif args.ep:
        if os.path.exists(os.path.join("episodes", args.ep)):
            ep_dir = os.path.join("episodes", args.ep)
        else:
            ep_str = args.ep if args.ep.startswith("ep") else f"ep{int(args.ep):02d}"
            ep_dir = os.path.join("episodes", ep_str)
    else:
        # 全エピソード一括スキャン（episodes/*/* 構造に対応）
        ep_dirs = []
        for root, dirs, files in os.walk("episodes"):
            if "script.json" in files:
                ep_dirs.append(root)
        ep_dirs.sort()
        
        all_ok = True
        for ed in ep_dirs:
            ok = check_script(ed)
            if not ok:
                all_ok = False
        sys.exit(0 if all_ok else 1)

    if not os.path.isdir(ep_dir):
        print(f"エラー: ディレクトリが見つかりません: {ep_dir}")
        sys.exit(1)

    ok = check_script(ep_dir)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()

