"""P114 (2026-10-23): guard a sound for its ROLE before it is used. My measurements (in tune, warm centroid, sustain) let
the Vital «FM Chorus Lead» through and Стас heard «a cheap 90s flute» (again in the W.A. Lead_Shot_26). A harmonic count
does not separate these from sounds he liked (Rhodes, piano, plucks also have few harmonics), so the guard is built on
his own verdicts: a timbre profile (spectral shape + MFCC) of every judged sound is stored with good/bad, and a candidate
that sits nearer to a «bad» sound than to any «good» one is flagged. Plus plain genre bounds (e.g. dark: lead centroid
<= 2.6 kHz). It only advises/blocks the choice of a sound; it never changes audio. audition() exports short blind clips
for Стас (4 s each) so the next verdicts come from his ear.
    from autodj.compose import timbre_guard as tg
    tg.check(render_one_note, "lead", mood="dark")   -> {"ok": bool, "reasons": [...], "nearest": (name, verdict, dist)}"""
import json, os, numpy as np, librosa
SR = 44100
STORE = os.environ.get("AUTODJ_TIMBRE_VERDICTS", "/opt/autodj-mixer/shared/timbre_verdicts.json")
BOUNDS = {"*": {"lead": dict(cen_max=4200), "pad": dict(cen_max=3200), "pluck": dict(cen_max=4500), "bass": dict(cen_max=1200)},
          "dark": {"lead": dict(cen_max=2600), "pad": dict(cen_max=2000), "pluck": dict(cen_max=3500), "bass": dict(cen_max=900)},
          "bright": {"lead": dict(cen_max=6000), "pad": dict(cen_max=4500), "pluck": dict(cen_max=6500), "bass": dict(cen_max=1500)}}

def profile(x, sr=SR):
    """one note's timbre: centroid (Hz), share of energy above 3 kHz, flatness, MFCC 1..12 means (pitch-light shape)"""
    m = x.mean(1) if np.ndim(x) == 2 else np.asarray(x, np.float32)
    nz = np.where(np.abs(m) > .02 * (np.abs(m).max() + 1e-12))[0]
    if len(nz) < 1024: return None
    m = m[nz[0]:nz[0] + int(1.0 * sr)]; m = m / (np.abs(m).max() + 1e-12)
    S = np.abs(librosa.stft(m, n_fft=2048)) + 1e-12; f = librosa.fft_frequencies(sr=sr, n_fft=2048)
    cen = float((f[:, None] * S).sum(0).mean() / S.sum(0).mean()); hi = float(S[f > 3000].sum() / S.sum())
    flat = float(librosa.feature.spectral_flatness(S=S).mean()); mf = librosa.feature.mfcc(y=m, sr=sr, n_mfcc=13).mean(1)[1:]
    return {"cen": round(cen, 1), "hi": round(hi, 4), "flat": round(flat, 4), "mfcc": [round(float(v), 2) for v in mf]}

def _vec(p):
    return np.array([np.log2(p["cen"] / 1000.0) * 4, p["hi"] * 20, p["flat"] * 40] + [v / 25.0 for v in p["mfcc"]], np.float32)

def load(path=None):
    path = path or STORE; return json.load(open(path)) if os.path.exists(path) else []

def add_verdict(name, x, good, role, note="", path=None, sr=SR):
    p = profile(x, sr)
    if p is None: return None
    db = [d for d in load(path) if d["name"] != name] + [{"name": name, "good": bool(good), "role": role, "note": note, **p}]
    json.dump(db, open(path or STORE, "w"), ensure_ascii=False, indent=0); return p

def nearest(x, role=None, path=None, sr=SR):
    p = profile(x, sr); db = [d for d in load(path) if role is None or d["role"] == role] or load(path)
    if p is None or not db: return None
    v = _vec(p); dist = sorted((float(np.linalg.norm(v - _vec(d))), d["name"], d["good"]) for d in db)
    return {"profile": p, "ranked": dist}

def check(x, role, mood="*", path=None, sr=SR):
    """ok=False if outside the genre bounds or nearer to a judged-bad sound than to every judged-good one"""
    reasons = []; r = nearest(x, role, path, sr)
    p = r["profile"] if r else profile(x, sr)
    if p is None: return {"ok": False, "reasons": ["silent / too short"], "nearest": None}
    b = {**BOUNDS["*"].get(role, {}), **BOUNDS.get(mood, {}).get(role, {})}
    if "cen_max" in b and p["cen"] > b["cen_max"]: reasons.append(f"too bright for {mood} {role}: centroid {p['cen']:.0f} > {b['cen_max']} Hz")
    near = None
    if r:
        near = r["ranked"][0]; bad = [d for d in r["ranked"] if not d[2]]; good = [d for d in r["ranked"] if d[2]]
        if bad and (not good or bad[0][0] < good[0][0]): reasons.append(f"sounds like a rejected sound: {bad[0][1]} (dist {bad[0][0]:.2f})")
    return {"ok": not reasons, "reasons": reasons, "nearest": near, "profile": p}

def audition(clips, outdir, seconds=4.0, sr=SR, seed=0):
    """clips {name: stereo array} -> blind A,B,C... 4 s mp3s + key.json (names hidden from the listener)"""
    import subprocess, soundfile as sf
    os.makedirs(outdir, exist_ok=True); names = list(clips); order = np.random.default_rng(seed).permutation(len(names)); key = {}
    for i, j in enumerate(order):
        L = chr(65 + i); x = clips[names[j]][: int(seconds * sr)]; x = x / (np.abs(x).max() + 1e-9) * .7
        w = os.path.join(outdir, f"{L}.wav"); sf.write(w, x, sr)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", w, "-q:a", "3", os.path.join(outdir, f"{L}.mp3")], check=True); os.remove(w); key[L] = names[j]
    json.dump(key, open(os.path.join(outdir, "key.json"), "w"), ensure_ascii=False, indent=1); return key
