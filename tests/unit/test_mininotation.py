"""S2: мини-нотация (Strudel/Tidal-подмножество). Офлайн, чистые функции."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from autodj.generate.mininotation import parse_pattern, struct_events, pattern_to_times


class TestBasics:
    def test_even_spacing(self):
        ev = parse_pattern("bd sd bd sd")
        assert [e["value"] for e in ev] == ["bd", "sd", "bd", "sd"]
        assert [round(e["start"], 3) for e in ev] == [0.0, 0.25, 0.5, 0.75]
    def test_rests(self):
        ev = parse_pattern("bd ~ sd -")
        assert [e["value"] for e in ev] == ["bd", "sd"]
        assert round(ev[1]["start"], 3) == 0.5
    def test_empty(self):
        assert parse_pattern("") == []


class TestOperators:
    def test_multiply_subdivides(self):
        ev = parse_pattern("bd*2 sd")
        assert [e["value"] for e in ev] == ["bd", "bd", "sd"]
        assert round(ev[1]["start"], 3) == 0.25            # два бд в первом слоте
        assert round(ev[0]["dur"], 3) == 0.25
    def test_repeat_takes_slots(self):
        ev = parse_pattern("bd!3 sd")
        assert len(ev) == 4 and [e["value"] for e in ev] == ["bd", "bd", "bd", "sd"]
        assert round(ev[3]["start"], 3) == 0.75
    def test_subgroup(self):
        ev = parse_pattern("[bd sd] hh")
        assert [e["value"] for e in ev] == ["bd", "sd", "hh"]
        assert round(ev[1]["start"], 3) == 0.25            # внутри первой половины
        assert round(ev[2]["start"], 3) == 0.5


class TestCycleVariation:
    def test_alternation_changes_per_cycle(self):
        c0 = parse_pattern("<bd sd> hh", cycle=0)
        c1 = parse_pattern("<bd sd> hh", cycle=1)
        c2 = parse_pattern("<bd sd> hh", cycle=2)
        assert c0[0]["value"] == "bd" and c1[0]["value"] == "sd" and c2[0]["value"] == "bd"
    def test_probability_deterministic_but_varies(self):
        a = [len(parse_pattern("bd? sd? hh? cp?", cycle=c, seed=7)) for c in range(8)]
        assert len(set(a)) > 1                              # по циклам по-разному
        b = [len(parse_pattern("bd? sd? hh? cp?", cycle=c, seed=7)) for c in range(8)]
        assert a == b                                       # но воспроизводимо


class TestStructAndTimes:
    def test_struct_positions(self):
        pos = struct_events("x - - x - - x -")
        assert len(pos) == 3 and round(pos[0], 3) == 0.0 and round(pos[1], 3) == 0.375
    def test_unroll_cycles_seconds(self):
        ev = pattern_to_times("bd sd", cycles=2, cycle_sec=2.0)
        assert [round(t, 2) for t, _, _ in ev] == [0.0, 1.0, 2.0, 3.0]
    def test_variation_across_unrolled_cycles(self):
        ev = pattern_to_times("<bd sd> hh", cycles=2, cycle_sec=1.0)
        vals = [v for _, v, _ in ev]
        assert vals[0] == "bd" and vals[2] == "sd"          # цикл 2 звучит иначе
