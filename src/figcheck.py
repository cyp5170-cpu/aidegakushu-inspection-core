# -*- coding: utf-8 -*-
r"""
figcheck.py — 画像（医療模式図）の独立・敵対検品＝medcheckの"画像版"

図＋事実仕様(CLAIMS) → ビジョンLLM(Claude Opus5 / Gemini Flash無料)が**わざと間違い探し**で
7観点(機構/数/局在/誤解要素/ラベル/一次資料/臨床)に照らし、NG項目・誤解要素・修正案を構造化出力。

原則（検品システム）：
  - 生成者(a)自身の目視は盲点が相関 → **別モデル/別エージェントで見る**のがこのツールの価値。
  - LLMも間違える（数え違い・局在誤読）＝補助。最終は人間(薬剤師)＋spec照合。

使い方:
  python src/figcheck.py "医療\細胞_分子\TPO機構_模式図.png" --claims "TPOはアピカル膜に埋まる;チロシンにヨウ素1個=MIT;2個=DIT;NISは描かない;コロイドは上・甲状腺の細胞は下" --backend gemini
  python src/figcheck.py path.png --spec-file spec.txt --backend claude --log "台帳.md"

必要: pip install anthropic google-genai pydantic  ／ APIキー(claude=ANTHROPIC_API_KEY / gemini=GEMINI_API_KEY)
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_boot  # 鍵は env_boot.resolve() で読取専用取得しSDKへ明示渡し（os.environ非汚染・過剰伝播#3回避）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import base64
import argparse
from typing import List

DB = r"C:\claude_shared\素材DB"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp"}

SYSTEM = (
    "あなたは医療図の独立した敵対的レビュアーです。与えられた図を、CLAIMS(この図が満たすべき事実仕様)と"
    "観点①機構②数・化学量論③局在④誤解要素⑤ラベル明快⑥一次資料整合⑦臨床接続"
    "⑧初学者フレンドリー(専門用語が図だけで分かるか＝未注釈のjargonを具体的に列挙／例『血液側』等の言い換え要否)"
    "⑨レイアウト・可読性(ラベルの重なり・窮屈・見切れ・薄くて読めない矢印/線・図と注釈の接触を列挙)"
    "⑩未説明の視覚要素(色付きの粒・記号・線・枠で凡例や説明が無いものを列挙＝『この丸は何？』を潰す)"
    "⑪図間整合(複数枚が渡された時のみ: **別概念が同じ見た目になっていないか**＝例 酵素と輸送体が同じ形／同概念がバラバラでないか／膜の側の描き方が一貫か)"
    "に照らし、**わざと間違い探し**します。"
    "**この図を初めて見る初学者**と**粗探しする専門家**の両方になりきり、"
    "『ユーザーに指摘される前に自分で全部あぶり出す』つもりで、不親切・重なり・未説明・不整合まで先回りで洗い出す。"
    "図を実際に見て、数・局在・矢印の向きと先・チャネル誤認/酵素と輸送体の取り違え・ラベルの曖昧/重なり/欠落・専門用語の不親切・凡例なき要素を厳しく確認。"
    "忖度・褒めは不要。正しく描けている点は confirmed に、問題は findings に(観点・重大度・修正案)。"
    "見落としを恐れず、疑わしきは指摘。CLAIMSの事実の真偽は判定せず『図がCLAIMS通り＋初学者に不親切でなく＋(複数図なら)整合的か』を見る。日本語で。"
)


def _verdict_cls():
    from pydantic import BaseModel
    from typing import Literal

    class Finding(BaseModel):
        kanten: Literal["機構", "数", "局在", "誤解要素", "ラベル", "一次資料", "臨床", "初学者", "レイアウト", "未説明", "整合", "その他"]
        problem: str          # 何が問題か
        severity: Literal["致命", "要修正", "軽微"]
        fix: str              # 推奨修正

    class FigVerdict(BaseModel):
        overall: Literal["合格", "要修正", "不合格"]
        confirmed: List[str]  # 仕様のうち正しく描けている項目
        findings: List[Finding]
        misleading: List[str]  # 誤解を招く要素
    return FigVerdict, Finding


def _load_image(path: str):
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = [path] if os.path.isabs(path) else [os.path.join(DB, path), os.path.join(proj, path)]
    p = next((c for c in cands if os.path.exists(c)), None)
    if p is None:
        print(f"[fail] 画像が見つかりません: {path}"); sys.exit(2)
    with open(p, "rb") as f:
        data = f.read()
    ext = os.path.splitext(p)[1].lower()
    return data, MIME.get(ext, "image/png"), p


def _prompt(claims: List[str], n: int = 1) -> str:
    spec = "\n".join(f"- {c}" for c in claims) if claims else "(仕様未指定＝観点で一般検品)"
    extra = (f"\n\n★複数図(計{n}枚)＝**⑪図間整合を必ず見る**：別概念(酵素vs輸送体等)が同じ見た目になっていないか／"
             "同概念がバラバラでないか／膜の側の描き方が一貫か。") if n > 1 else ""
    return (f"CLAIMS(この図が満たすべき事実仕様):\n{spec}{extra}\n\n"
            "上の図を敵対的に、**初めて見る初学者＋粗探しする専門家の両目で**検品してください（不親切・重なり・未説明・不整合も先回りで）。")


def check_with_claude(imgs, claims: List[str]):
    api_key = env_boot.resolve("ANTHROPIC_API_KEY")
    auth_token = env_boot.resolve("ANTHROPIC_AUTH_TOKEN")
    if not (api_key or auth_token):
        print("[skip] ANTHROPIC_API_KEY 未設定。"); return None
    try:
        import anthropic
    except ImportError:
        print("[skip] anthropic 未導入（pip install anthropic pydantic）"); return None
    FigVerdict, _ = _verdict_cls()
    # 認証は明示渡し（os.environ非汚染・#3）。api_key優先・無ければauth_token。
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic(auth_token=auth_token)
    content = []
    for i, (img, mime) in enumerate(imgs):
        if len(imgs) > 1:
            content.append({"type": "text", "text": f"[図{i + 1}]"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.standard_b64encode(img).decode("utf-8")}})
    content.append({"type": "text", "text": _prompt(claims, len(imgs))})
    try:
        resp = client.messages.parse(
            model="claude-opus-5", max_tokens=2048, system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_format=FigVerdict,
        )
        return resp.parsed_output
    except Exception as e:
        print(f"[error] Claude呼び出し失敗: {e}"); return None


def check_with_gemini(imgs, claims: List[str]):
    key = env_boot.resolve("GEMINI_API_KEY") or env_boot.resolve("GOOGLE_API_KEY")
    if not key:
        print("[skip] GEMINI_API_KEY 未設定。https://aistudio.google.com/ で無料取得。"); return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[skip] google-genai 未導入（pip install google-genai pydantic）"); return None
    FigVerdict, _ = _verdict_cls()
    client = genai.Client(api_key=key)
    contents = []
    for i, (img, mime) in enumerate(imgs):
        if len(imgs) > 1:
            contents.append(f"[図{i + 1}]")
        contents.append(types.Part.from_bytes(data=img, mime_type=mime))
    contents.append(_prompt(claims, len(imgs)))
    try:
        resp = client.models.generate_content(
            model="gemini-flash-latest",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=FigVerdict,
            ),
        )
        v = getattr(resp, "parsed", None)
        if v is None:
            import json as _j
            v = FigVerdict(**_j.loads(resp.text))
        return v
    except Exception as e:
        print(f"[error] Gemini呼び出し失敗: {e}"); return None


def check_with_vertex(imgs, claims: List[str]):
    """Vertex AI + ADC（APIキー不要・$300トライアルから課金）。要 gcloud auth application-default login。"""
    proj = env_boot.resolve("GOOGLE_CLOUD_PROJECT")
    if not proj:
        print("[skip] GOOGLE_CLOUD_PROJECT 未設定。setx GOOGLE_CLOUD_PROJECT <プロジェクトID>（＋gcloud auth application-default login）。"); return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[skip] google-genai 未導入（pip install google-genai pydantic）"); return None
    FigVerdict, _ = _verdict_cls()
    loc = env_boot.resolve("GOOGLE_CLOUD_LOCATION") or "us-central1"
    client = genai.Client(vertexai=True, project=proj, location=loc)  # ADC認証＝APIキー不要
    contents = []
    for i, (img, mime) in enumerate(imgs):
        if len(imgs) > 1:
            contents.append(f"[図{i + 1}]")
        contents.append(types.Part.from_bytes(data=img, mime_type=mime))
    contents.append(_prompt(claims, len(imgs)))
    try:
        resp = client.models.generate_content(
            model=env_boot.resolve("GEMINI_MODEL") or "gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=FigVerdict,
            ),
        )
        v = getattr(resp, "parsed", None)
        if v is None:
            import json as _j
            v = FigVerdict(**_j.loads(resp.text))
        return v
    except Exception as e:
        print(f"[error] Vertex呼び出し失敗: {e}"); return None


def check_with_openai(imgs, claims: List[str]):
    """OpenAI(GPT-5系ビジョン)で図検品＝Claude/Geminiと別系統の"第3の目"。OPENAI_API_KEY を使用。
    モデルは OPENAI_MODEL で上書き可（vision対応モデルであること）。"""
    openai_key = env_boot.resolve("OPENAI_API_KEY")
    if not openai_key:
        print("[skip] OPENAI_API_KEY 未設定。https://platform.openai.com/api-keys で取得→ setx OPENAI_API_KEY \"sk-...\"。")
        return None
    try:
        from openai import OpenAI
    except ImportError:
        print("[skip] openai 未導入（pip install openai pydantic）"); return None
    FigVerdict, _ = _verdict_cls()
    client = OpenAI(api_key=openai_key)  # 認証は明示渡し（os.environ非汚染・#3）
    model = env_boot.resolve("OPENAI_MODEL") or "gpt-5.6-terra"
    content = []
    for i, (img, mime) in enumerate(imgs):
        if len(imgs) > 1:
            content.append({"type": "text", "text": f"[図{i + 1}]"})
        b64 = base64.standard_b64encode(img).decode("utf-8")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    content.append({"type": "text", "text": _prompt(claims, len(imgs))})
    try:
        resp = client.beta.chat.completions.parse(
            model=model,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": content}],
            response_format=FigVerdict,
        )
        return resp.choices[0].message.parsed
    except Exception as e:
        print(f"[error] OpenAI呼び出し失敗: {e}\n"
              f"        → OPENAI_MODEL をvision対応の現行モデルID(https://platform.openai.com/docs/models)に設定してください。")
        return None


def main():
    ap = argparse.ArgumentParser(description="医療図の独立・敵対検品（画像版medcheck）")
    ap.add_argument("image", nargs="+", help="図のパス（1枚=通常検品／2枚以上=⑪図間整合も検品：別概念が同じ見た目でないか）")
    ap.add_argument("--claims", default="", help="事実仕様（; 区切り）")
    ap.add_argument("--spec-file", default=None, help="仕様ファイル（1行1項目）")
    ap.add_argument("--backend", choices=["claude", "gemini", "vertex", "openai"], default="gemini",
                    help="claude=課金／openai=GPT-5系vision／gemini=AI Studioキー／vertex=Vertex+ADC($300・APIキー不要)")
    ap.add_argument("--log", default=None, help="検品結果を追記する台帳(.md)")
    args = ap.parse_args()

    claims = [c.strip() for c in args.claims.split(";") if c.strip()]
    if args.spec_file and os.path.exists(args.spec_file):
        claims += [l.strip() for l in open(args.spec_file, encoding="utf-8") if l.strip()]
    if not claims:  # HIGH-4(R2): RAG接地の代替＝仕様との照合を必須化（ビジョンLLMの記憶頼みを禁止）
        print("[fail] --claims か --spec-file で『事実仕様』を必ず指定。figcheckは『仕様との照合』が前提で、"
              "仕様自体の正しさはmedcheck/一次資料で別途裏取り済みという運用にする。")
        sys.exit(2)

    loaded = [_load_image(p) for p in args.image]           # [(bytes, mime, path), ...]
    imgs = [(b, m) for b, m, _ in loaded]
    names = " / ".join(os.path.basename(p) for *_, p in loaded)
    mode = "図間整合込み" if len(imgs) > 1 else "単図"
    print(f"■ 図: {names}\n■ 仕様 {len(claims)}件 / 枚数 {len(imgs)}（{mode}） / backend={args.backend}\n")
    checker = {"claude": check_with_claude, "gemini": check_with_gemini,
               "vertex": check_with_vertex, "openai": check_with_openai}[args.backend]
    v = checker(imgs, claims)
    if v is None:
        # Claude-B R3-2/R3-3：検品したが失敗（キー未設定/API障害/画像拒否等）＝「未検証」を外形で区別。
        # medcheck.pyのLOW-2と同じく非ゼロ終了にし、自動化が"正常終了"と誤認しないようにする。
        print("[fail] 図を検品できませんでした＝この図は『未検証』（検証済みではない）。")
        sys.exit(2)

    print("=" * 60)
    print(f"総合: {v.overall}")
    print(f"確認OK: {('／'.join(v.confirmed)) or '(なし)'}")
    if v.misleading:
        print(f"誤解要素: {'／'.join(v.misleading)}")
    if v.findings:
        print("問題:")
        for f in v.findings:
            print(f"  [{f.severity}/{f.kanten}] {f.problem} → 修正: {f.fix}")
    else:
        print("問題: (指摘なし)")
    # HIGH-3(R2): 後付け完全性チェック＝仕様件数に対し確認/指摘が少なすぎれば未検証の疑い
    ncov = len(v.confirmed) + len(v.findings)
    if ncov < max(1, (len(claims) + 1) // 2):
        print(f"⚠️ 完全性：仕様{len(claims)}件に対し確認/指摘が計{ncov}件のみ＝一部が未検証の可能性（figcheckはLLM単眼＝見落とし得る）。")
    print("\n※ビジョンLLMも誤る（数え違い・局在誤読）＝補助。最終は人間(薬剤師)＋spec照合＋別視点。")

    if args.log:
        import datetime
        ng = "／".join(f"[{f.severity}/{f.kanten}]{f.problem}" for f in v.findings) or "なし"
        rec = (f"\n### figcheck: {names}（{args.backend}・{datetime.date.today().isoformat()}）\n"
               f"- 総合: {v.overall}／確認OK: {len(v.confirmed)}件／問題: {ng}\n"
               f"- ※LLM検品は補助。人間サインオフ必須。\n")
        with open(args.log, "a", encoding="utf-8") as fp:
            fp.write(rec)
        print(f"\n[log] 台帳に追記: {args.log}")


if __name__ == "__main__":
    main()
