"""Track builder (moved into the engine 2026-10-22 from workspace/music/step0/th5.py, P103: usable by Hermes).
build_concept(name, seed, **override) builds a whole track from a CONCEPTS entry: kit, bass, chords, hook type, arrangement.
Pipeline step 0 (Стас 2026-10-22): FIVE completely different 1-minute tech house tracks, each its own key, tempo,
kit, bass, groove and hook TYPE, with a 1-minute arrangement (base -> hook grows in -> full -> pull-back -> full).
Applies everything learned: new layers grow in, soft low-passed claps (never constant tambourine), no high pings,
held notes only on stable tones, the bass checks what really sounds above it, nothing out of key."""
import numpy as np, librosa
from pedalboard import Pedalboard, HighpassFilter, LowpassFilter, Compressor, Delay, Reverb
from autodj.compose import Track, pb, fx, load_sample
from autodj.compose.core import rms, sweep
from autodj.compose.harmony import Key, chord_of, lead_voices, comp_rhythm, stable_tone
from autodj.compose.bass import house_bass
from autodj.compose.hook import accents
from autodj.compose.ideas import riff, bass_hook, arp_cycle
from autodj.compose.sfz import oneshot
from autodj.compose.timbre import tune_kick
from autodj.compose.palettes import organic
W = "/home/cclaw/samples/wa_techno/WAV MIDI Presets"; W2 = "/home/cclaw/samples/wa2/WAV MIDI Loops/Percussion"; SH = f"{W}/Synth & Bass Shots"
BARS = 32
NOTE = {"C": 0, "C#": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}

CONCEPTS = {
 "deep_pluck": dict(key="F", bpm=124, swing=.08, kick=f"{W}/Kicks/WART_Kick_5.wav", clap=f"{W2}/WAFTH_Clap_06.wav",
     hat=f"{W}/Cymbals/WATE_Hithat_02.wav", shk=f"{W}/Cymbals/WART_HiHat_12.wav", ride=None, bass=f"{SH}/WART_Gm_Bass_Shot_2.wav",
     chords=[("F", "m7")] * 4 + [("C#", "maj7")] * 2 + [("Eb", "")] * 2, hook="chord_stabs", hook_snd=f"{SH}/WART_Gm_Pluck_Shot_3.wav",
     dip=True, title="Глубокие плак-стэбы", desc="фа минор 124: катящийся бас, аккорды-стэбы на плаке с голосоведением Fm7-Dbmaj7-Eb"),
 "bass_groove": dict(key="A", bpm=126, swing=.1, kick=f"{W}/Kicks/WATE_Kick_03.wav", clap=None, rim=f"{W2}/WAFTH_Snare_03.wav",
     hat=f"{W}/Cymbals/WART_HiHat_3.wav", shk=f"{W}/Cymbals/WATS_Closed_HiHat_08.wav", ride=None, bass=f"{SH}/WART_Gm_Bass_Shot_5.wav",
     chords=[("A", "m7")] * 4 + [("D", "m7")] * 2 + [("E", "m7")] * 2, hook="bass_hook", hook_snd=f"{SH}/WART_Gm_Pad_Shot_1.wav",
     dip=False, title="Басовый грув", desc="ля минор 126: хук в басу, сухие ударные без клэпа, тихий пэд на устойчивых нотах Am7-Dm7-Em7"),
 "robot_chant": dict(key="D", bpm=127, swing=.04, kick=f"{W}/Kicks/WART_Kick_8.wav", clap=f"{W}/Claps/WART_Clap_7.wav",
     hat=f"{W}/Cymbals/WATS_Closed_HiHat_06.wav", shk=f"{W}/Cymbals/WART_HiHat_9.wav", ride=f"{W}/Cymbals/WATE_Ride_02.wav", bass=f"{SH}/WART_Gm_Bass_Shot_9.wav",
     chords=[("D", "m")] * 4 + [("C", "")] * 0 + [("D", "m")] * 4, roots=[2, 2, 2, 2, 0, 0, 2, 2], hook="vocoder_chant",
     dip=False, title="Робо-напев", desc="ре минор 127: глубокий бас D/C, ритмичный вокодерный «напев» на аккорде Dm, райд в полной части"),
 "lead_riff": dict(key="G", bpm=125, swing=.06, kick=f"{W}/Kicks/WATE_Kick_07.wav", clap=f"{W}/Claps/WART_Clap_6.wav",
     hat=f"{W}/Cymbals/WATS_Closed_HiHat_02.wav", shk=f"{W}/Cymbals/WART_HiHat_5.wav", ride=f"{W}/Cymbals/WART_Ride_1.wav", bass=f"{SH}/WART_Gm_Bass_Shot_7.wav",
     chords=[("G", "m")] * 4 + [("Eb", "")] * 2 + [("F", "")] * 2, hook="lead_riff", hook_snd=f"{SH}/WART_Gm_Lead_Shot_13.wav",
     dip=True, title="Лид-рифф", desc="соль минор 125: рифф 3+3+2 на лид-шоте W.A. по Gm-Eb-F, драйвовые хэты и райд"),
 "afro_tech": dict(key="C", bpm=123, swing=.12, kick=f"{W}/Kicks/WATE_Kick_05.wav", clap=None,
     hat=f"{W}/Cymbals/WATE_Hithat_05.wav", shk=None, ride=None, bass=f"{SH}/WART_Gm_Bass_Shot_8.wav", congas=True, bass_db=-5,
     chords=[("C", "m7")] * 4 + [("Ab", "maj7")] * 2 + [("Bb", "")] * 2, hook="arp_shimmer", hook_snd=f"{SH}/WATE_Gm_Pluck_07.wav",
     dip=False, title="Афро-тек", desc="до минор 123: живые конги VSCO и бас-«резинка», тихое мерцающее арпеджио 3 против 4 Cm7-Abmaj7-Bb"),
}

import json as _json, os as _os, zlib as _zlib
USED = _os.environ.get("AUTODJ_USED_HOOKS", "/opt/autodj-mixer/shared/compose_used_hooks.json")   # shared with Hermes
def fresh_hook(name, c, h, seed, gen):
    """2026-10-22, Стас: deep techno D came with the riff of track D although nobody asked. Causes: (1) every hook was seeded
    with the plain render seed (5 everywhere) -> the same rhythm cell in every track; (2) the same W.A. pluck; (3) a similar
    acid treatment. Now: the hook seed is salted by the concept name (old concepts keep salt 0 = exactly what Стас heard),
    and a registry of used hooks (type + first-bar rhythm + sound) makes a NEW concept re-draw if it would repeat another
    concept's hook, unless c["reuse_hook"] is set (explicit request)."""
    salt = c.get("seed_salt", _zlib.crc32(name.encode()) % 100000)
    reg = _json.load(open(USED)) if _os.path.exists(USED) else {}
    snd = _os.path.basename(c.get("hook_snd") or "")
    for k in range(12):
        evs = gen(np.random.default_rng(seed + salt + 7919 * k))
        fp = f"{h}|{','.join(str(int(e[0]) % 16) for e in evs if e[0] < 16)}"          # the rhythm itself, whatever the sound
        owner = reg.get(fp)
        if owner in (None, name) or c.get("reuse_hook"): break
    reg[fp] = reg.get(fp, name)
    try: _json.dump(reg, open(USED, "w"), ensure_ascii=False, indent=0)
    except OSError: pass
    return evs

for _k in ("deep_pluck", "bass_groove", "robot_chant", "lead_riff", "afro_tech"): CONCEPTS[_k]["seed_salt"] = 0   # heard: keep

def _sec(c):
    base = dict(kick=1, hats=1, shk=1, perc=1, bass=1)
    return [(0, 8, "base", dict(base)), (8, 16, "grow", dict(base, hook=1, clap=1, conga=1)), (16, 28, "full", dict(base, hook=1, clap=1, ride=1, conga=1, pad=1)),
            (28, 30, "pull", dict(base, hook=1, clap=1)), (30, 32, "full2", dict(base, hook=1, clap=1, ride=1, conga=1, pad=1))]

def build_concept(name, seed, **override):
    """override: hook=..., hook_snd=... (pipeline step 1: other hooks on the same foundation)"""
    c = {**CONCEPTS[name], **override}; NB = c.get("bars", BARS); key = Key(c["key"], "minor")
    trk = Track(c["bpm"], NB, seed=seed, swing=c["swing"]).sections(c.get("sections") or _sec(c)); trk.step_env = True
    T = trk.N / trk.sr; S16 = trk.S16; B = lambda b: b * trk.BAR; r = np.random.default_rng(seed)
    ev = lambda xs: [(trk.t(s // 16, s % 16, 0), m, v, l * S16 * .85) for s, l, m, v in xs]
    CH = [chord_of(NOTE[a], q) for a, q in c["chords"]]; roots = c.get("roots") or [ch[0] for ch in CH]
    cp = lambda b: sorted(set(CH[b % 8]) | {roots[b % 8]}, key=lambda p: (p - roots[b % 8]) % 12)   # what sounds: chord + bass root
    grow = c["hook_grow"](trk) if c.get("hook_grow") else fx.swell(trk, 8, 16, 1.8)
    # ---- drums (each concept its own kit)
    k, _ = tune_kick(pb(Pedalboard([HighpassFilter(30)]), load_sample(c["kick"], .35)), key.tonic)
    if c.get("kick_hpf"): k = pb(Pedalboard([HighpassFilter(c["kick_hpf"])]), k)          # after tuning, or it does nothing
    Bf = {x: trk.buf() for x in ("kick", "hats", "shk", "clap", "ride", "perc")}
    hat = load_sample(c["hat"], .08); shk = load_sample(c["shk"], .06) if c.get("shk") else None
    clap = load_sample(c["clap"], .35) if c.get("clap") else None; rim = load_sample(c["rim"], .2) if c.get("rim") else None
    ride = load_sample(c["ride"], .6) if c.get("ride") else None; perc = load_sample(f"{W}/Percussion/WATE_Percussion_0{int(r.integers(1, 10))}.wav", .2)
    pc = sorted(r.choice([3, 6, 7, 11, 14, 15], 2, replace=False).tolist())
    for br in range(NB):
        for st in (0, 4, 8, 12):
            if (br, st) not in c.get("kick_skip", ()): trk.place(Bf["kick"], k, B(br) + st * S16)
        for st in (2, 6, 10, 14): trk.place(Bf["hats"], hat, trk.t(br, st, 0), .85)
        if shk is not None:
            for st in range(1, 16, 2): trk.place(Bf["shk"], shk, trk.t(br, st, c["swing"]), .4 * accents(st) / 110)
        if clap is not None:
            for st in (4, 12): trk.place(Bf["clap"], clap, trk.t(br, st, 0), .8)
        if rim is not None:
            for st in (4, 12) if br % 2 else (4, 11): trk.place(Bf["clap"], rim, trk.t(br, st, 0), .45)
        if ride is not None:
            for st in (2, 6, 10, 14): trk.place(Bf["ride"], ride, trk.t(br, st, 0), .5)
        for st in pc: trk.place(Bf["perc"], perc, trk.t(br, st, c["swing"]), .6)
    trk.add("kick", Bf["kick"], 1.0)
    if c.get("rumble"):                                                       # deep techno: the kick's own reverb, low-passed, ducked
        ru = pb(Pedalboard([Reverb(room_size=.92, wet_level=1.0, dry_level=0.0), LowpassFilter(170), HighpassFilter(32)]), Bf["kick"])
        trk.add("rumble", ru, level=10 ** (c.get("rumble_db", -9) / 20), duck=-9.0, env=trk.env("kick"))
    trk.add("hats", pb(Pedalboard([HighpassFilter(6000), LowpassFilter(12000)]), Bf["hats"]), level=10 ** (-16 / 20))
    if shk is not None: trk.add("shk", pb(Pedalboard([HighpassFilter(6500), LowpassFilter(11000)]), Bf["shk"]), level=10 ** (-21 / 20))
    if clap is not None or rim is not None:
        trk.add("clap", fx.tame(pb(Pedalboard([HighpassFilter(300), LowpassFilter(6500)]), Bf["clap"]), 14), level=10 ** (-14 / 20), env=trk.env("clap") * grow)
    if ride is not None: trk.add("ride", fx.tame(pb(Pedalboard([HighpassFilter(4000), LowpassFilter(11000)]), Bf["ride"]), 13), level=10 ** (-22 / 20), env=trk.env("ride") * fx.swell(trk, 16, 20, 1.5))
    trk.add("perc", pb(Pedalboard([HighpassFilter(400), LowpassFilter(9000)]), Bf["perc"]), level=10 ** (-18 / 20))
    if c.get("congas"):
        K = organic(np.random.default_rng(seed)); cb = trk.buf()
        cc = sorted(r.choice([2, 3, 5, 7, 9, 11, 13, 14], 4, replace=False).tolist())
        for br in range(NB):
            for st in cc: trk.place(cb, (K["conga"] if st % 4 else K["tumba"]).pick(accents(st) / 127), trk.t(br, st, c["swing"]), .75 * accents(st) / 127, pan=-.25)
            if br % 4 == 3:
                for st in (13, 14, 15): trk.place(cb, K["log_hi"].pick(.6), trk.t(br, st, 0), .5, pan=.3)       # log-drum answer
        trk.add("conga", fx.tame(pb(Pedalboard([HighpassFilter(160), LowpassFilter(8000)]), cb), 13), level=10 ** (-13 / 20), env=trk.one())
    # ---- bass
    BS = oneshot(c["bass"], release=.05)
    if c["hook"] == "bass_hook":
        bl = fresh_hook(name, c, "bass_hook", seed, lambda g: bass_hook(g, key, cp, NB, lo=33, hi=48)["bass"])   # P110: `h` was not set yet here
    else:
        bl = house_bass(np.random.default_rng(seed + 1), key, lambda b: roots[b % 8], NB, lo=29, hi=45, onsets=(4, 6), chord_of_bar=cp)   # shot stays near G1
    trk.log_notes("bass", ev(bl))
    trk.add("bass", fx.tame(pb(Pedalboard([HighpassFilter(c.get("bass_hpf", 30)), LowpassFilter(2200), Compressor(-18, 4, 2, 60)]), BS.render(ev(bl), T)), 11), level=10 ** (c.get("bass_db", -2) / 20), duck=-6.0)
    # ---- the hook (its own TYPE per concept), always growing in from bar 9
    h = c["hook"]; hx = None
    if h == "chord_stabs":
        vo = lead_voices([cp(b) for b in range(8)], 60, 76, 3); cell = comp_rhythm(r, (2, 3), min_off=2); st_ = []
        for br in range(NB):
            for s, ln in cell: st_ += [(br * 16 + s, min(ln, 2), m, 92 if s % 4 else 76) for m in vo[br % 8]]
        trk.log_notes("hook", ev(st_)); hx = pb(Pedalboard([HighpassFilter(250), Delay(S16 * 3, .3, .2), Reverb(room_size=.4, wet_level=.15, dry_level=.9)]), oneshot(c["hook_snd"], release=.15).render(ev(st_), T))
        hx = sweep(hx, [900, 1800, 3600, 7000], .2 + .8 * fx.swell(trk, 8, 16, 1.2)); lvl = -11
    elif h == "bass_hook":
        pv, prev = [], None
        for b in range(0, NB, 2):
            pcs = cp(b); st = [p for p in pcs if stable_tone(p, pcs)]
            d = sorted(min([m for m in range(60, 78) if m % 12 == p], key=lambda m: abs(m - (prev or 67))) for p in st[1:3] or st[:2]); prev = d[0]
            pv += [(B(b) + .02, m, 56, trk.BAR * 2.2) for m in d]
        trk.log_notes("hook", [(t, m, v, d_ - trk.BAR * .2) for t, m, v, d_ in pv])
        hx = pb(Pedalboard([HighpassFilter(200), LowpassFilter(4500), Reverb(room_size=.8, wet_level=.3, dry_level=.8)]), oneshot(c["hook_snd"], release=1.5).render(pv, T)); lvl = -17
    elif h == "vocoder_chant":
        from autodj.compose.fx import vocoder
        LEAD = oneshot(f"{SH}/WART_Gm_Lead_Shot_1.wav", release=.4); PAD = oneshot(f"{SH}/WART_Gm_Pad_Shot_2.wav", release=.4)
        lo_, hi_ = c.get("vc_range", (50, 65)); vc = lead_voices([cp(b) for b in range(8)], lo_, hi_, 3)   # carrier follows the chords
        car = (c.get("vc_lead", 1.0) * LEAD.render([(B(b), m, 70, trk.BAR) for b in range(NB) for m in vc[b % 8]], T)
               + c.get("vc_pad", .7) * PAD.render([(B(b), m, 64, trk.BAR) for b in range(NB) for m in vc[b % 8][:2]], T))
        vox = load_sample(f"{W}/FX/WART_FX_Vox_Crazy_4.wav", 13.0).mean(1); vox = librosa.effects.time_stretch(vox, rate=c.get("vc_rate", .85))
        if c.get("vc_segments"):                                                 # a different «word» every 2 bars
            seg = int(2 * trk.BAR * trk.sr); mod = np.zeros(trk.N, np.float32)
            for k, i0 in enumerate(range(0, trk.N, seg)):
                off = int((k * 1.3 % max(1.0, len(vox) / trk.sr - 2.2)) * trk.sr); piece = vox[off:off + seg]
                mod[i0:i0 + len(piece)] = piece[:trk.N - i0]
        else: mod = np.resize(vox, trk.N)
        gate = np.zeros(trk.N, np.float32); cell = c.get("vc_cell", [0, 3, 6, 10, 12]); cell2 = c.get("vc_cell2", cell[:3] + [11, 14])
        glen = c.get("vc_gate", 1.6)
        for br in range(NB):
            for s in (cell if br % 2 == 0 else cell2):
                i = max(0, int(trk.t(br, s, 0) * trk.sr)); n = min(int(S16 * glen * trk.sr), trk.N - i)
                if n > 0: gate[i:i + n] = np.maximum(gate[i:i + n], np.hanning(n * 2)[n:] ** .5)
        y = vocoder(mod * gate, car, trk.sr, n_fft=2048, hop=256, smooth_bins=14)
        trk.log_notes("hook", [(B(b), m, 70, trk.BAR) for b in range(NB) for m in vc[b % 8]])
        hx = pb(Pedalboard([HighpassFilter(150), LowpassFilter(c.get("vc_lpf", 3500)), Delay(S16 * 3, .3, .2),
                            Reverb(room_size=c.get("vc_room", .6), wet_level=c.get("vc_wet", .2), dry_level=.9)]), y); lvl = c.get("vc_db", -10)
        if c.get("hook_fx"): hx = c["hook_fx"](hx, trk, None)
    elif h == "lead_riff":
        rf = fresh_hook(name, c, h, seed, lambda g: riff(g, key, cp, NB, lo=62, hi=78)["hook"])
        if c.get("hook_edit"): rf = c["hook_edit"](rf, trk)                  # step 3: micro edits on the notes
        trk.log_notes("hook", ev(rf)); hx = pb(Pedalboard([HighpassFilter(250), LowpassFilter(8000), Delay(S16 * 3, .3, .22)]), oneshot(c.get("hook_snd") or f"{SH}/WART_Gm_Lead_Shot_13.wav", release=c.get("hook_release", .12)).render(ev(rf), T)); lvl = -11
        if c.get("hook_fx"): hx = c["hook_fx"](hx, trk, ev(rf))                 # step 2: the same notes, another sound
        lvl += c.get("hook_db", 0)
    elif h == "arp_shimmer":
        vo = lead_voices([cp(b) for b in range(8)], 60, 76, 3)
        ar = fresh_hook(name, c, h, seed, lambda g: arp_cycle(g, key, cp, lambda b: vo[b % 8], NB)["hook"])
        trk.log_notes("hook", ev(ar)); hx = pb(Pedalboard([HighpassFilter(300), LowpassFilter(7000), Delay(S16 * 3, .35, .25), Reverb(room_size=.6, wet_level=.25, dry_level=.85)]), oneshot(c["hook_snd"], release=.1).render(ev(ar), T)); lvl = -16
    elif h == "dialog":
        from autodj.compose.hook import anchor_hook
        bst = lambda b: {s_ % 16 for s_, *_ in bl if s_ // 16 == b}
        hk = fresh_hook(name, c, h, seed, lambda g: anchor_hook(g, key, cp, bst, 65, 82, bars=NB)[0])
        trk.log_notes("hook", ev(hk)); hx = pb(Pedalboard([HighpassFilter(250), LowpassFilter(8000), Delay(S16 * 3, .3, .2), Reverb(room_size=.45, wet_level=.15, dry_level=.9)]), oneshot(c["hook_snd"], release=.15).render(ev(hk), T)); lvl = -11
    elif h == "stab_answer":
        vo = lead_voices([cp(b) for b in range(8)], 60, 76, 3); st_ = []
        for br in range(NB):
            hits = [(10, 2), (13, 1), (15, 1)] if br % 2 else [(14, 2)]          # the chord answers at the end of each phrase
            st_ += [(br * 16 + s, ln, m, 98 if s in (10, 14) else 80) for s, ln in hits for m in vo[br % 8]]
        trk.log_notes("hook", ev(st_)); hx = pb(Pedalboard([HighpassFilter(250), Delay(S16 * 3, .35, .28), Reverb(room_size=.5, wet_level=.2, dry_level=.9)]), oneshot(c["hook_snd"], release=.25).render(ev(st_), T))
        hx = sweep(hx, [900, 1800, 3600, 7000], .2 + .8 * fx.swell(trk, 8, 16, 1.2)); lvl = -11
    elif h == "dub_chord":
        hits = []
        for br in range(NB):
            for st_ in ((6, 14) if br % 2 == 0 else (6, 11, 14)): hits.append((br * 16 + st_, 2, 67, 96 if st_ != 11 else 76))
        trk.log_notes("hook", [])                                             # a fixed G minor chord shot over a G pedal bass
        x = oneshot(c["hook_snd"], keycenter=67, release=.3).render(ev(hits), T)
        hx = pb(Pedalboard([HighpassFilter(200), LowpassFilter(3500), Delay(S16 * 3, .55, .45), Reverb(room_size=.8, wet_level=.3, dry_level=.85)]), x); lvl = -12
    elif h == "long_line":                                                    # slow guide-tone melody, held notes only stable tones
        from autodj.compose.ideas import long_line
        ll = fresh_hook(name, c, h, seed, lambda g: long_line(g, key, cp, NB, lo=c.get("ll_lo", 60), hi=c.get("ll_hi", 76))["hook"])
        trk.log_notes("hook", ev(ll))
        hx = pb(Pedalboard([HighpassFilter(200), LowpassFilter(6000), Reverb(room_size=.75, wet_level=.3, dry_level=.85)]),
                oneshot(c["hook_snd"], release=c.get("hook_release", .6)).render(ev(ll), T)); lvl = -12
        if c.get("hook_fx"): hx = c["hook_fx"](hx, trk, ev(ll))
    if hx is not None and c.get("hook_lpf"): hx = pb(Pedalboard([LowpassFilter(c["hook_lpf"])]), hx)
    if hx is not None and c.get("hook_fx2"): hx = c["hook_fx2"](hx, trk)        # any hook type: a sound treatment
    if hx is not None:
        hx = fx.tame(fx.autopan(trk, hx, 8, .3), 13)                           # spiky plucks must not set the track level
        trk.add("hook", hx, level=10 ** (lvl / 20), env=trk.env("hook") * grow, duck=-3.0)
    if c.get("post"): c["post"](trk, dict(ev=ev, key=key, cp=cp, hook_events=locals().get("rf") or locals().get("st_"), hook_snd=c.get("hook_snd")))
    if c.get("dip"): fx.fader_dip(trk, 16, 1, -30)
    for a_, b_ in c.get("pulls", [(28, 30)]): fx.pullback(trk, a_, b_, low_hz=600)
    trk.mono_low(140)
    return trk
