"""Unit tests for a1f.py config module (offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import a1f


class TestA1fPython:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("A1F_PYTHON", "/custom/py")
        assert a1f.a1f_python() == "/custom/py"

    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("A1F_PYTHON", raising=False)
        p = a1f.a1f_python()
        assert p.endswith("all-in-one-fix/venv/bin/python")
        assert "~" not in p                      # expanduser применён


class TestA1fCommand:
    def test_fast_has_skip_separation(self, monkeypatch):
        monkeypatch.setenv("A1F_PYTHON", "/py")
        cmd = a1f.a1f_command("song.wav", "/out", fast=True)
        assert cmd[:5] == ["/py", "-m", "allin1fix.cli", "song.wav", "-o"]
        assert "--skip-separation" in cmd
        assert "--overwrite" in cmd

    def test_full_no_skip_separation(self, monkeypatch):
        monkeypatch.setenv("A1F_PYTHON", "/py")
        cmd = a1f.a1f_command("song.wav", "/out", fast=False)
        assert "--skip-separation" not in cmd     # полный Demucs

    def test_no_overwrite(self, monkeypatch):
        monkeypatch.setenv("A1F_PYTHON", "/py")
        assert "--overwrite" not in a1f.a1f_command("s.wav", "/o", overwrite=False)
