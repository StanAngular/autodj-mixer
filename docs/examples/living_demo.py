"""P133 reference score: ONE set of notes, two ways of making sound out of them. No sample packs needed (everything is synthesised),
so it renders on any machine and is the A/B that shows what P130-P133 change:

    python -m autodj.compose run docs/examples/living_demo.py --name living                      # the new way
    AUTODJ_DEMO_FLAT=1 python -m autodj.compose run docs/examples/living_demo.py --name flat     # the old way, same notes

FLAT (how the engine worked so far): every note of a part is the same sound, each part has its own reverb, the «sidechain» is a
clock, all parts are summed straight into the mix.
LIVING: the same notes through the living synth (filter envelopes, velocity -> tone, LFOs across the phrase, no two notes equal, the
sound develops over the track), parts that listen to each other (bass and pad duck under the REAL kick, the pad gives way to the hook
only in the hook's band, the pad's filter closes while the hats play, the stab's echo blooms in the gaps), one shared room / hall /
echo with front-middle-back planes, a drum bus with glue + parallel compression. Both use the same master, so the only difference
is the engine; AUTODJ_DEMO_MASTER=studio renders with the P130 studio master (a third variant to compare).
Use it as the template for a real score: replace the synthesised drums with the track's kit and take the tonal patches from the lab
(autodj.compose.soundlab) instead of the hand-written ones below. AUTODJ_DEMO_BARS=32 renders a short version (tests)."""
import os
import numpy as np
from autodj.compose import Track, mono2
from autodj.compose.bus import glue, smash
from autodj.compose.synth import Synth, patch, procedural_table
from autodj.compose.harmony import Key, chord_of, lead_voices, comp_rhythm
from autodj.compose.bass import house_bass
from autodj.compose.hook import anchor_hook, accents

FLAT = os.environ.get("AUTODJ_DEMO_FLAT") == "1"
BARS = int(os.environ.get("AUTODJ_DEMO_BARS", "64"))
META = {"title": "Living Demo (flat)" if FLAT else "Living Demo (deep house)", "genre": "deep house", "key": "F minor", "target": -14.0,
        "master": os.environ.get("AUTODJ_DEMO_MASTER", "warm"), "story": "same notes, old engine vs living engine"}   # the SAME master both ways: one variable
CHORDS = [("F", "madd9"), ("F", "madd9"), ("C#", "maj7"), ("C#", "maj7"), ("A#", "m7"), ("A#", "m7"), ("C", "7sus4"), ("C", "7sus4")]
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}

# ---- drum hits: the W.A. kit when the sample packs are on this machine, otherwise synthesised stand-ins ----------------------
def _synth_kit(sr):
    from scipy.signal import butter, sosfilt
    from autodj.compose.instruments import hand_drum
    def noise(dur, lo, hi, decay, seed, attack=.0008):
        t = np.arange(int(dur * sr)) / sr; n = sosfilt(butter(2, [lo, hi], "band", fs=sr, output="sos"), np.random.default_rng(seed).normal(0, 1, len(t)))
        return mono2((n * np.exp(-t / decay) * np.minimum(1, t / attack)).astype(np.float32))
    t = np.arange(int(.3 * sr)) / sr; f = 50 + 105 * np.exp(-t / .026); body = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / .11)
    kick = np.tanh(1.5 * (body + .08 * np.random.default_rng(1).normal(0, 1, len(t)) * np.exp(-t / .003) * np.minimum(1, t / .0005)))
    kick = mono2(sosfilt(butter(2, 3500, "low", fs=sr, output="sos"), kick).astype(np.float32))
    c = noise(.28, 800, 3600, .06, 5); clap = np.zeros_like(c)
    for k, d in enumerate((0, .011, .023)): i = int(d * sr); clap[i:] += c[:len(c) - i] * (.6, .8, 1.0)[k]
    return dict(kick=kick, hat=noise(.06, 5000, 9500, .012, 2, .002), ohat=noise(.25, 4500, 9000, .07, 3, .003), clap=clap,
                perc=[hand_drum(260, .1, .12, sr, 4), hand_drum(340, .4, .09, sr, 6)])

def kit(sr, tonic_pc):
    from autodj.compose.assets import WA, WA2
    from autodj.compose import load_sample
    f = {"kick": f"{WA}/Kicks/WART_Kick_5.wav", "hat": f"{WA}/Cymbals/WATE_Hithat_02.wav", "ohat": f"{WA}/Cymbals/WATS_Open_HiHat_04.wav",
         "clap": f"{WA2}/Percussion/WAFTH_Clap_06.wav", "p1": f"{WA}/Percussion/WATE_Percussion_03.wav", "p2": f"{WA}/Percussion/WATE_Percussion_07.wav"}
    if not all(os.path.exists(v) for v in f.values()) or os.environ.get("AUTODJ_DEMO_SYNTH_KIT") == "1": return _synth_kit(sr)
    from autodj.compose.timbre import tune_kick
    k, _ = tune_kick(load_sample(f["kick"], .35), tonic_pc)
    return dict(kick=k, hat=load_sample(f["hat"], .08), ohat=load_sample(f["ohat"], .3), clap=load_sample(f["clap"], .35), perc=[load_sample(f["p1"], .2), load_sample(f["p2"], .2)])

def sections(nb):
    """a small rondo scaled to nb bars: intro -> home -> short break -> home + hook -> journey -> outro"""
    q = lambda f: int(nb * f / 4 + .5) * 4; a, b, c, d = q(.125), q(.375), q(.4375), q(.75); e = min(q(.9375), nb - 4)
    drums = dict(kick=1, hats=1, clap=1, perc=1)
    return [(0, a, "intro", dict(kick=1, hats=1, bass=1)), (a, b, "home", dict(drums, bass=1, stab=1, pad=1)),
            (b, c, "break", dict(hats=1, pad=1, stab=1, bass=1, _break=1)), (c, d, "home2", dict(drums, bass=1, stab=1, pad=1, hook=1)),
            (d, e, "journey", dict(drums, bass=1, pad=1, hook=1)), (e, nb, "outro", dict(kick=1, hats=1, bass=1, pad=1))]

def build(seed):
    trk = Track(124, BARS, seed=seed, swing=.08).sections(sections(BARS)); trk.step_env = True
    key = Key("F", "minor"); T = trk.N / trk.sr; S16 = trk.S16; live = not FLAT
    CH = [chord_of(NOTE[a], q) for a, q in CHORDS]; cp = lambda b: CH[b % 8]
    ev = lambda xs: [(trk.t(s // 16, s % 16, 0), m, v, l * S16 * .9) for s, l, m, v in xs]
    ends = {s[1] - 1 for s in trk.tl}

    # ---- the notes (identical in both versions): written first, with their own random generators
    roots = lambda b: cp(b)[0]
    bl = house_bass(np.random.default_rng(seed + 1), key, roots, BARS, lo=36, hi=52, onsets=(4, 6), chord_of_bar=cp)
    vo = lead_voices([cp(b) for b in range(8)], 55, 72, 4); cell = comp_rhythm(np.random.default_rng(seed + 3), (2, 3), min_off=2)
    stab = [(br * 16 + s, min(ln, 2), m, 100 if s % 4 else 82) for br in range(BARS) for s, ln in cell for m in vo[br % 8][1:]]
    pad = [(b * 16, 31, m, 78) for b in range(0, BARS, 2) for m in vo[b % 8][:3]]
    bst = lambda b: {s % 16 for s, *_ in bl if s // 16 == b}
    hk, _ = anchor_hook(np.random.default_rng(seed + 2), key, cp, bst, 65, 82, bars=BARS, home_pcs=cp(0))
    EV = {name: ev(xs) for name, xs in (("bass", bl), ("stab", stab), ("pad", pad), ("hook", hk))}        # timed BEFORE anything else draws from the track rng
    for name, e in EV.items(): trk.log_notes(name, e)

    # ---- drums: the same pattern both ways; LIVING adds accents, ghost notes, a pause of the kick before each section, a drum bus
    from pedalboard import Pedalboard, HighpassFilter, LowpassFilter
    from autodj.compose import pb
    Bf = {k: trk.buf() for k in ("kick", "hats", "clap", "perc")}; K = kit(trk.sr, key.tonic)
    prng = np.random.default_rng(seed + 5); perc_steps = sorted(prng.choice([3, 6, 7, 10, 11, 14], 3, replace=False).tolist())
    for br in range(BARS):
        for st in (0, 4, 8, 12):
            if live and br in ends and st == 12: continue                       # the kick breathes out before a new section
            trk.place(Bf["kick"], K["kick"], br * trk.BAR + st * S16)
        for st in range(16):
            if st % 4 == 2: trk.place(Bf["hats"], *((K["ohat"], trk.t(br, st, 0), .55) if (live and br % 4 == 3 and st == 14) else (K["hat"], trk.t(br, st, 0), .9)))
            elif live and st % 2: trk.place(Bf["hats"], K["hat"], trk.t(br, st), .32 * accents(st) / 110 * (1 + .25 * np.sin(br * .8 + st)))   # ghosts that move
        for st in (4, 12): trk.place(Bf["clap"], K["clap"], trk.t(br, st, 0), .8)
        if live and br % 8 == 7: trk.place(Bf["clap"], K["clap"], trk.t(br, 15, 0), .35)
        for i, st in enumerate(perc_steps):
            if FLAT or (br + st) % 5: trk.place(Bf["perc"], K["perc"][i % 2], trk.t(br, st), .6 if FLAT else .35 + .4 * prng.random(), pan=(-.15, .15)[i % 2])
    if live:
        trk.bus("drums", fx=[glue()], parallel=(smash(), .15))
        trk.space("room", kind="room"); trk.space("hall", kind="hall", back_db=-6); trk.space("echo", kind="echo", steps=3, fb=.5)
    D = dict(bus="drums") if live else {}
    trk.add("kick", pb(Pedalboard([HighpassFilter(30)]), Bf["kick"]), 1.0, **D)
    trk.add("hats", pb(Pedalboard([HighpassFilter(5000), LowpassFilter(9000)]), Bf["hats"]), level=10 ** (-28 / 20), **D, **(dict(send={"room": .12}) if live else {}))
    trk.add("clap", pb(Pedalboard([HighpassFilter(300), LowpassFilter(4500)]), Bf["clap"]), level=10 ** (-15 / 20), **D, **(dict(send={"room": .25}) if live else {}))
    trk.add("perc", pb(Pedalboard([HighpassFilter(200), LowpassFilter(8000)]), Bf["perc"]), level=10 ** (-17 / 20), **D, **(dict(send={"room": .2, "echo": .1}) if live else {}))

    # ---- the sounds: the same patches; FLAT strips everything that moves
    def still(p):
        q = patch(p, mods=[], drift=0); q["fx"] = {}; q["filt"].update(env=0, vel=0, cutoff=p["filt"]["cutoff"] * 2 ** (p["filt"]["env"] * .35)); q["amp"]["vel"] = .5; return q
    P = {"bass": patch(osc=[dict(wave="saw", unison=3, detune=9, spread=.15), dict(wave="sine", level=.35)],
                       filt=dict(cutoff=190, res=.32, env=3.2, vel=1.6, key=.2, drive=5), amp=dict(a=.002, d=.22, s=.35, r=.07), fenv=dict(a=.001, d=.13, s=0, r=.08),
                       mods=[dict(src="lfo", dst="cutoff", amt=.7, rate="4b", phase=.75), dict(src="rand", dst="cutoff", amt=.25), dict(src="ctl:energy", dst="cutoff", amt=1.0)]),
         "stab": patch(osc=[dict(wave="saw", unison=5, detune=16, spread=.8), dict(wave="pulse", pw=.3, level=.5, semi=12)],
                       filt=dict(cutoff=520, res=.25, env=2.9, vel=1.3, key=.3), amp=dict(a=.002, d=.2, s=.1, r=.25), fenv=dict(a=.001, d=.16, s=.05, r=.2),
                       mods=[dict(src="lfo", dst="cutoff", amt=.9, rate="8b"), dict(src="rand", dst="pan", amt=.3), dict(src="pos", dst="cutoff", amt=.5), dict(src="lfo", dst="pw", amt=.15, rate="2b")], fx=dict(chorus=.4)),
         "pad": patch(osc=[dict(wave="wt", table="t", pos=.2, unison=5, detune=14, spread=1.0), dict(wave="saw", level=.35, unison=3, detune=20, spread=.7)],
                      filt=dict(cutoff=420, res=.15, env=1.2, per="layer"), amp=dict(a=.5, d=1.5, s=.85, r=1.2), fenv=dict(a=.9, d=2.5, s=.4, r=1.0),
                      mods=[dict(src="lfo", dst="cutoff", amt=.9, rate="16b", phase=.6), dict(src="ctl:hats", dst="cutoff", amt=-.9), dict(src="lfo", dst="pos", amt=.35, rate="8b"), dict(src="time", dst="cutoff", amt=.6)]),
         "hook": patch(osc=[dict(wave="fm", ratio=2.0, index=.8), dict(wave="tri", level=.6)],
                       filt=dict(cutoff=650, res=.2, env=1.8, vel=1.2, key=.3), amp=dict(a=.003, d=.25, s=.3, r=.3), fenv=dict(a=.002, d=.2, s=.1, r=.25),
                       mods=[dict(src="env", dst="index", amt=1.8), dict(src="vel", dst="index", amt=1.0), dict(src="lfo_note", dst="pitch", amt=.06, rate=5.2), dict(src="rand", dst="cutoff", amt=.3), dict(src="time", dst="index", amt=.7)])}
    tables = {"t": procedural_table(np.random.default_rng(seed + 9))}
    energy = trk.curve([{"intro": .2, "home": .55, "break": .3, "home2": .8, "journey": 1.0, "outro": .3}[trk.sec(b)[2]] for b in range(BARS)], 4, step=False)
    ctl = {"energy": energy, "hats": trk.follow("hats", attack_ms=40, release_ms=900)} if live else {}
    R = lambda name: Synth(P[name] if live else still(P[name]), bpm=trk.bpm, seed=seed, tables=tables).render(EV[name], T, ctl=ctl)
    bass, stb, pd, hook = R("bass"), R("stab"), R("pad"), R("hook")
    LV = dict(bass=-4, hook=-8, stab=-8, pad=-10)                                # dB re the kick, the same both ways

    if live:
        trk.add("bass", bass, level=10 ** (LV["bass"] / 20), duck=-7.0, key="kick", release_ms=160)
        trk.add("hook", hook, level=10 ** (LV["hook"] / 20), duck=-2.0, key="kick", send={"echo": .22, "room": .12})                  # front
        trk.add("stab", stb, level=10 ** (LV["stab"] / 20), duck=-3.0, key="kick", depth=.35, send={"echo": .25, "room": .15})        # middle
        trk.add("pad", pd, level=10 ** (LV["pad"] / 20), duck=-4.0, key=["hook", "stab"], band=(400, 3500), depth=.8, send={"hall": .35})   # back, gives way to the hook
    else:
        from pedalboard import Reverb, Delay
        trk.add("bass", bass, level=10 ** (LV["bass"] / 20), duck=-6.0)
        trk.add("hook", pb(Pedalboard([Delay(S16 * 3, .3, .2), Reverb(room_size=.45, wet_level=.15, dry_level=.9)]), hook), level=10 ** (LV["hook"] / 20), duck=-3.0)
        trk.add("stab", pb(Pedalboard([Delay(S16 * 3, .3, .2), Reverb(room_size=.4, wet_level=.15, dry_level=.9)]), stb), level=10 ** (LV["stab"] / 20), duck=-3.0)
        trk.add("pad", pb(Pedalboard([Reverb(room_size=.8, wet_level=.3, dry_level=.8)]), pd), level=10 ** (LV["pad"] / 20), duck=-3.0)
    trk.mono_low(140)
    return trk
