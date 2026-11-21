"""P156 + P157 arrange: energy arc with a peak, gains, drum plan with functions, the static-drum report (both sides)"""
import types, numpy as np
from autodj.compose import arrange as A

SECS = [(0, 16, "intro"), (16, 32, "home1"), (32, 48, "journey1"), (48, 52, "break"), (52, 56, "build"), (56, 72, "home2"), (72, 88, "journey2"), (88, 104, "home3"), (104, 120, "outro")]

def test_the_arc_rises_through_the_homes_to_a_peak_in_the_last_one():
    e = A.energy_arc(SECS); assert e["home1"] < e["home2"] < e["home3"] == 1.0 and e["break"] < e["home1"] and e["intro"] < e["home1"] and e["outro"] < e["home3"]
    assert e["journey1"] > e["home1"] and A.energy_arc(SECS, peaks={"home2": .99})["home2"] == .99

def test_gains_put_the_peak_above_the_first_home_and_the_break_below():
    g = A.section_gain_db(A.energy_arc(SECS)); assert g["home3"] - g["home1"] >= 2.0 and g["break"] < g["home1"] and g["home1"] == 0.0

def plan(seed=1): return A.drum_plan(SECS, A.energy_arc(SECS), np.random.default_rng(seed))
def bars_of(ev, a, b): return [x for x in ev if a <= x[0] < b]

def test_the_club_pulse_stays_in_homes_and_journeys():
    k = plan()["kick"]
    for a, b, n in ((16, 32, "home1"), (32, 48, "journey1"), (88, 104, "home3")):
        beats = {(br, st) for br, st, v in bars_of(k, a, b) if st in (0, 4, 8, 12)}; assert len(beats) >= .85 * 4 * (b - a), n

def test_the_kick_marks_phrases_and_is_not_the_same_bar_everywhere():
    k = plan()["kick"]; ends = [b for b in range(16, 32) if (b - 16) % 8 == 7]
    assert any((br, 15) in {(x[0], x[1]) for x in k} or (br, 12) not in {(x[0], x[1]) for x in k} for br in ends)      # pickup or beat 4 out at phrase ends
    assert not bars_of(k, 48, 52) and len(bars_of(k, 0, 4)) < len(bars_of(k, 16, 20))                                  # no kick in the break, thin intro
    assert A.drum_static({"kick": k})["kick"] <= A.DRUM_STATIC_MAX

def test_the_clap_has_a_job_none_low_one_beat_mid_both_high():
    e = A.energy_arc(SECS); c = plan()["clap"]
    assert not bars_of(c, 0, 16) and not bars_of(c, 48, 52)                                                             # intro / break: no clap
    mid = {st for br, st, v in bars_of(c, 16, 32)}; hi = {st for br, st, v in bars_of(c, 88, 104)}
    assert (e["home1"] < .7 and mid == {12}) or (e["home1"] >= .7 and {4, 12} <= mid)
    assert {4, 12} <= hi and 15 in hi

def test_static_report_catches_a_flat_loop_and_is_quiet_on_the_plan():
    flat = {"kick": [(b, s, 120) for b in range(64) for s in (0, 4, 8, 12)]}
    assert A.drum_static(flat)["kick"] == 64
    t = types.SimpleNamespace(drum_events=flat); assert A.drum_static_problems(t)
    A.log_drums(t, plan()); assert A.drum_static_problems(t) == [] and set(t.drum_events) == {"kick", "clap"}
    assert A.drum_static_problems(types.SimpleNamespace()) == []
