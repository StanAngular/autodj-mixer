"""P130: the mix graph (keyed ducking, follow, shared spaces, depth, group buses) and the studio master.
Everything is synthetic: no sample packs needed."""
import json, os, textwrap
import numpy as np
import pytest
from autodj.compose import Track, mono2
from autodj.compose import bus as B

SR = 44100

def db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12)

def tone(trk, hz, amp=.2):
    return mono2((np.sin(2 * np.pi * hz * trk.tt) * amp).astype(np.float32))

def kick_buf(trk, bars):
    t = np.arange(int(.25 * trk.sr)) / trk.sr; k = mono2((np.sin(2 * np.pi * 55 * t) * np.exp(-t / .06)).astype(np.float32)); kb = trk.buf()
    for br in bars:
        for st in (0, 4, 8, 12): trk.place(kb, k, br * trk.BAR + st * trk.S16)
    return kb

def band_db(x, sr, lo, hi):
    X = np.abs(np.fft.rfft(x[:, 0] * np.hanning(len(x)))) ** 2; f = np.fft.rfftfreq(len(x), 1 / sr)
    return 10 * np.log10(X[(f >= lo) & (f < hi)].sum() + 1e-20)

# ---- envelope / follower ----------------------------------------------------------------------------------------------
def test_follower_attacks_at_once_and_releases_in_the_given_time():
    e = np.zeros(2000, np.float32); e[100:110] = 1.0
    f = B.follower(e, SR, B.CTL, attack_ms=0, hold_ms=0, release_ms=140)
    assert f[100] == pytest.approx(1.0) and f[99] == 0
    k = 110 + int(.140 * SR / B.CTL)
    assert f[k] < .03 and f[110 + int(.02 * SR / B.CTL)] > .5          # ~98 % back after release_ms, still deep after 20 ms

def test_follower_hold_keeps_the_dip():
    e = np.zeros(400, np.float32); e[10] = 1.0
    f = B.follower(e, SR, B.CTL, attack_ms=0, hold_ms=30, release_ms=100)
    assert f[10 + int(.025 * SR / B.CTL)] == pytest.approx(1.0)

# ---- keyed ducking ----------------------------------------------------------------------------------------------------
def _dip(trk, x, bar):
    """level right after the downbeat of `bar` minus the level just before it, dB"""
    i = trk.i(bar); return db(x[i + 200:i + 1500]) - db(x[i - 3000:i - 500])

def test_keyed_duck_follows_the_real_kick_and_the_clock_duck_does_not():
    def build(keyed):
        trk = Track(120, 4, seed=1, humanize_s=0).sections([(0, 4, "A", {"kick": 1, "bass": 1})])
        trk.add("kick", kick_buf(trk, bars=(0, 1)), 1.0)                      # the kick plays in bars 0-1 only
        before = trk._mix.copy(); trk.add("bass", tone(trk, 110), .5, duck=-6.0, **({"key": "kick"} if keyed else {}))
        return trk, trk._mix - before
    trk, keyed = build(True); _, clock = build(False)
    assert _dip(trk, keyed, 1) < -4.5 and abs(_dip(trk, keyed, 3)) < .3       # dips with the kick, stays flat where the kick is gone
    assert _dip(trk, clock, 1) < -2.0 and _dip(trk, clock, 3) < -2.0          # the clock keeps pumping an absent kick
    assert trk.routing["bass"]["key"] == "kick"

def test_keyed_duck_accepts_an_audio_key_for_a_ghost_kick():
    trk = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "A", {"bass": 1})])
    trk.add("bass", tone(trk, 110), 1.0, duck=-6.0, key=kick_buf(trk, bars=(0, 1)))     # the kick itself is not in the mix
    assert _dip(trk, trk._mix, 1) < -4.5 and trk.routing["bass"]["key"] == "audio" and "kick" not in trk.layers

def test_band_duck_gives_way_only_in_the_band():
    trk = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "A", {"kick": 1, "pad": 1})])
    trk.add("kick", kick_buf(trk, bars=(0, 1)), 1.0)
    pad = tone(trk, 150) + tone(trk, 2500)
    a = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "A", {"kick": 1, "pad": 1})]); a.add("kick", kick_buf(a, bars=(0, 1)), 1.0)
    m0 = trk._mix.copy(); trk.add("pad", pad, .5, duck=-9.0, key="kick", band=(1000, 6000)); banded = trk._mix - m0
    m0 = a._mix.copy(); a.add("pad", pad, .5); plain = a._mix - m0
    i = trk.i(1); seg = slice(i + 200, i + 2400)
    assert band_db(banded[seg], SR, 2000, 3000) < band_db(plain[seg], SR, 2000, 3000) - 5      # the band ducks
    assert abs(band_db(banded[seg], SR, 100, 200) - band_db(plain[seg], SR, 100, 200)) < .5    # the rest does not

def test_key_must_exist_and_the_message_says_what_to_do():
    trk = Track(120, 2, seed=1).sections([(0, 2, "A", {"bass": 1})])
    with pytest.raises(KeyError, match="not added yet"): trk.add("bass", tone(trk, 110), 1.0, duck=-6.0, key="kick")

def test_follow_gives_a_0_1_curve_and_its_inverse():
    trk = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "A", {"kick": 1})]); trk.add("kick", kick_buf(trk, bars=(0,)), 1.0)
    f = trk.follow("kick", release_ms=100); g = trk.follow("kick", release_ms=100, invert=True)
    assert f.shape == (trk.N, 1) and f.min() >= 0 and f.max() <= 1 and np.allclose(f + g, 1, atol=1e-6)
    assert f[trk.i(0) + 900, 0] > .8 and f[trk.i(1) + 300, 0] < .01           # high on the kick, zero in the empty bar

# ---- the default path is untouched ----------------------------------------------------------------------------------------
def test_add_without_the_new_arguments_gives_the_old_mix_bit_for_bit():
    from autodj.generate.mixbus import sidechain_duck
    from autodj.compose.core import rms
    trk = Track(124, 4, seed=3, humanize_s=0).sections([(0, 2, "A", {"kick": 1, "bass": .5}), (2, 4, "B", {"kick": 1, "bass": 1})])
    kb, bs = kick_buf(trk, range(4)), tone(trk, 82)
    trk.add("kick", kb, 1.0); trk.add("bass", bs, .6, duck=-6.0)
    ref = rms(kb[np.abs(kb).max(1) > 1e-4]); k2 = kb * trk.env("kick")
    b2 = sidechain_duck(bs * (.6 * ref / rms(bs[np.abs(bs).max(1) > 1e-4])) * trk.env("bass"), trk.sr, trk.BEAT, -6.0, release_ms=140)
    assert np.array_equal(trk.mix, (k2 + b2).astype(np.float32)) and not trk.buses and not trk.spaces

# ---- group buses ------------------------------------------------------------------------------------------------------
def test_bus_layers_wait_in_the_bus_and_reading_the_mix_brings_them_in():
    trk = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "A", {"kick": 1, "hats": 1})])
    trk.add("kick", kick_buf(trk, (0, 1)), 1.0); m0 = trk._mix.copy()
    trk.add("hats", tone(trk, 6000, .05), .3, bus="drums")
    assert np.array_equal(trk._mix, m0) and "drums" in trk.buses              # not in the sum yet
    full = trk.mix                                                            # a read (fx.pullback, mono_low ...) flushes
    assert not trk.buses and db(full - m0) > -60 and trk.flushes == {"drums": 1}

def test_bus_glue_keeps_the_level_plan_and_parallel_adds_body():
    def build(**cfg):
        trk = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "A", {"kick": 1, "perc": 1})])
        trk.add("kick", kick_buf(trk, (0, 1)), 1.0, bus="drums"); trk.add("perc", tone(trk, 900, .05), .2, bus="drums")
        if cfg: trk.bus("drums", **cfg)
        return trk.mix.copy()
    plain = build(); glued = build(fx=[B.glue(over_db=-6, ratio=4)]); par = build(parallel=(B.smash(), .5), makeup=False)
    act = np.abs(plain).max(1) > 1e-4
    assert abs(db(glued[act]) - db(plain[act])) < .2 and not np.allclose(glued, plain, atol=1e-4)   # compressed, same rms
    assert db(par[act]) > db(plain[act]) + .5                                                        # parallel adds under the dry

def test_default_glue_is_gentle_whatever_the_absolute_level():
    def peak_gain(scale):
        trk = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "A", {"kick": 1})]); k = kick_buf(trk, (0, 1)) * scale
        y = B._run([B.glue()], k, SR); return 20 * np.log10(np.abs(y).max() / np.abs(k).max())
    assert -3.5 < peak_gain(1.0) < -.3 and abs(peak_gain(1.0) - peak_gain(.05)) < .3     # 1-3 dB off the peaks, the same at any level
    mixed = B._run([B.glue(), lambda z: z * .5], np.ones((2000, 2), np.float32) * .1, SR)   # plugins and functions in one chain
    assert mixed.shape == (2000, 2)

def test_finish_brings_buses_and_spaces_in_and_reports_the_routing(tmp_path):
    trk = Track(120, 4, seed=1, humanize_s=0).sections([(0, 4, "A", {"kick": 1, "hook": 1})])
    trk.add("kick", kick_buf(trk, range(4)), 1.0, bus="drums")
    trk.add("hook", tone(trk, 440, .1) * (trk.tt[:, None] < 2.0), .4, send={"room": .3}, duck=-3, key="kick")
    info = trk.finish(str(tmp_path / "t.wav"))
    assert info["routing"]["hook"]["send"] == {"room": .3} and info["routing"]["kick"]["bus"] == "drums"
    assert info["spaces"]["room"]["sent"] == {"hook": .3} and info["flushes"] == {"drums": 1, "space:room": 1}
    assert json.load(open(tmp_path / "t.json"))["routing"]["hook"]["key"] == "kick"

# ---- shared spaces ----------------------------------------------------------------------------------------------------
def _burst(trk, t0=.2, dur=.15, hz=900):
    x = trk.buf(); i = int(t0 * trk.sr); n = int(dur * trk.sr)
    x[i:i + n] = (np.sin(2 * np.pi * hz * np.arange(n) / trk.sr) * np.hanning(n) * .5).astype(np.float32)[:, None]; return x

def test_room_return_has_a_tail_and_steps_back_while_the_source_plays():
    trk = Track(120, 2, seed=1); x = _burst(trk)
    a = B.Space(trk, "plate", back_db=0, seed=7); a.send(x, 1.0); wa = a.render()
    b = B.Space(trk, "plate", back_db=-9, seed=7); b.send(x, 1.0); wb = b.render()
    tail = slice(int(.6 * SR), int(1.2 * SR)); during = slice(int(.25 * SR), int(.33 * SR))
    assert db(wa[tail]) > -70 and db(x[tail]) < -200                           # the room rings after the dry sound ended
    assert db(wb[during]) < db(wa[during]) - 4 and abs(db(wb[tail]) - db(wa[tail])) < 1.5     # back while it plays, blooms after
    assert not a.pending and np.allclose(a.render(), 0)                       # the send buffer is emptied by render

def test_echo_repeats_on_the_grid_each_one_quieter_and_darker():
    trk = Track(120, 2, seed=1); x = trk.buf(); i = int(.1 * SR); x[i:i + 200] = np.random.default_rng(0).normal(0, .3, (200, 1)).astype(np.float32)
    sp = B.Space(trk, "echo", steps=4, fb=.5, back_db=0); sp.send(x, 1.0); w = sp.render(); d = int(round(4 * trk.S16 * SR))
    r1, r2, r3 = (w[i + k * d - 400:i + k * d + 2000] for k in (1, 2, 3))
    cen = lambda s: (lambda P, f: float((f * P).sum() / P.sum()))(np.abs(np.fft.rfft(s[:, 0])) ** 2, np.fft.rfftfreq(len(s), 1 / SR))
    assert db(r1) > db(r2) + 3 > db(r3) + 6 and cen(r2) < cen(r1) and db(w[i + d // 2 - 300:i + d // 2 + 300]) < db(r1) - 20

def test_unknown_space_kind_and_late_configuration_are_errors():
    trk = Track(120, 2, seed=1)
    with pytest.raises(ValueError): B.Space(trk, "cathedral")
    trk.space("room")
    with pytest.raises(ValueError): trk.space("room", decay_s=3)

# ---- depth ------------------------------------------------------------------------------------------------------------
def test_depth_takes_top_away_and_sends_into_the_room():
    trk = Track(120, 2, seed=1, humanize_s=0).sections([(0, 2, "A", {"a": 1, "b": 1})])
    x = tone(trk, 200) + tone(trk, 8000); far = B.distance(x, 1.0, SR); mid = B.distance(x, .5, SR)
    seg = slice(SR // 2, SR)
    assert band_db(far[seg], SR, 7000, 9000) < band_db(mid[seg], SR, 7000, 9000) - 2 < band_db(x[seg], SR, 7000, 9000) - 4
    assert abs(band_db(far[seg], SR, 150, 250) - band_db(x[seg], SR, 150, 250)) < 3 and B.distance(x, 0, SR) is x
    trk.add("a", x, 1.0); trk.add("b", x, .5, depth=.8)
    assert trk.routing["b"]["send"] == {"room": .28} and trk.spaces["room"].pending and trk.routing["a"]["send"] == {}

# ---- studio master ----------------------------------------------------------------------------------------------------
def test_knee_clip_leaves_the_body_alone_and_bends_only_the_peaks():
    from autodj.compose.master import knee_clip
    t = np.arange(SR) / SR; body = (.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)[:, None].repeat(2, 1)
    y = knee_clip(body); assert abs(db(y) - db(body)) < .02 and np.abs(y - body).max() < 2e-3          # below the knee: linear
    loud = (np.sin(2 * np.pi * 60 * t)).astype(np.float32)[:, None].repeat(2, 1); z = knee_clip(loud)
    assert np.abs(z).max() < 10 ** (-1.6 / 20) and np.abs(z).max() > 10 ** (-3 / 20)                  # peaks ~2 dB down

def test_clip_premaster_distorts_the_quiet_part_less_than_tanh(tmp_path):
    import soundfile as sf
    from autodj.compose.master import premaster
    t = np.arange(4 * SR) / SR; x = .12 * np.sin(2 * np.pi * 300 * t)
    for k in range(8): i = int((k + .25) * .5 * SR); x[i:i + 2000] += .9 * np.sin(2 * np.pi * 55 * np.arange(2000) / SR) * np.exp(-np.arange(2000) / 500)
    sf.write(tmp_path / "raw.wav", np.stack([x, x], 1).astype(np.float32), SR, subtype="FLOAT")
    def h3(mode):
        premaster(str(tmp_path / "raw.wav"), str(tmp_path / f"{mode}.wav"), mode=mode); y, _ = sf.read(tmp_path / f"{mode}.wav")
        seg = y[int(.02 * SR):int(.1 * SR), 0]                               # the tone alone, between two kicks
        return band_db(seg[:, None], SR, 850, 950) - band_db(seg[:, None], SR, 250, 350)
    assert h3("clip") < h3("sat") - 20                                        # third harmonic of the tone: far lower

def test_studio_master_hits_its_lufs_target_and_reports_it(tmp_path):
    pytest.importorskip("pyloudnorm")
    import soundfile as sf
    from autodj.compose.master import warm
    rng = np.random.default_rng(0); t = np.arange(12 * SR) / SR
    x = (.1 * np.sin(2 * np.pi * 110 * t) + .03 * rng.normal(0, 1, len(t))) * (.6 + .4 * np.sin(2 * np.pi * 2 * t))
    sf.write(tmp_path / "pre.wav", np.stack([x, x], 1).astype(np.float32), SR, subtype="FLOAT")
    ms = warm(str(tmp_path / "pre.wav"), str(tmp_path / "m.mp3"), -14.0, mode="studio")
    assert ms["mode"] == "studio" and abs(ms["lufs"] + 14.0) < .6 and ms["peak_db"] <= -1.4

def test_end_to_end_with_buses_spaces_and_the_studio_master(tmp_path, monkeypatch):
    from autodj.compose.run import main
    import autodj.compose.run as R; R.REGISTRY = str(tmp_path / "reg.jsonl")
    score = tmp_path / "graph.py"
    score.write_text(textwrap.dedent('''
        import numpy as np
        from autodj.compose import Track, mono2
        from autodj.compose.bus import glue
        META = {"title": "graph", "target": -16, "master": "studio"}
        def build(seed):
            trk = Track(120, 16, seed=seed).sections([(0, 16, "A", {"kick": 1, "tone": 1, "pad": 1})])
            t = np.arange(int(.3 * trk.sr)) / trk.sr; k = mono2((np.sin(2*np.pi*55*t) * np.exp(-t/.08)).astype(np.float32)); kb = trk.buf()
            for br in range(16):
                for st in (0, 4, 8, 12): trk.place(kb, k, br * trk.BAR + st * trk.S16)
            trk.bus("drums", fx=[glue()])
            trk.add("kick", kb, 1.0, bus="drums")
            trk.add("tone", mono2((np.sin(2*np.pi*110*trk.tt) * .1).astype(np.float32)), .4, duck=-6, key="kick")
            trk.add("pad", mono2((np.sin(2*np.pi*440*trk.tt) * .1).astype(np.float32)), .15, depth=.7, send={"echo": .2})
            trk.mono_low(140)
            return trk
    '''))
    s = main(["run", str(score), "--seed", "3", "--outdir", str(tmp_path)])
    assert os.path.exists(s["file"]) and s["master"]["mode"] == "studio" and s["silent_layers"] == []
