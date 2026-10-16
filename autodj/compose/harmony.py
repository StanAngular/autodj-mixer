"""Harmony and melody helpers: diatonic chords in any mode, voice-led inversions, generated comping rhythms,
call-and-response motifs. Nothing here is a fixed pattern: rhythms and motifs are drawn per track from the rng."""
import itertools
import numpy as np

MODES = {"minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10], "phrygian": [0, 1, 3, 5, 7, 8, 10],
         "major": [0, 2, 4, 5, 7, 9, 11], "mixolydian": [0, 2, 4, 5, 7, 9, 10], "lydian": [0, 2, 4, 6, 7, 9, 11],
         "harmonic_minor": [0, 2, 3, 5, 7, 8, 11]}
NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}
NOTE.update({"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10})

class Key:
    def __init__(self, tonic="A", mode="minor"):
        self.tonic = NOTE[tonic] if isinstance(tonic, str) else tonic % 12; self.mode = mode
        self.steps = MODES[mode]; self.pcs = {(self.tonic + s) % 12 for s in self.steps}
    def degree_pc(self, d):
        return (self.tonic + self.steps[d % 7]) % 12
    def chord(self, degree, size=4):
        """stacked diatonic thirds from scale degree (0-based): size 3 triad, 4 seventh, 5 ninth -> ordered pcs, root first"""
        return [self.degree_pc(degree + 2 * k) for k in range(size)]
    def snap(self, m):
        while m % 12 not in self.pcs: m -= 1
        return m
    def scale_notes(self, lo, hi):
        return [m for m in range(lo, hi + 1) if m % 12 in self.pcs]

def voicing(chord_pcs, lo, hi, prev=None, n=4, rootless=False):
    """choose n chord tones in [lo, hi]. Keeps 3rd and 7th (guide tones), avoids a 2nd at the bottom,
    and moves as little as possible from `prev` (voice leading through inversions)."""
    pcs = list(chord_pcs[1:] if rootless and len(chord_pcs) > 3 else chord_pcs)
    guide = [p for k, p in enumerate(chord_pcs) if k in (1, 3)]
    cands = [m for m in range(lo, hi + 1) if m % 12 in pcs]; best, bc = None, 1e9
    for combo in itertools.combinations(cands, min(n, len(cands))):
        got = {m % 12 for m in combo}
        if not all(g in got for g in guide[:2]): continue
        if len(got) < min(len(pcs), n) - 1: continue
        c = sorted(combo); cost = 0.0
        if c[1] - c[0] <= 2: cost += 6                                   # mud at the bottom
        cost += max(0, (c[-1] - c[0]) - 19) * .5                          # too wide
        if prev: cost += sum(min(abs(a - b) for b in prev) for a in c) + sum(min(abs(a - b) for a in c) for b in prev) * .5
        else: cost += abs(np.mean(c) - (lo + hi) / 2) * .3
        if cost < bc: best, bc = c, cost
    return best or sorted(cands[:n])

def lead_chords(chords_pcs, lo, hi, n=4, rootless=False):
    out, prev = [], None
    for c in chords_pcs:
        v = voicing(c, lo, hi, prev, n, rootless); out.append(v); prev = v
    return out

def comp_rhythm(rng, hits=(2, 4), steps=16, min_off=1):
    """a comping rhythm for one bar: (step, length_in_16ths). At least `min_off` hits off the quarter grid, never
    all on downbeats. Generated, not picked from a list."""
    while True:
        k = int(rng.integers(hits[0], hits[1] + 1)); st = sorted(rng.choice(steps, k, replace=False).tolist())
        if sum(1 for s in st if s % 4) >= min_off and st != [0, 4, 8, 12][:k]: break
    return [(s, (st[i + 1] if i + 1 < len(st) else steps) - s) for i, s in enumerate(st)]

def motif(rng, key, lo, hi, bars=2, notes=(4, 7)):
    """question phrase over `bars`: onsets on the 16th grid + scale-step contour; returns [(step, len, midi)]"""
    total = 16 * bars; k = int(rng.integers(notes[0], notes[1] + 1))
    on = sorted(set([0] + rng.choice(np.arange(1, total - 2), k - 1, replace=False).tolist()))
    sc = key.scale_notes(lo, hi); i = int(rng.integers(len(sc) // 3, 2 * len(sc) // 3)); out = []
    shape = rng.choice(["arch", "rise", "fall", "wave"])
    for j, s in enumerate(on):
        f = j / max(1, len(on) - 1)
        step = {"arch": 1 if f < .5 else -1, "rise": 1, "fall": -1, "wave": 1 if j % 2 else -1}[shape] * int(rng.choice([1, 1, 2]))
        i = int(np.clip(i + (step if j else 0), 0, len(sc) - 1)); ln = (on[j + 1] if j + 1 < len(on) else total) - s
        out.append((s, min(ln, 6), sc[i]))
    return out

def answer(m, key, chord_pcs, lo, hi):
    """same rhythm, ending resolved to the chord root (the question usually ends open)"""
    out = list(m); s, ln, n = out[-1]
    roots = [x for x in range(lo, hi + 1) if x % 12 == chord_pcs[0]]
    out[-1] = (s, ln, min(roots, key=lambda x: abs(x - n)) if roots else n)
    return out

def develop(m, key, kind, rng):
    """sequence (move up/down the scale), fragment (first half twice), invert (contour mirrored), displace (shift by a 16th)"""
    sc = sorted(set(key.scale_notes(0, 127)))
    idx = lambda n: sc.index(key.snap(n))
    if kind == "sequence":
        d = int(rng.choice([-2, -1, 1, 2])); return [(s, l, sc[idx(n) + d]) for s, l, n in m]
    if kind == "fragment":
        h = [x for x in m if x[0] < 16]; return h + [(s + 16, l, n) for s, l, n in h]
    if kind == "invert":
        p = idx(m[0][2]); return [(s, l, sc[2 * p - idx(n)]) for s, l, n in m]
    if kind == "displace":
        return [(s + 1, max(1, l - 1), n) for s, l, n in m if s + 1 < 32]
    return list(m)

def strong_to_chord(m, chord_pcs):
    """notes on beats move to the nearest chord tone (keeps the line consonant on the downbeats)"""
    out = []
    for s, l, n in m:
        if s % 4 == 0 and n % 12 not in chord_pcs:
            n = min([x for x in range(n - 3, n + 4) if x % 12 in chord_pcs] or [n], key=lambda x: abs(x - n))
        out.append((s, l, n))
    return out
