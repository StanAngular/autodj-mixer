"""
Unit tests for brief_parser.py pure functions (offline; no network/key).
parse_brief network wrapper is thin/defensive and not unit-tested live.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import brief_parser as bp


class TestBuildPrompt:
    def test_contains_contract_and_brief(self):
        p = bp.build_prompt("час эмбиента")
        assert '"segments"' in p and '"trajectory"' in p
        assert "underground" in p and "ramp" in p
        assert "час эмбиента" in p          # сам запрос вшит


class TestExtractJson:
    def test_bare_object(self):
        assert bp.extract_json('{"a": 1}') == {"a": 1}

    def test_with_code_fence(self):
        assert bp.extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_with_surrounding_prose(self):
        assert bp.extract_json('Вот конфиг:\n{"a": 1}\nГотово.') == {"a": 1}

    def test_invalid_returns_none(self):
        assert bp.extract_json("no json here") is None
        assert bp.extract_json("") is None
        assert bp.extract_json('{broken') is None


class TestApplyTextOverrides:
    def test_fast_word_sets_speed(self):
        cfg = {"speed": "thorough"}
        bp.apply_text_overrides(cfg, "сделай быстро пожалуйста")
        assert cfg["speed"] == "fast"

    def test_no_trigger_keeps_speed(self):
        cfg = {"speed": "thorough"}
        bp.apply_text_overrides(cfg, "час глубокого хауса")
        assert cfg["speed"] == "thorough"

    def test_english_fast(self):
        cfg = {"speed": "thorough"}
        bp.apply_text_overrides(cfg, "make it quick")
        assert cfg["speed"] == "fast"


class TestMissingFields:
    def test_no_segments_asks(self):
        qs = bp.missing_fields({"segments": []})
        assert qs and "стил" in qs[0].lower()

    def test_segment_without_style_or_seed(self):
        qs = bp.missing_fields({"segments": [{"name": "s", "count": 3}]})
        assert any("s" in q for q in qs)

    def test_complete_no_questions(self):
        cfg = {"segments": [{"name": "s", "styles": ["ambient"], "count": 3}],
               "duration_minutes": [60, 70]}
        assert bp.missing_fields(cfg) == []

    def test_no_duration_no_count_asks(self):
        cfg = {"segments": [{"name": "s", "styles": ["ambient"]}]}
        qs = bp.missing_fields(cfg)
        assert any("длительность" in q.lower() or "треков" in q.lower() for q in qs)


class TestParseBriefDefensive:
    def test_no_key(self):
        res = bp.parse_brief("час эмбиента", api_key="")
        assert res["error"] and res["config"] is None

    def test_empty_brief(self):
        res = bp.parse_brief("", api_key="KEY")
        assert res["error"]
