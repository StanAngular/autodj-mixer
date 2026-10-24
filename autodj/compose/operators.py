"""P115 (2026-10-24; ChatGPT research «Nonstandard composition v1.2» + Стас liked «Low Pulse X»): named experimental operators and a
technique registry. Pattern operators work on event lists (no audio): drums [(bar, step, vel)], notes [(step_abs, len, midi, vel)].
Rules built in: one ANCHOR role (default "kick") is never touched by ANT/DLY/ROT/OFF+/GHOST; deviations are SHORT (callers pass
bars); a DROP of the anchor keeps at least 2 full bars on each side. Bus operators (freeze, crush, pingpong, telephone, gate,
tail_only) work on trk.mix in a bar range, all on the grid. Every call is journaled in trk.ops (if a track is given).
The registry (shared/technique_registry.json) remembers which technique sounded in which track and Стас's verdicts, so a new
track picks techniques that were not used recently and never repeats the previous track's signature move."""
import json, os, math, datetime, numpy as np
REGISTRY = os.environ.get("AUTODJ_TECHNIQUES", "/opt/autodj-mixer/shared/technique_registry.json")
ANCHOR = "kick"

def _log(trk, op, **kw):
    if trk is not None:
        if not hasattr(trk, "ops"): trk.ops = []
        trk.ops.append({"op": op, **{k: (list(v) if isinstance(v, (range, tuple, set)) else v) for k, v in kw.items()}})
def _guard(role, op):
    if role == ANCHOR: raise ValueError(f"{op}: the anchor role «{ANCHOR}» is not moved (it holds the pulse)")
def _in(bars): return set(bars)

# ---- pattern operators (drums: (bar, step, vel)) --------------------------------------------------------------------
def ant(ev, role, bars, step=1, fraction=1.0, rng=None, trk=None):
    """anticipate: move strong-position onsets 1-2 sixteenths earlier"""
    _guard(role, "ANT"); B = _in(bars); rng = rng or np.random.default_rng(0); out = []
    for br, st, v in ev:
        if br in B and st % 4 == 0 and rng.random() < fraction:
            st2 = st - step; br2 = br if st2 >= 0 else br - 1; out.append((br2, st2 % 16, v))
        else: out.append((br, st, v))
    _log(trk, "ANT", role=role, bars=sorted(B), step=step); return sorted(out)
def dly(ev, role, bars, step=1, fraction=.25, rng=None, trk=None):
    """delay at most 25 % of a layer's onsets by 1-2 sixteenths"""
    _guard(role, "DLY"); B = _in(bars); rng = rng or np.random.default_rng(0); out = []; fr = min(fraction, .25)
    for br, st, v in ev:
        if br in B and rng.random() < fr: st2 = st + step; out.append((br + st2 // 16, st2 % 16, v))
        else: out.append((br, st, v))
    _log(trk, "DLY", role=role, bars=sorted(B), step=step); return sorted(out)
def drop(ev, role, bar, positions=(0,), all_bars=None, trk=None):
    """remove expected strong onsets in ONE bar; for the anchor, the 2 bars around must stay full"""
    if role == ANCHOR:
        have = {(br, st) for br, st, _ in ev}
        for b in (bar - 2, bar - 1, bar + 1, bar + 2):
            if not all((b, st) in have for st in (0, 4, 8, 12)): raise ValueError("DROP: the anchor needs 2 full bars before and after")
    out = [e for e in ev if not (e[0] == bar and e[1] in positions)]; _log(trk, "DROP", role=role, bar=bar, positions=list(positions)); return out
def rot(ev, role, bars, k, trk=None):
    """rotate a pattern by k sixteenths inside the bar, density unchanged (the riff «slides» against the beat)"""
    _guard(role, "ROT")
    if not 1 <= k <= 7: raise ValueError("ROT: k in 1..7")
    B = _in(bars); out = [((br, (st + k) % 16, v) if br in B else (br, st, v)) for br, st, v in ev]; _log(trk, "ROT", role=role, bars=sorted(B), k=k); return sorted(out)
def off_plus(ev, role, bars, positions, vel_ratio=.6, trk=None):
    """add onsets on weak positions, quieter (<= 60 % of the layer's accents)"""
    _guard(role, "OFF+"); B = _in(bars); top = max([v for *_, v in ev] or [100]); add = [(br, p, top * min(vel_ratio, .6)) for br in B for p in positions if p % 2]
    _log(trk, "OFF+", role=role, bars=sorted(B), positions=list(positions)); return sorted(ev + add)
def ghost(ev, role, bars, steps, vel=25, trk=None):
    """ghost notes (MIDI-like velocity 15-35); leaves at least one bar in four clean"""
    _guard(role, "GHOST"); vel = int(np.clip(vel, 15, 35)); B = [b for b in bars if b % 4 != 3]
    add = [(br, s, vel) for br in B for s in steps]; _log(trk, "GHOST", role=role, bars=B, steps=list(steps)); return sorted(ev + add)
def poly(r, cycle, bars, phase=0, vel=80, trk=None):
    """r events evenly over a cycle of `cycle` sixteenths, as a new layer; the ratio is reduced by gcd and must stay simple"""
    if not (isinstance(r, int) and isinstance(cycle, int)) or r <= 0 or cycle <= 0: raise ValueError("POLY: positive integers")
    g = math.gcd(r, cycle)
    if (r // g) + (cycle // g) > 21: raise ValueError("POLY: ratio too complex")
    bars = list(bars); out = []
    for i in range(bars[0] * 16, (bars[-1] + 1) * 16):
        if ((i - bars[0] * 16 + phase) * r) % cycle < r: out.append((i // 16, i % 16, vel if ((i - bars[0] * 16) // cycle) % 2 == 0 else vel * .8))
    _log(trk, "POLY", r=r, cycle=cycle, bars=bars); return out
def pmeter(cycle_steps, bars, accent=96, rest=60, trk=None):
    """a cycle that is not a bar (5/7/12 sixteenths) re-synchronised at the first bar line of every 4 bars"""
    bars = list(bars); out = []
    for blk in range(bars[0], bars[-1] + 1, 4):
        for i in range(blk * 16, min(blk + 4, bars[-1] + 1) * 16):
            k = (i - blk * 16) % cycle_steps; out.append((i // 16, i % 16, accent if k == 0 else rest)) if k in (0, cycle_steps // 2) else None
    _log(trk, "PMETER", cycle=cycle_steps, bars=bars); return out
def half(pattern):
    """half-time feel of a 1-bar drum pattern {role: steps}: kick 0+10, snare on 8"""
    return {**pattern, "kick": (0, 10), "snare": (8,)}

# ---- bus operators (trk.mix, bar ranges) ----------------------------------------------------------------------------
def freeze(trk, bar, beats=1):
    i1 = trk.i(bar + 1); i0 = i1 - beats * trk.BEAT; g = trk.mix[i0 - int(.06 * trk.sr):i0].copy() * np.hanning(int(.06 * trk.sr))[:, None]
    o = np.zeros((i1 - i0, 2), np.float32)
    for t in range(0, i1 - i0 - len(g), max(1, len(g) // 3)): o[t:t + len(g)] += g * .55
    trk.mix[i0:i1] = o * np.linspace(1, .6, i1 - i0)[:, None]; _log(trk, "FREEZE", bar=bar, beats=beats)
def crush(trk, a, b, factor=6, levels=64):
    from pedalboard import Pedalboard, LowpassFilter
    from .core import pb
    i0, i1 = trk.i(a), trk.i(b); seg = trk.mix[i0:i1]; held = np.repeat(seg[::factor], factor, axis=0)[:i1 - i0]
    trk.mix[i0:i1] = pb(Pedalboard([LowpassFilter(9000)]), (np.round(held * levels) / levels).astype(np.float32)); _log(trk, "CRUSH", bars=[a, b])
def pingpong(trk, bar):
    i0, i1 = trk.i(bar), trk.i(bar + 1); L = int(trk.S16 * trk.sr); seg = trk.mix[i0:i1].copy(); m = seg.mean(1)
    for k in range(0, i1 - i0, L):
        sd = (k // L) % 2; e = min(k + L, i1 - i0); seg[k:e, sd] = m[k:e] * 1.3; seg[k:e, 1 - sd] = m[k:e] * .3
    trk.mix[i0:i1] = seg; _log(trk, "PINGPONG", bar=bar)
def telephone(trk, a, b):
    """mono narrow band for a few bars — best right before the drums land (Стас)"""
    from pedalboard import Pedalboard, HighpassFilter, LowpassFilter
    from .core import pb
    i0, i1 = trk.i(a), trk.i(b); seg = trk.mix[i0:i1].copy(); m = seg.mean(1, keepdims=True).repeat(2, 1)
    tel = pb(Pedalboard([HighpassFilter(450), LowpassFilter(2600)]), m) * 1.8; r = int(.01 * trk.sr); w = np.ones(i1 - i0, np.float32); w[:r] = np.linspace(0, 1, r)
    trk.mix[i0:i1] = seg * (1 - w[:, None]) + tel * w[:, None]; _log(trk, "TELEPHONE", bars=[a, b])
def gate(trk, a, b, div=8, duty=.5):
    i0, i1 = trk.i(a), trk.i(b); n = i1 - i0; ph = (np.arange(n) / (trk.BEAT / (div / 4))) % 1; g = np.convolve((ph < duty).astype(np.float32), np.ones(64) / 64, "same")
    trk.mix[i0:i1] *= (.1 + .9 * g)[:, None]; _log(trk, "GATE", bars=[a, b], div=div)

# ---- technique registry -----------------------------------------------------------------------------------------------
TECHNIQUES = ["ANT", "DLY", "DROP", "ROT", "OFF+", "GHOST", "POLY", "PMETER", "HALF", "FREEZE", "CRUSH", "PINGPONG", "TELEPHONE", "GATE", "TAIL-ONLY"]
def load(path=None):
    p = path or REGISTRY; return json.load(open(p)) if os.path.exists(p) else {"uses": [], "votes": {}}
def save(db, path=None): json.dump(db, open(path or REGISTRY, "w"), ensure_ascii=False, indent=0)
def register(track, techniques, path=None, signature=None):
    db = load(path); d = datetime.date.today().isoformat()
    for t in techniques: db["uses"].append({"track": track, "technique": t, "date": d, "signature": t == signature})
    save(db, path)
def vote(technique, verdict, path=None):
    """+1 like, -1 dislike, 0 neutral (counted as a use, not as preference)"""
    if verdict not in (-1, 0, 1): raise ValueError("verdict -1/0/1")
    db = load(path); v = db["votes"].setdefault(technique, {"like": 0, "dislike": 0, "neutral": 0})
    v[{1: "like", -1: "dislike", 0: "neutral"}[verdict]] += 1; save(db, path)
def pick(n, rng=None, path=None, recent_tracks=3, pool=None):
    """n techniques: never the last track's signature, avoid those used in the last `recent_tracks` tracks, liked ones weighted up"""
    db = load(path); rng = rng or np.random.default_rng(0); pool = list(pool or TECHNIQUES)
    tracks = []
    for u in reversed(db["uses"]):
        if u["track"] not in tracks: tracks.append(u["track"])
    recent = {u["technique"] for u in db["uses"] if u["track"] in tracks[:recent_tracks]}
    sig = {u["technique"] for u in db["uses"] if tracks and u["track"] == tracks[0] and u.get("signature")}
    fresh = [t for t in pool if t not in recent and t not in sig] or [t for t in pool if t not in sig]
    w = np.array([1.0 + db["votes"].get(t, {}).get("like", 0) - .7 * db["votes"].get(t, {}).get("dislike", 0) for t in fresh]); w = np.clip(w, .1, None)
    return [fresh[i] for i in rng.choice(len(fresh), min(n, len(fresh)), replace=False, p=w / w.sum())]
