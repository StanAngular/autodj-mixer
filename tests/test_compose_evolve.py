"""P141: recordings played like instruments (evolve.py). Стас 2026-11-18: «он чаще просто семплами слой повторов одного звучка ...
постоянное звучание инструмента который бы в течении песни менял тон ... не совсем постоянно а иногда»."""
import importlib.util, io, contextlib, os
import numpy as np
from scipy.signal import butter, sosfilt
from autodj.compose import Track, evolve as V, clicks as K, chords as C
from autodj.compose.tuning import cents_off

SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def note(midi=57, seconds=2.0, seed=0, decay=.35):
    """a 'recording' of one sustained note: drifting harmonics, a few cents of wander, some bow noise, an 80 ms attack"""
    rng = np.random.default_rng([seed, midi]); n = int(seconds * SR); t = np.arange(n) / SR; f0 = 440 * 2 ** ((midi - 69) / 12)
    slow = lambda k, d: np.interp(np.arange(n), np.linspace(0, n, k), rng.normal(0, d, k))
    ph = 2 * np.pi * np.cumsum(f0 * 2 ** (slow(5, 2.0) / 1200)) / SR; y = np.zeros(n)
    for k in range(1, 16):
        y += (1 / k ** 1.2) * (1 + .2 * slow(4, .5)) * np.sin(k * ph + rng.uniform(0, 6.28))
    y += .02 * sosfilt(butter(2, [1500, 6000], "band", fs=SR, output="sos"), rng.normal(0, 1, n))
    y *= np.minimum(1, t / .08) * (1 - decay * t / seconds); y[-1000:] *= np.linspace(1, 0, 1000); y = .9 * y / np.abs(y).max()
    return np.stack([y, np.roll(y, 5)], 1).astype(np.float32)

def level_db(y, t0, t1):
    s = y[int(t0 * SR):int(t1 * SR)].mean(1); return 20 * np.log10(np.sqrt(np.mean(s ** 2)) + 1e-12)

def frame_db(y, hop=.02):
    e, _ = V._env(y.mean(1), int(hop * SR), int(2 * hop * SR)); return 20 * np.log10(e + 1e-9)

# ---- hold ----------------------------------------------------------------------------------------------------------------
def test_hold_replays_the_attack_and_holds_one_clean_tone():
    x = note(); y = V.hold(x, SR * 6)
    assert len(y) == SR * 6 and np.allclose(y[100:1700], x[100:1700], atol=1e-4)          # the attack as recorded
    assert len(K.steps(y)["idx"]) == 0                                                     # nothing jumps
    e = frame_db(y)[int(.3 / .02):]; assert e.std() < 1.0                                   # one held level (the body is flattened)
    assert abs(cents_off(y, 57, SR, start=3.0, dur=1.0)) < 6                               # one pitch, 3 s past the end of the recording

def test_aligned_grains_do_not_flange():
    x = note(); al = V.hold(x, SR * 6); raw = V.hold(x, SR * 6, tol_s=1e-6)                 # no search: grains overlap out of phase
    jump = lambda y: np.percentile(np.abs(np.diff(frame_db(y)[int(.3 / .02):])), 99)
    assert jump(al) < .7 and jump(raw) > 1.2 and frame_db(al)[15:].std() < .6 * frame_db(raw)[15:].std()

def test_a_held_note_keeps_moving_but_wander_zero_freezes_it():
    x = note(decay=.0, seed=3)
    def flux(y):
        S = [np.abs(np.fft.rfft(y[i:i + 8192].mean(1) * np.hanning(8192)))[:600] for i in range(SR, 5 * SR, SR // 4)]
        S = [s / (np.linalg.norm(s) + 1e-12) for s in S]; return float(np.mean([np.linalg.norm(a - b) for a, b in zip(S, S[1:])]))
    assert flux(V.hold(x, SR * 6, wander=.6, seed=1)) > 1.3 * flux(V.hold(x, SR * 6, wander=0.0, seed=1))

def test_body_says_when_there_is_nothing_to_hold():
    t = np.arange(int(.15 * SR)) / SR; pluck = np.sin(2 * np.pi * 220 * t) * np.exp(-t / .02)
    assert V.body(pluck)["short"] and not V.body(note())["short"]

# ---- the voice -----------------------------------------------------------------------------------------------------------
def test_a_voice_plays_a_legato_line_with_one_attack_per_phrase():
    ev = [(.5, 60, 90, 2.0), (2.5, 62, 90, 2.0), (4.5, 64, 100, 3.0), (8.5, 57, 80, 2.0)]   # C D E legato, a rest, A
    v = V.Voice(note(), 57, seed=1, swell_db=0); y = v.render(ev, 11.5)
    assert v.stats["phrases"] == 2 and v.stats["legato"] == 2 and v.stats["attacks"] == 2
    for t, m, _, d in ev: assert abs(cents_off(y, m, SR, start=t + .4, dur=min(1.0, d - .6))) < 8, m
    for tb in (2.5, 4.5): assert abs(level_db(y, tb - .2, tb - .05) - level_db(y, tb + .05, tb + .2)) < 2.5   # no dip, no re-attack
    assert level_db(y, 8.2, 8.45) < level_db(y, 8.6, 9.0) - 25                            # the rest is silent, the new phrase attacks
    assert len(K.steps(y)["idx"]) == 0

def test_the_glide_passes_through_the_notes_between():
    v = V.Voice(note(), 57, seed=1, glide_s=.4, swell_db=0); y = v.render([(.2, 57, 90, 1.5), (1.7, 64, 90, 1.5)], 3.6)
    seg = y[int(1.62 * SR):int(1.78 * SR)].mean(1); X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 16)); f = np.fft.rfftfreq(1 << 16, 1 / SR)
    band = (f > 200) & (f < 360); peak = f[band][np.argmax(X[band])]
    assert 230 < peak < 315                                                                  # between A3 (220) and E4 (330)

def test_far_notes_move_the_whole_line_by_an_octave():
    v = V.Voice(note(), 57, seed=1); v.render([(.1, 72, 90, 1.0), (1.1, 74, 90, 1.0), (2.1, 76, 90, 1.0)], 3.5)
    assert v.stats["octave_shift"] == -12 and v.stats["max_shift"] <= 7

def test_an_instrument_is_asked_for_the_note_the_part_needs():
    class Inst:
        asked = []
        def render(self, events, total_s):
            self.asked.append(events[0][1]); y = np.zeros((int(total_s * SR), 2), np.float32); x = note(events[0][1], events[0][3]); y[:len(x)] = x; return y
    inst = Inst(); v = V.Voice(inst, seed=1); v.render([(.1, 64, 90, 1.0), (1.1, 66, 90, 1.0), (2.1, 69, 90, 1.0)], 3.5)
    assert inst.asked == [66] and v.stats["recording_midi"] == 66

# ---- the ensemble --------------------------------------------------------------------------------------------------------
def test_the_ensemble_follows_the_plan_and_reenters_with_an_attack():
    import librosa
    trk = Track(122, 16, seed=3).sections([(0, 8, "home1", {"pad": 1}), (8, 12, "break", {"pad": 0}), (12, 16, "home2", {"pad": 1})])
    plan = C.Plan.build("A", trk.tl, "minor_plagal", "lament", seed=3).attach(trk)
    E = V.Ensemble(note(), 57, n=4, seed=2); y = E.render(trk, layer="pad")
    for b in list(range(0, 8)) + list(range(12, 16)):
        seg = y[trk.i(b) + 2000:trk.i(b + 1) - 2000].mean(1); ch = librosa.feature.chroma_stft(y=seg, sr=SR, n_fft=8192).mean(1)
        assert set(np.argsort(ch)[::-1][:3]) <= set(plan.at(b * 16).pcs), b
    for b in (9, 10, 11): assert np.abs(y[trk.i(b):trk.i(b + 1)]).max() < 1e-4                 # the break: the pad is out
    assert E.stats["voices"] == 4 and E.stats["attacks"] == 8 and E.stats["legato"] > 0       # one entry per voice, twice
    assert len(K.steps(y)["idx"]) == 0

def test_lines_of_hold_common_tones():
    L = V.lines_of([(0, 16, [57, 60, 64]), (16, 16, [57, 60, 65]), (32, 16, [55, 59, 62])], 3, .125)
    assert L[0] == [(0.0, 57, 80, 4.0), (4.0, 55, 80, 2.0)] and L[2] == [(0.0, 64, 80, 2.0), (2.0, 65, 80, 2.0), (4.0, 62, 80, 2.0)]

# ---- automation ----------------------------------------------------------------------------------------------------------
def test_lanes_move_by_section_without_corners():
    trk = Track(120, 16, seed=1).sections([(0, 8, "intro", {}), (8, 16, "peak1", {})])
    c = V.lane(trk, {"intro": .2, "peak*": .8}, glide_bars=2)[:, 0]; at = lambda bar: c[int(bar * trk.BAR * SR)]
    assert abs(at(5) - .2) < 1e-6 and abs(at(8) - .8) < 1e-3 and .2 < at(7) < .8 and abs(at(12) - .8) < 1e-6
    assert np.abs(np.diff(c, 2)).max() < 1e-6                                              # raised cosine: no corner
    d = V.lane(trk, {"*": 0, "peak1": 1}, 1, at="after")[:, 0]; assert d[int(8.5 * trk.BAR * SR)] > .4 and d[int(7.9 * trk.BAR * SR)] == 0
    n = V.lane(trk, {0: 0.0, 16: 1.0})[:, 0]; assert abs(n[int(8 * trk.BAR * SR)] - .5) < 1e-3

def test_drift_never_sits_still_and_sometimes_is_mostly_zero():
    trk = Track(120, 32, seed=1).sections([(0, 16, "a", {}), (16, 32, "b", {})])
    d = V.drift(trk, .1, 4, seed=2)[:, 0]; bars = d[::int(trk.BAR * SR)][:32]
    assert np.abs(d).max() <= .1 + 1e-6 and bars.std() > .02 and np.array_equal(d, V.drift(trk, .1, 4, seed=2)[:, 0])
    s = V.sometimes(trk, every=8, p=.5, length_bars=1, seed=4)[:, 0]; m = V.moments(trk, 8, .5, 1.0, 4)
    assert (15.0, 16.0) in m and (s > .01).mean() < .25 and s.max() > .99
    inside = np.zeros(len(s), bool)
    for a, b in m: inside[int(a * trk.BAR * SR):int(b * trk.BAR * SR) + 1] = True
    assert not np.any(s[~inside] > 1e-6)

# ---- the time-varying chain ----------------------------------------------------------------------------------------------
def test_tone_opens_drives_and_narrows_without_a_click():
    rng = np.random.default_rng(0); n = SR * 4; x = (rng.normal(0, .2, (n, 2))).astype(np.float32)
    y = V.tone(x, SR, bright=np.linspace(0, 1, n))
    cen = lambda s: (lambda X, f: (f * X).sum() / X.sum())(np.abs(np.fft.rfft(s.mean(1))) ** 2, np.fft.rfftfreq(len(s), 1 / SR))
    assert cen(y[SR // 4:SR]) * 3 < cen(y[3 * SR:]) and len(K.steps(y)["idx"]) == 0
    t = np.arange(n) / SR; s = np.stack([np.sin(2 * np.pi * 220 * t)] * 2, 1).astype(np.float32) * .5
    third = lambda z: (lambda X, f: X[np.argmin(np.abs(f - 660))] / X[np.argmin(np.abs(f - 220))])(np.abs(np.fft.rfft(z[SR:2 * SR, 0])), np.fft.rfftfreq(SR, 1 / SR))
    assert np.allclose(V.tone(s, SR, drive=0.0), s) and third(V.tone(s, SR, drive=1.0)) > 20 * third(s)
    w = V.tone(x, SR, width=0.0); assert np.allclose(w[:, 0], w[:, 1])

# ---- grains --------------------------------------------------------------------------------------------------------------
def test_grains_sit_on_the_chord_tones():
    import librosa
    trk = Track(120, 8, seed=2).sections([(0, 8, "home1", {"air": 1})])
    plan = C.Plan.build("D", trk.tl, "two_chord", seed=2).attach(trk)
    y = V.grains(trk, note(62, 3.0, decay=.1), 62, per_bar=8, seed=1)
    assert V.grains.last["grains"] > 30 and len(K.steps(y)["idx"]) == 0
    hits = 0
    for b in range(8):
        seg = y[trk.i(b):trk.i(b + 1)].mean(1)
        if np.abs(seg).max() < 1e-3: continue
        ch = librosa.feature.chroma_stft(y=seg, sr=SR, n_fft=8192).mean(1); hits += int(np.argmax(ch)) in plan.at(b * 16).pcs
    assert hits >= 6

# ---- the reference score: A (retriggered) against B (played) -------------------------------------------------------------
def _demo(monkeypatch, mode):
    monkeypatch.setenv("AUTODJ_EVOLVE", mode); monkeypatch.setenv("AUTODJ_DEMO_BARS", "24")
    spec = importlib.util.spec_from_file_location(f"evolve_demo_{mode}", os.path.join(ROOT, "docs", "examples", "evolve_demo.py"))
    m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(m); trk, plan, ev = m.write(3)
    return trk, plan

def test_the_demo_holds_what_the_old_way_retriggers(monkeypatch):
    a, _ = _demo(monkeypatch, "old"); b, plan = _demo(monkeypatch, "new")
    assert a.evolve["mode"] == "old" and b.evolve["mode"] == "new"
    hits = sum(len(ms) for _, _, ms in plan.voicings("drop2", 52, 71, 4)); pad = b.evolve["pad"]
    assert pad["attacks"] <= 3 * pad["voices"] and pad["attacks"] * 4 < hits                     # entries only, not one per chord tone
    assert b.evolve["top"]["legato"] > 0 and b.evolve["air"]["grains"] > 0
    assert len(K.steps(b.mix)["idx"]) == 0
