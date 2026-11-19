"""Final musicality check (Стас 2026-11-19: «в конце надо оценивать музыкальность»). Usage: python3 musicality.py ours.wav [ref.wav]
Prints and returns: tonal clarity (key-profile fit), pitch-vs-noise share of the non-drum part, Audiobox CE/PC, and with a ref: chroma similarity + Audiobox gap.
Then a BLIND Gemini rating: clips named X/Y in random order, no titles, 1-10 musicality each + one reason. Verdict FAIL if ours is clearly unmusical; do not send on FAIL."""
import sys, os, json, random, subprocess, tempfile, numpy as np, librosa
sys.path.insert(0, "/opt/autodj-mixer")
NAMES = "C C# D D# E F F# G G# A A# B".split()
MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]); MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.6, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
def tonal(path):
    y, sr = librosa.load(path, sr=22050); h, _ = librosa.effects.hpss(y); tun = librosa.estimate_tuning(y=h, sr=sr)
    ch = librosa.feature.chroma_cqt(y=h, sr=sr, tuning=tun).mean(1)
    fit, key = max((np.corrcoef(np.roll(t, k), ch)[0, 1], NAMES[k] + m) for k in range(12) for t, m in ((MAJ, ""), (MIN, "m")))
    S = np.abs(librosa.stft(h)); flat = float(librosa.feature.spectral_flatness(S=S).mean())
    return dict(key=key, key_fit=round(float(fit), 2), harm_flatness=round(flat, 3), harm_share=round(float((h ** 2).sum() / ((y ** 2).sum() + 1e-12)), 2)), ch
def gemini(paths):
    from autodj.compose.review import _upload
    import urllib.request, time
    key = os.environ["GOOGLE_API_KEY"]; order = list(paths); random.shuffle(order); lab = dict(zip(order, "XY")); parts = []
    for p in order:
        mp3 = tempfile.mktemp(suffix=".mp3"); subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", p, "-b:a", "192k", mp3], check=True)
        parts += [{"text": f"Клип {lab[p]}:"}, {"file_data": {"mime_type": "audio/mpeg", "file_uri": _upload(mp3, key)}}]
    q = ("Два коротких музыкальных клипа, X и Y. Оцени каждый ОТДЕЛЬНО по музыкальности 1-10: есть ли ясная мелодия/рифф с определённой высотой, держится ли тональность, "
         "сочетаются ли бас и мелодия, есть ли грув. Не знаешь, что это за музыка, не угадывай. Ответ строго JSON: {\"X\": {\"score\": n, \"why\": \"...\"}, \"Y\": {...}} по-русски.")
    body = {"contents": [{"parts": parts + [{"text": q}]}], "generationConfig": {"responseMimeType": "application/json"}}
    for m in ("gemini-3.8-flash", "gemini-3-flash-preview", "gemini-2.5-flash"):
        try:
            r = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            js = json.loads(json.load(urllib.request.urlopen(r, timeout=300))["candidates"][0]["content"]["parts"][-1]["text"])
            return {os.path.basename(p): js.get(lab[p]) for p in paths} | {"model": m}
        except Exception as e: err = str(e); time.sleep(3)
    return {"error": err}
def main(ours, ref=None):
    from autodj.compose.ears import abx
    out = {"ours": tonal(ours)[0] | {"abx": abx(ours, clip_s=10.0, at=(.5,))}}
    if ref:
        out["ref"] = tonal(ref)[0] | {"abx": abx(ref, clip_s=10.0, at=(.5,))}
        out["chroma_sim"] = round(float(np.corrcoef(tonal(ours)[1], tonal(ref)[1])[0, 1]), 2)
    g = gemini([ours] + ([ref] if ref else [])); out["gemini_blind"] = g
    so = (g.get(os.path.basename(ours)) or {}).get("score"); sr_ = (g.get(os.path.basename(ref)) or {}).get("score") if ref else None
    fails = []
    if out["ours"]["key_fit"] < (.5 if not ref else min(.5, out["ref"]["key_fit"] - .1)): fails.append("тональность не держится")
    if ref and out["chroma_sim"] < .6: fails.append("гармония не совпадает с оригиналом")
    if so is not None and (so < 5 or (sr_ is not None and so < sr_ - 2)): fails.append("слепой слушатель: немузыкально")
    a, b = out["ours"]["abx"], (out.get("ref") or {}).get("abx")
    if b and "CE" in a and "CE" in b and a["CE"] < b["CE"] - .7: fails.append("Audiobox CE заметно ниже оригинала")
    out["verdict"] = "FAIL: " + "; ".join(fails) if fails else "PASS"
    print(json.dumps(out, ensure_ascii=False, indent=1)); return out
if __name__ == "__main__": main(*sys.argv[1:3])
