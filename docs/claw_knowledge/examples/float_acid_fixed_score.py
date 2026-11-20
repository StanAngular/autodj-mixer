"""Float Acid (indie house), FIXED version of Hermes' score (same brief: 124 BPM, G minor, WA samples only, breakbeat groove, no guitar), by Claw 2026-11-20.
What changed and why is in HERMES_INSTRUCTION.md. Short: the notes come from the plan (plan.bass / plan.voicings / L.hook), not from `v % 3`; every sound goes through SG.pick (pitch gate) and is played
inside +-7 st of its root; no allow_silent / allow_bad_sounds flags; every layer has a key in SECS; kick is not louder than the bass by design (levels as in the compose kit); bass mono."""
import glob, os
import numpy as np
from autodj.compose import Track, pb, load_sample, fresh, chords as C, lines as L, microtiming as MT, sfz, soundgate as SG
from autodj.compose.bus import glue, smash
from autodj.compose.assets import WA
from pedalboard import Pedalboard, HighpassFilter, LowpassFilter, Distortion, Reverb, Delay, Chorus, Compressor, LadderFilter
BPM = 124; TITLE = "Float Acid (indie house)"
META = {"title": TITLE, "genre": "indie house", "key": "Gm", "target": -12.0, "master": "warm", "lead": "pluck"}
D = dict(kick=1, clap=1, hat=1, bass=1, chord=.7, pluck=1, pad=.6)
SECS = [(0, 8, "intro", dict(hat=.5, pad=1.2)), (8, 16, "build", dict(kick=.7, hat=.7, chord=.6, pad=1)), (16, 32, "drop_a", dict(D)), (32, 40, "bridge", dict(kick=.5, clap=.4, hat=.6, chord=.7, pluck=.6, pad=1.2)),
        (40, 56, "drop_c", dict(D, kick=1.0, pluck=1.1)), (56, 64, "break2", dict(kick=.4, hat=.6, chord=.5, pluck=.5, pad=1.5)), (64, 80, "drop_d", dict(D, pluck=1.1, bass=1.1)), (80, 88, "outro", dict(kick=.4, hat=.5, pad=1))]
def build(seed):
    trk = Track(BPM, 88, seed=seed, swing=.04, tail_s=4).sections(SECS); trk.step_env = True; S16, T = trk.S16, trk.N / trk.sr; db = fresh.load(); mt = MT.Ensemble(trk, seed)
    rng = np.random.default_rng([seed, 88]); prng = np.random.default_rng([seed, 10])
    plan = C.Plan.build("G", trk.tl, "minor_plagal", "lament", seed=seed); plan.attach(trk); SP = {n: (a, b) for a, b, n, _ in SECS}
    V = plan.voicings("close", 50, 62, n=3)
    bass = plan.bass(np.random.default_rng([seed, 1]), 28, 40, style="root", cell=[0, 3, 6, 9, 10, 14], approach=.2, against=V)       # (step, len, midi, velocity): the REAL notes (Hermes used velocity as a pitch class)
    ctx = L.context(plan, V, bass); bsteps = {}
    for s, *_ in bass: bsteps.setdefault(s // 16, set()).add(s % 16)
    h8 = L.hook(plan, np.random.default_rng([seed, 3]), 57, 69, SP["drop_a"][0], ctx, lambda b: bsteps.get(b, ()))
    starts = [b for n in ("drop_a", "bridge", "drop_c", "break2", "drop_d") for b in range(SP[n][0], SP[n][1], 8)]
    hook = L.tile(h8, plan, 57, 69, starts, ctx, origin=SP["drop_a"][0])
    chord = [(s0, n, m, 70) for s0, n, v in V if n >= 8 for m in v[:3]]
    pad = [(s0, n, m - 12 * max(0, -(-(m - 58) // 12)), 64) for s0, n, v in V if n >= 8 for m in v[:3]]
    lines_ = {"bass": bass, "chord": chord, "pluck": hook, "pad": pad}
    ev = lambda xs, k=.9: [(mt.time(s // 16, s % 16, "pluck"), m, MT.accent(s % 16, v), max(1, l) * S16 * k) for s, l, m, v in xs]
    EV = {k: ev(v, 1.0 if k == "bass" else .9) for k, v in lines_.items()}
    for k, e in EV.items(): trk.log_notes(k, e)
    trk.line_fit = {k: L.fit(lines_[k], plan, ctx if k == "pluck" else None) for k in ("pluck", "bass")}
    pool = lambda *k: sorted({p for x in k for p in glob.glob(os.path.join(WA, "Synth & Bass Shots", x))})
    bf = SG.pick(pool("*Bass*.wav"), "bass", 28, 40, prng, db=db, title=TITLE, strict=False); cf = SG.pick(pool("*Chord*.wav", "*Org*.wav", "*Synth*.wav"), "pad", 50, 62, prng, db=db, title=TITLE, strict=False)
    pf = SG.pick(pool("*Pluck*.wav", "*Lead*.wav"), "lead", 57, 69, prng, db=db, title=TITLE, strict=False); pdf = SG.pick(pool("*Pad*.wav", "*_Pd_*.wav"), "pad", 44, 56, prng, db=db, title=TITLE, strict=False)
    print("  sounds", [os.path.basename(x) for x in (bf, cf, pf, pdf)])
    kick_f = fresh.pick(glob.glob(os.path.join(WA, "Kicks/*Kick*")), rng, db=db, title=TITLE); clap_f = fresh.pick(glob.glob(os.path.join(WA, "Claps/*Clap*")), np.random.default_rng([seed, 2]), db=db, title=TITLE)
    hat_f = fresh.pick(glob.glob(os.path.join(WA, "Cymbals/*Hit*")) + glob.glob(os.path.join(WA, "Cymbals/*HiHat*")), np.random.default_rng([seed, 3]), db=db, title=TITLE)
    kick_s, clap_s, hat_s = load_sample(kick_f, .55), load_sample(clap_f, .40), load_sample(hat_f, .12)
    Bf = {n: trk.buf() for n in ("kick", "clap", "hat")}
    kick_p = [[0, 8, 13], [0, 5, 11], [0, 8, 12], [0, 4, 10, 14], [0, 8, 13], [0, 6, 12], [0, 3, 9, 13], [0, 8, 14]]; clap_p = [[5, 13], [4, 12, 15], [4, 11], [3, 7, 12], [5, 13], [4, 12], [4, 8, 12], [6, 14]]
    hat_p = [[2, 6, 10, 14], [2, 5, 10, 14], [2, 6, 9, 14], [2, 6, 10, 12, 14], [2, 6, 10, 14], [2, 5, 10, 13], [2, 6, 10, 14, 15], [2, 6, 10, 14]]
    ends = {b - 1 for a, b, n, _ in SECS if n.startswith("drop")}
    for b in range(88):
        lv = trk.sec(b)[3]; pi = (b // 4) % 8
        if lv.get("kick"):
            for st in (kick_p[pi] if b not in ends else [0, 3, 6, 8, 12, 14]): trk.place(Bf["kick"], kick_s, mt.time(b, st, "kick"), 1.0 if st == 0 else .6)
        if lv.get("clap"):
            for st in clap_p[pi]: trk.place(Bf["clap"], clap_s, mt.time(b, st, "clap"), .9 if st in (4, 5, 12, 13) else .35)
        if lv.get("hat"):
            for st in hat_p[pi]: trk.place(Bf["hat"], hat_s, mt.time(b, st, "hat"), .5 if st % 4 == 2 else .28)
    inst = lambda f, rel, att=.004: (lambda i: ([r.__setitem__("ampeg_attack", att) for r in i.regions], i)[1])(sfz.oneshot(f, release=rel, policy="warn"))
    bw = inst(bf, .06).render(EV["bass"], T); cw = inst(cf, .2).render(EV["chord"], T); pw = inst(pf, .1).render(EV["pluck"], T); pdw = inst(pdf, 1.2, .3).render(EV["pad"], T)
    bw = pb(Pedalboard([HighpassFilter(30), LowpassFilter(900), Distortion(6), LadderFilter(mode=LadderFilter.Mode.LPF24, cutoff_hz=1400, resonance=.3)]), bw); bw = np.repeat(bw.mean(1, keepdims=True), 2, 1).astype(np.float32)   # bass mono
    trk.bus("drums", fx=[glue()], parallel=(smash(), .12)); trk.space("room", kind="room"); trk.space("hall", kind="hall", back_db=-5)
    trk.add("kick", pb(Pedalboard([HighpassFilter(30), LowpassFilter(6000), Compressor(threshold_db=-16, ratio=4, attack_ms=2, release_ms=60)]), Bf["kick"]), 1.0, bus="drums")
    trk.add("clap", pb(Pedalboard([HighpassFilter(200), LowpassFilter(9000)]), Bf["clap"]), level=10 ** (-7 / 20), send={"room": .2}, bus="drums")
    trk.add("hat", pb(Pedalboard([HighpassFilter(5500), LowpassFilter(9000)]), Bf["hat"]), level=10 ** (-17 / 20), bus="drums")
    trk.add("bass", bw, level=10 ** (-3 / 20), duck=-7.0, key="kick", release_ms=80)
    trk.add("chord", pb(Pedalboard([HighpassFilter(160), LowpassFilter(3500)]), cw), level=10 ** (-11 / 20), duck=-4.0, key="kick", send={"hall": .2})
    trk.add("pluck", pb(Pedalboard([HighpassFilter(220), LowpassFilter(5500), Delay(delay_seconds=S16 * 3, feedback=.25, mix=.12)]), pw), level=10 ** (-9 / 20), duck=-3.0, key="kick", send={"hall": .2, "room": .08})
    trk.add("pad", pb(Pedalboard([HighpassFilter(150), LowpassFilter(2800)]), pdw), level=10 ** (-15 / 20), duck=-5.0, depth=.7, send={"hall": .3})
    trk.mono_low(150)
    return trk
