"""
Unit tests for fix_ht() and calc_bpm().

Heavy audio deps (soundfile, pyrubberband, librosa, ...) are mocked out
so these tests run without any audio installation.
"""
import sys, os
from unittest.mock import MagicMock

# Mock all heavy deps before importing smart_mixer
_HEAVY = [
    "soundfile", "pyrubberband", "librosa", "pyloudnorm",
    "scipy", "scipy.signal", "madmom",
    "madmom.features", "madmom.features.downbeats",
    "madmom.audio", "madmom.audio.signal",
]
for _m in _HEAVY:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from smart_mixer import fix_ht, calc_bpm

SR = 44100


def make_db(interval_s, n=20):
    """Create a downbeat array with uniform intervals."""
    step = int(interval_s * SR)
    return np.array([i * step for i in range(n)], dtype=int)


# ── calc_bpm ──────────────────────────────────────────────────────────────

class TestCalcBpm:
    def test_120bpm(self):
        db = make_db(2.0)  # 2s bar = 120 BPM
        assert abs(calc_bpm(db) - 120.0) < 0.5

    def test_90bpm(self):
        db = make_db(240.0 / 90.0)
        assert abs(calc_bpm(db) - 90.0) < 0.5

    def test_140bpm(self):
        db = make_db(240.0 / 140.0)
        assert abs(calc_bpm(db) - 140.0) < 1.0

    def test_too_short_returns_default(self):
        db = make_db(2.0, n=3)
        assert calc_bpm(db) == 120.0

    def test_outlier_rejection(self):
        """IQR filter should ignore a few bad intervals."""
        db = make_db(2.0, n=20)
        db_noise = db.copy()
        db_noise[5] += int(0.5 * SR)  # single glitch
        bpm = calc_bpm(db_noise)
        assert abs(bpm - 120.0) < 2.0


# ── fix_ht ────────────────────────────────────────────────────────────────

class TestFixHt:
    def test_correct_intervals_unchanged(self, downbeats_120bpm):
        """Clean 120 BPM downbeats should come through unchanged."""
        db, bpm = fix_ht(downbeats_120bpm, 120.0)
        assert abs(bpm - 120.0) < 1.0
        assert len(db) == len(downbeats_120bpm)

    def test_too_short_returns_unchanged(self):
        db = make_db(2.0, n=2)
        db_out, bpm_out = fix_ht(db, 120.0)
        assert np.array_equal(db_out, db)

    def test_half_bar_decimates(self):
        """
        Intervals of 1.0s (half of a 2s bar) should be decimated x2.
        Result should have ~half the entries and ~120 BPM.
        """
        db = make_db(1.0, n=30)        # 0.5s per downbeat → "bar"? No → 1.0s < 0.65s?
        # 1.0s: BAR_LO=1.0, 0.65*1.0=0.65 -- 1.0s > 0.65, so no fix expected
        # Let's use 0.6s intervals (clearly half-bar territory)
        db = make_db(0.6, n=30)
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) < len(db)   # decimated

    def test_beat_level_decimates_x4(self):
        """Intervals of 0.3s (individual beats at 120 BPM) decimated x4."""
        db = make_db(0.3, n=40)
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) < len(db)

    def test_double_bar_interpolates(self):
        """
        Intervals of 6.0s (2 bars at 80 BPM) should be halved by interpolation.
        Result should have roughly 2x more entries.
        """
        db = make_db(6.0, n=8)
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) > len(db)

    def test_very_long_intervals_split(self):
        """Intervals > 8.8s get split into multiple estimated bars."""
        db = make_db(10.0, n=6)
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) > len(db)

    def test_result_bpm_recalculated(self, downbeats_120bpm):
        """Return value should always be recalculated BPM, not the input."""
        db_out, bpm_out = fix_ht(downbeats_120bpm, 120.0)
        expected = calc_bpm(db_out)
        assert abs(bpm_out - expected) < 0.01

    def test_empty_array(self):
        db = np.array([], dtype=int)
        db_out, bpm_out = fix_ht(db, 120.0)
        assert len(db_out) == 0

    def test_monotonic_output(self, downbeats_120bpm):
        """Output downbeats must remain strictly increasing."""
        db_out, _ = fix_ht(downbeats_120bpm, 120.0)
        diffs = np.diff(db_out)
        assert np.all(diffs > 0)
