# -*- coding: utf-8 -*-
"""
fetch_images.py ― 解説画像の管理（存在チェック / 不足リスト / リサイズ補助）

【役割更新 2026-08-06】
解説画像は **Gemini(Antigravity)/ユーザーがAI生成して assets/images/ に配置**する。
本スクリプト(Claude担当)の主務は「取得」ではなく次の補助：
  - check   : script.json が要求する画像スロットが揃っているか照合し、不足を _wanted.json に出力（既定）
  - resize  : 配置済み画像を黒板カード用に長辺リサイズして _normalized/ に出力（要 Pillow）
  - commons : （フォールバック）Wikimedia Commonsから参照画像を取得

画像とセリフの対応規約（Gemini/ユーザーはこの名前で置く）:
  1) line に "image_file" があればそれを最優先
  2) 無ければ  img_<id>.<png|jpg|jpeg|webp>
  3) それも無ければ  <image_keywordをサニタイズ>.<拡張子>
"""
from __future__ import annotations
import json
import os
import re
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_JSON = ROOT / "script" / "script.json"
IMAGES_DIR = ROOT / "assets" / "images"
WANTED = IMAGES_DIR / "_wanted.json"
MANIFEST = IMAGES_DIR / "_fetch_manifest.json"

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def sanitize(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_") or "image"


def load_lines() -> list[dict]:
    data = json.loads(SCRIPT_JSON.read_text(encoding="utf-8"))
    return data["lines"] if isinstance(data, dict) else data


def find_existing(candidates: list[str]) -> str | None:
    """basename候補群について、拡張子違いを含め assets/images 直下から探す。"""
    for base in candidates:
        # 完全一致（拡張子付き）
        p = IMAGES_DIR / base
        if p.suffix and p.exists():
            return p.name
        # 拡張子補完
        stem = Path(base).stem
        for ext in IMG_EXTS:
            q = IMAGES_DIR / f"{stem}{ext}"
            if q.exists():
                return q.name
    return None


def image_slots() -> list[dict]:
    """image_keyword を持つ行を画像スロットとして列挙し、充足状況を付与。"""
    slots = []
    for ln in load_lines():
        kw = ln.get("image_keyword")
        if not kw:
            continue
        cands = []
        if ln.get("image_file"):
            cands.append(ln["image_file"])
        cands.append(f"img_{ln['id']}")
        cands.append(sanitize(kw))
        actual = find_existing(cands)
        slots.append({
            "id": ln["id"],
            "section": ln.get("section"),
            "keyword": kw,
            "suggested_file": f"img_{ln['id']}.png",
            "status": "present" if actual else "missing",
            "actual_file": actual,
        })
    return slots


def cmd_check() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    slots = image_slots()
    present = [s for s in slots if s["status"] == "present"]
    missing = [s for s in slots if s["status"] == "missing"]

    WANTED.write_text(json.dumps({
        "note": "Gemini/ユーザーは missing の各行に対し suggested_file 名で画像を assets/images/ へ配置",
        "slots": slots,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 配置済みなのに参照されない画像（参照用commons画像など）を情報表示
    referenced = {s["actual_file"] for s in present if s["actual_file"]}
    orphan = [p.name for p in IMAGES_DIR.iterdir()
              if p.is_file() and p.suffix.lower() in IMG_EXTS and p.name not in referenced]

    print(f"画像スロット {len(slots)} 件： 充足 {len(present)} / 不足 {len(missing)}")
    if missing:
        print("\n[不足＝Gemini/ユーザーが生成・配置してください]")
        for s in missing:
            print(f"  id{s['id']:>2} [{s['section']}] {s['suggested_file']}  ← {s['keyword']}")
    if orphan:
        print("\n[参照されていない画像（参照用/未割当）]")
        for n in orphan:
            print(f"  {n}")
    print(f"\n不足リスト: {WANTED}")

    # マニフェストの stale エントリ掃除（削除済みファイル）
    if MANIFEST.exists():
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        m2 = {k: v for k, v in m.items() if (IMAGES_DIR / v.get("file", "")).exists()}
        if len(m2) != len(m):
            MANIFEST.write_text(json.dumps(m2, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"（マニフェストの無効エントリ {len(m)-len(m2)} 件を掃除）")


def cmd_resize(spec: str) -> None:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow が必要です:  py -m pip install pillow")
        return
    w, h = (int(x) for x in spec.lower().split("x"))
    out = IMAGES_DIR / "_normalized"
    out.mkdir(exist_ok=True)
    n = 0
    for p in IMAGES_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            im = Image.open(p).convert("RGBA")
            im.thumbnail((w, h))
            im.save(out / (p.stem + ".png"))
            n += 1
    print(f"{n} 枚を {w}x{h} 以内へ正規化 → {out}")


# ---- フォールバック：Wikimedia Commons 取得（従来機能） -----------------
def cmd_commons() -> None:
    import time
    import requests
    API = "https://commons.wikimedia.org/w/api.php"
    # Wikimediaの礼儀としてUser-Agentに連絡先を入れる。個人メールをハードコードせず環境変数で指定可。
    _contact = os.environ.get("WIKIMEDIA_CONTACT", "contact via repository")
    HEADERS = {"User-Agent": f"AIHistoryGeminiProject/1.0 (education; {_contact})"}
    ACCEPT = {"image/jpeg": ".jpg", "image/png": ".png", "image/svg+xml": ".png"}

    def api(params):
        r = requests.get(API, params={**params, "format": "json"}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()

    def variants(kw):
        w = kw.split(); v = [kw]
        for n in range(len(w) - 1, 1, -1):
            v.append(" ".join(w[:n]))
        if w:
            v += [w[0], w[-1]]
        seen, out = set(), []
        for x in v:
            if x and x not in seen:
                seen.add(x); out.append(x)
        return out

    def pick(kw):
        for q in variants(kw):
            j = api({"action": "query", "list": "search", "srsearch": q,
                     "srnamespace": 6, "srlimit": 12})
            titles = [h["title"] for h in j.get("query", {}).get("search", [])]
            if not titles:
                continue
            j2 = api({"action": "query", "titles": "|".join(titles), "prop": "imageinfo",
                      "iiprop": "url|mime|size", "iiurlwidth": 1600})
            infos = {p["title"]: p["imageinfo"][0]
                     for p in j2.get("query", {}).get("pages", {}).values() if p.get("imageinfo")}
            for t in titles:
                info = infos.get(t)
                if info and info.get("mime") in ACCEPT and (info.get("width", 0) or 0) >= 200:
                    return t, info, q
        return None, None, None

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    for s in [x for x in image_slots() if x["status"] == "missing"]:
        kw = s["keyword"]
        try:
            t, info, q = pick(kw)
            if not info:
                print(f"[MISS] {kw}"); continue
            url = info.get("thumburl") or info.get("url")
            ext = ACCEPT.get(info["mime"], ".jpg")
            dest = IMAGES_DIR / f"{sanitize(kw)}{ext}"
            dest.write_bytes(requests.get(url, headers=HEADERS, timeout=60).content)
            print(f"[ ok ] {kw} -> {dest.name}（'{q}'／要目視確認）")
            time.sleep(0.4)
        except Exception as e:
            print(f"[ERR ] {kw}: {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description="解説画像の管理（既定=check）")
    ap.add_argument("mode", nargs="?", default="check", choices=["check", "resize", "commons"])
    ap.add_argument("--size", default="1200x900", help="resize時の長辺 WxH")
    args = ap.parse_args()
    if args.mode == "check":
        cmd_check()
    elif args.mode == "resize":
        cmd_resize(args.size)
    elif args.mode == "commons":
        cmd_commons()


if __name__ == "__main__":
    main()
