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

PUSH_LIMIT_MS = 40.0
class Ensemble:
    """version 1 (default, unchanged): metric swing, role flavours and noise are summed and clipped together to ±25 ms (the old behaviour of every score).
    version 2 (P163, 2026-11-21): the two things are SEPARATE. swing = metric swing, a fraction of a 16th on the odd steps (0.16 = 16 % of a 16th), exact and
    never clipped (on 100 and 130 BPM it is the same fraction of the step); micro = the live deviations (shared drift, role manner, jitter), clipped to ±25 ms;
    push = {role: ms} an on-purpose lead (negative = before the grid) or lag per role (a profile's choice, clipped to ±40 ms), never noise; the anchor role
    (kick) sits exactly on the grid: no swing, no micro, no push. Every call is logged in .log for the rhythm report (rhythm.timing)."""
    def __init__(self, trk, seed=0, drift_ms=6.0, role_jitter_ms=2.5, version=1, swing=None, push=None, anchor="kick"):
        self.version = int(version); self.push = dict(push or {}); self.anchor = anchor; self.log = []; trk.microtiming = self
        self.trk = trk; nsteps = trk.bars * 16 + 16; self.swing = float(getattr(trk, "swing", 0.0) or 0.0)    # P150: the track's own swing (a fraction of a 16th on the odd steps) now counts
        self.sw2 = float(self.swing if swing is None else swing)             # version 2: the metric swing (fraction of a 16th), exact
        self.drift = pink(nsteps, seed) * drift_ms                              # shared by every player
        self.jit = {r: pink(nsteps, seed + 97 + i, beta=.6) * role_jitter_ms for i, r in enumerate(ROLE_MS)}
    def offset_ms(self, br, st, role):
        if self.version >= 2: return self._offset_v2(br, st, role)
        i = int(br * 16 + st); sw = ROLE_SWING.get(role, 0.0) * (self.trk.S16 * 1000 * .18 if int(st) % 2 else 0)
        j = self.jit.get(role); ms = self.drift[i] + ROLE_MS.get(role, 0.0) + (j[i] if j is not None else 0) + sw + (self.swing * self.trk.S16 * 1000 if int(st) % 2 else 0)
        return float(np.clip(ms, -LIMIT_MS, LIMIT_MS))
    def _offset_v2(self, br, st, role):
        if role == self.anchor: return 0.0
        i = int(br * 16 + st); j = self.jit.get(role)
        micro = float(np.clip(self.drift[i] + ROLE_MS.get(role, 0.0) + (j[i] if j is not None else 0.0), -LIMIT_MS, LIMIT_MS))
        metric = self.sw2 * self.trk.S16 * 1000 if int(st) % 2 else 0.0
        return float(metric + micro + np.clip(self.push.get(role, 0.0), -PUSH_LIMIT_MS, PUSH_LIMIT_MS))
    def time(self, br, st, role):
        ms = self.offset_ms(br, st, role); self.log.append((role, int(br), int(st), round(float(ms), 3)))
        return br * self.trk.BAR + st * self.trk.S16 + ms / 1000.0

def accent(st, base=96, depth=.28):
    """strong beats louder, weak 16ths softer"""
    w = {0: 1.0, 8: .92, 4: .85, 12: .85}.get(int(st) % 16, .72 if int(st) % 2 == 0 else .6)
    return int(np.clip(base * (1 - depth + depth * w / 1.0), 1, 127))
