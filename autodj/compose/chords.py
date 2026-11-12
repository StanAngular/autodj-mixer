"""P134 (2026-11-12, Стас: «гармония… более глубокие, сложные, современные композиции, а не примитив из 2000-х»): harmony as a PLAN of
the whole track. The real scores (Night Shift Steps, Carthage, Glass Hours, Paper Lamps ...) all write `CH = [4 chords]`, one per
bar, looped for 5 minutes, voiced as stacked thirds, with a root-fifth-octave bass: the same Cm(add9) | Abmaj7 | Fm7 | G7sus4
transposed from track to track. The engine's theory tools (voice leading, stable tones) polish that loop; nothing writes harmony
that MOVES. This module does:

  Chord        root + quality (m9, m11, maj7#11, 13sus4, 7#9, m7b5 ...) + optional bass note; knows its chord scale and, for every
               pitch class, whether it is a chord tone, an available tension (9 / 11 / 13: the colour) or an avoid note.
  IDIOMS       8-bar harmonic sentences of today's deep / garage / melodic / dark / dreamy electronic music (dorian vamp with the
               major IV, m9 planing, line cliche over a falling bass, pedal with moving upper chords, neo-soul ii-V chains,
               phrygian bII, lydian float ...), with uneven harmonic rhythm, written as degrees so they fit any key.
  operators    extend / simplify (colour level), pedal, inversions (stepwise bass), passing (chromatic slide chord before a
               change), push (the change lands a 16th-pair early), turnaround, tritone: a progression is VARIED, not looped.
  Plan         the chords of the WHOLE track by section role: home (A A' pairs), journey (another sentence, optionally in the
               relative key), intro / outro (simplified over a pedal), break (long suspended chords), build (dominant pedal).
               One object that every tonal layer reads: voicings(), bass(), at(step), chord_of_bar(), describe(), fingerprint().
  voicings     close / drop2 / rootless / quartal / spread, chosen ALONG the progression (dynamic programming) for minimal
               motion, no minor ninths between voices, low-interval limits, and optionally a given top line (melody on top).

    plan = chords.Plan.build("C", sections=trk.tl, home="dorian_vamp", journey="line_cliche", seed=seed)
    keys = plan.voicings("drop2", 52, 76)            # [(step, len, [midi ...])]
    bass = plan.bass(rng, 28, 45, style="line")       # [(step, len, midi, vel)] with approach notes and inversions
See lines.py for melodies written against the plan."""
import numpy as np

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
QUAL = {  # intervals from the root, in the order root, 3rd/sus, 5th, 7th/6th, then the colours
    "m": [0, 3, 7], "m7": [0, 3, 7, 10], "m9": [0, 3, 7, 10, 14], "m11": [0, 3, 7, 10, 14, 17], "m6": [0, 3, 7, 9], "m69": [0, 3, 7, 9, 14],
    "madd9": [0, 3, 7, 14], "mM7": [0, 3, 7, 11], "m7b5": [0, 3, 6, 10], "dim7": [0, 3, 6, 9],
    "": [0, 4, 7], "maj7": [0, 4, 7, 11], "maj9": [0, 4, 7, 11, 14], "maj7#11": [0, 4, 7, 11, 14, 18], "6": [0, 4, 7, 9], "69": [0, 4, 7, 9, 14], "add9": [0, 4, 7, 14],
    "7": [0, 4, 7, 10], "9": [0, 4, 7, 10, 14], "13": [0, 4, 7, 10, 14, 21], "7b9": [0, 4, 7, 10, 13], "7#9": [0, 4, 7, 10, 15], "7#11": [0, 4, 7, 10, 14, 18],
    "sus2": [0, 2, 7], "sus4": [0, 5, 7], "7sus4": [0, 5, 7, 10], "9sus4": [0, 5, 7, 10, 14], "13sus4": [0, 5, 7, 10, 14, 21]}
FAMILY = {**{q: "minor" for q in ("m", "m7", "m9", "m11", "m6", "m69", "madd9")}, "mM7": "mM", "m7b5": "halfdim", "dim7": "dim",
          **{q: "major" for q in ("", "maj7", "maj9", "maj7#11", "6", "69", "add9")}, **{q: "dom" for q in ("7", "9", "13", "7b9", "7#9", "7#11")},
          **{q: "sus" for q in ("sus2", "sus4", "7sus4", "9sus4", "13sus4")}}
MODES = {"ionian": [0, 2, 4, 5, 7, 9, 11], "dorian": [0, 2, 3, 5, 7, 9, 10], "phrygian": [0, 1, 3, 5, 7, 8, 10], "lydian": [0, 2, 4, 6, 7, 9, 11],
         "mixolydian": [0, 2, 4, 5, 7, 9, 10], "aeolian": [0, 2, 3, 5, 7, 8, 10], "locrian": [0, 1, 3, 5, 6, 8, 10], "lydian_dominant": [0, 2, 4, 6, 7, 9, 10],
         "phrygian_dominant": [0, 1, 4, 5, 7, 8, 10], "altered": [0, 1, 3, 4, 6, 8, 10], "melodic_minor": [0, 2, 3, 5, 7, 9, 11], "locrian_nat2": [0, 2, 3, 5, 6, 8, 10],
         "whole_half": [0, 2, 3, 5, 6, 8, 9, 11], "spanish8": [0, 1, 3, 4, 5, 7, 8, 10], "half_whole": [0, 1, 3, 4, 6, 7, 9, 10], "minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11]}
SCALES_FOR = {"minor": ["dorian", "aeolian", "phrygian"], "major": ["ionian", "lydian"], "dom": ["mixolydian", "lydian_dominant", "phrygian_dominant", "spanish8", "half_whole", "altered"],
              "sus": ["mixolydian", "dorian", "ionian"], "halfdim": ["locrian", "locrian_nat2"], "dim": ["whole_half"], "mM": ["melodic_minor"]}
LADDER = {"minor": ["m", "m7", "m9", "m11"], "major": ["", "maj7", "maj9", "maj7#11"], "dom": ["7", "9", "13"], "sus": ["sus4", "7sus4", "9sus4", "13sus4"]}

def pc_of(x):
    return NOTE[x] if isinstance(x, str) else int(x) % 12

def key_pcs(tonic, mode="minor"):
    return {(pc_of(tonic) + s) % 12 for s in MODES[mode]}

class Chord:
    def __init__(self, root, qual, bass=None):
        if qual not in QUAL: raise ValueError(f"unknown chord quality {qual!r} (have: {sorted(QUAL)})")
        self.root = pc_of(root); self.qual = qual; self.bass = None if bass is None else pc_of(bass)
        self.iv = QUAL[qual]; self.pcs = [(self.root + i) % 12 for i in self.iv]; self.family = FAMILY[qual]
    def __eq__(self, o): return isinstance(o, Chord) and (self.root, self.qual, self.bass) == (o.root, o.qual, o.bass)
    def __hash__(self): return hash((self.root, self.qual, self.bass))
    def __repr__(self): return self.name
    @property
    def name(self):
        return NAMES[self.root] + self.qual + (f"/{NAMES[self.bass]}" if self.bass is not None and self.bass != self.root else "")
    @property
    def bass_pc(self): return self.root if self.bass is None else self.bass
    @property
    def core(self):
        """root, 3rd (or sus), 5th, 7th / 6th: the tones that define the chord"""
        return self.pcs[:4]
    def scale(self, key=None):
        """the chord scale: the mode of this chord's family that holds every chord tone and shares most notes with the key"""
        best = None
        for i, name in enumerate(SCALES_FOR[self.family]):
            m = MODES[name]
            if not all(iv % 12 in m for iv in self.iv): continue
            pcs = [(self.root + s) % 12 for s in m]; score = (len(set(pcs) & set(key)) if key else 0) - .01 * i
            if best is None or score > best[0]: best = (score, pcs, name)
        if best is None: return sorted(set(self.pcs)), "chord"
        return best[1], best[2]
    def roles(self, key=None):
        """{pc: "chord" | "tension" | "avoid"} for the chord scale. Avoid = a scale note a semitone ABOVE a defining chord tone
        (the 4th over a major chord, the b6 over a minor one ...): fine in passing, wrong when held. Dominants keep their
        altered ninths and 13ths as colours; only their 4th is avoided."""
        sc, _ = self.scale(key); out = {}; core = set(self.core)
        for pc in sc:
            if pc in self.pcs: out[pc] = "chord"
            elif self.family == "dom": out[pc] = "avoid" if pc == (self.root + 5) % 12 else "tension"
            else: out[pc] = "avoid" if (pc - 1) % 12 in core else "tension"
        if self.bass is not None: out[self.bass] = "chord"                             # the bass of a slash chord belongs to it
        return out
    def role(self, pc, key=None):
        return self.roles(key).get(pc % 12, "out")
    def colours(self, key=None):
        """the chord's colour tones for a top voice, best first: 9, 11 / #11, 13 / 6, then 7th, 5th, 3rd"""
        r = self.roles(key); ten = [p for p in r if r[p] == "tension"]; order = [2, 5, 6, 9, 1, 3, 8]
        ten.sort(key=lambda p: order.index((p - self.root) % 12) if (p - self.root) % 12 in order else 9)
        ext = [p for p in self.pcs[4:]]; rest = [self.pcs[i] for i in (3, 2, 1) if i < len(self.pcs)]
        return list(dict.fromkeys(ext + ten + rest))
    def tension(self, tonic, key=None):
        """0..1: how far from rest: distance of the root from the tonic on the circle of fifths, notes outside the key,
        tritones / semitones inside the chord, dominant or suspended function"""
        fifths = min((self.root - pc_of(tonic)) * 7 % 12, 12 - (self.root - pc_of(tonic)) * 7 % 12) / 6
        out = (sum(1 for p in self.pcs if p not in key) / len(self.pcs)) if key else 0
        ics = [min((a - b) % 12, (b - a) % 12) for i, a in enumerate(self.pcs) for b in self.pcs[i + 1:]]; rough = sum(1 for i in ics if i in (1, 6)) / max(1, len(ics))
        return float(min(1.0, .45 * fifths + .25 * out + .6 * rough + {"dom": .2, "sus": .1, "halfdim": .15, "dim": .2}.get(self.family, 0)))
    def moved(self, **kw):
        return Chord(kw.get("root", self.root), kw.get("qual", self.qual), kw.get("bass", self.bass))

# ---- harmonic sentences ------------------------------------------------------------------------------------------------------
# (degree in semitones above the tonic, quality, length in bars[, bass degree]) - 8 bars each; mode = the home scale; moods = where it fits
IDIOMS = {
 "dorian_vamp":   dict(mode="dorian", moods=("deep", "garage", "lofi"), slots=[(0, "m9", 2), (5, "13", 1.5), (10, "maj9", .5), (0, "m11", 2), (10, "maj9", 1), (5, "9sus4", 1)]),
 "planing_m9":    dict(mode="dorian", moods=("deep", "garage", "minimal"), slots=[(0, "m9", 1.5), (10, "m9", .5), (5, "m9", 2), (3, "m9", 1.5), (5, "m9", .5), (7, "m9", 1), (10, "m9", 1)]),
 "line_cliche":   dict(mode="minor", moods=("melodic", "deep", "dark"), slots=[(0, "m9", 2), (0, "m7", 2, 10), (8, "maj7#11", 2), (5, "m69", 1), (7, "9sus4", 1)]),
 "pedal_lift":    dict(mode="minor", moods=("melodic", "minimal", "dark"), slots=[(0, "m9", 2), (10, "add9", 2, 0), (8, "maj7", 2, 0), (5, "m7", 1, 0), (10, "6", 1, 0)]),
 "neo_soul":      dict(mode="minor", moods=("lofi", "garage", "deep"), slots=[(5, "m9", 1), (10, "13", 1), (3, "maj9", 1), (8, "maj7#11", 1), (2, "m7b5", 1), (7, "7#9", 1), (0, "m9", 2)]),
 "garage_steps":  dict(mode="dorian", moods=("garage", "deep"), slots=[(0, "m9", 1), (2, "m7", 1), (3, "maj9", 1.5), (5, "9", .5), (8, "maj9", 2), (7, "9sus4", 1), (7, "7#9", 1)]),
 "phrygian_dark": dict(mode="phrygian", moods=("dark", "minimal"), slots=[(0, "m9", 3), (1, "maj7#11", 1), (0, "m11", 2), (10, "m9", 1), (1, "maj7", 1)]),
 "mediant_drift": dict(mode="minor", moods=("melodic", "dreamy", "dark"), slots=[(0, "m9", 2), (8, "maj9", 1), (4, "maj7#11", 1), (0, "m11", 2), (3, "maj9", 1), (10, "13sus4", 1)]),
 "aeolian_wide":  dict(mode="minor", moods=("melodic", "dreamy"), slots=[(0, "m11", 2), (8, "maj9", 2), (3, "69", 1.5), (10, "9sus4", .5), (5, "m9", 1), (7, "m7", 1)]),
 "two_chord_dub": dict(mode="dorian", moods=("minimal", "deep", "dark"), slots=[(0, "m11", 3.5), (5, "9sus4", .5), (0, "m9", 2), (10, "69", 1.5), (0, "m11", .5)]),
 "lydian_float":  dict(mode="lydian", moods=("dreamy", "lofi"), slots=[(0, "maj9", 2), (2, "", 2, 0), (9, "m9", 2), (5, "maj7#11", 1), (7, "6", 1)]),
 "soul_major":    dict(mode="major", moods=("lofi", "dreamy", "garage"), slots=[(0, "maj9", 1.5), (4, "m7", .5), (9, "m9", 2), (2, "m9", 1), (7, "13sus4", 1), (5, "maj7#11", 1), (5, "m6", 1)]),
 "old_loop":      dict(mode="minor", moods=(), slots=[(0, "madd9", 1), (8, "maj7", 1), (5, "m7", 1), (7, "7sus4", 1)] * 2),   # the loop of the old scores (for A/B only)
}

def idioms(mood=None, mode=None):
    """names of the sentences for a mood ("deep", "garage", "melodic", "dark", "dreamy", "lofi", "minimal") and/or a home mode family"""
    minorish = ("minor", "dorian", "phrygian")
    return [n for n, d in IDIOMS.items() if d["moods"] and (mood is None or mood in d["moods"])
            and (mode is None or (d["mode"] in minorish) == (mode in minorish))]

def sentence(name, tonic):
    """an idiom in a key -> [(length in 16th steps, Chord)]"""
    t = pc_of(tonic); out = []
    for s in IDIOMS[name]["slots"]:
        out.append((int(round(s[2] * 16)), Chord((t + s[0]) % 12, s[1], None if len(s) < 4 else (t + s[3]) % 12)))
    return out

# ---- operators: a progression is varied, not looped -------------------------------------------------------------------------------
def extend(prog, by=1):
    """one more (or one less) level of colour: m -> m7 -> m9 -> m11, maj7 -> maj9 -> maj7#11, 7 -> 9 -> 13, 7sus4 -> 9sus4 -> 13sus4.
    Chords that are already a special colour (m69, 7#9, m7b5 ...) are left as they are."""
    out = []
    for n, c in prog:
        lad = LADDER.get(c.family, [])
        out.append((n, c.moved(qual=lad[int(np.clip(lad.index(c.qual) + by, 0, len(lad) - 1))]) if c.qual in lad else c))
    return out

def pedal(prog, bass):
    """every chord over one bass note (the upper harmony moves, the ground stays)"""
    return [(n, c.moved(bass=pc_of(bass))) for n, c in prog]

def merge(prog, steps=32):
    """longer breaths: chords are held in blocks of `steps` (the first chord of each block stays)"""
    out, pos = [], 0
    for n, c in prog:
        if pos % steps == 0 or not out: out.append([n, c])
        else: out[-1][0] += n
        pos += n
    return [(n, c) for n, c in out]

def passing(prog, rng, p=.5, steps=2):
    """a chromatic slide chord in the last `steps` sixteenths before a change: the NEXT chord's shape a semitone away (the keys
    player's slide into the chord). Only where the roots differ and the slot is long enough."""
    out = []
    for i, (n, c) in enumerate(prog):
        nxt = prog[(i + 1) % len(prog)][1]
        if nxt.root != c.root and n >= 8 and rng.random() < p:
            side = -1 if (nxt.root - c.root) % 12 <= 6 else 1                       # approach from the side we come from
            out += [(n - steps, c), (steps, Chord((nxt.root + side) % 12, nxt.qual, nxt.bass))]
        else: out.append((n, c))
    return out

def push(prog, rng, p=.5, steps=2):
    """the change lands `steps` sixteenths EARLY (on the «and» before the bar line): harmonic rhythm that leans forward"""
    L = [n for n, _ in prog]
    for i in range(1, len(prog)):
        if L[i - 1] > 8 and L[i] >= 8 and rng.random() < p: L[i - 1] -= steps; L[i] += steps
    return [(n, c) for n, (_, c) in zip(L, prog)]

def turnaround(prog, tonic, kind="sus"):
    """the last bar turns back to the tonic: "sus" V9sus4, "backdoor" bVII13, "neapolitan" bIImaj7, "tritone" bII7#11"""
    t = pc_of(tonic); ch = {"sus": Chord(t + 7, "9sus4"), "backdoor": Chord(t + 10, "13"), "neapolitan": Chord(t + 1, "maj7"), "tritone": Chord(t + 1, "7#11")}[kind]
    n, c = prog[-1]
    return prog[:-1] + ([(n - 8, c), (8, ch)] if n > 8 else [(n, ch)])

def tritone(prog):
    """dominant chords are replaced by the dominant a tritone away (the bass then falls by a semitone into the target)"""
    return [(n, Chord(c.root + 6, "7#11") if c.family == "dom" else c) for n, c in prog]

def inversions(prog, strict_first=True):
    """bass notes chosen among root / 3rd / 5th / 7th so that the bass line moves by step where it can (slash chords)"""
    cands = [[c.bass_pc] if c.bass is not None else list(dict.fromkeys([c.root] + c.core[1:])) for _, c in prog]
    if strict_first: cands[0] = [prog[0][1].bass_pc]
    cost = [{b: (0 if b == prog[i][1].bass_pc else 4.5 if b == prog[i][1].pcs[2] else 2.5) for b in cs} for i, cs in enumerate(cands)]; back = [{} for _ in cands]
    for i in range(1, len(cands)):
        for b in cands[i]:
            best = min(cands[i - 1], key=lambda a: cost[i - 1][a] + min((a - b) % 12, (b - a) % 12))
            cost[i][b] += cost[i - 1][best] + min((best - b) % 12, (b - best) % 12); back[i][b] = best
    b = min(cost[-1], key=cost[-1].get); line = [b]
    for i in range(len(cands) - 1, 0, -1): b = back[i][b]; line.append(b)
    return [(n, c.moved(bass=bp)) for (n, c), bp in zip(prog, line[::-1])]

def cycle(prog, steps):
    """repeat / cut a progression to exactly `steps` sixteenths"""
    out, pos, i = [], 0, 0
    while pos < steps:
        n, c = prog[i % len(prog)]; n = min(n, steps - pos); out.append((n, c)); pos += n; i += 1
    return out

# ---- voicings ----------------------------------------------------------------------------------------------------------------
SPAN = {"close": (0, 13, 9, 1), "rootless": (5, 17, 10, 1), "drop2": (10, 21, 10, 3), "spread": (16, 28, 12, 5)}     # style: (min span, max span, max gap, min bottom gap)

def arrangements(tones, lo, hi, max_gap=12):
    """every way to stack the pitch classes `tones` (each used once) upward from a bottom note in [lo, lo + 11]: the next voice is
    the nearest pitch above or an octave higher. Ascending midi lists with the top <= hi."""
    out = []
    def grow(v, rest):
        if not rest: out.append(v); return
        for i, p in enumerate(rest):
            g = (p - v[-1]) % 12 or 12
            for gap in (g, g + 12):
                if gap <= max_gap and v[-1] + gap <= hi: grow(v + [v[-1] + gap], rest[:i] + rest[i + 1:])
    for i, p in enumerate(tones):
        for b0 in range(lo, lo + 12):
            if b0 % 12 == p: grow([b0], tones[:i] + tones[i + 1:])
    return out

def candidates(chord, style, lo, hi, n=4, key=None, add=None, loose=False):
    """every placement of the chord in [lo, hi] for a voicing style -> list of ascending midi lists.
    close: within an octave; drop2: open, a tenth to a twelfth wide; rootless: 3rd, 7th and the colours (the root is the bass
    player's); spread: wide, a fifth or more at the bottom; quartal: stacked scale fourths."""
    c = chord; third, fifth = c.pcs[1], c.pcs[2]; sev = c.pcs[3] if len(c.pcs) > 3 else None; ext = c.pcs[4:]
    if style == "quartal":
        sc, _ = c.scale(key); out = []
        for st in sc:                                                                 # stacks of scale fourths (3 scale steps up)
            i = sc.index(st); tones = [sc[(i + 3 * k) % len(sc)] for k in range(n)]
            if len(set(tones)) < n or any(c.role(t, key) == "avoid" for t in tones): continue
            if not ({third, sev} & set(tones)): continue                              # it must still say which chord it is
            for b in range(lo, lo + 12):
                if b % 12 == tones[0]:
                    v = [b]
                    for t in tones[1:]: v.append(v[-1] + ((t - v[-1]) % 12 or 12))
                    if v[-1] <= hi: out.append(v)
        return out or candidates(c, "close", lo, hi, n, key)
    if ext: tones = [third, sev, ext[-1]] + ([ext[0]] if len(ext) > 1 else [fifth])     # with a 9th or more the root belongs to the bass
    elif style == "rootless" and sev is not None: tones = [third, fifth, sev, c.root]
    else: tones = [c.root, third, fifth] + ([sev] if sev is not None else [])
    tones = list(dict.fromkeys(tones))[:max(n, 3)]; mn, mx, gap, bot = SPAN.get(style, SPAN["drop2"])
    if add is not None and add not in tones:                                         # a melody note that is not in the voicing takes the 5th's place
        tones = [p for p in tones if p != (fifth if fifth in tones and len(tones) > 3 else None)] + [add]
    if len(tones) < 4: mn = min(mn, 7)                                               # a triad cannot be as wide
    allv = arrangements(tones, lo, hi, gap)
    if loose: return sorted(allv, key=lambda v: abs((v[-1] - v[0]) - (mn + mx) / 2))       # any width, the style's own first
    out = [v for v in allv if mn <= v[-1] - v[0] <= mx and v[1] - v[0] >= bot]
    return out or sorted(allv, key=lambda v: abs((v[-1] - v[0]) - (mn + mx) / 2))[:8] or [sorted(lo + ((p - lo) % 12) for p in tones)]

def _bad(v, chord):
    """penalties inside one voicing: minor ninths between voices (unless a dominant's b9), thirds too low, a semitone under the top"""
    pen = 0.0
    for i, a in enumerate(v):
        for b in v[i + 1:]:
            if (b - a) in (13, 25) and chord.family != "dom": pen += 12                 # a minor ninth between two voices
            if (b - a) == 1: pen += 12                                                 # a semitone cluster (it also rubs against any layer that doubles a voice)
        if i + 1 < len(v) and v[i + 1] - a == 6 and a < 60: pen += 1.5                 # a tritone low in the voicing is harsh
    if len(v) > 1:
        if v[0] < 48 and v[1] - v[0] < 5: pen += 5                                     # low interval limit
        if v[0] < 55 and v[1] - v[0] < 3: pen += 3
        if v[-1] - v[-2] == 1: pen += 5                                                # the top voice must sing clearly
    return pen

def lead(slots, style="drop2", lo=50, hi=76, n=4, key=None, top=None):
    """voice-led voicings for a chord sequence: [(Chord, ...)] -> [[midi ...]]. The path with the least motion and the fewest rubs is
    chosen over the WHOLE sequence (dynamic programming). top: optional list of midi notes (or None) that must be the top voice."""
    rub = lambda v, ch: any((b - a) == 1 or ((b - a) in (13, 25) and ch.family != "dom") for i, a in enumerate(v) for b in v[i + 1:])
    C = []; pool = {}
    for i, ch in enumerate(slots):
        if ch not in pool:
            cs = candidates(ch, style, lo, hi, n, key); pool[ch] = [v for v in cs if not rub(v, ch)] or cs      # no semitone / minor ninth between voices if any placement avoids it
        cs = pool[ch]
        if top is not None and top[i] is not None:
            want = top[i]; fit = [[x + (want - v[-1]) for x in v] for v in cs if (v[-1] - want) % 12 == 0]
            fit = [v for v in fit if v[0] >= lo - 5 and v[-1] <= hi + 5] or fit
            if not [v for v in fit if not rub(v, ch)]:                                # no clean placement under this melody note in the style's width:
                alt = candidates(ch, style, lo - 7, hi, n, key, add=want % 12, loose=True)   # voice the chord around the note, any width
                more = [[x + (want - v[-1]) for x in v] for v in alt if (v[-1] - want) % 12 == 0]; more = [v for v in more if v[0] >= lo - 7 and not rub(v, ch)][:12]
                fit = more or fit
            cs = [v for v in fit if not rub(v, ch)] or fit or cs
        C.append(cs)
    memo = {}
    def moves(U, V):                                                              # (len U, len V) motion cost, cached per pair of candidate sets
        k = (id(U), id(V))
        if k not in memo:
            M = np.empty((len(U), len(V)), np.float32)
            for j, u in enumerate(U):
                for q, v in enumerate(V):
                    m = min(len(u), len(v)); M[j, q] = sum(abs(a - b) for a, b in zip(u[-m:], v[-m:])) / m + .8 * abs(u[-1] - v[-1]) + .3 * abs(len(u) - len(v))
            memo[k] = M
        return memo[k]
    mid = (lo + hi) / 2 + 4; own = lambda i: np.array([_bad(v, slots[i]) + abs(v[-1] - mid) * .05 for v in C[i]], np.float32)
    cost = [own(0)]; back = [np.zeros(len(C[0]), int)]
    for i in range(1, len(C)):
        T = cost[-1][:, None] + moves(C[i - 1], C[i]); back.append(T.argmin(0)); cost.append(T.min(0) + own(i))
    j = int(np.argmin(cost[-1])); path = [j]
    for i in range(len(C) - 1, 0, -1): j = int(back[i][j]); path.append(j)
    return [C[i][j] for i, j in enumerate(path[::-1])]

# ---- the plan of a track --------------------------------------------------------------------------------------------------------
ROLES = ("intro", "home", "journey", "break", "build", "outro")
def role_of(name):
    """section name -> harmonic role, by what the name starts with (a trailing number is ignored: home2, journey1; "a" / "b" alone
    are home / journey). Unknown names are home."""
    n = name.lower().rstrip("0123456789_ ")
    if n in ("a", "b", "c"): return "home" if n == "a" else "journey"
    for r, keys in (("intro", ("intro", "step", "start")), ("break", ("break", "bridge", "pit")), ("build", ("build", "rise")), ("outro", ("outro", "end")),
                    ("journey", ("journey", "trip", "excursion", "half")), ("home", ("home", "main", "drop", "chop", "peak"))):
        if any(n.startswith(k) for k in keys): return r
    return "home"

class Plan:
    """the chords of the whole track: self.slots = [(start_step, length, Chord, section_name)]"""
    def __init__(self, tonic, mode, bars, slots, meta=None):
        self.tonic = pc_of(tonic); self.mode = mode; self.bars = bars; self.slots = slots; self.key = key_pcs(self.tonic, mode); self.meta = meta or {}
        self._starts = np.array([s[0] for s in slots])

    @classmethod
    def build(cls, tonic, sections, home, journey=None, seed=0, roles=None, journey_shift=0, colour=0, slide=.4, lean=.4):
        """sections: [(bar_a, bar_b, name, ...)] (Track.tl works). home / journey: idiom names (journey None = the home sentence
        re-harmonised: inversions + turnaround). roles: {section name: role} to override role_of(). journey_shift: semitones the
        journey's tonic sits above the home tonic (3 = relative major of a minor home). colour: +1 richer, -1 plainer chords.
        slide / lean: how often passing chords and early changes appear (0..1)."""
        rng = np.random.default_rng([seed, 134]); t = pc_of(tonic); H = sentence(home, t); mode = IDIOMS[home]["mode"]
        if colour: H = extend(H, colour)
        J = sentence(journey, (t + journey_shift) % 12) if journey else turnaround(inversions(extend(H, 1)), t, "backdoor")
        slots = []; nb = 0; count = {}
        for sec in sections:
            a, b, name = int(sec[0]), int(sec[1]), sec[2]; nb = max(nb, b)
            if b <= a: continue
            r = (roles or {}).get(name) or role_of(name); k = count.get(r, 0); count[r] = k + 1; steps = (b - a) * 16
            if r == "home":
                A = H; A2 = turnaround(passing(push(extend(H, 1) if k % 2 else H, rng, lean), rng, slide), t, ("sus", "backdoor", "neapolitan")[k % 3])
                prog = cycle(A + A2, steps)                                           # A A' pairs: the sentence, then its varied answer
            elif r == "journey": prog = cycle(J + passing(push(J, rng, lean), rng, slide), steps)
            elif r in ("intro", "outro"): prog = cycle(pedal(merge(extend(H, -1), 32), t), steps)
            elif r == "break":                                                        # two long chords over the tonic: home, then the sentence's far point
                calm = [c for _, c in H if c.family in ("minor", "major", "sus")] or [c for _, c in H]      # no dominant held for four bars over the pedal
                far = max(calm, key=lambda c: (c.root != H[0][1].root, c.tension(t, key_pcs(t, mode))))
                prog = cycle(extend(pedal([(64, H[0][1]), (64, far)], t), 1), steps)
            else: prog = cycle(pedal(merge(H, 32), (t + 7) % 12)[:-1] + [(32, Chord(t + 7, "13sus4"))], steps)      # build: dominant pedal
            pos = a * 16
            for n, c in prog: slots.append((pos, n, c, name)); pos += n
        return cls(t, mode, nb, slots, {"home": home, "journey": journey or f"{home} (reharmonised)", "journey_shift": journey_shift, "seed": seed})

    def idx(self, step):
        return int(np.clip(np.searchsorted(self._starts, step, side="right") - 1, 0, len(self.slots) - 1))
    def at(self, step):
        """the Chord sounding at an absolute 16th step"""
        return self.slots[self.idx(step)][2]
    def chord_of_bar(self, bar):
        """pitch classes at the start of a bar (the engine's older helpers ask for this)"""
        return self.at(bar * 16).pcs
    def root_of_bar(self, bar):
        return self.at(bar * 16).bass_pc
    def role(self, step, midi):
        return self.at(step).role(midi % 12, self.key)
    def tension(self):
        """per bar 0..1"""
        return [self.at(b * 16).tension(self.tonic, self.key) for b in range(self.bars)]
    def voicings(self, style="drop2", lo=50, hi=76, n=4, top=None):
        """[(start_step, length, [midi ...])] for every slot, voice-led across the whole track"""
        v = lead([s[2] for s in self.slots], style, lo, hi, n, self.key, top)
        return [(s[0], s[1], vv) for s, vv in zip(self.slots, v)]
    def bass(self, rng, lo=28, hi=45, style="root", cell=None, approach=.6, legato=.85, against=None):
        """[(step_abs, len, midi, vel)]. style "root": the chord's bass note on every change, root / octave / fifth / seventh between;
        "line": bass notes re-chosen for a stepwise line (inversions); "pedal": the tonic throughout. Before a change the last
        short note may become an APPROACH note a semitone or a scale step from the next bass note. cell: 16th steps of one bar
        (default: a new syncopated cell every 8 bars, its 4th bar varied). against: the voicings that sound above (Plan.voicings):
        a bass note that would sit a minor ninth under one of their notes falls back to the chord's bass note."""
        from .bass import bass_cell
        from .lines import context, clean
        ctx = context(self, against) if against else None
        slots = self.slots
        if style == "line":
            pr = inversions([(s[1], s[2]) for s in slots], strict_first=True); slots = [(s[0], s[1], c, s[3]) for s, (_, c) in zip(slots, pr)]
        starts = np.array([s[0] for s in slots]); at = lambda st: slots[int(np.clip(np.searchsorted(starts, st, side="right") - 1, 0, len(slots) - 1))]
        fold = lambda pc, near: min((m for m in range(lo, hi + 1) if m % 12 == pc), key=lambda m: (abs(m - near), m))
        on = []
        for bar in range(self.bars):
            if cell is None and bar % 8 == 0: cur = bass_cell(rng, on_kick=False, onsets=(3, 5)); var = sorted(set(cur[:-1]) | {int(rng.choice([11, 13, 14, 15]))})
            c = cell if cell is not None else (var if bar % 4 == 3 else cur)
            ch_on = {s[0] - bar * 16 for s in slots if bar * 16 <= s[0] < (bar + 1) * 16 and (s[0] % 2 == 0 or s[0] % 16 in c)}     # the bass marks every change
            on += [bar * 16 + s for s in sorted(ch_on | {s for s in c if s - 1 not in ch_on})]                      # ... and gives that note room
        out = []; prev = lo + 7
        for i, st in enumerate(on):
            s0, n, ch, _ = at(st); nxt_on = on[i + 1] if i + 1 < len(on) else st + 4; ln = max(1, min(nxt_on - st, 6))
            bp = self.tonic if style == "pedal" else ch.bass_pc; first = (i == 0) or at(on[i - 1])[0] != s0
            if first: m = fold(bp, lo + 5 if bp != self.tonic else lo); vel = 104
            else:
                opts = [bp, bp, (ch.root + 7) % 12 if (ch.root + 7) % 12 in ch.pcs else bp] + ([(ch.root + 10) % 12] if 10 in ch.iv else [])   # root, fifth, flat seventh
                pc = int(rng.choice(opts)); m = fold(pc, prev + (12 if pc == bp and rng.random() < .3 else 0)); vel = 84 if st % 4 else 94
                if ln >= 2 and not clean(m, st, ln, ctx): m = fold(bp, prev)
            nb = at(nxt_on); nbp = self.tonic if style == "pedal" else nb[2].bass_pc; changing = nb[0] != s0 and nbp != bp
            if changing and not first and ln <= 3 and rng.random() < approach:      # approach the next bass note by a semitone or a scale step
                tgt = fold(nbp, lo + 5 if nbp != self.tonic else lo); side = -1 if tgt > prev else 1; chrom = rng.random() < .6
                m = tgt + side if chrom else next((x for x in (tgt + 2 * side, tgt + side) if x % 12 in self.key), tgt + side); vel = 76
                m = int(np.clip(m, lo, hi)); ln = 1 if chrom or not clean(m, st, 2, ctx) else min(ln, 2)      # a chromatic approach is a 16th, no longer
            out.append((st, max(1, int(round(ln * legato))) if ln > 1 else 1, int(m), vel)); prev = m
        return out
    def describe(self):
        """a chord chart by section, e.g. {"home1": "Cm9 | F13 . Bbmaj9 | Cm11 ..."} (bars separated by |, changes inside a bar by .)"""
        out = {}
        for s0, n, c, name in self.slots:
            out.setdefault(name, []).append((s0, c.name))
        txt = {}
        for name, xs in out.items():
            bars = {}
            for s0, nm in xs: bars.setdefault(s0 // 16, []).append((s0 % 16, nm))
            b0 = min(bars); b1 = max(bars); seq = []
            for b in range(b0, min(b1, b0 + 15) + 1):
                cur = bars.get(b); seq.append(" . ".join((["%"] if cur[0][0] else []) + [nm for _, nm in cur]) if cur else "%")
            txt[name] = " | ".join(seq)
        return txt
    def fingerprint(self):
        """the harmony as a key-independent string (degree:quality per change of the first home and journey sections): equal strings
        in two tracks = the same progression again"""
        seen, out = set(), []
        for s0, n, c, name in self.slots:
            r = role_of(name)
            if r in ("home", "journey") and (r not in seen or name == out[-1][0]):
                if r not in seen: seen.add(r); out.append([name, []])
                if len(out[-1][1]) < 12: out[-1][1].append(f"{(c.root - self.tonic) % 12}:{c.qual}")
        return " || ".join(" ".join(x[1]) for x in out)
    def attach(self, trk):
        """tell the track which harmony it has (summary, freshness ledger)"""
        trk.harmony = {"tonic": NAMES[self.tonic], "mode": self.mode, **self.meta, "chart": self.describe(), "fingerprint": self.fingerprint(),
                       "chords": len({s[2] for s in self.slots}), "tension": [round(x, 2) for x in self.tension()]}
        return self
