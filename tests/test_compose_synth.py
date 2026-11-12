"""P131: the living synth. What is tested is what the ear should get: right pitch, no aliasing, and MOTION — inside a note
(filter envelope), between notes (velocity, random, LFO, place in the track) and between parts (ctl sources)."""
import numpy as np
import pytest
from autodj.compose.synth import (Synth, patch, rate_hz, adsr, svf, biquad_stream, comb, post, mipmap, wavetable_from_audio,
                                  procedural_table, TABLE)

SR = 44100

def f0(x, t0=.05, lo=40, hi=3000, n=8192):
    m = x.mean(1) if x.ndim == 2 else x; seg = m[int(t0 * SR):int(t0 * SR) + n] * np.hanning(n); ac = np.correlate(seg, seg, "full")[n - 1:]
    a, b = int(SR / hi), int(SR / lo); w = ac[a:b]; pk = np.where((w[1:-1] >= w[:-2]) & (w[1:-1] >= w[2:]) & (w[1:-1] >= .9 * w.max()))[0]
    return SR / (a + 1 + int(pk[0]) if len(pk) else a + int(np.argmax(w)))                     # the first strong peak, not a multiple of the period

def cen(x, t0, dur=.04):
    m = x.mean(1) if x.ndim == 2 else x; s = m[int(t0 * SR):int((t0 + dur) * SR)]
    P = np.abs(np.fft.rfft(s * np.hanning(len(s)))) ** 2; f = np.fft.rfftfreq(len(s), 1 / SR); return float((f * P).sum() / (P.sum() + 1e-20))

def bright(x, t0, dur=.04, split=500):
    """share of the energy above `split` Hz in a short window, dB (0 = everything is above)"""
    m = x.mean(1) if x.ndim == 2 else x; s = m[int(t0 * SR):int((t0 + dur) * SR)]
    P = np.abs(np.fft.rfft(s * np.hanning(len(s)))) ** 2; f = np.fft.rfftfreq(len(s), 1 / SR); return 10 * np.log10(P[f >= split].sum() / (P.sum() + 1e-20) + 1e-20)

def band(x, lo, hi):
    m = x.mean(1) if x.ndim == 2 else x; P = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2; f = np.fft.rfftfreq(len(m), 1 / SR)
    return 10 * np.log10(P[(f >= lo) & (f < hi)].sum() + 1e-20)

OPEN = dict(cutoff=20000, res=0)

# ---- pitch and band-limiting ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("wave", ["saw", "pulse", "tri", "sine", "fm"])
def test_every_wave_plays_the_asked_pitch(wave):
    x = Synth(patch(osc=[dict(wave=wave)], filt=OPEN, drift=0)).render([(0.0, 57, 100, .5)], 1.0)
    assert x.shape == (SR, 2) and abs(f0(x) / 220.0 - 1) < .01 and np.isfinite(x).all()

def test_saw_is_band_limited_no_aliasing_under_a_high_note():
    x = Synth(patch(osc=[dict(wave="saw")], filt=OPEN, drift=0)).render([(0.0, 96, 100, .6)], .8)        # C7 = 2093 Hz
    t = np.arange(int(.6 * SR)) / SR; naive = (2 * ((2093.0 * t) % 1) - 1)[:, None]
    assert band(x[2000:20000], 100, 1900) < band(x[2000:20000], 2000, 2200) - 55       # nothing folded below the fundamental
    assert band(naive[2000:20000], 100, 1900) > band(naive[2000:20000], 2000, 2200) - 45   # a naive saw does alias (the test can see it)

def test_wavetable_plays_in_tune_and_morphs_with_pos():
    tab = procedural_table(np.random.default_rng(3)); mk = lambda pos: Synth(patch(osc=[dict(wave="wt", table="t", pos=pos)], filt=OPEN, drift=0), tables={"t": tab}).render([(0.0, 57, 100, .5)], .8)
    a, b = mk(0.0), mk(1.0)
    assert abs(f0(a) / 220 - 1) < .01 and abs(f0(b) / 220 - 1) < .01 and abs(np.log2(cen(a, .1, .2) / cen(b, .1, .2))) > .05
    with pytest.raises(ValueError): Synth(patch(osc=[dict(wave="wt", table="nope")]))

def test_mipmap_levels_halve_the_harmonics():
    M = mipmap(procedural_table(np.random.default_rng(1), frames=2)); assert M.shape == (11, 2, TABLE)
    S = np.abs(np.fft.rfft(M[3, 0])); assert S[TABLE // 16 + 1:].max() < 1e-3 * S.max() and S[1:TABLE // 16].max() > 0

# ---- motion inside a note -------------------------------------------------------------------------------------------------
def test_filter_envelope_moves_the_tone_inside_the_note():
    ev = [(0.0, 45, 100, .6)]; base = dict(osc=[dict(wave="saw")], drift=0, fenv=dict(a=.001, d=.15, s=0, r=.1), amp=dict(a=.002, d=.5, s=1, r=.05))
    moving = Synth(patch(base, filt=dict(cutoff=200, env=4.0, res=.2))).render(ev, 1.0); still = Synth(patch(base, filt=dict(cutoff=200, env=0, res=.2))).render(ev, 1.0)
    assert bright(moving, .01) > bright(moving, .45) + 15 and abs(bright(still, .01) - bright(still, .45)) < 1.5

def test_shared_layer_filter_for_long_notes_follows_envelope_and_lfo():
    p = patch(osc=[dict(wave="saw", unison=3, detune=10, spread=.5)], filt=dict(cutoff=300, env=2.5, res=.2, per="layer"), amp=dict(a=.05, d=1, s=1, r=.3),
              fenv=dict(a=.01, d=.6, s=0, r=.3), mods=[dict(src="lfo", dst="cutoff", amt=1.5, rate=.25, phase=.25)])
    x = Synth(p).render([(0.0, 50, 100, 2.5), (0.0, 57, 100, 2.5)], 3.0)
    assert np.isfinite(x).all() and cen(x, .03) > 1.5 * cen(x, 1.9)                      # opens at the attack, lfo at its bottom at 2 s
    assert Synth(patch(p, filt=dict(per="auto"))).render([(0.0, 50, 100, 2.5)], 3.0).shape == (3 * SR, 2)   # auto -> layer for long notes

# ---- motion between notes -------------------------------------------------------------------------------------------------
BASS = dict(osc=[dict(wave="saw")], drift=0, filt=dict(cutoff=250, res=.2), amp=dict(a=.002, d=.3, s=.8, r=.05, vel=0))

def test_velocity_opens_the_filter_not_only_the_volume():
    soft, hard = [(0.0, 45, 40, .3)], [(0.0, 45, 127, .3)]
    r = lambda p, ev: Synth(patch(BASS, **p)).render(ev, .5)
    assert bright(r(dict(filt=dict(vel=2.5)), hard), .1) > bright(r(dict(filt=dict(vel=2.5)), soft), .1) + 8
    assert np.allclose(r({}, hard), r({}, soft), atol=1e-6)                             # no vel routing at all -> the same sound

def test_random_makes_no_two_notes_identical_and_seed_makes_it_repeatable():
    ev = [(0.0, 45, 100, .2), (.5, 45, 100, .2)]; p = patch(BASS, mods=[dict(src="rand", dst="cutoff", amt=1.0)])
    x = Synth(p, seed=4).render(ev, 1.0); n = int(.25 * SR); a, b = x[:n], x[int(.5 * SR):int(.5 * SR) + n]
    y = Synth(patch(BASS), seed=4).render(ev, 1.0)
    assert not np.allclose(a, b, atol=1e-3) and np.allclose(y[:n], y[int(.5 * SR):int(.5 * SR) + n], atol=1e-4)
    assert np.array_equal(x, Synth(p, seed=4).render(ev, 1.0)) and not np.allclose(x, Synth(p, seed=5).render(ev, 1.0), atol=1e-3)

def test_global_lfo_runs_across_the_phrase():
    bar = 2.0; ev = [(.25 * bar, 45, 100, .2), (.75 * bar, 45, 100, .2)]                   # lfo top and bottom of a one-bar cycle
    x = Synth(patch(BASS, mods=[dict(src="lfo", dst="cutoff", amt=1.5, rate="1b")]), bpm=120).render(ev, 2.5)
    assert bright(x, .25 * bar + .05) > bright(x, .75 * bar + .05) + 15

def test_the_sound_develops_over_the_track_with_the_time_source():
    ev = [(0.0, 45, 100, .2), (9.0, 45, 100, .2)]
    x = Synth(patch(BASS, mods=[dict(src="time", dst="cutoff", amt=3.0)])).render(ev, 10.0)
    assert bright(x, 9.05) > bright(x, .05) + 15

# ---- parts that listen to each other ------------------------------------------------------------------------------------------
def test_ctl_source_lets_another_layer_move_this_one():
    ev = [(0.2, 45, 100, .2), (1.2, 45, 100, .2)]; curve = np.zeros((2 * SR, 1), np.float32); curve[SR:] = 1.0       # the other part enters at 1 s
    p = patch(BASS, mods=[dict(src="ctl:hats", dst="cutoff", amt=2.0)])
    x = Synth(p).render(ev, 2.0, ctl={"hats": curve})
    assert bright(x, 1.25) > bright(x, .25) + 10
    with pytest.raises(KeyError, match="ctl="): Synth(p).render(ev, 2.0)

# ---- voices -------------------------------------------------------------------------------------------------------------------
def test_unison_spread_is_stereo_and_no_spread_is_mono():
    ev = [(0.0, 57, 100, .5)]
    wide = Synth(patch(osc=[dict(wave="saw", unison=5, detune=15, spread=.8)], filt=OPEN)).render(ev, .8)
    mono = Synth(patch(osc=[dict(wave="saw", unison=5, detune=15, spread=0)], filt=OPEN)).render(ev, .8)
    side = lambda x: np.sqrt(np.mean((x[:, 0] - x[:, 1]) ** 2)) / np.sqrt(np.mean((x[:, 0] + x[:, 1]) ** 2))
    assert side(wide) > .15 and side(mono) < 1e-6

def test_glide_slides_from_the_previous_note_only_when_legato():
    p = patch(BASS, filt=OPEN, glide_ms=120)
    leg = Synth(p).render([(0.0, 45, 100, .3), (.3, 57, 100, .4)], 1.0); gap = Synth(p).render([(0.0, 45, 100, .2), (.4, 57, 100, .4)], 1.0)
    assert f0(leg, .30, n=1024, lo=80, hi=400) < 190 and abs(f0(leg, .55, n=4096) / 220 - 1) < .02     # starts low, lands on the note
    assert abs(f0(gap, .40, n=1024, lo=80, hi=400) / 220 - 1) < .06                                    # after a rest: no slide

def test_no_events_is_silence_and_bad_destinations_are_refused():
    assert not Synth(patch()).render([], .5).any()
    with pytest.raises(ValueError): patch(mods=[dict(src="lfo", dst="reverb", amt=1)])
    p = patch(filt=dict(cutoff=300)); assert p["filt"]["res"] == .15 and p["osc"][0]["unison"] == 1

# ---- building blocks ------------------------------------------------------------------------------------------------------
def test_rate_strings():
    assert rate_hz(2.5, 120) == 2.5 and rate_hz("1/4", 120) == pytest.approx(2.0) and rate_hz("2b", 120) == pytest.approx(.25)
    assert rate_hz("1/8.", 120) == pytest.approx(4 / 1.5) and rate_hz("1/8t", 120) == pytest.approx(6.0)

def test_adsr_shape():
    tl = (np.arange(SR) / SR).astype(np.float32)[:, None]; e = adsr(tl, np.array([.5], np.float32), .01, .1, .5, .1)[:, 0]
    assert e[0] == 0 and abs(e[int(.01 * SR)] - 1) < .02 and abs(e[int(.4 * SR)] - .5) < .01 and e[int(.62 * SR)] < .01 and e.max() <= 1.0

def test_filters_cut_where_they_should():
    rng = np.random.default_rng(0); n = SR; x = rng.normal(0, .2, (n, 1, 1)).astype(np.float32); nc = -(-n // 32)
    lp = svf(x.copy(), np.full((nc, 1), 1000.0), 0.0, SR, "lp", 4)[:, 0]; hp = svf(x.copy(), np.full((nc, 1), 1000.0), 0.0, SR, "hp", 2)[:, 0]
    assert band(lp, 4000, 5000) < band(x[:, 0], 4000, 5000) - 40 and abs(band(lp, 100, 400) - band(x[:, 0], 100, 400)) < 1
    assert band(hp, 100, 250) < band(x[:, 0], 100, 250) - 20
    st = biquad_stream(x[:, 0].repeat(2, 1), np.full(nc, 1000.0), np.zeros(nc), SR, "lp", 4)
    assert band(st, 4000, 5000) < band(x[:, 0], 4000, 5000) - 40 and np.isfinite(st).all()
    sw = biquad_stream(x[:, 0].repeat(2, 1), np.geomspace(200, 8000, nc), np.full(nc, .8), SR)                 # a fast resonant sweep stays stable
    assert np.isfinite(sw).all() and np.abs(sw).max() < 20

def test_comb_resonator_rings_on_its_note():
    rng = np.random.default_rng(0); x = np.zeros((SR, 2), np.float32); x[:400] = rng.normal(0, .5, (400, 2))
    y = comb(x, SR, midi=57, fb=.95, mix=1.0, damp=.2)
    assert abs(f0(y, .1) / 220 - 1) < .02 and np.sqrt(np.mean(y[SR // 8:SR // 4] ** 2)) > 1e-3 and not x[SR // 8:].any()

def test_wavetable_from_audio_keeps_the_colour_of_the_source():
    t = np.arange(SR) / SR; src = np.sin(2 * np.pi * 200 * t) + .6 * np.sin(2 * np.pi * 600 * t)              # harmonics 1 and 3
    T = wavetable_from_audio(src, SR, frames=4); S = np.abs(np.fft.rfft(T[1])); assert T.shape == (4, TABLE)
    assert S[1] > 5 * S[2] and S[3] > 5 * S[2] and S[3] > 5 * S[4]
    with pytest.raises(ValueError): wavetable_from_audio(np.zeros(SR))

def test_procedural_tables_are_new_every_draw():
    a = procedural_table(np.random.default_rng(1)); b = procedural_table(np.random.default_rng(2))
    assert a.shape == (8, TABLE) and not np.allclose(a, b) and not np.allclose(a[0], a[-1])

def test_post_effects_chain_runs_and_changes_the_sound():
    x = Synth(patch(BASS)).render([(0.0, 45, 100, .4)], .6)
    y = post(x, dict(drive=6, chorus=.5, phaser=.3, comb=dict(midi=57, fb=.5, mix=.3), width=1.5, lpf=6000, hpf=40), SR)
    assert y.shape == x.shape and np.isfinite(y).all() and not np.allclose(x, y, atol=1e-3) and post(x, {}, SR) is x

def test_numba_and_numpy_filter_loops_give_the_same_sound(monkeypatch):
    pytest.importorskip("numba")
    import autodj.compose.synth as S
    rng = np.random.default_rng(0); x = rng.normal(0, .2, (3000, 2, 3)).astype(np.float32); nc = -(-3000 // 32)
    fc = np.geomspace(200, 6000, nc)[:, None] * np.ones((1, 3)); res = np.full((nc, 3), .6)
    monkeypatch.setattr(S, "_KERNEL", None); monkeypatch.delenv("AUTODJ_NO_NUMBA", raising=False); fast = {m: S.svf(x.copy(), fc, res, SR, m, 4) for m in ("lp", "bp", "hp")}
    assert S._KERNEL not in (None, False)
    monkeypatch.setattr(S, "_KERNEL", None); monkeypatch.setenv("AUTODJ_NO_NUMBA", "1"); slow = {m: S.svf(x.copy(), fc, res, SR, m, 4) for m in ("lp", "bp", "hp")}
    assert S._KERNEL is False and all(np.allclose(fast[m], slow[m], atol=2e-4) for m in fast)
    st = rng.normal(0, .2, (3000, 2)).astype(np.float32); f1 = np.geomspace(200, 6000, nc); r1 = np.full(nc, .6)
    monkeypatch.setattr(S, "_SKERNEL", None); a = S.biquad_stream(st, f1, r1, SR, "lp", 4); assert S._SKERNEL is False
    monkeypatch.delenv("AUTODJ_NO_NUMBA"); monkeypatch.setattr(S, "_SKERNEL", None); b = S.biquad_stream(st, f1, r1, SR, "lp", 4)
    assert S._SKERNEL not in (None, False) and np.allclose(a, b, atol=2e-4)
    monkeypatch.setattr(S, "_KERNEL", None); monkeypatch.setattr(S, "_SKERNEL", None)

def test_layer_filter_keeps_the_other_routings_per_note():
    tab = procedural_table(np.random.default_rng(3)); ev = [(0.0, 50, 100, 2.0)]
    base = dict(osc=[dict(wave="wt", table="t", pos=.1)], filt=dict(cutoff=4000, res=0, per="layer"), amp=dict(a=.01, d=1, s=1, r=.1), drift=0)
    a = Synth(patch(base), tables={"t": tab}).render(ev, 2.5); b = Synth(patch(base, mods=[dict(src="lfo", dst="pos", amt=.8, rate=.25, phase=.25)]), tables={"t": tab}).render(ev, 2.5)
    c = Synth(patch(base, mods=[dict(src="vel", dst="cutoff", amt=3)]), tables={"t": tab}).render(ev, 2.5)
    assert not np.allclose(a, b, atol=1e-3) and np.allclose(a, c, atol=1e-5)          # lfo -> wavetable position works; a per-note cutoff routing is ignored there
