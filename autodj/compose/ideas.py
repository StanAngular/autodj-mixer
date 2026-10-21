"""Competing hook IDEAS (P109, ТЗ ChatGPT+Gemini 2026-10-21: «не один вариант, а несколько музыкальных гипотез»).
Each family is a different musical identity, not a different timbre. All take the same key / per-bar chord /
bass rhythm, so a comparison changes ONE thing: the idea. Every family returns
    {"family", "desc", "hook": [(step_abs, len16, midi, vel)], "hook_inst", "bass": [...] or None, "chords": "comp"|"pad"}
with notes only from the key or the bar's chord (check_notes-safe).
- anchor_dialog: 2-3 anchor notes in dialog with the bass (hook.anchor_hook)
- riff:        one-bar rhythmic riff on root/octave/5th grouped 3+3+2 style (percussive identity), Rhodes
- arp_cycle:   chord tones cycled in groups of 3 sixteenths over 4/4 (a polymetric shimmer), piano
- long_line:   slow guide-tone melody (3rds/7ths moving by step), long held notes over a busier bass, piano
- bass_hook:   the BASS carries the hook: a melodic syncopated riff over an octave; no top hook"""
import numpy as np
from .hook import anchor_hook, _nearest
from .harmony import stable_tone
from .bass import house_bass

FAMILIES = ("anchor_dialog", "riff", "arp_cycle", "long_line", "bass_hook")

def _ok(key, pcs):
    return lambda m: m % 12 in key.pcs or m % 12 in pcs

def groupings(rng):
    """16 sixteenths split into groups of 3/4/2 with at least two 3s (tresillo-like, not four-on-the-floor)"""
    while True:
        g, s = [], 0
        while s < 16:
            x = int(rng.choice([3, 3, 3, 2, 4])); x = min(x, 16 - s); g.append(x); s += x
        if g.count(3) >= 2 and g[-1] >= 2: return g

def riff(rng, key, chord_of_bar, bars=8, lo=60, hi=76):
    g = groupings(rng); on = list(np.cumsum([0] + g[:-1])); out = []
    jump_at = int(rng.integers(1, len(on)))                                   # one accent jumps an octave
    for b in range(bars):
        pcs = chord_of_bar(b); r = _nearest([m for m in range(lo, hi - 11) if m % 12 == pcs[0]], (lo + hi) // 2 - 6)
        for j, s in enumerate(on):
            m = r + 12 if j == jump_at else r
            if j == len(on) - 1 and b % 2: m = _nearest([x for x in range(lo, hi + 1) if x % 12 in pcs[1:3]], r + 7)   # tail answers
            out.append((16 * b + s, min(2, g[j]), int(m), 104 if j == 0 or j == jump_at else 78))
    return {"family": "riff", "desc": f"ритмический рифф {'+'.join(map(str, g))} на тонике аккорда, скачок на октаву, хвост через такт", "hook": out,
            "hook_inst": "rhodes", "bass": None, "chords": "pad"}

def arp_cycle(rng, key, chord_of_bar, voices_of_bar, bars=8):
    order = [[0, 1, 2], [0, 2, 1], [2, 1, 0], [1, 0, 2]][int(rng.integers(4))]; out = []; k = 0
    for b in range(bars):
        v = sorted(voices_of_bar(b))[-3:]
        for s in range(16):
            if s in (14, 15) and b % 2: continue                              # breathe every second bar
            m = v[order[k % 3]]; out.append((16 * b + s, 1, int(m + 12), 100 if k % 3 == 0 else 58)); k += 1
    return {"family": "arp_cycle", "desc": f"арпеджио по тонам аккорда группами по 3 шестнадцатых поверх 4/4, порядок {order}", "hook": out,
            "hook_inst": "piano", "bass": None, "chords": "pad"}

def long_line(rng, key, chord_of_bar, bars=8, lo=64, hi=79):
    out, prev = [], None
    for b in range(0, bars, 2):
        pcs = chord_of_bar(b)
        guide = [q for q in (pcs[1], pcs[2]) + tuple(x for x in pcs[3:4] if (x - pcs[0]) % 12 == 10) if stable_tone(q, pcs)] or [pcs[0]]
        cands = [m for m in range(lo, hi + 1) if m % 12 in guide]                # held = 3rd/5th/b7 that do not rub (p109)
        m = _nearest(cands, prev if prev is not None else (lo + hi) // 2); prev = m
        st = int(rng.choice([0, 2, 3]))                                       # often anticipated, off the downbeat
        nxt = chord_of_bar(b + 1); keep = stable_tone(m % 12, nxt)
        out.append((16 * b + st, 16 - st + (6 if keep else 0), m, 92))       # do not hold it into a chord it rubs against
        back = m if keep else _nearest([x for x in range(lo, hi + 1) if stable_tone(x % 12, nxt)] or [m], m)   # sus4 -> 3rd
        if not keep: out.append((16 * (b + 1), 6, back, 84))                  # the suspension resolves with the chord
        nb = [x for x in key.scale_notes(back - 2, back + 2) if x != back and not any((x - q) % 12 in (1, 11) for q in nxt)]
        if nb:                                                                # passing note: never a semitone off the chord
            n = nb[int(rng.integers(len(nb)))]; out.append((16 * (b + 1) + 8, 3, n, 70)); out.append((16 * (b + 1) + 12, 4, back, 82))
        prev = back
    bass = house_bass(rng, key, lambda b: chord_of_bar(b)[0], bars, onsets=(5, 6))            # busy bass under long notes
    return {"family": "long_line", "desc": "медленная линия по устойчивым тонам (3-я/5-я/малая 7-я без полутона к аккорду), длинные ноты, предъём, бас плотнее", "hook": out,
            "hook_inst": "piano", "bass": bass, "chords": "comp"}

def bass_hook(rng, key, chord_of_bar, bars=8, lo=33, hi=52):
    on = sorted(set([0] + rng.choice([3, 6, 7, 10, 11, 14], int(rng.integers(3, 5)), replace=False).tolist()))
    on = [s for i, s in enumerate(on) if i == 0 or s - on[i - 1] >= 2]
    shape = [0] + [int(rng.choice([12, 7, 10, 3, 5])) for _ in on[1:]]       # intervals above the root
    out = []
    for b in range(bars):
        pcs = chord_of_bar(b); r = next(m for m in range(lo, hi + 1) if m % 12 == pcs[0]); ok = _ok(key, pcs)
        for j, s in enumerate(on):
            m = r + shape[j]
            if not ok(m): m = key.snap(m)
            if m > hi: m -= 12
            ln = min(2, (on[j + 1] if j + 1 < len(on) else 16) - s - 1) or 1
            out.append((16 * b + s, ln, int(m), 108 if s % 4 else 92))
    return {"family": "bass_hook", "desc": f"хук в басу: синкопы на шагах {on}, интервалы от корня {shape}; сверху только аккорды", "hook": [],
            "hook_inst": None, "bass": out, "chords": "comp"}

def anchor_dialog(rng, key, chord_of_bar, bass_steps_of_bar, bars=8):
    h, an = anchor_hook(rng, key, chord_of_bar, bass_steps_of_bar, 62, 81, bars=bars)
    return {"family": "anchor_dialog", "desc": f"2-3 опорные ноты {an} в диалоге с басом, акценты на слабых долях", "hook": h,
            "hook_inst": "piano", "bass": None, "chords": "comp"}

def make(family, rng, key, chord_of_bar, voices_of_bar=None, bass_steps_of_bar=None, bars=8):
    if family == "riff": return riff(rng, key, chord_of_bar, bars)
    if family == "arp_cycle": return arp_cycle(rng, key, chord_of_bar, voices_of_bar, bars)
    if family == "long_line": return long_line(rng, key, chord_of_bar, bars)
    if family == "bass_hook": return bass_hook(rng, key, chord_of_bar, bars)
    return anchor_dialog(rng, key, chord_of_bar, bass_steps_of_bar, bars)
