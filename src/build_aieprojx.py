# -*- coding: utf-8 -*-
"""
build_aieprojx.py ― A.I.VOICE2 用プロジェクト(.aieprojx)感情自動注入生成
script/script.json から全セリフ・感情・話者を読み込み、A.I.VOICE2でそのまま開いて一括音声書き出しできる .aieprojx ファイルを出力
"""
import os
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_JSON = ROOT / "script" / "script.json"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# A.I.VOICE2 感情スライダー設定テーブル
EMOTION_RULE = {
    "akane": { # 琴葉 茜
        "平静":   {"speed": 1.10, "emph": 1.10, "style": None, "val": 0.0},
        "喜び":   {"speed": 1.12, "emph": 1.18, "style": "J",  "val": 0.55},
        "驚き":   {"speed": 1.16, "emph": 1.24, "style": "J",  "val": 0.55},
        "悲しみ": {"speed": 1.05, "emph": 1.00, "style": "S",  "val": 0.55},
        "怒り":   {"speed": 1.15, "emph": 1.18, "style": "A",  "val": 0.50},
    },
    "aoi": {   # 琴葉 葵
        "平静":   {"speed": 1.12, "emph": 1.20, "style": None, "val": 0.0},
        "喜び":   {"speed": 1.14, "emph": 1.18, "style": "J",  "val": 0.30},
        "驚き":   {"speed": 1.17, "emph": 1.22, "style": "J",  "val": 0.32},
        "悲しみ": {"speed": 1.12, "emph": 1.00, "style": "S",  "val": 0.30},
        "怒り":   {"speed": 1.15, "emph": 1.18, "style": "A",  "val": 0.28},
    }
}

def generate_aieprojx(lines: list, out_file: Path):
    """A.I.VOICE2 用プロジェクトデータ生成"""
    talk_items = []
    
    for line in lines:
        line_id = line["id"]
        speaker = line.get("speaker", "akane")
        text = line["text"]
        emotion = line.get("emotion", "平静")
        
        target_spk = "akane" if speaker == "akane" else "aoi"
        chara_name = "琴葉 茜(NV)" if target_spk == "akane" else "琴葉 葵(NV)"
        
        spk_rules = EMOTION_RULE.get(target_spk, EMOTION_RULE["akane"])
        rule = spk_rules.get(emotion, spk_rules["平静"])
        
        styles = {"J": 0.0, "A": 0.0, "S": 0.0, "C": 0.0}
        if rule["style"] and rule["style"] in styles:
            styles[rule["style"]] = rule["val"]
            
        item = {
            "character": chara_name,
            "text": text,
            "filename": f"{line_id:03d}_{speaker}.wav",
            "tuning": {
                "slider": {
                    "speed": rule["speed"],
                    "emph": rule["emph"],
                    "pitch": 1.0,
                    "volume": 1.0,
                    "styles": {
                        "J": {"value": styles["J"]},
                        "A": {"value": styles["A"]},
                        "S": {"value": styles["S"]},
                        "C": {"value": 0.0}
                    }
                }
            }
        }
        talk_items.append(item)
        
    proj_data = {
        "version": "2.0.0",
        "title": "AIの歴史 第1話 本編ボイス",
        "items": talk_items
    }
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(proj_data, f, ensure_ascii=False, indent=2)

def main():
    print("Generating A.I.VOICE2 project (.aieprojx) with emotion injection...")
    with open(SCRIPT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    lines = data.get("lines", [])
    out_aie = OUTPUT_DIR / "AI_History_Ep1.aieprojx"
    generate_aieprojx(lines, out_aie)
    print(f"[OK] Generated A.I.VOICE2 emotion-injected project file: {out_aie}")

if __name__ == "__main__":
    main()
