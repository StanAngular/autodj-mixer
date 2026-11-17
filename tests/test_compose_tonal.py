"""P137: ears for harmony (tonal.py). Calibrated on Стас's verdict of 2026-11-17: the P134 jazz palette is «сложнее, но не
гармонично», the old four-chord loop «мелодичнее». The report must rank them the same way, and the consonant palette must not fall
below the old loop while carrying more harmony."""
import importlib.util, io, contextlib, json, os, textwrap
import numpy as np
import pytest
from autodj.compose import Track, tonal as T, chords as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def track_with(notes, bars=16, bpm=120, tl=None):
    trk = Track(bpm, bars, seed=1).sections(tl or [(0, bars, "home", {})])
    for name, ev in notes.items(): trk.log_notes(name, ev)
    return trk

def chords_ev(trk, prog, lo=48):
    """block chords: prog = [(bar_a, bar_b, [pitch classes])] -> events"""
    out = []
    for a, b, pcs in prog:
        for bar in range(a, b):
            for p in pcs: out.append((bar * trk.BAR, lo + (p - lo) % 12, 90, trk.BAR * .98))
    return out

def test_a_diatonic_loop_is_clear_and_clean():
    trk = Track(120, 16, seed=1).sections([(0, 16, "home", {})]); loop = [[9, 0, 4], [5, 9, 0], [2, 5, 9], [4, 7, 11]]          # Am F Dm Em
    trk.log_notes("pad", chords_ev(trk, [(b, b + 1, loop[b % 4]) for b in range(16)]))
    r = T.report(trk)
    assert r["key"] == "A minor" and r["out_of_key"] < .005 and r["clarity"] > .85 and r["notes"] == [] and r["chords"]["source"] == "estimated"

def test_chromatic_chords_are_found_and_named():
    trk = Track(120, 16, seed=1).sections([(0, 16, "home", {})]); loop = [[9, 0, 4], [8, 0, 3], [1, 5, 8], [6, 10, 1]]           # Am Ab Db Gb: no scale holds them
    trk.log_notes("keys", chords_ev(trk, [(b, b + 1, loop[b % 4]) for b in range(16)]))
    r = T.report(trk)
    assert r["out_of_key"] > .1 and any("вне звукоряда" in n for n in r["notes"]) and r["score"]["harmony"] < .6

def test_lead_stats_see_chord_tones_repetition_and_leaps():
    trk = Track(120, 16, seed=1).sections([(0, 16, "home", {})]); S = trk.S16
    trk.log_notes("pad", chords_ev(trk, [(0, 16, [9, 0, 4])]))
    good = [(b * trk.BAR + st * S, m, 100, ln * S) for b in range(16) for st, ln, m in ((0, 4, 69), (4, 2, 72), (6, 2, 71), (8, 4, 72), (12, 4, 76))]   # A C (B passing) C E, every bar
    r = T.report(track_with({"pad": chords_ev(trk, [(0, 16, [9, 0, 4])]), "hook": good}))["lead_stats"]
    assert r["held_on_triad"] == 1.0 and r["repeat"] == 1.0 and r["period_bars"] == 1 and r["leaps_over_fifth"] == 0
    rng = np.random.default_rng(0)
    wander = [(b * trk.BAR + st * S, int(rng.choice([61, 66, 70, 75, 80])), 100, 4 * S) for b in range(16) for st in (0, 4, 8, 12)]
    w = T.report(track_with({"pad": chords_ev(trk, [(0, 16, [9, 0, 4])]), "hook": wander}))
    assert w["lead_stats"]["held_on_triad"] < .3 and w["lead_stats"]["repeat"] < .3 and w["lead_stats"]["leaps_over_fifth"] > 5
    assert any("трезвучия" in n for n in w["notes"]) and any("повторяется" in n for n in w["notes"]) and any("скачков" in n for n in w["notes"])

def test_plan_chords_are_used_when_attached():
    trk = Track(120, 16, seed=1).sections([(0, 8, "home1", {}), (8, 16, "journey1", {})])
    P = C.Plan.build("A", trk.tl, "pop_minor", "rise", seed=1).attach(trk)
    trk.log_notes("keys", [(s0 / 16 * trk.BAR / 1, 57 + (p - 57) % 12, 90, n * trk.S16) for s0, n, c, _ in P.slots for p in c.pcs])
    r = T.report(trk)
    assert trk.plan is P and r["chords"]["source"] == "plan" and r["chords"]["outside_scale"] == 0 and r["chords"]["off_bar"] == 0 and r["out_of_key"] < .005

def test_gates_are_opt_in():
    rep = {"out_of_key": .08, "clarity": .79, "chords": {"outside_scale": .4, "outside_names": ["A9"]}, "lead_stats": {"held_on_triad": .3, "repeat": .2}}
    assert T.gates(rep, None) == [] and T.gates({}, {"tonal_clarity_min": .9}) == []
    g = T.gates(rep, {"tonal_out_of_key_max": .02, "tonal_clarity_min": .85, "tonal_chords_out_max": .15, "lead_triad_min": .5, "lead_repeat_min": .5})
    assert len(g) == 5

def test_tails_make_a_pad_overlap_its_next_chord():
    trk = Track(120, 4, seed=1).sections([(0, 4, "home", {})]); ev = [(b * trk.BAR, m, 90, trk.BAR * .5) for b in range(4) for m in (57, 60, 64)]
    short = T.grid({"keys": ev}, trk.S16, 64); long = T.grid({"pad": ev}, trk.S16, 64)
    assert sum(1 for c in short if c) < sum(1 for c in long if c)

# ---- calibration on the reference score: the ear's verdict -----------------------------------------------------------------
def _demo(monkeypatch, style, harm, seed=11):
    monkeypatch.setenv("AUTODJ_DEMO_SYNTH_KIT", "1"); monkeypatch.setenv("AUTODJ_DEMO_STYLE", style); monkeypatch.setenv("AUTODJ_DEMO_HARMONY", harm)
    spec = importlib.util.spec_from_file_location(f"tonal_demo_{style}_{harm}_{seed}", os.path.join(ROOT, "docs", "examples", "deep_harmony_demo.py"))
    m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(m); trk, plan, lines_, EV = m.write(seed)
    return T.report(trk, lead="hook"), plan

@pytest.mark.parametrize("style", ["garage", "deep", "melodic"])
def test_report_ranks_the_jazz_palette_below_the_old_loop_and_the_consonant_palette_with_it(monkeypatch, style):
    old, po = _demo(monkeypatch, style, "old"); jazz, pj = _demo(monkeypatch, style, "jazz"); cons, pc = _demo(monkeypatch, style, "consonant")
    assert jazz["out_of_key"] > .02 and old["out_of_key"] < .005 and cons["out_of_key"] < .005                          # chromatic notes
    assert jazz["chords"]["outside_scale"] > .15 and cons["chords"]["outside_scale"] == 0                                  # chromatic chords
    assert jazz["clarity"] < .85 <= cons["clarity"] and old["clarity"] >= .9                                               # where home is
    assert len(jazz["notes"]) >= 4 and old["notes"] == [] and cons["notes"] == []                                          # what the ear heard
    assert cons["lead_stats"]["held_on_triad"] >= .5 and cons["lead_stats"]["repeat"] >= .75 and cons["lead_stats"]["leaps_over_fifth"] == 0
    assert cons["chords"]["distinct"] >= 2.5 * old["chords"]["distinct"]                                                    # and still more harmony than the loop
    assert cons["score"]["harmony"] >= .9 and jazz["score"]["harmony"] < .6

def test_run_puts_the_tonal_report_into_the_summary(tmp_path):
    from autodj.compose.run import main
    import autodj.compose.run as R; R.REGISTRY = str(tmp_path / "reg.jsonl")
    score = tmp_path / "t.py"
    score.write_text(textwrap.dedent('''
        import numpy as np
        from autodj.compose import Track, mono2, chords, lines
        META = {"title": "Tonal Test", "target": -18, "lead": "melody", "gates": {"tonal_clarity_min": .99}}
        def build(seed):
            trk = Track(120, 8, seed=seed).sections([(0, 8, "home", {"pad": 1})])
            plan = chords.Plan.build("A", trk.tl, "two_chord", seed=seed).attach(trk)
            pad = [(s0 * trk.S16, m, 80, n * trk.S16) for s0, n, v in plan.voicings("drop2", 52, 72) for m in v]
            trk.log_notes("pad", pad); trk.log_notes("melody", [(b * trk.BAR, 69, 100, trk.BAR / 2) for b in range(8)])
            trk.add("pad", mono2((np.sin(2 * np.pi * 220 * trk.tt) * .1).astype(np.float32)), .4); return trk
    '''))
    s = main(["run", str(score), "--seed", "1", "--outdir", str(tmp_path)])
    assert s["tonal"]["lead"] == "melody" and s["tonal"]["chords"]["source"] == "plan" and s["tonal"]["out_of_key"] < .005 and isinstance(s["tonal_notes"], list)
    assert any("ясность тональности" in p for p in s["problems"])                                                          # the opt-in gate (set absurdly high here) fires
    assert json.load(open(tmp_path / "t.summary.json"))["tonal"]["key"].startswith("A")
