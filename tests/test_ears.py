"""P125: both sides of every check (what it flags AND what it passes)."""
import numpy as np, soundfile as sf
from autodj.compose import ears

def test_silent_layers_flags_none_and_floor_and_passes_audible():
    assert ears.silent_layers({"kick": -19.1, "snare": None, "bass": -95.0, "hats": -43.7}) == ["bass", "snare"]
    assert ears.silent_layers({"kick": -19.1, "hats": -43.7}) == []
    assert ears.silent_layers(None) == [] and ears.silent_layers({}) == []

def test_ears_gates_both_sides():
    g = {"ears_ce_min": 6.0, "arc_same8_max": .7, "arc_run_max": 32}
    bad = {"ears": {"CE": 4.5}, "arc": {"same_as_8_bars_ago": .9, "longest_unchanged_run_bars": 40}}
    good = {"ears": {"CE": 6.5}, "arc": {"same_as_8_bars_ago": .5, "longest_unchanged_run_bars": 10}}
    assert len(ears.ears_gates(bad, g)) == 3
    assert ears.ears_gates(good, g) == []
    assert ears.ears_gates(bad, {}) == [] and ears.ears_gates(bad, None) == []            # no gate key = no gate
    assert ears.ears_gates({"ears": {"error": "x"}}, g) == []                             # a missing model must not fail a track

def test_arc_runs_and_sees_repetition(tmp_path):
    sr = 22050; bpm = 120; bar = 2.0; t = np.arange(int(bar * 12 * sr)) / sr
    x = np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 2 * t) > 0)                     # 12 identical bars
    p = str(tmp_path / "rep.wav"); sf.write(p, x.astype("float32"), sr)
    r = ears.arc(p, bpm); assert r["bars"] >= 10 and r["longest_unchanged_run_bars"] >= 8 and r["same_as_8_bars_ago"] > .7
    y = np.concatenate([np.sin(2 * np.pi * f * np.arange(int(bar * sr)) / sr) for f in (220, 330, 440, 550, 660, 770, 880, 990, 1100, 1210, 1320, 1430)])   # 12 different bars
    p2 = str(tmp_path / "var.wav"); sf.write(p2, y.astype("float32"), sr); r2 = ears.arc(p2, bpm)
    assert r2["longest_unchanged_run_bars"] < r["longest_unchanged_run_bars"]

def test_abx_never_raises_without_model(tmp_path, monkeypatch):
    monkeypatch.setattr(ears, "ABX_PATH", "/nonexistent")
    p = str(tmp_path / "a.wav"); sf.write(p, np.zeros(44100 * 30, dtype="float32"), 44100)
    r = ears.abx(p); assert isinstance(r, dict)
