"""P141 (2026-11-18, Стас: «он чаще просто семплами слой повторов одного звучка в течении песни ... это же очень просто ...
постоянное звучание инструмента который бы в течении песни менял тон ... не совсем постоянно а иногда»).

Until now a tonal layer was one recording retriggered: every note the same attack, cut where the recording ends (a pad shot of
3 s cannot hold a 4-bar chord, so the score hits it again), its tone fixed for the whole track except a section level. The tracks
use recordings only (opus_pack CONTEXT: no synthesis), so this module makes a RECORDING behave like a played instrument:

  hold(x, n)              a recording held as long as the music needs: its attack exactly as recorded, then its body continued
                          by WSOLA (waveform-similarity overlap-add: every grain is placed where its wave lines up with the one
                          before, so a pitched sound stays one clean tone, no flanging), the read point wandering slowly through
                          the body so the held tone keeps moving the way the recording moved: not a frozen loop.
  Voice(src)              a continuous instrument from one recording. Notes become a pitch curve: legato notes glide / step
                          without a new attack (the bow does not stop), a phrase after a rest gets the recorded attack again,
                          long notes breathe (slow expression), louder = brighter, optional delayed vibrato.
  Ensemble(src, n=4)      n Voices on the chords of a chords.Plan, each moving to the nearest note of the next chord, common
                          tones held: a pad that changes with the harmony instead of chord shots hit every bar.
  grains(trk, src)        long grains of a recording pitched to the chord tones: an air layer that follows the harmony.
  lane / drift / sometimes   automation: values per section or per bar (no corners), a slow drift (no two bars alike) and
                          «иногда»: a few marked moments (phrase ends, before a new section) where something opens, then returns.
  tone(x, bright=, drive=, width=, gain=)   any layer through a time-varying chain: a low-pass that opens and closes,
                          saturation that comes and goes, width that breathes. Click-free (filter state carried across blocks).

src is a wav path (its pitch is measured), an array with its midi note, or any instrument with .render(events, total_s)
(sfz.SFZ / sfz.oneshot / vsampler.Sampler): it is asked for one long note at the pitch the part needs (multisamples keep
their real timbre per register). Pads, strings, organ, sax, e-piano bodies hold well; drums and short plucks do not (body()
says when a recording has no body to hold: "short")."""
import numpy as np
from scipy.signal import butter, sosfiltfilt, correlate

SR = 44100

# ---- recordings ------------------------------------------------------------------------------------------------------------
def _stereo(x):
    x = np.asarray(x, np.float32)
    if x.ndim == 1: x = np.stack([x, x], 1)
    return np.ascontiguousarray(x[:, :2] if x.shape[1] >= 2 else np.repeat(x, 2, 1))

def _trim(x, floor_db=-60.0, keep_ms=1.0, sr=SR):
    """leading / trailing silence off (1 ms kept before the first sound)"""
    a = np.abs(x).max(1); pk = a.max() if len(a) else 0.0
    if pk <= 0: return x
    on = np.where(a > pk * 10 ** (floor_db / 20))[0]; i0 = max(0, on[0] - int(keep_ms / 1000 * sr)); i1 = on[-1] + 1
    return x[i0:i1]

def recording(src, midi=None, vel=90, seconds=4.0, sr=SR):
    """(stereo float32 array, its midi note) from a wav path (pitch measured when midi is None), an array (midi required) or an
    instrument with .render (asked for ONE note of `seconds` at `midi`)"""
    if hasattr(src, "render"):
        if midi is None: raise ValueError("recording(instrument) needs the midi note to ask it for")
        # 2026-11-18 fix: an instrument can be silent on some notes (Bear Sax above MIDI 72, a gap in a multisample). The demo's top
        # line then rendered as silence and the layer vanished. Ask the nearest notes (down first, within MAX_SHIFT) for a sounding one.
        for d in [0] + [k for j in range(1, 8) for k in (-j, j)]:
            x = _stereo(src.render([(0.0, int(midi) + d, int(vel), float(seconds))], float(seconds) + 1.5))
            if x.size and float(np.abs(x).max()) > 1e-3: return _trim(x), int(midi) + d
        raise ValueError(f"recording(instrument): no sounding note within 7 semitones of MIDI {int(midi)}")
    if isinstance(src, str):
        from .core import load_sample
        x = load_sample(src)
        if midi is None:
            from .sfz import measure_keycenter
            midi = measure_keycenter(src)
        return _trim(_stereo(x)), int(midi)
    if midi is None: raise ValueError("an array needs its midi note: recording(x, midi)")
    return _trim(_stereo(src)), int(midi)

def _env(m, hop=256, win=1024):
    """RMS envelope (values, centre sample of each frame)"""
    n = max(1, (len(m) - win) // hop + 1); idx = np.arange(n) * hop
    c = np.concatenate([[0.0], np.cumsum(np.asarray(m, np.float64) ** 2)])
    return np.sqrt(np.maximum(c[np.minimum(idx + win, len(m))] - c[idx], 0) / win), idx + win // 2

def body(x, sr=SR, floor_db=-24.0, grain_s=.08):
    """where a recording's attack ends and how long it really sounds: {"a": attack end, "b0", "b1": the body to hold (samples),
    "decay_db": level change across the body, "short": True when there is too little body to hold cleanly}"""
    x = _stereo(x); m = x.mean(1); e, c = _env(m); N = int(grain_s * sr)
    if not len(e) or e.max() <= 0: return {"a": 0, "b0": 0, "b1": len(m), "decay_db": 0.0, "short": True}
    p = int(np.argmax(e)); a = int(min(max(c[p] + .03 * sr, .04 * sr), .45 * len(m)))
    up = np.where(e >= e[p] * 10 ** (floor_db / 20))[0]; b1 = int(min(c[up[-1]] if len(up) else len(m), len(m) - .005 * sr))
    short = b1 - a < 3 * N; b1 = max(b1, min(len(m), a + 3 * N))
    i0, i1 = np.searchsorted(c, a), max(np.searchsorted(c, b1), np.searchsorted(c, a) + 1)
    seg = e[i0:i1] if i1 > i0 and i1 <= len(e) else e[p:p + 1]
    dec = 20 * np.log10((seg[-1] + 1e-12) / (seg[0] + 1e-12)) if len(seg) > 1 else 0.0
    return {"a": a, "b0": a, "b1": int(b1), "decay_db": round(float(dec), 1), "short": bool(short)}

def hold(x, n, sr=SR, grain_s=.08, wander=.4, seed=0, flatten=.8, tol_s=.012, segs=None):
    """the recording held for n samples: the attack replayed exactly, then the body continued by WSOLA. wander = how fast the read
    point moves through the body (source samples per output sample on average; it turns at the ends): 0 = one spot (a static
    tone), 1 = the recording's own speed. flatten (0..1) evens out a decaying body so the wandering does not pump."""
    x = _stereo(x); L = len(x); N = max(256, int(grain_s * sr) // 2 * 2); H = N // 2; T = max(16, int(tol_s * sr))
    if L < N + 2 * T + H:                                                       # too short to hold: what there is, faded
        y = np.zeros((n, 2), np.float32); k = min(n, L); y[:k] = x[:k]; return y
    sg = segs or body(x, sr, grain_s=grain_s); a = int(sg["a"]); lo = int(min(max(sg["b0"], 0), L - N - T - 1))
    hi = int(max(lo + 1, min(sg["b1"], L) - N - T - 1)); src = x.copy()
    if flatten:
        e, c = _env(src.mean(1), 512, 2048); sel = (c >= lo) & (c <= hi + N)
        if sel.sum() > 2:
            gc = np.clip((np.median(e[sel]) / np.maximum(e, 1e-9)) ** float(flatten), .25, 4.0)
            g = np.interp(np.arange(L), c, gc).astype(np.float32); w = np.clip((np.arange(L) - lo) / (.1 * sr), 0, 1).astype(np.float32)
            src = src * (1 + (g - 1) * w)[:, None]                                 # 1 through the attack, the flattening after it
    mono = src.mean(1).astype(np.float64); win = (.5 - .5 * np.cos(2 * np.pi * np.arange(N) / N)).astype(np.float32)   # periodic Hann
    K = n // H + 3; out = np.zeros((K * H + N, 2), np.float32); ws = np.zeros(K * H + N, np.float32)
    rng = np.random.default_rng(seed); pos, d, prev = None, 1.0, None
    for k in range(K):
        o = k * H
        if o + N <= a or (prev is None and a > 0): s = o                                  # the attack, exactly as recorded
        else:
            if pos is None: pos = float(min(max((prev + H) if prev is not None else lo, lo), hi))
            else:
                pos += d * float(wander) * (.5 + rng.random()) * H
                if pos > hi: pos, d = 2 * hi - pos, -1.0
                if pos < lo: pos, d = 2 * lo - pos, 1.0
                pos = float(min(max(pos, lo), hi))
            tgt = int(pos + (rng.integers(-H // 8, H // 8 + 1) if wander else 0))
            nat = (prev + H) if prev is not None else tgt
            c0, c1 = max(0, tgt - T), min(L - N, tgt + T)
            if prev is not None and nat + H <= L and c1 > c0:
                tm = mono[nat:nat + H]; sg_ = mono[c0:c1 + H]
                r = correlate(sg_, tm, mode="valid", method="fft"); cs = np.concatenate([[0.0], np.cumsum(sg_ * sg_)])
                en = np.sqrt(np.maximum(cs[H:H + len(r)] - cs[:len(r)], 0)) + 1e-9; s = c0 + int(np.argmax(r / en))
            else: s = tgt
        s = int(min(max(s, 0), L - N)); out[o:o + N] += win[:, None] * src[s:s + N]; ws[o:o + N] += win; prev = s
    return (out[:n] / np.maximum(ws[:n], 1e-3)[:, None]).astype(np.float32)

# ---- automation ------------------------------------------------------------------------------------------------------------
def _cosine_curve(tt_bars, pts):
    """values at control points [(bar, value)] joined by raised-cosine segments (no corners), held flat outside"""
    pts = sorted(pts); xs = np.array([p[0] for p in pts], float); vs = np.array([p[1] for p in pts], float)
    if len(xs) == 1: return np.full(len(tt_bars), vs[0], np.float32)
    j = np.clip(np.searchsorted(xs, tt_bars, side="right") - 1, 0, len(xs) - 2); x0, x1 = xs[j], xs[j + 1]
    u = np.clip((tt_bars - x0) / np.maximum(x1 - x0, 1e-9), 0, 1); w = .5 - .5 * np.cos(np.pi * u)
    return (vs[j] + (vs[j + 1] - vs[j]) * w).astype(np.float32)

def lane(trk, points, glide_bars=1.0, at="before"):
    """(N, 1) automation curve. points: {bar: value} (joined smoothly) or {section name: value} ("peak*" = every section whose name
    starts with "peak", "*" = every section not named; without "*" a section not named keeps the value before it). With sections
    the move takes glide_bars and ends on the
    section line (at="before": the filter is open when the drop lands), starts on it (at="after") or is centred (at="center")."""
    tt = trk.tt / trk.BAR
    if not points: return np.zeros((trk.N, 1), np.float32)
    if all(isinstance(k, (int, float, np.integer, np.floating)) for k in points):
        return _cosine_curve(tt, [(float(k), float(v)) for k, v in points.items()])[:, None]
    def val(name, cur):
        if name in points: return float(points[name])
        for k, v in points.items():
            if isinstance(k, str) and k != "*" and k.endswith("*") and name.startswith(k[:-1]): return float(v)
        return float(points["*"]) if "*" in points else cur
    vals, cur = [], None
    for s in trk.tl:
        cur = val(s[2], cur); vals.append((s[0], s[1], cur))
    first = next((v for _, _, v in vals if v is not None), 0.0); vals = [(a, b, first if v is None else v) for a, b, v in vals]
    g = float(glide_bars); sh = {"before": -g, "after": 0.0, "center": -g / 2}[at]; pts = [(0.0, vals[0][2])]
    for (a0, b0, v0), (a1, b1, v1) in zip(vals, vals[1:]):
        if v1 == v0: continue
        pts += [(a1 + sh, v0), (a1 + sh + max(g, 1e-3), v1)]
    return _cosine_curve(tt, pts)[:, None]

def drift(trk, depth=.15, every_bars=4.0, seed=0):
    """(N, 1) slow random movement in [-depth, depth]: control points every ~every_bars (jittered), joined smoothly"""
    rng = np.random.default_rng([seed, 141]); xs = [0.0]
    while xs[-1] < trk.bars + 4: xs.append(xs[-1] + every_bars * (.6 + .8 * rng.random()))
    return _cosine_curve(trk.tt / trk.BAR, [(x, depth * (2 * rng.random() - 1)) for x in xs])[:, None]

def moments(trk, every=8, p=.5, length_bars=1.0, seed=0, before_sections=True):
    """the bars where «something happens»: the last length_bars of a phrase of `every` bars with probability p, and (before_sections)
    always the bars before a new section. -> sorted list of (start_bar, end_bar)"""
    rng = np.random.default_rng([seed, 1410]); ends = set()
    for s in trk.tl[1:] if before_sections else []: ends.add(float(s[0]))
    for b in range(every, trk.bars + 1, every):
        if rng.random() < p: ends.add(float(b))
    return sorted((max(0.0, e - length_bars), e) for e in ends if 0 < e <= trk.bars)

def sometimes(trk, every=8, p=.5, length_bars=1.0, seed=0, before_sections=True, shape="bump"):
    """(N, 1) 0..1, mostly 0: «иногда». shape "bump" rises and falls back inside the moment; "rise" climbs through it and falls
    back in 40 ms on the next downbeat (a lift into the next phrase). Use it for a filter, a send, drive, a level."""
    tt = trk.tt / trk.BAR; out = np.zeros(trk.N, np.float32); back = .04 / trk.BAR
    for a, b in moments(trk, every, p, length_bars, seed, before_sections):
        u = (tt - a) / max(b - a, 1e-9)
        if shape == "rise":
            v = np.where((u >= 0) & (u < 1), .5 - .5 * np.cos(np.pi * np.clip(u, 0, 1)), 0.0)
            f = np.clip(1 - (tt - b) / back, 0, 1); v = np.where((tt >= b) & (tt < b + back), .5 - .5 * np.cos(np.pi * f), v)
        else: v = np.where((u >= 0) & (u <= 1), np.sin(np.pi * np.clip(u, 0, 1)) ** 2, 0.0)
        out = np.maximum(out, v.astype(np.float32))
    return out[:, None]

# ---- a time-varying chain for any layer ------------------------------------------------------------------------------------
def _curve(v, n):
    if v is None: return None
    a = np.asarray(v, np.float32).reshape(-1) if np.ndim(v) else np.full(n, float(v), np.float32)
    return np.pad(a, (0, max(0, n - len(a))), "edge")[:n] if len(a) else np.zeros(n, np.float32)

def cutoff(bright, lo=400.0, hi=18000.0):
    """0..1 -> low-pass cutoff in Hz (exponential: equal steps sound equal)"""
    return lo * (hi / lo) ** np.clip(bright, 0, 1)

def tone(x, sr=SR, bright=None, drive=None, width=None, gain=None, lo=400.0, hi=18000.0, res=.12, poles=2, drive_db=12.0):
    """x (n, 2) through: low-pass whose cutoff follows bright (0..1, exponential lo..hi), parallel saturation mixed in by drive
    (0..1), side gain width (1 = as is), linear gain. Each argument: None, a number or a curve ((n,) or (n, 1), e.g. a lane)."""
    x = _stereo(x); n = len(x); y = x
    b = _curve(bright, n)
    if b is not None:
        from .synth import biquad_stream, CTL
        y = biquad_stream(y, cutoff(b[::CTL], lo, hi), res, sr, "lp", poles, CTL)
    d = _curve(drive, n)
    if d is not None and float(d.max()) > 0:
        from .core import sat
        y = y + np.clip(d, 0, 1)[:, None] * (sat(y, drive_db) - y)
    w = _curve(width, n)
    if w is not None:
        mid, side = (y[:, 0] + y[:, 1]) / 2, (y[:, 0] - y[:, 1]) / 2 * w; y = np.stack([mid + side, mid - side], 1)
    g = _curve(gain, n)
    if g is not None: y = y * g[:, None]
    return np.asarray(y, np.float32)

# ---- a continuous voice from a recording -----------------------------------------------------------------------------------
def _smooth_noise(L, sr, rng, every_s=1.6, depth=1.0):
    """L samples of a smooth random curve in [-depth, depth], control points every ~every_s seconds (starts at 0)"""
    k = max(2, int(L / sr / every_s) + 2); xs = np.linspace(0, max(L, 2), k)
    vs = depth * (2 * rng.random(k) - 1); vs[0] = 0.0
    return _cosine_curve(np.arange(L, dtype=np.float64), list(zip(xs, vs)))

class Voice:
    """one continuous instrument made of one recording (see the module doc). render(events, total_s, expr=None) -> (n, 2)
    events (t, midi, vel, dur) of ONE line (a monophonic part; overlapping notes are taken as legato).
    glide_s: how long a legato change takes (0.03 = a finger change, 0.25 = a slide); legato_s: a gap up to this is still legato;
    release_s: the tail after a phrase; swell_db: how much long notes breathe; bright: base brightness 0..1 (None = no filter),
    bright_track: how much louder = brighter; vibrato: (rate_hz, cents, delay_s) on long notes (strings, sax), None = off;
    max_shift / fold: a line whose middle is further than max_shift from the recording's pitch is moved by octaves as a WHOLE
    (fold="line", default: its intervals stay, no octave jumps inside a legato line), fold="note" moves single notes, None never."""
    def __init__(self, src, keycenter=None, sr=SR, tune=True, grain_s=.08, wander=.4, seed=0, release_s=.45, glide_s=.06, legato_s=.04,
                 vibrato=None, swell_db=2.5, bright=None, bright_track=.35, max_shift=7, fold="line", vel_db=10.0, cents=0.0):
        self.src, self.kc, self.sr, self.tune = src, keycenter, sr, tune
        self.grain_s, self.wander, self.seed, self.release_s, self.glide_s, self.legato_s = grain_s, wander, seed, release_s, glide_s, legato_s
        self.vibrato, self.swell_db, self.bright, self.bright_track, self.max_shift, self.fold, self.vel_db = vibrato, swell_db, bright, bright_track, max_shift, fold, vel_db
        self.cents = float(cents); self.x = None; self.stats = {}
    def _source(self, events):
        if self.x is not None: return
        med = int(round(float(np.median([e[1] for e in events])))) if events else 60
        if hasattr(self.src, "render"): self.x, self.kc = recording(self.src, med if self.kc is None else self.kc, sr=self.sr); self.det = 0.0
        else:
            self.x, self.kc = recording(self.src, self.kc, sr=self.sr); self.det = 0.0
            if self.tune:
                try:
                    from .tuning import cents_off
                    self.det = float(cents_off(self.x, self.kc, self.sr, start=min(.15, len(self.x) / self.sr / 4), dur=1.0))
                except Exception: self.det = 0.0
        self.segs = body(self.x, self.sr, grain_s=self.grain_s)
    def _phrases(self, ev):
        out = []
        for e in ev:
            if out and e[0] <= max(t + d for t, _, _, d in out[-1]) + self.legato_s: out[-1].append(e)
            else: out.append([e])
        return out
    def render(self, events, total_s, expr=None):
        sr = self.sr; ev = sorted((float(t), float(m), float(v), float(d)) for t, m, v, d in events if d > 0)
        n = int(round(total_s * sr)); out = np.zeros((n + int(self.release_s * sr * 2) + sr, 2), np.float32)
        if not ev: self.stats = {"phrases": 0, "notes": 0}; return out[:n]
        self._source(ev); kc = self.kc; folded = 0; fixed = []
        mid = float(np.median([m for _, m, _, _ in ev])); okt = 12 * round((mid - kc) / 12) if self.fold == "line" and abs(mid - kc) > self.max_shift else 0
        for t, m, v, d in ev:
            m2 = m - okt
            if self.fold == "note" and abs(m2 - kc) > self.max_shift: m2 = m2 - 12 * round((m2 - kc) / 12)
            folded += m2 != m; fixed.append((t, m2, v, d))
        rng = np.random.default_rng([self.seed, 1411]); E = _curve(expr, n) if expr is not None else None; legato = 0
        phrases = self._phrases(fixed)
        for pi, ph in enumerate(phrases):
            t0 = ph[0][0]; tend = max(t + d for t, _, _, d in ph); L = int((tend - t0 + self.release_s) * sr) + 1; tt = np.arange(L) / sr
            m = np.full(L, ph[0][1]); g_db = np.full(L, -self.vel_db * (1 - ph[0][2] / 127))
            for (ta, ma, va, _), (tb, mb, vb, _) in zip(ph, ph[1:]):
                c = tb - t0; gl = max(self.glide_s, 1e-3); w = np.clip((tt - (c - gl / 2)) / gl, 0, 1); w = w * w * (3 - 2 * w)
                m = m + (mb - ma) * w; wv = np.clip((tt - (c - .01)) / .02, 0, 1)
                g_db = g_db + (-self.vel_db * (1 - vb / 127) + self.vel_db * (1 - va / 127)) * wv; legato += 1
            if self.vibrato:
                rate, cents, delay = self.vibrato
                for t, _, _, d in ph:
                    a0 = t - t0 + delay
                    if d > delay + .2:
                        r = np.clip((tt - a0) / .35, 0, 1) * (tt < t - t0 + d); m = m + cents / 100 * r * np.sin(2 * np.pi * rate * (tt - a0))
            if self.swell_db: g_db = g_db + _smooth_noise(L, sr, rng, 1.6, self.swell_db / 2)        # long notes breathe
            rel = tend - t0; g = 10 ** (g_db / 20) * np.where(tt > rel, np.exp(-5 * (tt - rel) / max(self.release_s, 1e-3)), 1.0)
            g[-min(L, int(.005 * sr)):] *= np.linspace(1, 0, min(L, int(.005 * sr)))
            ratio = 2 ** ((m - kc - self.det / 100 + self.cents / 100) / 12); phi = np.concatenate([[0.0], np.cumsum(ratio[:-1])])
            sx = hold(self.x, int(phi[-1]) + 8, sr, self.grain_s, self.wander, seed=self.seed * 1000 + pi, segs=self.segs)
            rmax = float(ratio.max())
            if rmax > 1.02: sx = sosfiltfilt(butter(6, min(.45 * sr / rmax, .45 * sr), "low", fs=sr, output="sos"), sx, axis=0).astype(np.float32)
            ix = np.arange(len(sx)); y = np.stack([np.interp(phi, ix, sx[:, c]) for c in range(2)], 1).astype(np.float32)
            if self.bright is not None:
                b = np.clip(self.bright + self.bright_track * g_db / 12.0, 0, 1)
                y = tone(y, sr, bright=b)
            y *= g[:, None].astype(np.float32)
            i0 = int(round(t0 * sr))
            if E is not None: y *= _curve(E[i0:i0 + L] if i0 < n else [E[-1]], L)[:, None]
            k = min(L, len(out) - i0)
            if k > 0 and i0 >= 0: out[i0:i0 + k] += y[:k]
        self.stats = {"phrases": len(phrases), "notes": len(ev), "legato": legato, "attacks": len(phrases), "folded": int(folded), "octave_shift": -int(okt),
                      "recording_midi": int(kc), "detune_c": round(self.det, 1), "short_body": bool(self.segs["short"]),
                      "max_shift": int(max(abs(m - kc) for _, m, _, _ in fixed))}
        return out[:n]

def lines_of(voicings, n, S16):
    """voice-led voicings [(start_step, length, [midi])] -> n monophonic lines of events, common tones merged into held notes"""
    lines = [[] for _ in range(n)]
    for s0, ln, notes in voicings:
        ns = sorted(int(x) for x in notes)
        for j in range(n):
            mj = ns[j] if len(ns) >= n else ns[int(round(j * (len(ns) - 1) / max(1, n - 1)))]
            L = lines[j]
            if L and L[-1][1] == mj and abs(L[-1][0] + L[-1][3] - s0 * S16) < 1e-6: L[-1][3] += ln * S16      # the same note goes on
            else: L.append([s0 * S16, mj, 80, ln * S16])
    return [[tuple(e) for e in L] for L in lines]

def _only_bars(ev, bars, BAR):
    """cut events to the bars that play (a note across a silent bar is split: the voice re-enters with an attack)"""
    out = []
    for t, m, v, d in ev:
        b0, b1 = int(np.floor(t / BAR + 1e-9)), int(np.ceil((t + d) / BAR - 1e-9)); cur = None
        for b in range(b0, max(b1, b0 + 1)):
            if b in bars:
                a, e = max(t, b * BAR), min(t + d, (b + 1) * BAR)
                if cur and abs(cur[0] + cur[3] - a) < 1e-6: cur[3] = e - cur[0]
                else:
                    if cur: out.append(tuple(cur))
                    cur = [a, m, v, e - a]
            elif cur: out.append(tuple(cur)); cur = None
        if cur: out.append(tuple(cur))
    return out

class Ensemble:
    """n continuous voices on the chords of a plan: Ensemble(src).render(trk, plan) -> (N, 2). src: one recording, an instrument
    (each voice asks it for its own note: the real timbre of every register), or a list of recordings [(wav or array, midi), ...]
    (each voice takes the one nearest its register). Each voice takes one register of the voice-led voicings (plan.voicings),
    holds common tones, moves by step or glide to the next chord tone, breathes on its own (its own read path through the
    recording), sits at its own place in the stereo field, a few cents from the others (detune_c: players, not a chorus).
    lo / hi default to the recording's register (5 below .. 14 above its pitch), or 52..76 for an instrument."""
    def __init__(self, src, keycenter=None, n=4, spread=.6, detune_c=3.0, seed=0, **voice_kw):
        self.src, self.kc, self.n, self.spread, self.detune_c, self.seed, self.kw = src, keycenter, n, spread, detune_c, seed, voice_kw
        self.stats = {}
    def render(self, trk, plan=None, style="drop2", lo=None, hi=None, bars=None, layer=None, vel=80, expr=None):
        plan = plan or getattr(trk, "plan", None)
        if plan is None: raise ValueError("Ensemble.render needs a chords.Plan (or a track with plan.attach(trk))")
        if layer is not None and bars is None: bars = [b for b in range(trk.bars) if trk.sec(b)[3].get(layer, 0) > .05]
        bars = set(range(trk.bars)) if bars is None else set(bars)
        inst = hasattr(self.src, "render")
        srcs = None if inst else [recording(s, m, sr=trk.sr) for s, m in self.src] if isinstance(self.src, list) else [recording(self.src, self.kc, sr=trk.sr)]
        ref = 64 if inst else int(np.median([m for _, m in srcs]))
        lo = (52 if inst else ref - 5) if lo is None else lo; hi = (76 if inst else ref + 14) if hi is None else hi
        lines = [_only_bars([(t, m, vel, d) for t, m, _, d in L], bars, trk.BAR) for L in lines_of(plan.voicings(style, lo, hi, self.n), self.n, trk.S16)]
        total = trk.N / trk.sr; out = np.zeros((trk.N, 2), np.float32); st = []
        for j, L in enumerate(lines):
            if not L: continue
            c = 0.0 if self.n == 1 else self.detune_c * (2 * j / (self.n - 1) - 1)
            if inst: xs, kc = self.src, None
            else:
                mid = float(np.median([m for _, m, _, _ in L])); xs, kc = min(srcs, key=lambda r: abs(r[1] - mid))
            v = Voice(xs, kc, sr=trk.sr, seed=self.seed * 31 + j, cents=c, **self.kw)
            y = v.render(L, total, expr=expr); pan = 0.0 if self.n == 1 else self.spread * (2 * j / (self.n - 1) - 1)
            out += y[:trk.N] * np.array([np.sqrt(1 - pan), np.sqrt(1 + pan)], np.float32)
            st.append(v.stats)
        self.stats = {"voices": len(st), "notes": sum(s.get("notes", 0) for s in st), "attacks": sum(s.get("attacks", 0) for s in st),
                      "legato": sum(s.get("legato", 0) for s in st), "folded": sum(s.get("folded", 0) for s in st), "range": [int(lo), int(hi)],
                      "octave_shift": [s.get("octave_shift", 0) for s in st]}
        return out

# ---- grains of a recording on the harmony ----------------------------------------------------------------------------------
def grains(trk, src, keycenter=None, plan=None, per_bar=5.0, grain_s=(.3, .8), lo=62, hi=86, spread=.8, gain_db=(-10.0, -3.0), seed=0, bars=None, layer=None):
    """(N, 2) a texture of long grains of a recording, each pitched to a tone of the chord sounding at its time (plan or trk.plan;
    without a plan the recording's own pitch), at a random place in its body, randomly panned. Long grains with raised-cosine edges
    keep it a recording (a shimmer of the instrument), not a granular synth buzz."""
    x, kc = recording(src, keycenter, sr=trk.sr) if not hasattr(src, "render") else recording(src, (lo + hi) // 2, sr=trk.sr)
    plan = plan or getattr(trk, "plan", None); sg = body(x, trk.sr); a0, a1 = sg["a"], max(sg["b1"], sg["a"] + 1)
    if layer is not None and bars is None: bars = [b for b in range(trk.bars) if trk.sec(b)[3].get(layer, 0) > .05]
    bars = sorted(set(range(trk.bars)) if bars is None else set(bars)); rng = np.random.default_rng([seed, 1412]); sr = trk.sr
    out = np.zeros((trk.N, 2), np.float32); count = 0
    for b in bars:
        for _ in range(rng.poisson(per_bar)):
            t = (b + rng.random()) * trk.BAR; pcs = plan.at(int(t / trk.S16)).pcs if plan is not None else [kc % 12]
            pc = int(rng.choice(pcs)); target = rng.uniform(lo, hi); m = pc + 12 * round((target - pc) / 12)
            m = m + 12 if m < lo else m - 12 if m > hi else m; ratio = 2 ** ((m - kc) / 12)
            Lg = int(rng.uniform(*grain_s) * sr); need = int(Lg * ratio) + 2
            if need >= len(x): continue
            s_lo, s_hi = a0, min(a1, len(x)) - need
            if s_hi <= s_lo: s_lo, s_hi = 0, len(x) - need - 1
            p0 = int(rng.integers(s_lo, s_hi + 1))
            seg = x[p0:p0 + need]
            if ratio > 1.02: seg = sosfiltfilt(butter(4, .45 * sr / ratio, "low", fs=sr, output="sos"), seg, axis=0)
            ph = np.arange(Lg) * ratio; g = np.stack([np.interp(ph, np.arange(len(seg)), seg[:, c]) for c in range(2)], 1)
            u = np.arange(Lg) / max(1, Lg - 1); w = np.minimum(1, np.minimum(u, 1 - u) / .4); w = .5 - .5 * np.cos(np.pi * w)
            pan = float(rng.uniform(-spread, spread)); amp = 10 ** (rng.uniform(*gain_db) / 20)
            g = (g * (w * amp)[:, None] * np.array([np.sqrt(1 - pan), np.sqrt(1 + pan)])[None, :]).astype(np.float32)
            i = int(t * sr); k = min(Lg, trk.N - i)
            if k > 0: out[i:i + k] += g[:k]; count += 1
    grains.last = {"grains": count, "recording_midi": int(kc), "short_body": sg["short"]}
    return out
