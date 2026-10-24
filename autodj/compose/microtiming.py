"""P116 (2026-10-24): living micro-timing. Instead of independent white noise per note: one slow correlated (1/f-like) ensemble drift
on the absolute time axis + a per-role «manner» (snare a little late, hats swung, keys laid back), velocity accents (strong beats
louder, weak softer). Every shift is clipped to ±25 ms. Off unless a score calls it; deterministic by seed.
    mt = microtiming.Ensemble(trk, seed); t = mt.time(br, st, "snare"); v = microtiming.accent(st, 96)"""
import numpy as np
ROLE_MS = {"kick": 0.0, "bass": 2.0, "snare": 6.0, "clap": 5.0, "hats": 3.0, "perc": 4.0, "keys": 8.0, "rhodes": 9.0, "pluck": 4.0, "lead": 5.0, "pad": 0.0}
ROLE_SWING = {"hats": .55, "perc": .45, "keys": .3, "rhodes": .35}
LIMIT_MS = 25.0

def pink(n, seed=0, beta=1.0):
    """1/f^beta noise, zero mean, unit std"""
    rng = np.random.default_rng(seed); X = np.fft.rfft(rng.normal(0, 1, n)); f = np.fft.rfftfreq(n); f[0] = f[1] if n > 1 else 1
    y = np.fft.irfft(X / f ** (beta / 2), n); y = y - y.mean(); s = y.std(); return y / s if s > 0 else y

class Ensemble:
    def __init__(self, trk, seed=0, drift_ms=6.0, role_jitter_ms=2.5):
        self.trk = trk; nsteps = trk.bars * 16 + 16
        self.drift = pink(nsteps, seed) * drift_ms                              # shared by every player
        self.jit = {r: pink(nsteps, seed + 97 + i, beta=.6) * role_jitter_ms for i, r in enumerate(ROLE_MS)}
    def offset_ms(self, br, st, role):
        i = int(br * 16 + st); sw = ROLE_SWING.get(role, 0.0) * (self.trk.S16 * 1000 * .18 if int(st) % 2 else 0)
        j = self.jit.get(role); ms = self.drift[i] + ROLE_MS.get(role, 0.0) + (j[i] if j is not None else 0) + sw
        return float(np.clip(ms, -LIMIT_MS, LIMIT_MS))
    def time(self, br, st, role):
        return br * self.trk.BAR + st * self.trk.S16 + self.offset_ms(br, st, role) / 1000.0

def accent(st, base=96, depth=.28):
    """strong beats louder, weak 16ths softer"""
    w = {0: 1.0, 8: .92, 4: .85, 12: .85}.get(int(st) % 16, .72 if int(st) % 2 == 0 else .6)
    return int(np.clip(base * (1 - depth + depth * w / 1.0), 1, 127))
