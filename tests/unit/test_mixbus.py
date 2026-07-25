"""Q1 mixbus: гейн-стейджинг, частотные роли, сайдчейн, общий реверб-возврат."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import pytest

sc = pytest.importorskip("scipy")            # физика требует реального scipy
from autodj.generate import mixbus as mb
from autodj.generate.backends.fluidsynth import peak_guard


def _st(freq, amp=0.5, sec=1.0, sr=44100):
    t = np.arange(int(sec * sr)) / sr
    x = (amp * np.sin(2 * np.pi * freq * t)).astype("float32")
    return np.stack([x, x], 1)


class TestPeakGuardNotNormalizer:
    def test_quiet_layer_untouched(self):
        x = _st(440, 0.2)
        assert np.array_equal(peak_guard(x), x)      # раньше подтягивалось к -3dB
    def test_loud_layer_only_clipped(self):
        x = _st(440, 1.4)
        out = peak_guard(x)
        assert abs(float(np.abs(out).max()) - 0.99) < 1e-3
    def test_relative_loudness_preserved(self):
        a, b = peak_guard(_st(440, 0.2)), peak_guard(_st(440, 0.6))
        assert mb.rms(b) / mb.rms(a) > 2.5           # тихий остался тихим


class TestEqCarve:
    def test_bass_role_kills_mids(self):
        loud_mid = _st(900, 0.5)
        assert mb.rms(mb.eq_carve(loud_mid, 44100, "bass")) < 0.2 * mb.rms(loud_mid)
    def test_pad_role_kills_lows(self):
        low = _st(50, 0.5)
        assert mb.rms(mb.eq_carve(low, 44100, "pad")) < 0.2 * mb.rms(low)
    def test_drums_keep_lows(self):
        low = _st(50, 0.5)
        assert mb.rms(mb.eq_carve(low, 44100, "drums")) > 0.7 * mb.rms(low)


class TestStageGain:
    def test_quiet_layer_boosted_capped(self):
        g = mb.stage_gain(_st(440, 0.001), "lead", ref_rms=0.5)
        assert g == mb.MAX_BOOST                      # буст ограничен
    def test_loud_layer_reduced(self):
        assert mb.stage_gain(_st(440, 0.9), "pad", ref_rms=0.3) < 1.0
    def test_silence_zero(self):
        assert mb.stage_gain(np.zeros((1000, 2), "float32"), "pad", 0.5) == 0.0


class TestSidechain:
    def test_pumps_on_beat(self):
        x = np.ones((44100, 2), "float32")
        out = mb.sidechain_duck(x, 44100, period=11025, depth_db=-6)
        assert out[0, 0] < 0.55 and out[11000, 0] > 0.9   # провал на доле, восстановление
    def test_zero_period_noop(self):
        x = np.ones((100, 2), "float32")
        assert np.array_equal(mb.sidechain_duck(x, 44100, 0), x)


class TestMixLayers:
    def test_balance_and_headroom(self):
        layers = {"drums": _st(120, 0.5), "bass": _st(60, 0.9),
                  "pad": _st(500, 0.05), "lead": _st(1200, 0.02)}
        mix, gains = mb.mix_layers(layers, 44100, beat_samples=22050)
        assert float(np.abs(mix).max()) <= mb.MIX_CEILING + 1e-3
        assert gains["bass"] < 1.0 and gains["pad"] > 1.0   # громкий убран, тихий поднят
    def test_empty(self):
        mix, gains = mb.mix_layers({}, 44100, 22050)
        assert mix.shape == (0, 2) and gains == {}
    def test_reverb_send_is_shared_bus(self):
        layers = {"pad": _st(400, 0.3), "lead": _st(800, 0.3)}
        bus = mb.reverb_send(layers, {"pad": 0.5, "lead": 0.25})
        assert len(bus) == 44100 and mb.rms(bus) > 0
