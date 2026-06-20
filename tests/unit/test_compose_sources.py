"""P42: композитный фоллбэк источников (Beatport → YouTube/last.fm), дедуп-слияние."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import compose_sources as cs


def _c(vid, artist="A", track="t", **kw):
    return {"youtube_url": f"https://youtu.be/{vid}", "artist": artist, "track": track, **kw}


class TestMergeCandidates:
    def test_dedup_by_video_id_priority_first(self):
        pools = [[_c("aaaaaaaaaaa", camelot="8A")], [_c("aaaaaaaaaaa", track="dup"), _c("bbbbbbbbbbb")]]
        out = cs.merge_candidates(pools)
        assert [c["youtube_url"][-11:] for c in out] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
        assert out[0].get("camelot") == "8A"            # выиграл первый пул (Beatport)
    def test_cap_at_target(self):
        pools = [[_c("aaaaaaaaaaa"), _c("bbbbbbbbbbb"), _c("ccccccccccc")]]
        assert len(cs.merge_candidates(pools, target=2)) == 2
    def test_fallback_to_artist_track_key(self):
        pools = [[{"artist": "A", "track": "x"}], [{"artist": "A", "track": "x"}]]  # нет vid
        assert len(cs.merge_candidates(pools)) == 1     # дедуп по artist|track
    def test_skips_empty(self):
        pools = [[{"artist": "", "track": ""}]]
        assert cs.merge_candidates(pools) == []


class TestSourceAutoPlan:
    def test_auto_uses_compose_stage(self):
        import orchestrate as orch
        st = [s for s, _ in orch.build_plan("x", style="trance", source="auto")]
        assert "compose" in st and "seedlist" not in st and "beatport" not in st
        assert "resolve" in st and "prescreen" in st


class TestDataRichnessChain:
    def _mocks(self, monkeypatch, bp_n, bc_n, yt_n):
        import beatport_source as bps, build_seedlist as bsl, seed_discover as sd
        import curate_tracks as ct
        monkeypatch.setattr(bps, "beatport_candidates",
            lambda *a, **k: [{"youtube_url": f"bp{i}", "artist": "B", "track": f"t{i}"} for i in range(bp_n)])
        monkeypatch.setattr(ct, "fetch_bandcamp_underground",
            lambda *a, **k: [{"artist": "C", "track": f"bc{i}"} for i in range(bc_n)])
        calls = {"bandcamp": 0, "lastfm": 0}
        def fake_sd(seeds, **k):
            if seeds and seeds[0].startswith("C - "):
                calls["bandcamp"] += 1
                return [{"youtube_url": f"bc{i}", "artist": "C", "track": f"bc{i}"} for i in range(bc_n)]
            calls["lastfm"] += 1
            return [{"youtube_url": f"yt{i}", "artist": "Y", "track": f"y{i}"} for i in range(yt_n)]
        monkeypatch.setattr(sd, "seed_discover", fake_sd)
        monkeypatch.setattr(bsl, "build_seedlist", lambda **k: {"seeds": ["Y - y0"]})
        return calls

    def test_beatport_covers_no_fallback(self, monkeypatch):
        import compose_sources as cs
        calls = self._mocks(monkeypatch, 16, 5, 5)
        out = cs.compose(style="deep trance", target=16)
        assert len(out) == 16 and calls["bandcamp"] == 0 and calls["lastfm"] == 0

    def test_falls_bandcamp_then_lastfm(self, monkeypatch):
        import compose_sources as cs
        calls = self._mocks(monkeypatch, 4, 4, 20)
        out = cs.compose(style="deep trance", target=16)
        assert calls["bandcamp"] == 1 and calls["lastfm"] == 1 and len(out) == 16
