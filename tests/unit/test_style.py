"""P90/P91: пространство стилей, гармонический ритм, вариативность паттернов. Офлайн."""
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from autodj.generate.style import (StyleSpec, TIMBRE_POLICY, blend, list_styles,
                                   load_style, resolve_timbres, sample_style,
                                   save_style, style_from_brief, validate)


class TestSpecValidation:
    def test_agent_garbage_is_repaired(self):
        s = StyleSpec.from_dict({"name": "x", "bpm_range": [400, 10], "energy": 5,
                                 "swing_range": [-1, 9], "character": "марсианский"})
        assert 50 <= s.bpm_range[0] <= s.bpm_range[1] <= 200
        assert 0.0 <= s.energy <= 1.0 and 0.0 <= s.swing_range[0] <= s.swing_range[1] <= 0.3
        assert s.character in TIMBRE_POLICY
    def test_unknown_keys_ignored(self):
        s = StyleSpec.from_dict({"name": "y", "нечто": 1, "bpm_range": [120, 126]})
        assert s.name == "y" and s.bpm_range == (120, 126)
    def test_empty_sets_get_defaults(self):
        s = validate(StyleSpec(name="z", keys=(), modes=(), progressions=()))
        assert s.keys and s.modes and s.progressions


class TestUniquenessPerRender:
    def test_params_sampled_not_fixed(self):
        s = StyleSpec(name="t", bpm_range=(118, 130), dur_range=(200, 400))
        outs = [sample_style(s, random.Random(i)) for i in range(8)]
        assert len({o["bpm"] for o in outs}) > 1
        assert len({o["key"] for o in outs}) > 1
    def test_same_seed_reproduces(self):
        s = StyleSpec(name="t")
        assert sample_style(s, random.Random(5)) == sample_style(s, random.Random(5))
    def test_sampled_within_declared_ranges(self):
        s = StyleSpec(name="t", bpm_range=(100, 104), swing_range=(0.0, 0.05))
        for i in range(20):
            o = sample_style(s, random.Random(i))
            assert 100 <= o["bpm"] <= 104 and 0.0 <= o["swing"] <= 0.05


class TestTimbrePolicy:
    def test_electronic_has_no_gm_presets(self):
        t = resolve_timbres(StyleSpec(name="e", character="electronic"))
        assert all(str(v).startswith("synth:") for v in t.values())
    def test_acoustic_keeps_real_instruments(self):
        t = resolve_timbres(StyleSpec(name="a", character="acoustic"))
        assert not str(t["lead"]).startswith("synth:")
    def test_overrides_win(self):
        t = resolve_timbres(StyleSpec(name="o", character="electronic",
                                      role_overrides={"accent": "tubular_bells"}))
        assert t["accent"] == "tubular_bells" and t["lead"].startswith("synth:")


class TestBlending:
    def test_blend_interpolates_and_unions(self):
        a = StyleSpec(name="afro", bpm_range=(118, 122), keys=("Am",), energy=0.4,
                      progressions=("plagal",))
        b = StyleSpec(name="dnb", bpm_range=(170, 176), keys=("Fm",), energy=0.9,
                      progressions=("breakbeat",))
        m = blend(a, b, 0.5)
        assert 118 < m.bpm_range[0] < 170
        assert set(m.keys) == {"Am", "Fm"} and 0.4 < m.energy < 0.9
        assert set(m.progressions) == {"plagal", "breakbeat"}
    def test_blend_endpoints(self):
        a, b = StyleSpec(name="a", bpm_range=(100, 100)), StyleSpec(name="b", bpm_range=(160, 160))
        assert blend(a, b, 0.0).bpm_range == (100, 100)
        assert blend(a, b, 1.0).bpm_range == (160, 160)
    def test_blend_is_valid_style(self):
        m = blend(StyleSpec(name="a"), StyleSpec(name="b"), 0.5)
        assert sample_style(m, random.Random(1))["bpm"] > 0


class TestStyleFiles:
    def test_roundtrip_json(self, tmp_path):
        s = StyleSpec(name="test_style", character="hybrid", bpm_range=(124, 128))
        p = save_style(s, str(tmp_path / "test_style.json"))
        loaded = StyleSpec.from_dict(json.load(open(p, encoding="utf-8")))
        assert loaded.name == s.name and loaded.bpm_range == s.bpm_range
    def test_new_style_needs_no_code(self):
        brief = {"name": "desert_breaks", "character": "hybrid", "bpm_range": [96, 104],
                 "progressions": ["plagal", "modal_interchange"], "energy": 0.55}
        params = sample_style(style_from_brief(brief), random.Random(0))
        assert 96 <= params["bpm"] <= 104 and params["inst_lead"]
    def test_shipped_styles_exist(self):
        assert len(list_styles()) >= 10
        assert isinstance(load_style(list_styles()[0]), StyleSpec)



class TestHarmonicRhythm:
    def test_chord_bars_sampled_per_track(self):
        s = StyleSpec(name="h", chord_bars_options=(1, 2, 4))
        vals = {sample_style(s, random.Random(i))["chord_bars"] for i in range(10)}
        assert len(vals) > 1                                  # гармония движется по-разному
    def test_drum_pattern_varies(self):
        s = StyleSpec(name="d", drum_patterns=("four_on_floor", "breakbeat", "halftime"))
        pats = {sample_style(s, random.Random(i))["drum_pattern"] for i in range(10)}
        assert len(pats) > 1                                  # не один паттерн на жанр
    def test_legacy_single_pattern_still_works(self):
        s = StyleSpec(name="l", drum_patterns=(), drum_pattern="four_on_floor")
        assert sample_style(s, random.Random(0))["drum_pattern"] == "four_on_floor"
    def test_shipped_styles_have_pools(self):
        for name in list_styles()[:5]:
            sp = load_style(name)
            assert len(sp.drum_patterns) >= 2 and len(sp.chord_bars_options) >= 2
