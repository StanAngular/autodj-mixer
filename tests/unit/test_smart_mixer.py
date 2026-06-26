"""Тесты smart_mixer (пока точечно). resolve_camelot: curated primary, detect fallback."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import smart_mixer as m


class TestResolveCamelot:
    def test_curated_wins(self):
        assert m.resolve_camelot("8A", "5A") == "8A"        # курированный primary
    def test_empty_curated_falls_to_detected(self):
        assert m.resolve_camelot("", "5A") == "5A"
        assert m.resolve_camelot(None, "5A") == "5A"
    def test_unknown_curated_falls_to_detected(self):
        assert m.resolve_camelot("?", "5A") == "5A"         # '?' не валиден
    def test_whitespace_curated_falls_to_detected(self):
        assert m.resolve_camelot("  ", "5A") == "5A"
