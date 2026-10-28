"""P122 (2026-10-28, Стас's sound TZ, stage 6): three listening variants of ONE short fragment, so a choice is made by ear and not by "which is louder".
    python -m autodj.compose.abc track.mp3 START_S DUR_S OUTDIR [name]
A  baseline : the fragment as rendered (reference);
B  warmth   : gentle asymmetric tape-style saturation, slower/softer transients (low-ratio slow-attack compressor), air shelf -2 dB above 6 kHz;
C  space    : side boost above 400 Hz (static width x1.5) + a dark hall tail (pre-delay 25 ms, low-passed) — material and level unchanged.
Loudness of B and C is matched to A (rms, +-0.3 dB), so any preference is about colour, not level. Writes A/B/C.mp3 + manifest.json with what changed
and the measured differences (rms, crest, centroid, width). Pure post-processing of a finished fragment: no re-render, 10-20 s per call."""
import io, json, os, subprocess, sys
import numpy as np, soundfile as sf
from pedalboard import Pedalboard, Compressor, HighShelfFilter, Reverb, Delay, LowpassFilter, HighpassFilter
from .stereo import ms_widen, width_ratio
SR = 44100

def _load(path):
    w = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "wav", "-ac", "2", "-ar", str(SR), "-"], capture_output=True).stdout
    return sf.read(io.BytesIO(w), dtype="float32")[0]

def _rms_db(x): return float(20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12))
def _centroid(x):
    m = x.mean(1)[:SR * 20]; X = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2; f = np.fft.rfftfreq(len(m), 1 / SR); return float((f * X).sum() / (X.sum() + 1e-12))
def _crest(x): return float(20 * np.log10(np.abs(x).max() / (np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12)))

def _mono_low(x, cut=150):
    """the low end stays mono: a stereo reverb tail of broadband content would otherwise re-open the sub (found by the test)"""
    from scipy.signal import butter, sosfiltfilt
    lo = sosfiltfilt(butter(4, cut, "low", fs=SR, output="sos"), x, axis=0).astype(np.float32); return ((x - lo) + lo.mean(1, keepdims=True)).astype(np.float32)

def warmth(x):
    y = np.tanh(1.5 * (x + .05)) - np.tanh(1.5 * .05); y = y / np.tanh(1.5)                       # asymmetric: even harmonics, small
    y = Pedalboard([Compressor(threshold_db=-24, ratio=1.5, attack_ms=40, release_ms=220), HighShelfFilter(6000, gain_db=-2.0)])(y.astype(np.float32).T, SR).T
    return y.astype(np.float32)

def space(x):
    y = ms_widen(x, 1.5, 400, SR)
    tail = Pedalboard([HighpassFilter(250), Delay(.025, 0.0, 1.0), Reverb(room_size=.9, damping=.6, wet_level=1.0, dry_level=0.0, width=1.0), LowpassFilter(4500)])(y.T.astype(np.float32), SR).T
    y = (y + .22 * tail).astype(np.float32)
    return _mono_low(y, 220)

def variants(x, sr=SR):
    """A/B/C of an in-memory fragment (stereo float32): A untouched, B warmth, C space; B and C matched to A's rms, peaks <= 0.89"""
    A = np.asarray(x, np.float32).copy(); ref = _rms_db(A); out = {"A": A}
    for k, f in (("B", warmth), ("C", space)):
        y = f(A); y = y * 10 ** ((ref - _rms_db(y)) / 20); pk = np.abs(y).max()
        out[k] = (y * (.89 / pk) if pk > .89 else y).astype(np.float32)
    return out

def fragments(src, start_s, dur_s, outdir, name="frag"):
    x = _load(src) if isinstance(src, str) else np.asarray(src, np.float32)
    if len(x) < SR: raise ValueError("source shorter than 1 s")
    a0 = int(max(0, start_s) * SR); seg = x[a0:a0 + int(dur_s * SR)]
    if len(seg) < SR or _rms_db(seg) < -70: raise ValueError("fragment is empty or silent")
    os.makedirs(outdir, exist_ok=True); out = variants(seg)
    man = {"name": name, "source": src if isinstance(src, str) else "array", "start_s": start_s, "dur_s": round(len(seg) / SR, 1),
           "what": {"A": "baseline, untouched", "B": "warmth: tape-style saturation + soft slow compressor + air shelf -2 dB > 6 kHz", "C": "space: side x1.5 above 400 Hz + dark hall tail (pre-delay 25 ms), low end unchanged"},
           "measured": {k: {"rms_db": round(_rms_db(v), 1), "crest_db": round(_crest(v), 1), "centroid_hz": round(_centroid(v)), "width_400": round(width_ratio(v, 400, SR), 2)} for k, v in out.items()}}
    for k, v in out.items():
        w = os.path.join(outdir, f"{name}_{k}.wav"); sf.write(w, v, SR); subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", w, "-q:a", "2", os.path.join(outdir, f"{name}_{k}.mp3")], check=True); os.remove(w)
    json.dump(man, open(os.path.join(outdir, f"{name}_manifest.json"), "w"), ensure_ascii=False, indent=1)
    return man

if __name__ == "__main__":
    if len(sys.argv) < 5: sys.exit(__doc__)
    print(json.dumps(fragments(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "frag"), ensure_ascii=False, indent=1))
