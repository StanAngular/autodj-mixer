"""P134: harmony as a plan of the whole track (chords.py) and lines written against it (lines.py)."""
import numpy as np
import pytest
from autodj.compose import chords as C, lines as L

SECS = [(0, 8, "intro"), (8, 24, "home1"), (24, 36, "journey1"), (36, 52, "home2"), (52, 60, "break"), (60, 64, "build"), (64, 80, "home3"), (80, 88, "outro")]
KEY = C.key_pcs("C", "minor")

# ---- chords ------------------------------------------------------------------------------------------------------------
def test_chord_knows_its_scale_colours_and_avoid_notes():
    c = C.Chord("C", "m9"); r = c.roles(KEY)
    assert c.name == "Cm9" and c.pcs == [0, 3, 7, 10, 2] and c.scale(KEY)[1] == "aeolian"
    assert r[5] == "tension" and r[8] == "avoid" and r[2] == "chord" and c.role(1, KEY) == "out"          # 11 colours, b6 is avoided, Db is outside
    assert c.scale(C.key_pcs("C", "dorian"))[1] == "dorian" and c.role(9, C.key_pcs("C", "dorian")) == "tension"   # in a dorian key the 6th is a colour
    M = C.key_pcs("C", "major"); f = C.Chord("F", "maj7"); assert f.scale(M)[1] == "lydian" and f.role(10, M) == "out" and f.role(11, M) == "tension"   # IV is lydian: B = #11
    assert C.Chord("C", "maj7").role(5, M) == "avoid" and C.Chord("C", "maj7").role(9, M) == "tension"         # the 4th over a major chord is the classic avoid note
    g = C.Chord("G", "7#9"); assert g.role(0, KEY) == "avoid" and g.role(8, KEY) == "tension"            # a dominant keeps its altered colours
    assert C.Chord("D", "", bass="C").name == "D/C" and C.Chord("D", "", bass="C").role(0) == "chord"
    assert c.colours(KEY)[0] == 2 and 5 in c.colours(KEY)[:3]
    with pytest.raises(ValueError): C.Chord("C", "m13b5")

def test_tension_orders_rest_colour_and_dominant():
    t = lambda r, q: C.Chord(r, q).tension("C", KEY)
    assert t("C", "m9") < t("Ab", "maj9") < t("G", "7#9") and t("Db", "maj7#11") > t("Eb", "maj9")

def test_every_idiom_is_eight_bars_in_any_key_and_has_more_than_four_chords_or_rhythm():
    for name in C.IDIOMS:
        for tonic in ("C", "F#", 9):
            s = C.sentence(name, tonic); assert sum(n for n, _ in s) == 128 and s[0][1].root in {(C.pc_of(tonic) + d) % 12 for d in (0, 5)}
        if name != "old_loop":
            lens = {n for n, _ in C.sentence(name, "C")}; assert len(lens) > 1 or len({c for _, c in C.sentence(name, "C")}) > 4, name   # not 4 equal bars
    assert "dorian_vamp" in C.idioms("deep") and "old_loop" not in C.idioms() and set(C.idioms(mode="major")) == {"lydian_float", "soul_major"}

# ---- operators ---------------------------------------------------------------------------------------------------------
def test_operators_vary_a_progression_without_changing_its_length():
    rng = np.random.default_rng(1); H = C.sentence("dorian_vamp", "C"); total = lambda p: sum(n for n, _ in p)
    up = C.extend(H, 1); down = C.extend(H, -1)
    assert [c.qual for _, c in up][:2] == ["m11", "13"] and [c.qual for _, c in down][:2] == ["m7", "9"] and C.extend(C.extend(H, 5), -9)[0][1].qual == "m"
    assert all(c.bass == 0 for _, c in C.pedal(H, "C")) and total(C.merge(H, 32)) == 128 and len(C.merge(H, 32)) == 4
    ps = C.passing(H, rng, p=1.0); sl = [(n, c) for n, c in ps if n == 2]
    assert total(ps) == 128 and sl and all(min((c.root - nxt.root) % 12, (nxt.root - c.root) % 12) == 1 and c.qual == nxt.qual
                                          for (n, c), (_, nxt) in zip(ps, ps[1:]) if n == 2)             # a slide chord: the next shape a semitone away
    pu = C.push(H, rng, p=1.0); assert total(pu) == 128 and [c for _, c in pu] == [c for _, c in H] and any(n % 16 == 14 for n, _ in pu)
    ta = C.turnaround(H, "C", "neapolitan"); assert total(ta) == 128 and ta[-1][1] == C.Chord("Db", "maj7") and ta[-1][0] == 8
    assert C.tritone([(16, C.Chord("G", "7")), (16, C.Chord("C", "m9"))])[0][1].name == "Db7#11"
    assert total(C.cycle(H, 200)) == 200 and total(C.cycle(H, 40)) == 40

def test_inversions_make_the_bass_walk_by_step():
    P = [(32, C.Chord("C", "")), (32, C.Chord("G", "")), (32, C.Chord("A", "m")), (32, C.Chord("F", ""))]; inv = C.inversions(P)
    line = [c.bass_pc for _, c in inv]; jump = lambda xs: sum(min((a - b) % 12, (b - a) % 12) for a, b in zip(xs, xs[1:]))
    assert line[0] == 0 and jump(line) < jump([0, 7, 9, 5]) and inv[1][1].name == "G/B"

# ---- voicings ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("style", ["close", "drop2", "rootless", "quartal", "spread"])
def test_voicings_are_in_range_belong_to_the_chord_and_say_which_chord_it_is(style):
    P = C.Plan.build("C", SECS, "dorian_vamp", "line_cliche", seed=2); V = P.voicings(style, 48, 79)
    assert len(V) == len(P.slots)
    for (s0, n, c, _), (vs, vn, v) in zip(P.slots, V):
        sc = set(c.scale(P.key)[0])
        assert (vs, vn) == (s0, n) and v == sorted(v) and 43 <= v[0] and v[-1] <= 84 and len(v) >= 3
        assert all(x % 12 in sc for x in v) and ({c.pcs[1]} | set(c.pcs[3:4])) & {x % 12 for x in v}     # 3rd (or sus) or 7th is there

def test_voice_leading_moves_less_than_block_chords_and_avoids_minor_ninths():
    P = C.Plan.build("C", SECS, "neo_soul", None, seed=2); V = [v for *_, v in P.voicings("drop2", 50, 76)]
    led = np.mean([abs(a[-1] - b[-1]) for a, b in zip(V, V[1:])])
    block = [[48 + c.root + i for i in c.iv[:4]] for _, _, c, _ in P.slots]; blk = np.mean([abs(a[-1] - b[-1]) for a, b in zip(block, block[1:])])
    assert led < 2.0 < blk
    bad = sum(1 for v, (_, _, c, _) in zip(V, P.slots) for i, a in enumerate(v) for b in v[i + 1:] if b - a in (13, 25) and c.family != "dom")
    assert bad == 0 and all(v[-1] - v[-2] != 1 for v in V)

@pytest.mark.parametrize("home", ["dorian_vamp", "planing_m9", "neo_soul", "soul_major", "phrygian_dark"])
def test_no_voicing_has_a_semitone_or_minor_ninth_inside_with_or_without_a_top_line(home):
    for style in ("drop2", "close", "rootless", "spread", "quartal"):
        for use_top in (False, True):
            P = C.Plan.build("C", SECS, home, None, seed=2); top = L.topline(P, np.random.default_rng(2), 65, 77)[0] if use_top else None
            for (_, _, c, _), (_, _, v) in zip(P.slots, P.voicings(style, 50, 78, top=top)):
                assert not any(b - a == 1 or (b - a in (13, 25) and c.family != "dom") for i, a in enumerate(v) for b in v[i + 1:]), (style, use_top, c.name, v)

def test_a_given_top_line_is_harmonised():
    P = C.Plan.build("C", SECS, "aeolian_wide", None, seed=1); top, tl = L.topline(P, np.random.default_rng(1), 67, 79); V = P.voicings("drop2", 50, 79, top=top)
    assert [v[-1] for *_, v in V] == top and len(set(top)) >= 4 and max(abs(a - b) for a, b in zip(top, top[1:])) <= 7
    assert all(P.slots[i][2].role(m % 12, P.key) != "avoid" for i, m in enumerate(top)) and len(tl) == len(P.slots)

# ---- the plan ------------------------------------------------------------------------------------------------------------
def test_plan_covers_the_track_and_treats_sections_by_role():
    P = C.Plan.build("C", SECS, "dorian_vamp", "line_cliche", seed=3); d = P.describe()
    assert P.slots[0][0] == 0 and all(a[0] + a[1] == b[0] for a, b in zip(P.slots, P.slots[1:])) and P.slots[-1][0] + P.slots[-1][1] == 88 * 16
    assert d["home1"].startswith("Cm9 | % | F13") and d["journey1"].startswith("Cm9 | % | Cm7/Bb") and d["home1"] != d["home2"][:len(d["home1"])]
    assert all(c.bass == 0 for s0, n, c, nm in P.slots if nm in ("intro", "outro", "break")) and all(c.bass == 7 for s0, n, c, nm in P.slots if nm == "build")
    for idi in C.IDIOMS: assert all(c.family in ("minor", "major", "sus") for s0, n, c, nm in C.Plan.build("C", SECS, idi, None, seed=1).slots if nm == "break"), idi
    assert max(n for s0, n, c, nm in P.slots if nm == "break") == 64 and P.at(8 * 16).name == "Cm9" and P.chord_of_bar(8) == [0, 3, 7, 10, 2] and P.root_of_bar(26) == 10
    first, second = [(n, c) for s0, n, c, nm in P.slots if nm == "home1" and s0 < 16 * 16], [(n, c) for s0, n, c, nm in P.slots if nm == "home1" and s0 >= 16 * 16]
    assert first != second and first == C.sentence("dorian_vamp", "C")                                     # A, then a varied A'
    assert len({c for *_, c, _ in P.slots}) >= 10 and len(P.tension()) == 88 and max(P.tension()) > min(P.tension()) + .2

def test_plan_is_repeatable_differs_by_seed_and_transposes():
    a = C.Plan.build("C", SECS, "garage_steps", "soul_major", seed=3, journey_shift=3); b = C.Plan.build("C", SECS, "garage_steps", "soul_major", seed=3, journey_shift=3)
    c = C.Plan.build("C", SECS, "garage_steps", "soul_major", seed=4, journey_shift=3); e = C.Plan.build("E", SECS, "garage_steps", "soul_major", seed=3, journey_shift=3)
    assert a.slots == b.slots and a.slots != c.slots and a.fingerprint() == e.fingerprint() and a.describe()["journey1"].startswith("Ebmaj9")
    assert a.fingerprint() != C.Plan.build("C", SECS, "old_loop", None, seed=3).fingerprint() and a.fingerprint().startswith("0:m9 2:m7 3:maj9")
    assert [C.role_of(n) for n in ("build", "break", "b", "a", "home3", "half1", "chop", "step", "outro", "whatever")] == ["build", "break", "journey", "home", "home", "journey", "home", "intro", "outro", "home"]

def test_attach_reports_the_harmony_on_the_track():
    class T: pass
    t = T(); P = C.Plan.build("A", SECS, "phrygian_dark", None, seed=1).attach(t)
    assert t.harmony["tonic"] == "A" and t.harmony["home"] == "phrygian_dark" and "Am9" in t.harmony["chart"]["home1"] and t.harmony["fingerprint"] == P.fingerprint()

# ---- bass ----------------------------------------------------------------------------------------------------------------
def test_bass_marks_every_change_stays_in_range_and_approaches_the_next_root():
    P = C.Plan.build("C", SECS, "line_cliche", None, seed=2); V = P.voicings("drop2", 50, 76); B = P.bass(np.random.default_rng(3), 28, 45, against=V)
    on = {s: m for s, ln, m, v in B}
    assert all(28 <= m <= 45 for *_, m, v in B) and all(B[i][0] + B[i][1] <= B[i + 1][0] for i in range(len(B) - 1))
    changes = [(s0, c) for s0, n, c, nm in P.slots if s0 % 2 == 0]; assert all(on.get(s0, -1) % 12 == c.bass_pc for s0, c in changes)
    appr = [(a, b) for a, b in zip(B, B[1:]) if a[3] == 76]; assert appr and all(abs(a[2] - b[2]) in (1, 2) and a[1] <= 2 for a, b in appr)
    f = L.fit(B, P, L.context(P, V)); assert f["avoid"] < .05 and f["rub"] < .03
    ped = P.bass(np.random.default_rng(3), 28, 45, style="pedal"); assert {m % 12 for *_, m, v in ped if v == 104} == {0}
    line = P.bass(np.random.default_rng(3), 28, 45, style="line"); assert len(line) > 50

# ---- lines ---------------------------------------------------------------------------------------------------------------
def _setup(home="dorian_vamp", journey="line_cliche", seed=5):
    rng = np.random.default_rng(seed); P = C.Plan.build("C", SECS, home, journey, seed=seed); top, _ = L.topline(P, rng, 67, 79)
    V = P.voicings("drop2", 50, 79, top=top); B = P.bass(rng, 28, 45, against=V); return rng, P, V, B, L.context(P, V, B)

@pytest.mark.parametrize("home", [n for n in C.IDIOMS])
def test_hook_never_holds_an_avoid_note_or_rubs_whatever_the_harmony(home):
    rng, P, V, B, ctx = _setup(home, None); H = L.hook(P, rng, 60, 79, 8, ctx); full = L.tile(H, P, 60, 79, [8, 16, 24, 36, 44, 64, 72], ctx, origin=8)
    f = L.fit(full, P, ctx)
    assert f["avoid"] == 0 and f["rub"] == 0 and f["notes"] > 60 and f["range"] >= 5 and all(60 <= m <= 79 for *_, m, v in full)

def test_hook_is_one_idea_refitted_not_a_new_tune_every_two_bars():
    rng, P, V, B, ctx = _setup(); H = L.hook(P, rng, 60, 79, 8, ctx); rh = lambda a, b: [(s - a * 16, ln) for s, ln, m, v in H if a * 16 <= s < b * 16]
    assert rh(8, 10) == rh(10, 12) == rh(12, 14) and rh(14, 15) == rh(8, 9) and H[-1][1] == 10                 # same rhythm; B ends on a long note
    last = H[-1]; c = P.at(last[0]); assert last[2] % 12 in c.pcs[:3]
    assert [m for *_, m, v in H if 160 <= _[0] < 192] != [m for *_, m, v in H if 128 <= _[0] < 160]            # A' is not a copy

def test_tile_reharmonises_the_hook_over_the_journey():
    rng, P, V, B, ctx = _setup("garage_steps", "soul_major"); H = L.hook(P, rng, 60, 79, 8, ctx); J = L.tile(H, P, 60, 79, [24], ctx, origin=8)
    assert [(s - 24 * 16, ln) for s, ln, m, v in J] == [(s - 8 * 16, ln) for s, ln, m, v in H] and [m for *_, m, v in J] != [m for *_, m, v in H]
    assert L.fit(J, P, ctx)["avoid"] == 0 and sum(a != b for (_, _, a, _), (_, _, b, _) in zip(H, J)) < len(H)   # some notes stay: it is still the hook

def test_lines_use_colours_not_only_chord_tones():
    cols = []
    for seed in range(6):
        rng, P, V, B, ctx = _setup("line_cliche", None, seed); cols.append(L.fit(L.hook(P, rng, 60, 79, 8, ctx), P, ctx)["colour"])
    assert np.mean(cols) > .12 and max(cols) < .7

def test_ostinato_is_a_polymeter_that_bends_only_where_it_must():
    rng, P, V, B, ctx = _setup(); O = L.ostinato(P, rng, 72, 88, 8, 24, n=3, step=2, ctx=ctx); f = L.fit(O, P, ctx, 1)
    st = [s for s, *_ in O]; acc = [s % 16 for s, ln, m, v in O if v > 84]
    assert f["avoid"] == 0 and f["rub"] == 0 and set(np.diff(st)) <= {2, 4} and len(set(acc)) >= 6           # the accent drifts through the bar (3 x 2 = 6 sixteenths)
    from collections import Counter
    top3 = sum(c for _, c in Counter(m for *_, m, v in O).most_common(3)); assert top3 / len(O) > .7          # mostly its own three notes
    assert len(L.ostinato(P, rng, 72, 88, 8, 24, n=3, step=2, ctx=ctx, rest_every=4)) < len(O)

def test_arp_runs_through_the_voicing_and_does_not_restart_with_the_chord():
    rng, P, V, B, ctx = _setup(); A = L.arp(P, V, rng, 8, 16, step=1)
    assert len(A) == 128 and all(P.at(s).role(m % 12, P.key) != "avoid" for s, ln, m, v in A)
    acc = [s for s, ln, m, v in A if v > 80]; assert len({s % 16 for s in acc}) > 4

def test_counter_answers_in_the_rests_and_moves_against_the_melody():
    rng, P, V, B, ctx = _setup(); H = L.tile(L.hook(P, rng, 64, 79, 8, ctx), P, 64, 79, [8, 16], ctx, origin=8)
    Cn = L.counter(P, H, rng, 55, 67, L.context(P, V, B, H)); busy = {t for s, ln, *_ in H for t in range(s, s + ln)}
    assert Cn and not any(t in busy for s, ln, *_ in Cn for t in range(s, s + ln)) and L.fit(Cn, P, L.context(P, V, B, H))["rub"] == 0

def test_fit_sees_a_wrong_line_and_fix_repairs_it():
    rng, P, V, B, ctx = _setup(); wrong = [(8 * 16, 8, 68, 90), (9 * 16, 8, 61, 90), (10 * 16, 6, 70, 90)]      # Ab over Cm9 (avoid), Db (outside), Bb over F13 (avoid)
    f = L.fit(wrong, P, ctx); assert f["avoid"] == 1.0
    g = L.fix(wrong, P, 60, 79, ctx); assert L.fit(g, P, ctx)["avoid"] == 0 and L.fit(g, P, ctx)["rub"] == 0 and all(abs(a[2] - b[2]) <= 3 for a, b in zip(wrong, g))
    assert L.clean(62, 0, 4, [[61]] * 8) is False and L.clean(62, 0, 4, [[50]] * 8) is True and L.clean(62, 0, 4, None) is True
