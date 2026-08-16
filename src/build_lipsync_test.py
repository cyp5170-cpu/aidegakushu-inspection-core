# -*- coding: utf-8 -*-
"""口パク/瞬き 検証用テスト（id1〜6のみ）。
旧SD_v5の実証済 TachieItem(茜/葵)＋VoiceItem(Hatsuon=生wav＋同名.lab→YMM4が実行時に口パク自動計算)を土台に、
この新PJの音声で最小構成を組む。ClaudeはYMM4検証不可＝ユーザーが開いて口パク/瞬き/立ち絵表示を確認する用。
出力: output/AI_History_Ep1_lipsync_test.ymmp
"""
import json, copy, sys, io, wave, contextlib
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "src" / "_templates"
AUDIO = ROOT / "audio"
OUT = ROOT / "output" / "AI_History_Ep1_lipsync_test.ymmp"
FPS = 60
WAVJP = {"akane": "茜", "aoi": "葵"}                 # 生wav名・POS/FLIP/TACのキー
CHARNAME = {"akane": "琴葉茜SD", "aoi": "琴葉葵SD"}   # YMM4のキャラ名（登録済みSDキャラ）
POS = {"茜": {"x": -560.0, "y": 230.0, "zoom": 27.0}, "葵": {"x": 560.0, "y": 230.0, "zoom": 27.0}}
FLIP = {"茜": True, "葵": False}
NTEST = 6

_HOME = str(Path.home())
def _expand_home(obj):
    # テンプレJSONの %USERPROFILE% トークンを実ホームへ展開（ユーザー名をハードコードしない）
    if isinstance(obj, str): return obj.replace("%USERPROFILE%", _HOME)
    if isinstance(obj, list): return [_expand_home(x) for x in obj]
    if isinstance(obj, dict): return {k: _expand_home(v) for k, v in obj.items()}
    return obj

def load(p, sig=False):
    return _expand_home(json.load(open(p, encoding="utf-8-sig" if sig else "utf-8")))

BASE = load(TPL / "base_project.json", sig=True)
CHARS_DEF = load(TPL / "sd_characters.json")
VOICE = load(TPL / "sd_voice.json")
DEMO_AOI = load(TPL / "demo_tachie_琴葉葵SD.json")   # 母音口パク動作の実物(葵)
_dtp = DEMO_AOI["TachieItemParameter"]
MOUTH_PAIRS = [(p, l) for p, l in zip(_dtp["EnableLayerPaths"], _dtp["EnableLayers"]) if "口" in p]
def _patch_mouth(tp):
    """既存パラメータの口関連パスを、母音口パク動作の口>あいうえおグループへ差し替え。"""
    tp = copy.deepcopy(tp)
    kept = [(p, l) for p, l in zip(tp["EnableLayerPaths"], tp["EnableLayers"]) if "口" not in p]
    kept += MOUTH_PAIRS
    tp["EnableLayerPaths"] = [p for p, l in kept]; tp["EnableLayers"] = [l for p, l in kept]
    return tp
TACPARAM = {"葵": copy.deepcopy(_dtp),
            "茜": _patch_mouth(load(TPL / "sd_tachie_茜.json")["TachieItemParameter"])}
IMG = load(TPL / "image_item.json")
TXT = load(TPL / "text_item.json")

def anim(v):
    a = copy.deepcopy(IMG["X"]); a["Values"] = [{"Value": float(v)}]; return a

def wdur(f):
    with contextlib.closing(wave.open(str(f), "rb")) as w:
        return w.getnframes() / float(w.getframerate())

def ts(sec):
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = sec % 60
    return f"{h:02d}:{m:02d}:{s:010.7f}"

VOWEL = {"a": "A", "i": "I", "u": "U", "e": "E", "o": "O"}
def lipsync_from_lab(lab_path):
    """A.I.VOICE2の.lab(音素ラベル・100ns単位)→ YMM4 LipSyncFrames(母音A/I/U/E/O＋Silent)。
    子音はスキップ＝直前の母音口形を保持（自然な五十音口パク）。"""
    frames = [{"Time": "00:00:00", "Shape": "Silent"}]
    if not lab_path or not lab_path.exists():
        return frames
    for line in lab_path.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) < 3:
            continue
        t = int(p[0]) * 1e-7
        lab = p[2]
        if lab in VOWEL:
            frames.append({"Time": ts(t), "Shape": VOWEL[lab]})
        elif lab == "pau":
            frames.append({"Time": ts(t), "Shape": "Silent"})
    return frames

def raw_wav(idn, spk):
    cs = list(AUDIO.glob(f"琴葉 {WAVJP[spk]}(NV){idn:04d}*.wav"))
    return cs[0] if cs else None

def voice_item(idn, spk, text, frame, length, dur):
    v = copy.deepcopy(VOICE)
    v["CharacterName"] = CHARNAME[spk]; v["Serif"] = text
    w = raw_wav(idn, spk)
    v["Hatsuon"] = str(w)
    v["Pronounce"] = {"$type": "YukkuriMovieMaker.Voice.CustomVoice.CustomVoicePronounce, YukkuriMovieMaker",
                      "LipSyncFrames": lipsync_from_lab(w.with_suffix(".lab") if w else None)}
    v["LipSyncFrames"] = None; v["VoiceCache"] = None
    v["VoiceLength"] = ts(dur)
    v["JimakuVisibility"] = "Hidden"
    v["Frame"] = int(frame); v["Length"] = max(1, int(length)); v["Layer"] = 2
    return v

def tachie_item(spk, frame, length, layer):
    sister = WAVJP[spk]
    t = copy.deepcopy(DEMO_AOI)                          # item骨格(母音口パク動作の実物)
    t["CharacterName"] = CHARNAME[spk]
    t["TachieItemParameter"] = copy.deepcopy(TACPARAM[sister])  # 茜=あかねbody+口パク／葵=demo
    t["Frame"] = int(frame); t["Length"] = max(1, int(length)); t["Layer"] = int(layer)
    p = POS[sister]
    t["X"] = anim(p["x"]); t["Y"] = anim(p["y"]); t["Zoom"] = anim(p["zoom"])
    t["Rotation"] = anim(0.0); t["Opacity"] = anim(100.0); t["Z"] = anim(0.0)
    t["IsInverted"] = FLIP.get(sister, False)
    t["VideoEffects"] = []
    return t

def image_item(path, frame, length, layer, x=0.0, y=0.0, zoom=100.0):
    it = copy.deepcopy(IMG)
    it["FilePath"] = str(path); it["Frame"] = int(frame); it["Length"] = max(1, int(length)); it["Layer"] = int(layer)
    it["X"] = anim(x); it["Y"] = anim(y); it["Zoom"] = anim(zoom); it["Rotation"] = anim(0.0)
    it["Opacity"] = anim(100.0); it["Z"] = anim(0.0); it["VideoEffects"] = []; it["FadeIn"] = 0.0; it["FadeOut"] = 0.0
    return it

def text_item(text, frame, length, layer, y=470.0, color="#FFFFFFFF", sc="#FF101820"):
    it = copy.deepcopy(TXT)
    it["Text"] = text; it["Frame"] = int(frame); it["Length"] = max(1, int(length)); it["Layer"] = int(layer)
    it["X"] = anim(0.0); it["Y"] = anim(y); it["Zoom"] = anim(100.0); it["Rotation"] = anim(0.0)
    it["Opacity"] = anim(100.0); it["Z"] = anim(0.0); it["FontSize"] = anim(44.0)
    it["BasePoint"] = "CenterBottom"; it["FontColor"] = color; it["Style"] = "Border"; it["StyleColor"] = sc
    it["Bold"] = True; it["IsAlwaysOnTop"] = True; it["IsDevidedPerCharacter"] = False
    it["DisplayInterval"] = 0.0; it["VideoEffects"] = []; it["FadeIn"] = 0.0; it["FadeOut"] = 0.0
    return it

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = load(ROOT / "script" / "script.json")
    lines = (data["lines"] if isinstance(data, dict) else data)[:NTEST]

    proj = copy.deepcopy(BASE)
    tl = proj["Timelines"][0]
    tl["VideoInfo"]["FPS"] = FPS; tl["VideoInfo"]["Width"] = 1920; tl["VideoInfo"]["Height"] = 1080
    tl["VideoInfo"]["BackgroundColor"] = "#FF202B25"; tl["LayerSettings"] = None
    for c in CHARS_DEF:   # 登録名に合わせ、デフォルト口を母音口パク(あいうえお)へ
        if c.get("Name") == "茜": c["Name"] = CHARNAME["akane"]
        elif c.get("Name") == "葵": c["Name"] = CHARNAME["aoi"]
        di = c.get("TachieDefaultItemParameter")
        if isinstance(di, dict) and "EnableLayerPaths" in di:
            c["TachieDefaultItemParameter"] = _patch_mouth(di)
    proj["Characters"] = CHARS_DEF; proj["FilePath"] = str(OUT)

    items = []
    board = ROOT / "assets" / "images" / "_board_bg.png"
    # 尺割付（先に全区間を確定）
    spans = []; frame = 6; miss = []
    for ln in lines:
        spk = ln["speaker"] if ln["speaker"] in ("akane", "aoi") else "aoi"
        w = raw_wav(ln["id"], spk)
        if not w:
            miss.append(ln["id"]); continue
        dur = wdur(w); length = round(dur * FPS)
        spans.append((ln, spk, dur, frame, length))
        frame += length + 12
    total = frame
    for idx, (ln, spk, dur, f, length) in enumerate(spans):
        seg_len = (spans[idx+1][3] - f) if idx+1 < len(spans) else (total - f)
        items.append(voice_item(ln["id"], spk, ln["text"], f, length, dur))   # 音声=実長
        # 立ち絵：両話者を区間連続で配置（隙間なし＝一瞬消え防止）。テストは表情固定
        for who in ("akane", "aoi"):
            items.append(tachie_item(who, f, seg_len, 5))
        items.append(text_item(f"{('琴葉'+WAVJP[spk])}：{ln['text'][:26]}", f, seg_len, 12,
                               sc=("#FFE63946" if spk == "akane" else "#FF0077B6")))
    items.insert(0, image_item(board, 0, total, 1, 0, 0, 100.0))
    tl["Items"] = items; tl["Length"] = total; tl["MaxLayer"] = 12; tl["CurrentFrame"] = 0
    json.dump(proj, open(OUT, "w", encoding="utf-8-sig"), ensure_ascii=False, indent=1)
    print(f"テスト{len(lines)}行 / item{len(items)} / 尺{total/FPS:.1f}s / 音声欠落{miss}")
    print("出力:", OUT)

if __name__ == "__main__":
    main()
