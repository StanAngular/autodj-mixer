"""P150: kick and bass as a pair (Plan.bass(kick=), bass_around_kick, kick_bass_overlap, the kick_bass gate, the track's swing in microtiming), both sides"""
import types, numpy as np, pytest
from autodj.compose import chords as C, ears, microtiming as MT

SECS = [(0, 8, "home"), (8, 16, "journey")]
KICK = (0, 7, 10); CELL = [0, 3, 7, 10]

def bass_steps(P, kick=None):
    n = P.bass(np.random.default_rng(1), 28, 45, cell=CELL, kick=kick)
    return [(s // 16, s % 16) for s, *_ in n]

# ---- bass_around_kick / overlap ---------------------------------------------------------------------------------------------------
def test_a_bass_cell_on_the_kick_is_moved_next_to_it():
    out = C.bass_around_kick(CELL, set(KICK), keep={0})
    assert set(out) & set(KICK) == {0} and len(out) == 4                                     # only the chord-change root stays on a hit, nothing lost

def test_notes_off_the_kick_are_left_alone_and_the_bar_never_goes_empty():
    assert C.bass_around_kick([2, 6, 14], {0, 4, 8, 12}) == [2, 6, 14]                          # already between the hits
    assert C.bass_around_kick([0], {0, 1, 15, 2, 14}, keep=()) != []                            # no free neighbour: the first step is kept, not dropped

def test_overlap_counts_only_bars_with_a_kick():
    assert C.kick_bass_overlap([(0, 0), (0, 3), (1, 0)], {0: {0}}) == .5 and C.kick_bass_overlap([(2, 0)], {0: {0}}) is None

def test_plan_bass_built_from_the_kick_overlaps_far_less_than_the_blind_one():
    P = C.Plan.build("A", SECS, "epic_minor", None, seed=1, allow_repeat="test")
    kb = {b: set(KICK) for b in range(P.bars)}
    blind = C.kick_bass_overlap(bass_steps(P), kb); built = C.kick_bass_overlap(bass_steps(P, KICK), kb)
    assert blind >= .5 and built <= .25, (blind, built)
    fn = C.kick_bass_overlap(bass_steps(P, lambda bar: KICK), kb); assert fn == built          # a function bar -> steps gives the same

def test_without_a_kick_the_bass_is_exactly_as_before():
    P = C.Plan.build("A", SECS, "epic_minor", None, seed=1, allow_repeat="test")
    a = P.bass(np.random.default_rng(1), 28, 45, cell=CELL); b = P.bass(np.random.default_rng(1), 28, 45, cell=CELL, kick=None); assert a == b

# ---- the gate ------------------------------------------------------------------------------------------------------------------------
def fake_trk(bass_steps_per_bar, kick_steps, bars=8):
    E = np.zeros((bars * 16, 3), dtype=np.float32)
    for b in range(bars):
        for k in kick_steps: E[b * 16 + k] = 1.0
    notes = [(b * 2.0 + s * .125, 40, 90, .1) for b in range(bars) for s in bass_steps_per_bar]
    return types.SimpleNamespace(act={"kick": E}, bars=bars, notes={"bass": notes}, BAR=2.0, S16=.125)

def test_a_bass_on_the_kick_is_measured_and_stopped():
    r = ears.kick_bass(fake_trk([0, 7, 10, 3], [0, 7, 10])); assert r == .75
    assert ears.gate_failures({"kick_bass": r}, {}) == ["kick_bass"] and ears.kick_bass_failures({"kick_bass": r}, {})

def test_a_bass_between_the_hits_passes_and_the_limit_is_inclusive():
    r = ears.kick_bass(fake_trk([2, 6, 11, 14], [0, 4, 8, 12])); assert r == 0.0 and ears.gate_failures({"kick_bass": r}, {}) == []
    assert ears.kick_bass_failures({"kick_bass": ears.KICK_BASS_MAX}, {}) == [] and ears.kick_bass_failures({"kick_bass": ears.KICK_BASS_MAX + .01}, {})

def test_unknown_is_not_a_failure():
    assert ears.kick_bass(types.SimpleNamespace(act={}, bars=4, notes={}, BAR=2.0, S16=.125)) is None and ears.gate_failures({"kick_bass": None}, {}) == []

def test_the_limit_moves_only_under_the_stas_override():
    s = {"kick_bass": .8}; meta = {"gates": {"kick_bass_max": .9}}
    assert ears.gate_failures(s, meta) == ["kick_bass"]
    assert ears.gate_failures(s, {**meta, "allow_reason": "Стас asked for the unison"}, override=True) == []

# ---- swing in microtiming -----------------------------------------------------------------------------------------------------------
def ens(swing):
    t = types.SimpleNamespace(bars=8, S16=.125, BAR=2.0, swing=swing); return MT.Ensemble(t, seed=3, drift_ms=0.0, role_jitter_ms=0.0)

def test_the_tracks_swing_delays_the_odd_sixteenths_only():
    a, b = ens(0.0), ens(.1)
    assert b.offset_ms(1, 3, "kick") - a.offset_ms(1, 3, "kick") == pytest.approx(12.5)           # odd step: .1 of a 16th (125 ms)
    assert b.offset_ms(1, 4, "kick") == a.offset_ms(1, 4, "kick")                                  # even step: untouched

def test_no_swing_means_the_old_timing():
    t = types.SimpleNamespace(bars=8, S16=.125, BAR=2.0); e = MT.Ensemble(t, seed=3); assert e.swing == 0.0 and abs(e.offset_ms(0, 1, "hats")) <= MT.LIMIT_MS
