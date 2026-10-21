"""Track: bar grid, sections, layer bus with RMS-relative levels, filters and the final bus write."""
import json
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, butter, sosfiltfilt

SR = 44100

def pb(board, x, sr=SR):
    """run a pedalboard over an (n, 2) buffer"""
    return board(x.T.copy(), sr).T.astype(np.float32)

def mono2(x):
    return np.stack([x, x], 1).astype(np.float32)

def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2))) + 1e-9

def fade(x, ms=8, sr=SR):
    k = min(len(x) // 2, int(sr * ms / 1000)); x = x.copy()
    if k > 0: x[-k:] *= np.linspace(1, 0, k)[:, None] if x.ndim == 2 else np.linspace(1, 0, k)
    return x

def load_sample(path, max_s=None, sr=SR, fade_ms=15):
    """stereo float32, peak-normalised, optionally trimmed to max_s with a fade"""
    a, s = sf.read(path, dtype="float32", always_2d=True)
    if s != sr: a = resample_poly(a, sr, s, axis=0).astype(np.float32)
    a = np.repeat(a, 2, 1)[:, :2] if a.shape[1] == 1 else a[:, :2]
    a = a / (np.abs(a).max() + 1e-9)
    return fade(a[:int(max_s * sr)], fade_ms) if max_s else a

def sat(x, drive_db=6.0, os_=4):
    """tanh saturation at 4x rate, output RMS matched to input"""
    g = 10 ** (drive_db / 20); up = resample_poly(x, os_, 1, axis=0)
    y = resample_poly(np.tanh(up * g) / np.tanh(g), 1, os_, axis=0)[:len(x)].astype(np.float32)
    return (y * (rms(x) / rms(y))).astype(np.float32)

def sweep(x, cuts, c, kind=None, sr=SR):
    """click-free filter movement: crossfade copies filtered at `cuts` along curve c (n,1) in 0..1"""
    from pedalboard import Pedalboard, LowpassFilter
    kind = kind or LowpassFilter
    cps = [pb(Pedalboard([kind(f)]), x, sr) for f in cuts]
    pos = np.clip(np.asarray(c)[:, 0], 0, 1) * (len(cps) - 1); out = np.zeros_like(x)
    for i, cp in enumerate(cps): out += cp * np.clip(1 - np.abs(pos - i), 0, 1)[:, None]
    return out

# RMS of each role relative to the kick, dB. A starting point; a score can override with META["roles"] or level=.
ROLE_DB = {"kick": 0, "bass": -2, "sub": -3, "rumble": -9, "snare": -7, "clap": -9, "rim": -14, "hats": -15, "shaker": -18,
           "open": -17, "ride": -19, "perc": -14, "tom": -13, "pad": -11, "keys": -9, "chords": -10, "lead": -9, "pluck": -12,
           "strings": -10, "arp": -13, "fx": -20, "texture": -24, "voice": -6, "voice_bg": -14}

class Track:
    """Grid + sections + mix bus. Sections: list of (start_bar, end_bar, name, {layer: level}); add "_break": 1
    to a section's dict to tell the checks that it is meant to be quieter."""
    def __init__(self, bpm, bars, seed=0, tail_s=3.0, sr=SR, swing=0.0, humanize_s=0.0015):
        self.bpm, self.bars, self.sr = float(bpm), int(bars), sr
        self.BAR = 240 / self.bpm; self.S16 = self.BAR / 16; self.BEAT = int(60 / self.bpm * sr)
        self.N = int((self.bars * self.BAR + tail_s) * sr); self.rng = np.random.default_rng(seed)
        self.swing, self.humanize_s = swing, humanize_s
        self.mix = np.zeros((self.N, 2), np.float32); self.ref = None; self.tl = []; self.voice = []; self.layers = {}
        self.tt = np.arange(self.N, dtype=np.float32) / sr; self.roles = {}; self.notes = {}
    # ---- grid ----
    def t(self, br, st, swing=None):
        """time of 16th step st in bar br, with swing on odd steps and a little timing noise"""
        sw = self.swing if swing is None else swing
        return br * self.BAR + st * self.S16 + (sw * self.S16 if st % 2 else 0) + self.rng.normal(0, self.humanize_s)
    def i(self, br):
        return int(br * self.BAR * self.sr)
    def buf(self):
        return np.zeros((self.N, 2), np.float32)
    def place(self, buf, smp, t, g=1.0, pan=0.0):
        i = int(round(t * self.sr))
        if i < 0 or i >= len(buf): return
        smp = smp if smp.ndim == 2 else mono2(smp); n = min(len(smp), len(buf) - i)
        buf[i:i + n, 0] += smp[:n, 0] * g * np.sqrt(1 - pan); buf[i:i + n, 1] += smp[:n, 1] * g * np.sqrt(1 + pan)
    # ---- sections / envelopes ----
    def sections(self, tl):
        self.tl = tl; return self
    def sec(self, br):
        for s in self.tl:
            if s[0] <= br < s[1]: return s
        return self.tl[-1]
    def curve(self, vals, smooth_bars=1, step=None):
        """per-bar values -> per-sample curve. step=True (or Track.step_env): hard switches exactly on bar lines with a
        10 ms ramp, no fades (Стас 2026-10-17: fade-in/out transitions sound cheap); otherwise linear between bars."""
        if step if step is not None else getattr(self, "step_env", False):
            e = np.repeat(np.array(list(vals) + [vals[-1]] * 3, np.float32), int(round(self.BAR * self.sr)))
            e = np.pad(e, (0, max(0, self.N - len(e))), "edge")[:self.N]; k = int(.01 * self.sr)
            return np.convolve(e, np.ones(k) / k, "same").astype(np.float32)[:, None]
        e = np.array(list(vals) + [vals[-1]] * 3, np.float32)
        if smooth_bars > 1:
            k = smooth_bars; e = np.convolve(np.pad(e, (k, k), "edge"), np.ones(k) / k, "same")[k:-k]
        return np.interp(self.tt / self.BAR, np.arange(len(e)) + .02, e).astype(np.float32)[:, None]
    def env(self, layer, smooth_bars=1):
        return self.curve([self.sec(b)[3].get(layer, 0.0) for b in range(self.bars)], smooth_bars)
    def one(self):
        return np.ones((self.N, 1), np.float32)
    def lfo(self, bars, phase=0.0):
        return (.5 - .5 * np.cos(2 * np.pi * (self.tt / (bars * self.BAR) + phase))).astype(np.float32)[:, None]
    # ---- bus ----
    def add(self, name, x, level=None, duck=0.0, env=None, smooth_bars=1, release_ms=140, role=None):
        """level is RMS relative to the FIRST layer added (usually the kick); env defaults to the section level.
        level=None takes the role norm (ROLE_DB, role defaults to the layer name)."""
        from autodj.generate.mixbus import sidechain_duck
        x = np.pad(x, ((0, max(0, self.N - len(x))), (0, 0)))[:self.N]; act = x[np.abs(x).max(1) > 1e-4]
        if not len(act): return
        if level is None: level = 10 ** (self.roles.get(role or name, ROLE_DB.get(role or name, -12)) / 20)
        if self.ref is None: self.ref = rms(act)
        x = x * (level * self.ref / rms(act)) * (self.env(name, smooth_bars) if env is None else env)
        if duck: x = sidechain_duck(x, self.sr, self.BEAT, duck, release_ms=release_ms)
        self.mix += x; self.layers[name] = round(20 * np.log10(rms(x[np.abs(x).max(1) > 1e-4]) + 1e-9), 1) if np.any(np.abs(x) > 1e-4) else None
        print("  +", name, flush=True)
    def duck_for_voice(self, vbuf, band=(300, 3500), depth_db=-4.0, attack_ms=15, release_ms=250):
        """make room for the voice: only the voice band of the music dips while the voice sounds (call before add voice)"""
        from scipy.ndimage import maximum_filter1d, uniform_filter1d
        bp = sosfiltfilt(butter(4, list(band), "band", fs=self.sr, output="sos"), self.mix, axis=0).astype(np.float32)
        e = np.abs(vbuf).max(1); e = maximum_filter1d(e, int(self.sr * release_ms / 1000)); e = uniform_filter1d(e, int(self.sr * attack_ms / 1000))
        e = np.clip(e / (np.percentile(e[e > 1e-4], 90) if np.any(e > 1e-4) else 1), 0, 1)
        g = 1 - (1 - 10 ** (depth_db / 20)) * e
        self.mix[:] = self.mix - bp + bp * g[:, None]
    def focus(self, buf, depth_db=-4.0, band=None, attack_ms=10, release_ms=200):
        """Make one layer THE focus of the moment (Gemini/Стас: «все слои борются, каша»): while `buf` sounds, the rest
        of the mix gives way in that layer's own band. Call after the supporting layers are added, before adding `buf`.
        band=None -> one octave around the focus layer's spectral centroid."""
        if band is None:
            m = buf.mean(1); B = 2048; blk = m[:len(m) // B * B].reshape(-1, B)
            blk = blk[np.sqrt((blk ** 2).mean(1)) > 1e-4][: int(30 * self.sr / B)]   # whole active blocks: dropping single
            if not len(blk): return                                                 # samples tears the wave into clicks
            P = (np.abs(np.fft.rfft(blk * np.hanning(B), axis=1)) ** 2).sum(0); f = np.fft.rfftfreq(B, 1 / self.sr)
            c = float((f * P).sum() / (P.sum() + 1e-12)); band = (max(150.0, c / 2), min(9000.0, c * 2))
        self.duck_for_voice(buf, band=band, depth_db=depth_db, attack_ms=attack_ms, release_ms=release_ms)
    def mono_low(self, cut=120):
        lo = sosfiltfilt(butter(8, cut / (self.sr / 2), "low", output="sos"), self.mix, axis=0).astype(np.float32)
        self.mix[:] = (self.mix - lo) + lo.mean(1, keepdims=True)
    def log_notes(self, name, events):
        """register a tonal layer's notes (t, midi, vel, dur) for the clash check"""
        self.notes.setdefault(name, []).extend(events)
    def log_voice(self, t, label):
        self.voice.append([round(float(t), 2), label])
    def finish(self, path, fade_s=4.0, meta=None):
        m = self.mix * (.5 / (np.abs(self.mix).max() + 1e-9)); n = int(fade_s * self.sr)
        m[-n:] *= np.linspace(1, 0, n)[:, None]
        assert np.isfinite(m).all(), "NaN/inf in the mix"
        sf.write(path, m, self.sr, subtype="FLOAT")
        plan = [[a, b, nm, int(bool(lv.get("_break")))] for a, b, nm, lv in self.tl]
        from .harmony import clashes
        def audible(name, evs):                                    # notes of a layer muted by its section level do not clash
            if not any(name in lv for _, _, _, lv in self.tl): return evs
            return [e for e in evs if self.sec(int(e[0] / self.BAR))[3].get(name, 0) > .05]
        notes = {k: audible(k, v) for k, v in self.notes.items()}
        ratio, top = clashes(notes, self.S16, min_len_s=self.S16 * 1.5) if notes else (0.0, [])
        info = {"bpm": self.bpm, "bars": self.bars, "plan": plan, "voice": self.voice, "layers_db": self.layers,
                "clash_ratio": round(ratio, 3), "clash_pairs": [[f"{a}+{b}", c] for (a, b), c in top], **(meta or {})}
        json.dump(info, open(path.rsplit(".", 1)[0] + ".json", "w"), ensure_ascii=False)
        return info
