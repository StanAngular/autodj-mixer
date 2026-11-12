"""P136 reference score: a track whose HARMONY is a plan (chords.Plan) and whose lines are written against it (lines.py).
Nothing harmonic is typed in by hand: no `CH = [...]`, no note lists. Change STYLE / the idioms / the seed and it is another piece.

    python -m autodj.compose run docs/examples/deep_harmony_demo.py --name harmony_garage                       # UK garage, 130
    AUTODJ_DEMO_STYLE=melodic python -m autodj.compose run docs/examples/deep_harmony_demo.py --name harmony_melodic
    AUTODJ_DEMO_HARMONY=old python -m autodj.compose run docs/examples/deep_harmony_demo.py --name harmony_old    # A/B: the old way

AUTODJ_DEMO_HARMONY=old keeps every sound, rhythm and level and replaces only the harmony by what the scores did so far: the loop
i(add9) | VI maj7 | iv m7 | V7sus4, one chord per bar for the whole track, block voicings, root bass without approach notes, lines
from chord tones only. The difference between the two renders is the subject of P134.

What the plan gives here: home = an 8-bar sentence and its varied answer (slide chords, early changes, another turnaround each time),
journey = another sentence (garage: in the relative major), intro / outro = plainer chords over a pedal, break = two long chords,
build = dominant pedal. Keys play voice-led drop-2 voicings under a slow top line, the bass marks every change and walks into the
next root, the hook is one idea re-fitted to whatever chords are under it, a three-note ostinato runs in 6/16 against the bar,
a counter line answers in the hook's rests. No per-note panning (static stereo only). Drums: patterns are drawn per seed; samples, when the packs are on the machine, are the
LEAST used ones in the freshness ledger (fresh.pick), otherwise synthesised stand-ins. AUTODJ_DEMO_BARS=48 renders a short version."""
import glob, os
import numpy as np
from autodj.compose import Track, mono2, pb, load_sample, fresh, chords as C, lines as L
from autodj.compose.bus import glue, smash
from autodj.compose.synth import Synth, patch, procedural_table
from autodj.compose.harmony import comp_rhythm

STYLE = os.environ.get("AUTODJ_DEMO_STYLE", "garage"); OLD = os.environ.get("AUTODJ_DEMO_HARMONY") == "old"; SCALE = int(os.environ.get("AUTODJ_DEMO_BARS", "96")) / 96
ST = {"garage":  dict(bpm=130, tonic="F", home="garage_steps", journey="soul_major", shift=3, swing=.16, two_step=True, title="Harmony Demo (UK garage)"),
      "deep":    dict(bpm=122, tonic="A", home="dorian_vamp", journey="line_cliche", shift=0, swing=.08, two_step=False, title="Harmony Demo (deep house)"),
      "melodic": dict(bpm=124, tonic="D", home="mediant_drift", journey="pedal_lift", shift=0, swing=.0, two_step=False, title="Harmony Demo (melodic house)")}[STYLE]
META = {"title": ST["title"] + (" old harmony" if OLD else ""), "genre": STYLE, "key": ST["tonic"] + "m", "target": -14.0, "master": "warm",
        "story": "harmony from chords.Plan, lines from lines.py" if not OLD else "same sounds, the old four-chord loop"}
PL = [("intro", 8), ("home1", 16), ("journey1", 12), ("home2", 16), ("break", 8), ("build", 4), ("home3", 16), ("journey2", 8), ("outro", 8)]

def sections():
    out, b = [], 0; D = dict(kick=1, hats=1, clap=1, perc=1); T = dict(bass=1, keys=1, pad=.8)
    lv = {"intro": dict(kick=1, hats=1, bass=1, pad=1), "home1": dict(D, **T, hook=1), "journey1": dict(D, **T, ost=1, hook=1), "home2": dict(D, **T, hook=1, ost=1),
          "break": dict(hats=.7, pad=1.2, keys=1.1, top=1, _break=1), "build": dict(hats=1, clap=1, pad=1, keys=1, arp=1, bass=1),
          "home3": dict(D, **T, hook=1, ost=.8, counter=1, arp=.6), "journey2": dict(D, **T, hook=1, ost=1), "outro": dict(kick=1, hats=1, bass=1, pad=1, keys=.7)}
    for name, n in PL:
        n = max(4, int(round(n * SCALE / 4)) * 4); out.append((b, b + n, name, lv[name])); b += n
    return out

# ---- drum hits -------------------------------------------------------------------------------------------------------------------
def synth_kit(sr):
    from scipy.signal import butter, sosfilt
    from autodj.compose.instruments import hand_drum
    def noise(dur, lo, hi, decay, seed, attack=.002):
        t = np.arange(int(dur * sr)) / sr; n = sosfilt(butter(2, [lo, hi], "band", fs=sr, output="sos"), np.random.default_rng(seed).normal(0, 1, len(t)))
        return mono2((n * np.exp(-t / decay) * np.minimum(1, t / attack)).astype(np.float32))
    t = np.arange(int(.3 * sr)) / sr; f = 50 + 105 * np.exp(-t / .026); body = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / .11)
    kick = np.tanh(1.5 * (body + .08 * np.random.default_rng(1).normal(0, 1, len(t)) * np.exp(-t / .003) * np.minimum(1, t / .0005)))
    c = noise(.28, 800, 3600, .06, 5); clap = np.zeros_like(c)
    for k, d in enumerate((0, .011, .023)): i = int(d * sr); clap[i:] += c[:len(c) - i] * (.6, .8, 1.0)[k]
    return dict(kick=mono2(sosfilt(butter(2, 3500, "low", fs=sr, output="sos"), kick).astype(np.float32)), hat=noise(.06, 5000, 9500, .012, 2), ohat=noise(.25, 4500, 9000, .07, 3, .003),
                clap=clap, perc=[hand_drum(260, .1, .12, sr, 4), hand_drum(340, .4, .09, sr, 6)])

def kit(sr, rng, title):
    """real hits where the packs are installed: for every piece the file the EARLIER tracks used least (fresh.pick); else synthesised"""
    from autodj.compose.assets import WA
    K = synth_kit(sr)
    if os.environ.get("AUTODJ_DEMO_SYNTH_KIT") == "1": return K
    db = fresh.load()
    for name, pat, mx in (("kick", "Kicks/*Kick*.wav", .35), ("hat", "Cymbals/*Hithat*.wav", .08), ("ohat", "Cymbals/*Open*.wav", .3), ("clap", "Claps/*Clap*.wav", .35)):
        c = glob.glob(os.path.join(WA, pat))
        if c: K[name] = load_sample(fresh.pick(c, rng, db=db, title=title), mx)
    c = glob.glob(os.path.join(WA, "Percussion/*.wav"))
    if len(c) >= 2: K["perc"] = [load_sample(p, .2) for p in fresh.pick(c, rng, k=2, db=db, title=title)]
    return K

def write(seed):
    """the composition only (no audio): Track with its sections, the harmony plan and every line -> (trk, plan, lines, events)"""
    secs = sections(); BARS = secs[-1][1]; trk = Track(ST["bpm"], BARS, seed=seed, swing=ST["swing"]).sections(secs); trk.step_env = True
    S16 = trk.S16; SP = {n: (a, b) for a, b, n, _ in secs}

    # ---- the harmony of the whole track, then every line against it (all before the drums: their timing draws from the track rng)
    if OLD:
        loop = C.sentence("old_loop", ST["tonic"]); slots = []; pos = 0
        for a, b, name, _ in secs:
            for n, c in C.cycle(loop, (b - a) * 16): slots.append((pos, n, c, name)); pos += n
        plan = C.Plan(ST["tonic"], "minor", BARS, slots, {"home": "old_loop", "journey": None}); colour = 0.0
        V = plan.voicings("close", 50, 74); top = None; bass = plan.bass(np.random.default_rng([seed, 1]), 29, 46, approach=0.0, against=V)
    else:
        plan = C.Plan.build(ST["tonic"], secs, ST["home"], ST["journey"], seed=seed, journey_shift=ST["shift"]); colour = None
        top, topline = L.topline(plan, np.random.default_rng([seed, 2]), 65, 77); V = plan.voicings("drop2", 50, 78, top=top)
        bass = plan.bass(np.random.default_rng([seed, 1]), 29, 46, style="root", against=V)
    plan.attach(trk); ctx = L.context(plan, V, bass)
    bsteps = {}
    for s, *_ in bass: bsteps.setdefault(s // 16, set()).add(s % 16)
    h8 = L.hook(plan, np.random.default_rng([seed, 3]), 62, 79, SP["home1"][0], ctx, lambda b: bsteps.get(b, ()), colour=colour)
    starts = [b for n in ("home1", "journey1", "home2", "home3", "journey2") for b in range(SP[n][0] + (8 if n == "home1" else 4 if n == "journey1" else 0), SP[n][1], 8)]
    hook = L.tile(h8, plan, 62, 79, starts, ctx, origin=SP["home1"][0]); ctx2 = L.context(plan, V, bass, hook)
    ost = [n for a, b in (SP["journey1"], SP["home2"], SP["home3"], SP["journey2"]) for n in L.ostinato(plan, np.random.default_rng([seed, 4]), 74, 88, a, b, n=3, step=2, ctx=ctx2, rest_every=8)]
    cnt = L.counter(plan, hook, np.random.default_rng([seed, 5]), 55, 67, L.context(plan, V, bass, hook, ost)); cnt = [n for n in cnt if SP["home3"][0] * 16 <= n[0] < SP["home3"][1] * 16]
    arp = L.arp(plan, V, np.random.default_rng([seed, 6]), SP["build"][0], SP["home3"][1], step=1, shape="updown", lo=60, hi=86)
    cells = [comp_rhythm(np.random.default_rng([seed, 8, k]), (2, 3), min_off=2) for k in range(3)]; keys = []; pad = []
    for s0, n, v in V:                                                               # keys: a hit on every change + a comping cell; pad: the lower voices, held
        name = plan.slots[plan.idx(s0)][3]; held = name in ("break", "intro", "outro")
        if held: keys += [(s0, n - 1, m, 74) for m in v]
        else:
            hits = sorted({s0} | {b * 16 + s for b in range(s0 // 16, (s0 + n - 1) // 16 + 1) for s, _ in cells[(b // 4) % 3] if s0 < b * 16 + s < s0 + n})
            for i, h in enumerate(hits):
                ln = min(3 if i else 4, (hits[i + 1] if i + 1 < len(hits) else s0 + n) - h, s0 + n - h); keys += [(h, max(1, ln), m, (92 if i == 0 else 70) + (6 if m == v[-1] else 0)) for m in v]
        if n >= 8: pad += [(s0, n, m, 76) for m in v[:3]]                                          # the pad holds the keys' lower voices (slide chords are too short for it)
    lines_ = {"bass": bass, "keys": keys, "pad": pad, "hook": hook, "ost": ost, "counter": cnt, "arp": arp}
    if top is not None: lines_["top"] = [n for n in topline if SP["break"][0] * 16 <= n[0] < SP["break"][1] * 16]
    ev = lambda xs: [(trk.t(s // 16, s % 16, 0), m, v, max(1, l) * S16 * .93) for s, l, m, v in xs]
    EV = {k: ev(v) for k, v in lines_.items()}
    for k, e in EV.items(): trk.log_notes(k, e)
    trk.line_fit = {k: L.fit(lines_[k], plan, ctx if k == "hook" else None) for k in ("hook", "ost", "counter", "bass")}
    return trk, plan, lines_, EV

def build(seed):
    trk, plan, lines_, EV = write(seed); secs = trk.tl; BARS = trk.bars; S16 = trk.S16; T = trk.N / trk.sr; SP = {n: (a, b) for a, b, n, *_ in secs}
    inb = lambda *names: [b for n in names for b in range(*SP[n])]

    # ---- drums: the patterns are drawn for this seed (no fixed template); pieces picked fresh when real packs are there
    from pedalboard import Pedalboard, HighpassFilter, LowpassFilter
    K = kit(trk.sr, np.random.default_rng([seed, 9]), META["title"]); prng = np.random.default_rng([seed, 10]); Bf = {k: trk.buf() for k in ("kick", "hats", "clap", "perc")}
    ghosts = sorted(prng.choice([1, 3, 5, 7, 9, 11, 13, 15], int(prng.integers(2, 5)), replace=False).tolist()); openh = int(prng.choice([6, 10, 14]))
    perc_steps = sorted(prng.choice([3, 6, 7, 9, 10, 11, 14, 15], 3, replace=False).tolist()); k2 = [(0, int(prng.choice([6, 7])), 10), (0, int(prng.choice([3, 10])), int(prng.choice([11, 14])))]
    ends = {b - 1 for a, b, n, _ in secs}; bld = set(inb("build"))
    for br in range(BARS):
        ks = (k2[br % 2] if ST["two_step"] else (0, 4, 8, 12)) if br not in bld else (0, 8)
        for st in ks:
            if br in ends and st >= 12: continue                                     # the kick breathes out before a new section
            trk.place(Bf["kick"], K["kick"], br * trk.BAR + st * S16, 1.0 if st % 8 == 0 else .88)
        for st in range(16):
            if st % 4 == 2: trk.place(Bf["hats"], *((K["ohat"], trk.t(br, st, 0), .5) if (br % 4 == 3 and st == openh) else (K["hat"], trk.t(br, st, 0), .9)))
            elif st in ghosts and (br + st) % 3: trk.place(Bf["hats"], K["hat"], trk.t(br, st), .22 + .16 * prng.random())
        for st in (4, 12): trk.place(Bf["clap"], K["clap"], trk.t(br, st, 0), .8)
        if br in bld: [trk.place(Bf["clap"], K["clap"], trk.t(br, st, 0), .25 + .5 * (br - min(bld) + st / 16) / len(bld)) for st in range(0, 16, 2 if br < max(bld) else 1) if st not in (4, 12)]
        elif br % 8 == 7: trk.place(Bf["clap"], K["clap"], trk.t(br, int(prng.choice([13, 14, 15])), 0), .35)
        for i, st in enumerate(perc_steps):
            if (br + st) % 5: trk.place(Bf["perc"], K["perc"][i % 2], trk.t(br, st), .35 + .4 * prng.random(), pan=(-.15, .15)[i % 2])
    trk.bus("drums", fx=[glue()], parallel=(smash(), .15)); trk.space("room", kind="room"); trk.space("hall", kind="hall", back_db=-6); trk.space("echo", kind="echo", steps=3, fb=.45)
    D = dict(bus="drums")
    trk.add("kick", pb(Pedalboard([HighpassFilter(30)]), Bf["kick"]), 1.0, **D)
    trk.add("hats", pb(Pedalboard([HighpassFilter(5000), LowpassFilter(9000)]), Bf["hats"]), level=10 ** (-28 / 20), send={"room": .12}, **D)
    trk.add("clap", pb(Pedalboard([HighpassFilter(300), LowpassFilter(4500)]), Bf["clap"]), level=10 ** (-15 / 20), send={"room": .25}, **D)
    trk.add("perc", pb(Pedalboard([HighpassFilter(200), LowpassFilter(8000)]), Bf["perc"]), level=10 ** (-18 / 20), send={"room": .2, "echo": .1}, **D)

    # ---- sounds: the living synth; every part listens to something
    en = {"intro": .25, "home1": .6, "journey1": .7, "home2": .85, "break": .3, "build": .6, "home3": 1.0, "journey2": .9, "outro": .3}
    energy = trk.curve([en[trk.sec(b)[2]] for b in range(BARS)], 4, step=False); tab = {"t": procedural_table(np.random.default_rng([seed, 11])), "u": procedural_table(np.random.default_rng([seed, 12]))}
    ctl = {"energy": energy, "hats": trk.follow("hats", attack_ms=40, release_ms=900), "kick": trk.follow("kick", attack_ms=2, release_ms=180)}
    P = {"bass": patch(osc=[dict(wave="saw", unison=3, detune=9, spread=.15), dict(wave="sine", level=.35)], filt=dict(cutoff=180, res=.3, env=3.0, vel=1.5, key=.2, drive=5),
                       amp=dict(a=.002, d=.24, s=.4, r=.07), fenv=dict(a=.001, d=.13, s=0, r=.08), glide_ms=45,
                       mods=[dict(src="lfo", dst="cutoff", amt=.6, rate="4b", phase=.75), dict(src="rand", dst="cutoff", amt=.2), dict(src="ctl:energy", dst="cutoff", amt=.9)]),
         "keys": patch(osc=[dict(wave="fm", ratio=1.0, index=.5), dict(wave="sine", level=.5), dict(wave="fm", ratio=7.0, index=.15, level=.12)],          # an electric-piano kind of tone
                       filt=dict(cutoff=900, res=.1, env=1.6, vel=1.4, key=.4), amp=dict(a=.003, d=1.1, s=.25, r=.35, vel=.75), fenv=dict(a=.002, d=.4, s=.1, r=.3),
                       mods=[dict(src="env", dst="index", amt=1.6), dict(src="vel", dst="index", amt=1.2), dict(src="lfo", dst="amp", amt=.9, rate="1/8."),
                             dict(src="ctl:energy", dst="cutoff", amt=.7)], fx=dict(chorus=.2)),
         "pad": patch(osc=[dict(wave="wt", table="t", pos=.2, unison=5, detune=13, spread=1.0), dict(wave="saw", level=.3, unison=3, detune=19, spread=.7)],
                      filt=dict(cutoff=380, res=.15, env=1.0, per="layer"), amp=dict(a=.6, d=1.5, s=.85, r=1.4), fenv=dict(a=.9, d=2.5, s=.4, r=1.0),
                      mods=[dict(src="lfo", dst="cutoff", amt=.8, rate="16b", phase=.6), dict(src="ctl:hats", dst="cutoff", amt=-.8), dict(src="lfo", dst="pos", amt=.35, rate="8b"), dict(src="time", dst="cutoff", amt=.5)]),
         "hook": patch(osc=[dict(wave="pulse", pw=.32, unison=2, detune=7), dict(wave="tri", level=.55)], filt=dict(cutoff=700, res=.22, env=1.9, vel=1.2, key=.35),
                       amp=dict(a=.004, d=.35, s=.45, r=.3), fenv=dict(a=.003, d=.22, s=.15, r=.25), glide_ms=55,
                       mods=[dict(src="lfo", dst="pw", amt=.12, rate="2b"), dict(src="lfo_note", dst="pitch", amt=.05, rate=5.1), dict(src="rand", dst="cutoff", amt=.25), dict(src="time", dst="cutoff", amt=.5)]),
         "ost": patch(osc=[dict(wave="wt", table="u", pos=.3), dict(wave="sine", level=.4, semi=12)], filt=dict(cutoff=600, res=.3, env=3.0, vel=1.0, key=.3),
                      amp=dict(a=.002, d=.16, s=0, r=.18), fenv=dict(a=.001, d=.11, s=0, r=.15),
                      mods=[dict(src="lfo", dst="cutoff", amt=1.0, rate="8b"), dict(src="lfo", dst="pos", amt=.4, rate="4b"), dict(src="ctl:kick", dst="amp", amt=-3.0)]),
         "counter": patch(osc=[dict(wave="tri"), dict(wave="fm", ratio=2.0, index=.4, level=.4)], filt=dict(cutoff=500, res=.1, env=1.2, key=.4), amp=dict(a=.02, d=.5, s=.5, r=.4),
                          fenv=dict(a=.02, d=.4, s=.2, r=.3), mods=[dict(src="lfo_note", dst="pitch", amt=.04, rate=4.7), dict(src="rand", dst="cutoff", amt=.2)]),
         "arp": patch(osc=[dict(wave="saw", unison=2, detune=8)], filt=dict(cutoff=350, res=.35, env=2.6, vel=.8), amp=dict(a=.002, d=.12, s=0, r=.12), fenv=dict(a=.001, d=.09, s=0, r=.1),
                      mods=[dict(src="time", dst="cutoff", amt=1.2), dict(src="ctl:energy", dst="cutoff", amt=1.4), dict(src="pos", dst="cutoff", amt=.5)])}
    P["top"] = P["counter"]
    R = lambda name: Synth(P[name], bpm=trk.bpm, seed=seed, tables=tab).render(EV[name], T, ctl=ctl)
    trk.add("bass", R("bass"), level=10 ** (-4 / 20), duck=-7.0, key="kick", release_ms=160)
    trk.add("hook", R("hook"), level=10 ** (-9 / 20), duck=-2.0, key="kick", send={"echo": .2, "room": .12})                                   # front
    trk.add("keys", R("keys"), level=10 ** (-9 / 20), duck=-3.0, key="kick", depth=.3, send={"room": .18, "echo": .1})                        # middle
    trk.add("ost", R("ost"), level=10 ** (-15 / 20), depth=.45, send={"echo": .3, "room": .15})
    trk.add("counter", R("counter"), level=10 ** (-13 / 20), duck=-3.0, key="hook", depth=.4, send={"hall": .25})
    trk.add("arp", R("arp"), level=10 ** (-14 / 20), duck=-3.0, key="kick", depth=.5, send={"echo": .25})
    if "top" in EV: trk.add("top", R("top"), level=10 ** (-12 / 20), depth=.5, send={"hall": .35, "echo": .15})
    trk.add("pad", R("pad"), level=10 ** (-13 / 20), duck=-4.0, key=["hook", "keys"], band=(400, 3500), depth=.85, send={"hall": .35})          # back
    trk.mono_low(140)
    return trk
