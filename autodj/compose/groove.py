"""Human groove from real drummers (Groove MIDI Dataset library, see grooves_build.py).

Two ways to use it:
  g = Groove("funk", trk.rng)
  1) feel: put YOUR own pattern on the grid and let the drummers' micro-timing + accents shape it
        trk.place(buf, hat, g.t(trk, br, st, "hh"), g.vel("hh", st) * 1.0)
  2) real parts: take whole bars/phrases a drummer actually played (different every track)
        for st, v, off in g.bar()["hh"]: ...        g.phrase(4), g.fill()
Electronic dance music keeps the kick on the grid (feel amount 0 for "kick"), hats/perc/snare get the feel.
Offsets are fractions of a 16th, so they scale with tempo."""
import json, os
import numpy as np
from .assets import ASSETS

_LIB = None
def library():
    global _LIB
    if _LIB is None: _LIB = json.load(open(os.path.join(ASSETS, "grooves", "grooves.json")))
    return _LIB

STYLES = ("funk", "soul", "hiphop", "pop", "rock", "jazz", "neworleans", "dance", "latin", "afrocuban", "reggae", "country",
          "gospel", "punk", "afrobeat", "blues", "middleeastern", "highlife")
CLASS_FALLBACK = {"shaker": "hh", "tamb": "hh", "perc": "rim", "clap": "snare", "conga": "tom", "cowbell": "rim"}

class Groove:
    def __init__(self, style="funk", rng=None, amount=1.0, vel_depth=1.0, kick_on_grid=True):
        self.style = style; self.d = library()[style]; self.rng = rng or np.random.default_rng()
        self.amount, self.vel_depth, self.kick_on_grid = amount, vel_depth, kick_on_grid
        self.tpl = self.d["template"]
    def _row(self, cls, st):
        cls = CLASS_FALLBACK.get(cls, cls)
        r = self.tpl.get(f"{cls}:{st % 16}") or self.tpl.get(f"hh:{st % 16}")
        return r or [0.0, 0.01, .6, .1, 0]
    def offset(self, cls, st, amount=None):
        """sampled micro-offset in 16ths (drummer mean + their spread, clipped)"""
        if cls == "kick" and self.kick_on_grid: return 0.0
        mu, sd, *_ = self._row(cls, st); a = self.amount if amount is None else amount
        return float(np.clip(self.rng.normal(mu, sd * .6), -.3, .3)) * a
    def vel(self, cls, st, base=1.0):
        """accent shape from the drummers, normalised so the loudest step of that class is ~1"""
        cls2 = CLASS_FALLBACK.get(cls, cls); vs = [self._row(cls2, s)[2] for s in range(16)]; top = max(vs) or 1
        _, _, mv, sv, _ = self._row(cls2, st); v = np.clip(self.rng.normal(mv, sv * .5), .05, 1) / top
        return float(base * (1 - self.vel_depth + self.vel_depth * v))
    def t(self, trk, br, st, cls, amount=None):
        return br * trk.BAR + st * trk.S16 + self.offset(cls, st, amount) * trk.S16
    def bar(self, need=("kick", "hh")):
        """a real bar from this style that has all classes in `need`: {class: [(step, vel, off), ...]}"""
        bars = [b for b in self.d["bars"] if all(c in b for c in need)] or self.d["bars"]
        return bars[int(self.rng.integers(len(bars)))]
    def phrase(self, n=4, need=("kick",)):
        ph = [p for p in self.d["phrases"] if len(p) >= n and all(any(c in b for b in p) for c in need)] or self.d["phrases"]
        p = ph[int(self.rng.integers(len(ph)))]; k = int(self.rng.integers(0, len(p) - n + 1)) if len(p) > n else 0
        return p[k:k + n]
    def fill(self):
        fl = self.d["fills"] or library()["funk"]["fills"]; return fl[int(self.rng.integers(len(fl)))]
    def play(self, trk, buf, br, bar, kit, gain=None, classes=None, amount=None):
        """place a real bar with a kit {class: sample or [samples]}; vel -> gain, off -> timing"""
        for c, hits in bar.items():
            if (classes and c not in classes) or c not in kit: continue
            smp = kit[c]
            for st, v, off in hits:
                s = smp[int(self.rng.integers(len(smp)))] if isinstance(smp, list) else smp
                a = self.amount if amount is None else amount
                tt = br * trk.BAR + st * trk.S16 + (0 if (c == "kick" and self.kick_on_grid) else off * trk.S16 * a)
                trk.place(buf, s, tt, (gain or {}).get(c, 1.0) * (.25 + .75 * v))

def from_ref(name, rng=None, amount=1.0):
    """Groove learned from a reference track (autodj.compose.learn): micro-timing relative to the beat, accents and
    how often each 16th is played, per class (kick / hh / perc). Exposes .occupancy(cls, st) and .bass_occupancy(st)."""
    prof = json.load(open(os.path.join(ASSETS, "grooves", "refs", f"{name}.json")))
    g = Groove.__new__(Groove); g.rng = rng or np.random.default_rng(); g.amount, g.vel_depth, g.kick_on_grid = amount, 1.0, True
    g.style = "ref:" + name; g.prof = prof; tpl = {}
    for cls, t in prof["classes"].items():
        base = np.median([v[0] for s, v in t.items() if int(s) % 4 == 0] or [0])     # beat-tracker phase -> relative feel
        top = max([v[2] for v in t.values()] or [1])
        for s, (mu, sd, vel, occ) in t.items():
            tpl[f"{cls}:{s}"] = [round(mu - base, 3), min(sd, .05), vel / top, .08, occ]
        if cls == "perc":
            for s, row in list(tpl.items()):
                if s.startswith("perc:"): tpl["rim:" + s[5:]] = row
    g.tpl = tpl; g.d = {"template": tpl, "bars": [], "fills": [], "phrases": []}
    g.occupancy = lambda cls, st: g.tpl.get(f"{cls}:{st % 16}", [0, 0, 0, 0, 0])[4]
    g.bass_occupancy = lambda st: prof["bass"]["occupancy"].get(str(st % 16), 0.0)
    return g
