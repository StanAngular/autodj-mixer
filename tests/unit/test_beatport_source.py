"""P38: Beatport как источник сидов с метаданными в общей воронке."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import beatport_source as bp
import seed_discover as sd


class TestTracksToSeedsWithMeta:
    def test_builds_seeds_and_meta(self):
        tracks = [
            {"artist": "Tale Of Us", "track": "Nova", "bpm": 124, "camelot": "8A", "support_score": 10},
            {"artist": "Mind Against", "track": "Walk", "bpm": 122, "camelot": "5A"},
        ]
        seeds, meta = bp.tracks_to_seeds_with_meta(tracks)
        assert seeds == ["Tale Of Us - Nova", "Mind Against - Walk"]
        assert meta["Tale Of Us - Nova"] == {"source_type": "beatport", "camelot": "8A",
                                             "bpm": 124, "support_score": 10}
    def test_skips_empty_and_dedups(self):
        tracks = [{"artist": "", "track": "x"}, {"artist": "A", "track": "b", "camelot": "1A"},
                  {"artist": "A", "track": "b", "camelot": "1A"}]
        seeds, meta = bp.tracks_to_seeds_with_meta(tracks)
        assert seeds == ["A - b"]


class TestMergeSeedMeta:
    def test_merges_metadata_not_identity(self):
        cand = {"track": "Tale Of Us - Nova (Official)", "youtube_url": "u", "views": 5}
        sd.merge_seed_meta(cand, {"camelot": "8A", "bpm": 124, "source_type": "beatport"})
        assert cand["camelot"] == "8A" and cand["bpm"] == 124
        assert cand["track"] == "Tale Of Us - Nova (Official)"  # личность не затёрта
    def test_skips_empty_values(self):
        cand = {"bpm": 126}
        sd.merge_seed_meta(cand, {"camelot": "", "bpm": 0})
        assert "camelot" not in cand and cand["bpm"] == 126
    def test_no_meta(self):
        cand = {"track": "x"}
        assert sd.merge_seed_meta(cand, {}) == {"track": "x"}


# ── P39: гейты Mix Name (Radio Edit) + год + перенос полей ─────────────────

class TestMixNameGate:
    def test_radio_edit_rejected(self):
        assert bp.mix_name_ok("Radio Edit") is False
        assert bp.mix_name_ok("Radio Mix") is False
    def test_extended_original_ok(self):
        assert bp.mix_name_ok("Extended Mix") is True
        assert bp.mix_name_ok("Original Mix") is True
        assert bp.mix_name_ok("") is True

class TestReleaseYear:
    def test_parses(self):
        assert bp.release_year("2026-03-14") == 2026
    def test_bad(self):
        assert bp.release_year("") == 0 and bp.release_year("n/a") == 0

class TestGatesInSeeds:
    def test_drops_radio_edit_and_offyear(self):
        tracks = [
            {"artist": "A", "track": "Good", "mix_name": "Extended Mix",
             "release_date": "2026-01-01", "camelot": "8A", "bpm": 124, "label": "No Art"},
            {"artist": "B", "track": "Radio", "mix_name": "Radio Edit",
             "release_date": "2026-01-01"},                       # Radio Edit → отсев
            {"artist": "C", "track": "Old", "mix_name": "Original Mix",
             "release_date": "2019-05-05"},                       # вне года → отсев
        ]
        seeds, meta = bp.tracks_to_seeds_with_meta(tracks, year_lo=2026, year_hi=2026)
        assert seeds == ["A - Good"]
        assert meta["A - Good"]["year"] == 2026 and meta["A - Good"]["label"] == "No Art"
        assert meta["A - Good"]["mix_name"] == "Extended Mix"
    def test_unknown_year_kept(self):
        tracks = [{"artist": "A", "track": "x", "mix_name": "", "release_date": ""}]
        seeds, _ = bp.tracks_to_seeds_with_meta(tracks, year_lo=2026, year_hi=2026)
        assert seeds == ["A - x"]                                  # год неизвестен → не режем


# ── P43: сортировка пула по намерению (newest / bestsellers) ──────────────

class TestSortBeatportTracks:
    def test_newest_by_release_date(self):
        tracks = [{"track": "old", "release_date": "2024-01-01"},
                  {"track": "new", "release_date": "2026-05-01"},
                  {"track": "mid", "release_date": "2025-03-01"}]
        out = bp.sort_beatport_tracks(tracks, "newest")
        assert [t["track"] for t in out] == ["new", "mid", "old"]
    def test_bestsellers_by_support(self):
        tracks = [{"track": "a", "support_score": 3},
                  {"track": "b", "support_score": 10},
                  {"track": "c", "support_score": 7}]
        out = bp.sort_beatport_tracks(tracks, "bestsellers")
        assert [t["track"] for t in out] == ["b", "c", "a"]
    def test_empty_keeps_order(self):
        tracks = [{"track": "a"}, {"track": "b"}]
        assert [t["track"] for t in bp.sort_beatport_tracks(tracks, "")] == ["a", "b"]
    def test_unknown_dates_last(self):
        tracks = [{"track": "x", "release_date": ""}, {"track": "y", "release_date": "2026-01-01"}]
        assert [t["track"] for t in bp.sort_beatport_tracks(tracks, "newest")] == ["y", "x"]
