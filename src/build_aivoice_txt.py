# -*- coding: utf-8 -*-
"""
build_aivoice_txt.py ― A.I.VOICE2 公式テキスト一括読み込みファイルの自動生成
A.I.VOICE2の「ファイル」->「テキストファイルを読み込む」で100%エラーなく即座に読み込める形式を出力
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_JSON = ROOT / "script" / "script.json"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("Generating A.I.VOICE2 text import files...")
    with open(SCRIPT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    lines = data.get("lines", [])
    
    # 1. 話者名付きテキストファイル (話者: セリフ)
    out_txt_labeled = OUTPUT_DIR / "AI_History_Ep1_aivoice_import.txt"
    # 2. TSV形式 (話者 \t セリフ)
    out_tsv = OUTPUT_DIR / "AI_History_Ep1_aivoice_import.tsv"
    
    with open(out_txt_labeled, "w", encoding="utf-8") as f_txt, \
         open(out_tsv, "w", encoding="utf-8") as f_tsv:
        
        f_tsv.write("speaker\ttext\temotion\n")
        
        for line in lines:
            speaker = line.get("speaker", "akane")
            text = line["text"]
            emotion = line.get("emotion", "平静")
            
            spk_name = "琴葉 茜" if speaker == "akane" else "琴葉 葵"
            
            # 書き込み
            f_txt.write(f"{spk_name}＞{text}\n")
            f_tsv.write(f"{spk_name}\t{text}\t{emotion}\n")
            
    print(f"[OK] Generated A.I.VOICE2 import file: {out_txt_labeled}")
    print(f"[OK] Generated TSV import file: {out_tsv}")

if __name__ == "__main__":
    main()
