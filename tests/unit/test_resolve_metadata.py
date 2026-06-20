"""Unit tests for resolve_metadata.py pure cores (P33, offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import resolve_metadata as rm


class TestNeedsResolution:
    def test(self):
        assert rm.needs_resolution({"camelot": ""}) is True
        assert rm.needs_resolution({"camelot": "8A"}) is False


class TestFromCatalog:
    def _index(self):
        return {"tracks": {"abcdefghijk": {"camelot": "8A", "bpm": 124}}}
    def test_hit_fills(self):
        t = {"youtube_url": "https://youtu.be/abcdefghijk", "camelot": ""}
        assert rm.from_catalog(t, self._index()) is True
        assert t["camelot"] == "8A" and t["bpm"] == 124 and t["camelot_source"] == "catalog"
    def test_miss(self):
        t = {"youtube_url": "https://youtu.be/zzzzzzzzzzz", "camelot": ""}
        assert rm.from_catalog(t, self._index()) is False
    def test_entry_without_camelot(self):
        idx = {"tracks": {"abcdefghijk": {"bpm": 124}}}
        t = {"youtube_url": "https://youtu.be/abcdefghijk", "camelot": ""}
        assert rm.from_catalog(t, idx) is False


class TestFromCache:
    def test_hit(self):
        import enrich_cache as ec
        cache = {}
        ec.cache_put(cache, "ANOTR", "Talk To You", 126, "9A")
        t = {"artist": "ANOTR", "track": "Talk To You", "camelot": ""}
        assert rm.from_cache(t, cache) is True
        assert t["camelot"] == "9A" and t["camelot_source"] == "cache"
    def test_miss(self):
        assert rm.from_cache({"artist": "X", "track": "Y", "camelot": ""}, {}) is False


class TestResolveCascadeOrder:
    def test_catalog_then_cache_then_residual(self, tmp_path, monkeypatch):
        import enrich_cache as ec
        cache_path = tmp_path / "cache.json"
        cache = {}
        ec.cache_put(cache, "B", "b", 120, "5A")
        ec.save_cache(cache, str(cache_path))
        monkeypatch.setattr(rm, "video_id", lambda u: u)  # url == id для теста
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        catdir = os.path.join(root, "shared", "catalog")
        sys.path.insert(0, catdir)
        import catalog_utils as cu
        monkeypatch.setattr(cu, "load_index", lambda: {"tracks": {"a": {"camelot": "8A"}}})
        cands = [
            {"youtube_url": "a", "artist": "A", "track": "a", "camelot": ""},   # каталог
            {"youtube_url": "z", "artist": "B", "track": "b", "camelot": ""},   # кэш
            {"youtube_url": "q", "artist": "C", "track": "c", "camelot": ""},   # остаток
        ]
        _, st = rm.resolve_candidates(cands, catdir, str(cache_path), use_tunebat=False)
        assert st["catalog"] == 1 and st["cache"] == 1 and st["residual"] == 1
        assert cands[0]["camelot"] == "8A" and cands[1]["camelot"] == "5A"
