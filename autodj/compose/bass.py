"""Short, punchy house bass (P107 stage 4; Gemini teacher: «бас не гудит, он стреляет вместе с бочкой»).
Rules:
- every note <= 1/8 (2 sixteenths), a rest after every note: the gaps are where the groove lives;
- the kick owns the beats: by default no bass on steps 0/4/8/12 (opt in with `on_kick`), the line sits on the
  off-beats and 16th syncopations around them;
- pitch: the bar's chord root, its octave and fifth; the last note before a chord change may be an approach note
  (a scale step or a semitone into the next root);
- velocity: accents 110/60/90/70 per 16th within the beat, the root after a rest a bit harder;
- ONE rhythm cell per track (drawn from the rng, not from a list), every 4th bar varies only its tail."""
import numpy as np
from .hook import accents

def bass_cell(rng, on_kick=False, onsets=(3, 6)):
    """steps for one bar: syncopated, never two notes on adjacent steps (each note gets its rest)"""
    allowed = [s for s in range(16) if on_kick or s % 4]
    while True:
        k = int(rng.integers(onsets[0], onsets[1] + 1)); st = sorted(rng.choice(allowed, min(k, len(allowed)), replace=False).tolist())
        if all(b - a >= 2 for a, b in zip(st, st[1:])) and (16 + st[0] - st[-1]) >= 2 and sum(1 for s in st if s % 2) >= 1:
            return st

def house_bass(rng, key, roots_pc_of_bar, bars, lo=28, hi=48, on_kick=False, cell=None):
    """[(step_abs, len_16ths, midi, vel)] over `bars`; roots_pc_of_bar(bar) -> root pitch class of that bar"""
    cell = cell or bass_cell(rng, on_kick); out = []
    octave_p = float(rng.uniform(.15, .35)); fifth_p = float(rng.uniform(.05, .2))
    def root_midi(pc):
        return next(m for m in range(lo, hi + 1) if m % 12 == pc)       # lowest root in range: octave stays available
    for b in range(bars):
        r = root_midi(roots_pc_of_bar(b)); nxt = root_midi(roots_pc_of_bar(b + 1)) if b + 1 < bars else r
        st = list(cell)
        if b % 4 == 3:                                                  # tail variation: move or add the last onset
            t = st[-1] + int(rng.choice([-1, 1])) if st[-1] < 15 else st[-1] - 1
            if t % 4 or on_kick: st[-1] = t
            st = sorted(set(st))
            st = [s for i, s in enumerate(st) if i == 0 or s - st[i - 1] >= 2]
        for j, s in enumerate(st):
            ln = min(2, (st[j + 1] if j + 1 < len(st) else 16 + (cell[0] if b + 1 < bars else 16)) - s - 1)
            ln = max(1, ln)
            m = r
            if j == len(st) - 1 and nxt != r and s >= 12:                 # approach into the next root
                semi = [x for x in (nxt - 1, nxt + 1) if x % 12 in key.pcs and lo <= x <= hi]   # a semitone only if it is in the key
                if semi and rng.random() < .15: m = semi[0]
                else:                                                                         # a scale step into the next root
                    below = key.snap(nxt - 1); above = (key.scale_notes(nxt + 1, nxt + 3) or [nxt])[0]
                    m = below if below >= lo else above                                       # (not nxt+2: F# is not in A minor)
            elif j and rng.random() < octave_p and r + 12 <= hi: m = r + 12
            elif j and rng.random() < fifth_p and (r + 7) % 12 in key.pcs and r + 7 <= hi: m = r + 7   # m7b5: no perfect 5th
            v = accents(s) + (10 if j == 0 else 0)
            out.append((16 * b + s, ln, int(m), int(min(127, v))))
    return out
