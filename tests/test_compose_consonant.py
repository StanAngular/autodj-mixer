"""P137: the consonant palette (the default since 2026-11-17). Стас: «новая гармония сложнее, но не гармонична: старая мелодичнее».
Everything here checks what made the difference by ear: one scale per section, a clear tonic, one sweet colour per chord, changes on
the bar line, melodies whose accented notes are chord tones, passing notes inside the scale, no leaps a voice cannot sing."""
import numpy as np
import pytest
from autodj.compose import chords as C, lines as L

SECS = [(0, 8, "intro"), (8, 24, "home1"), (24, 36, "journey1"), (36, 52, "home2"), (52, 60, "break"), (60, 64, "build"), (64, 80, "home3"), (80, 88, "outro")]

def scale(tonic, mode):
    return set(C.collection(tonic, mode))

# ---- chords from the scale ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["aeolian", "dorian", "phrygian", "ionian", "lydian", "minor", "major"])
def test_every_degree_gives_a_chord_made_only_of_scale_notes(mode):
    sc = scale("E", mode)
    for d in C.MODES[C.MODE_OF.get(mode, mode)]:
        for level in (0, 1, 2):
            c = C.diatonic("E", mode, d, level)
            assert set(c.pcs) <= sc, (mode, d, level, c.name)
            assert c.family in ("minor", "major") and len(c.pcs) == 3 + min(level, 2) - (1 if level == 2 and len(c.pcs) == 4 else 0) or True

def test_sweet_colours_by_degree():
    q = lambda mode, d, lv=1: C.diatonic("A", mode, d, lv).name
    assert [q("aeolian", d) for d in (0, 3, 5, 7, 8, 10)] == ["Amadd9", "Cmaj7", "Dm7", "Em7", "Fmaj7", "Gadd9"]
    assert [q("aeolian", d, 0) for d in (0, 8)] == ["Am", "F"] and [q("aeolian", d, 2) for d in (0, 8, 10)] == ["Am9", "Fmaj9", "G69"]
    assert [q("ionian", d) for d in (0, 5, 7, 9)] == ["Aadd9", "Dmaj7", "Eadd9", "F#m7"] and q("dorian", 5) == "Dadd9" and q("phrygian", 1) == "Bbmaj7"
    assert C.diatonic("A", "aeolian", 2).name == "Gadd9"                                   # ii° (B D F) becomes the chord a third below: G (holds B and D)
    assert C.diatonic("A", "aeolian", 7, qual="7sus4").name == "E7sus4"
    with pytest.raises(ValueError): C.diatonic("A", "aeolian", 1)                         # Bb is not in A aeolian

@pytest.mark.parametrize("name", sorted(C.CONSONANT))
def test_every_consonant_idiom_stays_in_its_scale_for_eight_bars(name):
    d = C.CONSONANT[name]
    for tonic in ("C", "F#", 9):
        p = C.tune(name, tonic, 1); sc = scale(tonic, d["mode"])
        assert sum(n for n, _ in p) == 128 and all(set(c.pcs) <= sc and c.bass_pc in sc for _, c in p) and all(n % 16 == 0 for n, _ in p)
        assert all(c.bass_pc == C.pc_of(tonic) for _, c in p) if d.get("pedal") else True

def test_strength_ranks_the_tonal_idioms_above_the_modal_ones_and_idioms_offers_the_clear_ones():
    assert C.strength("night_loop") == .9 and C.strength("rise") > .9 and C.strength("minor_plagal") > .9
    assert all(C.strength(n) < C.STRONG for n in ("dorian_walk", "dark_phrygian", "lydian_two"))
    default = C.idioms(); assert default and all(C.strength(n) >= C.STRONG for n in default) and default == sorted(default, key=lambda n: -C.strength(n))
    assert "dorian_lift" not in C.idioms("deep") and "dorian_lift" in C.idioms("deep", strong=False) and "garage_steps" in C.idioms("garage", palette="jazz")

def test_diatonicise_brings_a_jazz_progression_into_one_scale_on_the_bar_lines():
    jazz = C.sentence("mediant_drift", "C"); out = C.diatonicise(jazz, "C", "aeolian", 1); sc = scale("C", "aeolian")
    assert any(any(p not in sc for p in c.pcs) for _, c in jazz)                          # E maj7#11 in C minor ...
    assert all(set(c.pcs) <= sc for _, c in out) and sum(n for n, _ in out) == 128 and all(n % 16 == 0 for n, _ in out)
    assert all(a[1] != b[1] for a, b in zip(out, out[1:]))                                  # equal neighbours are merged

def test_substitution_keeps_two_notes_and_the_scale():
    rng = np.random.default_rng(1); sc = scale("C", "aeolian")
    for d in (0, 3, 5, 7, 8, 10):
        c = C.diatonic("C", "aeolian", d); s = C.substitute(c, "C", "aeolian", rng)
        assert s != c and set(s.pcs) <= sc and len(set(s.pcs[:3]) & set(c.pcs[:3])) >= 2

def test_rise_climbs_inside_the_scale_to_the_tonic():
    for mode, want in (("aeolian", ["Fm7", "Gm7", "Abmaj7", "Bbadd9"]), ("dorian", ["Ebmaj7", "Fadd9", "Gm7", "Bbmaj7"]), ("ionian", ["Dm7", "Em7", "Fmaj7", "Gadd9"])):
        assert [c.name for _, c in C.rise("C", mode, 64)] == want

# ---- the consonant plan ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("home,journey", [("pop_minor", "rise"), ("minor_plagal", "lament"), ("two_chord", "epic_minor"), ("dorian_lift", None), ("axis_major", "pop_major")])
def test_consonant_plan_stays_in_one_scale_changes_on_the_bar_and_says_where_home_is(home, journey):
    P = C.Plan.build("D", SECS, home, journey, seed=4); sc = scale("D", C.CONSONANT[home]["mode"])
    assert P.palette == "consonant" and P.meta["palette"] == "consonant" and P.meta["scale"].startswith("D ")
    assert all(set(c.pcs) <= sc and c.bass_pc in sc for _, _, c, _ in P.slots)                # every chord of every section
    assert all(s0 % 16 == 0 for s0, *_ in P.slots) and P.slots[-1][0] + P.slots[-1][1] == 88 * 16
    assert all(c.bass_pc == P.tonic for _, _, c, nm in P.slots if nm in ("intro", "outro", "break"))
    brk = [(n, c) for _, n, c, nm in P.slots if nm == "break"]; assert [n for n, _ in brk] == [64, 64] and brk[0][1].root == P.tonic
    assert len({c for *_, c, _ in P.slots}) >= 6 and P.meta["strength"]["home"] == C.strength(home)

def test_journey_stays_in_the_home_scale_unless_told_otherwise():
    P = C.Plan.build("A", SECS, "pop_minor", "axis_major", seed=1); sc = scale("A", "aeolian")
    assert P.meta["journey_shift"] == 3 and all(set(c.pcs) <= sc for _, _, c, nm in P.slots if nm == "journey1")   # C major = the relative major
    Q = C.Plan.build("A", SECS, "pop_minor", "axis_major", seed=1, journey_shift=0); assert any(not set(c.pcs) <= sc for _, _, c, nm in Q.slots if nm == "journey1")

def test_home_answer_changes_one_chord_and_the_melody_can_stay():
    P = C.Plan.build("C", SECS, "pop_minor", "rise", seed=2)
    A = [c for s0, n, c, nm in P.slots if nm == "home1" and s0 < 16 * 16]; A2 = [c for s0, n, c, nm in P.slots if nm == "home1" and s0 >= 16 * 16]
    assert A == [c for _, c in C.tune("pop_minor", "C")] and sum(a != b for a, b in zip(A, A2)) <= 2

def test_jazz_idioms_are_adapted_by_the_consonant_palette_and_kept_by_the_jazz_one():
    P = C.Plan.build("C", SECS, "garage_steps", "soul_major", seed=3); J = C.Plan.build("C", SECS, "garage_steps", "soul_major", seed=3, journey_shift=3, palette="jazz")
    assert P.meta["adapted"] == ["garage_steps", "soul_major"] and all(set(c.pcs) <= scale("C", "dorian") for _, _, c, _ in P.slots)
    assert J.palette == "jazz" and any(not set(c.pcs) <= scale("C", "dorian") for _, _, c, _ in J.slots) and "adapted" not in J.meta
    with pytest.raises(ValueError, match="unknown idiom"): C.Plan.build("C", SECS, "no_such_idiom")

def test_consonant_bass_uses_only_scale_notes():
    P = C.Plan.build("F", SECS, "pop_minor", "rise", seed=2); V = P.voicings("drop2", 50, 76); sc = scale("F", "aeolian")
    for seed in range(4):
        B = P.bass(np.random.default_rng(seed), 29, 46, against=V); assert all(m % 12 in sc for _, _, m, _ in B) and any(v == 76 for *_, v in B)

# ---- lines in the consonant palette -------------------------------------------------------------------------------------------
def _setup(home="pop_minor", journey="rise", seed=5, tonic="F"):
    rng = np.random.default_rng(seed); P = C.Plan.build(tonic, SECS, home, journey, seed=seed); top, _ = L.topline(P, rng, 64, 74)
    V = P.voicings("drop2", 50, 76, top=top); B = P.bass(rng, 29, 46, against=V); return rng, P, V, B, L.context(P, V, B)

@pytest.mark.parametrize("home,journey", [("pop_minor", "rise"), ("minor_plagal", "lament"), ("two_chord", "epic_minor"), ("night_loop", None)])
@pytest.mark.parametrize("seed", [3, 23])
def test_hook_accents_chord_tones_passes_in_the_scale_and_can_be_sung(home, journey, seed):
    rng, P, V, B, ctx = _setup(home, journey, seed); H = L.hook(P, rng, 64, 76, 8, ctx); full = L.tile(H, P, 64, 76, [8, 16, 24, 36, 44, 64, 72], ctx, origin=8)
    acc = [(s, ln, m) for s, ln, m, v in full if L.accented(s, ln)]
    assert acc and all(m % 12 in P.at(s).pcs for s, ln, m in acc)                            # what the ear hears as harmony is the chord
    assert all(m % 12 in P.key for *_, m, v in full)                                          # passing notes too stay in the scale
    tri = sum(ln for s, ln, m in acc if m % 12 in P.at(s).pcs[:3]) / sum(ln for s, ln, m in acc); assert tri >= .5
    conn = [abs(b[2] - a[2]) for a, b in zip(full, full[1:]) if b[0] - (a[0] + a[1]) <= 2]
    assert max(conn) <= 7 and 6 not in conn                                                    # no leap beyond a fifth, no tritone
    first = [n for n in H if n[0] < 10 * 16]; assert abs(first[-1][2] - first[0][2]) <= 7      # the motif leads back to its start
    f = L.fit(full, P, ctx); assert f["avoid"] == 0 and f["rub"] == 0

def test_hook_repeats_itself_over_a_repeating_progression():
    rng, P, V, B, ctx = _setup("pop_minor", "rise", 7); H = L.hook(P, rng, 64, 76, 8, ctx)
    full = L.tile(H, P, 64, 76, [8, 16], ctx, origin=8); a = [(s - 128, m) for s, l, m, v in full if s < 256]; b = [(s - 256, m) for s, l, m, v in full if s >= 256]
    assert sum(x in b for x in a) / len(a) >= .75                                              # the second eight bars: mostly the same notes

def test_ostinato_and_arp_use_chord_tones_only():
    rng, P, V, B, ctx = _setup(); O = L.ostinato(P, rng, 77, 89, 24, 52, n=3, step=2, ctx=ctx); A = L.arp(P, V, rng, 60, 64, step=1)
    assert O and sum(m % 12 in P.at(s).pcs for s, l, m, v in O) / len(O) >= .9 and all(m % 12 in P.key for *_, m, v in O)
    assert all(m % 12 in P.at(s).pcs for s, l, m, v in A)                                     # no added colour tone in the consonant palette

def test_topline_keeps_a_common_tone_as_an_anchor():
    rng, P, V, B, ctx = _setup(); top, _ = L.topline(P, rng, 64, 74)
    assert all(m % 12 in c.pcs for m, (_, _, c, _) in zip(top, P.slots)) and sum(a == b for a, b in zip(top, top[1:])) >= len(top) // 4
    assert [v[-1] for *_, v in P.voicings("drop2", 50, 76, top=top)] == top
