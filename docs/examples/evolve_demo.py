"""P141 reference score: the same track twice. A = the old way: a recording hit again on every chord (each chord tone a resampled
copy, cut where the recording ends), the slow top line a one-shot per note, the tone fixed for the whole track.
B = the recordings played like instruments (evolve.py): a 4-voice ensemble that holds and moves with the harmony (common tones
stay, the others step to the next chord), a legato top line that glides and breathes, long grains of the recording over the break,
the pad's filter opening into every section, drifting a little, and «иногда» leaning in at phrase ends.

    python -m autodj.compose run docs/examples/evolve_demo.py --name evolve_B
    AUTODJ_EVOLVE=old python -m autodj.compose run docs/examples/evolve_demo.py --name evolve_A
    AUTODJ_EVOLVE_PAD=/path/one_note.wav AUTODJ_EVOLVE_PAD_MIDI=57 ...   a real recording (ONE sustained note: strings, pad, organ, sax)
    AUTODJ_EVOLVE_SFZ=rhodes ...                                          or a registered multisample: every voice asks it for its own note

Without a recording a stand-in is generated (a bowed-string-like tone with its own drift and bow noise) so the score runs
anywhere: the A/B is about what is DONE with the recording, not about the stand-in. AUTODJ_DEMO_BARS=24 renders a short version."""
import os
import numpy as np
from scipy.signal import butter, sosfilt
from autodj.compose import Track, mono2, chords as C, lines as Ln, evolve as V

OLD = os.environ.get("AUTODJ_EVOLVE", "new") == "old"; SCALE = int(os.environ.get("AUTODJ_DEMO_BARS", "56")) / 56
META = {"title": "Evolve Demo " + ("A (retriggered)" if OLD else "B (played)"), "genre": "deep house", "key": "Am", "target": -14.0, "master": "warm", "lead": "top",
        "story": "recordings retriggered per chord, tone fixed" if OLD else "recordings played: held ensemble on the plan, legato top line, grains, filter lanes"}
PL = [("intro", 8), ("home1", 16), ("break", 8), ("build", 4), ("home2", 16), ("outro", 4)]
SR = 44100

def sections():
    out, b = [], 0
    lv = {"intro": dict(kick=1, hats=1, bass=1, pad=1), "home1": dict(kick=1, hats=1, clap=1, bass=1, pad=1, top=1),
          "break": dict(hats=.6, pad=1.1, top=1, air=1, _break=1), "build": dict(hats=1, clap=1, bass=1, pad=1, top=1, air=.6),
          "home2": dict(kick=1, hats=1, clap=1, bass=1, pad=1, top=1, air=.5), "outro": dict(kick=1, hats=1, bass=1, pad=1)}
    for name, n in PL:
        n = max(4, int(round(n * SCALE / 4)) * 4); out.append((b, b + n, name, lv[name])); b += n
    return out

def standin(midi=57, seconds=2.5, kind="strings", seed=0):
    """a 'recorded' note made here: harmonics that drift on their own, a few cents of pitch wander, bow noise, a body resonance"""
    rng = np.random.default_rng([seed, midi]); n = int(seconds * SR); t = np.arange(n) / SR; f0 = 440 * 2 ** ((midi - 69) / 12)
    slow = lambda k, d: np.interp(np.arange(n), np.linspace(0, n, k), rng.normal(0, d, k))
    ph = 2 * np.pi * np.cumsum(f0 * 2 ** (slow(5, 3.0) / 1200)) / SR; y = np.zeros(n)
    for k in range(1, 24):
        if k * f0 > 14000: break
        y += (1 / k ** (1.1 if kind == "strings" else 1.7)) * (1 + .25 * slow(4, .5)) * np.sin(k * ph + rng.uniform(0, 2 * np.pi))
    if kind == "strings":
        y = (.5 * y + .6 * sosfilt(butter(2, [250, 3200], "band", fs=SR, output="sos"), y) + .03 * sosfilt(butter(2, [1500, 6000], "band", fs=SR, output="sos"), rng.normal(0, 1, n)))
        y *= np.minimum(1, t / .09) * (1 - .35 * t / seconds)
    else: y *= np.minimum(1, t / .003) * np.exp(-t / (.35 if kind == "bass" else 1.2))
    y[-int(.03 * SR):] *= np.linspace(1, 0, int(.03 * SR)); y = .9 * y / np.abs(y).max()
    return np.stack([y, np.roll(y, 7) * .97], 1).astype(np.float32)

def pad_source():
    """(recording or instrument, its midi): a real one from the environment, else the stand-in"""
    if os.environ.get("AUTODJ_EVOLVE_SFZ"):
        from autodj.compose.sfz import SFZ
        return SFZ(os.environ["AUTODJ_EVOLVE_SFZ"]), None
    if os.environ.get("AUTODJ_EVOLVE_PAD"):
        return os.environ["AUTODJ_EVOLVE_PAD"], (int(os.environ["AUTODJ_EVOLVE_PAD_MIDI"]) if os.environ.get("AUTODJ_EVOLVE_PAD_MIDI") else None)
    return standin(57, 2.5, "strings"), 57

def kit():
    t = np.arange(int(.3 * SR)) / SR; f = 48 + 100 * np.exp(-t / .028); k = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .12)
    k = sosfilt(butter(2, 3000, "low", fs=SR, output="sos"), np.tanh(1.6 * k)); rng = np.random.default_rng(5)
    def noise(dur, lo, hi, dec, att=.0015):
        tt = np.arange(int(dur * SR)) / SR; z = sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), rng.normal(0, 1, len(tt)))
        return mono2((z * np.exp(-tt / dec) * np.minimum(1, tt / att) / 4).astype(np.float32))
    c = noise(.25, 900, 3800, .06); clap = c.copy()
    for d in (.011, .022): i = int(d * SR); clap[i:] += c[:len(c) - i] * .8
    return dict(kick=mono2(k.astype(np.float32)), hat=noise(.05, 6000, 11000, .011), clap=clap)

def old_hits(trk, x, kc, events):
    """the old way: every note a resampled copy of the recording, cut where the recording ends"""
    from scipy.signal import resample_poly
    from fractions import Fraction
    buf = trk.buf(); cache = {}
    for t, m, v, d in events:
        st = m - kc
        if st not in cache:
            fr = Fraction(2 ** (-st / 12)).limit_denominator(300); cache[st] = resample_poly(x, fr.numerator, fr.denominator, axis=0).astype(np.float32)
        y = cache[st][:int((d + .3) * SR)].copy(); k = min(len(y), int(.3 * SR)); y[-k:] *= np.linspace(1, 0, k)[:, None]
        trk.place(buf, y, t, (v / 127) ** 1.2)
    return buf

def write(seed):
    trk = Track(122, sum(max(4, int(round(n * SCALE / 4)) * 4) for _, n in PL), seed=seed, humanize_s=.001).sections(sections())
    plan = C.Plan.build("A", trk.tl, "minor_plagal", "lament", seed=seed, rhythm=2).attach(trk); rng = np.random.default_rng(seed)
    K = kit(); S16 = trk.S16
    kick, hats, clap = trk.buf(), trk.buf(), trk.buf()
    for b in range(trk.bars):
        for st in range(16):
            if st % 4 == 0: trk.place(kick, K["kick"], trk.t(b, st))
            if st % 4 == 2: trk.place(hats, K["hat"], trk.t(b, st), .9)
            elif st % 2 == 1 and rng.random() < .55: trk.place(hats, K["hat"], trk.t(b, st), .35 + .2 * rng.random())
            if st in (4, 12): trk.place(clap, K["clap"], trk.t(b, st), .8)
    trk.add("kick", kick, 1.0); trk.add("hats", hats); trk.add("clap", clap)
    vo = plan.voicings("drop2", 52, 71, 4)
    bass_ev = [(s * S16, m, v, n * S16 * .9) for s, n, m, v in plan.bass(np.random.default_rng(seed + 1), 33, 47, style="root", against=vo)]
    bv = V.Voice(standin(45, 1.2, "bass"), 45, seed=seed, release_s=.06, swell_db=0, legato_s=0)
    trk.add("bass", bv.render(bass_ev, trk.N / SR), duck=-5.0, key="kick")
    src, kc = pad_source(); _, top = Ln.topline(plan, np.random.default_rng(seed + 2), 64, 76)
    top_ev = [(s * S16, m, 84, n * S16) for s, n, m, _ in top]
    pad_bars = [b for b in range(trk.bars) if trk.sec(b)[3].get("pad", 0) > .05]; top_bars = [b for b in range(trk.bars) if trk.sec(b)[3].get("top", 0) > .05]
    if OLD:
        x, kc = (V.recording(src, 57) if hasattr(src, "render") else V.recording(src, kc))
        pad_ev = [(s * S16, m, 80, n * S16) for s, n, ms in vo for m in ms if int(s * S16 / trk.BAR) in pad_bars]
        trk.log_notes("pad", pad_ev); trk.add("pad", old_hits(trk, x, kc, pad_ev), duck=-4.0, key="kick")
        tv = [e for e in top_ev if int(e[0] / trk.BAR) in top_bars]; trk.log_notes("top", tv); trk.add("top", old_hits(trk, x, kc, tv), role="strings")
        trk.evolve = {"mode": "old"}
        return trk, plan, {"pad": pad_ev, "top": tv}
    bright = V.lane(trk, {"intro": .3, "home*": .62, "break": .42, "build": .8, "outro": .3}, glide_bars=2) + V.drift(trk, .06, 4, seed) \
             + .2 * V.sometimes(trk, every=8, p=.5, length_bars=1, seed=seed)                    # opens into sections, drifts, leans in now and then
    ens = V.Ensemble(src, kc, n=4, seed=seed, spread=.55, bright=None, swell_db=2.5, glide_s=.09)
    pad = ens.render(trk, plan, "drop2", 52, 71, bars=pad_bars, expr=1 + .15 * V.sometimes(trk, every=8, p=.4, length_bars=2, seed=seed + 9))
    pad = V.tone(pad, SR, bright=bright, width=1.0 + .25 * V.lane(trk, {"*": 0, "break": 1, "build": .5}, 2, at="center"))
    trk.log_notes("pad", [(s * S16, m, 80, n * S16) for s, n, ms in vo for m in ms if int(s * S16 / trk.BAR) in pad_bars])
    trk.add("pad", pad, duck=-4.0, key="kick", send={"room": .18})
    tv = V._only_bars(top_ev, set(top_bars), trk.BAR); trk.log_notes("top", tv)
    vox = V.Voice(src, kc, seed=seed + 5, glide_s=.14, vibrato=(5.2, 9.0, .45), swell_db=3.5, bright=.62, bright_track=.4, release_s=.7)
    trk.add("top", vox.render(tv, trk.N / SR), role="strings", send={"room": .22})
    air_bars = [b for b in range(trk.bars) if trk.sec(b)[3].get("air", 0) > .05]
    air = V.grains(trk, src, kc, plan, per_bar=5, lo=67, hi=88, bars=air_bars, seed=seed)
    trk.add("air", V.tone(air, SR, bright=.55), role="texture", send={"room": .4})
    trk.evolve = {"mode": "new", "pad": ens.stats, "top": vox.stats, "air": getattr(V.grains, "last", {})}
    return trk, plan, {"pad": None, "top": tv}

def build(seed):
    return write(seed)[0]
