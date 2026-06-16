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
