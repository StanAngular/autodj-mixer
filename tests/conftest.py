"""
Shared pytest fixtures for autodj-mixer tests.
"""
import os
import sys
from unittest.mock import MagicMock
import numpy as np
import pytest

# Mock heavy audio deps so unit tests run without a full audio stack
_HEAVY = [
    "soundfile", "pyrubberband", "librosa", "pyloudnorm",
    "scipy", "scipy.signal", "madmom",
    "madmom.features", "madmom.features.downbeats",
    "madmom.audio", "madmom.audio.signal",
]
for _m in _HEAVY:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR = 44100


# ── Synthetic audio helpers ────────────────────────────────────────────────

def make_kick(duration_s=0.05, sr=SR):
    """Short sine burst to simulate a kick transient."""
    t = np.linspace(0, duration_s, int(duration_s * sr), endpoint=False)
    env = np.exp(-t * 80)
    return (np.sin(2 * np.pi * 60 * t) * env * 0.8).astype(np.float32)


def make_track_wav(bpm=120.0, duration_s=15.0, sr=SR):
    """
    Generate a stereo synthetic track:
    - Background sine tone
    - Kick on every downbeat (bar start)
    """
    n = int(duration_s * sr)
    mono = np.zeros(n, dtype=np.float32)

    # Background tone (500 Hz)
    t = np.linspace(0, duration_s, n, endpoint=False)
    mono += np.sin(2 * np.pi * 500 * t).astype(np.float32) * 0.1

    # Kick on each downbeat
    bar_samples = int(240.0 / bpm * sr)  # samples per bar (4 beats)
    kick = make_kick(sr=sr)
    pos = 0
    while pos < n:
        end = min(pos + len(kick), n)
        mono[pos:end] += kick[:end - pos]
        pos += bar_samples

    # Stereo
    stereo = np.stack([mono, mono], axis=1)
    return stereo


def make_annotation(bpm=120.0, duration_s=15.0, sr=SR):
    """
    Return annotation rows [[time, beat_pos], ...] for a synthetic track.
    beat_pos cycles 1,2,3,4.
    """
    bar_s = 240.0 / bpm
    beat_s = bar_s / 4
    rows = []
    t = 0.0
    beat_pos = 1
    while t < duration_s:
        rows.append([t, beat_pos])
        t += beat_s
        beat_pos = (beat_pos % 4) + 1
    return np.array(rows)


# ── Pytest fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_wav_dir(tmp_path):
    """Directory with two synthetic WAV files at 120 BPM."""
    import scipy.io.wavfile as wav_io
    bpms = [120.0, 124.0]
    names = ["track_a", "track_b"]
    for name, bpm in zip(names, bpms):
        stereo = make_track_wav(bpm=bpm, duration_s=15.0)
        wav_io.write(str(tmp_path / f"{name}.wav"),
                     SR, (stereo * 32767).astype(np.int16))
    return tmp_path


@pytest.fixture
def tmp_ann_dir(tmp_path):
    """Directory with two annotation files matching tmp_wav_dir tracks."""
    bpms = [120.0, 124.0]
    names = ["track_a", "track_b"]
    for name, bpm in zip(names, bpms):
        rows = make_annotation(bpm=bpm, duration_s=15.0)
        np.savetxt(str(tmp_path / f"{name}.txt"), rows, fmt="%.6f")
    return tmp_path


@pytest.fixture
def downbeats_120bpm():
    """Downbeat positions (sample indices) for a 120 BPM track.

    Variant A: db holds ONE downbeat per bar (as load_dbeats produces).
    At 120 BPM a bar = 4 beats = 2.0s, so downbeats are 2.0s apart.
    """
    bar_samples = int(240.0 / 120.0 * SR)  # 2.0s × 44100 = 88200
    return np.array([i * bar_samples for i in range(33)], dtype=int)  # ~32 bars


@pytest.fixture
def clean_analysis():
    """Minimal analysis dict representing a problem-free mix."""
    return {
        "source_info": {
            "track_a": {"key": "C maj", "bpm": 120.0, "dur_sec": 300.0,
                        "key_confidence": 0.9},
            "track_b": {"key": "G maj", "bpm": 122.0, "dur_sec": 300.0,
                        "key_confidence": 0.85},
        },
        "transitions": [
            {
                "master_name": "track_a",
                "slave_name": "track_b",
                "t": 280.0,
                "lufs_jump_db": 1.5,
                "reported_shift_ms": 3.0,
            }
        ],
        "mix_artefacts": [],
        "source_issues": [],
        "mixer_issues": [],
        "feedback": [],
    }
