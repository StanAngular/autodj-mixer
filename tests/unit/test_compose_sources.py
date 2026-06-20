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
