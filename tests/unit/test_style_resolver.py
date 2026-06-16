"""
Unit tests for style_resolver.py (offline, runs against the vendored
data/pulseroots.genres.json). No network, no heavy deps.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import style_resolver as sr


class TestIndex:
    def test_tree_loads(self):
        assert len(sr._index()) > 300            # ~307 nodes

    def test_handles_both_name_keys(self):
        # Top-level node uses 'style', substyle uses 'name' — both resolvable
        assert sr.resolve("House")["matched"]        # top-level (style key)
        assert sr.resolve("Deep House")["matched"]   # substyle (name key)


class TestResolve:
    def test_exact_match(self):
        r = sr.resolve("deep house")
        assert r["matched"] and r["score"] == 1.0
        assert r["style"] == "Deep House"

    def test_normalize_hyphen_case(self):
        r = sr.resolve("Nu-Disco")
        assert r["matched"]
        assert r["style"].lower().replace("-", "") == "nudisco"

    def test_fuzzy_french_touch(self):
        r = sr.resolve("french touch")
        assert r["matched"]
        assert r["style"] == "French House"
        assert "Daft Punk" in r["seed_artists"]

    def test_unknown_not_matched(self):
        r = sr.resolve("totally unknown xyz")
        assert not r["matched"]
        assert r["style"] == "totally unknown xyz"   # echoes query

    def test_threshold_respected(self):
        # A weak fuzzy hit fails under a strict threshold
        assert not sr.resolve("organic house", threshold=0.95)["matched"]

    def test_empty_query(self):
        assert not sr.resolve("")["matched"]


class TestSimilarAndSeeds:
    def test_similar_includes_parent_and_sibling(self):
        sim = sr.similar_styles("deep house")
        assert "House" in sim                     # parent
        assert any(s != "Deep House" for s in sim)  # at least one sibling/child
        assert "Deep House" not in sim            # excludes self

    def test_similar_empty_for_unknown(self):
        assert sr.similar_styles("totally unknown xyz") == []

    def test_seed_artists_nonempty(self):
        artists = sr.seed_artists("house")
        assert artists and "Frankie Knuckles" in artists
