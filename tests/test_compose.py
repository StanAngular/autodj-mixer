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
