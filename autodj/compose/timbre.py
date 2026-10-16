"""Timbre matching: describe drum hits by a few numbers and pick, from everything we own, the samples that sound
closest to a reference. Learned 2026-10-17: «Нічний тролейбус» had the right groove numbers but «примитивные семплы»
— the reference's kick/hats/perc were never compared to what we picked.

features(x): centroid (Hz), bandwidth, decay to -20 dB (ms), low-end pitch (Hz, for kicks), noisiness (flatness), click.
index(): one-shots (<=1.5 s) from all packs, cached at $AUTODJ_ASSETS/grooves/timbre_index.json.
ref_hits(drums_stem, class): median features of strong hits of that class in a reference stem.
match(target, kind, k): nearest samples in normalised feature space."""
import glob, json, os
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt, resample_poly
from .assets import ASSETS, WA, TDM, MUSICRADAR, VSCO

SR = 44100
KEYS = ("centroid", "bandwidth", "decay_ms", "pitch", "flatness", "click")

def features(x, sr=SR):
    x = x.mean(1) if x.ndim == 2 else x
    if sr != SR: x = resample_poly(x, SR, sr).astype(np.float32)
    x = x[:int(.6 * SR)]; x = x / (np.abs(x).max() + 1e-9); n = len(x)
    if n < 256: return None
    w = x[:min(n, 8192)] * np.hanning(min(n, 8192)); X = np.abs(np.fft.rfft(w, 16384)) + 1e-12; f = np.fft.rfftfreq(16384, 1 / SR)
    cen = float((f * X).sum() / X.sum()); bw = float(np.sqrt(((f - cen) ** 2 * X).sum() / X.sum()))
    env = np.maximum.accumulate(np.abs(x)[::-1])[::-1]; dec = np.argmax(env < .1) if np.any(env < .1) else n
    lo = (f > 30) & (f < 250); pitch = float(f[lo][np.argmax(X[lo])])
    flat = float(np.exp(np.mean(np.log(X[f < 16000]))) / np.mean(X[f < 16000]))
    hi = sosfiltfilt(butter(2, 2000, "high", fs=SR, output="sos"), x); click = float(np.abs(hi[:int(.01 * SR)]).max())
    return {"centroid": round(cen), "bandwidth": round(bw), "decay_ms": round(dec / SR * 1000, 1), "pitch": round(pitch, 1), "flatness": round(flat, 3), "click": round(click, 3)}

def _kind(path):
    p = path.lower()
    for k, words in (("kick", ("kick", "bd", "bassdrum")), ("hat", ("hat", "hh", "hithat", "shak", "tamb", "-oh", "_oh")),
                     ("perc", ("perc", "rim", "clav", "conga", "bongo", "tom", "cb", "cowbell", "wood", "log", "click", "quinto", "tumba", "guiro", "snap")),
                     ("snare", ("snare", "sd", "clap", "cp"))):
        if any(w in os.path.basename(p) or f"/{w}" in p or f"-{w}" in p for w in words): return k
    return None

def index(rebuild=False):
    out = os.path.join(ASSETS, "grooves", "timbre_index.json")
    if os.path.exists(out) and not rebuild: return json.load(open(out))
    files = (glob.glob(f"{WA}/**/*.wav", recursive=True) + glob.glob(f"{TDM}/**/*.wav", recursive=True) +
             glob.glob(f"{MUSICRADAR}/drums/**/*.wav", recursive=True) + glob.glob(f"{VSCO}/Percussion/*.wav"))
    idx = []
    for p in files:
        if "loop" in p.lower() or "bpm" in os.path.basename(p).lower(): continue
        k = _kind(p)
        if not k: continue
        try:
            info = sf.info(p)
            if info.duration > 1.5: continue
            x, sr = sf.read(p, dtype="float32", frames=int(.6 * info.samplerate))
            ft = features(x, sr)
            if ft: idx.append({"path": p, "kind": k, **ft})
        except Exception:
            pass
    json.dump(idx, open(out, "w")); return idx

BANDS = {"kick": ("low", 150), "hat": ("high", 5000), "perc": ("band", [900, 5000])}
WIN = {"kick": .3, "hat": .12, "perc": .15}

def band_features(x, cls, sr=SR):
    """features of the class's own band only (a hat inside a full drum loop is judged by its >5 kHz part)"""
    x = x.mean(1) if x.ndim == 2 else x; b = BANDS[cls]
    y = sosfiltfilt(butter(4, b[1], b[0], fs=sr, output="sos"), x[:int(WIN[cls] * sr)] if len(x) > 2000 else x)
    return features(y.astype(np.float32), sr)

def ref_hits(stem_path, cls, max_hits=200):
    """median band-features of the strongest hits of a class in a demucs drums stem"""
    import librosa
    x, sr = sf.read(stem_path, dtype="float32"); m = x.mean(1) if x.ndim == 2 else x; b = BANDS[cls]
    y = sosfiltfilt(butter(4, b[1], b[0], fs=sr, output="sos"), m)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256); on = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=256, units="samples", backtrack=True)
    st = env[np.clip(on // 256, 0, len(env) - 1)]; on = on[np.argsort(-st)][:max_hits]; L = int(WIN[cls] * sr)
    fts = [features(y[i:i + L].astype(np.float32), sr) for i in on if i + L < len(y)]
    fts = [f for f in fts if f]
    return {k: float(np.median([f[k] for f in fts])) for k in KEYS} if fts else None

_BF = {}
def match_band(target, cls, k=6, kinds=None):
    """nearest samples by band-features (computed on demand, cached per path)"""
    cands = [e for e in index() if e["kind"] in (kinds or {"kick": ("kick",), "hat": ("hat",), "perc": ("perc", "snare")}[cls])]
    out = []
    for e in cands:
        key = (e["path"], cls)
        if key not in _BF:
            try:
                x, sr0 = sf.read(e["path"], dtype="float32", frames=int(.4 * sf.info(e["path"]).samplerate))
                if sr0 != SR: x = resample_poly(x, SR, sr0, axis=0).astype(np.float32)
                _BF[key] = band_features(x, cls)
            except Exception: _BF[key] = None
        if _BF[key]: out.append({**e, **{"b_" + kk: v for kk, v in _BF[key].items()}})
    w = {"centroid": 1.0, "bandwidth": .5, "decay_ms": 1.2, "pitch": .8 if cls == "kick" else 0.0, "flatness": .6, "click": .3}
    def d(e):
        s = 0.0
        for kk, wt in w.items():
            a, b = e["b_" + kk], target[kk]
            s += wt * (np.log((a + 1) / (b + 1)) if kk in ("centroid", "bandwidth", "decay_ms", "pitch") else (a - b) * 3) ** 2
        return s
    return sorted(out, key=d)[:k]

def match(target, kind, k=5, weights=None):
    idx = [e for e in index() if e["kind"] == kind]
    w = {"centroid": 1.0, "bandwidth": .6, "decay_ms": 1.0, "pitch": .8 if kind == "kick" else 0.0, "flatness": .5, "click": .5, **(weights or {})}
    def d(e):
        s = 0.0
        for key, wt in w.items():
            if not wt: continue
            a, b = e[key], target[key]
            s += wt * (np.log((a + 1) / (b + 1)) if key in ("centroid", "bandwidth", "decay_ms", "pitch") else (a - b) * 3) ** 2
        return s
    return sorted(idx, key=d)[:k]
