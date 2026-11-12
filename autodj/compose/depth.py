"""P133 (2026-11-12, audit): ears for DEPTH. All existing gates look for defects (clash, harsh top, sub, clicks, silent layers).
A track can pass every one of them and still be flat: each layer a loop that never changes, nothing reacting to anything, everything
at the same distance. This module measures exactly that, per layer and between layers, from what every layer really played
(Track.add stores a small step x band energy map of each layer), and says in plain words where the track is flat:

  motion       is a layer a frozen loop? For each layer the bar is compared with the bar P bars earlier (P = its own loop length);
               `frozen_bars` = longest run in which nothing changed (rhythm AND tone, < 0.5 dB per cell). Static = the same loop
               at least 4 times in a row and at least 16 bars (the kick, the anchor of the pulse, is not judged).
  interaction  who reacts to whom: keyed ducks and follows (from the routing), measured pump of sustained layers against the kick,
               pairs that answer each other (complementary rhythms) and pairs that merely double each other;
  masking      how much of a layer's energy sits in step x band cells where the rest of the mix is >= 6 dB louder (it is in the
               file but nobody hears it: «каша»);
  space        distance planes of the tonal layers (front / middle / back from depth= and sends), shared spaces in use;
  texture      how many different layer combinations the track has and how long the longest unchanged stretch is.

report(trk) -> dict with the numbers, three scores 0..1 (motion / interaction / space) and `notes`: concrete hints in Russian.
Always on (it costs ~0.1 s per layer), never blocks by itself; gates are opt-in through META["gates"]:
  depth_static_max, depth_links_min, depth_planes_min, depth_masked_max."""
import numpy as np

NB = 16; EDGES = np.geomspace(30.0, 16000.0, NB + 1); FLOOR = 50.0
DRUMS = ("kick", "hat", "hats", "shk", "shaker", "clap", "snare", "rim", "ride", "perc", "conga", "tom", "open", "rumble", "drum", "cymbal")

def is_drum(name):
    n = name.lower(); return any(n == d or n.startswith(d) or n.endswith(d) for d in DRUMS)

def activity(x, sr, s16, n_steps):
    """(n_steps, NB) energy of a layer per 16th step and band: one windowed spectrum at the start of every step"""
    m = x.mean(1) if x.ndim == 2 else x; step = s16 * sr; W = int(min(4096, 2 ** np.floor(np.log2(max(256, step)))))
    idx = (np.arange(n_steps) * step).astype(np.int64); m = np.pad(m, (0, max(0, int(idx[-1]) + W - len(m))))
    F = m[idx[:, None] + np.arange(W)[None, :]] * np.hanning(W)[None, :]; P = np.abs(np.fft.rfft(F, axis=1)) ** 2; f = np.fft.rfftfreq(W, 1 / sr)
    return np.stack([P[:, (f >= EDGES[i]) & (f < EDGES[i + 1])].sum(1) for i in range(NB)], 1).astype(np.float32)

def _bar_maps(E, bars):
    """(bars, 16, NB) dB map of each bar relative to the layer's own loudest cell, floored at -FLOOR"""
    M = 10 * np.log10(E[:bars * 16].reshape(bars, 16, NB) + 1e-20); return np.maximum(M - M.max(), -FLOOR)

def _cells(a, b):
    """mean change (dB) over the step x band cells that sound in at least one of two bars"""
    on = (a > -FLOOR + 1) | (b > -FLOOR + 1); return float(np.abs(a - b)[on].mean()) if on.any() else 0.0

def layer_motion(E, bars):
    """is this layer a loop? -> dict(active_bars, loop_bars, repeat_db, frozen_bars, level_range_db)"""
    M = _bar_maps(E, bars); lev = M.max((1, 2)); act = lev > -40; nact = int(act.sum())
    out = {"active_bars": nact, "loop_bars": None, "repeat_db": None, "frozen_bars": 0, "level_range_db": 0.0}
    if nact < 2: return out
    out["level_range_db"] = round(float(np.percentile(lev[act], 90) - np.percentile(lev[act], 10)), 1); best = None
    for P in (1, 2, 4, 8, 16):
        pairs = [b for b in range(P, bars) if act[b] and act[b - P]]
        if len(pairs) < 2: continue
        d = np.array([_cells(M[b], M[b - P]) for b in pairs]); md = float(d.mean())
        if best is None or md < best[1] - .05: best = (P, md, pairs, d)                      # the shortest period that explains the layer
    if best is None: return out
    P, md, pairs, d = best; run = cur = 0; prev = None
    for b, same in zip(pairs, d < .5):
        cur = (cur + 1 if prev == b - 1 else 1) if same else 0; prev = b; run = max(run, cur)
    out.update(loop_bars=P, repeat_db=round(md, 2), frozen_bars=int(run + P if run else 0)); return out

def onsets(E, bars):
    """per bar, the set of 16th steps on which the layer starts a sound (a rise of >= 6 dB to within 20 dB of its loudest step)"""
    e = 10 * np.log10(E[:bars * 16].sum(1) + 1e-20); e = e - e.max(); prev = np.concatenate([[-99.0], e[:-1]])
    on = (e > -20) & (e - prev > 6); return [set(np.where(on[b * 16:(b + 1) * 16])[0].tolist()) for b in range(bars)]

def masking(act, bars, margin_db=6.0):
    """{layer: (share of its energy in cells where the others together are >= margin louder, the strongest masker)}"""
    names = list(act); tot = sum(act[n][:bars * 16] for n in names); out = {}; k = 10 ** (margin_db / 10)
    for n in names:
        E = act[n][:bars * 16]; s = float(E.sum())
        if s <= 0: continue
        hid = (tot - E) > k * E; share = float(E[hid].sum() / s); top = None
        if share > 0 and len(names) > 1: top = max((o for o in names if o != n), key=lambda o: float(act[o][:bars * 16][hid].sum()))
        out[n] = (round(share, 2), top)
    return out

def pump(act, bars, kick):
    """{sustained layer: dB on the kick's steps minus dB on the other steps} (negative = it breathes with the kick)"""
    if kick not in act: return {}
    ko = onsets(act[kick], bars); out = {}
    for n, E in act.items():
        if n == kick or is_drum(n): continue
        e = E[:bars * 16].sum(1).reshape(bars, 16); on, off = [], []
        for b in range(bars):
            row = e[b]
            if not ko[b] or row.max() <= 0 or (row > row.max() * .1).mean() < .75: continue           # bars with a kick where the layer really sustains (tails do not count)
            on += [row[s] for s in ko[b]]; off += [row[s] for s in range(16) if s not in ko[b]]
        if len(on) >= 8 and len(off) >= 8: out[n] = round(float(10 * np.log10(np.mean(on) / (np.mean(off) + 1e-20) + 1e-20)), 1)
    return out

def rhythm_pairs(act, bars):
    """(doubles, dialogs): pairs whose onsets coincide (Jaccard >= .85) and pairs that fill each other's gaps (Jaccard <= .1)"""
    on = {n: onsets(E, bars) for n, E in act.items()}; names = list(on); dbl, dia = [], []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = on[names[i]], on[names[j]]; js = [len(x & y) / len(x | y) for x, y in zip(a, b) if len(x) >= 2 and len(y) >= 2]
            if len(js) < 4: continue
            m = float(np.mean(js))
            if m >= .85: dbl.append([names[i], names[j], round(m, 2)])
            elif m <= .1 and not is_drum(names[i]) and not is_drum(names[j]): dia.append([names[i], names[j], round(m, 2)])   # two PARTS that answer each other
    return dbl, dia

def texture(act, bars):
    """how the set of sounding layers changes: number of different combinations, longest run of bars with the same one"""
    sets = []
    for b in range(bars):
        s = frozenset(n for n, E in act.items() if E[b * 16:(b + 1) * 16].sum() > E.sum() / max(1, bars) * 1e-3); sets.append(s)
    run = best = 1
    for a, b in zip(sets, sets[1:]):
        run = run + 1 if a == b else 1; best = max(best, run)
    return {"states": len(set(sets)), "longest_same_bars": int(best if sets else 0), "changes": int(sum(a != b for a, b in zip(sets, sets[1:])))}

def planes(routing, spaces=None):
    """distance planes of the non-drum layers from what was declared: depth + reverb sends (an echo is not a distance)"""
    out = {"front": [], "middle": [], "back": []}; echo = {k for k, v in (spaces or {}).items() if getattr(v, "kind", "") == "echo"}
    for n, r in (routing or {}).items():
        if is_drum(n): continue
        w = float(r.get("depth") or 0) + sum(a for k, a in (r.get("send") or {}).items() if k not in echo)
        out["front" if w < .2 else "middle" if w < .7 else "back"].append(n)
    return out

def report(trk):
    """everything above for a built Track -> dict (JSON-ready)"""
    act = {n: E for n, E in getattr(trk, "act", {}).items() if E is not None and float(E.sum()) > 0}; bars = trk.bars; routing = getattr(trk, "routing", {})
    if not act: return {"layers": {}, "notes": [], "score": {}}
    L = {n: layer_motion(E, bars) for n, E in act.items()}; mk = masking(act, bars); kick = next((n for n in act if n.lower().startswith("kick")), None)
    pm = pump(act, bars, kick) if kick else {}
    for n in L:
        L[n]["masked"], L[n]["masker"] = mk.get(n, (0.0, None)); L[n]["pump_db"] = pm.get(n)
    static = sorted(n for n, d in L.items() if n != kick and d["loop_bars"] and d["frozen_bars"] >= max(16, 4 * d["loop_bars"], .5 * d["active_bars"]))   # the kick is the anchor
    dbl, dia = rhythm_pairs(act, bars); tx = texture(act, bars); pl = planes(routing, getattr(trk, "spaces", {}))
    links = [[n, r["key"], r.get("duck_db"), r.get("band")] for n, r in routing.items() if r.get("key") not in (None, "clock")]
    clock = sorted(n for n, r in routing.items() if r.get("key") == "clock"); followed = sorted(getattr(trk, "followed", ()))
    hidden = sorted(n for n, d in L.items() if d["masked"] >= .6 and not n.lower().startswith(("sub", "rumble", "room", "texture", "fx")))
    long_layers = [n for n, d in L.items() if d["active_bars"] >= 16 and n != kick]; tonal = [n for n in act if not is_drum(n)]
    used_planes = sum(1 for v in pl.values() if v); spaces = {k: v.sent for k, v in getattr(trk, "spaces", {}).items()}
    score = {"motion": round(1 - len(static) / len(long_layers), 2) if long_layers else None,
             "interaction": round(min(1.0, (len(links) + len(followed) + min(1, len(dia))) / 4), 2),
             "space": round(min(1.0, (used_planes - 1) / 2 + (.34 if spaces else 0)), 2) if tonal else None}
    notes = []
    for n in static:
        d = L[n]; notes.append(f"слой «{n}» — петля: {d['frozen_bars']} тактов подряд без единого изменения (повтор каждые {d['loop_bars']} т.). Дай ему движение: "
                               f"synth-модуляции (lfo / time / rand), follow другого слоя, смена рисунка или фильтра по ходу трека")
    for n in hidden: notes.append(f"слой «{n}» почти не слышен: {L[n]['masked']:.0%} его энергии закрыто (сильнее всех «{L[n]['masker']}»). Разведи по полосам, "
                                  f"по времени или добавь duck с band= у закрывающего слоя")
    if not links and not followed: notes.append("ни один слой не реагирует на другой: нет duck по ключу (key=) и нет follow(). Взаимодействие элементов = 0")
    if clock: notes.append(f"duck по часам (а не по реальной бочке) у слоёв {clock}: поставь key=\"kick\", тогда качание следует за паузами и сбивками бочки")
    if tonal and used_planes <= 1: notes.append("все тональные слои на одном расстоянии (" + next(k for k, v in pl.items() if v) + "): раздай depth= / send= — передний, средний и дальний план")
    if tonal and not spaces: notes.append("нет общего пространства: слои не посланы ни в одну общую комнату/эхо (trk.add(..., send={\"room\": .2}))")
    for a, b, j in dbl: notes.append(f"«{a}» и «{b}» бьют в одни и те же доли ({j:.0%} совпадений): один из них лишний или пусть отвечает в паузах другого")
    if tx["longest_same_bars"] > 32: notes.append(f"фактура не меняется {tx['longest_same_bars']} тактов подряд (всего {tx['states']} сочетаний слоёв за трек)")
    for n, c in getattr(trk, "flushes", {}).items():
        if c > 1 and not n.startswith("space:"): notes.append(f"шина «{n}» влилась в микс {c} раза: вызывай bus-эффекты (pullback, freeze, mono_low...) после того, как добавлены все слои шины")
    tot = sum(E[:bars * 16].sum(0) for E in act.values()); lc = np.log2(np.sqrt(EDGES[:-1] * EDGES[1:])); sel = (lc > np.log2(100)) & (lc < np.log2(10000))
    tilt = float(np.polyfit(lc[sel], 10 * np.log10(tot[sel] + 1e-20), 1)[0])
    return {"layers": L, "static": static, "hidden": hidden, "links": links, "followed": followed, "clock_ducks": clock, "doubles": dbl, "dialogs": dia,
            "planes": pl, "spaces": spaces, "texture": tx, "tilt_db_oct": round(tilt, 1), "score": score, "notes": notes,
            "errors": getattr(trk, "act_err", [])[:5]}

def gates(rep, g):
    """opt-in gates -> list of problem strings"""
    g = g or {}; out = []
    if not rep or "layers" not in rep: return out
    if "depth_static_max" in g and len(rep.get("static", [])) > g["depth_static_max"]: out.append(f"застывшие слои-петли {rep['static']} (допустимо {g['depth_static_max']})")
    nl = len(rep.get("links", [])) + len(rep.get("followed", []))
    if "depth_links_min" in g and nl < g["depth_links_min"]: out.append(f"взаимодействий между слоями {nl} < {g['depth_links_min']} (duck по ключу / follow)")
    np_ = sum(1 for v in rep.get("planes", {}).values() if v)
    if "depth_planes_min" in g and np_ < g["depth_planes_min"]: out.append(f"планов глубины {np_} < {g['depth_planes_min']}")
    if "depth_masked_max" in g:
        bad = [n for n, d in rep["layers"].items() if d.get("masked", 0) > g["depth_masked_max"] and n in rep.get("hidden", [])]
        if bad: out.append(f"слои закрыты другими сильнее {g['depth_masked_max']:.0%}: {bad}")
    return out
