"""Unit tests for build_seedlist.py pure cores (P28, offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import build_seedlist as bs


class TestDedupKeepOrder:
    def test_case_insensitive_order(self):
        assert bs.dedup_keep_order(["FKJ", "fkj", "Zimmer", "  ", "FKJ"]) == ["FKJ", "Zimmer"]
    def test_empty(self):
        assert bs.dedup_keep_order([]) == []


class TestTracksToSeeds:
    def test_artist_track_strings(self):
        td = [{"artist": "FKJ", "track": "Tadow"}, {"artist": "Polo & Pan", "track": "Nana"}]
        assert bs.tracks_to_seeds(td) == ["FKJ - Tadow", "Polo & Pan - Nana"]
    def test_skips_empty_and_dedups(self):
        td = [{"artist": "", "track": ""}, {"artist": "A", "track": "x"},
              {"artist": "A", "track": "x"}]
        assert bs.tracks_to_seeds(td) == ["A - x"]
    def test_track_only(self):
        assert bs.tracks_to_seeds([{"track": "Solo"}]) == ["Solo"]


# ── P32: жёсткий кап на размер пула ─────────────────────────────────────────

class TestSeedLimit:
    def test_limit_caps_output(self, monkeypatch):
        import lastfm
        monkeypatch.setattr(lastfm, "get_similar_artists", lambda a, n=5, k="": [{"name": a+f"_s{i}"} for i in range(n)])
        monkeypatch.setattr(lastfm, "get_tag_top_artists", lambda t, n=5, k="": [{"name": f"tag{i}"} for i in range(n)])
        monkeypatch.setattr(lastfm, "get_artist_top_tracks", lambda a, n=2, k="": [{"artist": a, "track": f"T{i}"} for i in range(n)])
        res = bs.build_seedlist(seed_artists=["A", "B", "C"], tag="tech house", limit=10)
        assert len(res["seeds"]) == 10                   # жёстко обрезано до 10
        assert res["sources"]["before_limit"] > 10       # до капа было больше
