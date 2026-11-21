"""P153 kicktune: the kick's pitch class, the shift to the tonic/fifth, kick_in_key, retune, and the report of untuned kicks (both sides)"""
import numpy as np, pytest, soundfile as sf
from autodj.compose import kicktune as KT, fresh, ears

def kick(tmp_path, name, f0, sweep=0.0):
    t = np.arange(int(.35 * 44100)) / 44100; f = f0 * (1 + sweep * np.exp(-t / .02)); y = np.sin(2 * np.pi * np.cumsum(f) / 44100) * np.exp(-t / .12)
    p = str(tmp_path / name); sf.write(p, y.astype(np.float32), 44100); return p

@pytest.fixture(autouse=True)
def _clean(): KT.TUNED.clear(); fresh.PATHS.clear(); yield; KT.TUNED.clear(); fresh.PATHS.clear()

def test_pitch_class_of_a_steady_kick(tmp_path):
    assert KT.kick_pc(kick(tmp_path, "e_kick.wav", 82.41)) == 4 and KT.kick_pc(kick(tmp_path, "a_kick.wav", 110.0)) == 9

def test_offset_goes_to_the_nearest_of_tonic_or_fifth_and_zero_on_them():
    assert KT.offset(4, "E") == 0 and KT.offset(11, "E") == 0                    # E and B in E
    assert KT.offset(1, "E") == -2 and KT.offset(9, "E") == 2 and KT.offset(3, "E") == 1 and KT.offset(0, "E") == -1       # C# -2 (down to B), A +2 (to B), D# +1, C -1 (to B)
    assert KT.offset(7, "E") == -3 and KT.offset(8, "E") == 3                      # the two worst cases are still within 3.5

def test_kick_in_key_takes_one_within_range_and_registers_the_shift(tmp_path):
    k1 = kick(tmp_path, "cs_kick.wav", 69.30); k2 = kick(tmp_path, "e_kick.wav", 82.41)                       # C# and E
    p, st = KT.kick_in_key([k1, k2], "E", np.random.default_rng(1), db={"tracks": {}}); assert p in (k1, k2) and KT.TUNED[p] == st and (st == 0 if p == k2 else st == -2)

def test_a_kick_further_than_max_shift_is_refused_and_an_empty_list_raises(tmp_path):
    g = kick(tmp_path, "g_kick.wav", 98.0)                                                                  # G: 3 st from E
    assert KT.kick_in_key([g], "E", None, db={"tracks": {}}, max_shift=3)[1] == -3
    with pytest.raises(ValueError): KT.kick_in_key([g], "E", None, db={"tracks": {}}, max_shift=2)
    with pytest.raises(ValueError): KT.kick_in_key([], "E")

def test_retune_changes_length_and_pitch_by_the_asked_amount(tmp_path):
    x = np.sin(2 * np.pi * 100 * np.arange(8820) / 44100).astype(np.float32)
    y = KT.retune(x, 12); assert abs(len(y) - len(x) / 2) <= 1 and KT.retune(x, 0.01) is x
    f = lambda z: np.argmax(np.abs(np.fft.rfft(z, 1 << 15))) * 44100 / (1 << 15); assert abs(f(y) / f(x) - 2) < .05

def test_report_flags_an_untuned_off_key_kick_and_skips_tuned_and_in_key_ones(tmp_path):
    bad = kick(tmp_path, "cs_kick.wav", 69.30); ok = kick(tmp_path, "e2_kick.wav", 82.41); tuned = kick(tmp_path, "d_kick.wav", 73.4)
    for p in (bad, ok, tuned): fresh.used(p)
    KT.TUNED[tuned] = 2.0
    r = KT.report(list(fresh.USED), "E"); assert [n for n, d in r] == ["cs_kick.wav"] and r[0][1] == -2
    assert KT.report(list(fresh.USED), "C#") == [("e2_kick.wav", -3.0)]                                       # other key: the verdict follows the tonic (the C# kick is now in key)
    assert KT.report([], "E") == [] and KT.report(["hat.wav", "x_snare.wav"], "E") == []                      # no kicks / not kicks: nothing

def test_the_problem_line_needs_a_tonic_and_names_the_fix(tmp_path):
    bad = kick(tmp_path, "cs_kick.wav", 69.30); fresh.used(bad)
    assert "подстрой" in ears.kick_tuning_problems(list(fresh.USED), {"tonic": "E"})[0] and ears.kick_tuning_problems(list(fresh.USED), {}) == [] and ears.kick_tuning_problems(None, {"tonic": "E"}) == []
