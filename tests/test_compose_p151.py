"""P151: do the hat layers own the top of the spectrum (ears.top_balance / top_problems / top_failures), both sides"""
import types, numpy as np
from autodj.compose import ears

def trk(layers):
    """layers: {name: {band: energy}} -> a fake track whose act has one step"""
    act = {}
    for n, d in layers.items():
        e = np.zeros((1, 16), dtype=np.float64)
        for b, v in d.items(): e[0, b] = v
        act[n] = e
    return types.SimpleNamespace(act=act)

HOT = {"kick": {1: 1.0}, "keys": {8: .1}, "hats": {14: .06, 15: .02}, "snare": {14: .01}}            # hats carry most of the top, top near the body
QUIET = {"kick": {1: 1.0}, "keys": {8: .1}, "hats": {14: .002}, "snare": {14: .002}}

def test_hats_that_own_a_loud_top_are_reported_with_a_trim():
    t = ears.top_balance(trk(HOT)); assert t["hat_share_of_top"] > .4 and t["top_vs_body_db"] > ears.TOP_VS_BODY_MAX_DB and t["hat_trim_db"] < 0
    p = ears.top_problems(t); assert p and "хэты торчат" in p[0]

def test_a_quiet_top_passes_even_if_hats_are_all_of_it():
    t = ears.top_balance(trk({"kick": {1: 1.0}, "keys": {8: .1}, "hats": {14: .0005}})); assert t["hat_share_of_top"] == 1.0 and t["top_vs_body_db"] <= ears.TOP_VS_BODY_MAX_DB
    assert ears.top_problems(t) == [] and t["hat_trim_db"] == 0.0

def test_a_loud_top_that_is_not_the_hats_passes():
    t = ears.top_balance(trk({"kick": {1: 1.0}, "keys": {8: .1}, "hats": {14: .002}, "lead": {14: .08}})); assert t["hat_share_of_top"] < .4 and ears.top_problems(t) == []

def test_the_trim_really_brings_the_top_down_to_the_limit():
    H = {**HOT, "snare": {14: .002}}; t = ears.top_balance(trk(H)); k = 10 ** (t["hat_trim_db"] / 10); assert -12 < t["hat_trim_db"] < -3
    trimmed = {**H, "hats": {14: .06 * k, 15: .02 * k}}; t2 = ears.top_balance(trk(trimmed)); assert t2["top_vs_body_db"] <= ears.TOP_VS_BODY_MAX_DB + .2

def test_unknown_is_none_and_no_problem():
    assert ears.top_balance(types.SimpleNamespace(act={})) is None and ears.top_problems(None) == []

def test_the_gate_is_opt_in_and_only_for_the_hat_case():
    t = ears.top_balance(trk(HOT)); assert ears.top_failures({"top": t}, {}) == [] and ears.top_failures({"top": t}, {"gates": {"hat_top_max": .3}}) == ["hat_top"]
    assert ears.top_failures({"top": t}, {"gates": {"hat_top_max": .9}}) == [] and ears.gate_failures({"top": t}, {"gates": {"hat_top_max": .3}}) == ["hat_top"]
    q = ears.top_balance(trk(QUIET)); assert ears.top_failures({"top": q}, {"gates": {"hat_top_max": .1}}) == []

def test_when_the_other_layers_alone_are_over_the_limit_the_trim_is_capped_not_infinite():
    t = ears.top_balance(trk({"kick": {1: 1.0}, "keys": {8: .1}, "hats": {14: .02}, "lead": {14: .5}})); assert t["hat_trim_db"] == -12.0 or t["hat_share_of_top"] < .4
