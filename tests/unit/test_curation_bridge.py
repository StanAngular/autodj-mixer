"""Unit tests for curation_bridge.py (offline, pure functions)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import curation_bridge as cb


def _yt(v):
    return f"https://www.youtube.com/watch?v={v}"


class TestExtractVideoId:
    def test_watch_url(self):
        assert cb.extract_video_id(_yt("abcDEF12345")) == "abcDEF12345"

    def test_youtu_be(self):
        assert cb.extract_video_id("https://youtu.be/abcDEF12345") == "abcDEF12345"

    def test_soundcloud_empty(self):
        assert cb.extract_video_id("https://soundcloud.com/x/y") == ""

    def test_non_youtube(self):
        assert cb.extract_video_id("not a url") == ""


class TestUrlsAndEntries:
    def _cands(self):
        return [
            {"artist": "A", "track": "Intro", "youtube_url": _yt("aaaaaaaaaaa"), "segment": "intro"},
            {"artist": "B", "track": "Peak",  "youtube_url": _yt("bbbbbbbbbbb"), "segment": "peak"},
            {"artist": "C", "track": "Dup",   "youtube_url": _yt("aaaaaaaaaaa"), "segment": "peak"},  # дубль vid
            {"artist": "D", "track": "NoUrl", "youtube_url": ""},                                      # без url
        ]

    def test_urls_dedup_and_order(self):
        urls = cb.extract_urls(self._cands())
        assert len(urls) == 2                       # дубль и пустой отброшены
        assert "aaaaaaaaaaa" in urls[0]

    def test_entries_preserve_order_and_map_to_vid(self):
        e = cb.mix_config_entries(self._cands())
        assert e[0] == ("Intro", "aaaaaaaaaaa.wav", "aaaaaaaaaaa.txt")
        assert e[1] == ("Peak",  "bbbbbbbbbbb.wav", "bbbbbbbbbbb.txt")
        assert len(e) == 2

    def test_render_mix_config_valid_python(self):
        src = cb.render_mix_config(self._cands(), "/w", "/a")
        ns = {}
        exec(compile(src, "<gen>", "exec"), ns)     # должен исполняться как валидный модуль
        assert ns["WAV_DIR"] == "/w" and ns["ANN_DIR"] == "/a"
        assert ns["TRACKS"][0] == ("Intro", "aaaaaaaaaaa.wav", "aaaaaaaaaaa.txt")


class TestRecommendAnalysis:
    def test_multisegment_recommends_a1f(self):
        cands = [{"segment": "intro", "bpm": 120}, {"segment": "peak", "bpm": 122}]
        r = cb.recommend_analysis(cands)
        assert r["madmom"] is True and r["a1f"] is True
        assert "многосегмент" in r["reason"]

    def test_big_bpm_spread_recommends_a1f(self):
        cands = [{"segment": "s", "bpm": 90}, {"segment": "s", "bpm": 160}]
        assert cb.recommend_analysis(cands)["a1f"] is True

    def test_simple_set_madmom_enough(self):
        cands = [{"segment": "s", "bpm": 124}, {"segment": "s", "bpm": 126}]
        r = cb.recommend_analysis(cands)
        assert r["a1f"] is False and "не нужен" in r["reason"]

    def test_long_mix_recommends_a1f(self):
        cands = [{"segment": "s", "bpm": 124} for _ in range(12)]
        assert cb.recommend_analysis(cands)["a1f"] is True
