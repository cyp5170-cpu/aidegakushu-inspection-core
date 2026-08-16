# -*- coding: utf-8 -*-
"""
gen_scene_image.py — Vertex AI (gemini-2.5-flash-image / Nano Banana) でシーン画像を内製する。

[[tool_vertex_gemini_image_gen]] のルート：ADC認証＋$300無料クレジット・APIキー不要・手貼り不要。
Imagenは全モデル404で不可＝gemini-2.5-flash-image を generate_content(response_modalities=[TEXT,IMAGE]) で使う。
1枚≈$0.04。生成後は必ず内容/解剖検品してから配線すること（[[feedback_illustration_qa]]）。

使い方:
  py src/gen_scene_image.py --prompt "英語プロンプト" --out episodes/iodine/ep05/images --name ep05_xxx
  （--name に拡張子は付けない。png で保存する）

要: GOOGLE_CLOUD_PROJECT（既定 nice-ripple-505307-h7・env_bootがレジストリ補完）＋ gcloud auth application-default login
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # 設定は env_boot.resolve() で読取専用取得（os.environ非汚染・過剰伝播#3回避）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import argparse
from pathlib import Path

# 焼き込み文字を防ぐ共通サフィックス（日本語ラベル/字幕は別レイヤーでビルド側が重ねる）。
NO_TEXT = (" IMPORTANT: absolutely no text, no words, no letters, no numbers, no captions, "
           "no labels, no signage text, no watermark anywhere in the image.")


def generate(prompt: str, out_dir: str, name: str, n: int = 1) -> int:
    proj = env_boot.resolve("GOOGLE_CLOUD_PROJECT")
    if not proj:
        print("[NG] GOOGLE_CLOUD_PROJECT 未設定。setx GOOGLE_CLOUD_PROJECT nice-ripple-505307-h7"); return 2
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[NG] google-genai 未導入（pip install google-genai）"); return 2
    loc = env_boot.resolve("GOOGLE_CLOUD_LOCATION") or "us-central1"
    client = genai.Client(vertexai=True, project=proj, location=loc)  # ADC認証
    model = env_boot.resolve("GEMINI_IMAGE_MODEL") or "gemini-2.5-flash-image"
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    saved = 0
    for r in range(n):
        print(f"[gen] {r+1}/{n} model={model} ...", flush=True)
        resp = client.models.generate_content(
            model=model,
            contents=[prompt + NO_TEXT],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        cand = (resp.candidates or [None])[0]
        if not cand or not getattr(cand, "content", None):
            print("    [warn] 応答に content なし"); continue
        for part in cand.content.parts:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                fn = out / (f"{name}.png" if n == 1 else f"{name}_{r}.png")
                fn.write_bytes(inline.data)
                print(f"    画像保存: {fn} ({len(inline.data)} bytes)", flush=True)
                saved += 1
            elif getattr(part, "text", None):
                print(f"    テキスト: {part.text[:120]!r}", flush=True)
    print(f"[DONE] 合計 {saved} 点 → {out}")
    return 0 if saved else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True, help="拡張子なしのベース名（png保存）")
    ap.add_argument("--n", type=int, default=1)
    a = ap.parse_args()
    sys.exit(generate(a.prompt, a.out, a.name, a.n))


if __name__ == "__main__":
    main()
