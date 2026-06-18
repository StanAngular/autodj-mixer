"""Unit tests for catalog_register.py pure functions (P23, offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import catalog_register as cr


class TestVideoId:
    def test_watch(self):
        assert cr.video_id("https://www.youtube.com/watch?v=abcDEF12345") == "abcDEF12345"
    def test_none(self):
        assert cr.video_id("") == "" and cr.video_id("https://soundcloud.com/x") == ""


class TestBuildEntry:
    def test_stores_camelot_and_url(self):
        # ключевое: camelot и youtube_url теперь В каталоге (раньше терялись)
        t = {"artist": "Tale Of Us", "track": "Nova", "bpm": 124, "camelot": "8A",
             "youtube_url": "https://youtu.be/aaaaaaaaaaa", "year": 2025}
        e = cr.build_entry(t)
        assert e["camelot"] == "8A"
        assert e["youtube_url"] == "https://youtu.be/aaaaaaaaaaa"
        assert e["bpm"] == 124 and e["artist"] == "Tale Of Us" and e["title"] == "Nova"
        assert e["source"] == "curation" and e["analysis"] == "none"

    def test_full_a1f_structure_kept_as_is(self):
        # сегменты хранятся ЦЕЛИКОМ (полная структура), не урезаются
        a1f = {"bpm": 126, "beats": [0, 1, 2, 3], "downbeats": [0, 2],
               "segments": [{"start": 0.0, "end": 10.0, "label": "intro"},
                            {"start": 10.0, "end": 60.0, "label": "drop"}]}
        e = cr.build_entry({"artist": "A", "track": "x", "camelot": "9A",
                            "youtube_url": "https://youtu.be/bbbbbbbbbbb"}, a1f)
        assert e["structure"] == a1f["segments"]      # как есть
        assert e["num_beats"] == 4 and e["num_downbeats"] == 2
        assert e["duration"] == 60.0
        assert e["a1f_file"] == "a1f_results/bbbbbbbbbbb.json"
        assert e["analysis"] == "a1f"

    def test_merges_ytdlp_meta(self):
        # собранная за проход yt-dlp инфа (year/genre/tags) попадает в каталог
        meta = {"track_title": "yt title", "artist": "yt artist", "year": 2024,
                "genre": "Deep House", "tags": ["house"] * 30, "description": "x" * 999,
                "duration_sec": 300}
        e = cr.build_entry({"artist": "Real", "track": "Real Track", "camelot": "8A",
                            "youtube_url": "https://youtu.be/ccccccccccc"}, None, meta)
        assert e["artist"] == "Real"          # курация в приоритете над yt-dlp
        assert e["genre"] == "Deep House" and e["year"] == 2024
        assert len(e["tags"]) == 20 and len(e["description"]) == 500   # обрезка
        assert e["duration"] == 300

    def test_madmom_only_method(self):
        e = cr.build_entry({"artist": "A", "track": "x", "camelot": "8A",
                            "youtube_url": "https://youtu.be/ddddddddddd"},
                           None, None, madmom_downbeats=96)
        assert e["madmom_downbeats"] == 96 and e["analysis"] == "madmom"

    def test_bpm_fallback_to_a1f(self):
        e = cr.build_entry({"artist": "A", "track": "x", "youtube_url": "https://youtu.be/eeeeeeeeeee"},
                           {"bpm": 128, "segments": []})
        assert e["bpm"] == 128


class TestCountMadmomDownbeats:
    def test_counts_position_one(self, tmp_path):
        p = tmp_path / "v.txt"
        p.write_text("0.050000 1\n0.550000 2\n1.050000 3\n1.550000 4\n2.050000 1\n")
        assert cr._count_madmom_downbeats(str(p)) == 2     # две доли «1»
    def test_missing_file(self):
        assert cr._count_madmom_downbeats("/nope/x.txt") is None
