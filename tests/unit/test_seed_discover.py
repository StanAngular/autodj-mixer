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
