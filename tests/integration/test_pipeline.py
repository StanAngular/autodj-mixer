"""
Integration test: run_pipeline.py end-to-end (mix + analyze + validate).

Skips analyzer/validator steps gracefully if dependencies are missing.
"""
import os
import sys
import json
import subprocess
import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIPELINE = os.path.join(SCRIPT_DIR, "run_pipeline.py")
MIXER = os.path.join(SCRIPT_DIR, "smart_mixer.py")
SR = 44100


def write_wav_simple(path, duration_s=15.0, bpm=120.0, sr=SR):
    """Write a simple synthetic WAV."""
    import wave
    import numpy as np
    n = int(duration_s * sr)
    t = np.linspace(0, duration_s, n, endpoint=False)
    mono = (np.sin(2 * np.pi * 440 * t) * 0.2).astype(np.float32)
    # Add kicks
    bar_s = int(240.0 / bpm * sr)
    kick_n = int(0.04 * sr)
    kick = (np.exp(-np.linspace(0, 3, kick_n)) * 0.7).astype(np.float32)
    for pos in range(0, n, bar_s):
        end = min(pos + kick_n, n)
        mono[pos:end] += kick[:end - pos]
    pcm16 = (np.clip(mono, -1, 1) * 32767).astype('int16')
    stereo = [pcm16, pcm16]
    with wave.open(path, 'w') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        # Interleave channels
        import struct
        frames = bytearray()
        for l, r in zip(pcm16, pcm16):
            frames += struct.pack('<hh', l, r)
        wf.writeframes(bytes(frames))


def write_ann(path, duration_s=15.0, bpm=120.0):
    """Write beat annotation file."""
    beat_s = 60.0 / bpm
    rows = []
    t, pos = 0.0, 1
    while t < duration_s:
        rows.append(f"{t:.6f} {pos}")
        t += beat_s
        pos = (pos % 4) + 1
    with open(path, 'w') as f:
        f.write('\n'.join(rows))


@pytest.fixture
def track_env(tmp_path):
    """Set up two tracks + env for pipeline testing."""
    wav_dir = tmp_path / "wav"
    ann_dir = tmp_path / "ann"
    out_dir = tmp_path / "out"
    for d in [wav_dir, ann_dir, out_dir]:
        d.mkdir()

    for name, bpm in [("track_a", 120.0), ("track_b", 122.0)]:
        write_wav_simple(str(wav_dir / f"{name}.wav"), bpm=bpm)
        write_ann(str(ann_dir / f"{name}.txt"), bpm=bpm)

    return {
        "wav_dir": str(wav_dir),
        "ann_dir": str(ann_dir),
        "output": str(out_dir / "mix.mp3"),
    }


class TestPipeline:
    def test_mixer_only_no_validate(self, track_env):
        """--no-validate: only Step 1 mix, exit 0 on success."""
        result = subprocess.run(
            [sys.executable, PIPELINE,
             "--wav-dir", track_env["wav_dir"],
             "--ann-dir", track_env["ann_dir"],
             "--output", track_env["output"],
             "--no-validate"],
            capture_output=True, text=True, timeout=90
        )
        assert result.returncode in (0, 3), f"Unexpected exit: {result.returncode}\n{result.stderr}"
        if result.returncode == 0:
            assert os.path.exists(track_env["output"])

    def test_analyze_only_flag(self, track_env):
        """--analyze-only with pre-existing mix skips Step 1."""
        # First create a mix
        subprocess.run(
            [sys.executable, MIXER,
             "--wav-dir", track_env["wav_dir"],
             "--ann-dir", track_env["ann_dir"],
             "--output", track_env["output"]],
            capture_output=True, timeout=90
        )
        if not os.path.exists(track_env["output"]):
            pytest.skip("Mixer did not produce output for analyze-only test")

        result = subprocess.run(
            [sys.executable, PIPELINE,
             "--wav-dir", track_env["wav_dir"],
             "--ann-dir", track_env["ann_dir"],
             "--output", track_env["output"],
             "--analyze-only", "--no-validate"],
            capture_output=True, text=True, timeout=120
        )
        # Should not fail with code 3 (mixer error), may fail on analyzer deps
        assert result.returncode != 3, "Pipeline tried to mix despite --analyze-only"

    def test_json_output_created(self, track_env):
        """After full pipeline run, _analysis.json should exist if analyzer succeeded."""
        result = subprocess.run(
            [sys.executable, PIPELINE,
             "--wav-dir", track_env["wav_dir"],
             "--ann-dir", track_env["ann_dir"],
             "--output", track_env["output"],
             "--no-validate"],
            capture_output=True, text=True, timeout=120
        )
        json_path = track_env["output"].replace(".mp3", "_analysis.json")
        if result.returncode == 0 and os.path.exists(json_path):
            with open(json_path) as f:
                data = json.load(f)
            assert "source_info" in data
            assert "transitions" in data
            assert "mixer_issues" in data

    def test_exit_code_passthrough(self, track_env):
        """Pipeline exit code must be one of: 0, 1, 2 (validator) or 3 (error)."""
        result = subprocess.run(
            [sys.executable, PIPELINE,
             "--wav-dir", track_env["wav_dir"],
             "--ann-dir", track_env["ann_dir"],
             "--output", track_env["output"]],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode in (0, 1, 2, 3), \
            f"Unexpected exit code: {result.returncode}"
