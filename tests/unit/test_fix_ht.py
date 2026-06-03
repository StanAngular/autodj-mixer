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
    def test_correct_intervals_unchanged(self):
        """Beat intervals in the valid BEAT range (0.25-1.0s) pass through unchanged.
        Tests a 0.75s beat (80 BPM) -- well inside the valid window."""
        db = make_db(0.75, n=40)   # 0.75s/beat = valid range
        db_out, bpm = fix_ht(db, calc_bpm(db))
        assert len(db_out) == len(db), "Valid beat intervals must not be decimated or interpolated"

    def test_beat_interval_unchanged(self):
        """
        Beat-level intervals (0.5s @ 120 BPM) are in the valid BEAT range
        (BEAT_LO=0.25s .. BEAT_HI=1.0s).  Must NOT be decimated.
        This was the regression in 99691b3 (used BAR thresholds instead).
        """
        db = make_db(0.5, n=40)        # 120 BPM beats
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) == len(db), \
            f"0.5s beat intervals must not be modified (got {len(db_out)} from {len(db)})"

    def test_too_short_returns_unchanged(self):
        db = make_db(0.5, n=2)
        db_out, bpm_out = fix_ht(db, 120.0)
        assert np.array_equal(db_out, db)

    def test_eighth_note_decimates_x2(self):
        """Intervals of 0.1s (eighth notes) < BEAT_LO*0.65=0.16s → decimate x2."""
        db = make_db(0.1, n=40)
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) < len(db)

    def test_sixteenth_note_decimates_x4(self):
        """Intervals of 0.05s (16th notes) < BEAT_LO*0.35=0.088s → decimate x4."""
        db = make_db(0.05, n=60)
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) < len(db)

    def test_slow_intervals_interpolate(self):
        """Intervals of 1.5s > BEAT_HI*1.3=1.3s → insert midpoints."""
        db = make_db(1.5, n=10)
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) > len(db)

    def test_very_slow_intervals_split(self):
        """Intervals of 3.0s > BEAT_HI*2.2=2.2s → split into multiple beats."""
        db = make_db(3.0, n=6)
        bpm_raw = calc_bpm(db)
        db_out, bpm_out = fix_ht(db, bpm_raw)
        assert len(db_out) > len(db)

    def test_bar_level_pop_100bpm_splits_correctly(self):
        """Bar-level annotations at 100 BPM (2.4s per bar) must split into 4 beats.
        This was the bug Hermes identified: abs thresholds gave n_split=5 (wrong).
        BPM-ratio approach: musical=100, expected_beat=0.6s, ratio=4.0 → n_split=4."""
        beat_s = 60.0 / 100.0                     # 0.6s at 100 BPM
        bar_s = beat_s * 4                          # 2.4s per bar
        db = make_db(bar_s, n=8)                   # 8 bars of bar-level annotations
        bpm_raw = calc_bpm(db)                     # 4*60/2.4 = 100 (bar-level → musical BPM)
        db_out, _ = fix_ht(db, bpm_raw)
        # Each bar split into 4 beats: 8 bars → ~29 beat entries (7 gaps × 4 + 1 tail)
        assert len(db_out) > len(db), "Bar-level annotations must be split into beats"
        # Check split is into ~4 per bar (not 5 as the old hardcoded 0.5s would give)
        expected_len = (len(db) - 1) * 4 + 1
        assert len(db_out) == expected_len, f"Expected {expected_len} entries (4 per bar), got {len(db_out)}"

    def test_bar_level_120bpm_splits_to_beats(self):
        """Bar-level annotations at 120 BPM (2.0s per bar) split into 4 beats.
        This is the case Hermes warned absolute thresholds only give 1 midpoint for."""
        bar_s = 2.0   # 120 BPM bar
        db = make_db(bar_s, n=8)
        bpm_raw = calc_bpm(db)                     # = 120 (bar-level)
        db_out, _ = fix_ht(db, bpm_raw)
        expected_len = (len(db) - 1) * 4 + 1      # 29 entries
        assert len(db_out) == expected_len, f"120 BPM bar-level: expected {expected_len} beats, got {len(db_out)}"

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
