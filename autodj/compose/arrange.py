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

# ---- P165 (audit 3): drum_plan v2 = the whole kit from the energy arc AND a rhythm profile (rhythm_profiles) -----------------------------------------
def _lerp(lo, hi, e): return lo + (hi - lo) * float(np.clip(e, 0, 1))
def _db(v, db): return int(np.clip(v * 10 ** (db / 20), 1, 127))

def drum_plan_v2(sections, arc, profile, rng=None, phrase=8):
    """{"kick", "clap", "hats", "perc": [(bar, step, vel)], "ohat": [(bar, step, vel, length_s)]} for the sections (role_of: intro / home / journey / break / build / outro),
    shaped by the profile of the style (rhythm_profiles.profile): the kick FAMILY (four / two_step / half / broken / sparse), the backbeat from backbeat_min_energy
    (one beat below, both above, soft ghost notes before the next bar when ghost_backbeat), hats with accent_db contrast (the 2nd and 4th offbeat stronger) and
    16th ghosts (ghost_hat_db) from energy .7, the open hat ringing open_hat_s low..high energy, percussion perc_per_bar low..high with a cell that changes every
    8 bars (the density grows at the PEAK while the kick stays), and the BREATH: dropout_beats (<= 4) of silence for kick and perc at the end of the bar before a
    home (always before the peak), at most once in 16 bars, never inside a home. Nothing is written for a style that has none of it (ambient: no hats, no clap)."""
    rng = rng or np.random.default_rng(0); P = {**{"hat16": False, "shaker": False, "fill_every": 0, "clap": False}, **profile}; out = {k: [] for k in ("kick", "clap", "hats", "perc", "ohat", "shaker", "fill")}; last_drop = -99; bseed = int(rng.integers(0, 1 << 30))
    fam = P["kick_family"]; secs = [(int(a), int(b), name) for a, b, name, *_ in sections if int(b) > int(a)]
    for si, (a, b, name) in enumerate(secs):
        e = arc.get(name, .5); r = role_of(name); n = b - a; nxt = secs[si + 1] if si + 1 < len(secs) else None
        for br in range(a, b):
            k = br - a; end8 = (k % phrase) == phrase - 1; lastbar = br == b - 1; breath = 0
            if lastbar and nxt and role_of(nxt[2]) == "home" and P["dropout_beats"] and (br - last_drop >= 16) and r != "break":
                breath = int(P["dropout_beats"]); last_drop = br                                                              # the breath comes at the end of a section, never inside a home
            cut = 16 - 4 * breath if breath else 16                                                                            # steps >= cut are silent for kick and perc
            # -- kick
            if r == "break" and fam != "sparse": ks = []
            elif r in ("intro", "outro"): ks = ([0, 8] if fam != "sparse" else [0]) if not ((r == "intro" and k >= n - 4) or (r == "outro" and k < 4)) else {"four": [0, 4, 8, 12], "two_step": [0, 10], "half": [0, 10], "broken": [0, 10], "sparse": [0]}[fam]
            elif r == "build": ks = list(range(0, 16, 2)) if lastbar and fam in ("four", "two_step", "broken") else {"four": [0, 4, 8, 12], "two_step": [0, 10], "half": [0, 10], "broken": [0, 6, 10], "sparse": [0]}[fam]
            else:
                if fam == "four": ks = [0, 4, 8, 12]
                elif fam == "two_step": ks = [0, 10] if br % 2 == 0 else [0, 7, 10]
                elif fam == "half": ks = [0, 10] if br % 2 == 0 else [0, 6]
                elif fam == "broken": ks = [list(c) for c in ([0, 6, 10], [0, 3, 10], [0, 7, 10, 14], [0, 10])][int(rng.integers(0, 4))]
                else: ks = [0] if br % 2 == 0 else []
                if end8 and fam == "four": ks = [0, 4, 8] if rng.random() < .5 else [0, 4, 8, 12]
            for st in [x for x in ks if x < cut]: out["kick"].append((br, st, int(np.clip((118 if st == 0 else 92 + 20 * e) + rng.integers(-4, 5), 60, 127))))
            if breath: out["kick"].append((br, 15, int(40 + 15 * e)))                                                          # a soft pickup out of the breath
            # -- backbeat
            if P.get("clap") and r in ("home", "journey", "build") and e >= P["backbeat_min_energy"] and fam != "sparse":      # clap only when the score asks (Стас 2026-11-22)
                cs = {"half": [8], "four": [4, 12], "two_step": [4, 12], "broken": [4, 12]}[fam] if e >= P["backbeat_min_energy"] + .2 else ([12] if fam != "half" else [8])
                out["clap"] += [(br, st, int(np.clip(80 + 30 * e + rng.integers(-5, 6), 50, 120))) for st in cs]
                if P["ghost_backbeat"] and e >= .7 and k % 4 == 3: out["clap"].append((br, 15, 40))
            # -- hats
            hat_on = r != "break" and fam != "sparse" and (P["hat_accent_db"] > 0 or P["ghost_hat_db"] is not None or P["open_hat_s"][1] > 0)
            if hat_on:
                base = int(78 + 22 * e); strong, weak = _db(base, P["hat_accent_db"] / 2), _db(base, -P["hat_accent_db"] / 2)
                flip = (k % 4 == 3)                                                                                       # every 4th bar the accent moves to the other offbeats
                for st in (2, 6, 10, 14): out["hats"].append((br, st, strong if (st in (6, 14)) != flip else weak))
                if P["hat16"] and e >= .6:                                                  # P171: the steady 16th line of tech house (not random ghosts)
                    for st in (1, 3, 5, 7, 9, 11, 13, 15): out["hats"].append((br, st, _db(base, -P["ghost_hat_db"] if P["ghost_hat_db"] is not None else -10)))
                elif P["ghost_hat_db"] is not None and e >= .7 and k % 4 in (1, 3):
                    for st in sorted(rng.choice([1, 3, 5, 9, 11, 13], 3, replace=False).tolist()): out["hats"].append((br, int(st), _db(base, -P["ghost_hat_db"])))
                lo, hi = P["open_hat_s"]
                if hi > 0 and e >= .5 and br % 2 == 1 and not breath: out["ohat"].append((br, 14, int(np.clip(60 + 25 * e, 1, 127)), round(_lerp(lo, hi, e), 3)))
            if P["shaker"] and e >= .5 and r not in ("break",):                             # P171: shaker 16ths, accent on the 8th after each beat
                out["shaker"] += [(br, st, int(np.clip((70 if st % 4 == 2 else 46) + 20 * e + rng.integers(-4, 5), 1, 127))) for st in range(16) if st < cut]
            if P["fill_every"] and r in ("home", "journey") and (k % P["fill_every"]) == P["fill_every"] - 1 and not breath:   # P171: a machine fill into the next phrase
                out["fill"] += [(br, st, 50 + 12 * i) for i, st in enumerate((12, 13, 14, 15))]
            # -- percussion: the cell changes every 8 bars; the density follows the energy, the peak is denser
            lo, hi = P["perc_per_bar"]; cnt = int(round(_lerp(lo, hi, e))) if r in ("home", "journey", "build") else (min(1, hi) if r in ("intro", "outro") and hi else 0)
            if cnt:
                prng = np.random.default_rng([bseed, br // 8, cnt]); cell = sorted(prng.choice([3, 5, 7, 9, 11, 13, 14, 15], min(cnt, 8), replace=False).tolist())
                out["perc"] += [(br, st, int(40 + 30 * e + rng.integers(-5, 6))) for st in cell if st < cut and (br + st) % 5]
    return {k: sorted(v) for k, v in out.items()}

def log_drums(trk, plan):
    trk.drum_events = {**getattr(trk, "drum_events", {}), **{k: list(v) for k, v in plan.items()}}; return trk

def drum_static(trk_or_events, bars=None):
    """{role: longest run of consecutive bars that repeat the bar before exactly (steps and velocity bands of 16)} (empty bars break a run)"""
    ev = trk_or_events if isinstance(trk_or_events, dict) else getattr(trk_or_events, "drum_events", {})
    out = {}
    for role, xs in (ev or {}).items():
        if not xs: continue
        n = (bars or (max(x[0] for x in xs) + 1)); sig = [tuple() for _ in range(n)]
        by = {}
        for x in xs: by.setdefault(int(x[0]), []).append((int(x[1]), int(x[2]) // 16))
        sig = [tuple(sorted(by.get(i, ()))) for i in range(n)]; run = best = 1 if sig[0] else 0
        for i in range(1, n):
            run = run + 1 if sig[i] and sig[i] == sig[i - 1] else (1 if sig[i] else 0); best = max(best, run)
        out[role] = best
    return out

def drum_static_problems(trk):
    lim = lambda r: DRUM_STATIC_MAX * (2 if r == "clap" else 1)                                  # a steady backbeat is normal: the clap is held to twice the limit
    return [f"ударный {r} играет один и тот же такт {n} тактов подряд (> {lim(r)}): дай ему план по секциям (arrange.drum_plan)" for r, n in drum_static(trk).items() if n > lim(r)]
