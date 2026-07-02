"""P45: поиск ремиксов в seed_discover (чистые функции)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import seed_discover as sd


# ── P45: поиск ремиксов (для «похожие на X → танцевальные ремиксы») ─────────

class TestRemixSeeking:
    def test_is_remix(self):
        assert sd.is_remix("Born To Die (ARTBAT Remix)") is True
        assert sd.is_remix("Some Track (Extended Mix)") is False
        assert sd.is_remix("Video Games") is False
        assert sd.is_remix("Track (Bootleg)") is True

    def test_queries_append_remix(self):
        q = sd.build_seed_queries(["Lana Del Rey - Video Games"], remix=True)
        assert q == ["Lana Del Rey - Video Games remix"]
        q2 = sd.build_seed_queries(["Lana Del Rey - Video Games"], remix=False)
        assert q2 == ["Lana Del Rey - Video Games"]

    def test_score_bonus_for_remix(self):
        rem = {"track": "Video Games (ARTBAT Remix)", "views": 1000}
        orig = {"track": "Video Games", "views": 1000}
        assert sd.candidate_score(rem, "Lana Del Rey", "Video Games", prefer_remix=True) > \
               sd.candidate_score(orig, "Lana Del Rey", "Video Games", prefer_remix=True)

    def test_require_remix_drops_originals(self):
        cands = [
            {"track": "Lana Del Rey - Video Games", "views": 9999, "duration": 240},
            {"track": "Lana Del Rey - Video Games (ARTBAT Remix)", "views": 100, "duration": 300},
        ]
        best = sd.pick_best(cands, "Lana Del Rey", "Video Games",
                            require_identity=False, require_remix=True)
        assert best is not None and sd.is_remix(best["track"])   # выбран ремикс, не оригинал


class TestSoundCloudDiscovery:
    def test_parse_soundcloud_entry(self):
        data = {"entries": [{"id": "12345", "title": "Deep Cut", "uploader": "Obscure Artist",
                             "url": "https://soundcloud.com/obscure/deep-cut", "view_count": 500}]}
        cands = sd.parse_ytdlp_search(data, seed_artist="Obscure Artist", platform="soundcloud")
        assert len(cands) == 1
        assert cands[0]["youtube_url"] == "https://soundcloud.com/obscure/deep-cut"
        assert cands[0]["platform"] == "soundcloud"
        assert cands[0]["camelot_source"] == "pending_local"   # BPM/Camelot из аудио

    def test_soundcloud_entry_without_url_skipped(self):
        data = {"entries": [{"id": "x", "title": "T"}]}      # нет url → нечего качать
        assert sd.parse_ytdlp_search(data, platform="soundcloud") == []

    def test_youtube_keeps_fallback_url(self):
        data = {"entries": [{"id": "abc123", "title": "T", "uploader": "A"}]}  # без url
        cands = sd.parse_ytdlp_search(data, platform="youtube")
        assert cands[0]["youtube_url"] == "https://youtu.be/abc123"            # YT-фоллбэк цел
        assert cands[0]["platform"] == "youtube"

    def test_sc_fallback_when_youtube_empty(self, monkeypatch):
        # YouTube пусто → SoundCloud находит
        def fake_search(query, per, prefix, sa, country, platform="youtube"):
            if prefix == "scsearch":
                return [{"artist": sa, "track": "Deep Cut", "video_id": "1", "views": 100,
                         "youtube_url": "https://soundcloud.com/a/deep-cut", "platform": "soundcloud"}]
            return []
        monkeypatch.setattr(sd, "_ytdlp_search", fake_search)
        monkeypatch.setattr(sd, "pick_best", lambda c, *a, **k: c[0] if c else None)
        out = sd.seed_discover(["Obscure Artist - Deep Cut"], verify=False)
        assert len(out) == 1 and out[0]["platform"] == "soundcloud"
