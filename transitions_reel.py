#!/usr/bin/env python3
"""
transitions_reel.py — extract crossfade zones and stitch into a short review reel.

Usage:
    python3 transitions_reel.py MIX.wav [--pad-before 15] [--pad-after 15] [--gap 2] [--out reel.mp3]

For each transition in MIX.wav.npy stamps, extracts PAD_BEFORE + CF_DURATION + PAD_AFTER,
labels with a 0.5s tone (440Hz = A4) between clips, and stitches into one MP3.

This lets you review ALL transition points in ~2-3 minutes instead of full mix.
"""

import argparse
import json
import os
import sys
import numpy as np
import soundfile as sf
import subprocess

SR = 44100

def make_tone(freq=440.0, dur=0.25, sr=SR, amp=0.05):
    """Short sine tone as separator between clips."""
    t = np.linspace(0, dur, int(dur * sr), endpoint=False)
    wave = (amp * np.sin(2 * np.pi * freq * t)).astype("float32")
    # Fade in/out 20ms to avoid clicks
    fade = int(0.020 * sr)
    wave[:fade] *= np.linspace(0, 1, fade)
    wave[-fade:] *= np.linspace(1, 0, fade)
    stereo = np.stack([wave, wave], axis=1)
    return stereo


def make_silence(dur, sr=SR):
    return np.zeros((int(dur * sr), 2), dtype="float32")


def load_stamps(mix_path):
    """Load stamps from MIX.wav.npy (saved by smart_mixer)."""
    stamps_path = mix_path + ".npy"
    if not os.path.exists(stamps_path):
        print(f"ERROR: stamps not found at {stamps_path}", file=sys.stderr)
        sys.exit(1)
    data = np.load(stamps_path, allow_pickle=True)
    # numpy saves list of dicts as 0-d object array
    if data.ndim == 0:
        stamps = data.item()
    else:
        stamps = list(data)
    if isinstance(stamps, dict):
        stamps = stamps.get('stamps', [])
    return stamps


def main():
    p = argparse.ArgumentParser(description="Build transitions review reel")
    p.add_argument("mix", help="Mix WAV file")
    p.add_argument("--pad-before", type=float, default=15.0, help="Seconds before crossfade (default 15)")
    p.add_argument("--pad-after", type=float, default=15.0, help="Seconds after crossfade end (default 15)")
    p.add_argument("--gap", type=float, default=1.5, help="Silence gap between clips (default 1.5)")
    p.add_argument("--out", default="", help="Output path (default: next to mix as _reel.mp3)")
    args = p.parse_args()

    mix_path = args.mix
    if not os.path.exists(mix_path):
        print(f"ERROR: mix file not found: {mix_path}", file=sys.stderr)
        sys.exit(1)

    out_path = args.out or mix_path.replace(".wav", "_reel.mp3")
    reel_wav = out_path.replace(".mp3", ".wav")

    print(f"Loading mix: {mix_path}")
    mix, sr = sf.read(mix_path, dtype="float32", always_2d=True)
    mix_dur = len(mix) / sr
    print(f"  Duration: {mix_dur/60:.1f} min  SR={sr}")

    stamps = load_stamps(mix_path)
    print(f"  Found {len(stamps)} transition stamps")

    if not stamps:
        print("No stamps found. Exiting.")
        sys.exit(1)

    clips = []
    # Intro silence
    clips.append(make_silence(0.5))

    sep_tone = make_tone(freq=880.0, dur=0.3)   # short beep between clips
    header_tone = make_tone(freq=440.0, dur=0.5) # longer beep before each transition

    for i, stamp in enumerate(stamps):
        t_cf = stamp.get('t', 0.0)           # crossfade start in mix
        cf_dur = stamp.get('dur', 0.0)       # crossfade duration
        from_name = stamp.get('from', '?')
        to_name = stamp.get('to', '?')

        t_start = max(0.0, t_cf - args.pad_before)
        t_end = min(mix_dur, t_cf + cf_dur + args.pad_after)

        s = int(t_start * sr)
        e = int(t_end * sr)
        clip = mix[s:e].copy()

        # Fade in/out edges of clip (50ms)
        fade = min(int(0.050 * sr), len(clip) // 4)
        clip[:fade] *= np.linspace(0, 1, fade)[:, None]
        clip[-fade:] *= np.linspace(1, 0, fade)[:, None]

        label = f"[{i+1}] {from_name} → {to_name}  @{t_cf/60:.1f}m"
        print(f"  Clip {i+1}: {label}  ({(e-s)/sr:.1f}s extracted)")

        clips.append(header_tone)
        clips.append(make_silence(0.3))
        clips.append(clip)
        clips.append(make_silence(args.gap))

    reel = np.concatenate(clips)
    reel_dur = len(reel) / sr
    print(f"\nReel duration: {reel_dur:.1f}s ({reel_dur/60:.1f} min)")

    # Write WAV
    sf.write(reel_wav, reel, sr)
    print(f"WAV: {reel_wav}")

    # Encode to MP3
    cmd = ["ffmpeg", "-y", "-i", reel_wav, "-b:a", "320k", out_path]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0:
        size_mb = os.path.getsize(out_path) / 1e6
        print(f"MP3: {out_path}  ({size_mb:.1f} MB)")
        os.remove(reel_wav)
    else:
        print(f"FFmpeg error: {result.stderr.decode()[-200:]}")
        out_path = reel_wav

    print(f"\nDone: {out_path}")
    return out_path


if __name__ == "__main__":
    main()
