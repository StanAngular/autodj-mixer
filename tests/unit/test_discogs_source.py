"""Тесты discogs_source: парсеры + АДАПТЕР release→tracks (бэклог) + год-фильтр. Офлайн."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import discogs_source as dg


SEARCH_JSON = {"results": [
    {"id": 111, "title": "Artist A - Great EP", "year": 2026, "style": ["Deep House"],
     "country": "DE", "format": ["Vinyl", '12"', "EP"]},
    {"id": 222, "title": "V/A - Mega Hits", "year": 2026, "style": ["House"],
     "country": "US", "format": ["CD", "Compilation"]},          # компиляция — мимо
    {"id": 333, "title": "Artist B - Old Single", "year": 2019, "style": ["Disco"],
     "country": "FR", "format": ["Vinyl", "Single"]},
]}

RELEASE_EP = {
    "id": 111, "year": 2026, "styles": ["Deep House"],
    "artists": [{"name": "Artist A"}],
    "tracklist": [
        {"type_": "track", "title": "Opening Groove", "duration": "6:12"},
        {"type_": "track", "title": "Deep Cut", "duration": "7:01"},
        {"type_": "heading", "title": "B side"},                  # не трек
        {"type_": "track", "title": "Night Drive", "duration": "6:45"},
        {"type_": "track", "title": "Closer", "duration": "8:00"},
    ],
}

RELEASE_VA = {
    "id": 444, "year": 2025, "styles": ["Disco"],
    "artists": [{"name": "Various"}],
    "tracklist": [
        {"type_": "track", "title": "Funk It", "artists": [{"name": "Disco Dan (2)"}]},
        {"type_": "track", "title": "Roll On", "artists": [{"name": "Groove Sista"}]},
    ],
}


class TestParseSearch:
    def test_filters_compilations_keeps_eps(self):
        rels = dg.parse_search_releases(SEARCH_JSON)
        ids = [r["release_id"] for r in rels]
        assert 111 in ids and 333 in ids and 222 not in ids

    def test_fields(self):
        r = dg.parse_search_releases(SEARCH_JSON)[0]
        assert r["year"] == 2026 and r["styles"] == ["Deep House"]


class TestReleaseTracklistAdapter:
    def test_ep_yields_all_tracks_not_release_name(self):
        # ГЛАВНОЕ (бэклог): EP из 4 треков → 4 кандидата, а не 1 «псевдотрек» имени релиза
        tracks = dg.parse_release_tracklist(RELEASE_EP)
        assert len(tracks) == 4
        titles = [t["track"] for t in tracks]
        assert "Deep Cut" in titles and "Great EP" not in titles
        assert all(t["artist"] == "Artist A" and t["year"] == 2026 for t in tracks)

    def test_headings_skipped(self):
        assert all(t["track"] != "B side" for t in dg.parse_release_tracklist(RELEASE_EP))

    def test_va_release_per_track_artists_and_disambig_cleanup(self):
        tracks = dg.parse_release_tracklist(RELEASE_VA)
        assert tracks[0]["artist"] == "Disco Dan"                # '(2)' счищен
        assert tracks[1]["artist"] == "Groove Sista"


class TestSeedsWithMeta:
    def test_year_is_first_class_filter(self):
        tracks = [{"artist": "A", "track": "New", "year": 2026},
                  {"artist": "B", "track": "Old", "year": 2019},
                  {"artist": "C", "track": "NoYear", "year": 0}]
        seeds, meta = dg.tracks_to_seeds_with_meta(tracks, year_lo=2025, year_hi=2026)
        assert seeds == ["A - New", "C - NoYear"]               # вне диапазона — мимо; без года — мягко
        assert meta["A - New"]["year"] == 2026
        assert meta["A - New"]["source_type"] == "discogs"

    def test_dedup(self):
        tracks = [{"artist": "A", "track": "T", "year": 2026}] * 2
        seeds, _ = dg.tracks_to_seeds_with_meta(tracks)
        assert len(seeds) == 1


class TestEntityVerification:
    def test_verify_style_defaults_to_search_style(self, monkeypatch):
        # Carly-кейс: релиз Disco, но артист pop → seed_discover получает verify_style='Disco'
        captured = {}
        import seed_discover as sd
        def fake_discover(seeds, per_artist=5, verify=True, verify_style="", seed_meta=None, **kw):
            captured["verify_style"] = verify_style
            return []
        monkeypatch.setattr(sd, "seed_discover", fake_discover)
        monkeypatch.setattr(dg, "search_releases", lambda *a, **k: [{"release_id": 1}])
        monkeypatch.setattr(dg, "fetch_release_tracks",
                            lambda rid: [{"artist": "A", "track": "T", "year": 2026}])
        dg.discogs_candidates("Disco", 2025, 2026, target=1)
        assert captured["verify_style"] == "Disco"

    def test_verify_style_can_be_disabled(self, monkeypatch):
        captured = {}
        import seed_discover as sd
        def fake_discover(seeds, per_artist=5, verify=True, verify_style="", seed_meta=None, **kw):
            captured["verify_style"] = verify_style
            return []
        monkeypatch.setattr(sd, "seed_discover", fake_discover)
        monkeypatch.setattr(dg, "search_releases", lambda *a, **k: [{"release_id": 1}])
        monkeypatch.setattr(dg, "fetch_release_tracks",
                            lambda rid: [{"artist": "A", "track": "T", "year": 2026}])
        dg.discogs_candidates("Disco", 2025, 2026, target=1, verify_style="")
        assert captured["verify_style"] == ""


class TestStylesTravel:
    def test_merge_seed_meta_carries_styles(self):
        import seed_discover as sd
        cand = {"track": "Found On YT", "youtube_url": "u"}
        out = sd.merge_seed_meta(cand, {"styles": ["Deep House"], "year": 2026, "source_type": "discogs"})
        assert out["styles"] == ["Deep House"] and out["year"] == 2026
