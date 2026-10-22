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


# --- P107 stage 6: Gemini teacher loop ---
def test_style_guide_dedupes_puts_stas_first_and_parses_rules(tmp_path):
    from autodj.compose import teacher as T
    p = str(tmp_path / "g.json")
    assert T.add_rule("Бас короткий, 1/8", "gemini", path=p)
    assert not T.add_rule("бас  короткий 1/8!", "gemini", path=p)                    # duplicate (normalised)
    assert T.add_rule("Без фейдов", "stas", path=p)
    assert T.add_rule("Техно: бас длиннее", "gemini", genre="techno", path=p)
    T.add_verdict("demo1", "плохо", "каша", path=p)
    g = T.guide_text("house", path=p); lines = g.splitlines()
    assert lines[1].startswith("- [Стас]") and "Без фейдов" in lines[1]               # Стас outranks the teacher
    assert "Техно" not in g and "Техно" in T.guide_text("techno", path=p)              # genre filter both ways
    assert "demo1: плохо — каша" in g
    txt = "1. ...\nПРАВИЛО: хук не длиннее 2 тактов, 3-6 нот\n- ПРАВИЛО: ok\nобычная строка с ПРАВИЛО внутри"
    assert T.parse_rules(txt) == ["хук не длиннее 2 тактов, 3-6 нот"]

def test_ab_pick_counts_only_consistent_answers():
    from autodj.compose.teacher import ab_pick
    likes_a = lambda x, y, p: "чище\nВЫБОР: X" if x == "a.wav" else "чище\nВЫБОР: Y"
    always_first = lambda x, y, p: "ВЫБОР: X"                                          # order bias = no real preference
    assert ab_pick("a.wav", "b.wav", "?", ask=likes_a, path="/nonexistent.json") == "a"
    assert ab_pick("b.wav", "a.wav", "?", ask=likes_a, path="/nonexistent.json") == "b"
    assert ab_pick("a.wav", "b.wav", "?", ask=always_first, path="/nonexistent.json") == "tie"

def test_hook_endings_follow_slid_chords_in_every_repeat():
    """regression: Gemini's draft critique caught a question ending on F over Am9; repeats kept the old chord's
    endings, and chord tones outside the key (slid chords) were never offered"""
    from autodj.compose.harmony import Key, parallel_progression, shape_pcs
    from autodj.compose.hook import eight_bars
    passing = 0
    for seed in range(40):
        rng = np.random.default_rng(seed); k = Key("A", "minor"); roots = parallel_progression(rng, k, "m9", 4)
        cp = lambda b: shape_pcs(roots[(b // 2) % 4], "m9"); h = eight_bars(rng, k, cp, 62, 79)
        for bar in range(8):
            n = [x for x in h if x[0] // 16 == bar]; pcs = cp(bar)
            assert n[-1][2] % 12 in (pcs[1:3] if bar % 2 == 0 else pcs[:1])
            assert all(m % 12 in pcs for s, _, m in n if s % 4 == 0)
            passing += sum(1 for s, _, m in n if s % 4 and m % 12 not in pcs)
    assert passing > 0                                                   # the line still moves through passing tones

def test_guide_hides_rejected_marks_proposed_and_hook_prefers_in_key_chord_tones(tmp_path):
    from autodj.compose import teacher as T
    from autodj.compose.harmony import Key, thin, SHAPES
    from autodj.compose.hook import _tones
    p = str(tmp_path / "g.json")
    T.add_rule("выдуманное правило про релизы", path=p); T.add_rule("полезное правило", path=p); T.add_rule("правило Стаса", "stas", path=p)
    assert T.set_status("выдуманное", "rejected", path=p) == 1
    g = T.guide_text(path=p)
    assert "выдуманное" not in g and "[учитель, не проверено] полезное" in g and "[Стас] правило Стаса" in g
    assert not T.add_rule("Выдуманное правило про релизы!", path=p)              # a rejected rule is not re-learned
    k = Key("D", "minor")
    assert {x % 12 for x in _tones([0, 3, 7, 10, 2], 60, 72, k)} == {0, 7, 10, 2}  # Cm9 over D minor: Eb only as last resort
    assert {x % 12 for x in _tones([3], 60, 72, k)} == {3}                         # ...and still available if it is all there is
    assert thin("m9") == [0, 3, 10, 14] and thin("m7") == SHAPES["m7"]

def test_held_passing_notes_do_not_rub_but_short_ones_stay_free():
    from autodj.compose.harmony import Key, parallel_progression, shape_pcs
    from autodj.compose.hook import eight_bars, _unrub
    k = Key("D", "minor"); cm9 = shape_pcs(0, "m9")                          # C Eb G Bb D
    assert _unrub(61, 1, cm9, 55, 80, k) == 61                              # 1/16 passing C# stays (free side)
    assert _unrub(64, 2, cm9, 55, 80, k) in (62, 65)                        # held E (a semitone over Eb) moves
    assert _unrub(65, 4, cm9, 55, 80, k) == 65                              # held F: a tension, no semitone -> kept
    for seed in range(30):
        rng = np.random.default_rng(seed); roots = parallel_progression(rng, k, "m9", 4); cp = lambda b: shape_pcs(roots[(b // 2) % 4], "m9")
        for s, l, m in eight_bars(rng, k, cp, 62, 79):
            pcs = cp(s // 16)
            if l >= 2: assert m % 12 in pcs or not any((m - p) % 12 in (1, 11) for p in pcs)


# --- P107b: voice leading + tension/release (Стас: «запрети тупой перенос формы аккорда») ---
def test_lead_voices_holds_common_tones_and_moves_others_by_step():
    from autodj.compose.harmony import Key, tension_progression, lead_voices
    tot = good = near = 0
    for mode in ("minor", "major", "dorian"):
        for seed in range(40):
            k = Key("A", mode); prog = tension_progression(np.random.default_rng(seed), k, 2)
            pcs = [b["pcs"] for b in prog[::1]]; v = lead_voices(pcs, 55, 79, 4)
            for (a, b), c in zip(zip(v, v[1:]), pcs[1:]):
                if a == b: continue
                tot += 1; mv = [abs(x - y) for x, y in zip(a, b)]
                held = all(x in b for x in a if x % 12 in c)                    # every common tone stays put
                good += max(mv) <= 2 and held; near += max(mv) <= 3
                need = {c[1]} | {x for x in c[3:4] if (x - c[0]) % 12 in (10, 11)}
                assert need <= {x % 12 for x in b}                               # 3rd/sus + 7th always present
    assert good / tot > .85 and near / tot > .97                                # stepwise is the rule; no real leaps

def test_tension_progression_ends_phrases_on_dominant_and_resolves_to_tonic():
    from autodj.compose.harmony import Key, tension_progression
    shapes, sus = set(), 0
    for seed in range(40):
        k = Key("D", "minor"); prog = tension_progression(np.random.default_rng(seed), k, 3)
        assert len(prog) == 24
        for ph in range(3):
            bars = prog[8 * ph: 8 * ph + 8]
            assert bars[0]["fn"] == "T" and bars[0]["root"] == k.tonic             # each phrase starts on the tonic (release)
            assert bars[-1]["fn"] == "D"                                           # ...and ends in tension
            if "sus" in bars[-2]["name"] and bars[-2]["root"] == bars[-1]["root"]: sus += 1
            shapes.add(tuple(b["name"] for b in bars))
        d7 = [b for b in prog if b["name"].endswith("A7")]
        assert all(1 in b["pcs"] for b in d7)                                      # V7 in D minor has the raised C#
    assert len(shapes) >= 30 and sus >= 10                                         # drawn per phrase; suspensions resolve

def test_anchor_hook_two_three_notes_weak_beat_accents_and_bass_dialog():
    from autodj.compose.harmony import Key, tension_progression
    from autodj.compose.bass import house_bass
    from autodj.compose.hook import anchor_hook
    k = Key("D", "minor"); played_quiet = 0
    for seed in range(30):
        rng = np.random.default_rng(seed); prog = tension_progression(rng, k, 1)
        bass = house_bass(rng, k, lambda b: prog[b % 8]["root"], 8)
        bsteps = lambda b: {s % 16 for s, *_ in bass if s // 16 == b}
        hook, an = anchor_hook(rng, k, lambda b: prog[b % 8]["pcs"], bsteps, bars=8)
        assert 2 <= len(an) <= 3 and max(an) - min(an) <= 7
        body = [m for s, l, m, v in hook if not (s // 16 % 2 == 1 and s == max(x[0] for x in hook if x[0] // 16 == s // 16))]
        assert len({m for m in body} - set(an)) <= 2                              # lives on the anchors
        offv = [v for s, _, _, v in hook if s % 4]; onv = [v for s, _, _, v in hook if s % 4 == 0]
        assert offv and (not onv or np.mean(offv) > np.mean(onv))                # weak beats accented
        for b in range(8):
            notes = [(s % 16, l) for s, l, _, _ in hook if s // 16 == b]
            assert not ({s for s, _ in notes} & bsteps(b))                       # never on a bass onset
            for h in (0, 8):
                nb = len([s for s in bsteps(b) if h <= s < h + 8]); mine = [(s, l) for s, l in notes if h <= s < h + 8]
                if nb >= 2: assert len(mine) <= 1                                 # bass busy -> lead holds / waits
                if nb <= 1 and mine: played_quiet += 1; assert all(l == 1 for _, l in mine)  # bass rests -> short fill
            if notes:
                busy = sorted({x for s, l in notes for x in range(s, s + l)})
                assert max(b2 - a - 1 for a, b2 in zip([-1] + busy, busy + [16])) >= 3   # a rest is part of the rhythm
        home = prog[0]["pcs"][:3]
        for b in range(1, 8, 2):                                                   # answers resolve toward home
            last = max((x for x in hook if x[0] // 16 == b), key=lambda x: x[0], default=None)
            if not last: continue
            pcs = prog[b]["pcs"]; shared = [p_ for p_ in pcs if p_ in home]
            assert last[2] % 12 in (shared or pcs[:1])
    assert played_quiet > 0                                                        # the fills do happen (pass side)

def test_anchor_hook_rhythm_repeats_when_bass_repeats():
    from autodj.compose.harmony import Key
    from autodj.compose.hook import anchor_hook
    k = Key("A", "minor"); bs = lambda b: {2, 7, 10}
    h, _ = anchor_hook(np.random.default_rng(3), k, lambda b: [9, 0, 4, 7], bs, bars=8)
    rh = lambda b: [(s % 16, l) for s, l, _, _ in h if s // 16 == b]
    assert rh(0) == rh(2) == rh(4) and rh(1) == rh(3)                              # A A' A A'' keep the rhythm
    pitches = lambda b: [m for s, _, m, _ in h if s // 16 == b]
    assert pitches(0) == pitches(4) and pitches(0) != pitches(2) or len(set(pitches(0))) == 1   # A' varies the notes

def test_tension_progression_moves_roots_and_prefers_the_dominant():
    from autodj.compose.harmony import Key, tension_progression
    v = total = 0
    for seed in range(60):
        prog = tension_progression(np.random.default_rng(seed), Key("E", "minor"), 1)
        roots = [b["root"] for b in prog[::2]]
        assert all(a != b for a, b in zip(roots, roots[1:]))                        # a chord change is a real change
        total += 1; v += prog[-1]["root"] == Key("E", "minor").degree_pc(4)
    assert v / total > .55                                                          # mostly V/V7, VII only sometimes

def test_pad_dyad_exists_for_every_quality_and_root():
    from autodj.compose.harmony import pad_dyad, chord_of, QUALITY
    for q in QUALITY:
        for r in range(12):
            d = pad_dyad(chord_of(r, q), 65, 84); assert d and len(d) == 2 and {x % 12 for x in d} <= set(chord_of(r, q))


# --- P108: SFZ player + «оживление» ---
def test_sfz_parser_notes_includes_defines_and_cc_conditions(tmp_path):
    import soundfile as sf
    from autodj.compose.sfz import SFZ, note_num, parse
    assert note_num("C4") == 60 and note_num("A0") == 21 and note_num("F#3") == 54 and note_num("Bb1") == 34 and note_num("62") == 62
    t = np.arange(44100) / 44100; sf.write(tmp_path / "a.wav", (np.sin(2 * np.pi * 440 * t) * .5).astype(np.float32), 44100)
    (tmp_path / "inc.sfz").write_text("<region> sample=a.wav lokey=60 hikey=72 pitch_keycenter=$KC seq_length=2 seq_position=1\n"
                                      "<region> sample=a.wav lokey=60 hikey=72 pitch_keycenter=$KC seq_length=2 seq_position=2 volume=-6\n")
    (tmp_path / "i.sfz").write_text('<control> set_cc100=127\n#define $KC 69\n// comment\n<group> locc100=64\n#include "inc.sfz"\n'
                                    '<group> hicc100=10\n<region> sample=a.wav lokey=0 hikey=127 pitch_keycenter=69\n')
    s = SFZ(str(tmp_path / "i.sfz"), tune=False)
    assert len(s.regions) == 2                                                  # the hicc100=10 group is off (cc100=127)
    assert all(r["_kc"] == 69 for r in s.regions)                               # #define reached the included file
    assert len(SFZ(str(tmp_path / "i.sfz"), cc={100: 0}, tune=False).regions) == 1   # ...and the other side passes
    a, b = s.pick(64, 90), s.pick(64, 90)
    assert len(a) == len(b) == 1 and a[0] is not b[0]                           # round robin rotates
    assert s.pick(50, 90) == []                                                 # outside the key range: silent
    y = s.render([(0.0, 72, 100, .5)], 1.0); X = np.abs(np.fft.rfft(y[:22050, 0], 22050 * 8)); f = np.fft.rfftfreq(22050 * 8, 1 / 44100)
    assert abs(f[np.argmax(X)] - 523.25) < 1.5                                  # 3 semitones above the key centre

def test_drift_wanders_a_few_cents_and_room_is_shared():
    from autodj.compose.alive import drift, Room, mechanics
    from autodj.compose.core import Track, rms
    sr = 44100; t = np.arange(sr * 4) / sr; x = np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1).astype(np.float32) * .5
    y = drift(x, sr, cents=6, seed=1)
    def f0(seg):
        X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), len(seg) * 8)); return np.fft.rfftfreq(len(seg) * 8, 1 / sr)[np.argmax(X)]
    c = [1200 * np.log2(f0(y[i:i + 8192, 0]) / 440) for i in range(4410, len(y) - 8192, 8192)]
    assert 1.5 < max(np.abs(c)) < 12                                            # it moves, but only a few cents
    assert abs(20 * np.log10(rms(y) / rms(x))) < .3                              # level untouched
    assert np.allclose(drift(x, sr, cents=0), x, atol=1e-4)                     # 0 cents = transparent (pass side)
    trk = Track(120, 4); room = Room(trk, seed=3); a = trk.buf(); a[1000] = 1; room.send(a, .3); room.send(a * 0, .3)
    w = room.render(); assert np.abs(w[:1000]).max() < 1e-6 and np.abs(w[2000:44100]).max() > 0   # causal tail after the hit
    m = mechanics([(0.5, 60, 100, .5)], 2.0, ref=x[:88200])
    assert np.abs(m[:int(.49 * sr)]).max() == 0 and np.abs(m[int(.5 * sr):int(.52 * sr)]).max() > 0
    assert -33 < 20 * np.log10(rms(m) / rms(x[:88200])) < -27                    # quiet: about -30 dB under the instrument

def test_rate_clips_cancels_position_bias_and_keeps_real_preferences():
    from autodj.compose.teacher import rate_clips
    q = dict(question="?", path="/nonexistent.json", scales=("живость", "теплота"))
    real = {"live.wav": 8, "preset.wav": 3, "mid.wav": 5}
    honest = lambda files, pr: "\n".join(f"ОТРЫВОК {k + 1}: живость={real[f]}; теплота={real[f]}" for k, f in enumerate(files))
    r = rate_clips(["preset.wav", "live.wav", "mid.wav"], ask=honest, seed=1, **q)
    assert r["best"] == 1 and r["agree"] == 1.0 and r["total"][1] == 8               # a real preference survives
    biased = lambda files, pr: "\n".join(f"ОТРЫВОК {k + 1}: живость={3 + 3 * k}; теплота={3 + 3 * k}" for k in range(len(files)))
    r = rate_clips(["preset.wav", "live.wav", "mid.wav"], ask=biased, seed=1, **q)
    assert r["best"] is None                                                           # «the last one is best» cancels out
    assert r["agree"] < 1.0
    lucky = lambda files, pr: "\n".join(f"ОТРЫВОК {k + 1}: живость={3 + 3 * k}; теплота=7" for k in range(len(files)))
    assert rate_clips(["preset.wav", "live.wav", "mid.wav"], ask=lucky, seed=1, **q)["best"] is None   # 1 of 2 scales agree: no verdict

def test_house_bass_never_leaves_the_key():
    from autodj.compose.harmony import Key, tension_progression
    from autodj.compose.bass import house_bass
    for tonic in ("B", "C#", "F#", "A"):
        k = Key(tonic, "minor")
        for seed in range(25):
            prog = tension_progression(np.random.default_rng(seed), k, 1)
            ev = house_bass(np.random.default_rng(seed), k, lambda b: prog[b % 8]["root"], 32)
            chord = lambda s: prog[(s // 16) % 8]["pcs"]
            assert all(m % 12 in k.pcs or m % 12 in chord(s) for s, _, m, _ in ev)   # V7 leading tone allowed as a chord tone


# --- P109: competing ideas + experiment memory ---
def test_idea_families_are_different_and_stay_in_key():
    from autodj.compose.harmony import Key, tension_progression, lead_voices
    from autodj.compose.bass import house_bass
    from autodj.compose.ideas import make, FAMILIES
    k = Key("B", "minor")
    for seed in range(8):
        rng = np.random.default_rng(seed); prog = tension_progression(rng, k, 1); cp = lambda b: prog[b % 8]["pcs"]
        vo = lead_voices([b["pcs"] for b in prog], 55, 74, 4); bass = house_bass(rng, k, lambda b: prog[b % 8]["root"], 8)
        bs = lambda b: {s % 16 for s, *_ in bass if s // 16 == b}
        out = {f: make(f, np.random.default_rng(seed), k, cp, lambda b: vo[b % 8], bs) for f in FAMILIES}
        rhythms = set()
        for f, o in out.items():
            ev = o["hook"] or o["bass"]
            assert ev, f
            for s, l, m, v in ev: assert m % 12 in k.pcs or m % 12 in cp(s // 16), (f, s, m)
            rhythms.add(tuple(sorted({s % 16 for s, *_ in ev if s < 16})))
        assert len(rhythms) >= 4                                                   # different identities, not one pattern
        assert out["bass_hook"]["hook"] == [] and out["bass_hook"]["bass"]         # the bass carries that idea
        assert max(l for _, l, _, _ in out["long_line"]["hook"]) >= 10              # long notes really are long
        assert sum(1 for s, *_ in out["arp_cycle"]["hook"] if s < 16) >= 12         # the shimmer is continuous

def test_experiment_blind_labels_agreement_bias_and_human_vote(tmp_path):
    from autodj.compose.experiment import Experiment
    ex = Experiment("hooks", "какой хук", root=str(tmp_path), seed=1)
    for v in ("x", "y", "z"):
        f = tmp_path / f"{v}.mp3"; f.write_bytes(b"0"); ex.add(v, str(f), f"idea {v}")
    try: ex.add("x", str(tmp_path / "x.mp3"), "again"); assert False
    except AssertionError as e: assert "never overwrite" in str(e)
    lab = ex.blind(); assert sorted(lab.values()) == ["x", "y", "z"]
    true = {"y": 0, "x": 1, "z": 2}                                                  # y is really best
    honest = lambda items, p: "РЕЙТИНГ: " + " > ".join(sorted([L for L, _ in items], key=lambda L: true[lab[L]])) + "\nГИПОТЕЗА: h"
    r = ex.judge("t", ask=lambda i, p: "**" + honest(i, p).replace("РЕЙТИНГ:", "РЕЙТИНГ:**"), guide_path="/nonexistent.json")
    assert lab[r["agreed_best"]] == "y" and not r["position_bias_suspect"]          # markdown «**РЕЙТИНГ:**» parsed
    first = lambda items, p: "РЕЙТИНГ: " + " > ".join(L for L, _ in items)        # always «the first one»
    r = ex.judge("t", ask=first, guide_path="/nonexistent.json")
    assert r["agreed_best"] is None and r["position_bias_suspect"]
    L = [k for k, v in lab.items() if v == "z"][0]
    assert ex.vote(L, note="лучше") == "z" and Experiment.load(ex.dir).data["chosen"] == "z"
    assert len(open(tmp_path / "log.jsonl").read().strip().splitlines()) == 3

def test_held_melody_notes_never_sit_a_semitone_from_the_chord():
    """p109 regression: the long-line hook held E over Fmaj7 (a maj7 = a semitone above the root) -> «не попадает»"""
    from autodj.compose.harmony import Key, tension_progression, lead_voices, chord_of, stable_tone
    from autodj.compose.ideas import long_line
    assert not stable_tone(4, chord_of(5, "maj7")) and stable_tone(9, chord_of(5, "maj7"))   # E on Fmaj7 no, A yes
    assert stable_tone(10, chord_of(0, "7")) and stable_tone(4, chord_of(0, "7"))           # b7 and 3rd of C7 fine
    for tonic in ("A", "D", "E"):
        k = Key(tonic, "minor")
        for seed in range(20):
            prog = tension_progression(np.random.default_rng(seed), k, 1); cp = lambda b: prog[b % 8]["pcs"]
            o = long_line(np.random.default_rng(seed), k, cp)
            for s, l, m, v in o["hook"]:
                pcs = cp(s // 16)
                if l >= 8: assert stable_tone(m % 12, pcs), (tonic, seed, s, m, prog[(s // 16) % 8]["name"])
                assert not any((m - q) % 12 in (1, 11) for q in pcs) or m % 12 in pcs and l < 8 or stable_tone(m % 12, pcs)

def test_oneshot_plays_any_shot_at_the_asked_pitch(tmp_path):
    import soundfile as sf
    from autodj.compose.sfz import oneshot
    t = np.arange(44100) / 44100; w = tmp_path / "g4.wav"
    sf.write(w, (np.sin(2 * np.pi * 392.0 * t) * np.exp(-t * 2) * .5).astype(np.float32), 44100)
    inst = oneshot(str(w), cache_dir=str(tmp_path / "c"))                      # pitch measured: G4 = 67
    y = inst.render([(0.0, 69, 100, .6)], 1.0)                                  # ask for A4
    X = np.abs(np.fft.rfft(y[:30000, 0], 30000 * 4)); f = np.fft.rfftfreq(30000 * 4, 1 / 44100)
    assert abs(f[np.argmax(X)] - 440) < 3
    assert np.abs(y[int(.75 * 44100):]).max() < .05                             # released after the note

def test_bass_respects_what_really_sounds_over_it():
    """experiment 3: fixed Gm7 stab over a G|Eb|F|D bass -> the bass's A (5th of D) rubbed with the stab's Bb"""
    from autodj.compose.harmony import Key
    from autodj.compose.bass import house_bass
    from autodj.compose.ideas import bass_hook
    k = Key("G", "minor"); roots = [7, 7, 3, 5, 2, 2, 3, 5]
    snd = {7: [7, 10, 2, 5], 3: [3, 7, 10, 2], 5: [5, 7, 10, 2], 2: [2, 5, 7, 10]}; cp = lambda b: snd[roots[b % 8]]
    rub = lambda m, pcs: m % 12 not in pcs and any((m - q) % 12 in (1, 11) for q in pcs)
    free = 0
    for seed in range(30):
        ev = house_bass(np.random.default_rng(seed), k, lambda b: roots[b % 8], 16, lo=31, hi=50, chord_of_bar=cp, onsets=(5, 6))
        assert not any(rub(m, cp(s // 16)) for s, l, m, v in ev)
        bh = bass_hook(np.random.default_rng(seed), k, cp, 16, lo=31, hi=50)["bass"]
        assert not any(rub(m, cp(s // 16)) for s, l, m, v in bh)
        plain = house_bass(np.random.default_rng(seed), k, lambda b: roots[b % 8], 16, lo=31, hi=50, onsets=(5, 6))
        free += any(rub(m, cp(s // 16)) for s, l, m, v in plain)
    assert free > 0                                                      # without the chord the old rubs do happen

def test_fader_dip_only_hits_the_last_beat_and_swell_grows():
    from autodj.compose import fx
    from autodj.compose.core import Track
    trk = Track(120, 4).sections([(0, 4, "a", {})]); trk.mix[:] = .5
    fx.fader_dip(trk, 2, beats=1)
    beat = trk.BEAT; i = trk.i(2)
    assert np.abs(trk.mix[i - beat // 2:i - 100]).max() < .5 * 10 ** (-25 / 20)     # the beat before bar 2 is down
    assert np.allclose(trk.mix[:i - beat - 10], .5) and np.allclose(trk.mix[i + 400:], .5)   # everything else untouched
    s = fx.swell(trk, 1, 3)
    assert s[trk.i(.5)] == 0 and s[trk.i(3.5)] == 1 and 0 < s[trk.i(2)] < .5         # silent, then accelerating, then full

def test_autopan_moves_between_ears_keeps_power_and_float_gain_stays_in_range():
    from autodj.compose import fx
    from autodj.compose.core import Track, rms
    trk = Track(120, 8).sections([(0, 8, "a", {})]); x = np.stack([np.sin(2 * np.pi * 300 * trk.tt)] * 2, 1).astype(np.float32) * .3
    y = fx.autopan(trk, x, period_bars=8, depth=.8)
    q = trk.i(2); h = trk.i(6)                                                   # quarter and three quarters of the cycle
    l1, r1 = rms(y[q - 2000:q + 2000, 0]), rms(y[q - 2000:q + 2000, 1]); l2, r2 = rms(y[h - 2000:h + 2000, 0]), rms(y[h - 2000:h + 2000, 1])
    assert r1 > 2 * l1 and l2 > 2 * r2                                            # right ear, then left ear
    assert abs(20 * np.log10(rms(y) / rms(x))) < .5                               # same power overall
    assert np.allclose(fx.autopan(trk, x, depth=0), x, atol=1e-5)                 # depth 0 = untouched (pass side)
    g = 20 * np.log10(fx.float_gain(trk, 4, 3.0)); assert -1.6 < g.min() < -1.4 and 1.4 < g.max() < 1.6

def test_tame_caps_spiky_peaks_and_leaves_smooth_layers_alone():
    from autodj.compose import fx
    from autodj.compose.core import rms
    sr = 44100; t = np.arange(sr * 2) / sr
    smooth = np.stack([np.sin(2 * np.pi * 220 * t)] * 2, 1).astype(np.float32) * .2
    assert np.allclose(fx.tame(smooth, 14.0), smooth)                            # crest 3 dB: untouched
    spiky = smooth * .05; spiky[sr // 2:sr // 2 + 40] = .9                       # a 25+ dB spike
    y = fx.tame(spiky, 14.0)
    a0 = spiky[np.abs(spiky).max(1) > 1e-5]; over = 20 * np.log10(np.abs(y).max() / np.sqrt((a0 ** 2).mean()))
    assert over < 14.3 and abs(20 * np.log10(rms(y[sr:]) / rms(spiky[sr:]))) < .1    # peak at the cap, body untouched

def test_riff_root_always_exists_in_range():
    """2026-10-22: with lo=62 hi=78 a Db root had no candidate in 62..66 and _nearest returned the fallback E (64) ->
    an out-of-key note over Dbmaj7 in every track-D riff"""
    from autodj.compose.harmony import Key, chord_of
    from autodj.compose.ideas import riff
    k = Key("F", "minor"); ch = [chord_of(5, "m7")] * 4 + [chord_of(1, "maj7")] * 2 + [chord_of(3, "")] * 2
    for seed in range(20):
        o = riff(np.random.default_rng(seed), k, lambda b: ch[b % 8], 16, lo=62, hi=78)
        for s, l, m, v in o["hook"]:
            assert m % 12 in k.pcs or m % 12 in ch[(s // 16) % 8], (seed, s, m)

def test_builder_fresh_hook_avoids_another_tracks_rhythm_unless_asked(tmp_path, monkeypatch):
    from autodj.compose import builder as B
    monkeypatch.setattr(B, "USED", str(tmp_path / "used.json"))
    gen = lambda rng: [(int(s), 1, 60, 90) for s in sorted(rng.choice(16, 4, replace=False))]
    a = B.fresh_hook("track_one", {}, "riff", 5, gen)
    b = B.fresh_hook("track_two", {}, "riff", 5, gen)
    fp = lambda e: tuple(x[0] % 16 for x in e if x[0] < 16)
    assert fp(a) != fp(b)                                                    # a new track does not repeat another's rhythm
    assert fp(B.fresh_hook("track_one", {}, "riff", 5, gen)) == fp(a)        # the same track re-renders identically
    c = B.fresh_hook("track_three", {"reuse_hook": True, "seed_salt": B._zlib.crc32(b"track_one") % 100000}, "riff", 5, gen)
    assert fp(c) == fp(a)                                                    # explicit request: reuse is allowed

# ---- P110 / P111 / P112 (2026-10-23)
def test_builder_bass_hook_concept_builds_and_other_hooks_still_build(tmp_path, monkeypatch):
    """P110: a bass_hook concept crashed with UnboundLocalError (`h` used before it was set). Both sides: it builds now and
    registers its rhythm under bass_hook; a non-bass concept still builds as before."""
    from autodj.compose import builder as B
    monkeypatch.setattr(B, "USED", str(tmp_path / "used.json"))
    sec = [(0, 8, "A", dict(kick=1, hats=1, bass=1, hook=1))]
    t = B.build_concept("bass_groove", 5, bars=8, sections=sec, pulls=[])
    assert t.notes.get("bass") and np.isfinite(t.mix).all()
    reg = json.load(open(tmp_path / "used.json")); assert any(k.startswith("bass_hook|") for k in reg)
    t2 = B.build_concept("lead_riff", 5, bars=8, sections=sec, pulls=[], dip=False)
    assert t2.notes.get("hook") and any(k.startswith("lead_riff|") for k in json.load(open(tmp_path / "used.json")))

def test_clean_title_strips_artist_but_keeps_real_titles():
    from autodj.compose.run import clean_title
    assert clean_title("StanPo - Gated Depths (deep techno)") == "Gated Depths (deep techno)"
    assert clean_title("StanPo – Shimmer in the Deep") == "Shimmer in the Deep"
    assert clean_title("Gated Depths (deep techno)") == "Gated Depths (deep techno)"
    assert clean_title("StanPolis Lights (house)") == "StanPolis Lights (house)"            # a word, not the artist prefix

def test_send_telegram_performer_is_stanpo(tmp_path, monkeypatch):
    import io, autodj.compose.run as R
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x"); monkeypatch.setenv("ALLOWED_CHAT_ID", "1"); got = {}
    def fake(req, timeout=0): got["body"] = req.data; return io.BytesIO(b'{"ok": true}')
    import urllib.request; monkeypatch.setattr(urllib.request, "urlopen", fake)
    p = tmp_path / "a.mp3"; p.write_bytes(b"ID3")
    assert R.send_telegram(str(p), "Gated Depths (deep techno)") == "sent"
    assert b'name="performer"\r\n\r\nStanPo\r\n' in got["body"] and "Клод".encode() not in got["body"]

def test_tag_mp3_writes_artist_and_title(tmp_path):
    import subprocess
    from autodj.compose.run import tag_mp3
    p = tmp_path / "t.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1", "-q:a", "9", str(p)], check=True)
    assert tag_mp3(str(p), "Pulse (melodic house)", "house")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=artist,title", "-of", "json", str(p)], capture_output=True, text=True).stdout
    tags = {k.lower(): v for k, v in json.loads(out)["format"]["tags"].items()}
    assert tags["artist"] == "StanPo" and tags["title"] == "Pulse (melodic house)"
    assert not tag_mp3(str(tmp_path / "missing.mp3"), "x")                                  # a broken input fails cleanly

def test_gemini_listener_prefers_3_8_flash_with_fallbacks():
    import inspect
    from autodj.compose import teacher, review
    assert teacher.MODELS[0] == "gemini-3.8-flash" and "gemini-3-flash-preview" in teacher.MODELS[1:]
    d = inspect.signature(review.review).parameters["models"].default
    assert d[0] == "gemini-3.8-flash" and len(d) >= 2
