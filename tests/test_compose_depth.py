"""P133: ears for depth. Each test builds a tiny synthetic track whose flatness (or life) is known and checks that the report says so."""
import importlib.util, os
import numpy as np
import pytest
from autodj.compose import Track, mono2
from autodj.compose import depth as D

SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def trk_(bars=24, lv=None):
    return Track(120, bars, seed=1, humanize_s=0).sections([(0, bars, "A", lv or {"kick": 1, "a": 1, "b": 1, "hats": 1})])

def hits(trk, steps, hz=None, amp=.5, dur=.1, bars=None, bright=None):
    """a pattern of short tones (hz) or noise bursts on the given 16th steps of every bar; bright(bar) -> low-pass corner per bar"""
    from scipy.signal import butter, sosfilt
    x = trk.buf(); n = int(dur * trk.sr); t = np.arange(n) / trk.sr; rng = np.random.default_rng(3)
    for br in (bars if bars is not None else range(trk.bars)):
        for st in steps:
            h = (np.sign(np.sin(2 * np.pi * hz * t)) if hz else rng.normal(0, 1, n)) * np.exp(-t / (dur / 3)) * amp
            if bright: h = sosfilt(butter(2, bright(br), "low", fs=trk.sr, output="sos"), h)
            trk.place(x, mono2(h.astype(np.float32)), br * trk.BAR + st * trk.S16)
    return x

def held(trk, hz, amp=.2):
    return mono2((np.sign(np.sin(2 * np.pi * hz * trk.tt)) * amp).astype(np.float32))

# ---- the map ----------------------------------------------------------------------------------------------------------
def test_activity_puts_energy_on_the_right_steps_and_bands():
    trk = trk_(2); E = D.activity(hits(trk, (0, 8), hz=1000), SR, trk.S16, 32); c = np.sqrt(D.EDGES[:-1] * D.EDGES[1:])
    assert E.shape == (32, D.NB) and E[[0, 8, 16, 24]].sum() > 100 * E[[3, 5, 12, 20]].sum()
    assert abs(np.log2(c[int(np.argmax(E[0]))] / 1000)) < .6

# ---- motion -------------------------------------------------------------------------------------------------------------
def test_a_frozen_loop_is_found_with_its_period_and_a_moving_one_is_not():
    trk = trk_(24)
    one = D.layer_motion(D.activity(hits(trk, (0, 3, 6, 10), hz=220), SR, trk.S16, 24 * 16), 24)
    assert one["loop_bars"] == 1 and one["frozen_bars"] >= 23 and one["repeat_db"] < .3
    x4 = hits(trk, (0, 3, 6, 10), hz=220, bars=[b for b in range(24) if b % 4 != 3]) + hits(trk, (0, 4, 8, 12, 14), hz=330, bars=range(3, 24, 4))
    four = D.layer_motion(D.activity(x4, SR, trk.S16, 24 * 16), 24); assert four["loop_bars"] == 4 and four["frozen_bars"] >= 20
    moving = D.layer_motion(D.activity(hits(trk, (0, 3, 6, 10), hz=220, bright=lambda br: 300 * 2 ** (2 + 2 * np.sin(br * .7))), SR, trk.S16, 24 * 16), 24)
    assert moving["frozen_bars"] <= 2 and moving["repeat_db"] > 1.0                      # the same notes, but the tone travels

def test_report_names_the_frozen_layer_and_spares_the_kick():
    trk = trk_(24); trk.add("kick", hits(trk, (0, 4, 8, 12), hz=55, dur=.2), 1.0)
    trk.add("a", hits(trk, (2, 5, 9, 14), hz=220), .5); trk.add("b", hits(trk, (3, 7, 11), hz=440, bright=lambda br: 400 * 2 ** (br / 5)), .5)
    r = D.report(trk)
    assert r["static"] == ["a"] and r["layers"]["kick"]["frozen_bars"] >= 23 and r["score"]["motion"] == .5
    assert any("«a» — петля" in n for n in r["notes"]) and not any("«kick»" in n or "«b» — петля" in n for n in r["notes"])

# ---- interaction ----------------------------------------------------------------------------------------------------------
def test_pump_is_measured_and_links_are_listed():
    def build(keyed):
        trk = trk_(8, {"kick": 1, "pad": 1}); trk.add("kick", hits(trk, (0, 4, 8, 12), hz=55, dur=.2), 1.0)
        trk.add("pad", held(trk, 220), .4, **(dict(duck=-9, key="kick") if keyed else {})); return D.report(trk)
    k, n = build(True), build(False)
    assert k["layers"]["pad"]["pump_db"] < -2.5 and abs(n["layers"]["pad"]["pump_db"]) < .5
    assert k["links"] == [["pad", "kick", -9, None]] and k["score"]["interaction"] > n["score"]["interaction"] == 0
    assert any("ни один слой не реагирует" in x for x in n["notes"]) and not any("не реагирует" in x for x in k["notes"])

def test_clock_duck_is_called_out_and_follow_counts_as_a_link():
    trk = trk_(8, {"kick": 1, "pad": 1, "b": 1}); trk.add("kick", hits(trk, (0, 4, 8, 12), hz=55, dur=.2), 1.0)
    trk.add("pad", held(trk, 220), .4, duck=-6); trk.add("b", held(trk, 880) * trk.follow("kick", invert=True), .2)
    r = D.report(trk)
    assert r["clock_ducks"] == ["pad"] and r["followed"] == ["kick"] and any("duck по часам" in x for x in r["notes"]) and r["score"]["interaction"] == .25

def test_doubles_and_dialogs():
    trk = trk_(8, {"a": 1, "b": 1, "c": 1, "hats": 1, "kick": 1})
    trk.add("a", hits(trk, (0, 3, 6, 10), hz=220), 1.0); trk.add("b", hits(trk, (0, 3, 6, 10), hz=660), .8)       # b doubles a
    trk.add("c", hits(trk, (2, 8, 13), hz=440), .8); trk.add("hats", hits(trk, (2, 8, 13), amp=.1), .3)           # c answers a; hats are drums
    r = D.report(trk); dia = {tuple(x[:2]) for x in r["dialogs"]}
    assert [x[:2] for x in r["doubles"] if "hats" not in x] == [["a", "b"]] and ("a", "c") in dia and not any("hats" in p for p in dia)
    assert any("«a» и «b» бьют в одни и те же доли" in n for n in r["notes"])

# ---- masking ----------------------------------------------------------------------------------------------------------------
def test_a_buried_layer_is_reported_with_its_masker():
    rng = np.random.default_rng(0)
    trk = trk_(8, {"wall": 1, "a": 1, "b": 1}); trk.add("wall", mono2(rng.normal(0, .3, trk.N).astype(np.float32)), 1.0)
    trk.add("a", held(trk, 800), .05); r = D.report(trk)
    assert r["layers"]["a"]["masked"] > .8 and r["layers"]["a"]["masker"] == "wall" and r["hidden"] == ["a"] and any("почти не слышен" in n for n in r["notes"])
    t2 = trk_(8, {"lo": 1, "hi": 1}); t2.add("lo", held(t2, 60), 1.0); t2.add("hi", hits(t2, (2, 6, 10, 14), amp=.2), .3)
    assert D.report(t2)["hidden"] == []

# ---- space and texture ------------------------------------------------------------------------------------------------------
def test_planes_spaces_and_their_notes():
    flat = trk_(8, {"a": 1, "b": 1, "c": 1}); [flat.add(n, held(flat, hz), 1.0) for n, hz in (("a", 110), ("b", 330), ("c", 990))]; rf = D.report(flat)
    assert rf["planes"] == {"front": ["a", "b", "c"], "middle": [], "back": []} and rf["score"]["space"] == 0
    assert any("на одном расстоянии" in n for n in rf["notes"]) and any("нет общего пространства" in n for n in rf["notes"])
    deep = trk_(8, {"a": 1, "b": 1, "c": 1}); deep.add("a", held(deep, 110), 1.0, send={"echo": .3}); deep.add("b", held(deep, 330), .5, depth=.4); deep.add("c", held(deep, 990), .3, depth=.9, send={"hall": .3})
    rd = D.report(deep)
    assert rd["planes"] == {"front": ["a"], "middle": ["b"], "back": ["c"]} and rd["score"]["space"] == 1.0 and set(rd["spaces"]) == {"echo", "room", "hall"}
    assert not any("расстоянии" in n or "пространства" in n for n in rd["notes"])

def test_texture_counts_layer_combinations():
    trk = Track(120, 48, seed=1, humanize_s=0).sections([(0, 8, "A", {"a": 1}), (8, 48, "B", {"a": 1, "b": 1})])
    trk.add("a", held(trk, 110), 1.0); trk.add("b", held(trk, 440), .5); r = D.report(trk)
    assert r["texture"]["states"] == 2 and r["texture"]["changes"] == 1 and 40 <= r["texture"]["longest_same_bars"] <= 41 and any("фактура не меняется 4" in n for n in r["notes"])

def test_gates_are_opt_in():
    rep = {"layers": {"a": {"masked": .9}}, "static": ["a", "b"], "links": [], "followed": [], "planes": {"front": ["a"], "middle": [], "back": []}, "hidden": ["a"]}
    assert D.gates(rep, None) == [] and D.gates(rep, {"clash": 0}) == [] and D.gates({}, {"depth_links_min": 2}) == []
    p = D.gates(rep, {"depth_static_max": 0, "depth_links_min": 2, "depth_planes_min": 2, "depth_masked_max": .6})
    assert len(p) == 4 and "застывшие" in p[0] and "взаимодействий" in p[1] and "планов" in p[2] and "закрыты" in p[3]

def test_report_reaches_the_track_json_and_analysis_can_be_switched_off(tmp_path):
    import json
    trk = trk_(4, {"kick": 1}); trk.add("kick", hits(trk, (0, 4, 8, 12), hz=55, dur=.2), 1.0); trk.finish(str(tmp_path / "t.wav"))
    assert "kick" in json.load(open(tmp_path / "t.json"))["depth"]["layers"]
    off = trk_(4, {"kick": 1}); off.analyze = False; off.add("kick", hits(off, (0, 4, 8, 12), hz=55, dur=.2), 1.0)
    assert off.act == {} and D.report(off) == {"layers": {}, "notes": [], "score": {}}

# ---- the reference score: same notes, flat vs living --------------------------------------------------------------------------
def _demo(monkeypatch, flat):
    monkeypatch.setenv("AUTODJ_DEMO_BARS", "16"); monkeypatch.setenv("AUTODJ_DEMO_SYNTH_KIT", "1")
    monkeypatch.setenv("AUTODJ_DEMO_FLAT", "1") if flat else monkeypatch.delenv("AUTODJ_DEMO_FLAT", raising=False)
    spec = importlib.util.spec_from_file_location("living_demo_" + ("flat" if flat else "live"), os.path.join(ROOT, "docs", "examples", "living_demo.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); trk = m.build(7); return trk, D.report(trk)

def test_living_demo_has_depth_and_its_flat_twin_has_none(monkeypatch):
    lt, live = _demo(monkeypatch, False); ft, flat = _demo(monkeypatch, True)
    assert lt.notes.keys() == ft.notes.keys() and all(lt.notes[k] == ft.notes[k] for k in lt.notes)            # really the same notes
    assert len(live["links"]) == 4 and live["followed"] == ["hats"] and live["clock_ducks"] == [] and all(live["planes"][k] for k in live["planes"])
    assert set(live["spaces"]) == {"room", "hall", "echo"} and live["score"]["interaction"] == 1.0 and live["score"]["space"] == 1.0
    assert flat["links"] == [] and flat["clock_ducks"] == ["bass", "hook", "pad", "stab"] and flat["score"]["space"] == 0 and flat["score"]["interaction"] <= .25
    assert any("не реагирует" in n for n in flat["notes"]) and not any("не реагирует" in n or "расстоянии" in n for n in live["notes"])
    assert live["layers"]["pad"]["repeat_db"] > flat["layers"]["pad"]["repeat_db"] + .5                        # the living pad's tone travels
    assert np.isfinite(lt.mix).all() and lt.flushes.get("drums") == 1
