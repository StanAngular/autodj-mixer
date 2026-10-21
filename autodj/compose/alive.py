"""«Оживление» (P108, approved by Стас): what turns a clean render into a played, recorded sound.
- drift(): the pitch wanders 3-7 cents (slow random wander + a little wow), like tape / a real instrument;
  implemented as a modulated delay line, so nothing is re-synthesised;
- mechanics(): a very quiet key/finger noise at every note-on and a softer one at note-off (felt thump + a
  click band), -30 dB under the instrument by default;
- Room: ONE shared space for all melodic layers of a track (the same impulse response), so they sound recorded
  in one place instead of each in its own reverb. Layers send into the room; the room is added once."""
import numpy as np
from scipy.signal import butter, sosfiltfilt, oaconvolve
from .core import rms

def drift(x, sr=44100, cents=5.0, rate_hz=.35, seed=0):
    """pitch wander with a peak of about `cents` (random slow walk 60% + sine wow 40%), stereo kept"""
    rng = np.random.default_rng(seed); n = len(x); t = np.arange(n) / sr
    k = max(1, int(sr / (rate_hz * 4)))                                   # smooth noise -> slow walk
    walk = np.interp(np.arange(n), np.arange(0, n + k, k), rng.standard_normal(n // k + 2)[:len(np.arange(0, n + k, k))])
    walk = np.convolve(walk, np.ones(k) / k, "same"); walk /= (np.abs(walk).max() + 1e-9)
    ph = rng.uniform(0, 2 * np.pi); wav = np.sin(2 * np.pi * rate_hz * t + ph)
    dev = (.6 * walk + .4 * wav)                                          # -1..1
    # pitch deviation (cents) = 1200/ln2 * d(delay)/dt  ->  delay = integral of deviation
    ratio = 2 ** (cents * dev / 1200) - 1
    delay = np.cumsum(-ratio) ; delay -= delay.min(); delay = np.minimum(delay, sr * .05)
    pos = np.clip(np.arange(n) - delay, 0, n - 1)
    return np.stack([np.interp(pos, np.arange(n), x[:, c]) for c in range(x.shape[1])], 1).astype(np.float32)

def mechanics(events, total_s, sr=44100, level_db=-30.0, seed=0, ref=None):
    """key noise for events (t, midi, vel, dur): a felt thump (120-400 Hz, 15 ms) + a click band (2-5 kHz, 4 ms)
    at note-on, half as loud at note-off. Scaled to `level_db` under `ref` (the instrument audio) if given."""
    rng = np.random.default_rng(seed); n = int(total_s * sr); out = np.zeros((n, 2), np.float32)
    def burst(ms, lo, hi, g):
        k = int(ms * sr / 1000); z = rng.standard_normal(k * 3)
        z = sosfiltfilt(butter(2, [lo, hi], "band", fs=sr, output="sos"), z)[:k] * np.exp(-np.arange(k) / (k / 4))
        return (z / (np.abs(z).max() + 1e-9) * g).astype(np.float32)
    for t, m, v, d in events:
        for when, g in ((t, (v / 127) ** 1.5), (t + d, .5 * (v / 127) ** 1.5)):
            i = int(when * sr)
            if i < 0 or i >= n: continue
            y = burst(15, 120, 400, g) + np.pad(burst(4, 2000, 5000, .35 * g), (0, int(.011 * sr) + 1))[:int(.015 * sr)]
            k = min(len(y), n - i); pan = rng.uniform(-.2, .2)
            out[i:i + k, 0] += y[:k] * (1 - pan); out[i:i + k, 1] += y[:k] * (1 + pan)
    if ref is not None and rms(out) > 0: out *= rms(ref) / rms(out) * 10 ** (level_db / 20)
    return out

def room_ir(sr=44100, decay_s=1.4, predelay_ms=12, seed=0, lo=250, hi=7000, early=7):
    """one impulse response per track: a few early reflections + decorrelated exponentially decaying noise"""
    rng = np.random.default_rng(seed); n = int((decay_s * 1.3 + predelay_ms / 1000) * sr); ir = np.zeros((n, 2), np.float32)
    p = int(predelay_ms * sr / 1000)
    for _ in range(early):
        i = p + int(rng.uniform(1, 40) * sr / 1000); ir[i, 0] += rng.uniform(.2, .6); ir[i + int(rng.uniform(0, 3) * sr / 1000), 1] += rng.uniform(.2, .6)
    tail = rng.standard_normal((n - p, 2)) * np.exp(-6.9 * np.arange(n - p) / (decay_s * sr))[:, None]
    ir[p:] += sosfiltfilt(butter(2, [lo, hi], "band", fs=sr, output="sos"), tail, axis=0).astype(np.float32) * .5
    return ir / (np.sqrt((ir ** 2).sum(0, keepdims=True)) + 1e-9)

class Room:
    """room = Room(trk); room.send(layer_audio, .25); ...; trk.add("room", room.render(), level=...)"""
    def __init__(self, trk, decay_s=None, seed=None):
        r = np.random.default_rng(trk.rng.integers(1 << 30) if seed is None else seed)
        self.trk = trk; self.bus = trk.buf(); self.ir = room_ir(trk.sr, decay_s or float(r.uniform(1.1, 1.8)), float(r.uniform(8, 20)), int(r.integers(1 << 30)))
    def send(self, x, amount=.25):
        x = np.pad(x, ((0, max(0, len(self.bus) - len(x))), (0, 0)))[:len(self.bus)]; self.bus += x * amount; return x
    def render(self):
        y = np.stack([oaconvolve(self.bus[:, c], self.ir[:, c])[:len(self.bus)] for c in range(2)], 1).astype(np.float32)
        return y * (rms(self.bus) / (rms(y) + 1e-12))
