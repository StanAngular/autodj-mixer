"""P158: register_above, lines.story by section role / energy, the lead-under-kick report (both sides)"""
import types, numpy as np
from autodj.compose import chords as C, lines as L, arrange as A, ears

SECS = [(0, 8, "intro"), (8, 24, "home1"), (24, 40, "journey1"), (40, 44, "break"), (44, 48, "build"), (48, 64, "home2"), (64, 80, "outro")]
def setup():
    P = C.Plan.build("A", SECS, "epic_minor", "minor_plagal", seed=3, allow_repeat="test"); V = P.voicings("drop2", 50, 74)
    lo, hi = L.register_above(V); h = L.hook(P, np.random.default_rng(1), lo, hi, 8); return P, V, lo, hi, h

def test_the_lead_register_sits_above_the_chords():
    P, V, lo, hi, h = setup(); top = max(max(v) for *_, v in V); assert lo > top and hi - lo == 12 and all(lo <= m <= hi for _, _, m, _ in h)
    assert L.register_above([(0, 16, [80, 84, 87])], ceiling=88) == (76, 88)                           # never above the ceiling

def test_story_follows_the_sections_and_peaks_in_the_last_home():
    P, V, lo, hi, h = setup(); arc = A.energy_arc(SECS); s = L.story(h, P, np.random.default_rng(2), lo, hi, SECS, arc, origin=8)
    inb = lambda a, b: [n for n in s if a * 16 <= n[0] < b * 16]
    assert inb(0, 8) and len(inb(0, 8)) < len(inb(8, 16))                       # intro: a teaser, less than the hook
    assert not inb(44, 48) and not inb(64, 80)                                   # build and outro: no hook
    peak = np.mean([m for _, _, m, _ in inb(48, 56)]); first = np.mean([m for _, _, m, _ in inb(8, 16)]); assert peak > first          # the peak is higher
    assert all(lo <= m <= hi for _, _, m, _ in s)

def test_lead_report_both_sides():
    bo = {"heard_db": {"kick": 0.0, "hook": -5.0}}; assert ears.lead_problems(bo, "hook")
    assert ears.lead_problems({"heard_db": {"kick": 0.0, "hook": -2.0}}, "hook") == [] and ears.lead_problems(bo, None) == [] and ears.lead_problems(None, "hook") == []
