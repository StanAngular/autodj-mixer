"""Тесты run_pipeline — пока точечно: команда A1F-предрасчёта (мастер-поток)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import run_pipeline as rp


class TestA1FPrecomputeCmd:
    def test_selective_auto_mode(self):
        cmd = rp.a1f_precompute_cmd("wavs", "anns", "a1f")
        assert "batch_a1f.py" in cmd and "wavs" in cmd and "a1f" in cmd
        assert "--mode" in cmd and cmd[cmd.index("--mode") + 1] == "auto"   # точечно
        assert "--ann-dir" in cmd and "anns" in cmd
    def test_demix_dir_optional(self):
        assert "--demix-dir" not in rp.a1f_precompute_cmd("w", "a", "f")
        cmd = rp.a1f_precompute_cmd("w", "a", "f", demix_dir="d")
        assert "--demix-dir" in cmd and "d" in cmd
    def test_timeout_passed(self):
        cmd = rp.a1f_precompute_cmd("w", "a", "f", timeout=300)
        assert "--timeout" in cmd and "300" in cmd
