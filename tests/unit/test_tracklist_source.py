"""P52: явный треклист (поиск/LLM) → кандидаты, метаданные едут с сидами (как Beatport)."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import tracklist_source as tl


class TestKeyToCamelot:
    def test_full_names(self):
        assert tl.key_to_camelot("E Major") == "12B"
        assert tl.key_to_camelot("F Minor") == "4A"
        assert tl.key_to_camelot("Ab Major") == "4B"
        assert tl.key_to_camelot("F# Minor") == "11A"
    def test_abbrev(self):
        assert tl.key_to_camelot("E maj") == "12B"
    def test_unknown_empty(self):
        assert tl.key_to_camelot("") == "" and tl.key_to_camelot("бред") == ""


class TestSeedsWithMeta:
    def test_camelot_and_bpm_ride(self):
        seeds, meta = tl.tracklist_to_seeds_with_meta(
            [{"artist": "A", "track": "x", "bpm": 126, "key": "E Major"}])
        assert seeds == ["A - x"]
        assert meta["A - x"]["camelot"] == "12B" and meta["A - x"]["bpm"] == 126
    def test_direct_camelot(self):
        _, meta = tl.tracklist_to_seeds_with_meta([{"artist": "A", "track": "x", "camelot": "10A"}])
        assert meta["A - x"]["camelot"] == "10A"
    def test_dedup_and_skip_empty(self):
        seeds, _ = tl.tracklist_to_seeds_with_meta(
            [{"artist": "A", "track": "x"}, {"artist": "A", "track": "x"}, {"artist": "", "track": "y"}])
        assert seeds == ["A - x"]


class TestLoad:
    def test_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump([{"artist": "A", "track": "x", "bpm": 120}], f); p = f.name
        e = tl.load_tracklist(p); os.unlink(p)
        assert e[0]["artist"] == "A" and e[0]["bpm"] == 120
    def test_text(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Sunny Lax - Endlessly\nEgera - Need Your Love\n"); p = f.name
        e = tl.load_tracklist(p); os.unlink(p)
        assert len(e) == 2 and e[0]["track"] == "Endlessly"
