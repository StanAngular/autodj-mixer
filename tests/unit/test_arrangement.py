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


class TestSectionEnvelope:
    def _plan(self):
        return [(0, 8, "intro"), (8, 16, "drop"), (16, 24, "breakdown"), (24, 32, "drop")]

    def test_lead_silent_in_intro_full_in_drop(self):
        from autodj.generate.arrangement import section_gain_envelope
        import numpy as np
        sr, bar_sec = 100, 1.0                        # компактно: 1 бар = 100 сэмплов
        env = section_gain_envelope("lead", self._plan(), bar_sec, 3200, sr)
        assert env[300] < 0.15                        # интро — лида нет
        assert env[1200] > 0.9                        # дроп — лид на месте

    def test_bass_dips_in_breakdown(self):
        from autodj.generate.arrangement import section_gain_envelope
        sr = 100
        env = section_gain_envelope("bass", self._plan(), 1.0, 3200, sr)
        assert env[2000] < env[1200]                  # брейкдаун тише дропа

    def test_pad_leads_breakdown(self):
        from autodj.generate.arrangement import section_gain_envelope
        sr = 100
        pad = section_gain_envelope("pad", self._plan(), 1.0, 3200, sr)
        bass = section_gain_envelope("bass", self._plan(), 1.0, 3200, sr)
        assert pad[2000] > bass[2000]                 # в брейкдауне пад впереди

    def test_smooth_no_clicks(self):
        from autodj.generate.arrangement import section_gain_envelope
        import numpy as np
        env = section_gain_envelope("lead", self._plan(), 1.0, 3200, 100, smooth_ms=200)
        assert np.abs(np.diff(env)).max() < 0.25      # стыки сглажены

    def test_length_and_no_plan(self):
        from autodj.generate.arrangement import section_gain_envelope
        import numpy as np
        assert len(section_gain_envelope("lead", self._plan(), 1.0, 500, 100)) == 500
        assert np.all(section_gain_envelope("lead", [], 1.0, 500, 100) == 1.0)


# ═══ P92: иерархия слоёв, паузы, чередование, баланс барабанов ═══

class TestActivationMatrix:
    def test_pad_silent_in_drop(self):
        from autodj.generate.arrangement import active_roles
        assert active_roles("drop")["pad"] == 0.0          # «гудящий фон» убран из дропа
    def test_drums_silent_in_breakdown(self):
        from autodj.generate.arrangement import active_roles
        assert active_roles("breakdown")["drums"] == 0.0   # брейкдаун без барабанов
    def test_lead_absent_until_drop(self):
        from autodj.generate.arrangement import active_roles
        assert active_roles("intro")["lead"] == 0.0
        assert active_roles("build")["lead"] == 0.0
        assert active_roles("drop")["lead"] > 0.9          # лид входит только в дропе
    def test_max_voices_enforced(self):
        from autodj.generate.arrangement import active_roles, MELODIC
        for kind in ("intro", "build", "drop", "breakdown", "outro"):
            on = [r for r in MELODIC if active_roles(kind, max_voices=3).get(r, 0) > 0]
            assert len(on) <= 3, f"{kind}: {on}"           # не 6 слоёв разом
    def test_focus_is_loudest_melodic(self):
        from autodj.generate.arrangement import active_roles, FOCUS, MELODIC
        for kind in ("drop", "breakdown"):
            lv = active_roles(kind)
            focus = FOCUS[kind]
            others = [v for r, v in lv.items() if r in MELODIC and r != focus and v > 0]
            assert all(lv[focus] >= o for o in others)     # фокус ведёт


class TestTurnTaking:
    def test_secondary_roles_alternate(self):
        from autodj.generate.arrangement import turn_window, SECONDARY
        active_per_window = [
            [r for r in SECONDARY if turn_window(r, bar) > 0] for bar in (0, 8, 16, 24)
        ]
        assert all(len(a) == 1 for a in active_per_window)  # играет ОДИН, не все
        assert len({tuple(a) for a in active_per_window}) > 1  # и они сменяются
    def test_primary_roles_unaffected(self):
        from autodj.generate.arrangement import turn_window
        assert turn_window("lead", 0) == 1.0 and turn_window("drums", 8) == 1.0


class TestActivationEnvelope:
    def test_real_silence_not_just_quieter(self):
        import numpy as np
        from autodj.generate.arrangement import activation_envelope
        plan = [(0, 8, "drop")]
        env = activation_envelope("pad", plan, 1.0, 8 * 100, 100, turn_taking=False)
        assert float(np.abs(env).max()) < 0.05            # пад реально молчит
    def test_focus_louder_than_support(self):
        import numpy as np
        from autodj.generate.arrangement import activation_envelope
        plan = [(0, 8, "drop")]
        lead = activation_envelope("lead", plan, 1.0, 800, 100, turn_taking=False)
        arp = activation_envelope("arp", plan, 1.0, 800, 100, turn_taking=False)
        assert lead[400] > arp[400]


class TestDrumBalance:
    def test_kick_forward_cymbals_back(self):
        from autodj.generate.arrangement import balance_drums
        out = dict((n, v) for _, n, v in balance_drums(
            [(0.0, "kick", 100), (0.5, "closed_hat", 100), (1.0, "ride", 100)]))
        assert out["kick"] > 100 and out["closed_hat"] < 60 and out["ride"] < 45
    def test_velocity_clamped(self):
        from autodj.generate.arrangement import balance_drums
        assert all(1 <= v <= 127 for _, _, v in balance_drums([(0.0, "kick", 127)]))
    def test_unknown_drum_untouched(self):
        from autodj.generate.arrangement import balance_drums
        assert balance_drums([(0.0, "shaker", 80)])[0][2] == 80
