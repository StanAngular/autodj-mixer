"""Unit tests for cleanup_wavs.py pure core + dry-run safety (P29, offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cleanup_wavs as cw


class TestWavsSafeToDelete:
    def test_only_registered_deletable(self):
        deletable, unreg = cw.wavs_safe_to_delete(["aaa", "bbb", "ccc"], {"aaa", "ccc"})
        assert deletable == ["aaa", "ccc"]      # в каталоге
        assert unreg == ["bbb"]                 # НЕ удалять
    def test_none_in_catalog(self):
        deletable, unreg = cw.wavs_safe_to_delete(["x", "y"], set())
        assert deletable == [] and unreg == ["x", "y"]
    def test_empty(self):
        assert cw.wavs_safe_to_delete([], {"a"}) == ([], [])


class TestScanWavIds:
    def test_lists_ids(self, tmp_path):
        (tmp_path / "abcdefghijk.wav").write_bytes(b"x")
        (tmp_path / "lmnopqrstuv.wav").write_bytes(b"y")
        (tmp_path / "notes.txt").write_text("z")          # не .wav — игнор
        assert cw.scan_wav_ids(str(tmp_path)) == ["abcdefghijk", "lmnopqrstuv"]
    def test_missing_dir(self):
        assert cw.scan_wav_ids("/nope") == []


class TestCleanupDryRunSafety:
    def test_dry_run_does_not_delete(self, tmp_path, monkeypatch):
        tracks = tmp_path / "tracks"; tracks.mkdir()
        (tracks / "aaa.wav").write_bytes(b"x")
        (tracks / "bbb.wav").write_bytes(b"y")
        monkeypatch.setattr(cw, "catalog_ids", lambda d: {"aaa"})   # только aaa в каталоге
        res = cw.cleanup(str(tracks), "ignored", apply=False)
        assert res["deletable"] == ["aaa"] and res["unregistered"] == ["bbb"]
        assert res["applied"] is False
        assert (tracks / "aaa.wav").exists()        # dry-run НИЧЕГО не удалил
        assert (tracks / "bbb.wav").exists()

    def test_apply_deletes_only_registered(self, tmp_path, monkeypatch):
        tracks = tmp_path / "tracks"; tracks.mkdir()
        (tracks / "aaa.wav").write_bytes(b"x")
        (tracks / "bbb.wav").write_bytes(b"y")
        monkeypatch.setattr(cw, "catalog_ids", lambda d: {"aaa"})
        cw.cleanup(str(tracks), "ignored", apply=True)
        assert not (tracks / "aaa.wav").exists()    # зарегистрированный удалён
        assert (tracks / "bbb.wav").exists()        # незарегистрированный СОХРАНён
