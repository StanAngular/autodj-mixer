"""P162 rhythm measures + P163 place(align="onset") and Ensemble v2 (swing split from micro-timing, anchor, push); v1 stays bit-identical (both sides)"""
import types, numpy as np, pytest, soundfile as sf
from autodj.compose import rhythm as R, microtiming as MT, fresh
from autodj.compose.core import Track

SR = 44100
def fake(bpm=121, bars=16, swing=0.0):
    BAR = 240 / bpm; return types.SimpleNamespace(bars=bars, S16=BAR / 16, BAR=BAR, swing=swing, sr=SR)

# ---- regression: version 1 is exactly the old formula ---------------------------------------------------------------------------------------------
def old_offset(mt, br, st, role):                                   # the P150 formula, copied verbatim
    i = int(br * 16 + st); sw = MT.ROLE_SWING.get(role, 0.0) * (mt.trk.S16 * 1000 * .18 if int(st) % 2 else 0)
    j = mt.jit.get(role); ms = mt.drift[i] + MT.ROLE_MS.get(role, 0.0) + (j[i] if j is not None else 0) + sw + (mt.swing * mt.trk.S16 * 1000 if int(st) % 2 else 0)
    return float(np.clip(ms, -MT.LIMIT_MS, MT.LIMIT_MS))

@pytest.mark.parametrize("swing", [0.0, .08, .16])
def test_version_1_is_identical_to_the_old_behaviour(swing):
    mt = MT.Ensemble(fake(swing=swing), seed=5)
    for br in range(0, 16, 3):
        for st in range(16):
            for role in ("kick", "hats", "bass", "clap", "perc", "keys"): assert mt.offset_ms(br, st, role) == old_offset(mt, br, st, role)
    assert mt.version == 1 and mt.time(2, 3, "hats") == pytest.approx(2 * mt.trk.BAR + 3 * mt.trk.S16 + old_offset(mt, 2, 3, "hats") / 1000)

# ---- version 2 -------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bpm", [100, 130])
def test_v2_swing_is_a_fixed_fraction_of_the_sixteenth_on_odd_steps_only_and_never_clipped(bpm):
    t = fake(bpm); a = MT.Ensemble(t, seed=3, version=2, swing=0.0, drift_ms=0, role_jitter_ms=0); b = MT.Ensemble(t, seed=3, version=2, swing=.36, drift_ms=0, role_jitter_ms=0)
    odd = b.offset_ms(1, 3, "hats") - a.offset_ms(1, 3, "hats"); assert odd == pytest.approx(.36 * t.S16 * 1000) and odd > MT.LIMIT_MS * .9      # 0.36 of a 16th, more than the old clip allowed
    assert b.offset_ms(1, 4, "hats") == a.offset_ms(1, 4, "hats")

def test_v2_micro_is_clipped_and_separate_from_swing():
    t = fake(); e = MT.Ensemble(t, seed=3, version=2, swing=.2, drift_ms=60.0, role_jitter_ms=30.0)
    odd = [e.offset_ms(b, 3, "hats") - e.sw2 * t.S16 * 1000 for b in range(16)]; assert max(abs(x) for x in odd) <= MT.LIMIT_MS + 1e-6         # the micro part alone stays inside ±25

def test_v2_kick_is_exactly_on_the_grid_and_push_is_allowed_for_other_roles_by_profile():
    t = fake(swing=.1); e = MT.Ensemble(t, seed=1, version=2, push={"bass": -6.0, "perc": -3.0, "kick": -9.0}, drift_ms=8, role_jitter_ms=4)
    assert all(e.offset_ms(b, s, "kick") == 0.0 for b in range(16) for s in range(16))                          # the anchor ignores even an explicit push
    plain = MT.Ensemble(t, seed=1, version=2, drift_ms=8, role_jitter_ms=4); assert e.offset_ms(2, 4, "bass") - plain.offset_ms(2, 4, "bass") == pytest.approx(-6.0)
    assert MT.Ensemble(t, seed=1, version=2, push={"bass": -999}, drift_ms=8, role_jitter_ms=4).offset_ms(2, 4, "bass") - plain.offset_ms(2, 4, "bass") == pytest.approx(-MT.PUSH_LIMIT_MS)

def test_timing_report_reads_the_log_and_measures_the_swing():
    t = fake(); e = MT.Ensemble(t, seed=2, version=2, swing=.2, drift_ms=0, role_jitter_ms=0)
    for b in range(16):
        for s in range(16): e.time(b, s, "hats"); e.time(b, s, "kick")
    r = R.timing(t); assert r["swing"]["hats"] == pytest.approx(.2, abs=.02) and r["kick_sd_ms"] == 0.0 and r["version"] == 2
    assert R.timing(fake()) is None

# ---- place(align="onset") ------------------------------------------------------------------------------------------------------------------------
def hit(lead_ms):
    x = np.zeros(int(.3 * SR), np.float32); k = int(lead_ms / 1000 * SR); t = np.arange(len(x) - k) / SR; x[k:] = np.cos(2 * np.pi * 200 * t) * np.exp(-t / .05); return x      # starts at full level

def first(buf): return int(np.argmax(np.abs(buf).max(1) > .05))

def test_place_by_onset_puts_the_attack_on_the_beat_and_default_is_unchanged():
    trk = Track(120, 2, seed=1, humanize_s=0); trk.declick = False; at = int(round(.5 * SR)); x = hit(25)
    a = trk.buf(); trk.place(a, x, .5); b = trk.buf(); trk.place(b, x, .5, align="onset")
    assert abs(first(a) - at - int(.025 * SR)) < 60 and abs(first(b) - at) < 60                                 # default: 25 ms late (as before); onset: on the beat ±1 ms
    c = trk.buf(); trk.align = "onset"; trk.place(c, x, .5); assert abs(first(c) - at) < 60

def test_a_hit_without_leading_silence_is_not_moved_and_silence_is_safe():
    trk = Track(120, 2, seed=1, humanize_s=0); trk.declick = False; x = hit(0); a = trk.buf(); b = trk.buf(); trk.place(a, x, .5); trk.place(b, x, .5, align="onset")
    assert np.array_equal(a, b) and R.onset_samples(np.zeros(100, np.float32)) == 0 and R.onset_samples(np.zeros((0, 2), np.float32)) == 0

# ---- onset_latency cache --------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def cache(tmp_path, monkeypatch): monkeypatch.setenv("AUTODJ_ONSET_CACHE", str(tmp_path / "c.json")); R._MEM.clear(); yield; R._MEM.clear()

def test_latency_is_measured_once_per_file_and_again_when_the_file_changes(tmp_path, cache, monkeypatch):
    p = str(tmp_path / "clap_a.wav"); sf.write(p, hit(25), SR); calls = []; orig = sf.read
    monkeypatch.setattr(sf, "read", lambda *a, **k: calls.append(a[0]) or orig(*a, **k))
    l = R.onset_latency(p); assert abs(l - .025) < .002 and len(calls) == 1
    assert R.onset_latency(p) == l and len(calls) == 1                                    # cached: the file is not read again
    R._MEM.clear(); assert R.onset_latency(p) == l and len(calls) == 1                    # ... also from the cache FILE in a new process
    sf.write(p, hit(8), SR); assert abs(R.onset_latency(p) - .008) < .002 and len(calls) == 2    # changed file: measured again
    assert R.onset_latency(str(tmp_path / "missing.wav")) is None

def test_latency_report_names_late_drums_and_is_quiet_when_aligned_or_early(tmp_path, cache):
    late = str(tmp_path / "late_clap.wav"); ok = str(tmp_path / "ok_clap.wav"); sf.write(late, hit(25), SR); sf.write(ok, hit(1), SR); fresh.PATHS.clear()
    for p in (late, ok): fresh.used(p)
    r = R.latency_report(list(fresh.USED)); assert [n for n, ms in r] == ["late_clap.wav"] and R.latency_report(list(fresh.USED), aligned=True) == []; fresh.PATHS.clear()

# ---- measures from act -----------------------------------------------------------------------------------------------------------------------------
def act(layers, bars=16):
    out = {}
    for n, (steps, db) in layers.items():
        E = np.full((bars * 16, 4), 1e-12)
        for b in range(bars):
            for s in steps: E[b * 16 + s, 1] = 10 ** (db(b, s) / 10)
        out[n] = E
    return out

def trk_of(a, bars=16, tl=None): return types.SimpleNamespace(act=a, bars=bars, tl=tl or [(0, 8, "home1"), (8, 16, "home2")], microtiming=None)

def test_flat_hats_and_flat_density_are_reported_and_accented_hats_pass():
    flat = trk_of(act({"hats": ([2, 6, 10, 14], lambda b, s: -30.0), "kick": ([0, 4, 8, 12], lambda b, s: -20.0)}))
    assert R.accent_contrast(flat)["hats"] < 1.5 and any("одной силы" in n for n in R.report(flat)[1]) and any("бочка ровная" in n for n in R.report(flat)[1])
    acc = trk_of(act({"hats": ([2, 6, 10, 14], lambda b, s: -30.0 + (6 if s in (6, 14) else 0) + (b % 3)), "kick": ([0, 4, 8, 12], lambda b, s: -20.0 - (b % 4) * 2)}))
    assert R.accent_contrast(acc)["hats"] >= 4 and not any("одной силы" in n for n in R.report(acc)[1])

def test_density_change_and_dropout_before_the_peak():
    steps = lambda b: [0, 4, 8, 12] + ([2, 6, 10, 14] if b >= 8 else []); a = {}
    E = np.full((256, 4), 1e-12)
    for b in range(16):
        for s in ([0, 4, 8, 12] + ([2, 6, 10, 14] if b >= 8 else [])): E[b * 16 + s, 1] = 1e-2
    a["perc"] = E; d = R.section_density(trk_of(a)); assert d["per_bar"]["home2"] > d["per_bar"]["home1"] and d["range"] / d["mean"] > .12
    K = np.full((256, 4), 1e-12)
    for b in range(16):
        for s in ([0] if b == 7 else [0, 4, 8, 12]): K[b * 16 + s, 1] = 1e-2
    dr = R.dropouts(trk_of({"kick": K})); assert dr["before"] == ["home2"] and not dr["peak_without"]
    K2 = np.full((256, 4), 1e-12)
    for b in range(16):
        for s in (0, 4, 8, 12): K2[b * 16 + s, 1] = 1e-2
    assert R.dropouts(trk_of({"kick": K2}))["peak_without"] and any("провала" in n for n in R.report(trk_of({"kick": K2}))[1])

def test_the_task_moves_the_thresholds():
    flat = trk_of(act({"hats": ([2, 6, 10, 14], lambda b, s: -30.0 + (1 if s == 6 else 0))})); R.set_task(); assert any("одной силы" in n for n in R.report(flat)[1])
    R.set_task(mood="ambient"); assert not any("одной силы" in n for n in R.report(flat)[1]); R.set_task(limits={"hat_contrast_min_db": 9}); assert any("одной силы" in n for n in R.report(flat)[1]); R.set_task()
