"""P93/P96: живое исполнение. Тесты на ОБЕ стороны: что меняется И что не трогается."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import random
import numpy as np
from autodj.generate.groove import (sample_performance, apply_groove, thin_events, echo,
                                    grid_position, METRIC_WEIGHT)

BEAT = 60.0 / 86
STEP = BEAT / 4


def perf(seed=1, **over):
    return sample_performance({"enabled": True, **over}, random.Random(seed))


def grid_events(bars=8, role_vel=64):
    """Ровные 16-е на сетке, одинаковая velocity — «машина»."""
    return [(i * STEP, 60 + i % 5, role_vel, STEP * 0.9) for i in range(bars * 16)]


class TestSamplePerformance:
    def test_disabled_returns_none(self):
        assert sample_performance(None, random.Random(1)) is None
        assert sample_performance({}, random.Random(1)) is None
        assert sample_performance({"enabled": False}, random.Random(1)) is None

    def test_same_seed_same_profile(self):
        assert perf(7) == perf(7)

    def test_different_seeds_differ(self):
        profiles = {repr(perf(s)) for s in range(10)}
        assert len(profiles) == 10                      # каждый трек — свой профиль

    def test_values_inside_ranges(self):
        for s in range(20):
            p = perf(s)
            assert 1500 <= p["pad_release_ms"] <= 4000
            assert 0.40 <= p["arp_keep"] <= 0.60
            assert 0.45 <= p["echo_feedback"] <= 0.65
            assert p["echo_beats"] in (1.0, 0.75, 1.5)
            assert 8 <= p["lag_ms"]["counter"] <= 25

    def test_style_override_partial_roles(self):
        p = sample_performance({"lag_ms": {"counter": [30, 30]}}, random.Random(1))
        assert p["lag_ms"]["counter"] == 30
        assert "lead" in p["lag_ms"]                    # остальные роли из дефолта


class TestApplyGroove:
    def test_bass_and_drums_untouched(self):
        ev = grid_events()
        for role in ("bass", "drums"):
            assert apply_groove(ev, role, perf(), 0.13, BEAT, random.Random(1)) == ev

    def test_no_perf_untouched(self):
        ev = grid_events()
        assert apply_groove(ev, "counter", None, 0.13, BEAT, random.Random(1)) == ev

    def test_strong_beats_louder_than_weak(self):
        out = apply_groove(grid_events(16), "counter", perf(), 0.0, BEAT, random.Random(2))
        by_step = {}
        for t, _, v, _ in out:
            st, _ = grid_position(t - perf()["lag_ms"]["counter"] / 1000, BEAT)
            by_step.setdefault(st, []).append(v)
        assert np.mean(by_step[0]) > np.mean(by_step[4]) > np.mean(by_step[1])

    def test_velocity_not_flat(self):
        out = apply_groove(grid_events(), "arp", perf(), 0.1, BEAT, random.Random(3))
        assert np.std([e[2] for e in out]) > 5          # было 0: все 64

    def test_lagged_behind_grid_but_within_half_step(self):
        p = perf(4)
        out = apply_groove(grid_events(), "counter", p, 0.0, BEAT, random.Random(4))
        devs = [e[0] - i * STEP for i, e in enumerate(out)]
        assert np.mean(devs) > 0.004                    # в среднем позади сетки
        assert max(abs(d) for d in devs) < STEP / 2     # но в свою 16-ю

    def test_swing_matches_drums(self):
        """Нечётные 16-е сдвигаются на swing * шаг — ровно как _swt у барабанов."""
        p = perf(5, jitter_ms={"arp": [0, 0]}, lag_ms={"arp": [0, 0]})
        ev = grid_events(1)
        out = apply_groove(ev, "arp", p, 0.2, BEAT, random.Random(5))
        assert abs(out[1][0] - (STEP + 0.2 * STEP)) < 1e-6
        assert abs(out[2][0] - 2 * STEP) < 1e-6         # чётные на месте

    def test_offgrid_note_keeps_its_place(self):
        p = perf(6, jitter_ms={"accent": [0, 0]})
        t = 3 * STEP + STEP * 0.45                      # явно вне сетки
        out = apply_groove([(t, 60, 70, 1.0)], "accent", p, 0.2, BEAT, random.Random(6))
        assert abs(out[0][0] - (t + p["lag_ms"]["accent"] / 1000)) < 1e-6

    def test_pad_keeps_strum_timing(self):
        ev = [(0.0, [50], 58, 4.0), (0.011, [53], 58, 4.0), (0.022, [57], 58, 4.0)]
        out = apply_groove(ev, "pad", perf(), 0.2, BEAT, random.Random(7))
        assert [e[0] for e in out] == [0.0, 0.011, 0.022]
        assert all(isinstance(e[1], list) for e in out)


class TestThin:
    def test_thins_but_not_to_zero(self):
        ev = grid_events(32)
        out = thin_events(ev, 0.5, BEAT, random.Random(1))
        assert 0.3 * len(ev) < len(out) < 0.8 * len(ev)

    def test_keep_one_is_identity_and_zero_is_empty(self):
        ev = grid_events()
        assert thin_events(ev, 1.0, BEAT, random.Random(1)) == ev
        assert thin_events(ev, 0.0, BEAT, random.Random(1)) == []

    def test_prefers_strong_beats(self):
        ev = grid_events(64)
        out = thin_events(ev, 0.4, BEAT, random.Random(2))
        kept = {grid_position(e[0], BEAT)[0] for e in out}
        n0 = sum(1 for e in out if grid_position(e[0], BEAT)[0] == 0)
        n1 = sum(1 for e in out if grid_position(e[0], BEAT)[0] == 1)
        assert n0 > n1

    def test_protect_strong(self):
        ev = grid_events(16)
        out = thin_events(ev, 0.1, BEAT, random.Random(3), protect_strong=True)
        strong = [e for e in ev if METRIC_WEIGHT[grid_position(e[0], BEAT)[0]] >= 0.7]
        assert all(e in out for e in strong)


class TestEcho:
    SR = 8000

    def impulse(self, n_s=4.0):
        x = np.zeros((int(n_s * self.SR), 2), np.float32)
        x[100:140, :] = 0.8
        return x

    def test_adds_repeats_after_dry(self):
        x = self.impulse()
        y = echo(x, self.SR, 0.5, 0.6, 0.4, duck=0.0)
        k1 = 100 + int(0.5 * self.SR)
        assert np.abs(y[k1:k1 + 200]).max() > 0.01      # первый повтор есть
        assert np.abs(y[2 * k1:2 * k1 + 200]).max() > 0  # и второй

    def test_repeats_decay(self):
        x = self.impulse(6.0)
        y = echo(x, self.SR, 0.5, 0.6, 0.4, pingpong=False, duck=0.0)
        peaks = [np.abs(y[100 + k * 4000:100 + k * 4000 + 400, 0]).max() for k in (1, 2, 3)]
        assert peaks[0] > peaks[1] > peaks[2]

    def test_pingpong_alternates(self):
        x = self.impulse()
        y = echo(x, self.SR, 0.5, 0.6, 0.4, pingpong=True, duck=0.0)
        s1 = slice(4100, 4500)
        assert np.abs(y[s1, 0]).max() > np.abs(y[s1, 1]).max()   # первый повтор — слева

    def test_off_is_identity(self):
        x = self.impulse()
        assert np.array_equal(echo(x, self.SR, 0.5, 0.6, 0.0), x)
        assert np.array_equal(echo(x, self.SR, 0.5, 0.0, 0.4), x)
