"""P155 band_owners / band_problems, both sides"""
import types, numpy as np
from autodj.compose import ears
from autodj.compose.depth import EDGES

def trk(layers):
    mid = np.sqrt(np.asarray(EDGES[:-1]) * np.asarray(EDGES[1:])); act = {}
    for n, d in layers.items():
        e = np.zeros((1, len(mid)))
        for f, v in d.items(): e[0, int(np.argmin(np.abs(mid - f)))] = v
        act[n] = e
    return types.SimpleNamespace(act=act)

def test_owners_per_band_and_heard_level():
    bo = ears.band_owners(trk({"kick": {50: 1.0, 8000: .05}, "hook": {1000: .2}, "hats": {9000: .01}}))
    assert bo["bands"]["sub"][0][0] == "kick" and bo["bands"]["mid"][0][0] == "hook" and bo["bands"]["top"][0][0] == "kick"
    assert list(bo["heard_db"])[0] in ("hook", "kick") and bo["heard_db"][list(bo["heard_db"])[0]] == 0.0
    assert bo["heard_db"]["hook"] > bo["heard_db"]["hats"]                                  # A-weighting: 1 kHz counts, 9 kHz hats at -13 dB energy do not win

def test_a_kick_owning_the_top_is_reported_and_hats_owning_it_are_not():
    assert ears.band_problems(ears.band_owners(trk({"kick": {50: 1.0, 8000: .05}, "hats": {9000: .01}, "keys": {800: .1}})))
    assert ears.band_problems(ears.band_owners(trk({"kick": {50: 1.0}, "hats": {9000: .05}, "keys": {800: .1}}))) == []
    assert ears.band_problems(None) == [] and ears.band_owners(types.SimpleNamespace(act={})) is None
