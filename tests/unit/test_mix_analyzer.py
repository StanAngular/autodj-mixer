"""Unit tests for mix_analyzer.py pure helpers (P21): transition windows + volume jumps."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import mix_analyzer as ma


class TestTransitionWindows:
    def test_basic_window(self):
        # переход t=100, dur=30 → окно [95, 135]
        assert ma.transition_windows([{"t": 100, "dur": 30}], pad=5.0) == [(95.0, 135.0)]

    def test_merges_overlapping(self):
        # два близких перехода сливаются в одно окно
        out = ma.transition_windows([{"t": 100, "dur": 30}, {"t": 125, "dur": 10}], pad=5.0)
        assert out == [(95.0, 140.0)]

    def test_keeps_distant_separate(self):
        out = ma.transition_windows([{"t": 100, "dur": 10}, {"t": 300, "dur": 20}], pad=5.0)
        assert len(out) == 2

    def test_clamps_to_zero(self):
        assert ma.transition_windows([{"t": 2, "dur": 4}], pad=5.0)[0][0] == 0.0

    def test_empty(self):
        assert ma.transition_windows([], pad=5.0) == []


class TestDetectVolumeJumps:
    def test_flags_sudden_jump(self):
        env = np.array([0.1, 0.1, 0.1, 0.4, 0.4])     # ~+12 dB на 4-м окне
        jumps = ma.detect_volume_jumps(env, 0.2, jump_db=6.0)
        assert len(jumps) == 1
        assert jumps[0]["t"] == 0.6 and jumps[0]["jump_db"] == 12.0

    def test_smooth_fade_no_flag(self):
        env = np.array([0.1, 0.11, 0.12, 0.13, 0.14])  # плавно → нет скачков
        assert ma.detect_volume_jumps(env, 0.2, jump_db=6.0) == []

    def test_drop_flagged(self):
        env = np.array([0.4, 0.4, 0.05])               # резкое падение
        jumps = ma.detect_volume_jumps(env, 0.2, jump_db=6.0)
        assert len(jumps) == 1 and jumps[0]["jump_db"] < 0

    def test_empty(self):
        assert ma.detect_volume_jumps(np.array([]), 0.2) == []
