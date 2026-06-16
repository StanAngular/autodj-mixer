"""
Unit tests for fix_ht() and calc_bpm() — Variant A spec.

Variant A (decided 2026-06): `db` holds ONE downbeat per bar (as produced by
load_dbeats, which keeps only beat-position 1). calc_bpm() therefore reads bar
spacing and returns 240 / bar_seconds. fix_ht()'s job is HALF/DOUBLE-TIME
correction: if the detected tempo falls outside a plausible window it rescales
the downbeat grid (and BPM) to bring it back in range, keeping db and bpm
coherent for the warp engine.

Heavy audio deps are mocked so these tests run without an audio install.
"""
import sys, os
from unittest.mock import MagicMock

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
from smart_mixer import fix_ht, calc_bpm, _grid_densify

SR = 44100


def make_bars(bpm, n=20):
    """Downbeat grid (one entry per bar) at the given musical BPM."""
    bar_step = int(240.0 / bpm * SR)   # bar = 4 beats = 240/bpm seconds
    return np.array([i * bar_step for i in range(n)], dtype=int)


# -- calc_bpm (semantics: one downbeat per bar) -----------------------------

class TestCalcBpm:
    def test_120bpm(self):
        assert abs(calc_bpm(make_bars(120.0)) - 120.0) < 0.5

    def test_90bpm(self):
        assert abs(calc_bpm(make_bars(90.0)) - 90.0) < 0.5

    def test_140bpm(self):
        assert abs(calc_bpm(make_bars(140.0)) - 140.0) < 1.0

    def test_too_short_returns_default(self):
        assert calc_bpm(make_bars(120.0, n=3)) == 120.0

    def test_outlier_rejection(self):
        """IQR filter ignores a single bad bar interval."""
        db = make_bars(120.0, n=20)
        db[5] += int(0.5 * SR)            # one glitchy bar
        assert abs(calc_bpm(db) - 120.0) < 2.0


# -- _grid_densify helper ---------------------------------------------------

class TestGridDensify:
    def test_doubles_density(self):
        db = make_bars(120.0, n=10)
        out = _grid_densify(db)
        assert len(out) == 2 * len(db) - 1     # midpoint inserted in each gap

    def test_monotonic(self):
        out = _grid_densify(make_bars(120.0, n=10))
        assert np.all(np.diff(out) > 0)

    def test_too_short_noop(self):
        db = np.array([100], dtype=int)
        assert np.array_equal(_grid_densify(db), db)


# -- fix_ht (Variant A: half/double correction) -----------------------------

class TestFixHt:
    @pytest.mark.parametrize("bpm", [90.0, 100.0, 120.0, 128.0, 140.0, 160.0])
    def test_in_range_unchanged(self, bpm):
        """Tempo inside the [85,165] window passes through untouched."""
        db = make_bars(bpm, n=20)
        db_out, bpm_out = fix_ht(db, calc_bpm(db))
        assert len(db_out) == len(db)
        assert abs(bpm_out - bpm) < 1.0

    def test_half_time_corrected(self):
        """62 BPM (madmom marked downbeats every 2 bars) -> densify -> ~124."""
        db = make_bars(62.0, n=20)
        db_out, bpm_out = fix_ht(db, calc_bpm(db))
        assert len(db_out) > len(db)
        assert abs(bpm_out - 124.0) < 2.0

    def test_double_time_corrected(self):
        """248 BPM (downbeats every half-bar) -> thin -> ~124."""
        db = make_bars(248.0, n=40)
        db_out, bpm_out = fix_ht(db, calc_bpm(db))
        assert len(db_out) < len(db)
        assert abs(bpm_out - 124.0) < 2.0

    def test_too_short_unchanged(self):
        db = make_bars(120.0, n=3)
        db_out, bpm_out = fix_ht(db, 120.0)
        assert np.array_equal(db_out, db)

    def test_empty_array(self):
        db = np.array([], dtype=int)
        db_out, _ = fix_ht(db, 120.0)
        assert len(db_out) == 0

    def test_bpm_always_recalculated(self, downbeats_120bpm):
        """Returned BPM is always derived from the (possibly rescaled) grid."""
        db_out, bpm_out = fix_ht(downbeats_120bpm, 120.0)
        assert abs(bpm_out - calc_bpm(db_out)) < 0.01

    def test_output_monotonic(self):
        """Even after densify, downbeats stay strictly increasing."""
        db = make_bars(62.0, n=20)
        db_out, _ = fix_ht(db, calc_bpm(db))
        assert np.all(np.diff(db_out) > 0)

    # -- Heuristic boundaries (documented tradeoffs, not perfection) ---------

    def test_window_boundary_doubles_downtempo(self):
        """KNOWN TRADEOFF: legit downtempo at 75 BPM is treated as half-time and
        doubled to ~150, because 75 < 85 and 150 fits the window. If the library
        has real <85 BPM material, widen bpm_min for those runs (next test)."""
        db = make_bars(75.0, n=20)
        _, bpm_out = fix_ht(db, calc_bpm(db))
        assert abs(bpm_out - 150.0) < 2.0

    def test_custom_window_preserves_dnb(self):
        """Configurable window: raising bpm_max lets DnB (~174) pass unchanged."""
        db = make_bars(174.0, n=20)
        db_out, bpm_out = fix_ht(db, calc_bpm(db), bpm_min=85.0, bpm_max=180.0)
        assert len(db_out) == len(db)
        assert abs(bpm_out - 174.0) < 2.0
