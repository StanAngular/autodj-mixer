"""Q2: секционная аранжировка — плотность, филлы, ghosts. Офлайн, чистые функции."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from autodj.generate.arrangement import (default_plan, section_at, make_fill,
                                         apply_sections, layer_section_gain)


class TestPlan:
    def test_long_track_has_full_arc(self):
        kinds = [k for _, _, k in default_plan(96)]
        assert kinds[0] == "intro" and kinds[-1] == "outro"
        assert "breakdown" in kinds and kinds.count("drop") == 2   # дроп повторяется
    def test_short_track_simple(self):
        assert [k for _, _, k in default_plan(8)] == ["drop"]
    def test_medium_track(self):
        kinds = [k for _, _, k in default_plan(32)]
        assert kinds == ["intro", "build", "drop", "outro"]
    def test_sections_contiguous(self):
        plan = default_plan(96)
        for (a1, b1, _), (a2, _, _) in zip(plan, plan[1:]):
            assert b1 == a2                                        # без дыр и нахлёстов
    def test_section_at(self):
        plan = default_plan(32)
        assert section_at(plan, 0) == "intro" and section_at(plan, 31) == "outro"


class TestDensity:
    def _hits(self, bars=32, bar_sec=2.0):
        h = []
        for b in range(bars):
            t = b * bar_sec
            h += [(t, "kick", 110), (t + bar_sec / 2, "snare", 90),
                  (t + bar_sec / 4, "closed_hat", 70), (t + bar_sec * 3 / 4, "closed_hat", 70)]
        return h

    def test_intro_drops_snare(self):
        plan = default_plan(32)
        out = apply_sections(self._hits(), 2.0, plan, seed=1, fills=False, ghosts=False)
        intro_end = plan[0][1] * 2.0
        assert not [h for h in out if h[0] < intro_end and h[1] == "snare"]
        assert [h for h in out if h[0] < intro_end and h[1] == "kick"]      # кик остаётся

    def test_breakdown_removes_kick(self):
        plan = [(0, 8, "drop"), (8, 16, "breakdown"), (16, 32, "drop")]
        out = apply_sections(self._hits(), 2.0, plan, seed=1, fills=False, ghosts=False)
        bd = [h for h in out if 16.0 <= h[0] < 32.0 and h[1] == "kick"]
        assert not bd                                                       # кик уходит

    def test_drop_keeps_everything(self):
        plan = [(0, 32, "drop")]
        out = apply_sections(self._hits(), 2.0, plan, seed=1, fills=False, ghosts=False)
        assert len(out) == len(self._hits())

    def test_deterministic(self):
        plan = default_plan(32)
        a = apply_sections(self._hits(), 2.0, plan, seed=5)
        b = apply_sections(self._hits(), 2.0, plan, seed=5)
        assert a == b


class TestFillsAndGhosts:
    def test_fill_before_section_change(self):
        plan = [(0, 8, "intro"), (8, 16, "drop")]
        hits = [(b * 2.0, "kick", 110) for b in range(16)]
        out = apply_sections(hits, 2.0, plan, seed=2, ghosts=False)
        last_intro_bar = [h for h in out if 14.0 <= h[0] < 16.0]
        assert any(h[1].startswith("tom") for h in last_intro_bar)          # филл по томам
    def test_make_fill_rises(self):
        f = make_fill(0.0, 2.0, seed=1, steps=8)
        assert len(f) == 8 and f[-1][2] > f[0][2]                           # velocity растёт
        assert all(0.0 <= t < 2.0 for t, _, _ in f)
    def test_ghosts_only_in_drop(self):
        plan = [(0, 8, "intro"), (8, 16, "drop")]
        hits = [(b * 2.0, "kick", 110) for b in range(16)]
        out = apply_sections(hits, 2.0, plan, seed=3, fills=False)
        ghosts = [h for h in out if h[1] == "snare" and h[2] < 40]
        assert ghosts and all(h[0] >= 16.0 for h in ghosts)


class TestLayerGain:
    def test_lead_silent_in_intro_full_in_drop(self):
        assert layer_section_gain("lead", "intro") == 0.0
        assert layer_section_gain("lead", "drop") == 1.0
    def test_pad_leads_breakdown(self):
        assert layer_section_gain("pad", "breakdown") > layer_section_gain("bass", "breakdown")
