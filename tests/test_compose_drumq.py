"""P154 drumq: sharp drum hits are measured and refused, soft ones pass (both sides), CI.pick filters drums by it, the report names them"""
import numpy as np, pytest, soundfile as sf
from autodj.compose import drumq, fresh, ears

SR = 44100
def body(f0=55, dur=.4, tau=.12): t = np.arange(int(dur * SR)) / SR; return (np.sin(2 * np.pi * f0 * t) * np.exp(-t / tau)).astype(np.float32)
def soft_kick(): return body()
def spiky_kick():                                                  # a one-sample click far above a small body: high crest
    x = body() * .15; x[0] = 1.0; return x
def noise_burst(lp=None, seed=0, dur=.25, tau=.04):
    t = np.arange(int(dur * SR)) / SR; n = np.random.default_rng(seed).normal(0, 1, len(t))
    if lp:
        from scipy.signal import butter, sosfilt
        n = sosfilt(butter(4, lp, "low", fs=SR, output="sos"), n)
    y = n * np.exp(-t / tau); a = int(.004 * SR); y[:a] *= np.linspace(0, 1, a); return (y / np.abs(y).max()).astype(np.float32)

@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTODJ_DRUM_QUALITY", str(tmp_path / "dq.json")); drumq._MEM.clear(); fresh.PATHS.clear(); yield; drumq._MEM.clear(); fresh.PATHS.clear()

def wav(tmp_path, name, x): p = str(tmp_path / name); sf.write(p, x, SR); return p

def test_a_round_kick_passes_and_a_spiky_one_is_refused(tmp_path):
    assert drumq.ok(wav(tmp_path, "round_kick.wav", soft_kick()), "kick")
    p = wav(tmp_path, "spiky_kick.wav", spiky_kick()); r = drumq.problems(drumq.features(p), "kick"); assert r and "crest" in r[0]

def test_a_bright_clap_is_refused_and_a_darker_one_passes(tmp_path):
    bright = wav(tmp_path, "bright_clap.wav", noise_burst(None)); dark = wav(tmp_path, "dark_clap.wav", noise_burst(3000))
    assert drumq.problems(drumq.features(bright), "clap") and drumq.ok(dark, "clap")

def test_unknown_role_or_silence_is_never_a_problem(tmp_path):
    p = wav(tmp_path, "spiky_kick.wav", spiky_kick()); assert drumq.problems(drumq.features(p), "hats") == [] and drumq.problems({"error": "silent"}, "kick") == []
    assert drumq.features(wav(tmp_path, "silent.wav", np.zeros(4410, np.float32))).get("error") == "silent"

def test_features_are_cached_by_file_name(tmp_path):
    p = wav(tmp_path, "round_kick.wav", soft_kick()); a = drumq.features(p); sf.write(p, spiky_kick(), SR); assert drumq.features(p) == a

def test_report_and_problem_line_name_only_sharp_kicks_and_claps(tmp_path):
    good = wav(tmp_path, "round_kick.wav", soft_kick()); bad = wav(tmp_path, "spiky_kick.wav", spiky_kick()); clap = wav(tmp_path, "bright_clap.wav", noise_burst(None)); hat = wav(tmp_path, "hat_x.wav", noise_burst(None, 1))
    for p in (good, bad, clap, hat): fresh.used(p)
    r = drumq.report(list(fresh.USED)); assert set(r) == {"spiky_kick.wav", "bright_clap.wav"}
    lines = ears.drum_sharp_problems(list(fresh.USED)); assert len(lines) == 2 and all("острый" in l for l in lines) and ears.drum_sharp_problems([]) == []

def test_ci_pick_drops_sharp_drums_before_freshness(tmp_path, monkeypatch):
    from autodj.compose import clap_index as CI
    good = wav(tmp_path, "round_kick.wav", soft_kick()); bad = wav(tmp_path, "spiky_kick.wav", spiky_kick())
    monkeypatch.setattr(CI, "candidates", lambda *a, **k: [bad, good]); got = {}
    monkeypatch.setattr(fresh, "pick", lambda c, rng=None, k=None, title=None, **kw: got.setdefault("c", list(c)) and c[0])
    assert CI.pick("kick", role="kick") == good and got["c"] == [good]
    monkeypatch.setattr(CI, "candidates", lambda *a, **k: [bad])
    with pytest.raises(ValueError): CI.pick("kick", role="kick")
    got.clear(); assert CI.pick("kick", role="kick", strict=False) == bad                                       # not strict: falls back rather than failing
    got.clear(); assert CI.pick("hat", role="hats") == bad                                                       # roles without limits are not filtered
