"""P53: батч-раннер A1F — резюм/скип, чтобы микс не падал по таймауту."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import a1f, batch_a1f


class TestA1FCommand:
    def test_fast_has_skip_separation(self):
        cmd = a1f.a1f_command("/x/t.wav", "/out", fast=True)
        assert "--skip-separation" in cmd and "/x/t.wav" in cmd and "/out" in cmd
    def test_full_no_skip(self):
        assert "--skip-separation" not in a1f.a1f_command("/x/t.wav", "/out", fast=False)


class TestResume:
    def test_pending_skips_done(self):
        with tempfile.TemporaryDirectory() as wd, tempfile.TemporaryDirectory() as ad:
            for n in ["a.wav", "b.wav", "c.wav"]:
                open(os.path.join(wd, n), "w").close()
            open(os.path.join(ad, "b.json"), "w").close()      # b уже посчитан
            assert batch_a1f.pending(wd, ad) == ["a.wav", "c.wav"]
    def test_all_done_empty(self):
        with tempfile.TemporaryDirectory() as wd, tempfile.TemporaryDirectory() as ad:
            open(os.path.join(wd, "a.wav"), "w").close()
            open(os.path.join(ad, "a.json"), "w").close()
            assert batch_a1f.pending(wd, ad) == []


class TestDownbeatCV:
    def _ann(self, downbeat_positions):
        import tempfile, numpy as np
        rows = [[p, 1] for p in downbeat_positions]            # beat==1 = даунбит
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        np.savetxt(f.name, rows, fmt="%d %d"); return f.name
    def test_regular_low_cv(self):
        import os
        p = self._ann([0, 44100, 88200, 132300, 176400])       # ровные интервалы
        cv = batch_a1f.downbeat_cv(p); os.unlink(p)
        assert cv is not None and cv < 0.05
    def test_irregular_high_cv(self):
        import os
        p = self._ann([0, 44100, 200000, 230000, 500000])      # рваные
        cv = batch_a1f.downbeat_cv(p); os.unlink(p)
        assert cv is not None and cv > 0.10
    def test_too_few_none(self):
        import os
        p = self._ann([0, 44100]); cv = batch_a1f.downbeat_cv(p); os.unlink(p)
        assert cv is None


class TestRecommendTrackA1F:
    def test_short_track_recommended(self, monkeypatch):
        monkeypatch.setattr(batch_a1f, "track_duration", lambda p: 180.0)   # 3 мин
        rec, why = batch_a1f.recommend_track_a1f("/x/t.wav")
        assert rec and "короткий" in why
    def test_regular_long_not_recommended(self, monkeypatch):
        monkeypatch.setattr(batch_a1f, "track_duration", lambda p: 420.0)   # 7 мин
        rec, why = batch_a1f.recommend_track_a1f("/x/t.wav", ann_path=None)
        assert not rec and "madmom достаточно" in why
