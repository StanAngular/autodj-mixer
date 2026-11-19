"""Concrete Hours (broken melodic techno), 132 BPM, A minor. Style read off Quadratic Helm: light breakbeat (3+3+2 kick, not four-on-the-floor), rolling 16th bass pedal on the tonic with a flat-2 accent, drums from the first bar,
bass enters late, plucked arp over the pedal, a thin breakdown mid-track. Fresh everything else: harmony from chords.Plan, drums/sounds picked by fresh.pick/measurements, own hook. Recorded samples only. No voice."""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import saxlead, numpy as np, soundfile as sf, librosa
from autodj.compose import Track, pb, load_sample, fresh, chords as C, lines as L, microtiming as MT, sfz, soundgate as SG
from autodj.compose.bus import glue
from autodj.compose.core import sat
from pedalboard import Pedalboard, HighpassFilter, LadderFilter, Compressor, PeakFilter, Limiter, Reverb
LP24 = lambda f: LadderFilter(mode=LadderFilter.Mode.LPF24, cutoff_hz=f, resonance=0.0)
SM = "/home/cclaw/samples/"; WA = SM + "wa_techno/WAV MIDI Presets/Synth & Bass Shots/"; TDM = SM + "tidal-drum-machines/machines/"
TITLE = "Concrete Hours (broken melodic techno)"
META = {"title": TITLE, "genre": "broken melodic techno", "key": "Fm", "target": -11.5, "master": "warm", "lead": "hook",
        "story": "broken-beat melodic techno 132 BPM: 3+3+2 kick, rolling 16th bass pedal with a flat-2 accent entering late, plucked arp, thin breakdown"}
D = dict(kick=1, snare=1, hats=1, bass=1, duo=1)
SECS = [(0, 16, "intro", dict(kick=1, snare=1, arp=1, pad=.6)), (16, 32, "groove", dict(D, hats=.6, arp=1, pad=.5)), (32, 56, "home1", dict(D, hook=1, arp=1, pad=.5)),
        (56, 72, "thin", dict(kick=1, arp=1, pad=1.2, hook=1, bass=.5)), (72, 96, "home2", dict(D, hook=1, arp=1, pad=.5)),
        (96, 104, "break", dict(pad=1.5, arp=1, hook=1)), (104, 120, "drop", dict(D, hook=1, arp=1, pad=.5)), (120, 128, "outro", dict(kick=1, snare=1, arp=1, pad=1))]
SOFT = lambda x, ms=1.5: np.concatenate([x[:int(ms * 44.1)] * np.linspace(0, 1, int(ms * 44.1))[:, None], x[int(ms * 44.1):]]).astype(np.float32)
mono = lambda x: np.repeat(x.mean(1, keepdims=True), 2, 1).astype(np.float32)
def inst(f, rel, att=.004):
    ins = sfz.oneshot(f, release=rel, policy="warn")
    for rg in ins.regions: rg["ampeg_attack"] = att
    return ins
def hit_stats(p):
    try:
        x, sr = sf.read(p, frames=int(.5 * 44100), dtype="float32", always_2d=True); y = x.mean(1)
        if len(y) < 2048 or np.abs(y).max() < .05: return None
        n = min(len(y), int(.2 * sr)); S = np.abs(np.fft.rfft(y[:n] * np.hanning(n))) ** 2; f = np.fft.rfftfreq(n, 1 / sr)
        return dict(lf=float(S[f < 150].sum() / (S.sum() + 1e-12)), cen=float((f * S).sum() / (S.sum() + 1e-12)), rms=float(np.sqrt((y[:int(.15 * sr)] ** 2).mean())), dur=len(x) / sr)
    except Exception: return None
def strong(pattern, kind, rng, db):
    rows = []
    for p in sorted(glob.glob(TDM + pattern)):
        h = hit_stats(p)
        if not h: continue
        sc = {"kick": h["rms"] * h["lf"] if h["dur"] >= .12 else 0, "snare": h["rms"] * (1200 < h["cen"] < 5500) * (h["dur"] > .12)}[kind]
        if sc > 0: rows.append((sc, p))
    rows.sort(reverse=True); return fresh.pick([p for _, p in rows[:14]], rng, db=db, title=TITLE)
def build(seed):
    rng = np.random.default_rng(seed); prng = np.random.default_rng([seed, 10]); trk = Track(128, 128, seed=seed, tail_s=4, swing=.03).sections(SECS); trk.step_env = True
    S16, BARS, T = trk.S16, trk.bars, trk.N / trk.sr; SP = {n: (a, b) for a, b, n, _ in SECS}; mt = MT.Ensemble(trk, seed); db = fresh.load()
    plan = C.Plan.build("F", trk.tl, "rise", "minor_plagal", seed=seed); plan.attach(trk)
    V = plan.voicings("close", 50, 62, n=3)
    pbass = plan.bass(np.random.default_rng([seed, 1]), 33, 45, style="root", cell=[0, 3, 6, 9, 10, 14], approach=.2, against=V)
    # the pedal: A1 rolling 16ths, a flat-2 (Bb1) accent on steps 11-12 in every 2nd bar (as in the reference), gaps at 3 and 7 so the kick breathes
    ped = []
    for br in range(BARS):
        for st in range(16):
            if st in (3, 7): continue
            m = 29 + (1 if (br % 2 == 1 and st in (11, 12)) else 0); ped.append((br * 16 + st, 1, m, 100 if st % 4 == 0 else 82))
    ctx = L.context(plan, V, pbass); bsteps = {}
    for s, *_ in pbass: bsteps.setdefault(s // 16, set()).add(s % 16)
    F4, G4, Ab4, Bb4, C5, Db5, Eb5, F5 = 65, 67, 68, 70, 72, 73, 75, 77
    PA = [[(0, 6, C5), (6, 2, Eb5), (8, 8, F5)], [(0, 4, Eb5), (4, 4, C5), (8, 6, Bb4), (14, 2, C5)], [(0, 6, Ab4), (6, 2, Bb4), (8, 4, C5), (12, 4, Eb5)], [(0, 12, C5), (12, 2, Bb4)]]            # A: rises to F, falls back, hangs on C
    PA2 = PA[:2] + [[(0, 4, Eb5), (4, 4, Db5), (8, 8, C5)], [(0, 6, Bb4), (6, 2, Ab4), (8, 8, F4)]]                                                                                   # answer: resolves home to F
    PB = [[(0, 16, Ab4)], [(0, 8, Bb4), (8, 8, C5)], [(0, 12, Ab4), (12, 4, G4)], [(0, 16, F4)]]                                                                                        # slow held theme (thin / break)
    PD = [[(2, 4, F5), (6, 2, Eb5), (8, 6, C5)], [(2, 4, Eb5), (6, 2, C5), (8, 8, Bb4)], [(2, 4, Ab4), (6, 2, Bb4), (8, 6, C5), (14, 2, Eb5)], [(0, 8, C5), (8, 8, F5)]]                      # D: the same register, syncopated, for the drop
    SC = [65, 67, 68, 70, 72, 73, 75]                                                                                                                                                       # F aeolian
    def third_below(m):
        for o in (0, 12):
            for i, q in enumerate(SC):
                if q + o == m: return SC[(i - 2) % 7] + o - (12 if i < 2 else 0) if o == 0 else SC[(i - 2) % 7] + o - (12 if i < 2 else 0)
        return m - 4
    sax_notes = []; sax2 = []
    def lay(start, phrases, duo=False):
        for bi, bar in enumerate(phrases):
            for s_, l_, m_ in bar:
                sax_notes.append((start + bi, s_, l_, m_))
                if duo and l_ >= 4: sax2.append((start + bi, s_, l_, third_below(m_)))
    for a0 in (32, 40): lay(a0, PA); lay(a0 + 4, PA2)
    lay(48, PA); lay(52, PA2)
    for a0 in (56, 64): lay(a0, PB); lay(a0 + 4, PB)
    lay(72, PA, True); lay(76, PA2, True); lay(80, PD); lay(84, PA2, True); lay(88, PA, True); lay(92, PA2, True)
    lay(96, PB); lay(100, PB)
    lay(104, PD, True); lay(108, PA2, True); lay(112, PD, True); lay(116, PA2, True)
    lay(120, PA)
    hook = []
    pad_ = [(s0, n, m - 12 * max(0, -(-(m - 58) // 12)), 70) for s0, n, v in V if n >= 8 for m in v[:3]]
    arp = []
    for s0, n, v in V:                                           # plucked arp over each chord: 8ths/16ths cycling the chord tones, with gaps
        tones = [m + 12 * (i // len(v)) for i, m in enumerate(v * 2)]
        for k in range(n):
            st = s0 + k
            if (st % 16) in (1, 5, 9, 13) or (st % 16 == 14 and (st // 16) % 2): continue
            arp.append((st, 1, tones[(k * 3 + (k // 4)) % len(tones)] + 12, 76))
    lines_ = {"bass": pbass, "pad": pad_}
    ev = lambda xs, k=.9: [(mt.time(s // 16, s % 16, "pluck"), m, MT.accent(s % 16, v), max(1, l) * S16 * k) for s, l, m, v in xs]
    EV = {k: ev(v, .9) for k, v in lines_.items()}; EV["bass"] = ev(ped, .8); EV["arp"] = ev(arp, .6)
    for k, e in EV.items(): trk.log_notes(k, e)
    trk.line_fit = {"bass": L.fit(lines_["bass"], plan, None)}
    kA = strong("*/*-bd/*.wav", "kick", rng, db); sA = strong("*/*-sd/*.wav", "snare", rng, db)
    cp = fresh.pick(sorted(glob.glob(TDM + "*/*-cp/*.wav")), rng, db=db, title=TITLE); okh = lambda p: not any(w in os.path.basename(p).lower() for w in ("reverse", "pedal", "rev"))
    hh = fresh.pick([p for p in sorted(glob.glob(TDM + "*/*-hh/*.wav")) if okh(p)], rng, db=db, title=TITLE); oh = fresh.pick([p for p in sorted(glob.glob(TDM + "*/*-oh/*.wav")) if okh(p)], rng, db=db, title=TITLE)
    pc = fresh.pick(sorted(glob.glob(TDM + "*/*-rim/*.wav")) or sorted(glob.glob(TDM + "*/*-perc/*.wav")), rng, db=db, title=TITLE)
    print("  drums", [os.path.basename(os.path.dirname(os.path.dirname(x))) + "/" + os.path.basename(x) for x in (kA, sA, cp, hh, oh, pc)])
    K = dict(k=sat(load_sample(kA, .5), 2.0), s=sat(load_sample(sA, .35), 1.6), cp=SOFT(load_sample(cp, .3)), hh=SOFT(load_sample(hh, .07)), oh=SOFT(load_sample(oh, .25)), pc=SOFT(load_sample(pc, .2)))
    B = {k: trk.buf() for k in ("kick", "snare", "hats", "perc")}
    CELLS = [(0, 6, 12), (0, 6, 12, 14), (0, 6, 11), (0, 3, 6, 12)]                                   # 3+3+2 and its small variations, by bar position inside a 4-bar phrase
    ends = {b - 1 for a, b, n, _ in SECS if n in ("home1", "home2", "drop", "groove")}
    for br in range(BARS):
        on = trk.sec(br)[3]; pr = np.random.default_rng([seed, br, 7])
        if on.get("kick"):
            for st in CELLS[br % 4] if br not in ends else (0, 3, 6, 12, 14):
                trk.place(B["kick"], K["k"], mt.time(br, st, "kick"), 1.0 if st in (0, 6, 12) else .75)
        if on.get("snare"):
            for st in (4, 12): trk.place(B["snare"], K["s"], mt.time(br, st, "snare"), .9); trk.place(B["snare"], K["cp"], mt.time(br, st, "snare"), .4)
            for st in (7, 15) if br % 2 else (10,):
                if pr.random() < .5: trk.place(B["snare"], K["s"], mt.time(br, st, "snare"), .18)
            if br in ends:
                for st in (13, 14, 15): trk.place(B["snare"], K["s"], mt.time(br, st, "snare"), .35 + .12 * (st - 13))
        if on.get("hats"):
            for st in (2, 10, 14) if br % 4 != 3 else (2, 8, 10, 14):
                trk.place(B["hats"], K["hh"], mt.time(br, st, "hats"), (.55 if st % 8 == 2 else .35) * on["hats"] * (.85 + .3 * pr.random()))
        if False:
            for st in (3, 11) if br % 4 == 0 else (5, 13): trk.place(B["perc"], K["pc"], mt.time(br, st, "perc"), .5 + .2 * pr.random())
    pool = lambda *k: sorted({p for x in k for p in glob.glob(WA + x)})
    bf = SG.pick([p for p in pool("*Bass*.wav") if not p.endswith(("Shot_2.wav", "Shot_10.wav", "Shot_9.wav"))], "bass", 29, 30, prng, db=db, title=TITLE, strict=False); hf = SG.pick(pool("*Pluck*.wav", "*Lead*.wav"), "lead", 57, 69, prng, db=db, title=TITLE)
    af = SG.pick(pool("*Pluck*.wav", "*_Sc_*.wav", "*Lead*.wav"), "lead", 62, 78, prng, db=db, title=TITLE, strict=False); pf = SG.pick(pool("*Pad*.wav", "*_Pd_*.wav"), "pad", 44, 56, prng, db=db, title=TITLE)
    print("  sounds", [os.path.basename(x) for x in (bf, af, pf)])
    trk.bus("drums", fx=[glue()]); trk.space("room", kind="room"); trk.space("hall", kind="hall", back_db=-5); trk.space("echo", kind="echo", steps=3, fb=.45)
    trk.add("kick", pb(Pedalboard([HighpassFilter(30), LP24(6000), Compressor(threshold_db=-16, ratio=4, attack_ms=2, release_ms=60)]), B["kick"]), 1.0, bus="drums")
    trk.add("snare", pb(Pedalboard([HighpassFilter(160), LP24(9000), Compressor(threshold_db=-18, ratio=3, attack_ms=1, release_ms=60)]), B["snare"]), level=10 ** (-4 / 20), send={"room": .2}, bus="drums")
    trk.add("hats", pb(Pedalboard([HighpassFilter(5500), LP24(9500)]), B["hats"]), level=10 ** (-15 / 20), send={"room": .05}, bus="drums")
    trk.add("bass", mono(pb(Pedalboard([HighpassFilter(30), LP24(700), Compressor(threshold_db=-18, ratio=4, attack_ms=3, release_ms=70)]), inst(bf, .05).render(EV["bass"], T))), level=10 ** (-3 / 20), duck=-7.0, key="kick", release_ms=80)
    trk.add("arp", pb(Pedalboard([HighpassFilter(300), LP24(6500)]), inst(af, .12).render(EV["arp"], T)), level=10 ** (-13 / 20), duck=-4.0, key="kick", send={"echo": .3, "hall": .15})
    stl = [(mt.time(b_, s_, "pluck"), m_ - 12, l_ * S16 * .97, .85 if l_ >= 4 else .7) for b_, s_, l_, m_ in sax_notes]; trk.log_notes("hook", [(t_, m_ + 12, 90, d_) for t_, m_, d_, v_ in stl])
    sx = saxlead.render(stl, trk.N, np.random.default_rng(seed)); sx = np.repeat(sx[:, None], 2, 1)
    st2 = [(mt.time(b_, s_, "pluck"), m_ - 12, l_ * S16 * .97, .6) for b_, s_, l_, m_ in sax2]
    sx2 = np.repeat(saxlead.render(st2, trk.N, np.random.default_rng(seed + 1))[:, None], 2, 1)
    trk.add("duo", pb(Pedalboard([HighpassFilter(150), LP24(5500)]), sx2), level=10 ** (-13 / 20), duck=-3.0, key="kick", send={"hall": .5, "room": .1})
    trk.add("hook", pb(Pedalboard([HighpassFilter(150), LP24(7000), Compressor(threshold_db=-20, ratio=2.5, attack_ms=10, release_ms=120)]), sx), level=10 ** (-7 / 20), duck=-3.0, key="kick", send={"hall": .45, "room": .1})
    trk.add("pad", pb(Pedalboard([HighpassFilter(160), LP24(1800)]), inst(pf, 1.5, .5).render(EV["pad"], T)), level=10 ** (-17 / 20), duck=-5.0, depth=.7, send={"hall": .3})
    trk.mono_low(150)
    return trk
