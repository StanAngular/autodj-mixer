"""P139: sound quality gate + flexible freshness, both sides (what it cuts AND what it lets through)."""
import os, numpy as np, soundfile as sf, pytest
from autodj.compose import soundgate as G, fresh, ears

SR = 22050
def tone(f, dur=1.0, wob=0.0, noise=0.0):
    t = np.arange(int(SR * dur)) / SR; ph = 2 * np.pi * f * t + (wob * np.sin(2 * np.pi * 5 * t) if wob else 0)
    y = 0.5 * np.sin(ph) + 0.2 * np.sin(2 * ph) + noise * np.random.default_rng(1).standard_normal(len(t)); return y.astype(np.float32)

def test_clean_note_passes_and_is_pitched():
    m = G.measure_signal(tone(220.0), SR); q, bad = G.quality(m, "bass")
    assert not bad and q > .8 and abs(m["root"] - 57) < .2 and m["kind"] in ("note", "dyad")

def test_wobbling_pitch_is_hard_bad():
    q, bad = G.quality(G.measure_signal(tone(110.0, wob=6.0), SR), "bass"); assert any("wobble" in b for b in bad)

def test_noise_burst_is_hard_bad():
    q, bad = G.quality(G.measure_signal(tone(110.0, noise=2.0), SR), "bass"); assert bad

def test_chord_is_soft_for_pad_but_penalised_for_bass():
    m = {"root": 55.0, "cents": 0, "wobble": 3, "noise": .001, "kind": "chord", "pcs": 4}
    assert G.quality(m, "pad") == (1.0, []) and G.quality(m, "bass")[0] < G.quality(m, "pad")[0]
    assert not G.quality(m, "bass")[1]

def test_register_window():
    assert G.fits(55, 50, 62) and not G.fits(55, 40, 80) and G.needs_multisample(55, 40, 70) and not G.needs_multisample(55, 52, 60)

def test_pick_skips_bad_and_out_of_range(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTODJ_SOUND_QUALITY", str(tmp_path / "q.json")); G._MEM.clear()
    paths = {}
    for n, y in {"clean_a3": tone(220.0), "wobble": tone(220.0, wob=6.0), "clean_a1": tone(55.0)}.items():
        paths[n] = str(tmp_path / (n + ".wav")); sf.write(paths[n], y, SR)
    db = {"tracks": {}}
    assert G.pick(paths.values(), "lead", 52, 64, np.random.default_rng(0), db=db) == paths["clean_a3"]
    with pytest.raises(ValueError): G.pick([paths["wobble"]], "bass", 40, 60, db=db)
    assert G.pick([paths["wobble"]], "bass", 40, 60, db=db, strict=False) == paths["wobble"]

def test_report_flags_only_bad_measured_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTODJ_SOUND_QUALITY", str(tmp_path / "q.json")); G._MEM.clear()
    G._MEM["db"] = {"bad.wav": {"root": 40.0, "cents": 0, "wobble": 35, "noise": .001, "kind": "note", "pcs": 1}, "ok.wav": {"root": 40.0, "cents": 2, "wobble": 4, "noise": .001, "kind": "note", "pcs": 1}}
    r = G.report(["bad.wav", "ok.wav", "unknown.wav"]); assert list(r) == ["bad.wav"]

def test_gate_blocks_bad_sounds_and_opt_out():
    assert "bad_sounds" in ears.gate_failures({"bad_sounds": {"x.wav": ["r"]}}, {}) and not ears.gate_failures({"bad_sounds": {}}, {})
    assert "bad_sounds" in ears.gate_failures({"bad_sounds": {"x.wav": ["r"]}}, {"allow_bad_sounds": True})                       # P146: the flag alone does nothing
    assert "bad_sounds" in ears.gate_failures({"bad_sounds": {"x.wav": ["r"]}}, {"allow_bad_sounds": True, "allow_reason": "x"})   # a reason without the env var does nothing either
    assert not ears.gate_failures({"bad_sounds": {"x.wav": ["r"]}}, {"allow_bad_sounds": True}, override=True)

def db_with(*tracks): return {"tracks": {f"t{i}": {"sources": s} for i, s in enumerate(tracks)}}

def test_freshness_is_strict_every_earlier_use_counts_the_same():
    db = db_with(["old.wav"], [], [], [], ["recent.wav"])
    assert fresh.wear("old.wav", db) == fresh.wear("recent.wav", db) == 1.0 and fresh.wear("new.wav", db) == 0.0
    assert fresh.pick(["old.wav", "new.wav"], np.random.default_rng(0), db=db) == "new.wav"

def test_quality_never_brings_a_worn_sound_back():
    db = db_with(["good.wav"])
    assert fresh.pick(["good.wav", "poor.wav"], np.random.default_rng(0), db=db, quality={"good.wav": 1.0, "poor.wav": 0.1}) == "poor.wav"

def test_most_worn_loses_least_worn_wins():
    db = db_with(["a.wav", "b.wav"], ["a.wav"])
    assert fresh.pick(["a.wav", "b.wav"], np.random.default_rng(0), db=db) == "b.wav"

# ---- 2026-11-18 fixes: a silent layer is recorded (gate sees it), an instrument silent on a note falls back to a sounding neighbour
def test_silent_layer_is_recorded_and_audible_one_is_not():
    from autodj.compose import Track, ears
    trk = Track(120, 2, seed=1).sections([(0, 2, "home1", dict(a=1, b=1))])
    trk.add("a", np.zeros((trk.N, 2), np.float32)); trk.add("b", (0.1 * np.ones((trk.N, 2))).astype(np.float32))
    assert trk.layers["a"] is None and trk.layers["b"] is not None
    assert ears.silent_layers(trk.layers) == ["a"]

class _Inst:
    def __init__(self, silent): self.silent = silent
    def render(self, ev, T):
        y = np.zeros((int(T * 44100), 2), np.float32)
        t, m, v, d = ev[0]
        if m not in self.silent: y[:int(d * 44100)] = 0.2 * np.sin(np.arange(int(d * 44100)) / 20)[:, None]
        return y

def test_recording_falls_back_to_nearest_sounding_note():
    from autodj.compose import evolve as V
    x, m = V.recording(_Inst({69, 70}), 69, seconds=.5); assert m == 68 and np.abs(x).max() > .1
    x, m = V.recording(_Inst(set()), 69, seconds=.5); assert m == 69
    with pytest.raises(ValueError): V.recording(_Inst(set(range(60, 80))), 69, seconds=.5)


def test_bearsax_is_one_sustained_layer_per_key_no_noise_or_sub_layers():
    import os
    from autodj.compose.sfz import SFZ, available
    if not available().get("bearsax"): pytest.skip("bearsax not installed")
    ins = SFZ("bearsax")
    for m in (40, 55, 62, 68, 72):
        picked = ins.pick(m, 100)
        assert len(picked) == 1 and os.path.basename(picked[0]["_file"]).endswith("_looped_f.wav"), (m, [os.path.basename(r["_file"]) for r in picked])
    full = SFZ("bearsax_full")                       # the stock program still plays several layers at once: that is what the clean one replaces
    assert len(full.pick(62, 100)) > 1

def test_double_bass_and_tuba_are_one_pitched_layer_per_key_with_octave_override():
    import os
    from autodj.compose.sfz import SFZ, available, OCT_OVERRIDE
    for n in ("dbass", "tuba"):
        if not available().get(n): pytest.skip(n + " not installed")
        ins = SFZ(n); assert ins.oct == OCT_OVERRIDE[n] == 0
        for k in (34, 40, 46): assert len(ins.pick(k, 100)) == 1
    assert "sus" in os.path.basename(SFZ("tuba").pick(40, 100)[0]["_file"])
    assert "noise" not in os.path.basename(SFZ("dbass").pick(40, 100)[0]["_file"])
