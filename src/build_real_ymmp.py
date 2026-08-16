# -*- coding: utf-8 -*-
"""
build_real_ymmp.py ― パスの文字化け・絶対パス崩れを完全に排除した決定版ビルダー
YMM4がファイル存在確認で弾かれずに407秒全編を確実に読み込むv3を作成
"""
import os
import json
import wave
from pathlib import Path

# パスはユーザーのホーム基準で構築（環境変数で上書き可・ユーザー名をハードコードしない）
_DESKTOP = Path(os.environ.get("AIGAKU_DESKTOP", Path.home() / "OneDrive" / "デスクトップ"))
ROOT = Path(os.environ.get("AIHIST_ROOT", _DESKTOP / "projects" / "AIの歴史_Gemini版"))
SCRIPT_JSON = ROOT / "script" / "script.json"
AUDIO_DIR = ROOT / "audio"
OUTPUT_DIR = ROOT / "output"
FRAMES_DIR = OUTPUT_DIR / "frames"

REAL_YMMP_TEMPLATE = os.environ.get("YMMP_TEMPLATE", str(_DESKTOP / "projects" / "琴葉茜葵_設定学習データ" / "序章第1話_SD_v5.ymmp"))

def get_wav_duration_frames(wav_path: Path, fps: int = 60) -> int:
    if not wav_path.exists():
        return int(3.0 * fps)
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            duration_sec = frames / float(rate)
            return max(int((duration_sec + 0.2) * fps), int(1.2 * fps))
    except Exception:
        return int(3.0 * fps)

def main():
    print("Fixing paths for YMM4 v3 project...")
    
    if not os.path.exists(REAL_YMMP_TEMPLATE):
        raise FileNotFoundError(f"Template {REAL_YMMP_TEMPLATE} not found.")

    with open(REAL_YMMP_TEMPLATE, "r", encoding="utf-8-sig") as f:
        template_data = json.load(f)

    with open(SCRIPT_JSON, "r", encoding="utf-8") as f:
        script_data = json.load(f)

    lines = script_data.get("lines", [])
    fps = 60
    
    new_items = []
    current_frame = 0
    
    for line in lines:
        line_id = line["id"]
        speaker = line["speaker"]
        
        audio_path = AUDIO_DIR / f"{line_id:03d}_{speaker}.wav"
        frame_img_path = FRAMES_DIR / f"frame_{line_id:03d}.png"
        
        # 音声の長さからフレーム数を計算
        dur_frames = get_wav_duration_frames(audio_path, fps)
        
        # ★ パスを厳密なWindows絶対パス（文字列）にする！
        abs_frame_path = str(frame_img_path.resolve())
        abs_audio_path = str(audio_path.resolve())
        
        # 1. 映像トラック (Layer 1)
        if os.path.exists(abs_frame_path):
            image_item = {
                "$type": "YukkuriMovieMaker.Project.Items.ImageItem, YukkuriMovieMaker",
                "FilePath": abs_frame_path,
                "Start": current_frame,
                "Length": dur_frames,
                "Layer": 1,
                "X": 0,
                "Y": 0,
                "Scale": 100,
                "Opacity": 100
            }
            new_items.append(image_item)
        else:
            print(f"[WARNING] Frame image missing: {abs_frame_path}")
            
        # 2. 音声トラック (Layer 0)
        if os.path.exists(abs_audio_path):
            voice_item = {
                "$type": "YukkuriMovieMaker.Project.Items.AudioItem, YukkuriMovieMaker",
                "FilePath": abs_audio_path,
                "Start": current_frame,
                "Length": dur_frames,
                "Layer": 0,
                "Volume": 100
            }
            new_items.append(voice_item)
        else:
            print(f"[WARNING] Audio missing: {abs_audio_path}")
            
        current_frame += dur_frames

    print(f"Total v3 timeline length: {current_frame} frames ({current_frame / fps:.1f} seconds)")

    output_ymmp_v3 = OUTPUT_DIR / "AI_History_Ep1_v3.ymmp"
    template_data["FilePath"] = str(output_ymmp_v3.resolve())
    
    if "Timelines" in template_data and len(template_data["Timelines"]) > 0:
        template_data["Timelines"][0]["Items"] = new_items
        template_data["Timelines"][0]["CurrentFrame"] = 0
    else:
        template_data["Timelines"] = [{
            "VideoInfo": {"FPS": fps, "Hz": 44100, "Width": 1920, "Height": 1080},
            "CurrentFrame": 0,
            "Items": new_items
        }]

    # utf-8 (BOMなし) で書き出し
    with open(output_ymmp_v3, "w", encoding="utf-8") as f:
        json.dump(template_data, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] Created CLEAN v3 YMM4 project file: {output_ymmp_v3}")

if __name__ == "__main__":
    main()
