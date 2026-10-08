"""P99: клубные ударные. Тесты на обе стороны: что звучит И что молчит."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import random
import numpy as np
from autodj.generate import clubdrums as cd

GR = {"hat16": True, "ride": True, "open_offbeat": True, "clap_flam_ms": 8,
      "snare_layer": 0.4, "top_gain": 0.5, "roll_bars": 2, "kick_gap_before_drop": True,
      "hat_push_ms": -2}


def ev(kind, bar_in=0, sec_len=16, nxt=None, **over):
    return cd.bar_events(kind, bar_in, sec_len, {**GR, **over}, random.Random(1), nxt)


def sounds(e, name):
    return sorted(s for s, n, _ in e if n == name)


class TestBarEvents:
    def test_drop_four_on_floor_clap_on_2_and_4(self):
        e = ev("drop", 3)
        assert sounds(e, "kick") == [0, 4, 8, 12]
        assert sounds(e, "clap") == [4, 12]

    def test_breakdown_has_no_kick_and_no_clap(self):
        e = ev("breakdown", 3)
        assert not sounds(e, "kick") and not sounds(e, "clap")

    def test_drop_dense_hats_and_offbeat_open(self):
        e = ev("drop", 2)
        assert len(sounds(e, "hat")) == 16
        assert sounds(e, "open") == [2, 6, 10, 14]

    def test_hat_accents_strong_on_offbeat(self):
        e = [x for x in ev("drop", 2) if x[1] == "hat"]
        v = {s: vv for s, _, vv in e}
        assert v[2] > v[1] and v[2] > v[3]

    def test_eighth_hats_variant(self):
        assert len(sounds(ev("drop", 2, hat16=False), "hat")) == 4

    def test_roll_before_drop_crescendo_and_densifies(self):
        e1 = [x for x in ev("build", 14, 16, "drop") if x[1] == "snare"]
        e2 = [x for x in ev("build", 15, 16, "drop") if x[1] == "snare"]
        assert len(e2) > len(e1) > 2
        assert max(v for *_, v in e2) > max(v for *_, v in e1)

    def test_kick_breath_before_drop_only_when_enabled(self):
        assert not sounds(ev("build", 15, 16, "drop"), "kick")
        assert sounds(ev("build", 15, 16, "drop", kick_gap_before_drop=False), "kick")
        assert sounds(ev("build", 15, 16, "breakdown"), "kick")      # не перед дропом — бочка есть

    def test_no_roll_when_next_is_not_drop(self):
        e = ev("build", 15, 16, "breakdown")
        assert len(sounds(e, "snare")) == 2                          # только слой на 2 и 4

    def test_crash_on_drop_start_not_mid_phrase(self):
        assert sounds(ev("drop", 0), "crash") == [0]
        assert sounds(ev("drop", 5), "crash") == []

    def test_intro_hats_only_second_half(self):
        assert not sounds(ev("intro", 2, 16), "hat")
        assert sounds(ev("intro", 10, 16), "hat")


class TestHelpers:
    def test_resample_length(self):
        a = np.zeros((1000, 2), np.float32)
        assert len(cd.resample(a, 128 / 126)) == round(1000 * 128 / 126)

    def test_kick_score_prefers_low_short(self):
        sr = 44100
        t = np.arange(int(0.5 * sr)) / sr
        good = (np.sin(2 * np.pi * 55 * t) * np.exp(-t * 18))[:, None].repeat(2, 1)
        ring = (np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 3))[:, None].repeat(2, 1)
        assert cd.kick_score(good, sr) > cd.kick_score(ring, sr)

    def test_groove_differs_between_tracks(self):
        assert len({repr(cd.sample_groove(random.Random(s))) for s in range(8)}) > 4


def test_loops_never_lowpassed_or_rolls():
    if not cd.available():
        return
    for seed in range(40):
        lp = cd.pick_loops(random.Random(seed))
        for k in ("top_a", "top_b"):
            name = os.path.basename(lp[k])
            assert "LPF" not in name and "Roll" not in name and "Fx" not in name


def test_kick_score_penalizes_long_tail_and_rewards_punch():
    sr = 44100
    t = np.arange(int(0.5 * sr)) / sr
    punchy = (np.sin(2 * np.pi * 62 * t) * np.exp(-t * 14))[:, None].repeat(2, 1)
    t2 = np.arange(int(1.6 * sr)) / sr
    boomy = (np.sin(2 * np.pi * 62 * t2) * np.exp(-t2 * 14))[:, None].repeat(2, 1)
    assert cd.kick_score(punchy, sr) > cd.kick_score(boomy, sr)


def test_carve_bass_cuts_infra_keeps_bass():
    sr = 8000
    t = np.arange(sr * 2) / sr
    infra = np.sin(2 * np.pi * 20 * t)[:, None].repeat(2, 1).astype(np.float32)
    bass = np.sin(2 * np.pi * 90 * t)[:, None].repeat(2, 1).astype(np.float32)
    assert np.std(cd.carve_bass(infra, sr)[sr:]) < 0.25 * np.std(infra)
    assert np.std(cd.carve_bass(bass, sr)[sr:]) > 0.85 * np.std(bass)


def test_perc_only_when_enabled_and_in_groove_sections():
    on = cd.bar_events("drop", 2, 16, {**GR, "perc": True, "perc_pattern": [3, 7], "shaker16": True},
                       random.Random(1), None)
    assert sounds(on, "perc") == [3, 7] and len(sounds(on, "shaker")) == 16
    off = cd.bar_events("drop", 2, 16, {**GR, "perc": False}, random.Random(1), None)
    assert not sounds(off, "perc") and not sounds(off, "shaker")
    bd = cd.bar_events("breakdown", 2, 16, {**GR, "perc": True, "perc_pattern": [3], "shaker16": True},
                       random.Random(1), None)
    assert not sounds(bd, "perc")



def test_downbeat_halftime_snare_on_three_and_silent_breakdown_groove():
    g = {**GR, "pattern": "downbeat", "db_kick": 1}
    e = cd.bar_events("drop", 3, 16, g, random.Random(1), None)
    assert 8 in sounds(e, "snare") and 4 not in sounds(e, "snare") and 12 not in sounds(e, "snare")
    assert sounds(e, "kick") == [0, 7, 10]
    bd = cd.bar_events("breakdown", 3, 16, g, random.Random(1), None)
    assert not sounds(bd, "snare") and not sounds(bd, "hat")
    house = cd.bar_events("drop", 3, 16, GR, random.Random(1), None)
    assert sounds(house, "kick") == [0, 4, 8, 12]                 # хаус не затронут
