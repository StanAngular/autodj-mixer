"""Unit tests for enrich_cache.py (offline, tmp-file backed)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import enrich_cache as ec


class TestKey:
    def test_mirrors_dedup_key(self):
        assert ec.cache_key("  Daft Punk ", "Da Funk") == "daft punk|da funk"

    def test_handles_none(self):
        assert ec.cache_key(None, None) == "|"


class TestPutGet:
    def test_put_complete_only(self):
        c = {}
        assert ec.cache_put(c, "A", "1", 124, "8A") is True
        assert ec.cache_put(c, "B", "2", 0, "8A") is False    # нет bpm
        assert ec.cache_put(c, "C", "3", 124, "") is False    # нет camelot
        assert len(c) == 1

    def test_get(self):
        c = {}
        ec.cache_put(c, "A", "1", 124, "8A")
        assert ec.cache_get(c, "a", "1") == {"bpm": 124, "camelot": "8A"}
        assert ec.cache_get(c, "X", "Y") is None


class TestSplit:
    def test_hits_and_misses(self):
        cache = {}
        ec.cache_put(cache, "A", "1", 124, "8A")
        tracks = [
            {"artist": "A", "track": "1"},   # в кэше
            {"artist": "B", "track": "2"},   # нет
        ]
        hits, misses = ec.split_by_cache(tracks, cache)
        assert len(hits) == 1 and hits[0][1] == 124 and hits[0][2] == "8A"
        assert len(misses) == 1 and misses[0]["artist"] == "B"


class TestRoundTrip:
    def test_save_load(self, tmp_path):
        p = str(tmp_path / "ec.json")
        c = {}
        ec.cache_put(c, "A", "1", 124, "8A")
        assert ec.save_cache(c, p) is True
        loaded = ec.load_cache(p)
        assert loaded == c

    def test_missing_file_empty(self, tmp_path):
        assert ec.load_cache(str(tmp_path / "nope.json")) == {}
