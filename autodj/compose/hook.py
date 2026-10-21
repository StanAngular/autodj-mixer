"""Hooks: a short, memorable phrase that returns, instead of random motifs (Стас: «примитивно»; Gemini: no focus,
no hook). A hook is a 2-bar QUESTION -> ANSWER with ONE rhythm cell, repeated over 8 bars as A A' A A'' where the
primes vary only the tail (keeps it recognisable, avoids monotony).
Rules (from the Gemini teacher answer + common pop/house craft):
- rhythm: one cell per hook, 3-6 onsets per bar, >=2 off-beat onsets, at least one rest of >=2 sixteenths, no onset on
  every downbeat (syncopation), last note of the answer may be longer;
- pitch: strong beats (steps 0,4,8,12) take chord tones of the bar's chord, other steps move by scale step;
- contour: question rises / ends OPEN (3rd or 5th, never the root); answer mirrors and ends CLOSED on the root;
- range: at most an octave + a fourth (17 semitones) inside [lo, hi];
- variation: A' changes the last 1-2 notes, A'' adds a pickup or moves the peak a step (rhythm cell kept)."""
import numpy as np

def rhythm_cell(rng, onsets=(3, 6)):
    while True:
        k = int(rng.integers(onsets[0], onsets[1] + 1)); st = sorted(rng.choice(16, k, replace=False).tolist())
        off = sum(1 for s in st if s % 2); gaps = [b - a for a, b in zip(st, st[1:] + [16 + st[0]])]
        if off >= 2 and max(gaps) >= 2 and not all(s in st for s in (0, 4, 8, 12)): return st

def _nearest(cands, x):
    return min(cands, key=lambda c: (abs(c - x), c)) if cands else x

def phrase(rng, key, chord_pcs_of_bar, lo=60, hi=76, cell=None):
    """2 bars: question (bar 0) + answer (bar 1). Returns [(step 0..31, length_16ths, midi)]"""
    cell = cell or rhythm_cell(rng); scale = key.scale_notes(lo, hi); out = []
    center = scale[len(scale) // 2]; prev = center
    for bar in (0, 1):
        pcs = chord_pcs_of_bar(bar); n = len(cell)
        for j, s in enumerate(cell):
            f = j / max(1, n - 1)
            target = prev + (2 if f < .6 else -1) if bar == 0 else prev + (-2 if f < .6 else 1)
            if s % 4 == 0: m = _nearest([x for x in scale if x % 12 in pcs], target)
            else: m = _nearest(scale, target)
            if j == n - 1:
                root = pcs[0]
                if bar == 0: m = _nearest([x for x in scale if x % 12 in pcs[1:3]], m)            # open end
                else: m = _nearest([x for x in scale if x % 12 == root], m)                     # closed on the root
            ln = ((cell[j + 1] if j + 1 < n else 16) - s)
            out.append((bar * 16 + s, int(min(ln, 4 if j + 1 < n else 6)), int(m))); prev = m
    span = max(m for _, _, m in out) - min(m for _, _, m in out)
    if span > 17:                                                                               # squeeze range
        mid = (max(m for _, _, m in out) + min(m for _, _, m in out)) / 2
        out = [(s, l, _nearest(scale, m - 12 if m > mid + 8 else m + 12 if m < mid - 8 else m)) for s, l, m in out]
    return out

def vary(ph, key, kind, rng, lo=60, hi=76):
    """A' = new tail, A'' = pickup into bar 1 / peak moved; the rhythm cell is kept"""
    scale = key.scale_notes(lo, hi); out = list(ph)
    if kind == "tail":
        s, l, m = out[-2]; i = scale.index(_nearest(scale, m)); out[-2] = (s, l, scale[min(len(scale) - 1, i + 1)])
    elif kind == "pickup":
        s0 = out[0][0]; m0 = out[0][2]
        if s0 >= 2: out.insert(0, (s0 - 1, 1, _nearest(scale, m0 + 2)))
    elif kind == "peak":
        k = int(np.argmax([m for _, _, m in out])); s, l, m = out[k]; i = scale.index(_nearest(scale, m)); out[k] = (s, l, scale[min(len(scale) - 1, i + 1)])
    return out

def eight_bars(rng, key, chord_pcs_of_bar, lo=60, hi=76):
    """A A' A A'' over 8 bars (each A = 2 bars). Returns [(step 0..127, len, midi)]; chord_pcs_of_bar(bar 0..7)."""
    cell = rhythm_cell(rng); seq = []
    for i, kind in enumerate((None, "tail", None, "pickup")):
        ph = phrase(rng, key, lambda b, i=i: chord_pcs_of_bar(2 * i + b), lo, hi, cell)
        if i == 0: base = ph
        else:
            ph = [(s, l, m) for s, l, m in base]                                                 # the SAME phrase returns
            # keep strong-beat notes on the current chord (chords may differ between repeats)
            ph = [(s, l, (_nearest([x for x in key.scale_notes(lo, hi) if x % 12 in chord_pcs_of_bar(2 * i + s // 16)], m) if s % 4 == 0 else m)) for s, l, m in ph]
            if kind: ph = vary(ph, key, kind, rng, lo, hi)
        seq += [(32 * i + s, l, m) for s, l, m in ph]
    return seq

def accents(step):
    """house-style velocity accents per 16th position within a beat: 110/60/90/70 (Gemini teacher)"""
    return (110, 60, 90, 70)[step % 4]
