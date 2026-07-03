"""M4 club_rework: структурный план, рендер по даунбитам, тайлинг грува, гейт. Офлайн."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import club_rework as cr


POP = (["intro"] * 4 + ["verse"] * 8 + ["chorus"] * 8 + ["verse"] * 8 +
       ["chorus"] * 8 + ["bridge"] * 4 + ["chorus"] * 8 + ["outro"] * 4)   # 52 бара


class TestReworkPlan:
    def test_dj_structure(self):
        plan = cr.rework_plan(POP, intro_bars=16, outro_bars=16, loop_len=8)
        (i_s, i_e, i_r), body, (o_s, o_e, o_r) = plan[0], plan[1], plan[-1]
        assert (i_e - i_s) * i_r == 16                      # интро-луп добит до 16 бар
        assert body == (4, 48, 1)                           # тело нетронуто, один раз
        assert (o_e - o_s) * o_r == 16 and o_s >= 44        # аутро-луп из хвоста
        assert cr.plan_length_bars(plan) == 76

    def test_no_labels_returns_whole(self):
        assert cr.rework_plan([]) == []
        plan = cr.rework_plan(["chorus"] * 8)               # нет intro/outro материала
        assert (0, 8, 1) in plan                            # тело целиком, без обмана

    def test_blocks_split(self):
        blocks = cr._blocks(["a", "a", "b", "a"])
        assert blocks == [(0, 2, "a"), (2, 3, "b"), (3, 4, "a")]


class TestRenderPlan:
    def _grid(self, n_bars, bar=1000):
        return np.array([i * bar for i in range(n_bars + 1)])

    def test_loops_and_length(self):
        sr, bar = 44100, 1000
        db = self._grid(8, bar)
        audio = np.stack([np.arange(8 * bar, dtype="float32")] * 2, 1)
        out = cr.render_plan(audio, db, [(0, 2, 3), (2, 8, 1)], sr)
        # 2 бара ×3 + 6 бар = 12 бар; минус кроссфейды (15мс × 3 стыка)
        n_x = int(sr * 15 / 1000)
        assert abs(len(out) - (12 * bar - 3 * n_x)) <= 2

    def test_out_of_range_clamped(self):
        sr = 44100
        db = self._grid(4)
        audio = np.zeros((4000, 2), dtype="float32")
        out = cr.render_plan(audio, db, [(0, 99, 1)], sr)   # e за сеткой → кламп
        assert len(out) == 4000


class TestTileToLength:
    def test_tiles_to_exact_length(self):
        sr = 44100
        loop = np.ones((1000, 2), dtype="float32")
        out = cr.tile_to_length(loop, 4500, sr)
        assert len(out) == 4500
    def test_empty_loop_silence(self):
        out = cr.tile_to_length(np.zeros((0, 2), dtype="float32"), 100, 44100)
        assert len(out) == 100 and not out.any()


class TestClubGate:
    def test_typical_pop_to_club_ok(self):
        ok, rate, why = cr.club_gate(104, 124)              # ×1.192 — главный кейс
        assert ok and abs(rate - 124 / 104) < 1e-9
    def test_too_far_rejected(self):
        assert not cr.club_gate(90, 128)[0]                 # ×1.42 — развал
        assert not cr.club_gate(150, 120)[0]                # ×0.80 — развал
    def test_unknown_bpm(self):
        assert not cr.club_gate(0, 124)[0]


class TestLimiter:
    def test_limits_peak(self):
        x = np.ones((100, 2), dtype="float32") * 1.7
        assert float(np.max(np.abs(cr._limit(x)))) <= 0.99 + 1e-5
    def test_leaves_quiet_untouched(self):
        x = np.ones((100, 2), dtype="float32") * 0.5
        assert np.array_equal(cr._limit(x), x)
