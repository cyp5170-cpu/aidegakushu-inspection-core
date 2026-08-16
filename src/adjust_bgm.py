# -*- coding: utf-8 -*-
"""
adjust_bgm.py ― BGMのテンポを落として落ち着かせる（ffmpeg atempo・ピッチ保持）

「BGMのリズムが速くて落ち着かない」対策。assets/bgm/ の bgm_*.mp3 を atempo で減速。
原本は assets/bgm/_orig/ に一度だけ退避（再実行は原本から作り直すので劣化累積なし）。

使い方:  py src/adjust_bgm.py [tempo]     tempo省略時=0.8（小さいほどゆっくり穏やか）
"""
from __future__ import annotations
import sys, subprocess, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BGMDIR = ROOT / "assets" / "bgm"
ORIG = BGMDIR / "_orig"

def main():
    tempo = float(sys.argv[1]) if len(sys.argv) > 1 else 0.8
    assert 0.5 <= tempo <= 1.0, "tempoは0.5〜1.0（減速）で指定"
    ORIG.mkdir(exist_ok=True)
    targets = sorted(BGMDIR.glob("bgm_*.mp3"))
    ok = 0
    for m in targets:
        bak = ORIG / m.name
        if not bak.exists():
            shutil.copy2(m, bak)
        tmp = m.with_suffix(".tmp.mp3")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(bak),
                            "-filter:a", f"atempo={tempo}", str(tmp)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[NG] {m.name}: {r.stderr.strip()[:120]}"); continue
        try:
            tmp.replace(m); ok += 1
        except PermissionError:
            tmp.unlink(missing_ok=True)
            print(f"[SKIP-locked] {m.name}（YMM4が使用中→閉じて再実行）")
    print(f"[OK] BGM {ok}/{len(targets)} 本を tempo={tempo} で減速（原本={ORIG}）")

if __name__ == "__main__":
    main()
