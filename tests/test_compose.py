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
