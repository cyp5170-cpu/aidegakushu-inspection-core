# -*- coding: utf-8 -*-
"""
init_project.py ― 「AIの歴史」動画制作プロジェクトのスキャフォールド生成

体制: Gemini=企画/監督/脚本(Antigravity環境) / Claude Code=技術スタッフ/実装
方針: 既存ファイルは上書きしない（無ければ雛形を生成）＝再実行しても中身を壊さない。

生成物:
  - ディレクトリ構造 (assets/characters/{akane,aoi}, assets/images, assets/bgm,
    audio, script, output, src)
  - script/script.json         : 無ければ空配列 [] で初期化
  - src/fetch_images.py        : パスプレースホルダーのみ
  - src/generate_voice.py      : パスプレースホルダーのみ
  - src/build_ymm4.py          : パスプレースホルダーのみ
  - .gitignore                 : audio/ output/ assets/images/ を除外
"""
from __future__ import annotations
from pathlib import Path

# プロジェクトルート = このファイル(src/)の1つ上
ROOT = Path(__file__).resolve().parent.parent

DIRS = [
    "assets/characters/akane",
    "assets/characters/aoi",
    "assets/images",
    "assets/bgm",
    "audio",
    "script",
    "output",
    "src",
]

# --- 雛形テキスト ---------------------------------------------------------

PLACEHOLDER_HEADER = '''# -*- coding: utf-8 -*-
"""
{title}
（雛形＝パスプレースホルダーのみ。実装は後工程で追加する）
体制: Gemini=脚本/監督 / Claude Code=実装
"""
from pathlib import Path

# プロジェクト共通パス（プレースホルダー）
ROOT = Path(__file__).resolve().parent.parent
SCRIPT_JSON = ROOT / "script" / "script.json"
IMAGES_DIR = ROOT / "assets" / "images"
AUDIO_DIR = ROOT / "audio"
BGM_DIR = ROOT / "assets" / "bgm"
CHAR_DIR = ROOT / "assets" / "characters"
OUTPUT_DIR = ROOT / "output"

{extra}

def main() -> None:
    # TODO: 実装
    raise NotImplementedError("{title} は未実装（雛形）")


if __name__ == "__main__":
    main()
'''

PLACEHOLDERS = {
    "src/fetch_images.py": PLACEHOLDER_HEADER.format(
        title="fetch_images.py ― 解説画像の自動収集（Wikimedia Commons 等）",
        extra='# 出力先: IMAGES_DIR / "<image_keyword>.jpg"',
    ),
    "src/generate_voice.py": PLACEHOLDER_HEADER.format(
        title="generate_voice.py ― 音声自動合成（A.I.VOICE2 連携／既存技術を流用）",
        extra='# 出力先: AUDIO_DIR / "<連番>_<speaker>.wav"',
    ),
    "src/build_ymm4.py": PLACEHOLDER_HEADER.format(
        title="build_ymm4.py ― YMM4プロジェクト(.ymmp)自動生成（既存ビルド技術を流用）",
        extra='# 出力先: OUTPUT_DIR / "AI_History_Ep1.ymmp"',
    ),
}

GITIGNORE = """# 生成物・大容量素材はGit管理外
audio/
output/
assets/images/

# Python
__pycache__/
*.pyc
"""


def ensure_dir(rel: str) -> None:
    (ROOT / rel).mkdir(parents=True, exist_ok=True)
    print(f"[dir ] {rel}")


def write_if_absent(rel: str, content: str) -> None:
    p = ROOT / rel
    if p.exists():
        print(f"[skip] {rel}（既存＝温存）")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"[new ] {rel}")


def main() -> None:
    print(f"ROOT = {ROOT}")
    for d in DIRS:
        ensure_dir(d)
    write_if_absent("script/script.json", "[]\n")
    for rel, content in PLACEHOLDERS.items():
        write_if_absent(rel, content)
    write_if_absent(".gitignore", GITIGNORE)
    print("done.")


if __name__ == "__main__":
    main()
