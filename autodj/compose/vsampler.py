"""Small multisample player for the VSCO-2 CE library (a headless DecentSampler substitute).
Pitch of every file is measured once (pyin) and cached; notes use the nearest sample, matching dynamic layer,
round-robin rotation, resampling for the pitch offset, and a release fade at note-off."""
import os, re, glob, json, numpy as np, soundfile as sf
from scipy.signal import resample_poly
from .assets import VSCO as ROOT
SR = 44100
INSTR = {"violins": "Strings/Violin Section/susVib", "violins_spic": "Strings/Violin Section/Spic", "violas": "Strings/Viola Section/susvib",
         "violas_spic": "Strings/Viola Section/spic", "cellos": "Strings/Cello Section/susvib", "cellos_spic": "Strings/Cello Section/spic",
         "harp": "Strings/Harp", "piano": "Keys/Upright Nr1"}
def _dyn(name):
    n = name.lower()
    for k, v in (("_pp", 0), ("_mp", 1), ("_mf", 1), ("_f_", 2), ("_f.", 2), ("_v1", 0), ("_v2", 1), ("_v3", 2)):
        if k in n: return v
    return 1
class Sampler:
    def __init__(self, key):
        self.dir = os.path.join(ROOT, INSTR[key]); cache = os.path.join(self.dir, "_pitch.json")
        files = sorted(glob.glob(os.path.join(self.dir, "*.wav")))
        if os.path.exists(cache): pitch = json.load(open(cache))
        else:
            import librosa
            pitch = {}
            for f in files:
                y, sr = librosa.load(f, sr=22050, duration=1.5)
                f0, v, _ = librosa.pyin(y, fmin=30, fmax=2000, sr=sr, frame_length=4096)
                pitch[os.path.basename(f)] = int(round(librosa.hz_to_midi(np.nanmedian(f0[v])))) if np.any(v) else None
            json.dump(pitch, open(cache, "w"))
        self.map = {}
        for f in files:
            m = pitch.get(os.path.basename(f))
            if m is not None: self.map.setdefault(m, {}).setdefault(_dyn(os.path.basename(f)), []).append(f)
        self.keys = sorted(self.map); self.cache = {}; self.rr = 0
    def _cents(self, f, base):
        """measured detune of this sample (cents) so every note lands on A440 (VSCO samples drift +-15 c)"""
        from .tuning import Cache, cents_off
        if not hasattr(self, "_tc"): self._tc = Cache(os.path.join(self.dir, "_cents.json"))
        return self._tc.get(os.path.basename(f), lambda: cents_off(self._load(f), base, start=.12, dur=.8))
    def _load(self, f):
        if f not in self.cache:
            a, sr = sf.read(f, dtype="float32", always_2d=True)
            if sr != SR: a = resample_poly(a, SR, sr, axis=0).astype(np.float32)
            a = np.repeat(a, 2, 1)[:, :2] if a.shape[1] == 1 else a[:, :2]; self.cache[f] = a
        return self.cache[f]
    def note(self, midi, vel, dur, release=0.35):
        base = min(self.keys, key=lambda k: (abs(k - midi), k > midi)); layers = self.map[base]
        want = 0 if vel < 55 else (1 if vel < 95 else 2); lay = min(layers, key=lambda d: abs(d - want))
        fl = layers[lay]; f = fl[self.rr % len(fl)]; self.rr += 1
        a = self._load(f); ratio = 2 ** ((midi - base - self._cents(f, base) / 100) / 12)
        n_out = int((dur + release) * SR); n_in = min(len(a), int(n_out * ratio) + 2)
        src = a[:n_in]; pos = np.arange(n_out) * ratio; pos = pos[pos < len(src) - 1]
        y = np.stack([np.interp(pos, np.arange(len(src)), src[:, c]) for c in range(2)], 1).astype(np.float32)
        k = int(dur * SR); r = int(release * SR)
        if len(y) > k: y[k:k + r] *= np.linspace(1, 0, min(r, len(y) - k))[:, None]; y = y[:k + r]
        a_ = min(len(y), int(.004 * SR)); y[:a_] *= np.linspace(0, 1, a_)[:, None]
        return y * (vel / 127) ** 1.2
    def render(self, events, total_s, release=0.35):
        out = np.zeros((int(total_s * SR) + SR, 2), np.float32)
        for t, m, v, d in events:
            y = self.note(m, v, d, release); i = int(t * SR); n = min(len(y), len(out) - i)
            if n > 0 and i >= 0: out[i:i + n] += y[:n]
        return out[:int(total_s * SR)]
