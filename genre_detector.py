#!/usr/bin/env python3
"""
Genre detector for autodj-mixer.
Reads WAV files + annotations, determines genre, loads genre profile.

Usage:
    python3 genre_detector.py --wav-dir ./tracks --ann-dir ./ann
    python3 genre_detector.py --config mix_config.py
    python3 genre_detector.py --config mix_config.py --json   # machine-readable

Returns genre name + recommended mix params from genres/ profile.
"""

import os, sys, json, argparse
import numpy as np

GENRES_DIR = os.path.join(os.path.dirname(__file__), "genres")

# BPM-based genre map (min, max) -> genre
BPM_MAP = [
    (0,   45,  "ambient"),
    (45,  95,  "jazz_downtempo"),
    (95,  118, "house"),
    (118, 135, "afro_house"),
    (135, 148, "trance"),
    (148, 200, "hard_techno"),
]

# Spectral fingerprints (from genre analysis)
# distortion_ratio: high = techno/industrial, low = jazz/afro
SPECTRAL_HINTS = {
    "jazz_downtempo": {"distortion": (0.0, 0.15), "sub_ratio": (0.1, 0.4)},
    "afro_house":     {"distortion": (0.05, 0.25), "sub_ratio": (0.2, 0.5)},
    "hard_techno":    {"distortion": (0.2, 1.0),   "sub_ratio": (0.3, 0.7)},
}


def load_bpms(wav_dir, ann_dir):
    """Load BPMs from annotation files. Auto-detects samples vs seconds format."""
    SR = 44100
    bpms = []
    for f in sorted(os.listdir(ann_dir)):
        if not f.endswith(".txt"):
            continue
        ann_path = os.path.join(ann_dir, f)
        try:
            beats = np.loadtxt(ann_path)
            if beats.ndim < 2 or len(beats) < 4:
                continue
            # Auto-detect: samples (> 1000) or seconds (< 1000)
            first = beats[0, 0]
            is_samples = first > 1000
            times = beats[:, 0] / SR if is_samples else beats[:, 0]
            # Get downbeats only (beat position == 1)
            downbeats = times[beats[:, 1] == 1]
            if len(downbeats) < 4:
                # fallback: use all beats
                intervals = np.diff(times)
            else:
                intervals = np.diff(downbeats) / 4  # bar -> beat
            intervals = intervals[(intervals > 0.2) & (intervals < 2.0)]
            if len(intervals) > 0:
                bpm = 60.0 / np.median(intervals)
                bpms.append(bpm)
        except Exception:
            pass
    return bpms


def bpm_to_genre(median_bpm):
    """Map median BPM to genre."""
    for lo, hi, genre in BPM_MAP:
        if lo <= median_bpm < hi:
            return genre
    return "unknown"


def spectral_hint(wav_dir, sample_track=None):
    """
    Quick spectral analysis of one track to distinguish
    hard_techno vs afro_house (overlapping BPM range: 118-165).
    Returns distortion_ratio.
    """
    try:
        import soundfile as sf
        from scipy import signal as scipy_signal

        if sample_track is None:
            wavs = [f for f in os.listdir(wav_dir) if f.endswith(".wav")]
            if not wavs:
                return None
            sample_track = os.path.join(wav_dir, sorted(wavs)[0])

        audio, sr = sf.read(sample_track, frames=sr_frames(sr=44100, seconds=30),
                             always_2d=True)
        mono = audio.mean(axis=1)

        # High-frequency content ratio (distortion indicator)
        freqs, psd = scipy_signal.welch(mono, sr, nperseg=2048)
        lo = np.mean(psd[(freqs >= 20) & (freqs < 200)])
        hi = np.mean(psd[(freqs >= 4000) & (freqs < 16000)])
        distortion_ratio = hi / (lo + 1e-12)
        return float(distortion_ratio)
    except Exception:
        return None


def sr_frames(sr=44100, seconds=30):
    return sr * seconds


def load_genre_profile(genre_name):
    """Load genre .md profile and extract recommended params."""
    profile_path = os.path.join(GENRES_DIR, f"{genre_name}.md")
    if not os.path.exists(profile_path):
        return None, None

    with open(profile_path) as f:
        content = f.read()

    # Extract python code block with params
    params = {}
    in_block = False
    for line in content.splitlines():
        if "```python" in line:
            in_block = True
            continue
        if in_block and "```" in line:
            break
        if in_block and "=" in line and not line.strip().startswith("#"):
            try:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.split("#")[0].strip().strip('"')
                if key in ("CF_BARS", "RAMP_SEC", "TAIL_FADE_BARS"):
                    params[key] = int(val)
                elif key in ("TARGET_LUFS", "MAX_SHIFT_SEC"):
                    params[key] = float(val)
                elif key == "MODE":
                    params[key] = val.strip('"').strip("'")
                elif key == "USE_QUIET_EXIT":
                    params[key] = val == "True"
            except Exception:
                pass

    return content, params


def detect(wav_dir, ann_dir, verbose=True):
    """
    Main detection function.
    Returns (genre_name, params_dict, profile_text).
    """
    bpms = load_bpms(wav_dir, ann_dir)
    if not bpms:
        if verbose:
            print("  [genre] No BPM data -- defaulting to hard_techno")
        return "hard_techno", {}, None

    median_bpm = float(np.median(bpms))
    bpm_spread = float(np.max(bpms) - np.min(bpms))
    genre = bpm_to_genre(median_bpm)

    # Disambiguate afro_house vs hard_techno by spectral content
    if genre in ("afro_house", "hard_techno"):
        dist = spectral_hint(wav_dir)
        if dist is not None:
            if dist > 0.3:
                genre = "hard_techno"
            else:
                genre = "afro_house"
            if verbose:
                print(f"  [genre] Spectral distortion ratio: {dist:.3f} -> {genre}")

    profile_text, params = load_genre_profile(genre)
    if profile_text is None:
        if verbose:
            print(f"  [genre] No profile for '{genre}', using defaults")
        params = {}

    if verbose:
        print(f"  [genre] BPMs: {[f'{b:.0f}' for b in bpms]}")
        print(f"  [genre] Median BPM: {median_bpm:.1f}  spread: {bpm_spread:.1f}")
        print(f"  [genre] Detected: {genre.upper()}")
        if params:
            print(f"  [genre] Params: CF_BARS={params.get('CF_BARS','?')} "
                  f"MODE={params.get('MODE','?')} "
                  f"RAMP_SEC={params.get('RAMP_SEC','?')}")

    return genre, params, profile_text


def main():
    parser = argparse.ArgumentParser(description="Genre detector for autodj-mixer")
    parser.add_argument("--wav-dir", default="./tracks")
    parser.add_argument("--ann-dir", default="./ann")
    parser.add_argument("--config", help="mix_config.py path (overrides wav/ann dirs)")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    args = parser.parse_args()

    wav_dir, ann_dir = args.wav_dir, args.ann_dir
    if args.config:
        cfg = {}
        exec(open(args.config).read(), cfg)
        wav_dir = cfg.get("WAV_DIR", wav_dir)
        ann_dir = cfg.get("ANN_DIR", ann_dir)

    genre, params, profile = detect(wav_dir, ann_dir, verbose=not args.json)

    if args.json:
        print(json.dumps({"genre": genre, "params": params}, indent=2))
    elif profile:
        print(f"\n--- Profile excerpt (genres/{genre}.md) ---")
        # Print just first 15 lines
        for line in profile.splitlines()[:15]:
            print(line)
        print("...")


if __name__ == "__main__":
    main()
