"""M3 stem_mixer: тональная математика, гейт совместимости, сборка. Офлайн (numpy);
align_vocal — skip без rubberband CLI."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import pytest
import stem_mixer as sm


class TestCamelotShift:
    def test_neighbors_need_no_shift(self):
        # соседи по колесу совместимы КАК ЕСТЬ — суть Camelot
        assert sm.camelot_shift_semitones("8A", "9A") == 0
        assert sm.camelot_shift_semitones("12A", "1A") == 0      # круг замыкается
        assert sm.camelot_shift_semitones("8A", "8B") == 0       # относительный мажор
    def test_distant_pair_minimal_shift(self):
        assert sm.camelot_shift_semitones("5A", "9A") == -1      # −1 st → 10A, сосед 9A
        assert sm.camelot_shift_semitones("3B", "9B") == -1      # тритон решается одним st
    def test_unknown_camelot_none(self):
        assert sm.camelot_shift_semitones("", "9A") is None
        assert sm.camelot_shift_semitones("8A", "banana") is None
        assert sm.camelot_shift_semitones("13A", "9A") is None


class TestGate:
    def test_ok_pair(self):
        ok, why = sm.mashup_gate(0, 1.03)
        assert ok and "ok" in why
    def test_shift_too_far(self):
        ok, why = sm.mashup_gate(5, 1.0)
        assert not ok and "полутон" in why
    def test_stretch_too_far(self):
        ok, why = sm.mashup_gate(0, 1.33)
        assert not ok and "растяжка" in why
    def test_unknown_meta(self):
        assert not sm.mashup_gate(None, 1.0)[0]
        assert not sm.mashup_gate(0, None)[0]


class TestStretchRatio:
    def test_ratio(self):
        assert abs(sm.stretch_ratio(120, 124) - 124 / 120) < 1e-9
    def test_missing_bpm_none(self):
        assert sm.stretch_ratio(0, 124) is None


class TestBuildMashup:
    def test_vocal_enters_at_offset_and_limited(self):
        sr, bpm = 44100, 120
        bar = int(round(60 / bpm * 4 * sr))
        inst = np.ones((bar * 4, 2), dtype="float32") * 0.5
        vocal = np.ones((bar, 2), dtype="float32") * 0.9
        out = sm.build_mashup(inst, vocal, sr, offset_bars=2, inst_bpm=bpm, vocal_gain_db=0.0)
        assert len(out) == len(inst)
        assert np.allclose(out[: bar * 2 - 1], out[0])            # до входа — чистый инструментал
        assert out[bar * 2 + 10, 0] > out[0, 0]                   # после — вокал добавился
        assert float(np.max(np.abs(out))) <= 0.99 + 1e-4          # лимитер держит пик
    def test_vocal_longer_than_inst_clipped(self):
        sr = 44100
        inst = np.zeros((sr, 2), dtype="float32")
        vocal = np.ones((sr * 3, 2), dtype="float32")
        out = sm.build_mashup(inst, vocal, sr, offset_bars=0, inst_bpm=120)
        assert len(out) == sr                                     # не разрастается


class TestAlignVocal:
    def test_stretch_and_shift_change_length_and_pitch(self):
        import shutil, pytest
        if not shutil.which("rubberband"):
            pytest.skip("rubberband CLI недоступен")
        sr = 44100
        t = np.arange(sr) / sr
        x = np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1).astype("float32")
        out = sm.align_vocal(x, sr, shift=2, rate=1.05)
        assert abs(len(out) - int(sr / 1.05)) < sr * 0.02         # длина по rate
