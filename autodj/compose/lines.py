"""P135 (2026-11-12): melodic lines written AGAINST the harmony plan (chords.Plan). In the real scores the «line» is four chord
tones per bar typed in by hand (LN = {0: [67, 63, 62, 60], ...}) and the engine's hook is confined to 2-3 anchor notes: safe, and
flat. Here every note knows what it is over its chord (chord tone / colour 9-11-13 / avoid note) and what really sounds under it
(the voicing and the bass), so a line may use colours on long notes and passing notes between them and still never rub:

  context    what sounds at every 16th step (voicings + bass + other lines): the generators check real intervals against it
  motif      a 1-2 bar idea: syncopated rhythm, a contour, long notes on chord tones or colours, short notes passing by step
  hook       8 bars A A' A B from one motif; A' and B are the motif RE-FITTED to the chords under them (the idea stays, the notes
             follow the harmony)
  tile       put the hook anywhere in the track: over the journey's chords the same hook is re-harmonised, not transposed
  ostinato   a small pitch cell in a 3/16, 5/16, 6/16 ... cycle against the bar (polymeter); its notes are the ones that stay
             good over most chords, and only the note that would rub bends for that chord
  arp        the voicing's notes (plus one colour) run as a pattern that does not restart with the chord
  topline    one slow colour note per chord: give it to Plan.voicings(top=...) and the chords sing a melody on top
  counter    answers in the rests of a melody, on guide tones, moving the other way
  fit / fix  measure a line against the plan (held avoid notes, rubs, share of colours) and repair it

All lines are [(step_abs, len_16ths, midi, vel)]."""
import numpy as np

W16 = np.array([2.0, 1.0, 3.0, 2.0, 1.2, 1.0, 3.0, 2.0, 1.5, 1.0, 3.0, 2.0, 1.2, 1.0, 3.0, 1.5])     # where a syncopated line likes to start

def context(plan, voicings=None, bass=None, *lines):
    """what sounds at every 16th step: list (one per step) of midi lists. Voicings count for their whole slot (the harmony is in
    the air even between stabs); bass and other lines for their own lengths."""
    ctx = [[] for _ in range(plan.bars * 16 + 16)]
    for s, n, v in (voicings or []):
        for t in range(s, min(len(ctx), s + n)): ctx[t] += list(v)
    for ln in ((bass,) if bass else ()) + lines:
        for s, n, m, *_ in ln:
            for t in range(max(0, s), min(len(ctx), s + n)): ctx[t].append(m)
    return ctx

def clean(m, st, ln, ctx):
    """True if midi note m, held from step st for ln steps, is never a semitone / minor ninth from anything sounding"""
    if ctx is None: return True
    return not any(abs(m - x) in (1, 13, 25) for t in range(max(0, st), min(len(ctx), st + ln)) for x in ctx[t])

COLOUR = 4.3          # weight of a colour tone (9 / 11 / 13) on a strong note; guide tones (3rd, 7th) weigh 4.0, the root 2.2
def weight(plan, step, m, strong, colour=None):
    """how welcome pitch m is at a step: guide tones and colours on strong notes, anything in the chord scale in passing.
    colour: weight of 9 / 11 / 13 on strong notes (default COLOUR; 0 = chord tones only, the old way)"""
    c = plan.at(step); r = c.role(m % 12, plan.key)
    if r == "chord": return 4.0 if m % 12 in c.pcs[1:2] + c.pcs[3:4] else 2.2 if m % 12 == c.root else 3.0
    if r == "tension": return (COLOUR if colour is None else colour) if strong else 2.0
    if r == "avoid": return 0.0 if strong else .5
    return 0.0 if strong else (.3 if m % 12 in plan.key else 0.0)

def rhythm(rng, onsets=(3, 5), busy=(), last_long=True):
    """one bar: [(step, len)], syncopated, at least a 16th of air between notes, less likely where `busy` steps are taken"""
    w = W16.copy(); w[list(busy)] *= .2
    for _ in range(50):
        k = int(rng.integers(onsets[0], onsets[1] + 1)); st = sorted(rng.choice(16, k, replace=False, p=w / w.sum()).tolist())
        if all(b - a >= 2 for a, b in zip(st, st[1:])) and any(s % 4 for s in st): break
    out = []
    for i, s in enumerate(st):
        nxt = st[i + 1] if i + 1 < len(st) else (16 if last_long else s + 3); ln = min(nxt - s, 6)
        out.append((s, max(1, ln - 1 if ln > 2 and rng.random() < .7 else ln if ln <= 2 else int(rng.integers(1, 3)))))
    return out

def _pick(plan, st, ln, lo, hi, want, prev, ctx, rng, strong, exclude=(), colour=None):
    best, bm = -1e9, None
    for m in range(lo, hi + 1):
        w = weight(plan, st, m, strong or ln >= 2, colour)                                     # anything held is judged as a held note
        if w <= 0 or m in exclude or (ln >= 2 and not clean(m, st, ln, ctx)): continue
        leap = abs(m - prev) if prev is not None else 0
        sc = w * 1.3 - abs(m - want) * .55 - max(0, leap - 5) * 1.2 - (2.6 if prev is not None and leap == 0 else 0) - (.8 if leap == 6 else 0) + rng.random() * .6
        if sc > best: best, bm = sc, m
    return bm

def motif(plan, rng, lo, hi, bar, bars=2, onsets=(3, 5), ctx=None, busy_of_bar=None, shape=None, colour=None):
    """a `bars`-long idea starting at `bar`. shape: "arch" / "rise" / "fall" / "wave" (default: drawn)."""
    shape = shape or str(rng.choice(["arch", "rise", "fall", "wave"])); span = (hi - lo) * .7; mid = (lo + hi) / 2
    curve = {"arch": lambda u: mid - span * .2 + span * .55 * np.sin(np.pi * u), "rise": lambda u: mid - span * .35 + span * .7 * u,
             "fall": lambda u: mid + span * .35 - span * .7 * u, "wave": lambda u: mid + span * .35 * np.sin(2 * np.pi * u)}[shape]
    cells = [rhythm(rng, onsets, busy_of_bar(bar + b) if busy_of_bar else (), last_long=(b == bars - 1)) for b in range(bars)]
    ev = [(b * 16 + s, ln) for b, c in enumerate(cells) for s, ln in c]; out = []; prev = None
    for i, (s, ln) in enumerate(ev):
        strong = ln >= 3 or i == 0 or i == len(ev) - 1; st = bar * 16 + s
        m = _pick(plan, st, ln, lo, hi, curve(s / (bars * 16)), prev, ctx, rng, strong, colour=colour)
        if m is None: continue
        out.append((st, ln, m, 98 if strong else 80 if s % 2 == 0 else 72)); prev = m
    return out

def refit(notes, plan, lo, hi, ctx=None, shift=0):
    """the same line `shift` steps later, over other chords: a note that is still a chord tone or a colour there (and does not rub)
    stays; the others move to the nearest good pitch, keeping the direction of the line where they can"""
    out = []; prev_old = prev_new = None
    for s, ln, m, v in notes:
        st = s + shift; strong = ln >= 2
        ok = lambda x: lo <= x <= hi and weight(plan, st, x, strong) >= (2.0 if strong else .3) and (ln < 2 or clean(x, st, ln, ctx))
        if not ok(m):
            up = prev_old is None or m >= prev_old; cands = [m + d * k for k in range(1, 6) for d in ((1, -1) if up else (-1, 1))]
            m2 = next((x for x in cands if ok(x)), None)
            if m2 is None: ln = 1                                                     # nothing fits here: the note becomes a passing 16th
            else: m = m2
            if prev_new is not None and m == prev_new and ln < 2: m = next((x for x in cands if ok(x) and x != prev_new), m)
        out.append((st, ln, m, v)); prev_old, prev_new = notes[len(out) - 1][2], m
    return out

def hook(plan, rng, lo, hi, bar, ctx=None, busy_of_bar=None, onsets=(3, 5), colour=None):
    """8 bars from one 2-bar motif: A | A' (re-fitted, new tail) | A (re-fitted) | B (the motif's first bar, then one long note that
    comes to rest on a stable tone of the last chord)."""
    A = motif(plan, rng, lo, hi, bar, 2, onsets, ctx, busy_of_bar, colour=colour)
    A1 = refit(A, plan, lo, hi, ctx, 32)
    if len(A1) > 2:                                                                   # A': the tail answers differently
        s, ln, m, v = A1[-1]; alt = _pick(plan, s, ln, lo, hi, m + (3 if rng.random() < .5 else -3), A1[-2][2], ctx, rng, True, exclude=(m,), colour=colour)
        A1[-1] = (s, ln, alt if alt is not None else m, v)
    A2 = refit(A, plan, lo, hi, ctx, 64)
    B = refit([n for n in A if n[0] < bar * 16 + 16], plan, lo, hi, ctx, 96); st = (bar + 7) * 16 + int(rng.choice([0, 2])); c = plan.at(st)
    rest = [m for m in range(lo, hi + 1) if m % 12 in (c.pcs[0], c.pcs[2], c.pcs[1]) and clean(m, st, 10, ctx)]
    if rest: B.append((st, 10, min(rest, key=lambda m: abs(m - (B[-1][2] if B else (lo + hi) // 2)) + (0 if m % 12 != c.pcs[1] else .5)), 96))
    return A + A1 + A2 + B

def tile(line, plan, lo, hi, bars, ctx=None, period=8, origin=None):
    """repeat a `period`-bar line over the given bars (an iterable of bar numbers where a copy STARTS), re-fitted to the chords it
    meets there. origin: the bar the line was written at (default: its first note's bar, rounded down to the period)."""
    if not line: return []
    o = (line[0][0] // 16 // period * period) if origin is None else origin; out = []
    for b in bars: out += [n for n in refit(line, plan, lo, hi, ctx, (b - o) * 16) if n[0] < plan.bars * 16]
    return out

def ostinato(plan, rng, lo, hi, a_bar, b_bar, n=3, step=2, ctx=None, rest_every=0, vel=84):
    """n pitches, one every `step` sixteenths, round and round from bar a to bar b: n * step = 6, 10, 12 ... sixteenths does not divide
    the bar, so the figure drifts against it (polymeter). The pitches are the ones that are chord tones or colours for the largest
    part of the time; where one of them would be an avoid note or would rub, only that note bends to its neighbour."""
    score = {}
    for s0, ln, c, _ in plan.slots:
        if s0 >= b_bar * 16 or s0 + ln <= a_bar * 16: continue
        for pc, r in c.roles(plan.key).items():
            if r != "avoid": score[pc] = score.get(pc, 0) + ln * (1.0 if r == "chord" else .8)
    pcs = []
    for pc in sorted(score, key=lambda p: -score[p] - rng.random() * 8):
        if all(min((pc - q) % 12, (q - pc) % 12) >= 2 for q in pcs): pcs.append(pc)
        if len(pcs) == n: break
    base = sorted(lo + ((p - lo) % 12) for p in pcs); order = list(rng.permutation(len(base))); out = []; k = 0
    for st in range(a_bar * 16, b_bar * 16, step):
        k += 1
        if rest_every and k % rest_every == 0: continue
        m = base[order[(k - 1) % len(base)]]; ln = max(1, step - (1 if step > 1 else 0))
        if weight(plan, st, m, True) <= 0 or not clean(m, st, ln, ctx):
            m = next((x for d in (1, -1, 2, -2, 3, -3) for x in [m + d] if lo <= x <= hi + 2 and weight(plan, st, x, True) > 0 and clean(x, st, ln, ctx)), None)
            if m is None: continue
        out.append((st, ln, m, vel + (10 if (k - 1) % len(base) == 0 else 0)))
    return out

def arp(plan, voicings, rng, a_bar, b_bar, step=2, shape="updown", octave=True, colour=True, lo=None, hi=None, vel=80):
    """the notes of the current voicing (plus its top an octave up and one colour tone) as a running pattern. The position in the
    pattern carries on through chord changes (it does not restart), so the accents drift."""
    out = []; k = 0; vi = 0; starts = [v[0] for v in voicings]
    for st in range(a_bar * 16, b_bar * 16, step):
        while vi + 1 < len(starts) and starts[vi + 1] <= st: vi += 1
        v = list(voicings[vi][2]); c = plan.at(st)
        if colour:
            col = next((p for p in c.colours(plan.key) if p not in [x % 12 for x in v]), None)
            if col is not None: v.append(v[-1] + ((col - v[-1]) % 12 or 12))
        if octave: v.append(v[0] + 12 if v[0] + 12 not in v else v[-1] + 12)
        v = sorted(set(x for x in v if (lo is None or x >= lo) and (hi is None or x <= hi))) or list(voicings[vi][2])
        seq = v + v[-2:0:-1] if shape == "updown" else v[::-1] if shape == "down" else v if shape == "up" else [v[i] for i in rng.permutation(len(v))]
        out.append((st, max(1, step - 1) if step > 1 else 1, seq[k % len(seq)], vel + (12 if k % len(seq) == 0 else 0))); k += 1
    return out

def topline(plan, rng, lo, hi, rank_cost=.6):
    """one slow note per chord from its colours (9, 11, 13, then 7 / 5 / 3), moving as little as possible: [midi per slot] for
    Plan.voicings(top=...) and [(step, len, midi, vel)] as a line of its own"""
    top = []; prev = (lo + hi) // 2
    for s0, ln, c, _ in plan.slots:
        col = c.colours(plan.key)[:5]; stuck = len(top) >= 2 and top[-1] == top[-2]                       # a common tone may stay, but not for ever
        cands = [(abs(m - prev) + rank_cost * col.index(m % 12) + (2.5 if abs(m - prev) == 6 else 0) + (2.0 if stuck and m == prev else 0) + rng.random() * .3, m)
                 for m in range(lo, hi + 1) if m % 12 in col]
        prev = min(cands)[1] if cands else prev; top.append(prev)
    return top, [(s[0], s[1], m, 84) for s, m in zip(plan.slots, top)]

def counter(plan, melody, rng, lo, hi, ctx=None, min_gap=4):
    """answers in the melody's rests (>= min_gap sixteenths): one or two notes on the chord's guide tones (3rd / 7th) or its 5th,
    moving against the direction the melody just took"""
    busy = np.zeros(plan.bars * 16 + 16, bool)
    for s, ln, *_ in melody: busy[max(0, s):s + ln] = True
    mel = sorted(melody); out = []; prev = (lo + hi) // 2; i = 0; N = plan.bars * 16
    while i < N:
        if busy[i]: i += 1; continue
        j = i
        while j < N and not busy[j]: j += 1
        before = [n for n in mel if n[0] < i][-2:]
        if j - i >= min_gap and before:
            direction = -1 if len(before) == 2 and before[1][2] >= before[0][2] else 1; st = i + 1; k = 0
            while st + 2 <= j - 1 and k < 2:
                c = plan.at(st); ln = min(3, j - 1 - st); goal = prev + direction * 3
                cands = [m for m in range(lo, hi + 1) if m % 12 in (c.pcs[1:2] + c.pcs[3:4] + c.pcs[2:3]) and clean(m, st, ln, ctx)]
                if not cands: break
                m = min(cands, key=lambda x: abs(x - goal) + (1.5 if x == prev else 0)); out.append((st, ln, m, 70)); prev = m; st += ln + 1; k += 1
        i = j
    return out

def fit(notes, plan, ctx=None, min_len=2):
    """how a line sits on the harmony. Over the HELD notes (>= min_len sixteenths), by duration: avoid = share on avoid notes or
    outside the chord scale (should be 0), rub = share a semitone / minor ninth from what sounds (should be 0), colour = share on
    9 / 11 / 13 (0 = only chord tones: plain; .2-.5 = modern), plus the pitch range and the number of different pitch classes."""
    held = [(s, ln, m) for s, ln, m, *_ in notes if ln >= min_len]; tot = sum(n[1] for n in held) or 1
    role = lambda s, m: plan.at(s).role(m % 12, plan.key)
    return {"notes": len(notes), "held": len(held), "avoid": round(sum(ln for s, ln, m in held if role(s, m) in ("avoid", "out")) / tot, 3),
            "rub": round(sum(ln for s, ln, m in held if not clean(m, s, ln, ctx)) / tot, 3) if ctx is not None else None,
            "colour": round(sum(ln for s, ln, m in held if role(s, m) == "tension") / tot, 3),
            "range": (max(n[2] for n in notes) - min(n[2] for n in notes)) if notes else 0, "pitch_classes": len({n[2] % 12 for n in notes})}

def fix(notes, plan, lo, hi, ctx=None):
    """repair a hand-written or imported line: held avoid notes and rubs move to the nearest good pitch (refit in place)"""
    return refit(notes, plan, lo, hi, ctx, 0)
