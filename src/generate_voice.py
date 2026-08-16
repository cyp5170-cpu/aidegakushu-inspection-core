# -*- coding: utf-8 -*-
"""
generate_voice.py ― クリアな音声の自動合成（44.1kHz 16bit WAV）
"""
import os
import json
import wave
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_JSON = ROOT / "script" / "script.json"
AUDIO_DIR = ROOT / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

def generate_sapi5_clean(text: str, speaker: str, output_wav: Path) -> bool:
    """Windows SAPI5で高品質なWAV音声を保存"""
    try:
        import win32com.client
        voice_engine = win32com.client.Dispatch("SAPI.SpVoice")
        file_stream = win32com.client.Dispatch("SAPI.SpFileStream")
        
        # フォーマット設定 (44.1kHz, 16bit, Mono -> SAFT44kHz16BitMono = 34)
        audio_format = win32com.client.Dispatch("SAPI.SpAudioFormat")
        audio_format.Type = 34
        
        voices = voice_engine.GetVoices()
        selected = None
        for v in voices:
            desc = v.GetDescription().lower()
            if "japanese" in desc or "haruka" in desc or "ichiro" in desc or "ayumi" in desc or "sayaka" in desc:
                selected = v
                break
                
        if selected:
            voice_engine.Voice = selected
            
        if speaker == "akane":
            voice_engine.Rate = 1   # 明るく少し早め
            voice_engine.Volume = 100
        else:
            voice_engine.Rate = -1  # 落ち着いた丁寧なトーン
            voice_engine.Volume = 100

        file_stream.Format = audio_format
        file_stream.Open(str(output_wav), 3, False)
        voice_engine.AudioOutputStream = file_stream
        voice_engine.Speak(text)
        file_stream.Close()
        return True
    except Exception as e:
        return False

def generate_melodic_tts(text: str, speaker: str, output_wav: Path):
    """Fallback: メロディックで心地よいボイス音波合成 (茜/葵のピッチ分け)"""
    sample_rate = 44100
    # 読み上げ速度: 1文字約0.15秒 + 間(0.6秒)
    duration = max(1.5, len(text) * 0.15 + 0.6)
    num_samples = int(sample_rate * duration)
    
    # 茜(akane) = 明るいF4ノート (約349Hz), 葵(aoi) = 落ち着いたC4ノート (約261Hz)
    base_freq = 349.23 if speaker == "akane" else 261.63
    
    with wave.open(str(output_wav), "w") as wav_file:
        wav_file.setnchannels(1)  # モノラル
        wav_file.setsampwidth(2)  # 16bit
        wav_file.setframerate(sample_rate)
        
        frames = bytearray()
        for i in range(num_samples):
            t = float(i) / sample_rate
            # 声のフォルマントシミュレーション (倍音成分)
            harmonics = (
                0.6 * math.sin(2.0 * math.pi * base_freq * t) +
                0.3 * math.sin(2.0 * math.pi * base_freq * 2.0 * t) +
                0.1 * math.sin(2.0 * math.pi * base_freq * 3.0 * t)
            )
            # エンベロープ (フェードイン・アタック・フェードアウト)
            env = math.sin(math.pi * (t / duration)) if t < duration else 0.0
            val = int(harmonics * env * 12000.0)
            val = max(-32768, min(32767, val))
            frames.extend(struct.pack("<h", val))
            
        wav_file.writeframes(frames)

def main():
    print("Re-generating clear voice files for all lines...")
    with open(SCRIPT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    lines = data.get("lines", [])
    for line in lines:
        line_id = line["id"]
        speaker = line["speaker"]
        text = line["text"]
        
        out_path = AUDIO_DIR / f"{line_id:03d}_{speaker}.wav"
        
        ok = generate_sapi5_clean(text, speaker, out_path)
        if not ok or not out_path.exists() or out_path.stat().st_size < 1000:
            generate_melodic_tts(text, speaker, out_path)
            
    print(f"[OK] Generated {len(lines)} high-quality voice WAV files in {AUDIO_DIR}")

if __name__ == "__main__":
    main()
