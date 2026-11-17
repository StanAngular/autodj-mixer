"""P137 (2026-11-17, Стас: «новая гармония сложнее, но не гармонична: старая мелодичнее, даже по твоим демо слышно»).
Ears for HARMONY. The engine checked semitone rubs between layers (harmony.clashes) and nothing else, so a track could pass every
check and still sound «not harmonious». Measured on the P136 demos (old four-chord loop vs the jazz palette) the ear's verdict
followed these numbers, not roughness:

                                  old loop      jazz palette
  notes outside the scale         0.1 %         3 - 7.5 %       chromatic chords smear the key
  chords outside the scale        0 %           23 - 43 %
  key clarity (Krumhansl)         .92 - .95     .79 - .83       4-bar windows correlated with the 24 key profiles
  lead's held notes on the triad  50 - 75 %     34 - 42 %       a melody leaning on 9 / 11 / 13 sounds «off»
  lead repeats itself             43 %          0 - 14 %        a hook that changes with every chord is not remembered
  roughness (Sethares)            .30 - .35     .26 - .31       (not the cause: spread jazz voicings are even smoother)

report(trk) reads what every tonal layer played (Track.log_notes), the chords (Plan.attach -> trk.plan, or estimated per bar),
and the lead line (META["lead"] or the first of hook / lead / melody / riff / vocal / top) and returns the numbers, two scores
0..1 (harmony / melody) and `notes` in plain words. Always on, never blocks; gates are opt-in through META["gates"]:
  tonal_out_of_key_max (.02), tonal_clarity_min (.85), tonal_chords_out_max (.15), lead_triad_min (.5), lead_repeat_min (.5)."""
import numpy as np
from .depth import is_drum

NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MAJOR = np.array([0, 2, 4, 5, 7, 9, 11])
KK_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NORMS = {"out_of_key": .02, "chords_out": .15, "clarity": .85, "section_clarity": .80, "lead_triad": .5, "lead_repeat": .5, "dense_p90": 7, "changes_per_bar": 1.25}
TAILS = (("pad", .8), ("string", .8), ("choir", .8), ("drone", 1.0), ("atmo", 1.0), ("rhodes", .4), ("piano", .5), ("keys", .3))
LEADS = ("hook", "lead", "melody", "riff", "vocal", "top")

def tail_of(name, tails=None):
    """seconds of release that are still clearly heard after note-off (half of a typical release), by layer name"""
    if tails and name in tails: return float(tails[name])
    n = name.lower(); return next((t for k, t in TAILS if k in n), .1)

def grid(notes, step_s, n_steps, tails=None, skip=()):
    """per 16th step: [(midi, amp 0..1, layer)] of every tonal note that sounds there (onset to note-off plus the audible tail)"""
    g = [[] for _ in range(n_steps)]
    for name, ev in notes.items():
        if name in skip or is_drum(name): continue
        tl = tail_of(name, tails)
        for t, m, v, d in ev:
            a = int(round(t / step_s)); b = int(np.ceil((t + d + tl) / step_s))
            for k in range(max(0, a), min(n_steps, max(a + 1, b))): g[k].append((int(m), float(v) / 127, name))
    return g

def histogram(cells):
    h = np.zeros(12)
    for cell in cells:
        for m, a, _ in cell: h[m % 12] += a
    return h

def best_collection(h):
    """the diatonic collection (7 notes of a major scale) holding most of the weight -> (share inside, set of pcs)"""
    if h.sum() <= 0: return 1.0, set(MAJOR.tolist())
    share, r = max((h[(MAJOR + r) % 12].sum() / h.sum(), r) for r in range(12)); return float(share), set(((MAJOR + r) % 12).tolist())

def best_key(h):
    """(correlation, tonic pc, "major" | "minor") by the Krumhansl-Kessler profiles"""
    if h.sum() <= 0 or np.std(h) == 0: return 0.0, 0, "minor"
    return max((float(np.corrcoef(np.roll(p, k), h)[0, 1]), k, md) for k in range(12) for p, md in ((KK_MAJ, "major"), (KK_MIN, "minor")))

def clarity(g, bars, window=4):
    """key clarity: correlation of each `window`-bar stretch with its best key profile -> (mean, minimum)"""
    vals = []
    for b0 in range(0, max(1, bars - window + 1), window):
        h = histogram(g[b0 * 16:(b0 + window) * 16])
        if h.sum() > 0 and np.count_nonzero(h) >= 3: vals.append(best_key(h)[0])
    return (float(np.mean(vals)), float(np.min(vals))) if vals else (None, None)

TRIADS = [((r + 0) % 12, (r + 4) % 12, (r + 7) % 12) for r in range(12)] + [((r + 0) % 12, (r + 3) % 12, (r + 7) % 12) for r in range(12)]
def estimate_chords(g, bars, exclude=()):
    """no plan attached: the major / minor triad that holds most of each bar's accompaniment (all tonal layers except `exclude`)"""
    out = []
    for b in range(bars):
        h = np.zeros(12)
        for cell in g[b * 16:(b + 1) * 16]:
            for m, a, n in cell:
                if n not in exclude: h[m % 12] += a * (1.5 if m < 55 else 1.0)          # the bass and low voices weigh more
        out.append(list(max(TRIADS, key=lambda t: h[list(t)].sum() + .3 * h[t[0]])) if h.sum() > 0 else [])
    return out

def lead_stats(events, step_s, bars, chord_pcs_at):
    """events (t, midi, vel, dur) of the lead -> share of held notes (>= 2 sixteenths) on the triad / on chord tones of the
    harmony under them, literal repetition at the lead's own period, range, share of steps, number of pitch classes"""
    ev = sorted((int(round(t / step_s)), max(1, int(round(d / step_s))), int(m)) for t, m, v, d in events)
    if not ev: return None
    held = [(s, ln, m) for s, ln, m in ev if ln >= 3 or (s % 4 == 0 and ln >= 2)]; ht = sum(ln for _, ln, _ in held) or 1     # notes the ear hears as harmony
    tri = sum(ln for s, ln, m in held if m % 12 in chord_pcs_at(s)[:3]) / ht; ct = sum(ln for s, ln, m in held if m % 12 in chord_pcs_at(s)) / ht
    per_bar = [set() for _ in range(bars)]
    for s, ln, m in ev:
        if 0 <= s // 16 < bars: per_bar[s // 16].add((s % 16, m))
    best, period = 0.0, None
    for P in (1, 2, 4, 8):
        sims = [len(per_bar[b] & per_bar[b - P]) / max(len(per_bar[b]), len(per_bar[b - P])) for b in range(P, bars) if per_bar[b] and per_bar[b - P]]
        if len(sims) >= 4 and np.mean(sims) > best + .02: best, period = float(np.mean(sims)), P
    iv = [abs(b[2] - a[2]) for a, b in zip(ev, ev[1:]) if b[0] - (a[0] + a[1]) <= 2]     # intervals between connected notes (not across a rest)
    return {"notes": len(ev), "held_on_triad": round(tri, 2), "held_on_chord": round(ct, 2), "repeat": round(best, 2), "period_bars": period,
            "range": max(m for *_, m in ev) - min(m for *_, m in ev), "steps": round(float(np.mean([i <= 2 for i in iv])), 2) if iv else None,
            "leaps_over_fifth": int(sum(i > 7 for i in iv)), "pitch_classes": len({m % 12 for *_, m in ev})}

def report(trk, lead=None, tails=None):
    """the tonal report of a built Track (JSON-ready)"""
    notes = {k: v for k, v in getattr(trk, "notes", {}).items() if v and not is_drum(k)}
    if not notes: return {"notes": [], "score": {}}
    S = trk.S16; bars = trk.bars; g = grid(notes, S, bars * 16, tails)
    h = histogram(g); cover, coll = best_collection(h); kc, kt, km = best_key(h)
    clar, clar_min = clarity(g, bars)
    secs = {}
    for sec in getattr(trk, "tl", []) or []:                                          # where is home, section by section
        a, b, name = int(sec[0]), int(sec[1]), sec[2]; hs = histogram(g[a * 16:b * 16])
        if hs.sum() > 0 and np.count_nonzero(hs) >= 3: c_, k_, m_ = best_key(hs); secs[name] = [f"{NAMES[k_]} {m_}", round(c_, 2)]
    sounding = [{m % 12 for m, a, n in cell if m >= 48} for cell in g if len(cell) >= 2]
    dens = [len(x) for x in sounding] or [0]
    outside = {}
    for cell in g:
        for m, a, n in cell:
            if m % 12 not in coll: outside.setdefault(NAMES[m % 12], {}).setdefault(n, 0); outside[NAMES[m % 12]][n] += a
    plan = getattr(trk, "plan", None); chords = None
    if plan is not None:
        names = [c.name for _, _, c, _ in plan.slots]; outc = [c.name for _, _, c, _ in plan.slots if any(p not in coll for p in c.pcs)]
        chords = {"distinct": len(set(names)), "outside_scale": round(len(outc) / max(1, len(names)), 2), "outside_names": sorted(set(outc))[:8],
                  "changes_per_bar": round(len(plan.slots) / max(1, bars), 2), "off_bar": round(float(np.mean([s0 % 16 != 0 for s0, *_ in plan.slots])), 2),
                  "source": "plan"}
        chord_at = lambda s: plan.at(s).pcs
    else:
        L0 = lead or next((n for k in LEADS for n in notes if n.lower().startswith(k)), None)
        est = estimate_chords(g, bars, exclude=(L0,) if L0 else ()); chord_at = lambda s: est[min(len(est) - 1, max(0, s // 16))]
        chords = {"distinct": len({tuple(c) for c in est if c}), "changes_per_bar": round(sum(a != b for a, b in zip(est, est[1:])) / max(1, bars), 2), "source": "estimated"}
    lead = lead or (getattr(trk, "meta_lead", None)) or next((n for k in LEADS for n in notes if n.lower().startswith(k)), None)
    ls = lead_stats(notes[lead], S, bars, chord_at) if lead in notes else None
    out_share = 1 - cover
    rep = {"key": f"{NAMES[kt]} {km}", "key_fit": round(kc, 2), "scale_cover": round(cover, 3), "out_of_key": round(out_share, 3),
           "out_of_key_notes": {k: sorted(v, key=v.get, reverse=True)[:3] for k, v in sorted(outside.items(), key=lambda kv: -sum(kv[1].values()))[:4]},
           "clarity": None if clar is None else round(clar, 3), "clarity_min": None if clar_min is None else round(clar_min, 3), "sections": secs,
           "pcs_at_once": round(float(np.mean(dens)), 2), "pcs_at_once_p90": float(np.percentile(dens, 90)), "chords": chords, "lead": lead, "lead_stats": ls}
    harm = .4 * max(0.0, 1 - out_share / .05) + .4 * (0 if clar is None else float(np.clip((clar - .7) / .2, 0, 1))) + .2 * (1 - (chords.get("outside_scale") or 0))
    mel = None if not ls else round(.5 * min(1.0, ls["held_on_triad"] / .7) + .5 * min(1.0, ls["repeat"] / .8), 2)
    rep["score"] = {"harmony": round(harm, 2), "melody": mel}
    rep["notes"] = notes_of(rep); return rep

def notes_of(rep):
    """plain-word hints (Russian) where the harmony is smeared"""
    N = NORMS; out = []; ch = rep.get("chords") or {}; ls = rep.get("lead_stats")
    if rep["out_of_key"] > N["out_of_key"]:
        who = ", ".join(f"{k} ({'/'.join(v)})" for k, v in list(rep["out_of_key_notes"].items())[:3])
        out.append(f"{rep['out_of_key']:.0%} времени звучат ноты вне звукоряда: {who}. Хроматика размывает лад — держи аккорды и линии в одной гамме")
    if ch.get("outside_scale", 0) > N["chords_out"]:
        out.append(f"аккорды вне звукоряда: {', '.join(ch['outside_names'][:6])} — {ch['outside_scale']:.0%} всех смен. Замени их аккордами той же гаммы (chords.diatonic)")
    if rep["clarity"] is not None and rep["clarity"] < N["clarity"]:
        out.append(f"тональность размыта: ясность {rep['clarity']:.2f} (у мелодичных треков от {N['clarity']}): слушатель не слышит, где «дом». "
                   "Возьми оборот с ясной тоникой (chords.idioms() даёт их первыми) или поставь тонику в бас")
    from .chords import role_of
    weak = [f"{n} ({k}, {c})" for n, (k, c) in (rep.get("sections") or {}).items() if c < N["section_clarity"] and role_of(n) not in ("build", "break")]   # tension is their job
    if weak: out.append("секции без ясного тонального центра: " + ", ".join(weak[:4]))
    if ch.get("changes_per_bar", 0) > N["changes_per_bar"] or ch.get("off_bar", 0) > .2:
        out.append(f"аккорды меняются {ch['changes_per_bar']} раза за такт" + (f", {ch['off_bar']:.0%} смен не на сильную долю" if ch.get("off_bar") else "") +
                   ": ухо не успевает за гармонией. Один аккорд на такт или на два")
    if rep["pcs_at_once_p90"] >= N["dense_p90"]:
        out.append(f"в плотных местах звучат {int(rep['pcs_at_once_p90'])} разных нот одновременно: гармония превращается в кластер. Разведи слои по регистрам или убери краски")
    if ls:
        if ls["held_on_triad"] < N["lead_triad"]:
            out.append(f"мелодия «{rep['lead']}» держит долгие ноты на тонах трезвучия только {ls['held_on_triad']:.0%} времени (у мелодичных от {N['lead_triad']:.0%}): "
                       "опора на 9 / 11 / 13 звучит «не туда». Долгие ноты — на 1, 3, 5 аккорда")
        if ls["repeat"] < N["lead_repeat"]:
            out.append(f"мелодия «{rep['lead']}» повторяется дословно на {ls['repeat']:.0%}: хук не успевает запомниться. Повторяй мотив, меняй только хвост")
        if ls["leaps_over_fifth"] > max(2, ls["notes"] // 25):
            out.append(f"в мелодии {ls['leaps_over_fifth']} скачков больше квинты: её трудно напеть")
    return out

def gates(rep, g):
    """opt-in gates -> problem strings"""
    g = g or {}; out = []
    if not rep or "out_of_key" not in rep: return out
    if "tonal_out_of_key_max" in g and rep["out_of_key"] > g["tonal_out_of_key_max"]: out.append(f"ноты вне звукоряда {rep['out_of_key']:.1%} > {g['tonal_out_of_key_max']:.1%}")
    if "tonal_clarity_min" in g and (rep["clarity"] or 0) < g["tonal_clarity_min"]: out.append(f"ясность тональности {rep['clarity']} < {g['tonal_clarity_min']}")
    ch = rep.get("chords") or {}
    if "tonal_chords_out_max" in g and ch.get("outside_scale", 0) > g["tonal_chords_out_max"]: out.append(f"аккордов вне звукоряда {ch['outside_scale']:.0%}: {ch.get('outside_names')}")
    ls = rep.get("lead_stats")
    if ls and "lead_triad_min" in g and ls["held_on_triad"] < g["lead_triad_min"]: out.append(f"мелодия на тонах трезвучия {ls['held_on_triad']:.0%} < {g['lead_triad_min']:.0%}")
    if ls and "lead_repeat_min" in g and ls["repeat"] < g["lead_repeat_min"]: out.append(f"мелодия повторяется {ls['repeat']:.0%} < {g['lead_repeat_min']:.0%}")
    return out
