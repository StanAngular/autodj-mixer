"""S1: сэмплер (реальные банки драм-машин). Офлайн — на синтетических wav."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import pytest
from autodj.generate import sampler as sp


@pytest.fixture
def fake_banks(tmp_path):
    """Мини-банк на диске: RolandTR808/{bd,sd}/*.wav"""
    import soundfile as sf
    root = tmp_path / "banks" / "RolandTR808"
    for inst, n in (("bd", 2), ("sd", 1)):
        d = root / inst
        d.mkdir(parents=True)
        for i in range(n):
            sig = np.ones((1000, 2), dtype="float32") * (0.5 if inst == "bd" else 0.25)
            sf.write(str(d / f"{inst}{i}.wav"), sig, 44100)
    return str(tmp_path / "banks")


class TestBankLookup:
    def test_finds_bank_case_insensitive(self, fake_banks):
        assert sp.find_bank("rolandtr808", fake_banks) is not None
        assert sp.find_bank("Roland-TR808", fake_banks) is not None
    def test_missing_bank_helpful_error(self, tmp_path):
        with pytest.raises(FileNotFoundError) as e:
            sp.SampleBank("NoSuchBank", banks_dir=str(tmp_path))
        assert "tidal-drum-machines" in str(e.value)        # подсказка как поставить
    def test_variants_round_robin(self, fake_banks):
        bank = sp.SampleBank("RolandTR808", banks_dir=fake_banks)
        assert len(bank.get("bd")) == 2 and len(bank.get("sd")) == 1
        k, b = bank.get("kick"), bank.get("bd")
        assert len(k) == len(b) and np.array_equal(k[0], b[0])   # псевдоним Strudel


class TestShapeSample:
    def test_begin_end_trims(self):
        x = np.ones((1000, 2), dtype="float32")
        assert len(sp.shape_sample(x, begin=0.1, end=0.3)) == 200
    def test_speed_changes_length(self):
        x = np.ones((1000, 2), dtype="float32")
        assert abs(len(sp.shape_sample(x, speed=0.5)) - 2000) <= 2
    def test_gain_and_pan(self):
        x = np.ones((100, 2), dtype="float32")
        assert sp.shape_sample(x, gain=0.5)[0, 0] == pytest.approx(0.5)
        left = sp.shape_sample(x, pan=-1.0)
        assert left[0, 0] > left[0, 1]                      # панорама влево


class TestRenderPattern:
    def test_pattern_places_hits(self, fake_banks):
        bank = sp.SampleBank("RolandTR808", banks_dir=fake_banks)
        out = sp.render_pattern(bank, "bd ~ sd ~", cycles=2, cycle_sec=2.0, sr=44100)
        assert out.shape[1] == 2 and len(out) > 4 * 44100
        assert np.abs(out[:100]).max() > 0                  # удар в 0.0s
        assert np.abs(out[44100:44200]).max() > 0           # sd в 1.0s
        assert np.abs(out[22050:22150]).max() == 0          # пауза в 0.5s
    def test_unknown_name_silent(self, fake_banks):
        bank = sp.SampleBank("RolandTR808", banks_dir=fake_banks)
        out = sp.render_pattern(bank, "zzz zzz", cycles=1, cycle_sec=1.0)
        assert np.abs(out).max() == 0                       # нет сэмпла — тишина, не падение
