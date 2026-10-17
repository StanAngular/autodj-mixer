"""Track from a learned reference: the groove, bass rhythm, bass degrees and role levels come from the reference
profile (learn.py); sounds, key, arrangement, voice and story come from the per-track config. Mechanics only:
every musical decision is either measured from the reference or drawn from the rng, never a stored pattern."""
import os
import numpy as np
from pedalboard import Pedalboard, HighpassFilter, LowpassFilter, Reverb, Delay, Distortion, Bitcrush, PeakFilter
from .core import Track, pb, mono2, sat, sweep, load_sample, fade
from . import fx, voice as V
from .groove import from_ref
from .harmony import Key, voicing
from .instruments import keys, Vital, check_notes
from .assets import ASSETS
from .palettes import organic

NOTE_PC = {"C": 0, "C♯": 1, "D": 2, "D♯": 3, "E": 4, "F": 5, "F♯": 6, "G": 7, "G♯": 8, "A": 9, "A♯": 10, "B": 11}

def degrees_from_ref(prof):
    """bass pitch classes of the reference as intervals above its most used note (its 'tonic'), with weights"""
    pcs = {NOTE_PC[k]: v for k, v in prof["bass"]["pitch_classes"].items()}; tonic = max(pcs, key=pcs.get)
    return [((pc - tonic) % 12, w) for pc, w in pcs.items()]

def bass_note(kind, f, d, sr, rng):
    m = int(d * sr); t = np.arange(m) / sr; a = np.minimum(1, t / .003) * np.clip((d - t) / .01, 0, 1)
    if kind == "sine":                                   # minimal: round sine, a touch of 2nd harmonic
        y = np.sin(2 * np.pi * f * t) + .35 * np.sin(4 * np.pi * f * t) + .15 * np.sin(6 * np.pi * f * t)
    elif kind == "pluck":                                # deep tech: saw+sine with a fast filter-like decay of harmonics
        y = np.sin(2 * np.pi * f * t) + sum((.5 / k) * np.exp(-t / (.05 / k)) * np.sin(2 * np.pi * f * k * t) for k in range(2, 7))
    elif kind == "fm":                                   # hard techno: 2-op FM, index falls fast
        idx = 4 * np.exp(-t / .04) + .6; y = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * 2 * f * t))
    else:                                                # roll: saw-ish, filtered later by an LFO sweep
        y = sum(np.sin(2 * np.pi * f * k * t) / k for k in range(1, 9))
    return (y * a).astype(np.float32)

def build(cfg, seed):
    prof_path = os.path.join(ASSETS, "grooves", "refs", f"{cfg['ref']}.json"); import json; prof = json.load(open(prof_path))
    trk = Track(cfg["bpm"], cfg["bars"], seed=seed).sections(cfg["tl"]); r = trk.rng; g = from_ref(cfg["ref"], r, cfg.get("feel", 1.0))
    key = Key(cfg["tonic"], cfg.get("mode", "minor")); lv = prof["levels_vs_kick_db"]
    trk.roles = {"bass": min(-2.0, lv["bass"]) if cfg["bass"] != "fm" else -1.5, "hats": max(-19, lv["hats"]), "perc": max(-18, lv["perc"] - 1),
                 "rim": -15, "other": max(-14, lv["other"]), "voice": max(-12, lv["vocals"]), "fx": -20, "rumble": -10, **cfg.get("roles", {})}
    S = cfg["sounds"]; B = {k: trk.buf() for k in ("kick", "hats", "perc", "rim", "fx")}
    kick = load_sample(S["kick"], cfg.get("kick_len", .25)); kick = pb(Pedalboard([HighpassFilter(cfg.get("kick_hp", 38))]), sat(kick, cfg.get("kick_sat", 8)))
    kick[-int(.025 * trk.sr):] *= np.linspace(1, 0, int(.025 * trk.sr))[:, None]; kick /= np.abs(kick).max()
    hats = [load_sample(p, cfg.get("hat_len", .08)) for p in S["hats"]]; percs = [load_sample(p, .2) for p in S["perc"]]
    rim = load_sample(S["rim"], .15) if S.get("rim") else None
    hd = cfg.get("hat_density", 1.0); pd = cfg.get("perc_density", .5)
    perc_steps = [st for st in range(16) if st % 4 and g.occupancy("perc", st) > .3]
    fills = set(cfg.get("fills", [])); fg = None
    if fills:
        from .groove import Groove
        fg = Groove(cfg.get("fill_style", "funk"), r)
    for br in range(trk.bars):
        if br in fills:                                     # a real drummer's fill leads the drums back in
            f = fg.fill(); kit = {"snare": [rim] if rim is not None else percs, "rim": percs, "tom": percs}
            for c, hits in f.items():
                if c in kit:
                    for st, v, off in hits:
                        trk.place(B["perc"] if c != "snare" else B["rim"], kit[c][int(r.integers(len(kit[c])))], br * trk.BAR + (st + off) * trk.S16, .5 + .5 * v, r.uniform(-.3, .3))
        roll = cfg.get("kick_roll") and br in cfg["kick_roll"]
        for st in ((range(0, 16, 2) if roll else (0, 4, 8, 12)) if br not in fills else ()): trk.place(B["kick"], kick, br * trk.BAR + st * trk.S16, .75 if roll and st % 4 else 1.0)
        for st in range(16):
            if r.random() < min(1, g.occupancy("hh", st) * hd): trk.place(B["hats"], hats[st % len(hats)], g.t(trk, br, st, "hh"), .3 + .7 * g.vel("hh", st), (.2, -.2)[st % 2])
        if br % 8 == 0: chosen = [s for s in perc_steps if r.random() < pd]                 # perc layout changes every 8 bars
        for j, st in enumerate(chosen):
            trk.place(B["perc"], percs[(j + br // 8) % len(percs)], g.t(trk, br, st, "perc"), .4 + .6 * g.vel("perc", st), (-.45, .45, .1)[j % 3])
        if rim is not None and br not in fills and br % cfg.get("rim_every", 2) == cfg.get("rim_every", 2) - 1: trk.place(B["rim"], rim, g.t(trk, br, cfg.get("rim_step", 12), "perc"), .8, .1)
        if S.get("fx") and br % 16 == 15: trk.place(B["fx"], load_sample(S["fx"][br // 16 % len(S["fx"])], 2.5), br * trk.BAR + 8 * trk.S16, .7)
    trk.add("kick", B["kick"], 1.0)
    if cfg.get("rumble"):
        rum = pb(Pedalboard([Reverb(room_size=.9, damping=.6, wet_level=1., dry_level=0.), LowpassFilter(130), HighpassFilter(35)]), B["kick"][:, :1].repeat(2, 1))
        trk.add("rumble", sat(rum / np.abs(rum).max(), 9.0), role="rumble", duck=-16.0)
    hb = Pedalboard([HighpassFilter(cfg.get("hat_hp", 5000)), LowpassFilter(cfg.get("hat_lp", 12000))])
    trk.add("hats", sat(pb(hb, B["hats"]), 3.0), role="hats")
    trk.add("perc", pb(Pedalboard([HighpassFilter(cfg.get("perc_hp", 500)), Reverb(room_size=.2, damping=.4, wet_level=.12, dry_level=.95)]), sat(B["perc"], 3.0)), role="perc")
    if rim is not None: trk.add("rim", pb(Pedalboard([HighpassFilter(400), Reverb(room_size=.3, wet_level=.18, dry_level=.9)]), B["rim"]), role="rim")
    if S.get("fx"): trk.add("fx", pb(Pedalboard([HighpassFilter(300), LowpassFilter(9000)]), B["fx"]), role="fx")
    # bass: rhythm from the reference's bass occupancy, degrees from the reference's bass pitch classes
    degs = degrees_from_ref(prof); iv = [d for d, _ in degs]; w = np.array([w for _, w in degs]); w = w / w.sum()
    root = cfg.get("bass_root", 33 + (key.tonic - 9) % 12); bass = np.zeros(trk.N, np.float32); bev = []; pat = []
    for br in range(trk.bars):
        if br % 4 == 0:
            pat = [st for st in range(16) if (st % 4 or cfg["bass"] == "roll") and r.random() < min(.95, g.bass_occupancy(st) * cfg.get("bass_density", 1.0))]
            if cfg["bass"] in ("fm", "roll"): pat = [st for st in range(16) if st % 4]          # rolling 3 x 16th after each kick
            line = {st: (0 if (st % 4 == 3 or r.random() < .55) else int(r.choice(iv, p=w))) for st in pat}
        for st in pat:
            n = key.snap(root + line[st]) if (root + line[st]) % 12 not in key.pcs else root + line[st]
            d = trk.S16 * (cfg.get("bass_len", .8) * (1.6 if st % 4 == 3 else 1.0)); t0 = br * trk.BAR + (st + g.offset("perc", st, .5)) * trk.S16
            bev.append((t0, n, 100, d)); y = bass_note(cfg["bass"], 440 * 2 ** ((n - 69) / 12), d, trk.sr, r)
            i0 = int(t0 * trk.sr); vel = .75 + .25 * (st % 4) / 3 if cfg["bass"] in ("fm", "roll") else .9
            bass[i0:i0 + len(y)] += y[:trk.N - i0] * vel
    check_notes(bev, key.pcs, "bass"); trk.log_notes("bass", bev)
    bl = mono2(bass)
    if cfg["bass"] == "roll": bl = sweep(bl, [200, 500, 1200], .15 + .85 * trk.env("open", 8))
    if cfg["bass"] == "fm": bl = pb(Pedalboard([Distortion(cfg.get("bass_dist", 10)), LowpassFilter(1800)]), bl)
    trk.add("bass", pb(Pedalboard([HighpassFilter(32), LowpassFilter(cfg.get("bass_lp", 600))]), sat(bl, cfg.get("bass_drive", 6.0))), role="bass", duck=cfg.get("bass_duck", -4.0))
    # other: stab / dark pad + hypnotic line / metal shots
    oth = cfg.get("other")
    if oth == "stab":
        sev = []; v = voicing(key.chord(0, 5), 52, 64, n=3, rootless=True)
        for br in range(0, trk.bars, 2):
            if trk.sec(br)[3].get("other") and r.random() < .6:
                st = int(r.choice([6, 7, 10, 14])); sev += [(br * trk.BAR + st * trk.S16 + j * .004, m, 70, trk.S16 * 1.2) for j, m in enumerate(v)]
        check_notes(sev, key.pcs, "stab"); trk.log_notes("stab", sev)
        o = fx.analog(pb(Pedalboard([HighpassFilter(250), LowpassFilter(2200), PeakFilter(350, -3, 1)]), keys("Straight Rhodes", sev, trk.N / trk.sr)), wow_ms=.3, flutter_ms=.03)
        o = pb(Pedalboard([Delay(delay_seconds=trk.S16 * 3, feedback=.55, mix=.4), Reverb(room_size=.6, damping=.7, wet_level=.2, dry_level=.9)]), o)
        trk.add("other", o, role="other")
    elif oth == "melodic":
        vi = Vital(); pev = []; seq = []
        chords = [key.chord(d, 4) for d in cfg.get("degrees", (0, 5, 3, 6))]; voiced = [voicing(c, 50, 64, n=3) for c in chords]
        for br in range(0, trk.bars, 4): pev += [(br * trk.BAR, m, 55, 4 * trk.BAR + .05) for m in voiced[br // 4 % len(voiced)]]
        cyc = [key.scale_notes(57, 69)[i] for i in r.choice(len(key.scale_notes(57, 69)), 3, replace=False)]
        for k in range(int(trk.bars * 16 / 3)):                        # 3-note line in a 3/16 cycle: hypnotic, never lines up with the bar
            st = k * 3; br = st // 16
            if trk.sec(br)[3].get("other"): seq.append((br * trk.BAR + (st % 16) * trk.S16, cyc[k % 3], 70 + int(20 * (k % 3 == 0)), trk.S16 * 1.5))
        def under(t):                                                  # pad notes sounding at time t
            br = int(t / trk.BAR); return voiced[(br // 4) % len(voiced)], chords[(br // 4) % len(chords)]
        fixed = []
        for t, m, v, d in seq:                                         # never rub a minor 2nd/9th against the pad
            pv, ch = under(t)
            if any(abs(m - p) in (1, 13, 25) for p in pv):
                m = min([x for x in range(m - 4, m + 5) if x % 12 in ch[:4] and not any(abs(x - p) in (1, 13, 25) for p in pv)] or [m], key=lambda x: abs(x - m))
            fixed.append((t, m, v, d))
        seq = fixed
        check_notes(pev + seq, key.pcs, "pad/line"); trk.log_notes("pad", pev); trk.log_notes("line", seq)
        pad = vi.load(cfg.get("pad_preset", "Pads Soft String")).render(pev, trk.N / trk.sr)
        trk.add("pad", pb(Pedalboard([HighpassFilter(300), LowpassFilter(4000)]), pad), role="other", duck=-6.0)
        ln = vi.load(cfg.get("line_preset", "DnB Bass Analogish")).render([(t, m + 12 * cfg.get("line_oct", 0), v, d) for t, m, v, d in seq], trk.N / trk.sr)
        ln = sweep(pb(Pedalboard([HighpassFilter(250)]), ln), [600, 1500, 4000], .1 + .9 * trk.env("open", 8))
        trk.add("line", pb(Pedalboard([Delay(delay_seconds=trk.S16 * 3, feedback=.4, mix=.3), Reverb(room_size=.7, damping=.7, wet_level=.25, dry_level=.85)]), ln), role="other", duck=-6.0)
    elif oth == "shots":
        sh = load_sample(S["shot"], 1.0); sb = trk.buf()
        semis = (key.tonic - cfg.get("shot_pc", 0)) % 12; semis = semis - 12 if semis > 6 else semis
        from pedalboard import PitchShift
        sh = pb(Pedalboard([PitchShift(semitones=float(semis))]), sh) if semis else sh
        for br in range(trk.bars):
            if trk.sec(br)[3].get("other"):
                for st in (r.choice([2, 3, 6, 10, 11, 14], 2, replace=False) if br % 2 else [6]): trk.place(sb, sh, g.t(trk, br, int(st), "perc"), .6 + .3 * r.random(), r.uniform(-.4, .4))
        trk.add("other", pb(Pedalboard([HighpassFilter(200), LowpassFilter(6000), Delay(delay_seconds=trk.S16 * 3, feedback=.35, mix=.25), Reverb(room_size=.5, wet_level=.2, dry_level=.9)]), sh_bus := sb), role="other", duck=-5.0)
    trk.mono_low(cfg.get("mono_hz", 200))
    for a, b in cfg.get("pulls", []): fx.pullback(trk, a, b)
    for a, b in cfg.get("hp_builds", []): fx.hp_build(trk, a, b)
    for b0 in cfg.get("silences", []): fx.silence_beat(trk, b0)
    for b0 in cfg.get("stutters", []): fx.stutter(trk, b0)
    # voice
    vb = trk.buf(); mode = cfg.get("voice_mode", "chops")
    for bar, f in cfg.get("voice", []):
        x = V.load(os.path.join(cfg["dir"], "vox", f + ".mp3")); t0 = bar * trk.BAR + trk.S16 * 2
        if mode == "chops":                                            # syllables on the 8th grid, used as a rhythm
            y = V.chain(V.quantise(x, trk.BEAT // 2), hp=300, lp=5000, drive=4.0)
        elif mode == "texture":
            y = V.texture(x, r, octave=-12, wet=.45)
        else:                                                          # crush: robotic, dark
            y = pb(Pedalboard([Bitcrush(bit_depth=6), Distortion(12), HighpassFilter(200), LowpassFilter(4000)]), V.chain(x, semitones=-5, drive=6.0))
        trk.place(vb, y, t0); trk.log_voice(t0, f)
        fx.echo_throw(trk, vb, y, t0 + len(y) / trk.sr - .2, trk.S16 * 3, n=3, decay=.5, start_g=.45, tail_s=.25)
    if cfg.get("voice"):
        trk.duck_for_voice(vb, depth_db=-3)
        trk.add("voice", pb(Pedalboard([Delay(delay_seconds=trk.S16 * 3, feedback=.3, mix=.2), Reverb(room_size=.6, damping=.6, wet_level=.2, dry_level=.9)]), vb), role="voice", env=trk.one())
    return trk
