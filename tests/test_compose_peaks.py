"""P179: layer peaks recorded by Track.add and reported against the kick (both sides)"""
import types, numpy as np
from autodj.compose import ears
from autodj.compose.core import Track

def test_track_records_the_peak_after_level_and_envelope():
    trk = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "home", {"kick": 1, "fx": 1})]); x = np.zeros((trk.N, 2), np.float32); x[:2000] = .5; trk.add("kick", x, 1.0)
    y = np.zeros((trk.N, 2), np.float32); y[:100] = 1.0; y[5000:5000 + trk.sr // 2] = .02; trk.add("fx", y, .1)
    assert trk.peaks["kick"] > 0 and trk.peaks["fx"] > 0 and set(trk.peaks) == {"kick", "fx"}

def test_a_layer_peaking_over_the_kick_is_reported_and_normal_layers_pass():
    t = types.SimpleNamespace(peaks={"kick": 1.0, "bass": 1.0, "fx": 3.0, "hats": .2})
    rel, lines = ears.peak_report(t); assert rel["fx"] > 9 and rel["bass"] == 0.0 and len(lines) == 1 and "fx" in lines[0]
    assert ears.peak_report(types.SimpleNamespace(peaks={"kick": 1.0, "bass": 1.1}))[1] == [] and ears.peak_report(types.SimpleNamespace(peaks={})) == ({}, []) and ears.peak_report(types.SimpleNamespace(peaks={"fx": 1.0}))[1] == []
