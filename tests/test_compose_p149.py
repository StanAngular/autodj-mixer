"""P149: developed lines (lines.develop / lines.evolve) and the literal-repeat gate (ears.literal_runs / literal_failures / gate_failures), both sides"""
import numpy as np, pytest
from autodj.compose import chords as C, lines as L, ears

SECS = [(0, 16, "home"), (16, 32, "journey"), (32, 48, "home2"), (48, 64, "home3")]
LO, HI = 60, 79

def plan(): return C.Plan.build("A", SECS, "epic_minor", "minor_plagal", seed=3)
def hook(p, seed=1): return L.hook(p, np.random.default_rng(seed), LO, HI, 0)
def key(n): return [(s, ln, m) for s, ln, m, v in n]

# ---- develop -----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", L.DEVELOP_KINDS)
def test_every_development_changes_the_line_and_stays_in_range_and_in_key(kind):
    p = plan(); h = hook(p); d = L.develop(h, p, kind, LO, HI, np.random.default_rng(5), None, 32 * 16)
    assert d and key(d) != key(L.refit(h, p, LO, HI, None, 32 * 16))                         # not the plain copy
    assert all(LO <= m <= HI and m % 12 in p.key for s, ln, m, v in d)

def test_a_development_keeps_the_idea_the_contour_or_rhythm_of_the_source_survives():
    p = plan(); h = hook(p); a = [m for s, ln, m, v in h][:6]
    seq = [m for s, ln, m, v in L.develop(h, p, "sequence", LO, HI, np.random.default_rng(1), None, 0)][:6]
    assert [np.sign(np.diff(a))] != [] and sum(np.sign(np.diff(a)) == np.sign(np.diff(seq))) >= 3        # contour mostly kept
    disp = L.develop(h, p, "displace", LO, HI, np.random.default_rng(1), None, 0); assert {s % 16 for s, *_ in disp} != {s % 16 for s, *_ in h}   # rhythm moved

def test_unknown_kind_and_empty_line():
    p = plan()
    assert L.develop([], p, "sequence", LO, HI, np.random.default_rng(1)) == []
    with pytest.raises(ValueError): L.develop(hook(p), p, "bogus", LO, HI, np.random.default_rng(1))

# ---- evolve ------------------------------------------------------------------------------------------------------------------------
def copies(out, bars, period=8):
    return [[n for n in out if b * 16 <= n[0] < (b + period) * 16] for b in bars]

def test_evolve_gives_a_different_copy_every_time_and_returns_at_the_end():
    p = plan(); h = hook(p); bars = [0, 8, 16, 24, 32, 40]; out = L.evolve(h, p, np.random.default_rng(2), LO, HI, bars, period=8, origin=0)
    cs = [[(s - b * 16, ln, m) for s, ln, m, v in c] for c, b in zip(copies(out, bars), bars)]
    assert all(c for c in cs) and all(cs[i] != cs[i + 1] for i in range(len(cs) - 1))          # no two neighbours alike
    assert len({tuple(c) for c in cs}) >= 4                                                     # real variety, not A B A B
    assert cs[0][:3] == [(s, ln, m) for s, ln, m, v in L.refit(h, p, LO, HI, None, 0)][:3]      # the first copy is the line itself

def test_evolve_with_one_bar_start_is_just_the_line_and_without_notes_is_empty():
    p = plan(); h = hook(p)
    assert L.evolve([], p, np.random.default_rng(1), LO, HI, [0, 8]) == []
    assert key(L.evolve(h, p, np.random.default_rng(1), LO, HI, [0], origin=0))[:4] == key(L.refit(h, p, LO, HI, None, 0))[:4]

# ---- the literal-repeat gate -----------------------------------------------------------------------------------------------------
BAR, S16 = 2.0, .125
def ev(bar, steps=(0, 3, 6, 10), pitches=(60, 62, 64, 67)): return [(bar * BAR + s * S16, p, 90, .1) for s, p in zip(steps, pitches)]

def test_a_layer_that_plays_the_same_bar_for_40_bars_is_caught():
    notes = {"lead": [e for b in range(40) for e in ev(b)]}
    r = ears.literal_runs(notes, BAR, S16); assert r["lead"] == (40, 1)
    assert ears.gate_failures({"literal": r}, {}) == ["literal_repeat"] and ears.literal_failures({"literal": r}, {})

def test_a_two_bar_loop_is_caught_with_its_period():
    notes = {"lead": [e for b in range(40) for e in ev(b, pitches=(60, 62, 64, 67) if b % 2 else (60, 65, 64, 69))]}
    assert ears.literal_runs(notes, BAR, S16)["lead"] == (40, 2)

def test_a_developed_layer_passes_the_same_length():
    notes = {"lead": [e for b in range(40) for e in ev(b, pitches=tuple(60 + (b // 8) * 2 + i for i in (0, 2, 4, 7)))]}        # the pitches move every 8 bars
    r = ears.literal_runs(notes, BAR, S16); assert r["lead"][0] <= 9 and not ears.gate_failures({"literal": r}, {})

def test_a_loop_of_exactly_the_limit_passes_and_one_bar_more_fails():
    ok = {"l": [e for b in range(ears.LITERAL_RUN_MAX) for e in ev(b)]}; bad = {"l": [e for b in range(ears.LITERAL_RUN_MAX + 1) for e in ev(b)]}
    assert not ears.literal_failures({"literal": ears.literal_runs(ok, BAR, S16)}, {}) and ears.literal_failures({"literal": ears.literal_runs(bad, BAR, S16)}, {})

def test_held_notes_and_silent_bars_are_not_a_loop():
    pad = {"pad": [(b * BAR, 60, 80, BAR) for b in range(40)]}                              # one note per bar: skipped (min_notes)
    gap = {"l": [e for b in range(60) if b % 8 != 7 for e in ev(b)]}                          # a silent bar every 8: runs of 7, not 60
    assert ears.literal_runs(pad, BAR, S16) == {} and ears.literal_runs(gap, BAR, S16)["l"][0] <= 8

def test_the_limit_can_only_be_moved_under_the_stas_override(monkeypatch):
    s = {"literal": {"lead": (48, 1)}}; meta = {"gates": {"literal_run_max": 64}}
    assert ears.gate_failures(s, meta) == ["literal_repeat"]                                  # the META number alone does nothing
    assert ears.gate_failures(s, {**meta, "allow_reason": "Стас asked for a loop"}, override=True) == []
    monkeypatch.setenv("AUTODJ_GATE_OVERRIDE", "1"); assert ears.gate_failures(s, {**meta, "allow_reason": "Стас asked"}) == []

def test_allow_bad_sounds_does_not_hide_a_literal_loop():
    s = {"literal": {"lead": (48, 1)}, "bad_sounds": {"x": 1}}
    assert "literal_repeat" in ears.gate_failures(s, {"allow_bad_sounds": True, "allow_reason": "x"}, override=True)
