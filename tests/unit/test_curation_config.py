"""
Unit tests for curation_config.py (offline, no network/deps).
Covers segment normalisation, validation errors, trajectory defaults,
the CLI→1-segment bridge, and loading the shipped example brief.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import curation_config as cc
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNormalizeSegment:
    def test_minimal_valid(self):
        s = cc.normalize_segment({"styles": "ambient", "count": 3})
        assert s["styles"] == ["ambient"]
        assert s["count"] == 3
        assert s["discovery"] == "popular"          # default
        assert s["name"] == "segment-1"

    def test_seed_artists_only_is_valid(self):
        s = cc.normalize_segment({"seed_artists": ["Daft Punk"], "count": 2})
        assert s["seed_artists"] == ["Daft Punk"]

    def test_bpm_range_sorted(self):
        s = cc.normalize_segment({"styles": ["x"], "count": 1, "bpm_range": [124, 120]})
        assert s["bpm_range"] == [120, 124]

    def test_requires_styles_or_seed(self):
        with pytest.raises(cc.CurationConfigError):
            cc.normalize_segment({"count": 3})

    def test_count_must_be_positive_int(self):
        for bad in (0, -1, "3", 2.5, True):
            with pytest.raises(cc.CurationConfigError):
                cc.normalize_segment({"styles": ["x"], "count": bad})

    def test_bad_discovery(self):
        with pytest.raises(cc.CurationConfigError):
            cc.normalize_segment({"styles": ["x"], "count": 1, "discovery": "viral"})

    def test_bad_camelot(self):
        with pytest.raises(cc.CurationConfigError):
            cc.normalize_segment({"styles": ["x"], "count": 1, "target_key": "13Z"})

    def test_valid_camelot(self):
        s = cc.normalize_segment({"styles": ["x"], "count": 1, "target_key": "12A"})
        assert s["target_key"] == "12A"


class TestTrajectory:
    def test_defaults(self):
        cfg = cc.load_config({"segments": [{"styles": ["x"], "count": 1}]})
        assert cfg["trajectory"] == cc.DEFAULT_TRAJECTORY

    def test_partial_override(self):
        cfg = cc.load_config({"segments": [{"styles": ["x"], "count": 1}],
                              "trajectory": {"bpm": "ramp"}})
        assert cfg["trajectory"]["bpm"] == "ramp"
        assert cfg["trajectory"]["key"] == "per_segment"   # untouched default

    def test_bad_value(self):
        with pytest.raises(cc.CurationConfigError):
            cc.load_config({"segments": [{"styles": ["x"], "count": 1}],
                            "trajectory": {"bpm": "zigzag"}})


class TestLoadConfig:
    def test_requires_segments(self):
        with pytest.raises(cc.CurationConfigError):
            cc.load_config({"title": "x", "segments": []})

    def test_bad_years(self):
        with pytest.raises(cc.CurationConfigError):
            cc.load_config({"segments": [{"styles": ["x"], "count": 1}], "years": ["2025"]})

    def test_example_brief_loads(self):
        cfg = cc.load_config_file(os.path.join(REPO, "examples", "curation_brief.example.json"))
        assert len(cfg["segments"]) == 3
        assert cfg["trajectory"]["bpm"] == "ramp"
        assert cfg["segments"][0]["name"] == "intro-eurasia"
        assert cfg["segments"][2]["bpm_range"] == [150, 170]


class TestConfigFromCli:
    class _Args:
        genre = "deep house"; bpm = 122; bpm_min = 0; bpm_max = 0
        bpm_tolerance = 3; camelot = "8A"; count = 12
        country = "FR"; region = ""; years = "2025,2026"; discovery = "popular"

    def test_single_segment_bridge(self):
        cfg = cc.config_from_cli(self._Args())
        assert len(cfg["segments"]) == 1
        s = cfg["segments"][0]
        assert s["styles"] == ["deep house"]
        assert s["bpm_range"] == [119, 125]      # 122 ± 3
        assert s["countries"] == ["FR"]
        assert s["target_key"] == "8A"
        assert cfg["years"] == [2025, 2026]

    def test_explicit_bpm_range_wins(self):
        a = self._Args(); a.bpm_min = 120; a.bpm_max = 126
        cfg = cc.config_from_cli(a)
        assert cfg["segments"][0]["bpm_range"] == [120, 126]


class TestDescribe:
    def test_describe_runs(self):
        cfg = cc.load_config_file(os.path.join(REPO, "examples", "curation_brief.example.json"))
        out = cc.describe(cfg)
        assert "intro-eurasia" in out and "ramp" in out
