"""Genre sound palettes: which real samples a genre is built from, chosen once here instead of per track.
Learned the hard way (Gemini review of «Тепло рук», 2026-10-17): techno-pack kicks/hats and synthesised congas
inside organic house read as cheap and «из 90-х». Use real hand percussion and soft acoustic-ish drums there."""
import glob, os
import numpy as np
from .assets import ASSETS, VSCO, WA
from .core import SR, load_sample, pb

MR_KITS = os.path.join(ASSETS, "musicradar", "drums", "musicradar-drum-samples", "Drum Kits")
VPERC = os.path.join(VSCO, "Percussion")

def _vs(prefix):
    """VSCO percussion group as {velocity_layer: [round robins]} (v1 soft .. v3 loud)"""
    out = {}
    for f in sorted(glob.glob(os.path.join(VPERC, prefix + "*.wav"))):
        v = int(f.split("_v")[1][0]) if "_v" in f else 1
        out.setdefault(v, []).append(load_sample(f, 1.2, fade_ms=30))
    return out

class Layered:
    """velocity-layered, round-robin one-shot: pick(vel 0..1) -> sample"""
    def __init__(self, layers, rng):
        self.l = layers; self.keys = sorted(layers); self.rng = rng
    def pick(self, vel):
        k = self.keys[min(len(self.keys) - 1, int(vel * len(self.keys)))]; rr = self.l[k]
        return rr[int(self.rng.integers(len(rr)))]

def soft_kick(rng=None):
    """round organic-house kick: W.A. body, click softened, plus a little acoustic kick for the wooden knock"""
    from pedalboard import Pedalboard, HighpassFilter, LowpassFilter
    body = load_sample(os.path.join(WA, "Kicks", "WATS_Kick_05.wav"), .26)
    body = pb(Pedalboard([HighpassFilter(52), LowpassFilter(1600)]), body); a = int(.004 * SR); body[:a] *= np.linspace(.3, 1, a)[:, None]
    wood = pb(Pedalboard([HighpassFilter(90), LowpassFilter(3500)]), load_sample(os.path.join(MR_KITS, "Kit 3 - Acoustic", "CyCdh_K3Kick-02.wav"), .2))
    n = max(len(body), len(wood)); k = np.zeros((n, 2), np.float32); k[:len(body)] += body; k[:len(wood)] += .22 * wood
    return k / np.abs(k).max()

def organic(rng):
    """palette for organic / afro / deep house"""
    from pedalboard import Pedalboard, HighpassFilter, LowpassFilter
    hats = [pb(Pedalboard([HighpassFilter(500), LowpassFilter(9000)]), load_sample(f, .15))
            for f in sorted(glob.glob(os.path.join(MR_KITS, "Kit 3 - Acoustic", "CyCdh_K3ClHat-0*.wav")))]
    return {"kick": soft_kick(rng), "hats": hats,
            "conga": Layered(_vs("Conga-HitN"), rng), "quinto": Layered(_vs("Quinto-HitN"), rng), "tumba": Layered(_vs("Tumba-HitN"), rng),
            "conga_tap": Layered({**_vs("Conga-Tap1"), **{2: _vs("Quinto-Tap1").get(1, [])}}, rng), "tumba_tap": Layered(_vs("Tumba-Tap1"), rng),
            "shaker": Layered(_vs("Tamb1-Shake"), rng), "tamb": Layered(_vs("Tamb1-Hit"), rng), "claves": Layered(_vs("Claves1_Hit"), rng),
            "guiro": Layered(_vs("Guiro-Hit"), rng), "cowbell": Layered(_vs("Cowbell1_Hit"), rng),
            "log_hi": Layered(_vs("LogDrumHi"), rng), "log_lo": Layered(_vs("LogDrumLo"), rng)}

def techno(rng):
    """palette for techno: W.A. Production packs"""
    w = lambda r, s=None: load_sample(os.path.join(WA, r), s)
    return {"kick": w("Kicks/WATE_Kick_07.wav", .32), "hats": [w(f"Cymbals/WATS_Closed_HiHat_{i:02d}.wav", .12) for i in (2, 5, 8)],
            "open": w("Cymbals/WATS_Open_HiHat_04.wav", .3), "ride": w("Cymbals/WATE_Ride_02.wav", .9),
            "perc": [w(f"Percussion/WART_Percussion_{i}.wav", .25) for i in (4, 9)]}
