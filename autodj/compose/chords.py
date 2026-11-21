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

P137 (2026-11-17): the default is now palette="consonant" (one scale per section, one sweet colour per chord, idioms that state
their tonic; see CONSONANT, diatonic(), strength()). The P134 behaviour below stays available as palette="jazz".

    plan = chords.Plan.build("C", sections=trk.tl, home="pop_minor", journey="rise", seed=seed)     # C.idioms(mood) lists the choices
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

def idioms(mood=None, mode=None, palette="consonant", strong=True):
    """names of the sentences for a mood ("deep", "garage", "melodic", "dark", "dreamy", "lofi", "minimal") and/or a home mode family,
    clearest tonic first. palette "consonant" (default): the diatonic idioms (CONSONANT), by default only those that state their
    tonic clearly (strength >= STRONG; strong=False adds the modal ones); "jazz": the P134 ones (IDIOMS)"""
    minorish = ("minor", "aeolian", "dorian", "phrygian")
    src = CONSONANT if palette == "consonant" else IDIOMS
    out = [n for n, d in src.items() if d["moods"] and (mood is None or mood in d["moods"]) and (mode is None or (d["mode"] in minorish) == (mode in minorish))
           and (palette != "consonant" or not strong or strength(n) >= STRONG)]
    return sorted(out, key=lambda n: -strength(n)) if palette == "consonant" else out

def sentence(name, tonic):
    """an idiom in a key -> [(length in 16th steps, Chord)]"""
    t = pc_of(tonic); out = []
    for s in IDIOMS[name]["slots"]:
        out.append((int(round(s[2] * 16)), Chord((t + s[0]) % 12, s[1], None if len(s) < 4 else (t + s[3]) % 12)))
    return out

# ---- the consonant palette (P137) ----------------------------------------------------------------------------------------------
# Стас, 2026-11-17: «новая гармония сложнее, но не гармонична: старая мелодичнее». Measured on the P136 demos: the jazz palette put
# 23-43 % of the chords outside the key (chromatic slide chords, chromatic mediants, dorian and aeolian mixed inside one phrase, 7#9,
# neapolitan / tritone turnarounds), the key clarity fell from .83-.92 to .77-.81 and the hook, re-fitted to every new chord, no
# longer repeated. Depth in electronic music does not come from chromatic chords; it comes from the form, the voicing, the lines
# and the sound. The consonant palette (the default since P137) therefore keeps every section inside ONE scale, gives each chord
# ONE sweet colour, changes chords on the bar line and varies a progression with chords of the same scale.
CONSONANT = {   # cycle: scale degrees in semitones above the tonic, or (degree, forced quality, bass degree); per: bars per chord
 "epic_minor":   dict(mode="aeolian", per=1, cycle=[0, 8, 3, 10], moods=("melodic", "dreamy", "deep", "garage")),          # i VI III VII
 "night_loop":   dict(mode="aeolian", per=1, cycle=[0, 8, 5, (7, "7sus4")], moods=("deep", "melodic", "garage")),           # i VI iv v7sus4: the Night Shift loop
 "lament":       dict(mode="aeolian", per=1, cycle=[0, (0, "m7", 10), 8, 7], moods=("melodic", "dark", "deep")),          # i i/VII VI v: the bass walks down
 "descent":      dict(mode="aeolian", per=1, cycle=[0, 10, 8, 10], pedal=True, moods=("melodic", "dark", "minimal")),                   # i VII VI VII
 "pop_minor":    dict(mode="aeolian", per=1, cycle=[0, 5, 8, 7], moods=("garage", "lofi", "melodic")),                      # i iv VI v
 "rise":         dict(mode="aeolian", per=1, cycle=[8, 10, 0, 0], moods=("melodic", "dreamy")),                             # VI VII i i: the lift
 "minor_plagal": dict(mode="aeolian", per=2, cycle=[0, 5, 0, 8], moods=("deep", "minimal", "dark")),                        # i iv i VI
 "two_chord":    dict(mode="aeolian", per=2, cycle=[0, 8], moods=("minimal", "deep", "dark")),                              # i VI
 "dorian_lift":  dict(mode="dorian", per=2, cycle=[0, 5], pedal=True, moods=("deep", "garage", "minimal")),                             # i IV: the deep-house vamp
 "dorian_walk":  dict(mode="dorian", per=1, cycle=[0, 2, 3, 5], pedal=True, moods=("garage", "deep", "lofi")),                          # i ii III IV
 "dark_phrygian": dict(mode="phrygian", per=2, cycle=[0, 1, 0, 10], pedal=True, moods=("dark", "minimal")),                             # i bII i bVII
 "axis_major":   dict(mode="ionian", per=1, cycle=[0, 7, 9, 5], moods=("dreamy", "lofi", "melodic")),                       # I V vi IV
 "royal_road":   dict(mode="ionian", per=1, cycle=[5, 7, 4, 9], pedal=True, moods=("dreamy", "lofi", "garage")),                        # IV V iii vi
 "pop_major":    dict(mode="ionian", per=1, cycle=[9, 5, 0, 7], moods=("dreamy", "melodic")),                               # vi IV I V
 "lydian_two":   dict(mode="lydian", per=2, cycle=[0, 2], pedal=True, moods=("dreamy",)),                                                # I II
}
MODE_OF = {"minor": "aeolian", "major": "ionian"}
STRONG = .85      # an idiom whose own tonic it states at least this clearly (Krumhansl correlation) is offered by default
# pedal=True: a modal or floating idiom (dorian / phrygian / lydian vamps, the royal road, the VII-VI descent) does not say where
# home is by itself (.61-.74); over the tonic in the bass, the way deep house and techno play them, it does (.79-.91).

def collection(tonic, mode):
    """the seven notes of a mode on a tonic (pitch classes, scale order)"""
    return [(pc_of(tonic) + x) % 12 for x in MODES[MODE_OF.get(mode, mode)]]

def diatonic(tonic, mode, degree, level=1, qual=None, bass=None):
    """the chord on `degree` (semitones above the tonic) made of the mode's own notes, with a colour level:
    0 plain triad; 1 one sweet colour (minor tonic add9, other minor chords m7; major chords maj7 where the scale has the major 7th,
    else add9; a major tonic add9); 2 richer (m9, maj9, 6/9). qual forces a quality ("7sus4"). A degree whose triad is diminished
    becomes the chord a third below it, which holds the same two notes."""
    t = pc_of(tonic); coll = set(collection(t, mode)); r = (t + degree) % 12
    if r not in coll: raise ValueError(f"degree {degree} is not a note of {NAMES[t]} {mode}")
    b = None if bass is None else pc_of(bass)
    if qual: return Chord(r, qual, b)
    has = lambda iv: (r + iv) % 12 in coll
    if not has(7):                                                                    # diminished triad: the chord a third below
        r2 = next((r - k) % 12 for k in (4, 3) if (r - k) % 12 in coll and (r - k + 7) % 12 in coll)
        return diatonic(t, mode, (r2 - t) % 12, level, None, b)
    if has(3):
        q = ("m" if level <= 0 else ("madd9" if degree % 12 == 0 and has(2) else "m7" if has(10) else "madd9" if has(2) else "m") if level == 1
             else "m9" if has(10) and has(2) else "m7" if has(10) else "madd9" if has(2) else "m")
    else:
        q = ("" if level <= 0 else ("add9" if degree % 12 == 0 and has(2) else "maj7" if has(11) else "add9" if has(2) else "") if level == 1
             else "maj9" if has(11) and has(2) else "69" if has(9) and has(2) else "add9" if has(2) else "maj7" if has(11) else "")
    return Chord(r, q, b)

def tune(name, tonic, level=1, per=None):
    """a consonant idiom in a key -> 8 bars [(length in 16ths, Chord)] (over the tonic pedal when the idiom asks for it)"""
    d = CONSONANT[name]; per = per or d["per"]; one = []
    for e in d["cycle"]:
        deg, q, bd = (e, None, None) if isinstance(e, int) else (tuple(e) + (None, None))[:3]
        one.append((per * 16, diatonic(tonic, d["mode"], deg, level, q, None if bd is None else (pc_of(tonic) + bd) % 12)))
    out = cycle(one, 128)
    return pedal(out, tonic) if d.get("pedal") else out

_STRENGTH = {}
def strength(name):
    """how clearly an idiom states its own tonic: Krumhansl correlation of its 8 bars (chord tones by length, colours .6, the bass
    note once more) with the profile of its intended key. The old Night Shift loop: .90; below .80 a listener loses «home»."""
    if name not in _STRENGTH:
        from .tonal import KK_MAJ, KK_MIN
        p = tune(name, 0, 1) if name in CONSONANT else sentence(name, 0); h = np.zeros(12)
        for n, c in p:
            for i, pc in enumerate(c.pcs): h[pc] += n * (1.0 if i < 3 else .6)
            h[c.bass_pc] += n
        mode = (CONSONANT.get(name) or IDIOMS.get(name))["mode"]; minor = MODES[MODE_OF.get(mode, mode)][2] == 3
        _STRENGTH[name] = round(float(np.corrcoef(KK_MIN if minor else KK_MAJ, h)[0, 1]), 2)
    return _STRENGTH[name]

def diatonicise(prog, tonic, mode, level=1):
    """bring any progression into one scale: a root outside the scale moves to the nearest scale note, every chord is rebuilt from
    the scale's own notes (diatonic), a chord equal to the one before is merged into it, changes are moved to the nearest bar line"""
    t = pc_of(tonic); coll = collection(t, mode); out = []; pos = 0
    for n, c in prog:
        r = c.root if c.root in coll else min(coll, key=lambda p: (min((p - c.root) % 12, (c.root - p) % 12), -sum(q in c.pcs for q in collection(p, "ionian"))))
        ch = diatonic(t, mode, (r - t) % 12, level)
        if c.bass is not None and c.bass in coll and c.bass in ch.pcs + [t]: ch = ch.moved(bass=c.bass)
        a, b = int(round(pos / 16)) * 16, int(round((pos + n) / 16)) * 16; pos += n
        if b <= a: continue
        if out and out[-1][1] == ch: out[-1] = (out[-1][0] + b - a, ch)
        else: out.append((b - a, ch))
    return out

def substitute(c, tonic, mode, rng, level=1, avoid=()):
    """a chord of the same scale that shares two notes with c (its third-related neighbour): the variation that keeps the melody"""
    t = pc_of(tonic); coll = set(collection(t, mode)); cands = []
    for k in (3, 4, -3, -4):
        r = (c.root + k) % 12
        if r in coll and (r + 7) % 12 in coll:
            ch = diatonic(t, mode, (r - t) % 12, level)
            if ch.root != c.root and ch not in avoid and len(set(ch.pcs[:3]) & set(c.pcs[:3])) >= 2: cands.append(ch)
    return cands[int(rng.integers(len(cands)))] if cands else c

def vary(prog, tonic, mode, rng, kind, level=1):
    """A' of a consonant sentence: kind 0 = the last chord replaced by its third-related neighbour (the melody fits both);
    kind 1 = the last two chords one colour richer and the last bass note re-chosen for a step into the next sentence"""
    prog = list(prog)
    if kind % 2 == 0:
        n, c = prog[-1]; prog[-1] = (n, substitute(c, tonic, mode, rng, level, avoid=[prog[0][1]] + ([prog[-2][1]] if len(prog) > 1 else [])))
    else:
        for i in (-2, -1): n, c = prog[i]; prog[i] = (n, diatonic(tonic, mode, (c.root - pc_of(tonic)) % 12, level + 1, None, c.bass) if not c.qual.endswith("sus4") else c)
        first = prog[0][1].bass_pc; n, c = prog[-1]; opts = [p for p in c.pcs[:3] if min((p - first) % 12, (first - p) % 12) <= 2]
        if opts and c.qual not in ("7sus4",): prog[-1] = (n, c.moved(bass=opts[0]) if opts[0] != c.root else c)
    return prog

def rise(tonic, mode, steps, level=1):
    """the build: chords of the scale climbing by step towards the tonic, made of the mode's own degrees without diminished triads
    (aeolian: iv v VI VII, dorian: III IV v VII, ionian: ii iii IV V)"""
    mm = MODES[MODE_OF.get(mode, mode)]; minor = mm[2] == 3; coll = set(collection(tonic, mode)); t = pc_of(tonic)
    ok = [d for d in mm[1:] if (t + d + 7) % 12 in coll and (not minor or True) and (minor or d <= 7)]
    degs = ok[-4:]; n = max(1, steps // len(degs)); prog = [(n, diatonic(tonic, mode, d, level)) for d in degs]
    return cycle(prog, steps)

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


# ---- P147 / P148 (2026-11-21, audit of the composition core) --------------------------------------------------------------------
RECENT = 15                                       # P147: a progression heard in one of this many latest tracks may not open the next one
SIG_LEN = 4                                       # ... compared by its first chords (degree:quality), so a re-ordered tail does not hide a repeat

class HarmonyRepeat(ValueError):
    """P147: the home progression of this track opens like one of the latest tracks"""

def signature(fp, n=SIG_LEN):
    """key-independent opening of a harmony fingerprint (the home section): its first n "degree:quality" chords"""
    return " ".join(((fp or "").split(" || ")[0]).split()[:n])

def recent_signatures(db=None, title=None, n=RECENT):
    """{signature: [titles]} of the n latest tracks with a harmony in the freshness ledger (this track's own title is skipped: a re-render is not a repeat)"""
    from . import fresh
    db = db if db is not None else fresh.load(); out = {}
    rows = [(t, e.get("harmony")) for t, e in db["tracks"].items() if e.get("harmony") and t != title][-n:]
    for t, fp in rows: out.setdefault(signature(fp), []).append(t)
    return out

def check_repeat(plan, title=None, db=None, rhythm=None):
    """P147: raise HarmonyRepeat when the plan's home progression opens like one of the RECENT latest tracks; the message names the tracks and
    lists idioms that do not (same tonic and mode family)"""
    seen = recent_signatures(db, title); sig = signature(plan.fingerprint())
    if not sig or sig not in seen: return
    alt = []
    for name in idioms(None, plan.mode):
        try: s2 = signature(" ".join(f"{(c.root - plan.tonic) % 12}:{c.qual}" for _, c in tune(name, plan.tonic, 1, rhythm)))
        except Exception: continue
        if s2 not in seen: alt.append(name)
    raise HarmonyRepeat(f"the home progression ({sig}) already opened {', '.join(seen[sig][-3:])}: choose another idiom"
                        + (f" (free now: {', '.join(alt[:6])})" if alt else "") + ". Only on Стас's request: Plan.build(..., allow_repeat=\"why\")")

def with_journey_role(sections, roles, journey):
    """P148: a journey idiom was ordered but no section has the journey role (verse / A2 / final all count as home): the middle home section
    takes it, so the second progression is heard. Returns (roles, assigned section name or None); one home section only -> nothing to assign."""
    if not journey: return roles, None
    rs = [(s[2], (roles or {}).get(s[2]) or role_of(s[2])) for s in sections if int(s[1]) > int(s[0])]
    if any(r == "journey" for _, r in rs): return roles, None
    homes = [n for n, r in rs if r == "home"]
    if len(homes) < 2: return roles, None
    pick = homes[len(homes) // 2]
    return {**(roles or {}), pick: "journey"}, pick

class Plan:
    """the chords of the whole track: self.slots = [(start_step, length, Chord, section_name)]"""
    def __init__(self, tonic, mode, bars, slots, meta=None, palette="jazz"):
        self.tonic = pc_of(tonic); self.mode = MODE_OF.get(mode, mode) if mode not in MODES else mode; self.bars = bars; self.slots = slots
        self.key = key_pcs(self.tonic, self.mode); self.meta = meta or {}; self.palette = palette
        mm = MODES[MODE_OF.get(self.mode, self.mode)]
        self.penta = {(self.tonic + x) % 12 for x in ((0, 3, 5, 7, 10) if mm[2] == 3 else (0, 2, 4, 7, 9))}   # the pentatonic of the key: passing notes that never rub
        self._starts = np.array([s[0] for s in slots])

    @classmethod
    def build(cls, tonic, sections, home, journey=None, seed=0, roles=None, journey_shift=None, colour=0, slide=None, lean=None, palette="consonant", rhythm=None, title=None, allow_repeat=None):
        """sections: [(bar_a, bar_b, name, ...)] (Track.tl works). home / journey: idiom names (journey None = the home sentence
        re-harmonised). roles: {section name: role} to override role_of(). colour: +1 richer, -1 plainer chords.
        palette "consonant" (default, P137): every section inside one scale, one sweet colour per chord, changes on the bar line,
        variations by chords of the same scale; jazz idioms given here are brought into the scale (diatonicise). journey_shift None:
        the journey stays in the home scale (a major idiom sits on the relative major). rhythm: bars per chord (1 or 2) instead of
        the idiom's own. palette "jazz": the P134 behaviour (chromatic slides, early changes, neapolitan / backdoor turnarounds,
        mixed modes); slide / lean: how often slides and early changes appear there (default .4).
        P147: inside `autodj.compose run` (the render's title is known) a home progression that opens like one of the RECENT latest tracks of the
        freshness ledger raises HarmonyRepeat; title= overrides the render's title; allow_repeat="reason" (a non-empty text, only on Стас's
        request) switches the check off and is written to meta. P148: a journey idiom without a journey section goes to the middle home section."""
        roles, promoted = with_journey_role(sections, roles, journey)
        plan = cls._build(tonic, sections, home, journey, seed, roles, journey_shift, colour, slide, lean, palette, rhythm)
        if promoted: plan.meta["journey_section"] = promoted
        elif journey and not any(role_of(s[2]) == "journey" or (roles or {}).get(s[2]) == "journey" for s in sections): plan.meta["journey_unused"] = True
        from . import fresh
        t = title or fresh.TITLE
        if allow_repeat:
            if isinstance(allow_repeat, str) and allow_repeat.strip(): plan.meta["repeat_allowed"] = allow_repeat.strip()
            else: raise ValueError('allow_repeat must be a reason text: allow_repeat="Стас asked for the old loop"')
        elif t: check_repeat(plan, t, rhythm=rhythm)
        return plan

    @classmethod
    def _build(cls, tonic, sections, home, journey, seed, roles, journey_shift, colour, slide, lean, palette, rhythm):
        if palette != "jazz": return cls._consonant(tonic, sections, home, journey, seed, roles, journey_shift, colour, slide or 0, lean or 0, rhythm)
        slide = .4 if slide is None else slide; lean = .4 if lean is None else lean; journey_shift = journey_shift or 0
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
        return cls(t, mode, nb, slots, {"home": home, "journey": journey or f"{home} (reharmonised)", "journey_shift": journey_shift, "seed": seed, "palette": "jazz"})

    @classmethod
    def _consonant(cls, tonic, sections, home, journey, seed, roles, journey_shift, colour, slide, lean, rhythm):
        rng = np.random.default_rng([seed, 137]); t = pc_of(tonic); level = 1 + colour; adapted = []
        def sent(name, tn, lv):
            if name in CONSONANT: return tune(name, tn, lv, rhythm), CONSONANT[name]["mode"]
            if name in IDIOMS:
                md = MODE_OF.get(IDIOMS[name]["mode"], IDIOMS[name]["mode"]); adapted.append(name); return diatonicise(sentence(name, tn), tn, md, lv), md
            raise ValueError(f"unknown idiom {name!r}: consonant {sorted(CONSONANT)}, jazz {sorted(IDIOMS)}")
        H, mode = sent(home, t, level); coll = set(collection(t, mode))
        if journey:
            jm = CONSONANT[journey]["mode"] if journey in CONSONANT else MODE_OF.get(IDIOMS.get(journey, {}).get("mode", ""), IDIOMS.get(journey, {}).get("mode", "aeolian"))
            if journey_shift is None:                                                 # stay in the home scale: find the tonic of the journey's mode in it
                journey_shift = next((k for k in range(12) if set(collection(t + k, jm)) == coll), 0)
            jt = (t + journey_shift) % 12; J, jmode = sent(journey, jt, level)
        else:
            jt, jmode, journey_shift = t, mode, 0; J = inversions([(n, diatonic(t, mode, (c.root - t) % 12, level + 1, c.qual if c.qual.endswith("sus4") else None)) for n, c in H])
        if slide or lean:                                                             # explicit wish: early changes / slides, but inside the scale
            J = push(J, rng, lean)
        slots = []; nb = 0; count = {}
        for sec in sections:
            a, b, name = int(sec[0]), int(sec[1]), sec[2]; nb = max(nb, b)
            if b <= a: continue
            r = (roles or {}).get(name) or role_of(name); k = count.get(r, 0); count[r] = k + 1; steps = (b - a) * 16
            if r == "home": prog = cycle(H + vary(H, t, mode, rng, k, level), steps)            # A A': the sentence, then the same sentence with one chord changed
            elif r == "journey": prog = cycle(J + vary(J, jt, jmode, rng, k + 1, level), steps)
            elif r in ("intro", "outro"): prog = cycle(pedal(merge([(n, diatonic(t, mode, (c.root - t) % 12, max(0, level - 1), c.qual if c.qual.endswith("sus4") else None)) for n, c in H], 32), t), steps)
            elif r == "break":                                                        # two long chords over the tonic, one colour richer
                calm = [c for _, c in H if c.family in ("minor", "major")] or [c for _, c in H]
                far = max(calm, key=lambda c: (c.root != H[0][1].root, c.family == "major", -abs(((c.root - t) % 12) - 6)))
                prog = cycle(pedal([(64, diatonic(t, mode, (H[0][1].root - t) % 12, level + 1)), (64, diatonic(t, mode, (far.root - t) % 12, level + 1))], t), steps)
            else: prog = rise(t, mode, steps, level)                                  # build: the scale climbs to the drop
            pos = a * 16
            for n, c in prog: slots.append((pos, n, c, name)); pos += n
        meta = {"home": home, "journey": journey or f"{home} (reharmonised)", "journey_shift": journey_shift, "seed": seed, "palette": "consonant", "scale": f"{NAMES[t]} {mode}",
                "strength": {k: strength(v) for k, v in (("home", home), ("journey", journey)) if v}}
        if adapted: meta["adapted"] = sorted(set(adapted))
        return cls(t, mode, nb, slots, meta, palette="consonant")

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
    def bass(self, rng, lo=28, hi=45, style="root", cell=None, approach=None, legato=.85, against=None):
        """[(step_abs, len, midi, vel)]. style "root": the chord's bass note on every change, root / octave / fifth / seventh between;
        "line": bass notes re-chosen for a stepwise line (inversions); "pedal": the tonic throughout. Before a change the last
        short note may become an APPROACH note a semitone or a scale step from the next bass note. cell: 16th steps of one bar
        (default: a new syncopated cell every 8 bars, its 4th bar varied). against: the voicings that sound above (Plan.voicings):
        a bass note that would sit a minor ninth under one of their notes falls back to the chord's bass note."""
        from .bass import bass_cell
        from .lines import context, clean
        ctx = context(self, against) if against else None; cons = self.palette == "consonant"
        if approach is None: approach = .25 if cons else .6                           # consonant: rarer approach notes, always on scale notes
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
                tgt = fold(nbp, lo + 5 if nbp != self.tonic else lo); side = -1 if tgt > prev else 1; chrom = (not cons) and rng.random() < .6
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
        trk.plan = self                                                               # P137: the tonal report reads the chords from here
        return self
