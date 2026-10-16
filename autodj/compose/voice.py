"""Voice from edge-tts: generate with retries, trim, fit to a grid slot, nudge to a chord tone, quantise words."""
import io, os, subprocess, time
import numpy as np, soundfile as sf
from .assets import EDGE_TTS
from .core import SR, pb, mono2, sat

def tts(text, out, voice="uk-UA-PolinaNeural", rate="+0%", pitch="+0Hz", retries=4):
    env = dict(os.environ, PYTHONPATH=EDGE_TTS)
    for k in range(retries):
        subprocess.run(["python3", "-m", "edge_tts", "--voice", voice, f"--rate={rate}", f"--pitch={pitch}", "--text", text,
                        "--write-media", out], env=env, capture_output=True)
        if os.path.exists(out) and os.path.getsize(out) > 0: return out
        time.sleep(2 + k)
    raise RuntimeError(f"edge-tts failed for {text!r}")

def load(path, thr=.012, sr=SR):
    """mono float32, leading/trailing silence trimmed"""
    w = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "wav", "-"], capture_output=True).stdout
    a = sf.read(io.BytesIO(w), dtype="float32")[0]; nz = np.where(np.abs(a) > thr)[0]
    return a[max(0, nz[0] - 200):nz[-1] + 1] if len(nz) else a

def fit(a, slot_s, fill=.9, sr=SR):
    import librosa
    return librosa.effects.time_stretch(a, rate=len(a) / (slot_s * sr * fill)) if len(a) > slot_s * sr * fill else a

def f0_midi(a, sr=SR):
    import librosa
    f = librosa.pyin(a, fmin=70, fmax=450, sr=sr, frame_length=2048)[0]; f = f[~np.isnan(f)]
    return float(librosa.hz_to_midi(np.median(f))) if len(f) else None

def tune(a, pcs, max_st=2.5, sr=SR):
    """shift the whole word/line so its median pitch lands on the nearest pitch class in pcs (never more than max_st).
    Big shifts make speech quack, so keep max_st small."""
    from pedalboard import Pedalboard, PitchShift
    m = f0_midi(a, sr)
    if m is None: return a, 0.0
    cands = [x for x in range(int(m) - 7, int(m) + 8) if x % 12 in pcs]
    s = float(np.clip(min(cands, key=lambda x: abs(x - m)) - m, -max_st, max_st)) if cands else 0.0
    return (pb(Pedalboard([PitchShift(semitones=s)]), mono2(a), sr)[:, 0] if s else a), s

def quantise(a, grid, top_db=30):
    """snap word onsets to the grid (samples), keeping order; returns the re-timed line"""
    import librosa
    iv = librosa.effects.split(a, top_db=top_db, frame_length=1024, hop_length=256); out = np.zeros(len(a) * 2 + grid * 4, np.float32); prev = 0
    for s, e in iv:
        q = max(int(round(s / grid)) * grid, prev); w = a[s:e].copy(); k = min(len(w), len(out) - q)
        w = w[:k]; f = min(64, k // 2)
        if f: w[:f] *= np.linspace(0, 1, f); w[-f:] *= np.linspace(1, 0, f)
        out[q:q + k] += w; prev = q + k
    return out[:prev + 1]

def chain(a, semitones=0.0, hp=120, lp=6000, drive=4.0, sr=SR):
    """default voice treatment: optional pitch, band-limit (muffled top), gentle comp, saturation. Returns stereo."""
    from pedalboard import Pedalboard, PitchShift, HighpassFilter, LowpassFilter, Compressor
    fx = ([PitchShift(semitones=semitones)] if semitones else []) + [HighpassFilter(hp), LowpassFilter(lp), Compressor(-22, 3, 4, 100)]
    x = pb(Pedalboard(fx), mono2(a / (np.abs(a).max() + 1e-9)), sr)
    return sat(x, drive) if drive else x

def texture(a, rng=None, sr=SR, octave=-12, grains=24, spread_s=1.6, wet=.55):
    """turn a spoken line into an atmospheric texture: octave double, scattered grains after it, big dark reverb.
    The words stay recognisable at the start, then dissolve."""
    from pedalboard import Pedalboard, PitchShift, Reverb, LowpassFilter, HighpassFilter
    rng = rng or np.random.default_rng(0); x = mono2(a / (np.abs(a).max() + 1e-9))
    low = pb(Pedalboard([PitchShift(semitones=octave)]), x, sr)
    out = np.zeros((len(x) + int((spread_s + 3) * sr), 2), np.float32); out[:len(x)] += x + .45 * low[:len(x)]
    for _ in range(grains):
        L = int(rng.uniform(.06, .14) * sr); s = int(rng.integers(0, max(1, len(x) - L))); g = x[s:s + L] * np.hanning(L)[:, None]
        p = rng.uniform(-.8, .8); i = len(x) + int(rng.uniform(0, spread_s) * sr) - L // 2
        out[i:i + L, 0] += g[:, 0] * .35 * np.sqrt(1 - p); out[i:i + L, 1] += g[:, 1] * .35 * np.sqrt(1 + p)
    return pb(Pedalboard([HighpassFilter(150), LowpassFilter(5000), Reverb(room_size=.95, damping=.6, wet_level=wet, dry_level=1 - wet * .6, width=1.)]), out, sr)
