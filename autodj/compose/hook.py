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

def _tones(pcs, lo, hi, key=None):
    """chord tones in range; with a key, the ones inside the key win (a slid chord's outside tone only if nothing else)"""
    if key is not None and any(p in key.pcs for p in pcs): pcs = [p for p in pcs if p in key.pcs]
    return [x for x in range(lo, hi + 1) if x % 12 in pcs]

def _end(m, pcs, bar, lo, hi, key=None):
    """question (even bar) ends OPEN on the 3rd/5th, answer (odd bar) CLOSED on the root"""
    return _nearest(_tones(pcs[1:3] if bar % 2 == 0 else pcs[:1], lo, hi, key), m)

def _unrub(m, l, pcs, lo, hi, key=None):
    """a passing note that is HELD (>= 2 sixteenths) must not sit a semitone from a chord tone: over stabs/pads that
    is the m2/m9 rub (P107 demo: stabs+hook clashed in 15% of beats). Short (1/16) passing notes stay free."""
    if l < 2 or m % 12 in pcs or not any((m - p) % 12 in (1, 11) for p in pcs): return m
    ok = [x for x in range(lo, hi + 1) if (key is None or x % 12 in key.pcs or x % 12 in pcs)
          and (x % 12 in pcs or not any((x - p) % 12 in (1, 11) for p in pcs))]
    inkey = [x for x in ok if key is None or x % 12 in key.pcs]                # a slid chord's outside tone: last resort
    return _nearest(inkey or ok, m)

def _refit(ph, chord_pcs_of_bar, lo, hi, key=None):
    """after a repeat/variation under other chords: strong beats -> chord tones, bar endings -> open/closed"""
    out = [(s, l, _nearest(_tones(chord_pcs_of_bar(s // 16), lo, hi, key), m) if s % 4 == 0 else _unrub(m, l, chord_pcs_of_bar(s // 16), lo, hi, key))
           for s, l, m in ph]
    for bar in {s // 16 for s, _, _ in out}:
        j = max(k for k, x in enumerate(out) if x[0] // 16 == bar); s, l, m = out[j]
        out[j] = (s, l, _end(m, chord_pcs_of_bar(bar), bar, lo, hi, key))
    return out

def phrase(rng, key, chord_pcs_of_bar, lo=60, hi=76, cell=None):
    """2 bars: question (bar 0) + answer (bar 1). Returns [(step 0..31, length_16ths, midi)]"""
    cell = cell or rhythm_cell(rng); scale = key.scale_notes(lo, hi); out = []
    center = scale[len(scale) // 2]; prev = center
    for bar in (0, 1):
        pcs = chord_pcs_of_bar(bar); n = len(cell)
        for j, s in enumerate(cell):
            f = j / max(1, n - 1)
            target = prev + (2 if f < .6 else -1) if bar == 0 else prev + (-2 if f < .6 else 1)
            if s % 4 == 0: m = _nearest(_tones(pcs, lo, hi, key), target)
            else: m = _nearest(scale, target)
            if j == n - 1:
                root = pcs[0]
                m = _end(m, pcs, bar, lo, hi, key)
            ln = ((cell[j + 1] if j + 1 < n else 16) - s)
            out.append((bar * 16 + s, int(min(ln, 4 if j + 1 < n else 6)), int(m))); prev = m
    span = max(m for _, _, m in out) - min(m for _, _, m in out)
    if span > 17:                                                                               # squeeze range
        mid = (max(m for _, _, m in out) + min(m for _, _, m in out)) / 2
        out = [(s, l, _nearest(scale, m - 12 if m > mid + 8 else m + 12 if m < mid - 8 else m)) for s, l, m in out]
    return _refit(out, chord_pcs_of_bar, lo, hi, key)                                                 # squeezing may move an ending

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
            ph = list(base)                                                                     # the SAME phrase returns
            if kind: ph = vary(ph, key, kind, rng, lo, hi)
        ph = _refit(ph, lambda b, i=i: chord_pcs_of_bar(2 * i + b), lo, hi, key)                     # fit THIS pair of chords
        seq += [(32 * i + s, l, m) for s, l, m in ph]
    return seq

def accents(step):
    """house-style velocity accents per 16th position within a beat: 110/60/90/70 (Gemini teacher)"""
    return (110, 60, 90, 70)[step % 4]


# --- P107b (Стас): hook on 2-3 anchor notes, accents on weak beats, rests as rhythm, dialog with the bass ----------
def anchors(rng, key, tonic_pcs, lo, hi, k=None):
    """2-3 key notes within a fifth: a chord tone of the home chord + its scale neighbours (the hook «lives» there)"""
    k = k or int(rng.choice([2, 3])); sc = key.scale_notes(lo, hi)
    mid = [m for m in sc if m % 12 in tonic_pcs[1:3] and lo + 3 <= m <= hi - 5] or [sc[len(sc) // 2]]
    c = int(rng.choice(mid)); i = sc.index(c)
    shape = [[0, 1], [0, -1], [0, 2], [-1, 0, 1], [0, 1, 2], [0, 2, 3], [-2, 0, 1]]
    pick = [s for s in shape if len(s) == k][int(rng.integers(len([s for s in shape if len(s) == k])))]
    return sorted(sc[max(0, min(len(sc) - 1, i + d))] for d in pick)

def dialog_cell(rng, bass_steps):
    """lead onsets for one bar from the bass rhythm, per half bar: bass busy (>=2 onsets) -> at most one LONG note
    (>=4 sixteenths), started off the beat; bass resting (<=1 onset) -> a short fill (2-3 sixteenths, 1 step each).
    Lead onsets never coincide with bass onsets; at least one rest of >=3 steps per bar. Returns [(step, len)]."""
    for _ in range(200):
        out = []
        for h in (0, 8):
            bs = [s for s in bass_steps if h <= s < h + 8]; free = [s for s in range(h, h + 8) if s not in bass_steps]
            if len(bs) >= 2:
                if rng.random() < .7:
                    c = [s for s in free if s % 2 and s <= h + 4]
                    if c: s = int(rng.choice(c)); out.append((s, h + 8 - s if rng.random() < .5 else min(6, h + 8 - s)))
            else:
                k = int(rng.choice([2, 3])); c = [s for s in free if s >= h + 2]
                if len(c) >= k:
                    st = sorted(rng.choice(c, k, replace=False).tolist())
                    if all(b - a >= 1 for a, b in zip(st, st[1:])): out += [(s, 1) for s in st]
        out = sorted(out); fixed = []
        for j, (s, l) in enumerate(out):                                        # a note never overlaps the next onset
            nxt = out[j + 1][0] if j + 1 < len(out) else 16; fixed.append((s, max(1, min(l, nxt - s))))
        if not fixed: continue
        busy = sorted(set(x for s, l in fixed for x in range(s, s + l)))
        gaps = [b - a - 1 for a, b in zip([-1] + busy, busy + [16])]
        off = sum(1 for s, _ in fixed if s % 4)
        if max(gaps) >= 3 and off >= max(1, len(fixed) // 2): return fixed
    free = [s for s in range(16) if s not in bass_steps and s % 4] or [s for s in range(16) if s not in bass_steps] or [2]
    return [(free[0], min(6, 16 - free[0]))]                                    # dense bass: one held note, off its onsets

def anchor_hook(rng, key, chord_of_bar, bass_steps_of_bar, lo=62, hi=81, bars=8, home_pcs=None):
    """the hook over `bars` (pairs = question/answer). Pitches come ONLY from the 2-3 anchors, except: the question
    ends on a non-root anchor (tension), the answer's last note resolves to the chord root. The rhythm is the dialog
    cell of each bar (fresh bass -> fresh cell), the A' repeats keep pitches by position. Velocity: notes off the
    beat are accented (108), on the beat softer (84), fill notes lighter (72). Returns [(step, len, midi, vel)]."""
    home = home_pcs or chord_of_bar(0); an = anchors(rng, key, home, lo, hi); out = []
    order = [int(x) for x in rng.permutation(len(an))]; cells = {}
    for b in range(bars):
        ck = (b % 2, tuple(sorted(bass_steps_of_bar(b))))                      # the SAME rhythm returns -> memorable
        if ck not in cells: cells[ck] = dialog_cell(rng, bass_steps_of_bar(b))
        cell = cells[ck]; pcs = chord_of_bar(b); n = len(cell); rot = (0, 1, 0, 2)[(b // 2) % 4]   # A A' A A''
        for j, (s, l) in enumerate(cell):
            m = an[order[(j + rot) % len(an)]]
            if s % 4 == 0 and m % 12 not in pcs:                                 # a beat note: a fitting anchor, else unrub
                fit = [a for a in an if a % 12 in pcs]; m = fit[0] if fit else _unrub(m, max(l, 2), pcs, lo, hi, key)
            elif l >= 2: m = _unrub(m, l, pcs, lo, hi, key)
            if j == n - 1 and b % 2 == 0:                                         # question: open, never the root
                if m % 12 == pcs[0]: m = next((a for a in an if a % 12 != pcs[0]), m)
            if j == n - 1 and b % 2 == 1:                                         # answer: resolve to the root
                m = _nearest([x for x in range(lo, hi + 1) if x % 12 == pcs[0]], m)
            v = 72 if l == 1 and n > 2 else (108 if s % 4 else 84)
            out.append((16 * b + s, int(l), int(m), int(v)))
    return out, an
