"""P124 (2026-11-01): «кач» as a choice you can listen to. Three feels for the SAME pattern, kick and clap/snare always on the grid:
  grid  - on the grid, only the accent shape (strong beats louder);
  ref   - micro-timing and accents learned from a real reference track (groove.from_ref: hats / perc / bass get the reference's feel);
  swing - drum-machine swing: every odd 16th delayed by (2p-1) of a 16th (MPC 50 % = straight, 54-62 % = house/hip-hop pocket, 66 % = triplet).
Reason: random jitter is not groove (Миша: «зрозумій що таке кач»; microtiming itself has a small effect in the research) - where the hits sit relative to the
kick and the accent/syncopation pattern matter. Use feel_time() / feel_vel() for each hit and A/B the feels with groove_ab.py.
    feel = Feel("ref", ref="sven_v_th_face_it", seed=1);  t = feel.time(trk, br, st, "hh");  v = feel.vel("hh", st, 96)"""
import numpy as np
from .groove import from_ref
ON_GRID = ("kick", "clap", "snare")

def swing_shift(st, pct):
    """shift of 16th number `st` (0..15) as a fraction of a 16th. pct = MPC swing % (50 = none). Even steps never move."""
    return (2 * pct / 100 - 1) if int(st) % 2 else 0.0

REFS = {"house": "sven_v_th_face_it", "house2": "mike_morrisey_ollie_bc_d", "deep": "tre01", "organic": "blue_bus", "breaks": "08_king_freak_astrology"}

class Feel:
    def __init__(self, mode="grid", ref="sven_v_th_face_it", swing=60.0, seed=0, amount=1.0):
        assert mode in ("grid", "ref", "swing"), mode
        self.mode, self.swing, self.amount = mode, float(swing), amount; self.rng = np.random.default_rng(seed)
        self.g = from_ref(ref, self.rng, amount) if mode == "ref" else None
    def shift16(self, cls, st):
        """timing shift of a hit in fractions of a 16th"""
        if cls in ON_GRID or self.mode == "grid": return 0.0
        if self.mode == "swing": return swing_shift(st, self.swing)
        return float(self.g.offset(cls if cls in ("kick", "hh", "perc") else ("perc" if cls != "bass" else "hh"), st))
    def time(self, trk, br, st, cls):
        return br * trk.BAR + (st + self.shift16(cls, st)) * trk.S16
    def vel(self, cls, st, base=96):
        """velocity: reference accents in ref mode, a simple strong/weak shape otherwise"""
        if self.mode == "ref":
            c = cls if cls in ("kick", "hh", "perc") else ("perc" if cls != "bass" else "hh")
            return int(np.clip(base * (.45 + .55 * self.g.vel(c, st, 1.0)), 1, 127))
        w = {0: 1.0, 8: .95, 4: .9, 12: .9}.get(int(st) % 16, .78 if int(st) % 2 == 0 else .62)
        return int(np.clip(base * (.55 + .45 * w), 1, 127))
