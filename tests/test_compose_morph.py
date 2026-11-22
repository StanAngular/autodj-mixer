"""P181-P184 morph: handoff keeps the level, spectral morph is a hybrid (not a cut), granular follows the curve, cross-synth carries the modulator's colour,
note relay, apply() + report + problems both sides"""
import types, numpy as np, pytest
from autodj.compose import morph as M

SR = 44100
def tone(f, s=2.0, amp=.3):
    t = np.arange(int(s * SR)) / SR; return np.stack([amp * np.sin(2 * np.pi * f * t)] * 2, 1).astype(np.float32)
def noise(s=2.0, amp=.1, seed=0): return np.stack([np.random.default_rng(seed).normal(0, amp, int(s * SR))] * 2, 1).astype(np.float32)
def spec_at(x, a, b):
    seg = x[int(a * SR):int(b * SR)].mean(1); S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))); f = np.fft.rfftfreq(len(seg), 1 / SR); return S, f
def energy_near(x, a, b, hz):
    S, f = spec_at(x, a, b); return float(S[(f > hz * .95) & (f < hz * 1.05)].sum())

def test_curve_shapes():
    for s in ("smooth", "linear", "late", "early"):
        c = M.curve(100, s); assert abs(c[0]) < 1e-9 and abs(c[-1] - 1) < 1e-9 and np.all(np.diff(c) >= -1e-12)

def test_spectral_morph_middle_has_both_partials_and_ends_on_each_source():
    a, b = tone(220), tone(660); out = M.spectral_morph(a, b, M.curve(512))
    assert energy_near(out, .1, .3, 220) > 5 * energy_near(out, .1, .3, 660)                      # starts as A
    assert energy_near(out, 1.7, 1.9, 660) > 5 * energy_near(out, 1.7, 1.9, 220)                  # ends as B
    m220, m660 = energy_near(out, .9, 1.1, 220), energy_near(out, .9, 1.1, 660); assert min(m220, m660) > .1 * max(m220, m660)   # the middle carries both
    r = M.report(a, b, out, 0, len(out)); assert r["peak"] < 1.0 and r["level_dev_db"] < 3.0

def test_handoff_keeps_the_level_and_moves_the_band():
    a, b = noise(seed=1), noise(seed=2); out = M.spectral_handoff(a, b, M.curve(512)); r = M.report(a, b, out, 0, len(out)); assert r["level_dev_db"] < 3.0
    lo = lambda x, t: energy_near(x, t, t + .2, 200); assert lo(out, .1) > 0

def test_granular_follows_the_curve_and_is_deterministic():
    a, b = tone(220), tone(660); c = M.curve(256)
    o1 = M.granular_morph(a, b, c, np.random.default_rng(3)); o2 = M.granular_morph(a, b, c, np.random.default_rng(3)); assert np.array_equal(o1, o2)
    assert energy_near(o1, .05, .25, 220) > energy_near(o1, .05, .25, 660) and energy_near(o1, 1.7, 1.95, 660) > energy_near(o1, 1.7, 1.95, 220)

def test_cross_synth_takes_the_colour_of_the_modulator():
    car = noise(seed=4); mod = tone(1000) + tone(1000) * 0; out = M.cross_synth(mod, car, 1.0)
    assert energy_near(out, .5, 1.5, 1000) / energy_near(car, .5, 1.5, 1000) > 2.0                 # the noise now peaks where the tone was
    same = M.cross_synth(mod, car, 0.0); assert abs(np.sqrt((same ** 2).mean()) - np.sqrt((car ** 2).mean())) < .02

def test_note_relay_split_and_weave():
    notes = [(s, 2, 60 + s % 5, 90) for s in range(0, 64, 4)]
    a, b = M.note_relay(notes, split=32); assert all(n[0] < 32 for n in a) and all(n[0] >= 32 for n in b) and len(a) + len(b) == len(notes)
    a, b = M.note_relay(notes, mode="weave", window=(16, 48)); w = [n for n in a + b if 16 <= n[0] < 48]; assert len(w) == 8 and any(16 <= n[0] < 48 for n in a) and any(16 <= n[0] < 48 for n in b)

def test_apply_logs_and_refuses_bad_ranges_and_problems_flag_a_cut():
    trk = types.SimpleNamespace(N=SR * 4, BAR=1.0, sr=SR, seed=1); a, b = tone(220, 4), tone(660, 4)
    out = M.apply(trk, "pad", a, b, 1, 3, kind="spectral"); assert len(out) == trk.N and trk.morphs[0]["layer"] == "pad" and trk.morphs[0]["bars"] == [1, 3]
    with pytest.raises(ValueError): M.apply(trk, "pad", a, b, 1, 1.5)
    with pytest.raises(ValueError): M.apply(trk, "pad", a, b, 3, 9)
    cut = [{"layer": "x", "kind": "spectral", "bars": [0, 4], "peak": .5, "level_dev_db": .5, "low_side": 0.0, "mid_like_a": .95, "mid_like_b": .2}]
    assert any("переключение" in l for l in M.problems(cut))
    ok = [{"layer": "x", "kind": "spectral", "bars": [0, 4], "peak": .5, "level_dev_db": .5, "low_side": 0.0, "mid_like_a": .8, "mid_like_b": .75}]; assert M.problems(ok) == []
    loud = [{**ok[0], "peak": 1.3, "level_dev_db": 5.0}]; assert len(M.problems(loud)) == 2
