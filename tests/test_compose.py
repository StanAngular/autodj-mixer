"""autodj.compose: every gate is tested on both sides (what it blocks AND what it lets through), plus a tiny end-to-end run."""
import json, os, textwrap
import numpy as np
from autodj.compose import Track
from autodj.compose.checks import gates
from autodj.compose import fx

OK_MASTER = {"limiter_max_db": 1.0}
def ok_metrics(**kw):
    m = {"high_db": -25.0, "sub_mean": .25, "sub_max": .3, "jump_db": 1.0, "break_drop_db": 3.0, "voice_lift": [[30, "v1", 3.0]], "spikes": []}
    m.update(kw); return m

def codes(m, ms=OK_MASTER): return {c for c, _ in gates(m, ms)}

def test_clean_track_passes_all_gates():
    assert gates(ok_metrics(), OK_MASTER) == []

def test_limiter_gate_both_sides():
    assert "limiter" in codes(ok_metrics(), {"limiter_max_db": 4.3})
    assert "limiter" not in codes(ok_metrics(), {"limiter_max_db": 3.0})

def test_high_gate_both_sides():
    assert "high" in codes(ok_metrics(high_db=-15.8))      # Sieben v1, «шик-шик»
    assert "high" not in codes(ok_metrics(high_db=-23.1))  # Sieben v2, accepted

def test_sub_gate_both_sides():
    assert "sub" in codes(ok_metrics(sub_mean=.40))
    assert "sub" in codes(ok_metrics(sub_max=.55))
    assert "sub" not in codes(ok_metrics(sub_mean=.30, sub_max=.47))

def test_jump_and_break_gates_both_sides():
    assert "jump" in codes(ok_metrics(jump_db=5.0)) and "jump" not in codes(ok_metrics(jump_db=3.5))
    assert "break" in codes(ok_metrics(break_drop_db=11.0)) and "break" not in codes(ok_metrics(break_drop_db=7.0))

def test_voice_gate_both_sides():
    assert "voice" in codes(ok_metrics(voice_lift=[[20, "v1", 10.1]]))
    assert "voice" not in codes(ok_metrics(voice_lift=[[20, "v1", 5.5], [40, "v2", -1.0]]))

def test_spike_gate_both_sides():
    assert "spikes" in codes(ok_metrics(spikes=[1.2])) and "spikes" not in codes(ok_metrics(spikes=[]))

def test_add_levels_are_relative_to_first_layer():
    trk = Track(120, 4, seed=1).sections([(0, 4, "A", {"a": 1, "b": 1})])
    x = np.random.default_rng(0).normal(0, .1, (trk.N, 2)).astype(np.float32)
    trk.add("a", x, 1.0); first = trk.mix.copy(); trk.add("b", x * 7, .5)
    b = trk.mix - first; r = lambda z: np.sqrt(np.mean(z ** 2))
    assert abs(r(b) / r(first) - .5) < .02

def test_section_env_silences_layer_outside_its_sections():
    trk = Track(120, 8, seed=1).sections([(0, 4, "A", {"a": 1}), (4, 8, "B", {})])
    e = trk.env("a"); assert e[trk.i(1)] == 1 and e[trk.i(6)] == 0

def test_tapestop_keeps_length_and_silences_gap():
    trk = Track(120, 4, seed=1).sections([(0, 4, "A", {})]); trk.mix[:] = .3
    n = len(trk.mix); gap_t = fx.tapestop(trk, 2, beats=1, gap_beats=2, tail=0)
    assert len(trk.mix) == n and np.allclose(trk.mix[int(gap_t * trk.sr) + 10:trk.i(2)], 0) and trk.mix[trk.i(2) + 10, 0] == np.float32(.3)

def test_end_to_end_run(tmp_path, monkeypatch):
    from autodj.compose.run import main
    monkeypatch.setenv("AUTODJ_COMPOSE_REGISTRY", str(tmp_path / "reg.jsonl"))
    import autodj.compose.run as R; R.REGISTRY = str(tmp_path / "reg.jsonl")
    score = tmp_path / "tiny.py"
    score.write_text(textwrap.dedent('''
        import numpy as np
        from autodj.compose import Track, mono2
        META = {"title": "tiny", "target": -16}
        def build(seed):
            trk = Track(120, 24, seed=seed).sections([(0, 24, "A", {"kick": 1, "tone": 1})])
            t = np.arange(int(.3 * trk.sr)) / trk.sr; k = mono2((np.sin(2*np.pi*55*t) * np.exp(-t/.08)).astype(np.float32))
            kb = trk.buf()
            for br in range(24):
                for st in (0, 4, 8, 12): trk.place(kb, k, br * trk.BAR + st * trk.S16)
            trk.add("kick", kb, 1.0)
            trk.add("tone", mono2((np.sin(2*np.pi*440*trk.tt) * .1).astype(np.float32)), .3)
            return trk
    '''))
    s = main(["run", str(score), "--seed", "3", "--outdir", str(tmp_path)])
    assert os.path.exists(s["file"]) and not os.path.exists(tmp_path / "tiny_raw.wav")
    assert s["master"]["limiter_max_db"] < 6 and json.loads((tmp_path / "reg.jsonl").read_text().splitlines()[-1])["name"] == "tiny"

def test_autofix_only_fixable_codes_and_sized():
    from autodj.compose.run import fixes_for
    eq, dt = fixes_for([("high", ""), ("voice", ""), ("limiter", "")], ok_metrics(high_db=-15.0), {"limiter_max_db": 4.0}, None)
    assert len(eq) == 1 and abs(eq[0].gain_db + 5.5) < 1e-6 and abs(dt + 1.5) < 1e-6
    eq, dt = fixes_for([("voice", ""), ("jump", "")], ok_metrics(), OK_MASTER, None)
    assert eq == [] and dt == 0

# ---- P104 stage A: groove, harmony, roles, voice ducking ----
from autodj.compose.harmony import Key, voicing, lead_chords, comp_rhythm, motif, answer, strong_to_chord
from autodj.compose.groove import Groove, library

def test_groove_kick_stays_on_grid_hats_get_feel():
    g = Groove("funk", np.random.default_rng(0))
    assert all(g.offset("kick", s) == 0 for s in range(16))
    offs = [g.offset("hh", s) for s in range(16) for _ in range(5)]
    assert np.std(offs) > .01 and max(abs(o) for o in offs) <= .3

def test_groove_accents_strong_steps_louder_than_weak():
    g = Groove("hiphop", np.random.default_rng(0))
    strong = np.mean([g.vel("hh", s) for s in (0, 4, 8, 12) for _ in range(20)]); weak = np.mean([g.vel("hh", s) for s in (1, 3, 5, 7) for _ in range(20)])
    assert strong > weak

def test_groove_real_bar_has_requested_classes():
    b = Groove("rock", np.random.default_rng(3)).bar(("kick", "snare", "hh")); assert {"kick", "snare", "hh"} <= set(b)

def test_voicing_keeps_guide_tones_and_key_both_sides():
    k = Key("D", "dorian"); chs = [k.chord(d, 4) for d in (0, 3, 6, 4)]; vs = lead_chords(chs, 50, 67)
    for c, v in zip(chs, vs):
        assert c[1] in {n % 12 for n in v} and c[3] in {n % 12 for n in v}
        assert all(n % 12 in k.pcs for n in v) and 50 <= min(v) and max(v) <= 67
    assert max(abs(a - b) for a, b in zip(vs[0], vs[1])) <= 7          # moves smoothly, not block jumps
    for v in vs: assert not any(abs(a - b) in (1, 13) for a in v for b in v)   # no rubbing minor 2nds / 9ths inside a voicing

def test_comp_rhythm_is_syncopated_never_all_downbeats():
    r = np.random.default_rng(5)
    for _ in range(50):
        cr = comp_rhythm(r); st = [s for s, _ in cr]
        assert any(s % 4 for s in st) and sum(l for _, l in cr) + st[0] == 16

def test_answer_resolves_to_chord_root_question_unchanged():
    k = Key("A", "minor"); r = np.random.default_rng(1); m = motif(r, k, 57, 72); a = answer(m, k, k.chord(0), 57, 72)
    assert a[-1][2] % 12 == k.chord(0)[0] and a[:-1] == m[:-1]

def test_strong_to_chord_moves_only_downbeat_notes():
    out = strong_to_chord([(0, 2, 62), (2, 2, 62)], [9, 0, 4]); assert out[0][2] % 12 in (9, 0, 4) and out[1][2] == 62

def test_role_level_used_when_level_missing():
    trk = Track(120, 4).sections([(0, 4, "A", {"kick": 1, "hats": 1})])
    x = np.random.default_rng(0).normal(0, .1, (trk.N, 2)).astype(np.float32)
    trk.add("kick", x, 1.0); k = trk.mix.copy(); trk.add("hats", x * 3)
    r = lambda z: np.sqrt(np.mean(z ** 2)); assert abs(20 * np.log10(r(trk.mix - k) / r(k)) + 15) < .3

def test_duck_for_voice_dips_only_where_voice_is():
    trk = Track(120, 8).sections([(0, 8, "A", {})]); t = trk.tt
    trk.mix[:] = np.stack([np.sin(2 * np.pi * 1000 * t)] * 2, 1) * .3; v = trk.buf(); a, b = trk.i(4), trk.i(5); v[a:b] = .5
    before = trk.mix.copy(); trk.duck_for_voice(v, depth_db=-6)
    r = lambda z: np.sqrt(np.mean(z ** 2))
    assert r(trk.mix[a + 5000:b - 5000]) < r(before[a + 5000:b - 5000]) * .6           # dips under the voice
    assert abs(r(trk.mix[trk.i(1):trk.i(2)]) / r(before[trk.i(1):trk.i(2)]) - 1) < .02  # untouched elsewhere

# ---- harmony of layers: tuning + clashes ----
from autodj.compose.harmony import clashes
from autodj.compose.tuning import split

def test_clash_detector_both_sides():
    keys = [(0, 62, 80, 2), (0, 65, 80, 2), (0, 69, 80, 2)]
    assert clashes({"keys": keys, "bass": [(0, 38, 90, 2)]}, .125)[0] == 0          # D under Dm: fine
    assert clashes({"keys": keys, "bass": [(0, 37, 90, 2)]}, .125)[0] == 1.0        # C# under Dm: the v1/v2 bug

def test_clash_gate_both_sides():
    assert "clash" in codes(ok_metrics(clash_ratio=.3)) and "clash" not in codes(ok_metrics(clash_ratio=.05))

def test_tuning_split_keeps_octaves_fixes_pitch_class():
    assert split(-12.02) == (0, -2.0)           # an octave down is a register choice, not an error
    assert split(-13.0)[0] == 1                 # octave + semitone flat -> transpose MIDI up 1
    assert split(-5.95)[0] == 6 or split(-5.95)[0] == -6
    assert split(0.05) == (0, 5.0)


def test_muted_layer_notes_do_not_count_as_clashes(tmp_path):
    trk = Track(120, 8).sections([(0, 4, "A", {"bass": 1}), (4, 8, "B", {"pad": 1})])
    trk.log_notes("bass", [(br * trk.BAR, 37, 90, trk.BAR) for br in range(8)])         # C# bass, but muted in B
    trk.log_notes("pad", [(4 * trk.BAR, 62, 60, 4 * trk.BAR)])
    trk.mix[:] = .01; assert trk.finish(str(tmp_path / "x.wav"))["clash_ratio"] == 0
    trk2 = Track(120, 8).sections([(0, 8, "A", {"bass": 1, "pad": 1})])
    trk2.log_notes("bass", [(br * trk2.BAR, 37, 90, trk2.BAR) for br in range(8)]); trk2.log_notes("pad", [(4 * trk2.BAR, 62, 60, 4 * trk2.BAR)])
    trk2.mix[:] = .01; assert trk2.finish(str(tmp_path / "y.wav"))["clash_ratio"] > 0


# ---- Lakh pattern library -------------------------------------------------------------------------------------------
import pytest
from autodj.compose.lakh import Lakh, parse_roman, drums_aligned, plausible_tempo, ROOT as LAKH_ROOT
from autodj.compose.harmony import Key

def _lakh_lib(tmp_path):
    g = {"songs": 3, "tempo": [100.0, 199.4, 210.0], "bass_rhythms": [["x.x.x.x.x.x.x.x.", 5]],
         "bass_lines": [[[[[0, 0], [4, 4], [8, 7], [8, 0]], [[0, 5]], [[0, 7]], [[0, 10]]], 4]],
         "progressions": [["minor", ["Im7", "bVImaj7"], 3], ["major", ["I", "IV"], 9]],
         "drums": [[{"kick": [1, 5, 9, 13]}, 1000], [{"kick": [0, 4, 8, 12], "snare": [4, 12]}, 1]],
         "entry_bar_median": {"drums": 1, "bass": 4, "keys": 1, "lead": 5}}
    p = tmp_path / "patterns.json"; p.write_text(json.dumps({"house": g})); return str(p)

def test_lakh_roman_parser_both_sides():
    assert parse_roman("bVImaj7") == (8, "maj7") and parse_roman("IVm") == (5, "m") and parse_roman("Vsus4") == (7, "sus4")
    assert parse_roman("VII") == (11, "") and parse_roman("#IV") == (6, "")
    for bad in ("", "X", "Im9", "imaj7", "bVImaj"):
        with pytest.raises(ValueError): parse_roman(bad)

def test_lakh_chords_in_key(tmp_path):
    lib = Lakh("house", _lakh_lib(tmp_path))
    assert lib.chords(["Im7", "bVImaj7"], Key("A", "minor")) == [[9, 0, 4, 7], [5, 9, 0, 4]]

def test_lakh_drums_drop_offset_bars_keep_real_ones(tmp_path):
    assert not drums_aligned({"kick": [1, 5, 9, 13]}) and not drums_aligned({"hh": [0, 2]})
    assert drums_aligned({"kick": [0, 4, 8, 12]}) and drums_aligned({"kick": [3, 6]})
    lib = Lakh("house", _lakh_lib(tmp_path)); rng = np.random.default_rng(0)
    assert all(lib.drums(rng) == {"kick": [0, 4, 8, 12], "snare": [4, 12]} for _ in range(20))   # 1000x offset bar never picked

def test_lakh_tempo_folds_double_time_keeps_normal():
    assert plausible_tempo(199.4) == 99.7 and plausible_tempo(60.0) == 120.0
    assert plausible_tempo(124.0) == 124.0 and plausible_tempo(80.0) == 80.0 and plausible_tempo(150.0) == 150.0

def test_lakh_bass_notes_snap_out_of_key_keep_in_key(tmp_path):
    lib = Lakh("house", _lakh_lib(tmp_path)); key = Key("A", "minor")
    notes = lib.bass_notes(lib.bass(np.random.default_rng(0)), key, lo=28, hi=52)
    assert all(28 <= m <= 52 and m % 12 in key.pcs for _, _, m, _ in notes)
    by = {(b, s): m for b, s, m, _ in notes}
    assert by[(0, 0)] % 12 == 9 and by[(0, 8)] % 12 == 4               # tonic and fifth unchanged
    assert by[(0, 4)] % 12 == 0                                          # major third C# (not in A minor) -> C
    assert sum(1 for b, s, _, _ in notes if (b, s) == (0, 8)) == 1       # double-stop on step 8 -> one note
    assert all(1 <= ln <= 2 for *_, ln in notes)

def test_lakh_progression_mode_filter_and_fallback(tmp_path):
    lib = Lakh("house", _lakh_lib(tmp_path)); rng = np.random.default_rng(1)
    assert all(lib.progression(rng, "minor") == ["Im7", "bVImaj7"] for _ in range(10))
    assert lib.progression(rng, "dorian") in (["Im7", "bVImaj7"], ["I", "IV"])   # no such mode -> any progression

def test_lakh_missing_file_or_group_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError): Lakh("house", str(tmp_path / "nope.json"))
    with pytest.raises(KeyError): Lakh("polka", _lakh_lib(tmp_path))

@pytest.mark.skipif(not os.path.exists(os.path.join(LAKH_ROOT, "patterns.json")), reason="Lakh library not built here")
def test_lakh_real_library_every_group_usable():
    key = Key("F", "minor"); rng = np.random.default_rng(7)
    for g in Lakh.groups():
        lib = Lakh(g)
        assert 80 <= lib.tempo() <= 150
        for _ in range(5):
            assert all(len(c) >= 3 for c in lib.chords(lib.progression(rng, "minor"), key))   # every top symbol parses
            assert drums_aligned(lib.drums(rng)) and lib.bass_notes(lib.bass(rng), key)

# ---- P107 stage 1-2: focus + hook ----
from autodj.compose import hook as H

def test_rhythm_cell_is_syncopated_with_a_rest_both_sides():
    r = np.random.default_rng(3)
    for _ in range(30):
        c = H.rhythm_cell(r); gaps = [b - a for a, b in zip(c, c[1:] + [16 + c[0]])]
        assert sum(1 for s in c if s % 2) >= 2 and max(gaps) >= 2 and not all(s in c for s in (0, 4, 8, 12))

def test_hook_question_open_answer_closed_strong_beats_on_chord():
    k = Key("A", "minor"); chords = [k.chord(0), k.chord(5)]; r = np.random.default_rng(1)
    for seed in range(10):
        ph = H.phrase(np.random.default_rng(seed), k, lambda b: chords[b], 57, 76)
        q = [x for x in ph if x[0] < 16]; a = [x for x in ph if x[0] >= 16]
        assert q[-1][2] % 12 != chords[0][0]                    # question stays open
        assert a[-1][2] % 12 == chords[1][0]                    # answer lands on the root
        assert all(m % 12 in k.pcs for _, _, m in ph)
        assert all(m % 12 in chords[s // 16] for s, _, m in ph if s % 4 == 0)
        assert max(m for *_, m in ph) - min(m for *_, m in ph) <= 17

def test_eight_bars_repeat_keeps_rhythm_but_varies_tail():
    k = Key("D", "minor"); ch = [k.chord(d) for d in (0, 5, 3, 4, 0, 5, 3, 4)]
    seq = H.eight_bars(np.random.default_rng(4), k, lambda b: ch[b % 8], 57, 76)
    blocks = [[(s % 32, m) for s, _, m in seq if i * 32 <= s < (i + 1) * 32] for i in range(4)]
    rh = lambda b: [s for s, _ in b if s >= 0]
    assert rh(blocks[0]) == rh(blocks[2]) and set(rh(blocks[0])) <= set(rh(blocks[1])) | set(rh(blocks[1]))
    assert blocks[0] != blocks[1] or blocks[0] != blocks[3]       # variation exists

def test_focus_dips_mix_only_while_focus_layer_sounds():
    trk = Track(120, 8).sections([(0, 8, "A", {})]); t = trk.tt
    trk.mix[:] = np.stack([np.sin(2 * np.pi * 900 * t)] * 2, 1) * .3
    lead = trk.buf(); a, b = trk.i(4), trk.i(5); lead[a:b] = np.stack([np.sin(2 * np.pi * 900 * t[a:b])] * 2, 1) * .5
    before = trk.mix.copy(); trk.focus(lead, depth_db=-6)
    r = lambda z: np.sqrt(np.mean(z ** 2))
    assert r(trk.mix[a + 5000:b - 5000]) < r(before[a + 5000:b - 5000]) * .7
    assert abs(r(trk.mix[trk.i(1):trk.i(2)]) / r(before[trk.i(1):trk.i(2)]) - 1) < .02


# --- P107 stage 3: house harmony ---
def test_parallel_progression_keeps_one_shape_and_limits_outside_notes():
    from autodj.compose.harmony import Key, parallel_progression, stab_voicing, SHAPES
    k = Key("A", "minor"); seen_chromatic = False
    for seed in range(20):
        roots = parallel_progression(np.random.default_rng(seed), k, "m9", 4, max_out=1)
        assert roots[0] == k.tonic and len(roots) == 4 and all(a != b for a, b in zip(roots, roots[1:]))
        for r in roots: assert sum((r + i) % 12 not in k.pcs for i in SHAPES["m9"]) <= 1
        seen_chromatic |= any((r + i) % 12 not in k.pcs for r in roots for i in SHAPES["m9"])
        v = stab_voicing(roots, "m9", 55, 84)
        assert all([x - c[0] for x in c] == SHAPES["m9"] for c in v)          # identical shape = parallel motion
        assert all(abs(a[0] - b[0]) <= 8 for a, b in zip(v, v[1:]))           # slides (up to a 5th), never leaps
        assert 52 <= min(c[0] for c in v) and max(c[-1] for c in v) <= 87      # stays in the register asked for
    assert seen_chromatic                                                     # the slide does add colour (passes side)
    for seed in range(10):                                                    # max_out=0 -> strictly diatonic
        roots = parallel_progression(np.random.default_rng(seed), k, "m7", 4, max_out=0)
        assert all((r + i) % 12 in k.pcs for r in roots for i in SHAPES["m7"])

def test_shell_is_root_third_seventh_and_pad_is_two_guide_tones():
    from autodj.compose.harmony import Key, shell, pad_dyad
    k = Key("D", "dorian"); prev = pv = None
    for d in (0, 3, 6, 4):
        c = k.chord(d, 4); v = shell(c, 45, 72, prev)
        assert len(v) == 3 and v[0] % 12 == c[0] and {x % 12 for x in v} == {c[0], c[1], c[3]}
        p = pad_dyad(c, 60, 79, pv)
        assert len(p) == 2 and {x % 12 for x in p} == {c[1], c[3]} and 3 <= p[1] - p[0] <= 11
        prev, pv = v, p
    tri = shell(k.chord(0, 3), 45, 72)                                        # triad still works: 1-3-5
    assert {x % 12 for x in tri} == set(k.chord(0, 3))


# --- P107 stage 4: short bass ---
def test_house_bass_is_short_with_rests_and_leaves_beats_to_kick():
    from autodj.compose.harmony import Key
    from autodj.compose.bass import house_bass, bass_cell
    from autodj.compose.hook import accents
    k = Key("A", "minor"); roots = [9, 5, 0, 7]; cells = set()
    for seed in range(30):
        rng = np.random.default_rng(seed); ev = house_bass(rng, k, lambda b: roots[b % 4], 8)
        cells.add(tuple(bass_cell(np.random.default_rng(seed))))
        assert ev and all(1 <= l <= 2 for _, l, _, _ in ev)                              # <= 1/8
        assert all(b[0] - (a[0] + a[1]) >= 1 for a, b in zip(ev, ev[1:]))               # a rest after every note
        assert all(s % 4 for s, _, _, _ in ev)                                           # beats belong to the kick
        assert all(28 <= m <= 48 for _, _, m, _ in ev)
        assert all(v in (accents(s), accents(s) + 10) for s, _, _, v in ev)              # accent grid
        for s, _, m, _ in ev:                                                             # root/octave/5th, approach only at bar end
            r = roots[(s // 16) % 4]
            assert (m - r) % 12 in (0, 7) or s % 16 >= 12
        assert len({v for *_, v in ev}) >= 2                                             # not one flat velocity
    assert len(cells) >= 20                                                              # generated, not a fixed pattern
    ev = house_bass(np.random.default_rng(1), k, lambda b: 9, 4, on_kick=True, cell=[0, 3, 6, 10, 14])
    assert any(s % 16 == 0 for s, *_ in ev)                                              # opt-in: may sit on the kick


# --- P107 stage 5: micro-development ---
def test_micro_plan_one_event_per_block_no_repeat_and_varies():
    from autodj.compose.develop import micro_plan, MENU
    plans = set()
    for seed in range(20):
        p = micro_plan(np.random.default_rng(seed), 64)
        assert sorted(p) == list(range(3, 64, 4))                                    # exactly one per 4 bars, at block end
        ev = [p[b] for b in sorted(p)]
        assert all(e in MENU for e in ev) and all(a != b for a, b in zip(ev, ev[1:]))
        assert len(set(ev)) >= 4                                                      # not a 2-event ping-pong
        plans.add(tuple(ev))
    assert len(plans) == 20

def test_breathe_moves_tone_but_keeps_level_and_phrase_send_grows_to_phrase_end():
    from autodj.compose.develop import breathe, phrase_send
    from autodj.compose.core import Track, rms
    trk = Track(120, 16); rng = np.random.default_rng(0)
    x = (rng.standard_normal((trk.N, 2)) * .1).astype(np.float32)
    y = breathe(trk, x, period_bars=8, rng=np.random.default_rng(1))
    assert abs(20 * np.log10(rms(y) / rms(x))) < .5                                   # no level change overall
    def bright(z):
        X = np.abs(np.fft.rfft(z.mean(1))); f = np.fft.rfftfreq(len(z), 1 / trk.sr); return (f * X).sum() / X.sum()
    br = [bright(y[trk.i(b):trk.i(b + 1)]) for b in range(8)]
    assert max(br) > 1.3 * min(br)                                                    # the tone does move
    imp = trk.buf(); imp[::trk.BEAT] = .5
    z = phrase_send(trk, imp, period_bars=4); wet = z - imp
    e = lambda b: rms(wet[trk.i(b):trk.i(b + 1)])
    assert e(3) > 3 * e(0) + 1e-9 and e(7) > 3 * e(4) + 1e-9                           # send blooms at the phrase end
