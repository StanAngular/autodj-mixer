"""P159 verdicts: words -> axes, verdict -> rule (proposed / confirmed), check, CI.pick refuses only confirmed (both sides)"""
import numpy as np, pytest, soundfile as sf
from autodj.compose import verdicts as V, drumq, fresh

SR = 44100
def kick(crest_click):
    t = np.arange(int(.4 * SR)) / SR; x = (np.sin(2 * np.pi * 55 * t) * np.exp(-t / .12)).astype(np.float32)
    if crest_click: x *= .15; x[0] = 1.0
    return x

@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTODJ_LAYER_VERDICTS", str(tmp_path / "v.jsonl")); monkeypatch.setenv("AUTODJ_DRUM_QUALITY", str(tmp_path / "dq.json")); drumq._MEM.clear(); fresh.PATHS.clear()
    yield; drumq._MEM.clear(); fresh.PATHS.clear()

def wav(tmp_path, n, x): p = str(tmp_path / n); sf.write(p, x, SR); return p

def test_words_map_to_axes():
    assert set(V.axes_of("острый и резкий, лупит втупую")) == {"crest", "atk", "cen", "static"} and V.axes_of("примитивный") == ["events"] and V.axes_of("нормально") == []

def test_one_bad_verdict_proposes_a_rule_two_confirm_it_and_a_liked_sound_is_never_refused(tmp_path):
    bad = wav(tmp_path, "sharp_kick.wav", kick(True)); good = wav(tmp_path, "round_kick.wav", kick(False))
    V.add("T", "kick", "kick", bad, "острый резкий", False); r = V.rules("kick"); assert r["crest"]["status"] == "proposed"
    f, w = V.check(bad, "kick"); assert not f and w                                             # proposed: warns, does not fail
    V.add("T", "kick", "kick", good, "лучше, мягко", True); assert not V.check(good, "kick")[0] and not V.check(good, "kick")[1]
    V.confirm("kick", "crest"); assert V.rules("kick")["crest"]["status"] == "confirmed" and V.check(bad, "kick")[0]

def test_no_rule_when_words_do_not_separate_good_from_bad(tmp_path):
    a = wav(tmp_path, "a_kick.wav", kick(True)); V.add("T", "kick", "kick", a, "острый", False); V.add("T", "kick", "kick", a, "отлично", True)
    assert "crest" not in V.rules("kick")

def test_report_and_pick(tmp_path, monkeypatch):
    from autodj.compose import clap_index as CI
    bad = wav(tmp_path, "sharp_kick.wav", kick(True)); good = wav(tmp_path, "round_kick.wav", kick(False))
    monkeypatch.setattr(drumq, "LIMITS", {"kick": {}})                                         # only the learnt rule decides here
    V.add("T", "kick", "kick", bad, "резкий", False); fresh.used(bad); fresh.used(good)
    assert V.report(list(fresh.USED)) and "не подтверждено" in V.report(list(fresh.USED))[0]
    monkeypatch.setattr(CI, "candidates", lambda *a, **k: [bad, good]); monkeypatch.setattr(fresh, "pick", lambda c, rng=None, k=None, title=None, **kw: c[0])
    assert CI.pick("kick", role="kick") == bad                                                   # proposed rule: still allowed
    V.confirm("kick", "crest"); assert CI.pick("kick", role="kick") == good                      # confirmed: refused
