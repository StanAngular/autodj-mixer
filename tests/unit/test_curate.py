"""
Unit tests for curate_tracks.py pure functions (no network).

Covers the P1 provenance layer (set_field / tag_src / merge_provenance /
dedup_key) plus the existing Camelot math and text helpers. Heavy/network deps
are mocked so the suite runs in CI without an audio or scraping stack.
"""
import sys, os
from unittest.mock import MagicMock

for _m in ("requests", "bs4", "dotenv"):
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import curate_tracks as ct


# ── Camelot compatibility math ─────────────────────────────────────────────

class TestCompatibleKeys:
    def test_8A(self):
        assert ct.get_compatible_keys("8A") == {"8A", "7A", "9A", "8B", "7B"}

    def test_wrap_low(self):
        # 1A neighbours wrap to 12A; relative 1B; diagonal 12B
        assert ct.get_compatible_keys("1A") == {"1A", "12A", "2A", "1B", "12B"}

    def test_wrap_high(self):
        assert ct.get_compatible_keys("12B") == {"12B", "11B", "1B", "12A", "11A"}

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            ct.get_compatible_keys("99Z")


class TestCamelotRelation:
    def test_exact(self):
        assert ct.camelot_relation("8A", "8A") == "exact match"

    def test_neighbour(self):
        assert ct.camelot_relation("8A", "9A") == "wheel neighbour"

    def test_neighbour_wrap(self):
        assert ct.camelot_relation("12A", "1A") == "wheel neighbour"

    def test_major_minor_swap(self):
        assert ct.camelot_relation("8A", "8B") == "major/minor swap"

    def test_diagonal(self):
        assert ct.camelot_relation("8A", "7B") == "diagonal energy boost"


# ── Text normalisation + dedup ─────────────────────────────────────────────

class TestNormalize:
    def test_strips_noise_and_punct(self):
        out = ct.normalize_text("Artist - Track (Official Video)!!!")
        assert "official" not in out
        assert "video" not in out
        assert out == out.lower()

    def test_dedup_key_case_insensitive(self):
        assert ct.dedup_key("  Daft Punk ", "One More Time") == \
               ct.dedup_key("daft punk", "one more time")


# ── P1: provenance ─────────────────────────────────────────────────────────

class TestSetField:
    def test_fills_empty(self):
        t = {"bpm": 0}
        ct.set_field(t, "bpm", 124, "Beatport")
        assert t["bpm"] == 124 and t["bpm_src"] == "Beatport"

    def test_ignores_empty_value(self):
        t = {"bpm": 0}
        ct.set_field(t, "bpm", 0, "Beatport")
        assert t["bpm"] == 0 and "bpm_src" not in t

    def test_lower_priority_does_not_overwrite(self):
        t = {}
        ct.set_field(t, "bpm", 124, "Beatport")          # prio 50
        ct.set_field(t, "bpm", 99, "YouTube-desc")       # prio 20
        assert t["bpm"] == 124 and t["bpm_src"] == "Beatport"

    def test_higher_priority_overwrites(self):
        t = {}
        ct.set_field(t, "camelot", "5A", "YouTube-desc")  # prio 20
        ct.set_field(t, "camelot", "8A", "user")          # prio 100
        assert t["camelot"] == "8A" and t["camelot_src"] == "user"

    def test_tie_keeps_first(self):
        t = {}
        ct.set_field(t, "bpm", 120, "Beatport")
        ct.set_field(t, "bpm", 128, "Tunebat")            # equal prio
        assert t["bpm"] == 120 and t["bpm_src"] == "Beatport"


class TestTagSrc:
    def test_stamps_populated_fields(self):
        tracks = [{"artist": "A", "track": "T", "bpm": 124, "camelot": ""}]
        ct.tag_src(tracks, "Beatport")
        t = tracks[0]
        assert t["bpm_src"] == "Beatport"
        assert "camelot_src" not in t          # empty field not stamped
        assert t["found_in"] == ["Beatport"]

    def test_found_in_no_duplicates(self):
        tracks = [{"artist": "A", "track": "T", "bpm": 0}]
        ct.tag_src(tracks, "Discogs")
        ct.tag_src(tracks, "Discogs")
        assert tracks[0]["found_in"] == ["Discogs"]

    def test_does_not_clobber_existing_src(self):
        tracks = [{"artist": "A", "track": "T", "bpm": 124, "bpm_src": "Tunebat"}]
        ct.tag_src(tracks, "Beatport")
        assert tracks[0]["bpm_src"] == "Tunebat"


class TestMergeProvenance:
    def test_merges_found_in_and_fills_fields(self):
        kept = {"artist": "A", "track": "T", "bpm": 0, "camelot": "",
                "country": "", "found_in": ["Discogs"]}
        dup = {"artist": "A", "track": "T", "bpm": 124, "bpm_src": "Beatport",
               "camelot": "", "country": "FR", "country_src": "Discogs",
               "found_in": ["Beatport"]}
        ct.merge_provenance(kept, dup)
        assert set(kept["found_in"]) == {"Discogs", "Beatport"}
        assert kept["bpm"] == 124 and kept["bpm_src"] == "Beatport"
        assert kept["country"] == "FR" and kept["country_src"] == "Discogs"


# ── P3: approval table formatting ──────────────────────────────────────────

class TestFormatting:
    def test_fmt_duration(self):
        assert ct.fmt_duration(372) == "6:12"
        assert ct.fmt_duration(60) == "1:00"
        assert ct.fmt_duration(0) == "?"

    def test_fmt_views(self):
        assert ct.fmt_views(1_200_000) == "1.2M"
        assert ct.fmt_views(12_000) == "12K"
        assert ct.fmt_views(850) == "850"
        assert ct.fmt_views(0) == "—"

    def test_fmt_field_with_src(self):
        t = {"bpm": 124, "bpm_src": "Beatport"}
        assert ct.fmt_field(t, "bpm", " BPM") == "124 BPM (Beatport)"

    def test_fmt_field_empty(self):
        assert ct.fmt_field({}, "camelot") == "?"

    def test_fmt_field_no_src(self):
        assert ct.fmt_field({"bpm": 124}, "bpm", " BPM") == "124 BPM"


class TestApprovalTable:
    def _track(self):
        return {
            "artist": "Daft Punk", "track": "One More Time",
            "bpm": 123, "bpm_src": "Beatport",
            "camelot": "7A", "camelot_src": "Tunebat",
            "country": "FR", "country_src": "Discogs",
            "style": "French House",
            "duration_sec": 320, "youtube_views": 1_200_000,
            "youtube_url": "https://youtu.be/abc", "youtube_status": "verified",
        }

    def test_contains_link_and_sources(self):
        out = ct.format_approval_table([self._track()], target_camelot="7A")
        assert "https://youtu.be/abc" in out      # ссылка
        assert "(Beatport)" in out                # провенанс BPM
        assert "(Tunebat)" in out                 # провенанс Key
        assert "(Discogs)" in out                 # провенанс страны
        assert "5:20" in out                      # длительность
        assert "1.2M" in out                      # просмотры
        assert "French House" in out              # стиль
        assert "verified" in out

    def test_key_relation_shown(self):
        out = ct.format_approval_table([self._track()], target_camelot="7A")
        assert "=" in out                         # 7A vs 7A → exact

    def test_summary_line(self):
        out = ct.format_approval_table([self._track()])
        assert "1 треков" in out
        assert "BPM 123–123" in out

    def test_unknown_fields_render_placeholder(self):
        t = {"artist": "A", "track": "T"}
        out = ct.format_approval_table([t])
        assert "?" in out                         # пустые поля → '?'


# ── P3b: temporary YouTube playlist link ───────────────────────────────────

class TestVideoId:
    def test_watch_url(self):
        assert ct.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_watch_url_with_extra_params(self):
        assert ct.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RD&t=10") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert ct.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_bare_id(self):
        assert ct.extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_soundcloud_returns_empty(self):
        assert ct.extract_video_id("https://soundcloud.com/artist/track") == ""

    def test_empty(self):
        assert ct.extract_video_id("") == ""


class TestPlaylistUrl:
    def test_builds_url(self):
        tracks = [
            {"youtube_url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"},
            {"youtube_url": "https://youtu.be/bbbbbbbbbbb"},
        ]
        url = ct.build_youtube_playlist_url(tracks)
        assert url == "https://www.youtube.com/watch_videos?video_ids=aaaaaaaaaaa,bbbbbbbbbbb"

    def test_dedups_preserving_order(self):
        tracks = [
            {"youtube_url": "https://youtu.be/aaaaaaaaaaa"},
            {"youtube_url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"},
            {"youtube_url": "https://youtu.be/ccccccccccc"},
        ]
        url = ct.build_youtube_playlist_url(tracks)
        assert url.endswith("video_ids=aaaaaaaaaaa,ccccccccccc")

    def test_skips_soundcloud_and_empty(self):
        tracks = [
            {"youtube_url": "https://soundcloud.com/a/b"},
            {"youtube_url": ""},
            {"youtube_url": "https://youtu.be/ddddddddddd"},
        ]
        url = ct.build_youtube_playlist_url(tracks)
        assert url.endswith("video_ids=ddddddddddd")

    def test_caps_at_limit(self):
        tracks = [{"youtube_url": f"https://youtu.be/{'x'*10}{i}"} for i in range(10)]
        url = ct.build_youtube_playlist_url(tracks, limit=3)
        assert url.count(",") == 2          # 3 ids → 2 commas

    def test_empty_when_no_youtube(self):
        assert ct.build_youtube_playlist_url([{"youtube_url": ""}]) == ""

    def test_appears_in_approval_table(self):
        tracks = [{"artist": "A", "track": "T", "youtube_url": "https://youtu.be/eeeeeeeeeee"}]
        out = ct.format_approval_table(tracks)
        assert "watch_videos?video_ids=eeeeeeeeeee" in out


# ── Wiring: PulseRoots resolver tier in get_discogs_styles ─────────────────

class TestGetDiscogsStyles:
    def test_exact_static_map_wins(self):
        # Ручная таблица имеет приоритет над резолвером
        assert ct.get_discogs_styles("deep house") == ct.DISCOGS_STYLE_MAP["deep house"]

    def test_pulseroots_tier_for_unmapped(self):
        # 'filter house' нет в статической таблице, но точно есть в PulseRoots
        styles = ct.get_discogs_styles("filter house")
        assert styles[0] == "Filter House"
        assert len(styles) > 1            # + смежные стили

    def test_fallthrough_to_as_is(self, monkeypatch):
        # Не в таблице, слабый матч PulseRoots, нет LLM-ключа → жанр как есть
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        styles = ct.get_discogs_styles("zzqq nonexistent style")
        assert styles == ["Zzqq Nonexistent Style"]


# ── B4: discovery ranking modes ────────────────────────────────────────────

class TestDiscoveryRank:
    def _pool(self):
        return [
            {"artist": "A", "track": "1", "bpm": 124, "camelot": "8A",
             "support_score": 900, "youtube_views": 50000, "year": 2024, "found_in": ["Discogs"]},
            {"artist": "B", "track": "2", "bpm": 120, "camelot": "7A",
             "support_score": 10, "youtube_views": 2000, "year": 2026, "found_in": ["Bandcamp"]},
            {"artist": "C", "track": "3", "bpm": 0, "camelot": "",
             "support_score": 999, "youtube_views": 9999999, "year": 2025, "found_in": ["Beatport"]},
        ]

    def test_popular_high_support_first(self):
        out = ct.discovery_rank(self._pool(), "popular")
        assert out[0]["artist"] == "A"        # highest support among meta-known
        assert out[-1]["artist"] == "C"       # no metadata → last

    def test_underground_low_support_bandcamp_first(self):
        out = ct.discovery_rank(self._pool(), "underground")
        assert out[0]["artist"] == "B"        # bandcamp + low popularity, meta known

    def test_newest_year_first(self):
        out = ct.discovery_rank(self._pool(), "newest")
        assert out[0]["artist"] == "B"        # 2026, meta known

    def test_unknown_mode_defaults_popular(self):
        assert ct.discovery_rank(self._pool(), "whatever")[0]["artist"] == "A"

    def test_meta_known_always_above_unknown(self):
        for mode in ("popular", "newest", "underground"):
            out = ct.discovery_rank(self._pool(), mode)
            assert out[-1]["artist"] == "C"   # C has no bpm/camelot → always last


# ── P6b: per-segment filter / rank / tag ───────────────────────────────────

class TestFilterRankTag:
    def _pool(self):
        return [
            {"artist": "A", "track": "1", "bpm": 122, "camelot": "8A", "support_score": 50},
            {"artist": "B", "track": "2", "bpm": 100, "camelot": "8A", "support_score": 90},  # bpm out of range
            {"artist": "C", "track": "3", "bpm": 123, "camelot": "2A", "support_score": 70},  # key incompatible
            {"artist": "D", "track": "4", "bpm": 0,   "camelot": "",   "support_score": 80},  # unknown meta
        ]

    def test_bpm_range_filters(self):
        seg = {"name": "s", "bpm_range": [120, 124], "target_key": "", "discovery": "popular"}
        out = ct.filter_rank_tag(self._pool(), seg)
        names = {t["artist"] for t in out}
        assert "B" not in names              # bpm 100 excluded
        assert "A" in names and "C" in names # in-range kept
        assert "D" in names                  # unknown bpm passes (not excluded)

    def test_target_key_filters(self):
        seg = {"name": "s", "bpm_range": [], "target_key": "8A", "discovery": "popular"}
        out = ct.filter_rank_tag(self._pool(), seg)
        names = {t["artist"] for t in out}
        assert "C" not in names              # 2A incompatible with 8A
        assert "A" in names                  # 8A compatible
        assert "D" in names                  # empty camelot passes

    def test_no_constraints_keeps_all(self):
        seg = {"name": "s", "bpm_range": [], "target_key": "", "discovery": "popular"}
        out = ct.filter_rank_tag(self._pool(), seg)
        assert len(out) == 4

    def test_tags_segment_name(self):
        seg = {"name": "intro", "bpm_range": [], "target_key": "", "discovery": "popular"}
        out = ct.filter_rank_tag(self._pool(), seg)
        assert all(t["segment"] == "intro" for t in out)

    def test_discovery_ranking_applied(self):
        seg = {"name": "s", "bpm_range": [], "target_key": "", "discovery": "underground"}
        out = ct.filter_rank_tag(self._pool(), seg)
        # underground → среди meta-known первым идёт низкий support_score (A=50 < C=70)
        meta = [t for t in out if t.get("bpm") and t.get("camelot")]
        assert meta[0]["artist"] == "A"


# ── xvfb preflight (headed scraping environment check) ─────────────────────

class TestXvfbPreflight:
    def test_display_present_ok(self):
        ok, msg = ct.xvfb_preflight(":99", "/usr/bin/xvfb-run")
        assert ok and msg == ""

    def test_no_display_but_xvfb_run(self):
        ok, msg = ct.xvfb_preflight("", "/usr/bin/xvfb-run")
        assert not ok
        assert "xvfb-run --auto-servernum" in msg
        assert "setup_xvfb.sh" not in msg          # xvfb есть → не предлагаем установку

    def test_no_display_no_xvfb_run(self):
        ok, msg = ct.xvfb_preflight("", "")
        assert not ok
        assert "setup_xvfb.sh" in msg              # предлагаем установку


# ── P6c: assemble_mix / harmonic order / trajectory summary ────────────────

class TestAssembleMix:
    def _multiseg(self):
        return [
            {"artist": "P1", "track": "x", "segment": "peak",  "bpm": 160, "camelot": "8A"},
            {"artist": "I1", "track": "x", "segment": "intro", "bpm": 80,  "camelot": "8A"},
            {"artist": "I2", "track": "x", "segment": "intro", "bpm": 72,  "camelot": "9A"},
            {"artist": "P2", "track": "x", "segment": "peak",  "bpm": 158, "camelot": "7A"},
        ]

    def test_preserves_segment_order(self):
        # intro появляется в пуле позже peak, но порядок групп = порядок появления
        out = ct.assemble_mix(self._multiseg(), {"bpm": "constant", "key": "per_segment"})
        segs = [t["segment"] for t in out]
        assert segs == ["peak", "peak", "intro", "intro"]   # peak встретился первым

    def test_bpm_ramp_sorts_within_segment(self):
        out = ct.assemble_mix(self._multiseg(), {"bpm": "ramp", "key": "per_segment"})
        intro = [t for t in out if t["segment"] == "intro"]
        assert [t["bpm"] for t in intro] == [72, 80]        # по возрастанию

    def test_harmonic_walk_orders_by_compatibility(self):
        tracks = [
            {"artist": "a", "track": "1", "segment": "s", "camelot": "8A"},
            {"artist": "b", "track": "2", "segment": "s", "camelot": "2A"},  # несовместим с 8A
            {"artist": "c", "track": "3", "segment": "s", "camelot": "9A"},  # сосед 8A
        ]
        out = ct.assemble_mix(tracks, {"bpm": "constant", "key": "harmonic_walk"})
        # после 8A первым должен идти совместимый 9A, а не 2A
        assert out[0]["camelot"] == "8A"
        assert out[1]["camelot"] == "9A"

    def test_no_key_tracks_go_last(self):
        tracks = [
            {"artist": "a", "track": "1", "segment": "s", "camelot": ""},
            {"artist": "b", "track": "2", "segment": "s", "camelot": "8A"},
        ]
        out = ct._harmonic_order(tracks)
        assert out[-1]["camelot"] == ""


class TestTrajectorySummary:
    def test_bpm_curve_and_keys(self):
        tracks = [
            {"segment": "intro", "bpm": 72, "camelot": "8A"},
            {"segment": "intro", "bpm": 80, "camelot": "9A"},
            {"segment": "peak",  "bpm": 158, "camelot": "7A"},
        ]
        out = ct.trajectory_summary(tracks)
        assert "72▸80" in out and "158" in out
        assert "8A▸9A▸7A" in out

    def test_empty(self):
        assert ct.trajectory_summary([]) == ""


# ── Tunebat-opt: select_enrich_candidates (top-N enrichment) ───────────────

class TestSelectEnrichCandidates:
    def _pool(self):
        # 5 без метаданных (разный support), 2 с полными метаданными
        return [
            {"artist": "n1", "track": "x", "bpm": 0,   "camelot": "",   "support_score": 10},
            {"artist": "n2", "track": "x", "bpm": 120, "camelot": "",   "support_score": 90},  # нет camelot
            {"artist": "n3", "track": "x", "bpm": 0,   "camelot": "8A", "support_score": 50},  # нет bpm
            {"artist": "n4", "track": "x", "bpm": 0,   "camelot": "",   "support_score": 70},
            {"artist": "n5", "track": "x", "bpm": 0,   "camelot": "",   "support_score": 30},
            {"artist": "ok1","track": "x", "bpm": 124, "camelot": "7A", "support_score": 99},
            {"artist": "ok2","track": "x", "bpm": 126, "camelot": "9A", "support_score": 99},
        ]

    def test_only_incomplete_meta_selected(self):
        out = select_names = ct.select_enrich_candidates(self._pool())
        names = {t["artist"] for t in select_names}
        assert "ok1" not in names and "ok2" not in names    # полные — не трогаем
        assert names == {"n1", "n2", "n3", "n4", "n5"}

    def test_limit_caps_and_ranks_by_discovery(self):
        # popular → топ по support_score: n2(90), n4(70), n3(50)
        out = ct.select_enrich_candidates(self._pool(), "popular", limit=3)
        assert len(out) == 3
        assert [t["artist"] for t in out] == ["n2", "n4", "n3"]

    def test_underground_prefers_low_support(self):
        out = ct.select_enrich_candidates(self._pool(), "underground", limit=2)
        # underground → низкий support первым: n1(10), n5(30)
        assert [t["artist"] for t in out] == ["n1", "n5"]

    def test_no_limit_returns_all_incomplete(self):
        out = ct.select_enrich_candidates(self._pool(), "popular", limit=None)
        assert len(out) == 5

    def test_limit_above_need_returns_all(self):
        out = ct.select_enrich_candidates(self._pool(), "popular", limit=100)
        assert len(out) == 5


# ── Speed-aware enrichment budget ──────────────────────────────────────────

class TestEnrichBudget:
    def test_thorough_factor4(self):
        assert ct.enrich_budget(5, "thorough") == 20      # 5×4
        assert ct.enrich_budget(1, "thorough") == 12      # пол ENRICH_MIN

    def test_fast_factor2(self):
        assert ct.enrich_budget(5, "fast") == 10          # 5×2
        assert ct.enrich_budget(1, "fast") == 6           # пол ENRICH_MIN_FAST

    def test_default_is_thorough(self):
        assert ct.enrich_budget(5) == 20

    def test_fast_smaller_than_thorough(self):
        assert ct.enrich_budget(8, "fast") < ct.enrich_budget(8, "thorough")
