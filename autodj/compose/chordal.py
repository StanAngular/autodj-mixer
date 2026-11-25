"""P187 (2026-11-25): chordal filter, a POINT tool (not a track concept). Idea from the Au5 «chordal bass» method, adapted: the signal is resonated on the notes of the
chord that is playing, so a bass drone, a pad, a noise bed, a break or a voice sample «sings» the harmony. Everything is optional and OFF unless a score calls it.
Where it helps (heard 2026-11-25, Стас: not to be built around): sustained or noisy sources in ambient / downtempo / breaks sections, chord changes every 1-2 bars.
Where it does not: one dry source for the whole track; fast divisions on a bass (tempo-synced reese was not audible) -> use it on one layer for a few sections.

  chord_freqs(pcs, octaves, lo, hi)           resonance frequencies for pitch classes (0 = C) across octaves
  filter(x, timeline, mix, q, ...)            x mono or stereo; timeline [(start_sample, end_sample, [pcs])] -> same shape, float32
  timeline_from_bars(bar_s, bars_per_chord, progression, n_bars, sr)   [(s, e, pcs)] for a looping progression
Differences from the spec (own improvements): the processed band is high-passed again at the crossover (without it the sub gained ~3 dB), each chord segment is
RMS-matched to its own input, raised-cosine crossfades of glide_ms between chords, deterministic (no random state)."""
import numpy as np
from scipy.signal import butter, sosfilt, lfilter, iirpeak

def chord_freqs(pcs, octaves=(2, 6), lo=130.0, hi=6500.0):
    f = [440.0 * 2 ** ((12 * (o + 1) + (pc % 12) - 69) / 12) for o in range(octaves[0], octaves[1] + 1) for pc in pcs]
    return np.unique(np.round([v for v in f if lo <= v <= hi], 2))

def _split(x, hz, sr):
    """Linkwitz-Riley 4th order (two cascaded 2nd-order Butterworth): lo + hi is flat in level, and hi has almost nothing below the crossover.
    (A complementary x - lowpass(x) leaks phase-shifted sub into hi: measured +3..4 dB in the sub band after processing.)"""
    lp = butter(2, hz, "lowpass", fs=sr, output="sos"); hp = butter(2, hz, "highpass", fs=sr, output="sos")
    return sosfilt(lp, sosfilt(lp, x)), sosfilt(hp, sosfilt(hp, x))

def filter(x, timeline, mix=.45, q=14.0, sub_hz=130.0, octaves=(2, 6), glide_ms=65.0, drive_pre=1.2, sr=44100, hi_hz=6500.0):
    """mix 0 returns x unchanged (bit-identical). The part below sub_hz is never touched."""
    xs = np.asarray(x)
    if mix <= 0 or not len(timeline): return xs.copy()
    st_ = xs.ndim == 2; m = xs.mean(1).astype(np.float64) if st_ else xs.astype(np.float64)
    sub, hi = _split(m, sub_hz, sr)
    if drive_pre > 1: hi = np.tanh(hi * drive_pre) / np.tanh(drive_pre)
    wet = np.zeros_like(hi); F = max(1, int(sr * glide_ms / 1000))
    for s, e, pcs in timeline:
        s = max(0, int(s)); e = min(len(hi), int(e))
        if e <= s or not pcs: continue
        ps, pe = max(0, s - F), min(len(hi), e + F); seg = hi[ps:pe]; fr = chord_freqs(pcs, octaves, sub_hz, hi_hz)
        if not len(fr): continue
        acc = np.zeros_like(seg)
        for f0 in fr:
            b, a = iirpeak(f0, q, fs=sr); acc += (200.0 / f0) ** .45 * lfilter(b, a, seg)
        acc *= (np.sqrt(np.mean(seg ** 2)) + 1e-12) / (np.sqrt(np.mean(acc ** 2)) + 1e-12)
        w = np.ones(len(acc))
        if ps < s: n = s - ps; w[:n] = .5 - .5 * np.cos(np.pi * np.linspace(0, 1, n))
        if pe > e: n = pe - e; w[-n:] = .5 + .5 * np.cos(np.pi * np.linspace(0, 1, n))
        wet[ps:pe] += acc * w
    y = sub + _split((1 - mix) * hi + mix * wet, sub_hz, sr)[1]
    return (np.stack([y, y], 1) if st_ else y).astype(np.float32)

def timeline_from_bars(bar_s, bars_per_chord, progression, n_bars, sr=44100):
    """progression: list of pitch-class lists, looped; bar_s: seconds per bar"""
    return [(int(b * bar_s * sr), int((b + bars_per_chord) * bar_s * sr), list(progression[(b // bars_per_chord) % len(progression)])) for b in range(0, n_bars, bars_per_chord)]
