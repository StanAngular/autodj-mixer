"""P122: A/B/C fragments. Both sides: loudness matched (a choice must not be about level) AND the variants really differ in the intended parameter only."""
import numpy as np, pytest
from autodj.compose import abc as ABC
from autodj.compose.stereo import width_ratio
SR = ABC.SR

def _music(seconds=6, seed=0):
    r = np.random.default_rng(seed); t = np.arange(int(seconds * SR)) / SR
    L = .3 * np.sin(2 * np.pi * 220 * t) + .1 * np.sin(2 * np.pi * 880 * t) + .02 * r.normal(0, 1, len(t))
    R = .3 * np.sin(2 * np.pi * 220 * t) + .1 * np.sin(2 * np.pi * 882 * t) + .02 * r.normal(0, 1, len(t))
    return np.stack([L, R], 1).astype(np.float32)

def test_loudness_matched_and_a_untouched(tmp_path):
    x = _music(); m = ABC.fragments(x, 0, 5, str(tmp_path), "t")
    rms = {k: v["rms_db"] for k, v in m["measured"].items()}
    assert abs(rms["B"] - rms["A"]) <= .4 and abs(rms["C"] - rms["A"]) <= .4                 # same level
    assert (tmp_path / "t_A.mp3").exists() and (tmp_path / "t_manifest.json").exists()

def test_variants_differ_only_where_intended(tmp_path):
    x = _music(); m = ABC.fragments(x, 0, 5, str(tmp_path), "t")["measured"]
    assert m["C"]["width_400"] > m["A"]["width_400"] * 1.15                                   # C is wider ...
    assert abs(m["B"]["width_400"] - m["A"]["width_400"]) < .12                               # ... B is not
    assert m["B"]["centroid_hz"] <= m["A"]["centroid_hz"] * 1.02                              # B never brighter (air shelf)

def test_does_not_touch_the_low_end_width(tmp_path):
    x = _music(); y = ABC.space(x[:SR * 4]); from scipy.signal import butter, sosfilt
    lo = lambda z: sosfilt(butter(4, [20, 120], "band", fs=SR, output="sos"), z, axis=0)   # same idea as the 20-150 Hz gate, clear of the filter skirt
    sa, sc = lo(x[:SR * 4]), lo(y); side = lambda z: float(np.mean(((z[:, 0] - z[:, 1]) / 2) ** 2))
    assert side(sc) <= side(sa) * 1.5 + 1e-8                                                  # no new side energy in the sub/bass band (low end folded to mono)

def test_rejects_silence_and_short_input(tmp_path):
    with pytest.raises(ValueError): ABC.fragments(np.zeros((SR * 3, 2), np.float32), 0, 2, str(tmp_path))
    with pytest.raises(ValueError): ABC.fragments(np.zeros((100, 2), np.float32), 0, 2, str(tmp_path))
    ok = ABC.fragments(_music(3), 2.0, 5, str(tmp_path), "short")                              # start near the end: shorter fragment is accepted if >= 1 s
    assert ok["dur_s"] >= 1.0
