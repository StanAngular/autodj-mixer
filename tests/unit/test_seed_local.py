"""Unit tests for Path B: seed_discover + local_enrich pure cores (offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import seed_discover as sd
import local_enrich as le


class TestBuildSeedQueries:
    def test_artist_gets_style(self):
        assert sd.build_seed_queries(["FKJ"], ["organic house"]) == ["FKJ organic house"]
    def test_artist_track_kept_as_is(self):
        assert sd.build_seed_queries(["Polo & Pan - Nanã"], ["x"]) == ["Polo & Pan - Nanã"]
    def test_skips_empty(self):
        assert sd.build_seed_queries(["", "  ", "Zimmer"], None) == ["Zimmer"]


class TestParseYtdlpSearch:
    def test_builds_candidates(self):
        data = {"entries": [
            {"id": "abcdefghijk", "title": "FKJ - Ylang Ylang", "uploader": "FKJ",
             "duration": 240, "view_count": 1000000, "url": "https://youtu.be/abcdefghijk"},
            None,                                   # битую запись пропускаем
            {"id": "", "title": "no id"},           # без id пропускаем
        ]}
        out = sd.parse_ytdlp_search(data, seed_artist="FKJ", country="FR")
        assert len(out) == 1
        c = out[0]
        assert c["artist"] == "FKJ" and c["video_id"] == "abcdefghijk"
        assert c["country"] == "FR" and c["source"] == "seed"
        assert c["camelot"] == "" and c["camelot_source"] == "pending_local"

    def test_empty(self):
        assert sd.parse_ytdlp_search({}) == []


class TestNeedsLocalKey:
    def test_missing_camelot(self):
        assert le.needs_local_key({"camelot": ""}) is True
        assert le.needs_local_key({}) is True
    def test_has_camelot(self):
        assert le.needs_local_key({"camelot": "8A"}) is False


class TestVideoId:
    def test_forms(self):
        assert le.video_id("https://youtu.be/abcdefghijk") == "abcdefghijk"
        assert le.video_id("https://www.youtube.com/watch?v=abcdefghijk") == "abcdefghijk"
        assert le.video_id("") == ""
