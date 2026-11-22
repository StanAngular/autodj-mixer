"""P181-P184 (2026-11-22, Стас: «хочу, чтобы ты свободнее оперировал слоями и делал переходы из одного в другое, у Suno это легко»): LAYER MORPHING.
Not a crossfade (one layer down, the other up): one sound TURNS INTO another, and in the middle of the transition both are heard as one hybrid.
Everything works on the audio of the layers BEFORE Track.add, (n, 2) float32 at 44.1 kHz; off unless a score calls it; deterministic (seed); every use is logged.

  curve(n, shape)                   0 -> 1 over n points ("smooth" = raised cosine, "linear", "late", "early")
  spectral_handoff(a, b, c)         P181: a moving crossover: A keeps the band under the split, B takes the band above it, the split sweeps from the top to the bottom;
                                    the two parts always sum to the full spectrum, so the level holds (a filter handoff, but complementary per STFT bin)
  note_relay(notes, split, mode)    P181: a phrase handed from instrument A to instrument B: "split" at a step, or "weave" = alternate notes inside a window
  spectral_morph(a, b, c)           P182: per STFT bin the log-magnitude goes from A to B (geometric mean in the middle: a real hybrid, not a sum), the phase follows the
                                    stronger source, the frame energy follows the straight line between the two energies (no hole, no bump). Best on the SAME notes or on drums.
  cross_synth(mod, car, amount)     P183: the spectral envelope of `mod` (its colour / formants) on the fine structure of `car` (a vocoder-like cross-synthesis)
  granular_morph(a, b, c, rng)      P183: overlapping grains, each taken from A or B with the probability of the curve (textures, FX, field recordings)
  apply(trk, name, a, b, bar0, bar1, kind, **kw)   the whole layer: A before bar0, the morph between, B after bar1; trk.morphs gets a record
  report(a, b, out, i0, i1)         P184: peak, level continuity through the transition (dB off the straight line), low-band mono, and how much the middle resembles A and B
Transitions of 2-8 bars sound best (research 2026-11-22: longer spectral morphs smear, shorter ones read as a cut)."""
import numpy as np

SR = 44100; NFFT = 2048; HOP = 512

def curve(n, shape="smooth"):
    u = np.linspace(0.0, 1.0, max(2, int(n)))
    if shape == "linear": return u
    if shape == "late": return u ** 2
    if shape == "early": return 1 - (1 - u) ** 2
    return .5 - .5 * np.cos(np.pi * u)

def _st(x):
    x = np.asarray(x, np.float32); return np.stack([x, x], 1) if x.ndim == 1 else x
def _stft(x):
    import librosa
    return np.stack([librosa.stft(x[:, ch], n_fft=NFFT, hop_length=HOP) for ch in range(x.shape[1])])     # (ch, bins, frames)
def _istft(S, n):
    import librosa
    return np.stack([librosa.istft(S[ch], hop_length=HOP, length=n) for ch in range(S.shape[0])], 1).astype(np.float32)
def _frames_curve(c, frames, n):
    """the sample curve resampled to the STFT frames"""
    return np.interp(np.arange(frames) * HOP, np.linspace(0, n, len(c)), c)

def _pair(a, b):
    a, b = _st(a), _st(b); n = min(len(a), len(b)); return a[:n], b[:n], n

def spectral_handoff(a, b, c=None, sr=SR, lo_hz=60.0, hi_hz=16000.0, width_oct=.8):
    a, b, n = _pair(a, b); c = curve(256) if c is None else c; A, B = _stft(a), _stft(b); F = A.shape[2]; cf = _frames_curve(c, F, n)
    f = np.maximum(np.fft.rfftfreq(NFFT, 1 / sr), 1.0); split = np.exp(np.log(hi_hz) + (np.log(lo_hz) - np.log(hi_hz)) * cf)          # the split sweeps from the top down
    z = (np.log2(f)[:, None] - np.log2(split)[None, :]) / width_oct; mb = 1 / (1 + np.exp(-4 * z))                                       # B above the split, smooth
    mb = np.where(cf[None, :] >= .999, 1.0, np.where(cf[None, :] <= .001, 0.0, mb))
    return _istft(A * (1 - mb)[None] + B * mb[None], n)

def spectral_morph(a, b, c=None, eps=1e-6):
    a, b, n = _pair(a, b); c = curve(256) if c is None else c; A, B = _stft(a), _stft(b); F = A.shape[2]; cf = _frames_curve(c, F, n)[None, None, :]
    ma, mb = np.abs(A) + eps, np.abs(B) + eps; m = np.exp((1 - cf) * np.log(ma) + cf * np.log(mb))
    ph = np.where(ma >= mb, np.angle(A), np.angle(B)); S = m * np.exp(1j * ph)
    ea, eb, es = (np.sqrt((np.abs(X) ** 2).sum(1, keepdims=True)) for X in (A, B, S)); target = (1 - cf) * ea + cf * eb
    S = S * (target / (es + 1e-9))                                                                                                      # the energy follows the straight line
    return _istft(S, n)

def _envelope(M, smooth_bins=24):
    k = np.hanning(2 * smooth_bins + 1); k /= k.sum(); return np.apply_along_axis(lambda v: np.convolve(v, k, "same"), 1, M) + 1e-6
def cross_synth(mod, car, amount=1.0, smooth_bins=24):
    mod, car, n = _pair(mod, car); Mo, Ca = _stft(mod), _stft(car); out = []
    for ch in range(Ca.shape[0]):
        em, ec = _envelope(np.abs(Mo[ch]), smooth_bins), _envelope(np.abs(Ca[ch]), smooth_bins); g = (em / ec) ** float(amount)
        S = Ca[ch] * g; S *= np.sqrt((np.abs(Ca[ch]) ** 2).sum()) / (np.sqrt((np.abs(S) ** 2).sum()) + 1e-9); out.append(S)
    return _istft(np.stack(out), n)

def granular_morph(a, b, c=None, rng=None, grain_ms=60.0, sr=SR):
    a, b, n = _pair(a, b); c = curve(256) if c is None else c; rng = rng or np.random.default_rng(0); g = int(grain_ms / 1000 * sr); hop = g // 2
    w = np.hanning(g).astype(np.float32)[:, None]; out = np.zeros_like(a); norm = np.zeros((n, 1), np.float32)
    for i in range(0, n - g, hop):
        p = float(np.interp(i + g / 2, np.linspace(0, n, len(c)), c)); src = b if rng.random() < p else a
        out[i:i + g] += src[i:i + g] * w; norm[i:i + g] += w
    tail = norm[:, 0] < 1e-3; out[~tail] /= norm[~tail]; out[tail] = (a[tail] if c[-1] < .5 else b[tail]); return out

def note_relay(notes, split=None, mode="split", window=None):
    """(notes for A, notes for B); notes [(step, len, midi, vel)]. split: the step where B takes over; weave: inside window=(s0, s1) the notes alternate A / B, before A, after B"""
    a, b = [], []
    for i, n in enumerate(sorted(notes)):
        s = n[0]
        if mode == "weave" and window:
            if s < window[0]: a.append(n)
            elif s >= window[1]: b.append(n)
            else: (a if i % 2 == 0 else b).append(n)
        else: (a if split is None or s < split else b).append(n)
    return a, b

KINDS = {"handoff": spectral_handoff, "spectral": spectral_morph, "granular": granular_morph}
def apply(trk, name, a, b, bar0, bar1, kind="spectral", shape="smooth", rng=None, **kw):
    """the full-length layer: A until bar0, the morph between bar0 and bar1, B from bar1; logs trk.morphs; returns the buffer"""
    a, b = _st(a), _st(b); n = min(len(a), len(b), trk.N); a, b = a[:n], b[:n]; i0, i1 = int(bar0 * trk.BAR * trk.sr), int(bar1 * trk.BAR * trk.sr)
    if not (0 <= i0 < i1 <= n): raise ValueError(f"morph {name}: bars {bar0}-{bar1} outside the layer")
    if not (2 <= bar1 - bar0 <= 16): raise ValueError(f"morph {name}: {bar1 - bar0} bars; keep 2-16 (2-8 sound best)")
    c = curve(i1 - i0, shape); f = KINDS[kind]
    mid = f(a[i0:i1], b[i0:i1], c, rng=rng or np.random.default_rng(trk.seed if hasattr(trk, "seed") else 0), **kw) if kind == "granular" else f(a[i0:i1], b[i0:i1], c, **kw)
    out = np.concatenate([a[:i0], mid, b[i1:]]).astype(np.float32)
    rep = report(a, b, out, i0, i1, trk.sr); rec = {"layer": name, "kind": kind, "bars": [int(bar0), int(bar1)], **rep}
    trk.morphs = getattr(trk, "morphs", []) + [rec]; return out

def _logspec(x, i0, i1):
    seg = _st(x)[i0:i1].mean(1)
    if len(seg) < NFFT: return None
    S = np.abs(np.fft.rfft(seg[:len(seg) // NFFT * NFFT].reshape(-1, NFFT) * np.hanning(NFFT), axis=1)).mean(0); return np.log(S + 1e-6)
def report(a, b, out, i0, i1, sr=SR):
    """{"peak": max |out|, "level_dev_db": the largest deviation (dB, 100 ms frames) of out's level from the straight line between A's and B's levels through the
    transition, "low_side": side/mid energy of out under 150 Hz, "mid_like_a" / "mid_like_b": correlation of the middle's log spectrum with A's and B's}"""
    a, b, out = _st(a), _st(b), _st(out); fr = int(.1 * sr); devs = []
    for k, j in enumerate(range(i0, i1 - fr, fr)):
        u = (j - i0) / max(1, i1 - i0); r = lambda x: np.sqrt((x[j:j + fr] ** 2).mean() + 1e-12)
        line = (1 - u) * r(a) + u * r(b)
        if line > 1e-4: devs.append(abs(20 * np.log10(r(out) / line)))
    m0, m1 = i0 + int(.4 * (i1 - i0)), i0 + int(.6 * (i1 - i0)); so, sa, sb = (_logspec(x, m0, m1) for x in (out, a, b))
    from scipy.signal import butter, sosfilt
    lo = sosfilt(butter(4, 150, "low", fs=sr, output="sos"), out[i0:i1], axis=0); mid, side = (lo[:, 0] + lo[:, 1]) / 2, (lo[:, 0] - lo[:, 1]) / 2
    corr = lambda x, y: float(np.corrcoef(x, y)[0, 1]) if x is not None and y is not None else None
    return {"peak": round(float(np.abs(out[i0:i1]).max()), 3), "level_dev_db": round(float(max(devs)) if devs else 0.0, 2),
            "low_side": round(float((side ** 2).sum() / ((mid ** 2).sum() + 1e-12)), 4), "mid_like_a": corr(so, sa), "mid_like_b": corr(so, sb)}

def problems(morphs, level_tol_db=3.0, hybrid_min=.6):
    """report lines: a morph that clips, changes level more than level_tol_db, has stereo bass, or whose middle resembles only one of the two (= a cut, not a morph)"""
    out = []
    for m in morphs or []:
        tag = f"морф {m['layer']} ({m['kind']}, такты {m['bars'][0]}-{m['bars'][1]})"
        if m["peak"] > 1.0: out.append(f"{tag}: клиппинг (пик {m['peak']})")
        if m["level_dev_db"] > level_tol_db: out.append(f"{tag}: громкость гуляет на {m['level_dev_db']} дБ через переход")
        if m["low_side"] > .02: out.append(f"{tag}: бас не в моно в переходе ({m['low_side']:.1%})")
        la, lb = m.get("mid_like_a"), m.get("mid_like_b")
        if la is not None and lb is not None and min(la, lb) < hybrid_min: out.append(f"{tag}: середина похожа только на {'A' if la > lb else 'B'} (сходство {la:.2f}/{lb:.2f}): это переключение, не морф")
    return out
