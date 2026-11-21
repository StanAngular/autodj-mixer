"""P147 (no repeated opening progression, checked while a render runs) and P148 (an ordered journey progression is never silently dropped), both sides"""
import pytest
from autodj.compose import chords as C, fresh

SECS = [(0, 8, "intro"), (8, 24, "verse"), (24, 40, "A2"), (40, 56, "final"), (56, 64, "outro")]   # no section the role_of() calls journey

def ledger(*rows):
    """a freshness ledger whose tracks carry the given harmony fingerprints, oldest first"""
    return {"version": 1, "tracks": {t: {"harmony": fp, "sources": []} for t, fp in rows}}

def fp_of(home, tonic="A", **kw):
    return C.Plan.build(tonic, SECS, home, None, seed=1, allow_repeat="test", **kw).fingerprint()

@pytest.fixture(autouse=True)
def _no_title():
    fresh.TITLE = None; yield; fresh.TITLE = None

# ---- P147: what it stops ----------------------------------------------------------------------------------------------------------
def test_a_progression_that_opens_like_a_recent_track_is_refused_inside_a_render(monkeypatch):
    db = ledger(("Old Track", fp_of("night_loop")))
    monkeypatch.setattr(fresh, "load", lambda path=None: db); fresh.TITLE = "New Track"
    with pytest.raises(C.HarmonyRepeat) as e: C.Plan.build("A", SECS, "night_loop", None, seed=1)
    assert "Old Track" in str(e.value) and "free now" in str(e.value)

def test_the_same_progression_in_another_key_is_still_a_repeat(monkeypatch):
    db = ledger(("Old Track", fp_of("night_loop", "A")))
    monkeypatch.setattr(fresh, "load", lambda path=None: db); fresh.TITLE = "New Track"
    with pytest.raises(C.HarmonyRepeat): C.Plan.build("E", SECS, "night_loop", None, seed=2)

def test_a_repeat_hidden_behind_a_different_tail_is_still_caught(monkeypatch):
    fp = fp_of("night_loop"); head = C.signature(fp)
    db = ledger(("Old Track", head + " 3:maj7 9:m7 || 0:m7"))                         # same first four chords, another tail
    monkeypatch.setattr(fresh, "load", lambda path=None: db); fresh.TITLE = "New Track"
    with pytest.raises(C.HarmonyRepeat): C.Plan.build("A", SECS, "night_loop", None, seed=1)

# ---- P147: what it lets through ---------------------------------------------------------------------------------------------------
def test_a_new_progression_passes(monkeypatch):
    db = ledger(("Old Track", fp_of("night_loop")))
    monkeypatch.setattr(fresh, "load", lambda path=None: db); fresh.TITLE = "New Track"
    P = C.Plan.build("A", SECS, "epic_minor", None, seed=1); assert P.slots

def test_a_rerender_of_the_same_title_is_not_a_repeat(monkeypatch):
    db = ledger(("Same Track", fp_of("night_loop")))
    monkeypatch.setattr(fresh, "load", lambda path=None: db); fresh.TITLE = "Same Track"
    assert C.Plan.build("A", SECS, "night_loop", None, seed=1).slots

def test_only_the_latest_tracks_count(monkeypatch):
    rows = [("Ancient", fp_of("night_loop"))] + [(f"T{i}", fp_of("epic_minor")) for i in range(C.RECENT)]
    monkeypatch.setattr(fresh, "load", lambda path=None: ledger(*rows)); fresh.TITLE = "New Track"
    assert C.Plan.build("A", SECS, "night_loop", None, seed=1).slots                  # Ancient fell out of the window

def test_outside_a_render_nothing_is_checked(monkeypatch):
    db = ledger(("Old Track", fp_of("night_loop")))
    monkeypatch.setattr(fresh, "load", lambda path=None: db)                           # fresh.TITLE is None: tests, scratch work
    assert C.Plan.build("A", SECS, "night_loop", None, seed=1).slots

def test_allow_repeat_needs_a_reason_and_is_written_to_meta(monkeypatch):
    db = ledger(("Old Track", fp_of("night_loop")))
    monkeypatch.setattr(fresh, "load", lambda path=None: db); fresh.TITLE = "New Track"
    P = C.Plan.build("A", SECS, "night_loop", None, seed=1, allow_repeat="Стас asked for it"); assert P.meta["repeat_allowed"] == "Стас asked for it"
    with pytest.raises(ValueError): C.Plan.build("A", SECS, "night_loop", None, seed=1, allow_repeat=True)

def test_run_sets_and_reset_clears_the_title():
    fresh.TITLE = "x"; fresh.reset(); assert fresh.TITLE is None

# ---- P148 -------------------------------------------------------------------------------------------------------------------------
def test_an_ordered_journey_is_not_lost_when_no_section_is_called_journey():
    P = C.Plan.build("A", SECS, "minor_plagal", "lament", seed=1)
    names = {nm for *_, nm in P.slots if C.role_of(nm) == "home"}; assert "A2" in names                       # roles stay by name...
    assert P.meta["journey_section"] == "A2"
    home = [c for s, n, c, nm in P.slots if nm == "verse"]; j = [c for s, n, c, nm in P.slots if nm == "A2"]
    assert home[0] != j[0] or [c.qual for c in home[:4]] != [c.qual for c in j[:4]]                           # the second progression is really different

def test_a_journey_section_by_name_or_roles_is_left_alone():
    secs = [(0, 16, "verse"), (16, 32, "journey"), (32, 48, "final")]
    assert "journey_section" not in C.Plan.build("A", secs, "minor_plagal", "lament", seed=1).meta
    assert "journey_section" not in C.Plan.build("A", SECS, "minor_plagal", "lament", seed=1, roles={"A2": "journey"}).meta

def test_no_journey_ordered_means_no_change():
    a = C.Plan.build("A", SECS, "minor_plagal", None, seed=1); assert "journey_section" not in a.meta and "journey_unused" not in a.meta

def test_a_single_home_section_cannot_take_the_journey_and_says_so():
    P = C.Plan.build("A", [(0, 16, "main")], "minor_plagal", "lament", seed=1); assert P.meta.get("journey_unused") and "journey_section" not in P.meta
