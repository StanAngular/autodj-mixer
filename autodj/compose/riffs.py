"""P172 + P173 (2026-11-21, audit 4): the tech-house bass riff and the stab harmony.
  stab_plan(tonic, sections, rng)     a Plan with NO progression: the minor tonic chord (m7) everywhere, a move to iv or VI for the journeys (one colour, dark),
                                      no jazz turnaround; chords change at most every 8 bars
  rolling_bass(plan, rng, kick_steps, lo, hi, pattern=None)   1-2 notes, 16th grid, notes about one 16th long (80-150 ms at 124-128 BPM), on the offbeats
                                      BETWEEN the kicks; the riff is 1 bar (or 2) and changes only at phrase ends (every 8 bars a variant); root most of the time,
                                      the octave or the flat seventh as the second note
  stab_events(plan, rng, sections, arc)   offbeat stab hits of the tonic chord (one short chord), a new cell every 8 bars, absent in intro / break unless energy"""
import numpy as np
from . import chords as C

PATTERNS = ([2, 6, 10, 14], [1, 2, 5, 6, 9, 10, 13, 14], [2, 5, 7, 10, 13, 15], [2, 3, 6, 10, 14], [2, 6, 7, 10, 14, 15], [3, 6, 10, 13], [2, 5, 6, 10, 13, 14], [2, 6, 9, 10, 14])

def stab_plan(tonic, sections, rng=None, journey="iv"):
    rng = rng or np.random.default_rng(0); t = C.pc_of(tonic); slots = []
    for a, b, name, *_ in sections:
        a, b = int(a), int(b)
        if b <= a: continue
        r = C.role_of(name)
        if r == "journey":
            alt = (t + (5 if journey == "iv" else 8)) % 12; qual = "m7" if journey == "iv" else "maj7"
            for k, bar in enumerate(range(a, b, 8)): slots.append((bar * 16, min(8, b - bar) * 16, C.Chord(t if k % 2 else alt, "m7" if k % 2 else qual), name))
        else: slots.append((a * 16, (b - a) * 16, C.Chord(t, "m7"), name))
    nb = max(int(s[1]) for s in sections)
    return C.Plan(t, "aeolian", nb, slots, {"home": "stab_tonic", "journey": journey, "palette": "stab"}, palette="consonant")

def rolling_bass(plan, rng, kick_steps=None, lo=26, hi=42, pattern=None, phrase=8):
    """[(step_abs, len_16ths, midi, vel)]: the riff is chosen once, varied at every phrase end (the last bar of 8 gets a pickup / a moved note)"""
    rng = rng or np.random.default_rng(0); base = list(pattern or PATTERNS[int(rng.integers(0, len(PATTERNS)))]); out = []
    second = [int(rng.choice([12, 10]))]                                                   # the octave or the flat seventh above the root
    hits2 = set(int(x) for x in rng.choice(base, max(1, len(base) // 3), replace=False))   # which steps take the second note
    for bar in range(plan.bars):
        c = plan.at(bar * 16); root = min((m for m in range(lo, hi + 1) if m % 12 == c.bass_pc), key=lambda m: abs(m - (lo + 5)))
        steps = list(base)
        if bar % phrase == phrase - 1: steps = sorted(set(steps) | {15}) if 15 not in steps else sorted(set(steps) - {14})
        ks = set(kick_steps(bar) if callable(kick_steps) else (kick_steps or (0, 4, 8, 12)))
        for st in steps:
            if st in ks: continue
            m = root + (second[0] if st in hits2 else 0); m = m if m <= hi else m - 12
            out.append((bar * 16 + st, 1, int(m), 100 if st % 4 == 2 else 84))
    return out

def stab_events(plan, rng, sections, arc, phrase=8):
    rng = rng or np.random.default_rng(0); out = []; cells = [sorted(rng.choice([3, 6, 7, 10, 11, 14], 2, replace=False).tolist()) for _ in range(4)]
    for a, b, name, *_ in sections:
        e = arc.get(name, .5); r = C.role_of(name)
        if r in ("intro", "outro", "break") and e < .5: continue
        for bar in range(int(a), int(b)):
            c = plan.at(bar * 16); v = sorted({(c.root + iv) % 12 + 60 for iv in (0, 3, 7, 10)})
            for st in cells[(bar // phrase) % 4]: out += [(bar * 16 + st, 1, m, int(70 + 25 * e)) for m in v]
    return out
