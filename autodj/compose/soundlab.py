"""P132 (2026-11-12, audit «електронна музика — це пошук нового звуку»): the search for a new sound as a MECHANISM.
Until now «new sound» meant: pick one of 15 named tricks from a list (operators.TECHNIQUES) or pick a sample from the catalog and
ask whether it is bad (soundq / timbre_guard). Nothing ever produced a sound that did not exist before, and nothing measured
whether a sound was new. Here a sound is a patch of the living synth (synth.py); the lab

  1. draws many patches for a ROLE (bass / lead / pluck / pad / stab / texture), partly at random, partly as mutations of what
     Стас liked, optionally with wavetables cut from any recording we own (sources=[...wav]);
  2. renders each on the same short phrase and DESCRIBES it by numbers: tone (centroid, spread, tilt, band shape), motion (how
     many dB per band the timbre changes inside a note and between notes), attack, sustain, harmonicity, roughness, width;
  3. refuses what cannot work: silent, out of tune, outside the role's register, harsh, or STATIC (a sound must move);
     and everything close to a sound Стас rejected;
  4. scores the rest by NOVELTY: distance to everything already in the archive (all sounds ever proposed, used or judged);
  5. keeps the best of each region (bright/dark x moving/steady x sharp/soft attack: quality-diversity search) and returns a few
     that are as different from each other as possible, as a blind audition reel for Стас;
  6. remembers: votes move the next search (toward liked, away from rejected); a sound claimed by a track is not offered again.

    python -m autodj.compose.soundlab search bass --n 48 --keep 6 --out /tmp/lab        # reel + key, candidates into the archive
    python -m autodj.compose.soundlab vote bass-20261112-3fa9c1 1 "тёплый, качает"
    python -m autodj.compose.soundlab list bass
    in a score:  syn = soundlab.Archive().synth("bass-20261112-3fa9c1", bpm=trk.bpm, track="Night Shift 2")   # claims it

The ear stays the judge: the lab only makes sure that what reaches the ear is in tune, alive and unlike what was heard before."""
import copy, datetime, hashlib, json, os
import numpy as np
from .synth import Synth, procedural_table, wavetable_from_audio, SR

ARCHIVE = os.environ.get("AUTODJ_SOUNDLAB", "/opt/autodj-mixer/shared/soundlab.json")
BPM = 124.0

# ---- roles: the test phrase and the limits a sound of that role must respect ------------------------------------------------
# phrase steps: (16th step, length in 16ths, midi or [chord], velocity)
ROLES = {
 "bass":    dict(bars=2, phrase=[(0, 2, 36, 112), (3, 1, 36, 70), (6, 2, 48, 100), (8, 2, 36, 116), (11, 1, 43, 78), (14, 2, 39, 104)],
                 tonal=True, cen=(60, 900), low_share=.35, motion=2.5, attack_max=.05),
 "lead":    dict(bars=2, phrase=[(0, 4, 69, 104), (4, 2, 72, 90), (6, 2, 71, 78), (8, 5, 67, 112), (14, 2, 69, 72)],
                 tonal=True, cen=(350, 4500), motion=2.0),
 "pluck":   dict(bars=2, phrase=[(0, 1, 60, 110), (3, 1, 63, 76), (6, 1, 67, 96), (8, 1, 72, 114), (10, 1, 67, 70), (12, 1, 63, 92), (14, 1, 65, 82)],
                 tonal=True, cen=(300, 6000), motion=2.5, attack_max=.03),
 "pad":     dict(bars=4, phrase=[(0, 31, [57, 60, 64, 67], 84), (32, 31, [55, 59, 62, 67], 78)], repeat=False, tonal=False, cen=(150, 3500), motion=.8),
 "stab":    dict(bars=2, phrase=[(2, 2, [60, 63, 67, 70], 108), (7, 2, [60, 63, 67, 70], 84), (10, 1, [60, 63, 67, 70], 96), (13, 2, [58, 62, 65, 70], 110)],
                 tonal=False, cen=(250, 5000), motion=2.5, attack_max=.05),
 "texture": dict(bars=4, phrase=[(0, 62, 48, 90)], repeat=False, tonal=False, cen=(100, 8000), motion=.8),
}

def phrase_events(role, bpm=BPM):
    """the role's test phrase as synth events (t, midi, vel, dur)"""
    R = ROLES[role]; s16 = 15.0 / bpm; out = []
    for rep in range(R["bars"] if R.get("repeat", True) else 1):
        for st, ln, m, v in R["phrase"]:
            for mm in (m if isinstance(m, (list, tuple)) else [m]):
                out.append(((rep * 16 + st) * s16, mm, v, ln * s16 * .92))
    return out, R["bars"] * 16 * s16 + 1.0

# ---- drawing patches --------------------------------------------------------------------------------------------------
U = lambda rng, lo, hi: float(rng.uniform(lo, hi))
LG = lambda rng, lo, hi: float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
PRIOR = {   # per role: ranges the random draw starts from (mutation may leave them, BOUNDS may not be left)
 "bass":    dict(waves=["saw", "pulse", "fm", "wt"], sub=.7, uni=(1, 3), cutoff=(70, 450), env=(1.5, 5), fvel=(.4, 2.2), a=(.001, .006), d=(.08, .4), s=(0, .7), r=(.03, .12), fd=(.05, .3), drive=(0, 12), glide=.3, spread=(0, .25)),
 "lead":    dict(waves=["saw", "pulse", "fm", "wt", "tri"], sub=.15, uni=(1, 5), cutoff=(400, 3000), env=(.5, 3.5), fvel=(.3, 1.8), a=(.002, .03), d=(.1, .6), s=(.3, .9), r=(.06, .3), fd=(.08, .6), drive=(0, 8), glide=.4, spread=(.1, .7)),
 "pluck":   dict(waves=["saw", "pulse", "fm", "wt", "tri"], sub=.1, uni=(1, 3), cutoff=(250, 1800), env=(2, 6), fvel=(.5, 2.5), a=(.001, .004), d=(.06, .35), s=(0, .15), r=(.05, .4), fd=(.03, .25), drive=(0, 6), glide=0, spread=(0, .6)),
 "pad":     dict(waves=["saw", "pulse", "wt", "tri", "fm"], sub=.2, uni=(3, 7), cutoff=(250, 2200), env=(.3, 2.5), fvel=(0, .8), a=(.08, 1.2), d=(.5, 3), s=(.5, 1), r=(.4, 2.0), fd=(.5, 4), drive=(0, 4), glide=0, spread=(.5, 1)),
 "stab":    dict(waves=["saw", "pulse", "wt", "fm"], sub=0, uni=(2, 5), cutoff=(300, 2500), env=(1.5, 5), fvel=(.3, 2), a=(.001, .008), d=(.08, .35), s=(0, .3), r=(.08, .5), fd=(.04, .3), drive=(0, 8), glide=0, spread=(.3, .9)),
 "texture": dict(waves=["wt", "noise", "fm", "saw"], sub=.2, uni=(1, 5), cutoff=(200, 5000), env=(0, 2), fvel=(0, .5), a=(.3, 3), d=(1, 4), s=(.6, 1), r=(.5, 3), fd=(1, 6), drive=(0, 10), glide=0, spread=(.4, 1)),
}
BOUNDS = {"cutoff": (40, 9000), "res": (0, .85), "env": (0, 7), "vel": (0, 3), "key": (0, 1), "drive": (0, 18), "a": (.0005, 4), "d": (.02, 6), "s": (0, 1), "r": (.02, 4),
          "detune": (0, 45), "spread": (0, 1), "level": (.1, 1.2), "pw": (.08, .92), "ratio": (.5, 9), "index": (0, 9), "pos": (0, 1), "amt": (-4, 4), "glide_ms": (0, 250), "drift": (0, 12)}
LOGK = {"cutoff", "a", "d", "r", "ratio"}
RATES = ["1/8.", "1/4", "1/4.", "1/2", "1b", "2b", "4b", "8b", "3/16"]

def _mod_pool(role, waves):
    P = [("lfo", "cutoff", (.3, 1.6)), ("rand", "cutoff", (.1, .5)), ("time", "cutoff", (.4, 1.8)), ("pos", "cutoff", (.2, 1.0)), ("lfo", "res", (.05, .3)),
         ("rand", "amp", (.5, 2.5)), ("lfo", "detune", (.2, .8))]
    if "pulse" in waves: P += [("lfo", "pw", (.1, .35)), ("env", "pw", (.1, .3))]
    if "fm" in waves: P += [("env", "index", (1, 6)), ("lfo", "index", (.5, 3)), ("vel", "index", (1, 4))]
    if "wt" in waves: P += [("lfo", "pos", (.2, .5)), ("env", "pos", (.2, .7)), ("time", "pos", (.3, .8)), ("rand", "pos", (.1, .4))]
    if role in ("lead", "pad", "texture"): P += [("lfo_note", "pitch", (.03, .14)), ("lfo", "pan", (.0, .0))]
    if role in ("pluck", "stab"): P += [("rand", "pan", (.1, .45)), ("vel", "res", (.05, .3))]
    return [q for q in P if q[2][1] > 0]

def random_patch(rng, role, sources=()):
    """a fresh patch for a role. Wavetables are named inside the patch ("proc:SEED" or "wav:PATH") so the patch alone rebuilds the sound."""
    R = PRIOR[role]; n_osc = int(rng.choice([1, 2, 2, 3])) if role != "bass" else int(rng.choice([1, 1, 2])); osc = []
    for k in range(n_osc):
        w = str(rng.choice(R["waves"])); uni = int(rng.integers(R["uni"][0], R["uni"][1] + 1))
        o = dict(wave=w, level=U(rng, .5, 1.0) if k else 1.0, semi=float(rng.choice([0, 0, 0, 12, -12, 7])) if k else 0.0, unison=uni,
                 detune=U(rng, 4, 24) if uni > 1 else 0.0, spread=U(rng, *R["spread"]) if uni > 1 else 0.0)
        if w == "pulse": o["pw"] = U(rng, .15, .5)
        if w == "fm": o["ratio"] = float(rng.choice([.5, 1, 2, 3, 4, 1.5, 2.01, 3.5, 7])); o["index"] = U(rng, .3, 4)
        if w == "wt": o["table"] = ("wav:" + str(rng.choice(list(sources)))) if len(sources) and rng.random() < .6 else f"proc:{int(rng.integers(1 << 30))}"; o["pos"] = U(rng, 0, 1)
        if w == "noise": o["level"] = U(rng, .15, .5) if k else 1.0
        osc.append(o)
    if rng.random() < R["sub"]: osc.append(dict(wave="sine", semi=-12.0 if role != "bass" else 0.0, level=U(rng, .4, .8)))
    waves = {o["wave"] for o in osc}; pool = _mod_pool(role, waves); mods = []
    for i in rng.choice(len(pool), min(len(pool), int(rng.integers(2, 5))), replace=False):
        s, d, (lo, hi) = pool[int(i)]; m = dict(src=s, dst=d, amt=round(U(rng, lo, hi) * (1 if d in ("pw", "pos", "res", "index", "detune") or rng.random() < .75 else -1), 3))
        if s in ("lfo", "lfo_note"): m["rate"] = (round(U(rng, 4.5, 6.5), 2) if d == "pitch" else str(rng.choice(RATES))); m["phase"] = round(U(rng, 0, 1), 2); m["shape"] = str(rng.choice(["sine", "sine", "tri", "sh"])) if d != "pitch" else "sine"
        mods.append(m)
    fx = {}
    if rng.random() < .35: fx["chorus"] = round(U(rng, .2, .8), 2)
    if rng.random() < .2: fx["phaser"] = round(U(rng, .2, .7), 2)
    if rng.random() < .25 and role != "bass": fx["width"] = round(U(rng, 1.2, 1.8), 2)
    if rng.random() < .2: fx["drive"] = round(U(rng, 2, 8), 1)
    p = dict(osc=osc, filt=dict(mode="lp" if rng.random() < .85 or role == "bass" else "bp", poles=int(rng.choice([2, 4, 4])), cutoff=round(LG(rng, *R["cutoff"]), 1), res=round(U(rng, .05, .6), 2),
                                env=round(U(rng, *R["env"]), 2), vel=round(U(rng, *R["fvel"]), 2), key=round(U(rng, 0, .5), 2), drive=round(U(rng, *R["drive"]), 1) if rng.random() < .5 else 0.0),
             amp=dict(a=round(LG(rng, *R["a"]), 4), d=round(LG(rng, *R["d"]), 3), s=round(U(rng, *R["s"]), 2), r=round(LG(rng, *R["r"]), 3), vel=round(U(rng, .4, .9), 2)),
             fenv=dict(a=round(LG(rng, .001, max(.002, R["a"][1])), 4), d=round(LG(rng, *R["fd"]), 3), s=round(U(rng, 0, .5), 2), r=round(LG(rng, *R["r"]), 3)),
             glide_ms=round(U(rng, 40, 130)) if rng.random() < R["glide"] else 0.0, drift=round(U(rng, 1, 7), 1), mods=mods, fx=fx)
    return p

def _clamp(k, v):
    lo, hi = BOUNDS[k]; return float(min(hi, max(lo, v)))

def mutate(p, rng, amount=.25, role=None, sources=()):
    """a neighbour of a patch: numbers move a little (log-scale for times and frequencies), now and then a wave, a mod or an effect changes"""
    q = copy.deepcopy(p)
    def jig(d, keys):
        for k in keys:
            if k in d and isinstance(d[k], (int, float)) and k in BOUNDS and rng.random() < .5:
                lo, hi = BOUNDS[k]
                d[k] = round(_clamp(k, d[k] * float(np.exp(rng.normal(0, amount))) if k in LOGK and d[k] > 0 else d[k] + float(rng.normal(0, amount)) * (hi - lo) * .35), 4)
    for o in q["osc"]: jig(o, ("level", "detune", "spread", "pw", "ratio", "index", "pos"))
    jig(q["filt"], ("cutoff", "res", "env", "vel", "key", "drive")); jig(q["amp"], ("a", "d", "s", "r")); jig(q["fenv"], ("a", "d", "s", "r")); jig(q, ("glide_ms", "drift"))
    for m in q["mods"]: jig(m, ("amt",))
    if role and rng.random() < .35:                                                   # structural step: borrow a part of a fresh draw
        f = random_patch(rng, role, sources); part = str(rng.choice(["osc", "mods", "fx"]))
        if part == "osc": q["osc"][int(rng.integers(len(q["osc"])))] = f["osc"][0]
        elif part == "mods" and f["mods"]: q["mods"] = (q["mods"] + [f["mods"][0]])[-4:]
        else: q["fx"] = f["fx"]
    return q

def tables_for(p):
    """build the wavetables a patch names: {"proc:SEED": table, "wav:PATH": table}"""
    out = {}
    for o in p["osc"]:
        t = o.get("table")
        if o.get("wave") != "wt" or not t or t in out: continue
        if t.startswith("proc:"): out[t] = procedural_table(np.random.default_rng(int(t[5:])))
        elif t.startswith("wav:"):
            import soundfile as sf
            a, s = sf.read(t[4:], dtype="float32", always_2d=True); out[t] = wavetable_from_audio(a[:int(s * 6)], s)
        else: raise ValueError(f"table {t!r}: expected proc:SEED or wav:PATH")
    return out

def make(p, bpm=BPM, seed=0):
    """Synth for a lab patch (wavetables resolved)"""
    return Synth(p, bpm=bpm, seed=seed, tables=tables_for(p))

# ---- describing a sound -----------------------------------------------------------------------------------------------------
NB = 20; EDGES = np.geomspace(40.0, 16000.0, NB + 1)
SCALE = {"cen": 1.0, "spread": .5, "tilt": 5.0, "flat": 20.0, "evolve": 4.0, "vary": 4.0, "attack": 1.0, "crest": 5.0, "harm": .25, "rough": .4, "low": .3, "air": .25, "width": .3}
SHAPE_SCALE = 6.0

FLOOR = 50.0
def _profile(seg, sr):
    """band profile of a short mono segment in dB below its own strongest band (NB log bands, floor -50 dB); None if too short or silent"""
    if len(seg) < 256 or np.abs(seg).max() < 1e-6: return None
    n = max(2048, 1 << int(np.ceil(np.log2(len(seg))))); P = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n)) ** 2; f = np.fft.rfftfreq(n, 1 / sr)
    b = 10 * np.log10(np.array([P[(f >= EDGES[i]) & (f < EDGES[i + 1])].sum() for i in range(NB)]) + 1e-20); return np.maximum(b - b.max(), -FLOOR)

def _pdist(p, q):
    """timbre distance of two band profiles: mean change per band, dB (level does not count)"""
    return float(np.mean(np.abs(p - q)))

def motion(m, events, sr=SR):
    """how much the TIMBRE moves, in dB per band, independent of level and of the note pattern:
    evolve = change of the band profile between the first and the last third of a note (inside the note; long notes: also second by second);
    vary   = difference between notes of the SAME pitch played at different moments / velocities (between the notes)."""
    wins = {}
    for t, mid, v, d in events: wins.setdefault((round(float(t), 4), round(float(d), 4)), []).append(int(mid))
    ev, groups = [], {}
    for (t, d), mids in sorted(wins.items()):
        a, b = int(t * sr), int((t + d) * sr); seg = m[a:b]
        if len(seg) < int(.06 * sr): continue
        k = len(seg) // 3; p0, p1 = _profile(seg[:k], sr), _profile(seg[-k:], sr)
        if p0 is not None and p1 is not None: ev.append(_pdist(p0, p1))
        if d >= 1.0:                                                           # a long note must also live from second to second
            h = int(.25 * sr); ps = [_profile(seg[i:i + h], sr) for i in range(0, len(seg) - h, h)]; ps = [q for q in ps if q is not None]
            if len(ps) > 4: ev.append(float(np.mean([_pdist(ps[i], ps[i + 4]) for i in range(len(ps) - 4)])))
        pf = _profile(seg[:int(.1 * sr)], sr)                                  # the same first 100 ms of every note
        if pf is not None: groups.setdefault(tuple(sorted(mids)), []).append(pf)
    va = [_pdist(g[i], g[i + 1]) for g in groups.values() for i in range(len(g) - 1)]
    return (float(np.mean(ev)) if ev else 0.0), (float(np.mean(va)) if va else 0.0)

def describe(x, sr=SR, events=None):
    """numbers for one rendered phrase (stereo or mono); None if silent. Keys of SCALE + "shape" (6 cepstrum-like band coefficients),
    "motion" (= evolve + vary, needs the phrase's events) and "buzz". Without events the motion numbers are 0."""
    from scipy.signal import stft, butter, sosfiltfilt
    x = np.asarray(x, np.float32); m = x.mean(1) if x.ndim == 2 else x
    if not np.isfinite(m).all() or np.abs(m).max() < 1e-5: return None
    f, _, Z = stft(m, sr, nperseg=2048, noverlap=1024, boundary=None, padded=False); P = np.abs(Z) ** 2; e = P.sum(0)
    act = e > e.max() * 1e-4
    if act.sum() < 3: return None
    B = np.stack([P[(f >= EDGES[i]) & (f < EDGES[i + 1])].sum(0) for i in range(NB)], 0)[:, act] + 1e-14                  # (NB, frames)
    mag = np.sqrt(P[:, act]); lf = np.log2(np.maximum(f, 20.0))[:, None]; w = mag / (mag.sum(0, keepdims=True) + 1e-12)
    cfr = (lf * w).sum(0); cen = float(np.average(cfr, weights=np.sqrt(e[act]))); spread = float(np.sqrt(np.average(((lf - cfr[None, :]) ** 2 * w).sum(0), weights=np.sqrt(e[act]))))
    prof = 10 * np.log10(B.mean(1)); lc = np.log2(np.sqrt(EDGES[:-1] * EDGES[1:])); top = int(np.argmax(prof)); up = np.maximum(prof[top:], prof.max() - 60)
    tilt = float(np.polyfit(lc[top:], up, 1)[0]) if len(up) >= 3 else -30.0                 # roll-off above the strongest band, dB / octave
    band = P[(f > 200) & (f < 8000)][:, act] + 1e-14; flat = float(10 * np.log10(np.exp(np.log(band).mean()) / band.mean()))
    env = np.sqrt(np.convolve(m ** 2, np.ones(256) / 256, "same")); pk = env.max()
    a0, a1 = (int(min(events)[0] * sr), int((min(events)[0] + min(events)[3]) * sr)) if events else (0, len(env))       # attack of the FIRST note
    w0 = env[a0:max(a0 + 64, a1)]; wp = w0.max() + 1e-12; attack = (int(np.argmax(w0 > .9 * wp)) - int(np.argmax(w0 > .1 * wp))) / sr
    onl = env[env > pk * 1e-2]; crest = float(20 * np.log10(np.percentile(onl, 97) / (np.median(onl) + 1e-12)))
    c = int(np.argmax(env)); seg = m[max(0, c - 1024):c + 3072]; seg = seg * np.hanning(len(seg)); ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
    lo, hi = int(sr / 2000), min(len(ac) - 1, int(sr / 40)); harm = float(ac[lo:hi].max() / (ac[0] + 1e-12)) if hi > lo else 0.0
    r = np.abs(sosfiltfilt(butter(2, 300, "high", fs=sr, output="sos"), m)); r = sosfiltfilt(butter(2, 200, "low", fs=sr, output="sos"), r)      # beating of the partials
    rough = float(np.sqrt(np.mean(sosfiltfilt(butter(2, [25, 150], "band", fs=sr, output="sos"), r) ** 2)) / (np.abs(r).mean() + 1e-12))
    tot = P[:, act].sum() + 1e-14; low = float(P[f < 250][:, act].sum() / tot); air = float(P[f > 5000][:, act].sum() / tot)
    width = float(np.sqrt(np.mean((x[:, 0] - x[:, 1]) ** 2) / (np.mean((x[:, 0] + x[:, 1]) ** 2) + 1e-12))) if x.ndim == 2 else 0.0
    k = np.arange(NB); shape = [float((np.maximum(prof, prof.max() - 60) - np.maximum(prof, prof.max() - 60).mean()) @ np.cos(np.pi * (k + .5) * j / NB) / NB) for j in range(1, 7)]
    evo, var = motion(m, events, sr) if events else (0.0, 0.0)
    return {"cen": cen, "spread": spread, "tilt": tilt, "flat": flat, "evolve": evo, "vary": var, "motion": evo + var, "attack": float(np.log10(max(1e-4, attack))),
            "crest": crest, "harm": harm, "rough": rough, "low": float(np.sqrt(low)), "air": float(np.sqrt(air)), "width": width, "shape": shape,
            "buzz": float(P[(f > 1500) & (f < 5000)][:, act].sum() / (P[(f > 100) & (f < 1500)][:, act].sum() + 1e-14))}

def vector(d):
    """the description as a point in a space where 1.0 is «clearly different» on every axis"""
    return np.array([d[k] / s for k, s in SCALE.items()] + [c / SHAPE_SCALE for c in d["shape"]], np.float32)

def pitch_error_cents(x, midi, sr=SR, t0=.03, dur=.12):
    """how far the first note sounds from `midi`, folded to the nearest octave (a missing fundamental is not a wrong note). None = no pitch."""
    m = x.mean(1) if x.ndim == 2 else x; seg = m[int(t0 * sr):int((t0 + dur) * sr)].astype(np.float64)
    if len(seg) < 1024 or np.abs(seg).max() < 1e-5: return None
    seg = seg * np.hanning(len(seg)); ac = np.correlate(seg, seg, "full")[len(seg) - 1:]; a, b = int(sr / 1500), min(len(ac) - 2, int(sr / 25)); w = ac[a:b]
    pk = np.where((w[1:-1] > w[:-2]) & (w[1:-1] >= w[2:]))[0]                        # true local peaks (a dark sound's maximum sits at lag 0)
    if not len(pk) or w[pk + 1].max() < .25 * ac[0]: return None
    k = a + 1 + int(pk[np.argmax(w[pk + 1] >= .85 * w[pk + 1].max())])                # the first strong one = the period; y0, y1, y2 = ac[k - 1], ac[k], ac[k + 1]; k = k + .5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)      # parabolic peak
    c = 1200 * np.log2((sr / k) / (440.0 * 2 ** ((midi - 69) / 12.0))); return float((c + 600) % 1200 - 600)

def judge(d, role, pitch_cents=None):
    """(ok, quality 0..1, reasons). Hard refusals: silent, out of tune, outside the role's register, static. Soft: harsh, rough."""
    R = ROLES[role]; why = []
    if d is None: return False, 0.0, ["беззвучен"]
    if R["tonal"] and (pitch_cents is None or abs(pitch_cents) > 35): why.append("не строит" if pitch_cents is not None else "нет высоты")
    hz = 2 ** d["cen"]
    if not R["cen"][0] <= hz <= R["cen"][1]: why.append(f"центр спектра вне роли: {hz:.0f} Гц при {R['cen']}")
    if R.get("low_share") and d["low"] ** 2 < R["low_share"]: why.append("нет низа для баса")
    if d["motion"] < R["motion"]: why.append(f"статичен: тембр меняется на {d['motion']:.1f} дБ при норме от {R['motion']}")
    if R.get("attack_max") and 10 ** d["attack"] > R["attack_max"]: why.append("атака слишком мягкая для роли")
    if why: return False, 0.0, why
    q = 1.0
    if d["buzz"] > .5: q *= .5 if d["buzz"] < 1.5 else .25; why.append("резкая середина 1.5-5 кГц")
    if role in ("pad", "lead") and d["rough"] > .35: q *= .6; why.append("шероховат (биения)")
    if d["air"] ** 2 > .35: q *= .6; why.append("слишком много верха")
    return True, q, why

# ---- the archive ------------------------------------------------------------------------------------------------------------
class Archive:
    """every sound ever proposed, judged or used: {id: {role, patch, vec, desc, score, novelty, verdict, note, used_in, date}}"""
    def __init__(self, path=None):
        self.path = path or ARCHIVE; self.db = json.load(open(self.path)) if os.path.exists(self.path) else {"version": 1, "sounds": {}}
    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True); tmp = self.path + ".tmp"
        json.dump(self.db, open(tmp, "w"), ensure_ascii=False, indent=0); os.replace(tmp, self.path)
    def vectors(self, role=None, verdict="any"):
        return [(k, np.array(s["vec"], np.float32)) for k, s in self.db["sounds"].items()
                if (role is None or s["role"] == role) and (verdict == "any" or s.get("verdict") == verdict)]
    def add(self, cand, save=True):
        self.db["sounds"][cand["id"]] = {"role": cand["role"], "patch": cand.get("patch"), "vec": [round(float(v), 4) for v in cand["vec"]],
                                         "desc": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in cand["desc"].items() if k != "shape"},
                                         "score": round(float(cand.get("score", 0)), 3), "novelty": round(float(cand.get("novelty", 0)), 3),
                                         "verdict": cand.get("verdict"), "note": cand.get("note", ""), "used_in": [], "date": datetime.date.today().isoformat()}
        if save: self.save()
    def add_audio(self, name, x, role, verdict=None, note="", sr=SR, events=None):
        """register a sound that is NOT a lab patch (a sample, a sound of an old track, a rejected timbre): the lab then keeps its distance from it"""
        d = describe(x, sr, events)
        if d is None: raise ValueError("silent audio")
        self.add({"id": name, "role": role, "patch": None, "vec": vector(d), "desc": d, "verdict": verdict, "note": note}); return name
    def vote(self, sid, verdict, note=""):
        if verdict not in (-1, 0, 1): raise ValueError("verdict -1 / 0 / 1")
        s = self.db["sounds"][sid]; s["verdict"] = verdict; s["note"] = note or s.get("note", ""); self.save(); return s
    def claim(self, sid, track, reuse=False):
        """a track takes a sound. One sound belongs to one track unless reuse=True (an explicit decision, e.g. Стас asked for it)."""
        s = self.db["sounds"][sid]; others = [t for t in s["used_in"] if t != track]
        if s.get("verdict") == -1: raise ValueError(f"{sid} was rejected by ear: {s.get('note', '')}")
        if others and not reuse: raise ValueError(f"{sid} already belongs to {others}: search a new sound or pass reuse=True")
        if track not in s["used_in"]: s["used_in"].append(track); self.save()
        return s
    def fresh(self, role):
        """ids not used by any track and not rejected, liked ones first, then by score"""
        c = [(k, s) for k, s in self.db["sounds"].items() if s["role"] == role and s.get("patch") and not s["used_in"] and s.get("verdict") != -1]
        return [k for k, s in sorted(c, key=lambda ks: (-(ks[1].get("verdict") or 0), -ks[1]["score"]))]
    def synth(self, sid, bpm=BPM, seed=0, track=None, reuse=False):
        if track: self.claim(sid, track, reuse)
        p = self.db["sounds"][sid].get("patch")
        if not p: raise ValueError(f"{sid} is a registered recording, not a patch")
        return make(p, bpm, seed)

# ---- the search -------------------------------------------------------------------------------------------------------------
BAD_RADIUS = 1.5                 # closer than this to a rejected sound = refused
def _knn(v, others, k=3):
    if not len(others): return 3.0
    d = np.sort(np.linalg.norm(np.asarray(others) - v[None, :], axis=1)); return float(d[:k].mean())

def evaluate(p, role, bpm=BPM, seed=0, guard=None):
    """render the role phrase with patch p -> candidate dict (ok, quality, why, desc, vec, audio) ; never raises on a bad patch"""
    ev, total = phrase_events(role, bpm)
    try: x = make(p, bpm, seed).render(ev, total)
    except Exception as e: return {"ok": False, "why": [f"{type(e).__name__}: {str(e)[:80]}"], "patch": p, "role": role}
    d = describe(x, events=ev); first = min(ev, key=lambda e: (e[0], e[1]))
    ok, q, why = judge(d, role, pitch_error_cents(x, first[1]) if ROLES[role]["tonal"] else None)
    if ok and guard is not None and not guard(x): ok, why = False, why + ["отклонён внешним стражем тембра"]
    c = {"ok": ok, "quality": q, "why": why, "patch": p, "role": role, "desc": d, "audio": x}
    if d is not None: c["vec"] = vector(d)
    c["id"] = f"{role}-{datetime.date.today().strftime('%Y%m%d')}-{hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:6]}"
    return c

def _cell(d, role):
    mn = ROLES[role]["motion"]                                       # regions: dark..bright x moving a little..a lot x sharp..soft attack
    return (int(np.digitize(d["cen"], np.log2([300, 800, 2000]))), int(np.digitize(d["motion"], [2.5 * mn, 5 * mn])), int(np.digitize(d["attack"], [-2.3, -1.3])))

def search(role, n=48, keep=6, seed=0, generations=2, archive=None, sources=(), bpm=BPM, guard=None, log=None):
    """quality-diversity search: returns up to `keep` candidates (dicts with id, patch, desc, vec, novelty, score, audio), best first,
    chosen to be far from the archive AND from each other. Nothing is stored: call Archive.add for the ones that go to the reel."""
    if role not in ROLES: raise ValueError(f"role {role!r} not in {sorted(ROLES)}")
    rng = np.random.default_rng(seed); arc = archive if archive is not None else Archive(); log = log or (lambda *a: None)
    known = [v for _, v in arc.vectors(role)]; bad = [v for _, v in arc.vectors(role, -1)]; liked = [arc.db["sounds"][k]["patch"] for k, _ in arc.vectors(role, 1) if arc.db["sounds"][k].get("patch")]
    cells = {}; seen = set(); stats = {"rendered": 0, "refused": {}}
    def consider(p):
        c = evaluate(p, role, bpm, seed, guard); stats["rendered"] += 1
        if c["ok"] and bad and min(np.linalg.norm(np.asarray(bad) - c["vec"][None, :], axis=1)) < BAD_RADIUS: c["ok"] = False; c["why"] = ["слишком близко к отклонённому на слух"]
        if not c["ok"] or c["id"] in seen or c["id"] in arc.db["sounds"]:
            for w in (c["why"] or ["повтор"])[:1]: stats["refused"][w.split(":")[0]] = stats["refused"].get(w.split(":")[0], 0) + 1
            return
        seen.add(c["id"]); pool.append(c)
    pool = []
    for i in range(n):
        consider(mutate(liked[int(rng.integers(len(liked)))], rng, .3, role, sources) if liked and rng.random() < .4 else random_patch(rng, role, sources))
    for g in range(generations):
        vecs = [c["vec"] for c in pool]
        for i, c in enumerate(pool):
            c["novelty"] = _knn(c["vec"], known + vecs[:i] + vecs[i + 1:]); c["score"] = c["novelty"] * c["quality"]
            k = _cell(c["desc"], role)
            if k not in cells or cells[k]["score"] < c["score"]: cells[k] = c
        log(f"gen {g}: {stats['rendered']} rendered, {len(pool)} alive, {len(cells)} regions")
        if g == generations - 1: break
        elites = sorted(cells.values(), key=lambda c: -c["score"])
        for i in range(n // 2):
            if elites: consider(mutate(elites[i % len(elites)]["patch"], rng, .25, role, sources))
        for i in range(n // 4): consider(random_patch(rng, role, sources))
    elites = sorted(cells.values(), key=lambda c: -c["score"]); out = []
    while elites and len(out) < keep:                                                # far from each other, not only good
        best = max(elites, key=lambda c: c["score"] ** .5 * (min(np.linalg.norm(c["vec"] - o["vec"]) for o in out) if out else 1.0))
        out.append(best); elites.remove(best)
    for c in out: c["stats"] = stats
    return out

def reel(cands, path, gap_s=.7, level_db=-20.0, sr=SR):
    """blind audition: every candidate's phrase at the same loudness, letters instead of names. Writes `path` (wav) and path + ".json" (the key)."""
    import soundfile as sf
    parts, key, t = [], [], 0.0
    for i, c in enumerate(cands):
        x = np.asarray(c["audio"], np.float32); act = np.abs(x).max(1) > 1e-4; r = float(np.sqrt(np.mean(x[act] ** 2))) if act.any() else 1.0
        x = x * (10 ** (level_db / 20) / r); pk = float(np.abs(x).max()); x = x * min(1.0, .89 / pk)
        key.append({"letter": chr(65 + i), "id": c["id"], "start_s": round(t, 2), "end_s": round(t + len(x) / sr, 2), "novelty": round(float(c.get("novelty", 0)), 2),
                    "why_soft": c.get("why", [])}); parts += [x, np.zeros((int(gap_s * sr), 2), np.float32)]; t += len(x) / sr + gap_s
    sf.write(path, np.concatenate(parts), sr, subtype="PCM_16"); json.dump(key, open(path + ".json", "w"), ensure_ascii=False, indent=1)
    return key

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="autodj.compose.soundlab"); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("role", choices=sorted(ROLES)); s.add_argument("--n", type=int, default=48); s.add_argument("--keep", type=int, default=6)
    s.add_argument("--seed", type=int, default=None); s.add_argument("--out", default="."); s.add_argument("--source", nargs="*", default=[]); s.add_argument("--bpm", type=float, default=BPM); s.add_argument("--archive")
    v = sub.add_parser("vote"); v.add_argument("id"); v.add_argument("verdict", type=int, choices=[-1, 0, 1]); v.add_argument("note", nargs="?", default=""); v.add_argument("--archive")
    l = sub.add_parser("list"); l.add_argument("role", nargs="?"); l.add_argument("--archive")
    c = sub.add_parser("claim"); c.add_argument("id"); c.add_argument("track"); c.add_argument("--reuse", action="store_true"); c.add_argument("--archive")
    a = ap.parse_args(argv); arc = Archive(a.archive)
    if a.cmd == "search":
        seed = a.seed if a.seed is not None else int(datetime.datetime.now().timestamp()) % 100000
        out = search(a.role, a.n, a.keep, seed, archive=arc, sources=a.source, bpm=a.bpm, log=lambda *m: print(*m, flush=True))
        if not out: print(json.dumps({"found": 0, "hint": "ничего не прошло отбор: увеличь --n"}, ensure_ascii=False)); return []
        os.makedirs(a.out, exist_ok=True); wav = os.path.join(a.out, f"lab_{a.role}_{seed}.wav"); key = reel(out, wav)
        for cnd in out: arc.add(cnd, save=False)
        arc.save(); print(json.dumps({"reel": wav, "seed": seed, "key": key, "refused": out[0]["stats"]["refused"], "rendered": out[0]["stats"]["rendered"]}, ensure_ascii=False)); return key
    if a.cmd == "vote": print(json.dumps(arc.vote(a.id, a.verdict, a.note), ensure_ascii=False)[:300])
    if a.cmd == "claim": arc.claim(a.id, a.track, a.reuse); print("ok")
    if a.cmd == "list":
        for k, sd in arc.db["sounds"].items():
            if a.role in (None, sd["role"]): print(k, sd["role"], "verdict", sd.get("verdict"), "novelty", sd.get("novelty"), "used_in", sd["used_in"], sd.get("note", ""))

if __name__ == "__main__":
    main()
