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
        cost += 14 * sum(1 for x, y in itertools.combinations(c, 2) if y - x in (1, 13))   # minor 2nd / minor 9th = cluster that rubs
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

# --- house harmony (P107 stage 3): one chord SHAPE moved in parallel, shell voicings, 2-note pads ------------------
SHAPES = {"m7": [0, 3, 7, 10], "m9": [0, 3, 7, 10, 14], "m11": [0, 7, 10, 15, 17], "maj7": [0, 4, 7, 11],
          "maj9": [0, 4, 7, 11, 14], "quartal": [0, 5, 10, 15], "sus7": [0, 5, 7, 10], "add9": [0, 4, 7, 14]}

def parallel_progression(rng, key, shape, n=4, max_out=1):
    """house/garage move: the SAME chord shape slid onto n roots (the colour comes from the slide, not from diatonic
    rules). Starts on the tonic; each root keeps at most `max_out` shape tones outside the key, so the stab rubs a
    little but never fights the melody. Returns [root_pc, ...]."""
    iv = SHAPES[shape] if isinstance(shape, str) else list(shape)
    ok = [r for r in range(12) if sum((r + i) % 12 not in key.pcs for i in iv) <= max_out]
    if key.tonic not in ok: ok.append(key.tonic)
    out = [key.tonic]
    while len(out) < n:
        c = [r for r in ok if r != out[-1] and (len(out) < n - 1 or r != out[0])]
        w = np.array([3.0 if r in key.pcs else 1.0 for r in c]); out.append(int(rng.choice(c, p=w / w.sum())))
    return out

def shape_pcs(root_pc, shape):
    iv = SHAPES[shape] if isinstance(shape, str) else list(shape)
    return [(root_pc + i) % 12 for i in iv]

def thin(shape):
    """a stab of 5+ notes is a cluster (Gemini draft critique): drop the 5th, keep 1-3-7-9(-11)"""
    iv = SHAPES[shape] if isinstance(shape, str) else list(shape)
    return [i for i in iv if i % 12 != 7] if len(iv) > 4 and 7 in iv else iv

def stab_voicing(roots_pc, shape, lo, hi):
    """place the shape on each root with IDENTICAL intervals (true parallel motion); each root is the one closest
    to the previous root so the stab slides instead of jumping. Returns [[midi, ...], ...]."""
    iv = SHAPES[shape] if isinstance(shape, str) else list(shape); span = iv[-1] - iv[0]; mid = (lo + hi - span) / 2
    opts = [[m for m in range(lo - 12, hi + 1) if m % 12 == r and lo - 12 <= m <= hi - span + 12] for r in roots_pc]
    def cost(c):                                                    # whole line at once: a greedy walk drifts to the edge
        steps = [abs(x - y) for x, y in zip(c, c[1:])]
        return sum(steps) + 4 * sum(max(0, s - 7) for s in steps) + 2 * sum(max(0, lo - m) + max(0, m + span - hi) for m in c) \
            + .1 * abs(np.mean(c) - mid)
    best = min(itertools.product(*opts), key=cost)
    return [[m + i for i in iv] for m in best]

def shell(chord_pcs, lo, hi, prev=None):
    """shell voicing 1-3-7 (1-3-5 for a triad): root at the bottom, 3rd and 7th above, nothing else. Open (root,
    7th, 10th) or closed (root, 3rd, 7th), whichever moves least from `prev`."""
    r, t, top = chord_pcs[0], chord_pcs[1], chord_pcs[3] if len(chord_pcs) > 3 else chord_pcs[2]; best, bc = None, 1e9
    for b in (m for m in range(lo, hi + 1) if m % 12 == r):
        for v in ([b, b + (t - r) % 12, b + (top - r) % 12], [b, b + (top - r) % 12, b + 12 + (t - r) % 12]):
            if v[-1] > hi: continue
            c = sum(min(abs(a - x) for x in prev) for a in v) if prev else abs(np.mean(v) - (lo + hi) / 2)
            if c < bc: best, bc = v, c
    return best or voicing(chord_pcs, lo, hi, prev, 3)

def pad_dyad(chord_pcs, lo, hi, prev=None):
    """pad under keys/stabs plays only the guide tones (3rd + 7th, or 3rd + 5th), never the full chord"""
    c0 = chord_pcs; real7 = len(c0) > 3 and (c0[3] - c0[0]) % 12 in (10, 11)
    for g in ([c0[1], c0[3] if real7 else c0[2]], [c0[1], c0[2]], [c0[0], c0[2]]):   # 3rd+7th, else 3rd+5th, else 1+5
        best, bc = None, 1e9
        for a in (m for m in range(lo, hi + 1) if m % 12 == g[0]):
            for b in (m for m in range(lo, hi + 1) if m % 12 == g[1]):
                if not 3 <= abs(a - b) <= 11: continue
                v = sorted([a, b]); c = sum(min(abs(x - y) for y in prev) for x in v) if prev else abs(np.mean(v) - (lo + hi) / 2)
                if c < bc: best, bc = v, c
        if best: return best
    return None


def clashes(layers, step_s, min_len_s=0.0):
    """layers: {name: [(t, midi, vel, dur), ...]} -> how often notes of DIFFERENT layers sound a minor 2nd / minor 9th
    (or two octaves + a semitone) apart. Major 7ths are left alone: they live inside every maj7/9th chord. Returns (ratio of busy grid steps with a clash, top offending layer pairs)."""
    import collections
    ends = [t + d for evs in layers.values() for t, _, _, d in evs]
    if not ends: return 0.0, []
    n = int(max(ends) / step_s) + 1; grid = [collections.defaultdict(set) for _ in range(n)]
    for name, evs in layers.items():
        for t, m, _, d in evs:
            if d < min_len_s: continue
            for k in range(int(t / step_s), min(n, int((t + d) / step_s))): grid[k][name].add(int(m))
    busy = bad = 0; pairs = collections.Counter()
    for g in grid:
        names = list(g)
        if len(names) < 2: continue
        busy += 1; hit = False
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                for a in g[names[i]]:
                    for b in g[names[j]]:
                        if abs(a - b) in (1, 13, 25): pairs[(names[i], names[j])] += 1; hit = True
        bad += hit
    return (bad / busy if busy else 0.0), pairs.most_common(4)


# --- P107b (Стас, отзыв на демо): voice leading instead of planing, tension -> release ---------------------------
QUALITY = {"m": [0, 3, 7], "m7": [0, 3, 7, 10], "madd9": [0, 3, 7, 14], "": [0, 4, 7], "maj7": [0, 4, 7, 11], "add9": [0, 4, 7, 14],
           "7": [0, 4, 7, 10], "7sus4": [0, 5, 7, 10], "sus4": [0, 5, 7], "sus2": [0, 2, 7], "m7b5": [0, 3, 6, 10]}
FUNCTIONS = {   # degree (0-based) -> quality choices per function; "D" chords use the raised 7th of harmonic minor
    "minor": {"T": [(0, ["m", "m7", "madd9"]), (5, ["maj7", "add9"]), (2, ["maj7"])],
              "S": [(3, ["m", "m7", "sus2"]), (5, ["maj7"]), (1, ["m7b5"]), (6, ["", "add9"])],
              "D": [(4, ["7", "7sus4"]), (6, ["", "sus2"])]},
    "major": {"T": [(0, ["", "maj7", "add9"]), (5, ["m7", "m"]), (2, ["m7"])],
              "S": [(3, ["", "maj7", "sus2"]), (1, ["m7", "m"])],
              "D": [(4, ["7", "7sus4", "sus4"]), (6, ["m7b5"])]}}

def chord_of(root_pc, quality, name_tonic=None):
    """pcs ordered [root, 3rd-or-sus, 5th, 7th/9th]: hook endings use pcs[1:3] (an open end on a sus note = tension)"""
    iv = QUALITY[quality]; return [(root_pc + i) % 12 for i in iv]

def tension_progression(rng, key, phrases=1, chords=4, bars_per_chord=2):
    """functional chain per phrase: T ... S ... D -> (next phrase starts on T = the release). Each phrase is drawn
    anew (no fixed list), the dominant often comes as a suspension that resolves inside its own chord span
    (7sus4 -> 7, sus4 -> major). Returns per-BAR list of dicts {name, root, pcs, fn}."""
    fam = "major" if key.mode in ("major", "mixolydian", "lydian") else "minor"; F = FUNCTIONS[fam]; NM = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    out = []
    for ph in range(phrases):
        fns = ["T"] + [str(rng.choice(["T", "S"], p=[.35, .65])) if i < chords - 2 else "S" for i in range(1, chords - 1)] + ["D"]
        prev = None
        for fn in fns:
            opts = [(d, q) for d, qs in F[fn] for q in qs if (prev is None or d != prev[0]) and not (fn == "T" and prev is None and d != 0)]
            w = np.array([(2.3 if d == 4 else .7) if fn == "D" else 1.0 for d, _ in opts]); w = w / w.sum()   # V(7) is THE tension
            d, q = opts[int(rng.choice(len(opts), p=w))]; prev = (d, q)                                         # never the same root twice
            root = key.degree_pc(d)
            seq = [q] * bars_per_chord
            if fn == "D" and d == 4 and fam == "minor" and q == "7" and bars_per_chord >= 2 and rng.random() < .6: seq = ["7sus4"] + ["7"] * (bars_per_chord - 1)
            if fn == "D" and q == "7sus4": seq = ["7sus4"] * (bars_per_chord - 1) + ["7"]           # suspension resolves
            if fn == "D" and q == "sus4": seq = ["sus4"] * (bars_per_chord - 1) + [""]
            for qq in seq: out.append({"name": NM[root] + qq, "root": root, "pcs": chord_of(root, qq), "fn": fn})
    return out

def lead_voices(chords_pcs, lo, hi, n=4, max_step=2, prev=None):
    """classical voice leading: a voice whose note belongs to the next chord STAYS (common tone); the others move by
    at most `max_step` semitones to the nearest tone of the next chord; the 3rd/sus note and the 7th must be present.
    Only if no such move exists is a voice allowed to go further (then the smallest leap wins). Root may be left out:
    the bass plays it."""
    out = []
    for c in chords_pcs:
        need = [c[1]] + [x for x in c[3:4] if (x - c[0]) % 12 in (10, 11)]          # 3rd/sus + a REAL 7th (a 9th is colour)
        if prev is None:
            prev = voicing(c, lo, hi, None, n); out.append(sorted(prev)); continue
        best, bc = None, 1e9
        for reach in (max_step, max_step + 2, 7):
            opts = [[m + d for d in range(-reach, reach + 1) if (m + d) % 12 in c and lo <= m + d <= hi] or [m] for m in prev]
            for combo in itertools.product(*opts):
                got = {x % 12 for x in combo}
                if not all(g in got for g in need) or len(set(combo)) < len(combo): continue
                s = sorted(combo); cost = sum(abs(a - b) for a, b in zip(prev, combo))
                cost += sum(3 for a, b in zip(prev, combo) if a % 12 in c and a != b)            # a common tone moved
                cost += 10 * sum(1 for x, y in zip(s, s[1:]) if y - x == 1)                        # m2 between voices
                cost += 4 * (len(combo) - len(got))                                                 # doubled pcs block later steps
                cost += 6 * sum(1 for x, y in zip(s, s[1:]) if y - x == 2 and x < 79)               # a 2nd at 300-800 Hz = mud
                cost += 2 * sum(1 for i in range(len(combo)) for j in range(i + 1, len(combo)) if (prev[i] - prev[j]) * (combo[i] - combo[j]) < 0)  # crossing
                if cost < bc: best, bc = list(combo), cost
            if best: break
        prev = best or voicing(c, lo, hi, prev, n); out.append(sorted(prev))
    return out
