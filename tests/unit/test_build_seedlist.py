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
