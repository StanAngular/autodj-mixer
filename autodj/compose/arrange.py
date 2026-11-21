"""P156 + P157 (2026-11-21, audit 2): layers have FUNCTIONS and the track has an ENERGY ARC. Slate Harbor's kick «лупит втупую» (the same 4/4 hit
in every bar of every section, velocity 1.0/0.9) and the clap «забирает внимание, пользы нет» (2 and 4 everywhere); home1..home3 were within 0.5 dB:
no peak, no reason to keep listening. Here the arc decides how much each section carries and the drum plan follows it.

  energy_arc(sections)          {section name: energy 0..1}: intro low, homes RISE to the last home (the peak), journeys a little above the home
                                before them, break low, build ramps, outro low. Override any value with peaks={name: e}.
  section_gain_db(arc)          {name: dB} for the tonal layers: the peak +2.5 dB over the first home, the break and the outro below it
  drum_plan(sections, arc, rng) {"kick": [(bar, step, vel)], "clap": [...]} drawn from the arc:
      kick: a steady four in every home / journey bar with energy (>= 85 % of the beats: the club pulse stays), the phrase is MARKED: the last bar of
            every 8 drops beat 4 or gets a soft pickup on the last 16th, a ghost kick on the "a" of a beat every 4 bars at energy >= .7; intro/outro
            thin (beat 1 and 3, the four only in the last 4 bars of the intro); no kick in the break; build: four, then eighths in its last bar.
            Velocity: beat 1 accented, the others follow energy (softer when lower) and differ slightly.
      clap: has a JOB: none below energy .5; .5-.7 only on beat 4 (step 12); >= .7 on 2 and 4; at the peak a soft ghost before every 4th bar
            and a short roll into the next section.
  log_drums(trk, plan)          tell the track what the drums play (the static gate and the report read it)
  drum_static(trk)              {role: longest run of bars with the very same pattern}; DRUM_STATIC_MAX bars more = a problem line
The score still places the hits (its own samples / timing): for br, st, v in plan["kick"]: trk.place(buf, kick, mt.time(br, st, "kick"), v / 127)."""
import numpy as np
from .chords import role_of

DRUM_STATIC_MAX = 32
BASE = {"intro": .3, "break": .25, "build": .6, "outro": .3}

def energy_arc(sections, peaks=None):
    names = [s[2] for s in sections if int(s[1]) > int(s[0])]; roles = {n: role_of(n) for n in names}
    homes = [n for n in names if roles[n] == "home"]; arc = {}
    for i, n in enumerate(homes): arc[n] = round(.55 + .45 * (i / max(1, len(homes) - 1)), 2) if len(homes) > 1 else .8
    last = None
    for n in names:
        r = roles[n]
        if r == "home": last = arc[n]
        elif r == "journey": arc[n] = round(min(.95, (last if last is not None else .5) + .1), 2)
        else: arc[n] = BASE.get(r, .5)
    if homes: arc[homes[-1]] = 1.0
    arc.update(peaks or {}); return arc

def section_gain_db(arc, peak_db=2.5):
    """tonal layer gain per section relative to the first home: linear in energy, the peak +peak_db"""
    ref = min((e for e in arc.values() if e > .5), default=.55); span = max(1e-6, 1.0 - ref)
    return {n: round(float(np.clip((e - ref) / span * peak_db, -6.0, peak_db)), 2) for n, e in arc.items()}

def drum_plan(sections, arc, rng=None, phrase=8):
    rng = rng or np.random.default_rng(0); K, C = [], []
    for a, b, name, *_ in sections:
        a, b = int(a), int(b); e = arc.get(name, .5); r = role_of(name); n = b - a
        if n <= 0: continue
        nxt_roll = r == "home" and e >= .99
        for br in range(a, b):
            k = br - a; end8 = (k % phrase) == phrase - 1; last = br == b - 1
            if r == "break": steps = []
            elif r in ("intro", "outro"):
                full = (r == "intro" and k >= n - 4) or (r == "outro" and k < 4)
                steps = [0, 4, 8, 12] if full else [0, 8]
            elif r == "build": steps = list(range(0, 16, 2)) if last else [0, 4, 8, 12]
            else:
                steps = [0, 4, 8, 12]
                if end8: steps = [0, 4, 8] if rng.random() < .5 else [0, 4, 8, 12]                  # the phrase end breathes (beat 4 out) or ...
            vel = []
            for st in steps:
                base = 118 if st == 0 else int(92 + 20 * e); vel.append((br, st, int(np.clip(base + rng.integers(-4, 5), 60, 127))))
            if r in ("home", "journey") and end8 and 12 in steps: vel.append((br, 15, int(48 + 20 * e)))          # ... gets a soft pickup into the next phrase
            if r in ("home", "journey") and e >= .7 and k % 4 == 2: vel.append((br, int(rng.choice([3, 7, 11])), int(40 + 15 * e)))   # a ghost kick on an "a"
            K += vel
            if r in ("home", "journey", "build"):
                if e >= .7: cs = [4, 12]
                elif e >= .5: cs = [12]
                else: cs = []
                C += [(br, st, int(np.clip(80 + 30 * e + rng.integers(-5, 6), 50, 120))) for st in cs]
                if e >= .99 and k % 4 == 3: C.append((br, 15, 40))
                if nxt_roll and last: C += [(br, st, 40 + 6 * i) for i, st in enumerate((13, 14, 15))]
    return {"kick": sorted(K), "clap": sorted(C)}

def log_drums(trk, plan):
    trk.drum_events = {**getattr(trk, "drum_events", {}), **{k: list(v) for k, v in plan.items()}}; return trk

def drum_static(trk_or_events, bars=None):
    """{role: longest run of consecutive bars that repeat the bar before exactly (steps and velocity bands of 16)} (empty bars break a run)"""
    ev = trk_or_events if isinstance(trk_or_events, dict) else getattr(trk_or_events, "drum_events", {})
    out = {}
    for role, xs in (ev or {}).items():
        if not xs: continue
        n = (bars or (max(b for b, *_ in xs) + 1)); sig = [tuple() for _ in range(n)]
        by = {}
        for b, st, v in xs: by.setdefault(int(b), []).append((int(st), int(v) // 16))
        sig = [tuple(sorted(by.get(i, ()))) for i in range(n)]; run = best = 1 if sig[0] else 0
        for i in range(1, n):
            run = run + 1 if sig[i] and sig[i] == sig[i - 1] else (1 if sig[i] else 0); best = max(best, run)
        out[role] = best
    return out

def drum_static_problems(trk):
    return [f"ударный {r} играет один и тот же такт {n} тактов подряд (> {DRUM_STATIC_MAX}): дай ему план по секциям (arrange.drum_plan)" for r, n in drum_static(trk).items() if n > DRUM_STATIC_MAX]
