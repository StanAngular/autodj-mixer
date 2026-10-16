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
