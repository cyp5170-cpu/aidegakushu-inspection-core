# -*- coding: utf-8 -*-
"""
cinematic_lint.py ― 「シネマ調画像を使わない」方針([[feedback_no_cinematic_learning_images]])のコード化。

方針＝資料画像はシネマ調(暗い/劇的/写実的グロー/映画的ライティング/SF質感/煙・火花)や
焼き込み文字を避け、明快・正確な学習用図に。「シネマ調か」は曖昧＝決定論不可 → Vertex視覚でAI判定(L2)。

★record+stale化＝画像の"内容ハッシュ"で判定を記録(cinematic_manifest.json)。
  変更していない画像は再判定しない(安い)＝ship.py/preshipは記録を読むだけ(Vertex不要)。
  画像が変われば内容ハッシュが変わり自動でUNKNOWN(要再判定)＝取りこぼしなし。
※AI判定は不完全＝多層＋人のバックストップは残す。判定は"下限"であって"正しさ"の保証ではない。

使い方:
  py src/cinematic_lint.py --dir <ep> --record   # 未判定/変更のみVertex判定して記録(429はリトライ)
  py src/cinematic_lint.py --dir <ep>            # 記録から状態表示(Vertex不要・速い)
  py src/cinematic_lint.py --image <path>        # 1枚だけ即判定(記録しない)
要: GOOGLE_CLOUD_PROJECT + gcloud auth application-default login。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # 設定は env_boot.resolve() で読取専用取得（os.environ非汚染・過剰伝播#3回避）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import time
import argparse
import datetime
from pathlib import Path
import verify_core as vc

SYSTEM = (
    "あなたは学習動画の画像検品官です。方針：資料画像は『シネマ調』(暗い/劇的/写実的な光沢やグロー/"
    "映画的ライティング/SF的質感/煙・火花・ドラマ演出)や『焼き込み文字』(画像内の英字/数字/ラベル)を避け、"
    "明快で正確な学習用図(フラット/クリーン/図解的・やわらか3Dの説明図も可)にすべきです。"
    "与えられた画像を判定し、必ず指定JSONだけで答えてください。"
)
PROMPT = (
    "この画像について判定: cinematic(シネマ調で学習に不向きか true/false), "
    "burned_text(画像内に焼き込み文字があるか true/false), "
    "learning_appropriate(明快・正確な学習用図として適切か true/false), "
    "reason(20〜60字の理由・日本語). JSONのみ。"
)
VERIFIER = "cinematic-lint-vertex-v1"


def _mime(p: Path):
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(p.suffix.lower(), "image/png")


def classify(path: Path, retries=4):
    proj = env_boot.resolve("GOOGLE_CLOUD_PROJECT")
    if not proj:
        return {"error": "GOOGLE_CLOUD_PROJECT未設定"}
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {"error": "google-genai未導入"}
    loc = env_boot.resolve("GOOGLE_CLOUD_LOCATION") or "us-central1"
    client = genai.Client(vertexai=True, project=proj, location=loc)
    model = env_boot.resolve("GEMINI_MODEL") or "gemini-2.5-flash"
    data = path.read_bytes()
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=data, mime_type=_mime(path)), PROMPT],
                config=types.GenerateContentConfig(system_instruction=SYSTEM, response_mime_type="application/json"),
            )
            return json.loads(resp.text or "{}")
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                time.sleep(8 * (attempt + 1))   # レート制限＝指数バックオフ
                continue
            return {"error": msg}
    return {"error": "429リトライ上限"}


def _violation(v):
    return bool(v.get("cinematic") or v.get("burned_text") or (v.get("learning_appropriate") is False))


def _raw_targets(ep_dir: Path):
    """判定対象＝表示される"生画像"(images/)。合成図(_fx)は学習用に作った図＝対象外。"""
    import verify_assets as va
    rows, _m, _mode, _cd = va._rows(ep_dir)
    if rows is None:
        return None
    return [r for r in rows if "images" in str(r["img"]).replace("\\", "/") and "_fx" not in str(r["img"])]


def _man(ep_dir: Path):
    return vc.Manifest(str(ep_dir / "cinematic_manifest.json"))


def record_dir(ep_dir: Path, throttle=3.0):
    """未判定/変更された生画像だけVertex判定して記録(内容ハッシュkey)。429はリトライ＋間隔。"""
    targets = _raw_targets(ep_dir)
    if targets is None:
        return 2
    man = _man(ep_dir)
    today = datetime.date.today().isoformat()
    n_new = n_skip = n_err = 0
    print(f"🎬 cinematic record: {ep_dir.name}  対象生画像{len(targets)}枚")
    for r in targets:
        img = r["img"]
        ch = "sha:" + vc.sha256_hex(img.read_bytes())         # 内容ハッシュ＝画像が変われば変わる
        aid = f"cine:{img.name}"
        if man.status(aid, ch) in (vc.PASS, vc.BLOCK):        # 現内容で判定済み→再判定しない(安い)
            n_skip += 1
            continue
        v = classify(img)
        if v.get("error"):
            print(f"  ⚠ {img.name[:34]} 判定不可: {v['error']}"); n_err += 1
            time.sleep(throttle); continue
        verdict = vc.BLOCK if _violation(v) else vc.PASS
        flags = [k for k in ("cinematic", "burned_text") if v.get(k)] + ([] if v.get("learning_appropriate", True) else ["not_learning"])
        man.record(aid, ch, verdict, verifier_version=VERIFIER, verified_at=today,
                   note=("/".join(flags) + " : " if flags else "") + str(v.get("reason", "")))
        print(f"  {'🔴' if verdict==vc.BLOCK else '🟢'} {img.name[:34]} {v.get('reason','')[:40]}")
        n_new += 1
        time.sleep(throttle)
    man.save()
    print(f"[OK] 新規判定{n_new} / 記録済skip{n_skip} / 判定不可{n_err} → cinematic_manifest.json")
    return 0


def status_dir(ep_dir: Path):
    """記録から状態を返す(Vertex不要)。(img, status)  status=PASS/BLOCK/UNKNOWN(未判定or変更)。"""
    targets = _raw_targets(ep_dir)
    if targets is None:
        return None
    man = _man(ep_dir)
    out = []
    for r in targets:
        img = r["img"]
        ch = "sha:" + vc.sha256_hex(img.read_bytes())
        out.append((r["line"].get("id"), img, man.status(f"cine:{img.name}", ch), man.get(f"cine:{img.name}")))
    return out


def cmd_report(ep_dir: Path):
    st = status_dir(ep_dir)
    if st is None:
        print("❌ script.json無し"); return 2
    print("=" * 70)
    print(f"🎬 シネマ調 検証状態（記録ベース・機械は下限保証）: {ep_dir.name}  生画像{len(st)}枚")
    print("=" * 70)
    nb = nu = 0
    for lid, img, s, rec in st:
        if s == vc.BLOCK:
            nb += 1; mark = "🔴シネマ調違反"
        elif s == vc.PASS:
            mark = "🟢OK"
        else:
            nu += 1; mark = "⬜未判定(--recordを)"
        print(f"  {mark} 行{lid} {img.name[:34]} {((rec or {}).get('note','')[:38]) if rec else ''}")
    print("-" * 70)
    print(f"  違反 {nb} / 未判定 {nu} / 全{len(st)}")
    return 1 if (nb or nu) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=str, default=None)
    ap.add_argument("--dir", type=str, default=None)
    ap.add_argument("--record", action="store_true", help="未判定/変更のみVertex判定して記録")
    a = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    if a.image:
        v = classify(Path(a.image))
        print(json.dumps(v, ensure_ascii=False, indent=2))
        sys.exit(1 if (not v.get("error") and _violation(v)) else 0)
    if a.dir:
        d = Path(a.dir) if os.path.isabs(a.dir) else root / a.dir
        sys.exit(record_dir(d) if a.record else cmd_report(d))
    print("--image か --dir を指定"); sys.exit(2)


if __name__ == "__main__":
    main()
