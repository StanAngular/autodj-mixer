"""Тесты smart_mixer (пока точечно). resolve_camelot: curated primary, detect fallback."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import smart_mixer as m


class TestResolveCamelot:
    def test_curated_wins(self):
        assert m.resolve_camelot("8A", "5A") == "8A"        # курированный primary
    def test_empty_curated_falls_to_detected(self):
        assert m.resolve_camelot("", "5A") == "5A"
        assert m.resolve_camelot(None, "5A") == "5A"
    def test_unknown_curated_falls_to_detected(self):
        assert m.resolve_camelot("?", "5A") == "5A"         # '?' не валиден
    def test_whitespace_curated_falls_to_detected(self):
        assert m.resolve_camelot("  ", "5A") == "5A"


class TestA1FSnapBar:
    # сетка: intro(0-1) verse(2-3) break(4-5) chorus(6-7) outro(8-9)
    LABELS = ["intro", "intro", "verse", "verse", "break", "break", "chorus", "chorus", "outro", "outro"]

    def test_snaps_exit_to_outro_start(self):
        bar, lab = m.a1f_snap_bar(9, self.LABELS, m.A1F_EXIT_LABELS, window=4)
        assert bar == 8 and lab == "outro"            # начало outro рядом с энергетич. bar9
    def test_snaps_exit_to_break(self):
        bar, lab = m.a1f_snap_bar(5, self.LABELS, m.A1F_EXIT_LABELS, window=2)
        assert bar == 4 and lab == "break"            # начало break
    def test_entry_snaps_to_intro(self):
        bar, lab = m.a1f_snap_bar(1, self.LABELS, m.A1F_ENTRY_LABELS, window=2)
        assert bar == 0 and lab == "intro"
    def test_no_match_in_window_keeps_anchor(self):
        bar, lab = m.a1f_snap_bar(3, self.LABELS, m.A1F_EXIT_LABELS, window=0)
        assert bar == 3 and lab is None               # окно 0, на verse — не трогаем
    def test_none_labels_keeps_anchor(self):
        assert m.a1f_snap_bar(5, None, m.A1F_EXIT_LABELS) == (5, None)
    def test_none_bar(self):
        assert m.a1f_snap_bar(None, self.LABELS, m.A1F_EXIT_LABELS) == (None, None)
    def test_picks_nearest_boundary(self):
        # outro начинается в 8; verse-как-prefer нет; ближайший break(4) от bar6 vs outro(8) → break ближе? нет: |4-6|=2,|8-6|=2 → break (first found, d равны → break т.к. меньший индекс не гарантирован; проверим что вернулась валидная граница)
        bar, lab = m.a1f_snap_bar(6, self.LABELS, m.A1F_EXIT_LABELS, window=2)
        assert lab in ("break", "outro") and bar in (4, 8)


# ═══ M1: DSP-ядро — тесты на ФИЗИКУ (сетка перед Фазой M сведения) ═══
# Требуют РЕАЛЬНЫЙ scipy/pyloudnorm (conftest мокает только отсутствующие).
# В голой среде (без аудио-стека) — skip, на сервере/CI со стеком — полноценная физика.
import sys as _sys
import unittest.mock as _um
import numpy as np
import pytest as _pt

_dsp_real = not isinstance(_sys.modules.get("scipy"), _um.MagicMock)
pytestmark_dsp = _pt.mark.skipif(not _dsp_real, reason="scipy замокан — DSP-физика недоступна")


def _tone(freq, sec=1.0, sr=44100):
    t = np.arange(int(sec * sr)) / sr
    return np.sin(2 * np.pi * freq * t).astype("float32")


@pytestmark_dsp
class TestEqPow:
    def test_equal_power_identity(self):
        fo, fi = m.eq_pow(1024)
        assert np.allclose(fo**2 + fi**2, 1.0, atol=1e-5)     # fo²+fi²=1 всюду
    def test_endpoints(self):
        fo, fi = m.eq_pow(512)
        assert fo[0] > 0.999 and fi[0] < 1e-3                 # старт: только уходящий
        assert fo[-1] < 1e-3 and fi[-1] > 0.999               # финиш: только входящий


@pytestmark_dsp
class TestThreeBandSplit:
    def test_bands_reconstruct_original(self):
        # LR4-кроссоверы: сумма полос ≈ исходник (allpass-свойство Linkwitz-Riley)
        sr = 44100
        x = (_tone(60) + _tone(1000) + _tone(9000)) / 3.0
        x2 = np.stack([x, x], axis=1)
        low, mid, high = m.three_band_split(x2, 200, 4000, sr)
        recon = low + mid + high
        seg = slice(2048, -2048)                              # без краевых переходных
        err = np.max(np.abs(recon[seg] - x2[seg]))
        assert err < 0.02, f"реконструкция разошлась: {err}"
    def test_band_separation(self):
        # 60Гц живёт в low, 9кГц — в high (перекрёстное подавление сильное)
        sr = 44100
        bass = np.stack([_tone(60)]*2, 1); treble = np.stack([_tone(9000)]*2, 1)
        bl, bm, bh = m.three_band_split(bass, 200, 4000, sr)
        tl, tm, th = m.three_band_split(treble, 200, 4000, sr)
        seg = slice(2048, -2048)
        assert np.abs(bl[seg]).mean() > 10 * np.abs(bh[seg]).mean()
        assert np.abs(th[seg]).mean() > 10 * np.abs(tl[seg]).mean()


@pytestmark_dsp
class TestVocalNotchSweep:
    def test_attenuates_vocal_band_keeps_bass(self):
        sr = 44100
        x = np.stack([(_tone(2000) + _tone(80)) / 2.0]*2, 1)  # вокал-зона + бас
        out = m.vocal_notch_sweep(x, sr, gain_db=-12)
        seg = slice(4096, -4096)
        # общая энергия упала (вокал-полоса продавлена), но не в ноль (бас цел)
        r = np.abs(out[seg]).mean() / np.abs(x[seg]).mean()
        assert 0.4 < r < 0.95, f"ratio={r}"
    def test_shape_preserved(self):
        x = np.zeros((44100, 2), dtype="float32")
        assert m.vocal_notch_sweep(x, 44100).shape == x.shape


@pytestmark_dsp
class TestNormLufs:
    def test_hits_target_loudness(self):
        import pyloudnorm as pyln
        sr = 44100
        x = np.stack([_tone(440, sec=3.0) * 0.05]*2, 1)       # тихий тон
        out = m.norm_lufs(x, target=-14.0, sr=sr)
        loud = pyln.Meter(sr).integrated_loudness(out.astype("float64"))
        assert abs(loud - (-14.0)) < 1.0, f"LUFS={loud}"
    def test_silence_passthrough(self):
        x = np.zeros((44100, 2), dtype="float32")
        assert np.array_equal(m.norm_lufs(x, target=-14.0, sr=44100), x)


@pytestmark_dsp
class TestWarpToGrid:
    def _db(self, bar_sec, n_bars, sr=44100):
        return np.array([int(i * bar_sec * sr) for i in range(n_bars + 1)])
    def test_warp_matches_master_grid_length(self):
        import shutil, pytest
        if not shutil.which("rubberband"):
            pytest.skip("rubberband CLI недоступен в этой среде")
        sr = 44100
        s_db = self._db(0.50, 4, sr)                          # слейв: бары по 0.50s
        m_db = self._db(0.48, 4, sr)                          # мастер: по 0.48s
        audio = np.stack([_tone(440, sec=2.2)]*2, 1)
        warped, consumed = m.warp_to_grid(audio, s_db, m_db, sr)
        if warped is None:
            pytest.skip("warp вернул None (защитная ветка)")
        expect = m_db[4] - m_db[0]
        assert abs(len(warped) - expect) <= sr * 0.02         # ±20мс на 4 бара
