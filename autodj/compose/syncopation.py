"""P124 (2026-11-01): syncopation as a number. Исследования (Duncan & Orgs 2024; Witek/Sioros): groove vs syncopation is an inverted U - a medium amount
is best, a straight pattern is flat and a very broken one loses the pulse; for house the BASS syncopation matters most. LHL index (Longuet-Higgins & Lee):
on a 16-step bar every position has a metric weight; an onset followed by a silent position of HIGHER weight is a syncopation worth the weight difference.
    lhl([0, 3, 6, 10, 12]) -> bar score;  lhl_events(events) -> mean per bar over (bar, step) hits;  in_range(style, v) -> (ok, lo, hi)"""
import numpy as np
W16 = [0, -4, -3, -4, -2, -4, -3, -4, -1, -4, -3, -4, -2, -4, -3, -4]       # 4/4 on 16ths (Longuet-Higgins & Lee, Witek et al.)
# Measured on the 14 learned references (2026-11-01): the KICK is straight in almost all of them (LHL 0), the BASS line carries the syncopation:
# bass LHL 0, 0, 0, 3, 7, 7, 8, 8, 8, 8, 8, 11, 11, 15 (median 8). So the gate looks at the bass line; windows are the reference spread, a little widened.
RANGES = {"house": (3.0, 14.0), "techno": (2.0, 12.0), "downtempo": (4.0, 16.0), "breaks": (6.0, 22.0), "*": (3.0, 16.0)}

def lhl(steps):
    on = sorted({int(s) % 16 for s in steps})
    if len(on) < 2: return 0.0
    tot = 0.0
    for k, i in enumerate(on):
        j = on[(k + 1) % len(on)] if k + 1 < len(on) else on[0] + 16
        sil = [p % 16 for p in range(i + 1, j)]
        if not sil: continue
        wr = max(W16[p] for p in sil)
        if wr > W16[i]: tot += wr - W16[i]
    return float(tot)

def lhl_events(events):
    """events (bar, step, ...) -> mean LHL per bar that has at least 2 hits"""
    by = {}
    for e in events: by.setdefault(int(e[0]), set()).add(int(e[1]) % 16)
    v = [lhl(s) for s in by.values() if len(s) >= 2]
    return float(np.mean(v)) if v else 0.0

def in_range(style, value):
    lo, hi = RANGES.get(style, RANGES["*"]); return (lo <= value <= hi), lo, hi
