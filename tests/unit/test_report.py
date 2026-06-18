"""Unit tests for report.py (P22): render_report + helpers (offline, pure)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import report as R


class TestCamelotMarker:
    def test_relations(self):
        assert R._camelot_marker("8A", "8A") == "[= тот же ключ]"
        assert R._camelot_marker("8A", "9A") == "[±1 сосед]"
        assert R._camelot_marker("8A", "8B") == "[REL relative]"
        assert R._camelot_marker("8A", "9B") == "[diag energy]"
        assert R._camelot_marker("8A", "3B") == "[⚠ скачок]"
    def test_empty(self):
        assert R._camelot_marker("", "8A") == ""


class TestFmtTime:
    def test_basic(self):
        assert R._fmt_time(0) == "00:00"
        assert R._fmt_time(344) == "05:44"
        assert R._fmt_time(3550) == "59:10"


class TestRenderReport:
    def _data(self):
        return {
            "title": "Ритуал Рассвета", "genre": "Organic House", "duration": "10:00",
            "month": "Июнь 2026", "playlist_url": "https://youtube.com/playlist?list=X",
            "tracks": [
                {"time": "00:00", "artist": "Volen Sentir", "track": "Neunivai",
                 "flag": "🇺🇦", "country": "Украина", "label": "All Day I Dream",
                 "year": 2026, "bpm": 120, "key": "E maj", "camelot": "12B",
                 "youtube": "https://youtu.be/aaa"},
                {"time": "05:44", "artist": "Nikita Grib", "track": "Raag Yaman",
                 "bpm": 125, "key": "A min", "camelot": "8A", "youtube": "https://youtu.be/bbb"},
            ],
        }

    def test_header_and_totals(self):
        out = R.render_report(self._data())
        assert "DJ AGENT 001 — РИТУАЛ РАССВЕТА" in out   # придуманное название, не жанр
        assert "**Organic House**" in out                          # жанр — подзаголовком
        assert "Всего треков:** 2" in out
        assert "playlist?list=X" in out

    def test_title_slot_when_empty(self):
        d = self._data(); d["title"] = ""
        out = R.render_report(d)
        assert "НАЗВАНИЕ МИКСА" in out                 # пустое название → слот для агента

    def test_creative_slots_marked_when_empty(self):
        out = R.render_report(self._data())
        assert "ИНТРО:" in out                       # интро-слот
        assert out.count("клубный статус") == 2      # комментарий-слот на каждый трек

    def test_filled_comment_not_slot(self):
        d = self._data()
        d["intro"] = "Готовое интро."
        d["tracks"][0]["comment"] = "Хит лейбла."
        out = R.render_report(d)
        assert "Готовое интро." in out and "Хит лейбла." in out

    def test_transition_marker(self):
        out = R.render_report(self._data())
        assert "12B→8A" in out and "⚠ скачок" in out  # переход между треками с маркером


class TestBuildReportData:
    def test_times_from_stamps(self):
        cands = [{"artist": "A", "track": "1", "camelot": "8A", "youtube_url": "u1"},
                 {"artist": "B", "track": "2", "camelot": "9A", "youtube_url": "u2"}]
        stamps = [{"t": 344, "dur": 8}]
        data = R.build_report_data(cands, stamps, 600.0, title="X")
        assert data["tracks"][0]["time"] == "00:00"
        assert data["tracks"][1]["time"] == "05:44"
        assert data["duration"] == "10:00"
