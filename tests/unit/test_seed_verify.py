"""Unit tests for P34: identity/style verification + best-pick in seed_discover."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import seed_discover as sd
import lastfm


class TestIdentityOk:
    def test_artist_in_title(self):
        assert sd.identity_ok("ANOTR - Relax (Original Mix)", "ANOTR") is True
    def test_track_in_title(self):
        assert sd.identity_ok("Some Channel — Relax", "ANOTR", "Relax") is True
    def test_no_match(self):
        assert sd.identity_ok("Random Pop Song", "ANOTR", "Relax") is False
    def test_partial_tokens(self):
        assert sd.identity_ok("Chris Stussy live set", "Chris Stussy") is True


class TestTitlePenalty:
    def test_flags_junk(self):
        assert sd.title_penalty("ANOTR Relax (LIVE at Tomorrowland)") >= 1
        assert sd.title_penalty("track REACTION video") >= 1
    def test_clean(self):
        assert sd.title_penalty("ANOTR - Relax (Original Mix)") == 0
    def test_remix_not_penalised(self):
        assert sd.title_penalty("Maria Maria (Diplo Remix)") == 0


class TestCandidateScore:
    def test_identity_and_views_beat_junk(self):
        good = {"track": "ANOTR - Relax", "views": 1_000_000}
        junk = {"track": "ANOTR Relax REACTION", "views": 5_000_000}
        assert sd.candidate_score(good, "ANOTR") > sd.candidate_score(junk, "ANOTR")


class TestPickBest:
    def test_picks_highest_confident(self):
        cands = [
            {"track": "ANOTR - Relax", "views": 100},
            {"track": "ANOTR - Relax (Extended)", "views": 900000},
            {"track": "totally other song", "views": 9999999},     # не та личность
        ]
        best = sd.pick_best(cands, "ANOTR")
        assert best["views"] == 900000                              # лучший ИЗ совпавших
    def test_none_when_no_identity(self):
        cands = [{"track": "random", "views": 999}]
        assert sd.pick_best(cands, "ANOTR", require_identity=True) is None


class TestStyleInTags:
    def test_match(self):
        assert sd.style_in_tags(["Tech House", "techno", "house"], "tech house") is True
    def test_no_match(self):
        assert sd.style_in_tags(["pop", "synthpop"], "tech house") is False
    def test_empty_target_passes(self):
        assert sd.style_in_tags(["whatever"], "") is True


class TestArtistTopTagsParser:
    def test_parse_tags(self):
        data = {"toptags": {"tag": [{"name": "Tech House"}, {"name": "Techno"}]}}
        assert lastfm._parse_tags(data) == ["tech house", "techno"]
    def test_error(self):
        assert lastfm._parse_tags({"error": 6}) == []


# ── P35: отсев DJ-сетов по длительности + маркерам ─────────────────────────

class TestIsPlausibleTrack:
    def test_normal_track(self):
        assert sd.is_plausible_track({"duration": 300}) is True      # 5 мин
    def test_dj_set_rejected(self):
        assert sd.is_plausible_track({"duration": 3600}) is False     # 60 мин = сет
    def test_teaser_rejected(self):
        assert sd.is_plausible_track({"duration": 30}) is False       # 30с = тизер
    def test_unknown_allowed(self):
        assert sd.is_plausible_track({"duration": None}) is True

class TestSetMarkersAndPick:
    def test_set_markers_penalised(self):
        assert sd.title_penalty("Adriatique @ Cercle, Mexico") >= 1
        assert sd.title_penalty("ANOTR | Boiler Room") >= 1
    def test_pick_best_skips_long_set(self):
        cands = [
            {"track": "Adriatique @ Cercle", "duration": 5400, "views": 9000000},  # сет
            {"track": "Adriatique - Miracle", "duration": 380, "views": 200000},   # трек
        ]
        best = sd.pick_best(cands, "Adriatique")
        assert best["track"] == "Adriatique - Miracle"   # сет отброшен, взят трек
