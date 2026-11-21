"""P160: the home at the peak of the energy arc is the same sentence one colour richer; without arc nothing changes (both sides)"""
from autodj.compose import chords as C, arrange as A

SECS = [(0, 8, "intro"), (8, 24, "home1"), (24, 40, "journey1"), (40, 56, "home2"), (56, 64, "outro")]

def test_peak_home_is_richer_same_roots_same_scale():
    base = C.Plan.build("A", SECS, "epic_minor", "minor_plagal", seed=2, allow_repeat="t"); arc = A.energy_arc(SECS)
    p = C.Plan.build("A", SECS, "epic_minor", "minor_plagal", seed=2, allow_repeat="t", arc=arc)
    h1 = [(s0, c) for s0, n, c, nm in p.slots if nm == "home1"]; h2 = [c for s0, n, c, nm in p.slots if nm == "home2"]; b2 = [c for s0, n, c, nm in base.slots if nm == "home2"]
    assert [c.root for c in h2] == [c.root for c in b2] and [c.qual for c in h2] != [c.qual for c in b2]          # same roots, other colours
    assert sum(len(c.pcs) for c in h2) > sum(len(c.pcs) for c in b2) and all(set(c.pcs) <= p.key for c in h2)    # richer, still in the scale
    assert [c for s0, c in h1] == [c for s0, n, c, nm in base.slots if nm == "home1"] and p.meta["peak_colour"] == ["home2"]

def test_without_arc_or_without_a_peak_home_the_plan_is_unchanged():
    a = C.Plan.build("A", SECS, "epic_minor", "minor_plagal", seed=2, allow_repeat="t"); b = C.Plan.build("A", SECS, "epic_minor", "minor_plagal", seed=2, allow_repeat="t", arc={"home1": .5})
    assert [s[2] for s in a.slots] == [s[2] for s in b.slots] and "peak_colour" not in b.meta
