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
    def test_no_stems_runs_demucs_keeps(self, monkeypatch, tmp_path):
        monkeypatch.setenv("A1F_PYTHON", "/py")
        cmd = a1f.a1f_command("song.wav", "/out", demix_dir=str(tmp_path))
        assert cmd[:5] == ["/py", "-m", "allin1fix.cli", "song.wav", "-o"]
        assert "-k" in cmd and "--demix-dir" in cmd          # сохраняем стемы
        assert "--skip-separation" not in cmd                # стемов нет → demucs RUN
        assert "--overwrite" in cmd

    def test_stems_present_skips_separation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("A1F_PYTHON", "/py")
        st = tmp_path / "htdemucs" / "song"
        st.mkdir(parents=True)
        for s in ("bass", "drums", "other", "vocals"):
            (st / f"{s}.wav").write_text("")
        cmd = a1f.a1f_command("song.wav", "/out", demix_dir=str(tmp_path))
        assert "--skip-separation" in cmd                    # стемы есть → reuse

    def test_overwrite_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("A1F_PYTHON", "/py")
        assert "--overwrite" not in a1f.a1f_command("s.wav", "/o", demix_dir=str(tmp_path), overwrite=False)

    def test_stems_ready_detection(self, tmp_path):
        assert a1f.stems_ready("song.wav", str(tmp_path)) is False
        st = tmp_path / "htdemucs" / "song"; st.mkdir(parents=True)
        for s in ("bass", "drums", "other", "vocals"):
            (st / f"{s}.wav").write_text("")
        assert a1f.stems_ready("song.wav", str(tmp_path)) is True
