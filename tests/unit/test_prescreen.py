"""Unit tests for prescreen.py pure cores (P26, offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import prescreen as ps


class TestFitCheck:
    def test_no_camelot_fails(self):
        ok, why = ps.fit_check({"camelot": "", "bpm": 124}, 118, 128)
        assert ok is False and "Camelot" in why
    def test_bpm_out_of_range_fails(self):
        ok, why = ps.fit_check({"camelot": "8A", "bpm": 150}, 118, 128)
        assert ok is False and "BPM" in why
    def test_fits(self):
        ok, why = ps.fit_check({"camelot": "8A", "bpm": 124}, 118, 128)
        assert ok is True and why == ""
    def test_unknown_bpm_with_camelot_passes(self):
        # Camelot есть, BPM неизвестен → проходит (BPM добьёт madmom на WAV)
        ok, _ = ps.fit_check({"camelot": "8A", "bpm": 0}, 118, 128)
        assert ok is True
    def test_tolerance(self):
        assert ps.fit_check({"camelot": "8A", "bpm": 129}, 118, 128, 2)[0] is True   # 128+2
        assert ps.fit_check({"camelot": "8A", "bpm": 131}, 118, 128, 2)[0] is False


class TestPartitionKeepers:
    def test_splits(self):
        cands = [
            {"artist": "A", "track": "1", "camelot": "8A", "bpm": 124},   # keep
            {"artist": "B", "track": "2", "camelot": "9A", "bpm": 150},   # reject bpm
            {"artist": "C", "track": "3", "camelot": "",   "bpm": 122},   # reject no key
        ]
        keepers, rejects = ps.partition_keepers(cands, 118, 128)
        assert len(keepers) == 1 and keepers[0]["artist"] == "A"
        assert len(rejects) == 2
        assert all("_reject" in r for r in rejects)


# ── P32: лимиты против слепого скачивания сотен ────────────────────────────

class TestCapProbe:
    def test_caps_to_max_probe(self):
        cands = [{"camelot": ""} for _ in range(50)]
        assert len(ps.cap_probe(cands, 10)) == 10        # не больше 10 на пробу
    def test_skips_those_with_camelot(self):
        cands = [{"camelot": "8A"}, {"camelot": ""}, {"camelot": "9A"}]
        assert ps.cap_probe(cands, None) == [{"camelot": ""}]   # только без Camelot
    def test_no_cap(self):
        assert len(ps.cap_probe([{"camelot": ""}]*5, 0)) == 5
