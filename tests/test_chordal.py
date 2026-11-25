import numpy as np
from autodj.compose import chordal
SR = 44100
def _noise(sec=4, seed=3): return np.random.default_rng(seed).standard_normal(SR * sec).astype(np.float32) * .2
def _band(x, lo, hi):
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2; f = np.fft.rfftfreq(len(x), 1 / SR); return 10 * np.log10(X[(f >= lo) & (f < hi)].sum() + 1e-20)
TL = [(0, SR * 2, [9, 0, 4]), (SR * 2, SR * 4, [5, 9, 0])]

def test_mix_zero_is_identical():
    x = _noise(); assert np.array_equal(chordal.filter(x, TL, mix=0), x)
def test_empty_timeline_is_identical():
    x = _noise(); assert np.array_equal(chordal.filter(x, []), x)
def test_deterministic_and_finite():
    x = _noise(); a = chordal.filter(x, TL, mix=.8); b = chordal.filter(x, TL, mix=.8); assert np.array_equal(a, b) and np.isfinite(a).all()
def test_chord_pitches_are_boosted():
    x = _noise(); y = chordal.filter(x, [(0, SR * 4, [9])], mix=1.0, q=20)           # A only: 220, 440, 880 ...
    on = _band(y[:, ] if y.ndim == 1 else y, 435, 445) - _band(x, 435, 445); off = _band(y, 500, 510) - _band(x, 500, 510)
    assert on - off >= 6, (on, off)                                                  # >= +6 dB on the chord tone relative to a non-chord frequency
def test_sub_untouched():
    x = _noise() + (np.sin(2 * np.pi * 55 * np.arange(SR * 4) / SR) * .3).astype(np.float32); y = chordal.filter(x, TL, mix=.9)
    assert abs(_band(y, 30, 90) - _band(x, 30, 90)) < .5
def test_no_click_at_chord_change():
    x = (np.sin(2 * np.pi * 220 * np.arange(SR * 4) / SR) * .3).astype(np.float32); y = chordal.filter(x, TL, mix=.8); i = SR * 2
    assert np.abs(np.diff(y[i - 200:i + 200])).max() <= np.abs(np.diff(y)).max() * 1.0 + 1e-6 and np.abs(np.diff(y[i - 200:i + 200])).max() < .3
def test_stereo_shape_and_mono_sum():
    x = np.stack([_noise(), _noise()], 1); y = chordal.filter(x, TL, mix=.6); assert y.shape == x.shape and np.allclose(y[:, 0], y[:, 1])
def test_timeline_from_bars():
    tl = chordal.timeline_from_bars(2.0, 2, [[0, 4, 7], [5, 9, 0]], 8); assert len(tl) == 4 and tl[0][2] == [0, 4, 7] and tl[1][2] == [5, 9, 0] and tl[2][2] == [0, 4, 7] and tl[1][0] == int(4.0 * SR)
