"""P167 rhythm profiles: data per style, aliases, mood scaling, overrides, ensemble(), and the report thresholds follow the style (both sides)"""
import types, numpy as np, pytest
from autodj.compose import rhythm_profiles as RP, rhythm as R

@pytest.fixture(autouse=True)
def _reset(): R.set_task(); yield; R.set_task()

def test_every_style_has_every_key_and_sane_values():
    for s in RP.STYLES:
        p = RP.profile(s); assert set(RP.BASE) <= set(p) and 0 <= p["swing"] <= .33 and p["kick_family"] in ("four", "two_step", "half", "broken", "sparse") and 0 <= p["dropout_beats"] <= 4
        assert p["open_hat_s"][0] <= p["open_hat_s"][1] and p["perc_per_bar"][0] <= p["perc_per_bar"][1]

def test_styles_differ_where_they_should_and_clubs_accents_are_not_everywhere():
    h, g, a, t = RP.profile("house"), RP.profile("garage"), RP.profile("ambient"), RP.profile("techno")
    assert g["swing"] > h["swing"] > t["swing"] == 0 and g["kick_family"] == "two_step" and RP.profile("downtempo")["kick_family"] == "half"
    assert a["hat_accent_db"] == 0 and a["ghost_hat_db"] is None and a["open_hat_s"] == (0.0, 0.0) and a["perc_per_bar"][1] <= 2 and a["backbeat_min_energy"] > 1.0     # no club hats in ambient

def test_aliases_and_unknown_styles():
    assert RP.profile("Tech House")["style"] == "tech_house" and RP.profile("tech_house")["shaker"] and RP.profile("deep melodic house")["style"] == "melodic" and RP.profile("UK garage")["style"] == "garage"
    with pytest.raises(ValueError): RP.profile("polka")

def test_mood_scales_the_expectations_and_overrides_win_and_are_checked():
    base = RP.profile("house"); soft = RP.profile("house", "soft"); hard = RP.profile("house", "hard")
    assert soft["hat_accent_db"] < base["hat_accent_db"] < hard["hat_accent_db"] and soft["swing"] == base["swing"]                 # swing is the style's, not the mood's
    assert RP.profile("house", swing=.2)["swing"] == .2 and RP.profile("house", dropout_beats=9)["dropout_beats"] == 4
    with pytest.raises(ValueError): RP.profile("house", swnig=.2)
    assert RP.STYLES["house"]["push_ms"] == {"bass": -3.0, "perc": -2.0} and RP.profile("house")["push_ms"] is not RP.STYLES["house"]["push_ms"]      # a copy

def test_ensemble_uses_the_profile_swing_push_and_keeps_the_kick_on_the_grid():
    BAR = 240 / 124; t = types.SimpleNamespace(bars=16, S16=BAR / 16, BAR=BAR, swing=0.0, sr=44100)
    e = RP.ensemble(t, "garage", seed=2); assert e.version == 2 and e.sw2 == .16 and e.push == {"hats": 2.0}
    assert all(e.offset_ms(b, s, "kick") == 0.0 for b in range(16) for s in range(16)) and RP.ensemble(t, "techno").sw2 == 0.0

def flat_hats_trk():
    E = np.full((256, 4), 1e-12)
    for b in range(16):
        for s in (2, 6, 10, 14): E[b * 16 + s, 1] = 10 ** (-3 + (.1 if s == 6 else 0))
    return types.SimpleNamespace(act={"hats": E}, bars=16, tl=[(0, 8, "home1"), (8, 16, "home2")], microtiming=None)

def test_report_thresholds_follow_the_style():
    t = flat_hats_trk(); R.set_task(); assert any("одной силы" in n for n in R.report(t)[1])                                  # default threshold 1.5 dB
    R.set_task(style="ambient"); assert not any("одной силы" in n for n in R.report(t)[1])                                  # ambient expects no accents
    R.set_task(style="breaks"); assert any("одной силы" in n for n in R.report(t)[1]) and R.limit("hat_contrast_min_db") == 3.0
    R.set_task(style="breaks", limits={"hat_contrast_min_db": 0.1}); assert not any("одной силы" in n for n in R.report(t)[1])    # explicit numbers win
    R.set_task(style="house", mood="soft"); assert R.limit("hat_contrast_min_db") == pytest.approx(2.0 * .6)
