"""Neon Decay (techno breakbeat) — modern techno breakbeat hybrid.
132 BPM, G minor, dark atmospherics, breakbeat percussion, WA samples only.
Key features: SG.pick melodic samples within ±7 st, no allow_silent/allow_bad_sounds,
levels from kick=1.0 hierarchy, bass mono, int velocities, no ampeg_attack override.
"""
import glob, os
import numpy as np
from autodj.compose import Track, pb, load_sample, fresh, chords as C, lines as L, microtiming as MT, sfz, soundgate as SG
from autodj.compose.bus import glue, smash
from autodj.compose.assets import WA
from pedalboard import Pedalboard, HighpassFilter, LowpassFilter, Distortion, Reverb, Delay, Chorus, Compressor, LadderFilter

BPM = 132
TITLE = "Neon Decay (techno breakbeat)"
META = {"title": TITLE, "genre": "techno breakbeat", "key": "Gm", "target": -12.0, "master": "warm", "lead": "synth"}
D = dict(kick=1, clap=1, hat=1, perc=1, bass=1, chord=.7, pluck=.8, pad=1)
CACHE = "/home/hermes/.hermes/cache/scratch/sfz/_oneshots"

SECS = [
    (0, 8, "intro", dict(hat=.4, pad=1)),
    (8, 16, "build", dict(kick=.6, hat=.6, perc=.5, pad=1)),
    (16, 28, "drop_a", dict(D, pluck=.8)),
    (28, 36, "bridge", dict(kick=.4, hat=.5, chord=.6, pad=1.2)),
    (36, 40, "pre_drop", dict(kick=.7, hat=.7, perc=.7, bass=.7, chord=.6, pad=1)),
    (40, 56, "drop_b", dict(D, pluck=1, perc=1.1)),
    (56, 64, "break", dict(kick=.3, hat=.4, pad=1.5, chord=.4)),
    (64, 76, "drop_c", dict(D, pluck=1.2, perc=1.2, kick=1.1)),
    (76, 80, "outro", dict(kick=.3, hat=.3, pad=1)),
]

def build(seed):
    trk = Track(BPM, 80, seed=seed, swing=.03, tail_s=4).sections(SECS)
    trk.step_env = True
    S16, T = trk.S16, trk.N / trk.sr
    db = fresh.load()
    mt = MT.Ensemble(trk, seed)
    rng = np.random.default_rng([seed, 80])
    prng = np.random.default_rng([seed, 10])

    # Harmony: G minor, dark lament + minor_plagal
    plan = C.Plan.build("G", trk.tl, "lament", "minor_plagal", seed=seed)
    plan.attach(trk)
    SP = {n: (a, b) for a, b, n, _ in SECS}

    V = plan.voicings("close", 50, 62, n=3)
    bass = plan.bass(np.random.default_rng([seed, 1]), 28, 40, style="root", cell=[0, 3, 6, 9, 10, 14], approach=.2, against=V)
    ctx = L.context(plan, V, bass)
    bsteps = {}
    for s, *_ in bass:
        bsteps.setdefault(s // 16, set()).add(s % 16)

    # Hook / lead line from plan (not arithmetic)
    h8 = L.hook(plan, np.random.default_rng([seed, 3]), 57, 69, SP["drop_a"][0], ctx, lambda b: bsteps.get(b, ()))
    starts = [b for n in ("drop_a", "bridge", "drop_b", "break", "drop_c")
              for b in range(SP[n][0], SP[n][1], 8)]
    hook = L.tile(h8, plan, 57, 69, starts, ctx, origin=SP["drop_a"][0])

    chord = [(s0, n, m, 70) for s0, n, v in V if n >= 8 for m in v[:3]]
    pad = [(s0, n, m, 64) for s0, n, v in V if n >= 8 for m in v[:3]]
    lines_ = {"bass": bass, "chord": chord, "pluck": hook, "pad": pad}

    ev = lambda xs, k=.9: [(mt.time(s // 16, s % 16, "pluck"), m, MT.accent(s % 16, v), max(1, l) * S16 * k)
                           for s, l, m, v in xs]
    EV = {k: ev(v, 1.0 if k == "bass" else .9) for k, v in lines_.items()}
    for k, e in EV.items():
        trk.log_notes(k, e)
    trk.line_fit = {k: L.fit(lines_[k], plan, ctx if k == "pluck" else None) for k in ("pluck", "bass")}

    # Sample selection via SG.pick (pitch gate, ±7 st from root)
    pool = lambda *k: sorted({p for x in k for p in glob.glob(os.path.join(WA, "Synth & Bass Shots", x))})
    bf = SG.pick(pool("*Bass*.wav"), "bass", 28, 40, prng, db=db, title=TITLE, strict=False)
    # Chord: exclude Chord_Shot_1 (known wobble ±193c) - use Org/Synth as fallback
    cf = SG.pick(pool("*Chord*.wav", "*Org*.wav", "*Synth*.wav"), "pad", 50, 62, prng, db=db, title=TITLE, strict=False)
    pf = SG.pick(pool("*Lead*.wav", "*Pluck*.wav"), "lead", 57, 69, prng, db=db, title=TITLE, strict=False)
    # Pad: play at voicing octave (no -12), sample root within range 50-62
    pdf = SG.pick(pool("*Pad*.wav", "*Org*.wav", "*Synth*.wav"), "pad", 50, 62, prng, db=db, title=TITLE, strict=False)
    print("  sounds", [os.path.basename(x) for x in (bf, cf, pf, pdf)])

    # Drums (fresh.pick — least-used)
    kick_f = fresh.pick(glob.glob(os.path.join(WA, "Kicks/*Kick*")), rng, db=db, title=TITLE)
    clap_f = fresh.pick(glob.glob(os.path.join(WA, "Claps/*Clap*")), np.random.default_rng([seed, 2]), db=db, title=TITLE)
    hat_f = fresh.pick(
        glob.glob(os.path.join(WA, "Cymbals/*HiHat*")) + glob.glob(os.path.join(WA, "Cymbals/*Hithat*")),
        np.random.default_rng([seed, 3]), db=db, title=TITLE)
    perc_f = fresh.pick(glob.glob(os.path.join(WA, "Percussion/*Percussion*")),
                        np.random.default_rng([seed, 4]), db=db, title=TITLE)

    kick_s, clap_s, hat_s, perc_s = load_sample(kick_f, .55), load_sample(clap_f, .40), load_sample(hat_f, .12), load_sample(perc_f, .25)
    Bf = {n: trk.buf() for n in ("kick", "clap", "hat", "perc")}

    # 16-step patterns per section for dramaturgy (different drops, not identical)
    # Drop A: driving techno 4/4 with breakbeat ghost notes
    kp_a = [[0, 8, 12], [0, 6, 11], [0, 8, 13], [0, 4, 10, 14], [0, 8], [0, 5, 11], [0, 3, 9, 13], [0, 8]]
    cp_a = [[4, 12], [4, 11], [3, 10], [4, 12, 15], [4, 12], [4, 12], [4, 8, 12], [4, 12]]
    hp_a = [[2, 6, 10, 14], [2, 5, 10, 14], [2, 6, 9, 14], [2, 6, 10, 12, 14], [2, 6, 10], [2, 5, 10, 13], [2, 6, 10, 14], [2, 6, 10]]
    pp_a = [[3, 7, 11], [3, 7, 11, 15], [3, 7, 11], [3, 7, 11, 14], [3, 6, 11], [3, 7, 11, 15], [3, 7, 11], [3, 6, 10]]

    # Drop B: more syncopated, broken beat
    kp_b = [[0, 11], [0, 7, 13], [0, 8], [0, 5, 11], [0, 9], [0, 7, 12], [0, 8, 14], [0, 4, 10]]
    cp_b = [[4, 12], [4, 12], [3, 11], [4, 12], [4, 12], [4, 12], [4, 8, 12], [4, 12]]
    hp_b = [[2, 6, 10, 14], [2, 5, 10, 14], [2, 6, 9, 14], [2, 6, 10, 12], [2, 6, 10, 14], [2, 5, 10, 14], [2, 6, 10, 14, 15], [2, 6, 10]]
    pp_b = [[3, 7, 11, 14], [3, 7, 11, 15], [3, 6, 10, 14], [3, 7, 11], [3, 6, 10, 14], [3, 7, 11, 14], [3, 6, 10, 13], [3, 7, 11]]

    # Drop C: densest, full breakbeat
    kp_c = [[0, 11], [0, 7], [0, 8, 13], [0, 5, 10], [0, 9], [0, 7, 13], [0, 8, 12], [0, 4, 10, 14]]
    cp_c = [[4, 12], [4, 12], [3, 11], [4, 12], [4, 12], [4, 12], [4, 8, 12, 15], [4, 12]]
    hp_c = [[2, 6, 10, 14], [2, 5, 10, 13], [2, 6, 9, 14], [2, 6, 10, 12, 14], [2, 6, 10, 14], [2, 5, 10, 13], [2, 6, 10, 14, 15], [2, 6, 10]]
    pp_c = [[3, 7, 11, 14, 15], [3, 6, 10, 13, 15], [3, 7, 11, 14], [3, 6, 10, 13], [3, 7, 11, 15], [3, 6, 10, 14], [3, 7, 11, 13, 15], [3, 6, 10, 14]]

    for b in range(80):
        lv = trk.sec(b)[3]
        pi = (b // 4) % 8
        sec_name = trk.sec(b)[2]

        if "drop_c" in sec_name:
            kp, cp, hp, pp = kp_c, cp_c, hp_c, pp_c
        elif "drop_b" in sec_name:
            kp, cp, hp, pp = kp_b, cp_b, hp_b, pp_b
        elif sec_name in ("drop_a",):
            kp, cp, hp, pp = kp_a, cp_a, hp_a, pp_a
        elif sec_name in ("build", "pre_drop"):
            kp, cp, hp, pp = kp_a, cp_a, hp_a, pp_a
        elif sec_name == "bridge":
            kp, cp, hp, pp = kp_b, cp_b, hp_a, pp_b
        elif sec_name == "break":
            kp, cp, hp, pp = kp_a, cp_a, hp_a, []
        elif sec_name == "intro":
            kp, cp, hp, pp = [], [], hp_a, []
        else:  # outro
            kp, cp, hp, pp = kp_a, cp_a, hp_a, []

        if lv.get("kick"):
            for st in kp[pi]:
                trk.place(Bf["kick"], kick_s, mt.time(b, st, "kick"), 1.0 if st == 0 else .6)
        if lv.get("clap"):
            for st in cp[pi]:
                trk.place(Bf["clap"], clap_s, mt.time(b, st, "clap"), .9 if st in (4, 12) else .35)
        if lv.get("hat"):
            for st in hp[pi]:
                trk.place(Bf["hat"], hat_s, mt.time(b, st, "hat"), .5 if st % 4 == 2 else .28)
        if lv.get("perc") and pp:
            for st in pp[pi]:
                trk.place(Bf["perc"], perc_s, mt.time(b, st, "perc"), .6 if st % 4 == 3 else .35)

    # SFZ oneshots with explicit cache_dir (no ampeg_attack — breaks render)
    bw = sfz.oneshot(bf, release=.06, cache_dir=CACHE, policy="warn").render(EV["bass"], T)
    cw = sfz.oneshot(cf, release=.2, cache_dir=CACHE, policy="warn").render(EV["chord"], T)
    pw = sfz.oneshot(pf, release=.1, cache_dir=CACHE, policy="warn").render(EV["pluck"], T)
    pdw = sfz.oneshot(pdf, release=1.2, cache_dir=CACHE, policy="warn").render(EV["pad"], T)

    # Processing
    bw = pb(Pedalboard([HighpassFilter(30), LowpassFilter(900), Distortion(6),
                        LadderFilter(mode=LadderFilter.Mode.LPF24, cutoff_hz=1400, resonance=.3)]), bw)
    bw = np.repeat(bw.mean(1, keepdims=True), 2, 1).astype(np.float32)  # bass mono

    # Mix
    kick_pp = pb(Pedalboard([HighpassFilter(30), LowpassFilter(6000),
                            Compressor(threshold_db=-16, ratio=4, attack_ms=2, release_ms=60)]), Bf["kick"])
    clap_pp = pb(Pedalboard([HighpassFilter(200), LowpassFilter(9000)]), Bf["clap"])
    hat_pp = pb(Pedalboard([HighpassFilter(5500), LowpassFilter(9000)]), Bf["hat"])
    perc_pp = pb(Pedalboard([HighpassFilter(300), LowpassFilter(8000)]), Bf["perc"])

    trk.bus("drums", fx=[glue()], parallel=(smash(), .12))
    trk.space("room", kind="room")
    trk.space("hall", kind="hall", back_db=-5)

    trk.add("kick", kick_pp, 1.0, bus="drums")
    trk.add("clap", clap_pp, level=10 ** (-7 / 20), send={"room": .2}, bus="drums")
    trk.add("hat", hat_pp, level=10 ** (-17 / 20), bus="drums")
    trk.add("perc", perc_pp, level=10 ** (-12 / 20), send={"room": .1}, bus="drums")
    trk.add("bass", bw, level=10 ** (-3 / 20), duck=-7.0, key="kick", release_ms=80)
    trk.add("chord",
            pb(Pedalboard([HighpassFilter(160), LowpassFilter(3500)]), cw),
            level=10 ** (-11 / 20), duck=-4.0, key="kick", send={"hall": .2})
    trk.add("pluck",
            pb(Pedalboard([HighpassFilter(220), LowpassFilter(5500),
                          Delay(delay_seconds=S16 * 3, feedback=.25, mix=.12)]), pw),
            level=10 ** (-9 / 20), duck=-3.0, key="kick", send={"hall": .2, "room": .08})
    trk.add("pad",
            pb(Pedalboard([HighpassFilter(150), LowpassFilter(2800)]), pdw),
            level=10 ** (-15 / 20), duck=-5.0, key="kick", depth=.7, send={"hall": .3})
    trk.mono_low(150)
    return trk