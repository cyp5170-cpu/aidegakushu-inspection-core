# -*- coding: utf-8 -*-
"""
slow_voice.py ― PNG版音声(NNN_speaker.wav)を『声質そのまま』でゆっくり化

早口対策。ffmpegのatempoフィルタでピッチを変えずに話速だけを落とす。
対象は audio/NNN_speaker.wav（＝A.I.VOICE2琴葉音声のコピー。PNG版build_ymm4が参照）。
口パク版が使う NV版wav＋.lab は .lab のタイム整合が崩れるため触らない。

使い方:  py src/slow_voice.py [tempo]     tempo省略時=0.9（1割ゆっくり／小さいほど遅い）
原本は audio/_orig/ に一度だけ退避（再実行しても原本から作り直すので劣化累積しない）。
"""
from __future__ import annotations
import sys, subprocess, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"
ORIG = AUDIO / "_orig"

def main():
    tempo = float(sys.argv[1]) if len(sys.argv) > 1 else 0.9
    assert 0.5 <= tempo <= 2.0, "tempoは0.5〜2.0で指定（<1=遅く / 1=等速 / >1=速く）"
    ORIG.mkdir(exist_ok=True)
    targets = sorted(AUDIO.glob("[0-9][0-9][0-9]_*.wav"))
    if not targets:
        print("対象wavが見つかりません"); return
    ok = 0
    for w in targets:
        bak = ORIG / w.name
        if not bak.exists():                 # 原本を一度だけ退避
            shutil.copy2(w, bak)
        tmp = w.with_suffix(".slow.wav")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(bak),
               "-filter:a", f"atempo={tempo}", str(tmp)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[NG] {w.name}: {r.stderr.strip()[:120]}"); continue
        tmp.replace(w); ok += 1
    print(f"[OK] PNG版 {ok}/{len(targets)} 本を tempo={tempo} でスロー化（原本={ORIG}）")

    # 口パク版が実再生するNV生wav＋.lab も同倍率でスロー化（.labの時刻は1/tempo倍に再スケール＝口パク整合維持）
    factor = 1.0 / tempo; okn = 0
    nvs = sorted(AUDIO.glob("琴葉 *(NV)*.wav"))
    for w in nvs:
        bakw = ORIG / w.name
        if not bakw.exists():
            shutil.copy2(w, bakw)
        tmp = w.with_suffix(".slow.wav")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(bakw),
                            "-filter:a", f"atempo={tempo}", str(tmp)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[NG] {w.name}: {r.stderr.strip()[:100]}"); continue
        try:
            tmp.replace(w)
        except PermissionError:                 # YMM4等がwavを使用中→スキップ（YMM4を閉じて再実行で反映）
            tmp.unlink(missing_ok=True)
            print(f"[SKIP-locked] {w.name}（YMM4が使用中）"); continue
        lab = w.with_suffix(".lab"); bakl = ORIG / lab.name
        if lab.exists():
            if not bakl.exists():
                shutil.copy2(lab, bakl)
            outl = []
            for line in bakl.read_text(encoding="utf-8").splitlines():
                p = line.split()
                if len(p) >= 3:
                    outl.append(f"{int(round(int(p[0])*factor))} {int(round(int(p[1])*factor))} {p[2]}")
                elif line.strip():
                    outl.append(line)
            lab.write_text("\n".join(outl) + "\n", encoding="utf-8")
        okn += 1
    print(f"[OK] 口パク版 NV {okn}/{len(nvs)} 本＋.lab を tempo={tempo} でスロー化")

if __name__ == "__main__":
    main()
