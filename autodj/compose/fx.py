"""DJ transitions applied to the mix bus (call after the music layers, before the voice)."""
import numpy as np
from .core import pb, fade, sweep

def tapestop(trk, end_bar, beats=2, gap_beats=0, tail=0.3):
    """the music slows to a stop over `beats`, then `gap_beats` of silence (reverb tail) up to end_bar.
    Returns the time (s) where the gap starts, for a voice line."""
    from pedalboard import Pedalboard, Reverb
    D = beats * trk.BEAT; j1 = trk.i(end_bar); i0 = j1 - (beats + gap_beats) * trk.BEAT
    tau = np.arange(D); pos = tau - tau ** 2 / (2 * D)
    seg = np.stack([np.interp(pos, np.arange(D), trk.mix[i0:i0 + D, c]) for c in range(2)], 1) * np.linspace(1, 0, D)[:, None] ** .6
    trk.mix[i0:j1] = 0; trk.mix[i0:i0 + D] = seg
    if gap_beats and tail:
        rv = pb(Pedalboard([Reverb(room_size=.8, wet_level=1., dry_level=0.)]), np.concatenate([seg, np.zeros((j1 - i0 - D, 2), np.float32)]))
        trk.mix[i0:j1] += tail * rv[:j1 - i0] * np.linspace(1, 0, j1 - i0)[:, None]
    return (i0 + D) / trk.sr

def tapestop_for(trk, end_bar, voice_len_s, beats=1):
    """tape stop whose silent gap is just long enough for a voice line ending right before end_bar"""
    g = int(np.ceil((voice_len_s + .1) * trk.sr / trk.BEAT)); return tapestop(trk, end_bar, beats, g)

def stutter(trk, bar, plan=((2, 2), (4, 1), (8, 1))):
    """beat-repeat over one bar: (division, beats) e.g. 1/8 for 2 beats, 1/16 for 1, 1/32 for 1"""
    i0 = trk.i(bar); src = trk.mix[i0:i0 + trk.BEAT // 2].copy(); out = []
    for div, beats in plan:
        L = trk.BEAT // div; out += [fade(src[:L], 3)] * (beats * div)
    o = np.concatenate(out)[:trk.i(bar + 1) - i0]; trk.mix[i0:i0 + len(o)] = o * np.linspace(.8, 1.1, len(o))[:, None]

def hp_build(trk, a, b, cuts=(20, 150, 400, 900)):
    """high-pass rises over bars a..b, snaps open at b"""
    from pedalboard import HighpassFilter
    i0, i1 = trk.i(a), trk.i(b); c = np.linspace(0, 1, i1 - i0, dtype=np.float32)[:, None] ** 1.5
    trk.mix[i0:i1] = sweep(trk.mix[i0:i1].copy(), list(cuts), c, HighpassFilter)

def silence_beat(trk, bar, beats=1):
    """drop the last beat(s) before `bar` to silence (for a shout / an impact)"""
    n = beats * trk.BEAT; i = trk.i(bar) - n
    trk.mix[i:i + n] *= np.concatenate([np.linspace(1, 0, 200), np.zeros(n - 200)])[:, None]

def reverse_swell(x, room=.9, pad_s=1.0, sr=44100):
    """reversed reverb of a sample: place it to end exactly on a downbeat"""
    from pedalboard import Pedalboard, Reverb
    y = pb(Pedalboard([Reverb(room_size=room, wet_level=.8, dry_level=.4)]), np.concatenate([x, np.zeros((int(pad_s * sr), 2), np.float32)]))
    return y[::-1].copy()

def noise_riser(trk, dur_s, cuts=(600, 1500, 3500)):
    from pedalboard import LowpassFilter, Pedalboard
    n = int(dur_s * trk.sr); x = trk.rng.normal(0, 1, (n, 2)).astype(np.float32); y = np.zeros_like(x)
    for q, f in enumerate(cuts):
        a, b = q * n // len(cuts), (q + 1) * n // len(cuts); y[a:b] = pb(Pedalboard([LowpassFilter(f)]), x)[a:b]
    return y * (np.linspace(0, 1, n) ** 3)[:, None]

def echo_throw(trk, buf, x, t, step_s, n=4, decay=.6, start_g=.5, tail_s=.3):
    """repeat the tail of x after time t, alternating sides (send the buffer through a dark delay/reverb)"""
    tl = fade(x[-int(tail_s * trk.sr):] if x.ndim == 2 else x[-int(tail_s * trk.sr):], 40)
    for q in range(n): trk.place(buf, tl, t + (q + 1) * step_s, start_g * decay ** q, (-.5, .5)[q % 2])

def analog(x, sr=44100, wow_ms=1.0, wow_hz=.45, flutter_ms=.08, flutter_hz=6.5, drive_db=2.5, hiss_db=-66, top_hz=12000, seed=0):
    """tape-ish imperfection: slow wow + fast flutter (pitch wobble via modulated delay), soft saturation, rolled-off
    top and a whisper of hiss. Against the 'sterile / digital' sound."""
    from pedalboard import Pedalboard, LowpassFilter
    from .core import sat
    n = len(x); t = np.arange(n) / sr; r = np.random.default_rng(seed); ph = r.uniform(0, 2 * np.pi, 2)
    d = (3.0 + wow_ms * np.sin(2 * np.pi * wow_hz * t + ph[0]) + flutter_ms * np.sin(2 * np.pi * flutter_hz * t + ph[1])) * sr / 1000
    pos = np.clip(np.arange(n) - d, 0, n - 1)
    y = np.stack([np.interp(pos, np.arange(n), x[:, c]) for c in range(2)], 1).astype(np.float32)
    y = pb(Pedalboard([LowpassFilter(top_hz)]), sat(y, drive_db), sr)
    if hiss_db is not None:
        lvl = np.sqrt(np.mean(y ** 2)) * 10 ** (hiss_db / 20) * 30
        y += pb(Pedalboard([LowpassFilter(9000)]), r.normal(0, lvl, (n, 2)).astype(np.float32), sr)
    return y

def pullback(trk, a, b, low_hz=350, curve=1.6):
    """«оттяжка»: over bars a..b the whole mix is pulled back through a closing low-pass (the groove keeps going,
    nothing goes silent), then it snaps fully open on bar b where the drums come back. Стас 2026-10-17: short pulls
    like this instead of long drumless breaks and instead of «build a layer, cut everything to silence, drums»."""
    from pedalboard import LowpassFilter
    i0, i1 = trk.i(a), trk.i(b); c = 1 - np.linspace(0, 1, i1 - i0, dtype=np.float32)[:, None] ** curve
    trk.mix[i0:i1] = sweep(trk.mix[i0:i1].copy(), [low_hz, low_hz * 3, 2500, 9000, 18000], c, LowpassFilter)

def vocoder(mod, carrier, sr=44100, n_fft=2048, hop=512, smooth_bins=12):
    """channel-vocoder-like cross synthesis: the carrier (e.g. a saw chord in the key) speaks with the modulator's
    spectral envelope -> robotic but clean and in key. Both (n, 2) or (n,), same length."""
    import librosa
    mm = mod.mean(1) if mod.ndim == 2 else mod; cc = carrier.mean(1) if carrier.ndim == 2 else carrier
    M = librosa.stft(mm, n_fft=n_fft, hop_length=hop); C = librosa.stft(cc, n_fft=n_fft, hop_length=hop)
    k = np.ones(smooth_bins) / smooth_bins
    env = lambda X: np.apply_along_axis(lambda c: np.convolve(c, k, "same"), 0, np.abs(X)) + 1e-6
    Y = C / env(C) * env(M)
    y = librosa.istft(Y, hop_length=hop, length=len(mm)).astype(np.float32)
    return np.stack([y, y], 1)

def fader_dip(trk, bar, beats=1, depth_db=-30.0, down_ms=50, up_ms=4):
    """DJ fader trick (Стас 2026-10-21: «крутони громкость вниз и потом вверх на бит»): the whole mix drops on the last
    `beats` before `bar` (fast pull-down) and slams back exactly on the downbeat of `bar`."""
    i1 = trk.i(bar); i0 = i1 - beats * trk.BEAT; g = 10 ** (depth_db / 20); d = int(down_ms * trk.sr / 1000); u = int(up_ms * trk.sr / 1000)
    env = np.full(i1 - i0, g, np.float32); env[:d] = np.linspace(1, g, d) ** 2 if d else g
    trk.mix[i0:i1] *= env[:, None]
    if u: trk.mix[i1:i1 + u] *= np.linspace(g, 1, u)[:, None]

def swell(trk, a, b, power=2.0, floor=0.0):
    """per-sample gain (n,1): 0 before bar a, rising (accelerating, power>1) to 1 at bar b, 1 after — a layer that
    grows in instead of switching on"""
    x = np.clip((trk.tt / trk.BAR - a) / max(1e-9, b - a), 0, 1)
    return (floor + (1 - floor) * x ** power).astype(np.float32)[:, None]

def autopan(trk, x, period_bars=8, depth=.5, phase=0.0):
    """the layer drifts slowly from ear to ear (constant power); depth 1 = fully left <-> fully right"""
    p = depth * np.sin(2 * np.pi * (trk.tt[:len(x)] / (period_bars * trk.BAR) + phase)).astype(np.float32)
    th = (p + 1) * np.pi / 4; m = x.mean(1); s = (x[:, 0] - x[:, 1]) / 2                # keep the layer's own width as side
    return np.stack([m * np.cos(th) * np.sqrt(2) + s, m * np.sin(th) * np.sqrt(2) - s], 1).astype(np.float32)

def float_gain(trk, period_bars=16, depth_db=3.0, phase=0.0):
    """slow floating volume (n,1): +-depth_db/2 around 0 dB, for an overlay that breathes instead of sitting still"""
    return (10 ** (depth_db / 2 * np.sin(2 * np.pi * (trk.tt / (period_bars * trk.BAR) + phase)) / 20)).astype(np.float32)[:, None]
