"""P113 (Стас 2026-10-23, «Agentic Audio» idea 4): one macro energy curve for the whole track, 0..1, that several mix
controls follow at once (filter opening, stereo width, reverb send, kick strength, LFO speed), each strictly inside the
bounds the score gives. Nothing here runs unless a score calls it: old scores sound exactly the same.
    e = energy.curve(trk, [(0, .2), (64, .5), (112, 1.0), (176, .3)])     # or energy.from_sections(trk) (section key "energy")
    x = energy.filter_open(x, e, 800, 6000); x = energy.width(x, e, .9, 1.2); x = energy.reverb_send(x, e, .05, .25)
    trk.add("kick", k, 1.0, env=energy.gain(e, -1.0, .8))"""
import numpy as np
from pedalboard import Pedalboard, Reverb
from .core import pb, sweep

def curve(trk, points):
    """[(bar, value)] -> per-sample (N, 1), linear between points, clipped to 0..1"""
    xs, ys = zip(*sorted(points)); return np.clip(np.interp(trk.tt / trk.BAR, xs, ys), 0, 1).astype(np.float32)[:, None]

def from_sections(trk, default=0.0, smooth_bars=4):
    """section level dicts may carry "energy": 0..1; smoothed over a few bars (macro, not a switch)"""
    return np.clip(trk.curve([trk.sec(b)[3].get("energy", default) for b in range(trk.bars)], smooth_bars, step=False), 0, 1)

def span(e, lo, hi):
    return lo + (hi - lo) * np.clip(e, 0, 1)

def filter_open(x, e, lo_hz, hi_hz, steps=4):
    """low-pass between lo_hz (e=0) and hi_hz (e=1); never outside"""
    cuts = list(np.geomspace(lo_hz, hi_hz, steps)); return sweep(x, cuts, np.clip(e[:len(x)], 0, 1))

def width(x, e, lo=.9, hi=1.2):
    """mid/side width factor between lo and hi"""
    m, s = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2; w = span(e[:len(x), 0], lo, hi)
    return np.stack([m + s * w, m - s * w], 1).astype(np.float32)

def reverb_send(x, e, lo=.05, hi=.3, room=.8):
    """dry + reverb return, the send level between lo and hi"""
    wet = pb(Pedalboard([Reverb(room_size=room, wet_level=1.0, dry_level=0.0)]), x)
    return (x + wet * span(e[:len(x)], lo, hi)).astype(np.float32)

def gain(e, lo_db=-1.0, hi_db=.8):
    """an env multiplier for trk.add: e.g. the kick a little softer at low energy, a little stronger at the peak"""
    return (10 ** (span(e, lo_db, hi_db) / 20)).astype(np.float32)

def lfo(trk, e, slow_bars=16, fast_bars=4):
    """0..1 LFO whose period glides from slow_bars (e=0) to fast_bars (e=1), phase-continuous"""
    period = span(e[:, 0], slow_bars, fast_bars) * trk.BAR; ph = np.cumsum(1.0 / period) / trk.sr
    return (.5 - .5 * np.cos(2 * np.pi * ph)).astype(np.float32)[:, None]
