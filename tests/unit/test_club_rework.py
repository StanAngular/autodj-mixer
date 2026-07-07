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


# ═══ v2: секционный аранжировщик (DJ-логика) ═══

POP_REAL = (["intro"] * 7 + ["verse"] * 11 + ["chorus"] * 10 + ["inst"] * 5 +
            ["verse"] * 11 + ["chorus"] * 20 + ["outro"] * 7)      # профиль из live-отчёта
DONOR_REAL = ["intro"] * 38 + ["chorus"] * 80 + ["inst"] * 16      # Exhale-подобный


class TestClubArrangement:
    def test_hook_played_twice(self):
        arr = cr.club_arrangement(POP_REAL)
        drops = [s for s in arr if s["kind"] == "drop"]
        assert len(drops) == 2 and drops[0]["pop"] == drops[1]["pop"]   # хук ×2
        assert drops[0]["pop"] == (44, 64)                              # самый длинный chorus
    def test_breakdown_has_no_groove(self):
        arr = cr.club_arrangement(POP_REAL)
        br = [s for s in arr if s["kind"] == "breakdown"]
        assert br and br[0]["groove"] is None
    def test_intro_outro_groove_only(self):
        arr = cr.club_arrangement(POP_REAL)
        assert arr[0]["kind"] == "intro" and arr[0]["pop"] is None
        assert arr[-1]["kind"] == "outro" and arr[-1]["pop"] is None
    def test_no_structure_fallback(self):
        arr = cr.club_arrangement(["chorus"] * 8)
        assert any(s["kind"] == "drop" for s in arr)                    # честный фоллбэк


class TestDonorLoopPick:
    def test_peak_after_giant_intro(self):
        s, e = cr.pick_donor_loop_bars(DONOR_REAL, "peak")
        assert s >= 38                                                  # НЕ из интро (v1-баг)
    def test_sparse_from_intro(self):
        s, e = cr.pick_donor_loop_bars(DONOR_REAL, "sparse")
        assert s == 0 and e <= 38
    def test_empty_labels_fallback(self):
        assert cr.pick_donor_loop_bars([], "peak") == (0, 8)


class TestDspBricks:
    def test_hpf_kills_bass_keeps_treble(self):
        sr = 44100
        t = np.arange(sr) / sr
        bass = np.stack([np.sin(2 * np.pi * 60 * t)] * 2, 1).astype("float32")
        treb = np.stack([np.sin(2 * np.pi * 4000 * t)] * 2, 1).astype("float32")
        seg = slice(4096, -4096)
        assert np.abs(cr.hpf(bass, sr, 150)[seg]).mean() < 0.1 * np.abs(bass[seg]).mean()
        assert np.abs(cr.hpf(treb, sr, 150)[seg]).mean() > 0.9 * np.abs(treb[seg]).mean()
    def test_duck_drops_at_beats(self):
        sr, q = 44100, 11025
        x = np.ones((sr, 2), dtype="float32")
        out = cr.sidechain_duck(x, sr, q, depth_db=-6.0)
        assert out[0, 0] < 0.52                                          # на доле продавлено
        assert out[q - 100, 0] > 0.95                                    # к концу четверти восстановилось
    def test_sweep_opens_up(self):
        sr = 44100
        t = np.arange(sr) / sr
        x = np.stack([np.sin(2 * np.pi * 200 * t)] * 2, 1).astype("float32")
        out = cr.hpf_sweep(x, sr, 120, 700, blocks=4)
        q1, q4 = slice(2048, sr // 4), slice(3 * sr // 4 + 2048, -256)
        assert np.abs(out[q1]).mean() > np.abs(out[q4]).mean()           # 200Гц глохнет к концу
    def test_fade(self):
        x = np.ones((1000, 2), dtype="float32")
        out = cr.fade_gain(x, 1.0, 0.2)
        assert out[0, 0] > 0.99 and abs(out[-1, 0] - 0.2) < 1e-3


class TestRenderSection:
    def _pop(self, bars=64, bar=1000):
        a = np.ones((bars * bar, 2), dtype="float32") * 0.3
        return {"vocals": a, "other": a.copy(), "bass": a.copy()}
    def test_groove_only_intro_length(self):
        sr, bar = 44100, 44100 // 4
        db = np.arange(0, 65) * bar
        loops = {"peak": np.ones((bar, 2), "float32"), "sparse": np.ones((bar, 2), "float32")}
        sec = dict(kind="intro", pop=None, bars=16, groove="sparse")
        out = cr.render_section(sec, self._pop(bar=bar), db, loops, sr, bar, bar // 4)
        assert len(out) == 16 * bar
    def test_build_lift_silences_last_bar(self):
        sr, bar = 44100, 44100 // 4
        db = np.arange(0, 65) * bar
        loops = {"peak": np.ones((bar, 2), "float32"), "sparse": np.ones((bar, 2), "float32")}
        sec = dict(kind="build", pop=None, bars=4, groove="peak")
        out = cr.render_section(sec, self._pop(bar=bar), db, loops, sr, bar, bar // 4)
        assert np.abs(out[-bar // 2:]).max() < 1e-6                     # drum-lift
