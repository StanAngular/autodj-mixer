"""P140: «резкий щелчок в верху» in every render. The clock sidechain stepped the gain in one sample on every beat; recordings cut
mid-wave clicked on every hit; fx.silence_beat / fx.stutter jumped back in. And the old number could not say when or which layer."""
import os, sys, json, textwrap
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt
from autodj.compose import Track, mono2, clicks as K, fx
from autodj.generate.mixbus import sidechain_duck

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SR = 44100

def hf_step(x, skip=SR // 4):
    """the old metric (checks.stereo_metrics): biggest step of the 6+ kHz band (after the first 0.25 s: a tone switched on at
    t=0 has a step of its own)"""
    m = x.mean(1) if x.ndim == 2 else x
    return 20 * np.log10(np.abs(np.diff(sosfilt(butter(4, 6000, "high", fs=SR, output="sos"), m)[skip:])).max() + 1e-12)

def bass(sec=8, f=55.0, amp=.35):
    t = np.arange(int(SR * sec)) / SR
    return mono2((amp * (np.sin(2 * np.pi * f * t) + .4 * np.sin(4 * np.pi * f * t) + .2 * np.sin(6 * np.pi * f * t))).astype(np.float32))

def hats(sec=8, every=.25, seed=0):
    rng = np.random.default_rng(seed); n = int(SR * .15); out = np.zeros(int(SR * sec), np.float32)
    e = np.minimum(np.arange(n) / (.0008 * SR), 1) * np.exp(-np.arange(n) / (.04 * SR))
    for k in range(int(sec / every) - 1):
        z = sosfilt(butter(2, 7000, "high", fs=SR, output="sos"), rng.normal(0, 1, n)) * e
        i = int(k * every * SR); out[i:i + n] += (.3 * z / np.abs(z).max()).astype(np.float32)
    return out

# ---- the clock duck -------------------------------------------------------------------------------------------------------
def test_the_clock_duck_pumps_the_same_without_a_step_on_every_beat():
    b = bass(); beat = int(60 / 124 * SR)
    old = sidechain_duck(b, SR, beat, -6.0, release_ms=140, attack_ms=0)
    new = sidechain_duck(b, SR, beat, -6.0, release_ms=140)
    assert hf_step(b) < -100 and hf_step(old) > -25 and hf_step(new) < -40                 # the bass has no top: the click was the duck
    pre = np.zeros(len(b), bool)
    for pos in range(beat, len(b), beat): pre[pos - 22:pos] = True
    assert np.allclose(new[~pre], old[~pre]) and np.allclose(new[::beat], old[::beat])     # same dip, same depth on the beat, same release

def test_the_dj_rework_ducks_ramp_too():
    import club_rework as cr, club_underlay as cu
    b = bass(4); q = int(60 / 128 * SR)
    for f in (cr.sidechain_duck, cu.sidechain_duck):
        assert hf_step(f(b, SR, q, depth_db=-6.0, attack_ms=0)) > -25 and hf_step(f(b, SR, q, depth_db=-6.0)) < -40

# ---- edges / declick ------------------------------------------------------------------------------------------------------
def test_declick_ramps_only_hard_edges_and_returns_clean_recordings_untouched():
    t = np.arange(4000) / SR; clean = (np.sin(2 * np.pi * 200 * t) * np.hanning(4000)).astype(np.float32)
    assert K.edges(clean) == (0.0, 0.0) or max(K.edges(clean)) < K.EDGE
    assert K.declick(clean) is clean
    cut = np.cos(2 * np.pi * 200 * t).astype(np.float32)                                   # starts at its peak, ends mid-wave
    s, e = K.edges(cut); assert s > .9 and e > .1
    d = K.declick(cut); assert d is not cut and abs(d[0]) < 1e-6 and abs(d[-1]) < 1e-6 and np.allclose(d[200:-200], cut[200:-200])
    pre = np.concatenate([np.zeros(50, np.float32), cut]); assert abs(K.declick(pre)[50]) < 1e-6   # digital silence, then a jump
    st = mono2(cut); assert K.declick(st).shape == st.shape and abs(K.declick(st)[0]).max() < 1e-6

def test_steps_tell_a_click_from_an_attack():
    h = hats(); r = K.steps(h)
    assert len(r["idx"]) == 0 and r["max"][2] < K.ISO_DB                                   # hats: fast, but nothing jumps
    t = np.arange(SR * 8) / SR; pad = (.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    cut = int(SR * 5.1) + int(SR / 220 / 4); pad[cut:] = 0                                  # a pad cut at its peak, between two hats
    r = K.steps(h + pad); hit = [i for i in r["idx"] if abs(i - cut) < 50]
    assert hit and r["iso"][list(r["idx"]).index(hit[0])] >= K.ISO_DB

# ---- the track -----------------------------------------------------------------------------------------------------------
def kick_cut_midwave():
    t = np.arange(int(SR * .35)) / SR; f = 50 + 110 * np.exp(-t / .03)
    k = np.sin(2 * np.pi * np.cumsum(f) / SR + np.pi / 2) * np.exp(-t / .2)                # starts at its peak (cut on the transient)
    return mono2(k.astype(np.float32))

def test_place_ramps_hard_recordings_and_the_report_counts_them():
    def render(dc):
        trk = Track(124, 4, seed=1, humanize_s=0).sections([(0, 4, "A", {"kick": 1})]); trk.declick = dc
        b = trk.buf(); k = kick_cut_midwave()
        for br in range(4):
            for beat in range(4): trk.place(b, k, br * trk.BAR + beat * trk.BAR / 4 + .01)
        trk.add("kick", b, 1.0); return trk
    on, off = render(True), render(False)
    assert on.declicked == 16 and off.declicked == 0
    assert len(on.steps["kick"]["idx"]) == 0 and len(off.steps["kick"]["idx"]) >= 14

def test_finish_names_the_layer_that_clicks(tmp_path):
    trk = Track(124, 4, seed=1, humanize_s=0).sections([(0, 4, "A", {"hats": 1, "pad": 1})])
    trk.add("hats", mono2(hats(trk.N / SR)), 1.0)
    t = trk.tt; pad = mono2((.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)); cut = trk.i(2) + int(SR / 220 / 4) + 5000
    pad[cut:] *= .3                                                                         # a gain step (a hard switch) in the pad
    trk.add("pad", pad, .5)
    info = trk.finish(str(tmp_path / "c.wav"))
    c = info["clicks"]; assert "pad" in c["layers"] and "hats" not in c["layers"]
    assert abs(c["layers"]["pad"]["worst_t"] - cut / SR) < .002
    assert any(s["layer"] == "pad" and abs(s["t"] - cut / SR) < .002 for s in c["bus"]["steps"])
    notes = K.explain(c); assert any("pad" in n for n in notes)
    json.dumps(c)                                                                           # goes into the info / summary json

def test_silence_beat_and_stutter_leave_no_step():
    def mk():
        trk = Track(124, 4, seed=1, humanize_s=0).sections([(0, 4, "A", {"pad": 1})])
        x = (.3 * np.sin(2 * np.pi * 220 * trk.tt + .7) * np.minimum(trk.tt / .01, 1)).astype(np.float32)   # (switched on softly)
        trk.add("pad", mono2(x), 1.0); return trk
    a = mk(); fx.silence_beat(a, 2); assert len(K.steps(a.mix)["idx"]) == 0
    b = mk(); fx.stutter(b, 1); assert len(K.steps(b.mix)["idx"]) == 0

def test_a_sampler_note_longer_than_its_recording_ends_ramped(tmp_path):
    from autodj.compose.sfz import SFZ
    t = np.arange(int(SR * .5)) / SR; sf.write(tmp_path / "s.wav", (.8 * np.sin(2 * np.pi * 261.63 * t + .9)).astype(np.float32), SR)
    (tmp_path / "s.sfz").write_text("<region> sample=s.wav lokey=0 hikey=127 pitch_keycenter=60 ampeg_release=0.1\n")
    inst = SFZ(str(tmp_path / "s.sfz"), tune=False); y = inst.render([(0.1, 60, 100, 2.0)], 3.0)   # the note is 4x the recording
    assert len(K.steps(y)["idx"]) == 0

def test_scan_lists_the_recordings_with_hard_edges(tmp_path, capsys):
    t = np.arange(4000) / SR
    sf.write(tmp_path / "clean.wav", (np.sin(2 * np.pi * 200 * t) * np.hanning(4000)).astype(np.float32), SR)
    sf.write(tmp_path / "cut.wav", np.cos(2 * np.pi * 200 * t).astype(np.float32), SR)
    rows = K.scan(str(tmp_path)); assert [os.path.basename(r[3]) for r in rows] == ["cut.wav"]
    assert K.main(["scan", str(tmp_path)]) == 0 and "cut.wav" in capsys.readouterr().out

def test_run_reports_where_the_wave_jumps(tmp_path):
    from autodj.compose.run import main
    import autodj.compose.run as R; R.REGISTRY = str(tmp_path / "reg.jsonl")
    score = tmp_path / "c.py"
    score.write_text(textwrap.dedent('''
        import numpy as np
        from autodj.compose import Track, mono2
        META = {"title": "Click Test", "target": -18, "gates": {"click_dbfs": -90.0}}
        def build(seed):
            trk = Track(120, 8, seed=seed).sections([(0, 8, "home", {"pad": 1})])
            x = mono2((np.sin(2 * np.pi * 220 * trk.tt + .7) * .2).astype(np.float32)); x[trk.i(4) + 777:] *= .25
            trk.add("pad", x, .5); return trk
    '''))
    s = main(["run", str(score), "--seed", "1", "--outdir", str(tmp_path)])
    assert "pad" in s["clicks"]["layers"] and s["click_notes"] and s["hf_step_t"] is not None
    assert any(p.startswith("резкий щелчок") and "самый резкий" in p for p in s["problems"])

def test_attacks_alone_do_not_fail_the_click_gate(tmp_path):
    """the same pad without its gain step, with loud sharp hats: the top jumps (attacks), the wave does not"""
    from autodj.compose.run import main
    import autodj.compose.run as R; R.REGISTRY = str(tmp_path / "reg.jsonl")
    body = textwrap.dedent('''
        import numpy as np
        from scipy.signal import butter, sosfilt
        from autodj.compose import Track, mono2
        META = {"title": "Attack Test", "target": -12, "gates": GATES}
        def build(seed):
            trk = Track(120, 8, seed=seed).sections([(0, 8, "home", {"hats": 1, "pad": 1})]); rng = np.random.default_rng(0); h = trk.buf()
            n = int(.08 * trk.sr); e = np.minimum(np.arange(n) / 30, 1) * np.exp(-np.arange(n) / (.012 * trk.sr))
            for k in range(64):
                z = sosfilt(butter(2, 6500, "high", fs=trk.sr, output="sos"), rng.normal(0, 1, n)) * e; trk.place(h, mono2((z / np.abs(z).max()).astype(np.float32)), k * trk.BAR / 8 + .01)
            trk.add("hats", h, 1.0)
            x = mono2((np.sin(2 * np.pi * 220 * trk.tt) * np.minimum(trk.tt / .02, 1) * .2).astype(np.float32)); trk.add("pad", x, .3); return trk
    ''')
    for strict in (False, True):
        score = tmp_path / f"a{int(strict)}.py"; score.write_text(body.replace("GATES", str({"click_dbfs": -60.0, "click_strict": strict})))
        s = main(["run", str(score), "--seed", "1", "--outdir", str(tmp_path)])
        assert s["clicks"]["bus"]["max"]["kind"] == "attack" and not s["clicks"]["layers"]
        assert any(p.startswith("резкий щелчок") for p in s["problems"]) == strict
        assert strict or s["click_notes"][0].startswith("гейт щелчка снят")
