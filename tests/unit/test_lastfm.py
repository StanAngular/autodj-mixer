"""
Unit tests for lastfm.py pure functions (offline; no network, no API key).
Network wrapper get_similar_artists() is intentionally not unit-tested live —
it is thin and defensive; the parsing logic is what carries risk and is tested
here against fixture responses matching the Last.fm artist.getSimilar schema.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import lastfm


# Фикстура: нормальный ответ artist.getSimilar (несколько артистов)
FIXTURE_MULTI = {
    "similarartists": {
        "artist": [
            {"name": "Cassius",        "mbid": "x1", "match": "1.0",  "url": "u1"},
            {"name": "Stardust",       "mbid": "",   "match": "0.83", "url": "u2"},
            {"name": "Etienne de Crécy","mbid": "x3", "match": "0.61", "url": "u3"},
        ],
        "@attr": {"artist": "Daft Punk"},
    }
}

# Last.fm-причуда: единственный похожий артист приходит как dict, не list
FIXTURE_SINGLE = {"similarartists": {"artist":
    {"name": "Breakbot", "mbid": "y", "match": "0.7", "url": "u"}}}

FIXTURE_ERROR = {"error": 6, "message": "The artist you supplied could not be found"}
FIXTURE_EMPTY = {"similarartists": {"artist": []}}


class TestBuildUrl:
    def test_includes_required_params(self):
        url = lastfm._build_url("artist.getsimilar", {"artist": "X", "limit": 5}, "KEY123")
        assert "method=artist.getsimilar" in url
        assert "api_key=KEY123" in url
        assert "format=json" in url
        assert "artist=X" in url
        assert "limit=5" in url

    def test_url_encodes_spaces(self):
        url = lastfm._build_url("artist.getsimilar", {"artist": "Daft Punk"}, "K")
        assert "Daft+Punk" in url or "Daft%20Punk" in url


class TestParseSimilar:
    def test_parses_multiple_sorted(self):
        out = lastfm._parse_similar(FIXTURE_MULTI)
        assert [a["name"] for a in out] == ["Cassius", "Stardust", "Etienne de Crécy"]
        assert out[0]["match"] == 1.0
        assert out[1]["mbid"] == ""

    def test_single_artist_as_dict(self):
        out = lastfm._parse_similar(FIXTURE_SINGLE)
        assert len(out) == 1 and out[0]["name"] == "Breakbot"

    def test_error_response_returns_empty(self):
        assert lastfm._parse_similar(FIXTURE_ERROR) == []

    def test_empty_response(self):
        assert lastfm._parse_similar(FIXTURE_EMPTY) == []

    def test_garbage_input(self):
        assert lastfm._parse_similar(None) == []
        assert lastfm._parse_similar("nonsense") == []

    def test_bad_match_value_does_not_crash(self):
        data = {"similarartists": {"artist": [{"name": "A", "match": "not-a-number"}]}}
        out = lastfm._parse_similar(data)
        assert out[0]["match"] == 0.0


class TestGetSimilarDefensive:
    def test_no_key_returns_empty(self):
        assert lastfm.get_similar_artists("Daft Punk", api_key="") == []

    def test_empty_artist_returns_empty(self):
        assert lastfm.get_similar_artists("", api_key="KEY") == []
