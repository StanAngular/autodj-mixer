#!/usr/bin/env python3
"""
vocal_robotize.py — Split vocals/instrumental, robotize vocals, recombine.
Purpose: bypass Suno/YouTube speech-based copyright detection.

Підхід:
  1. Інструментал = bass + drums + other (demucs стеми без змін)
  2. Вокал = vocal стем → ring modulation + pitch shift → ASR не розпізнає слова
  3. Результат = інструментал + роботизований вокал → 1 файл

Usage:
  python3 vocal_robotize.py \
    --stems-dir shared/rework/demix_hq/htdemucs/mozgoviy_original \
    --out shared/rework/mozgoviy_robot_bypass.mp3 \
    [--carrier-hz 40] \
    [--pitch-st 3.0] \
    [--vocal-db -3]
"""

import argparse
import subprocess
import tempfile
import os
import sys


def ffmpeg(*args, label=""):
    cmd = ["ffmpeg", "-y"] + list(args)
    if label:
        print(f"  ffmpeg: {label}")
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode()[-3000:], file=sys.stderr)
        sys.exit(1)


def mix_instrumental(stems_dir, out_path):
    """Mix bass + drums + other into one WAV (vocals excluded)."""
    inputs = []
    for stem in ["bass", "drums", "other"]:
        p = os.path.join(stems_dir, f"{stem}.wav")
        if not os.path.exists(p):
            print(f"ERROR: stem not found: {p}", file=sys.stderr)
            sys.exit(1)
        inputs += ["-i", p]

    fc = "[0:a][1:a][2:a]amix=inputs=3:normalize=0[out]"
    ffmpeg(*inputs,
           "-filter_complex", fc,
           "-map", "[out]",
           "-c:a", "pcm_s24le",
           out_path,
           label="mix bass+drums+other")


def robotize_vocals(vocals_path, out_path, carrier_hz=40.0, pitch_st=3.0):
    """
    Robotize vocal stem to defeat ASR and speech fingerprinting.

    Chain:
      1. rubberband pitch shift — moves frequency peaks, breaks pitch-hash match
         formant=preserved → voice sounds robotic (formants stay, pitch moves)
      2. aeval ring modulation — multiplies signal by carrier sine wave
         → classic robot buzz, destroys formant clarity → ASR fails
      3. aecho — smears transients, masks phoneme boundaries
      4. loudnorm — consistent level
    """
    pitch_ratio = 2 ** (pitch_st / 12)

    filters = []

    # 1. Pitch shift with formant preservation (sounds robotic AND defeats matching)
    if abs(pitch_st) > 0.05:
        filters.append(
            f"rubberband=pitch={pitch_ratio:.6f}:pitchq=quality:formant=preserved"
        )

    # 2. Ring modulation — key step for defeating ASR
    #    carrier 40Hz: low enough to be felt as buzz, high enough to scramble formants
    filters.append(f"aeval=val(0)*sin(2*PI*{carrier_hz:.1f}*t):c=same")

    # 3. Light reverb — smears phoneme boundaries
    filters.append("aecho=0.6:0.7:40:0.25")

    # 4. Normalize output level
    filters.append("loudnorm=I=-18:TP=-2:LRA=9")

    ffmpeg("-i", vocals_path,
           "-af", ",".join(filters),
           "-c:a", "pcm_s24le",
           out_path,
           label=f"robotize vocals (carrier={carrier_hz}Hz, pitch=+{pitch_st}st)")


def combine(inst_path, vocal_path, out_path, inst_db=0.0, vocal_db=-3.0):
    """Mix instrumental + robotized vocals → final MP3."""
    vol_inst = 10 ** (inst_db / 20)
    vol_vox  = 10 ** (vocal_db / 20)

    fc = (
        f"[0:a]volume={vol_inst:.4f}[a];"
        f"[1:a]volume={vol_vox:.4f}[b];"
        "[a][b]amix=inputs=2:normalize=0,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
        "[out]"
    )

    ffmpeg("-i", inst_path, "-i", vocal_path,
           "-filter_complex", fc,
           "-map", "[out]",
           "-c:a", "libmp3lame", "-b:a", "320k",
           out_path,
           label="combine → MP3")


def main():
    ap = argparse.ArgumentParser(
        description="Robotize vocals and recombine with instrumental for Suno bypass"
    )
    ap.add_argument("--stems-dir", required=True,
                    help="Dir with bass.wav drums.wav other.wav vocals.wav")
    ap.add_argument("--out", required=True,
                    help="Output MP3 path")
    ap.add_argument("--carrier-hz", type=float, default=40.0,
                    help="Ring modulation carrier frequency (Hz). Default: 40")
    ap.add_argument("--pitch-st", type=float, default=3.0,
                    help="Pitch shift semitones (positive = up). Default: 3.0")
    ap.add_argument("--vocal-db", type=float, default=-3.0,
                    help="Vocal level in final mix (dB). Default: -3")
    ap.add_argument("--inst-db", type=float, default=0.0,
                    help="Instrumental level in final mix (dB). Default: 0")
    args = ap.parse_args()

    stems_dir   = args.stems_dir
    vocals_path = os.path.join(stems_dir, "vocals.wav")

    if not os.path.exists(vocals_path):
        print(f"ERROR: vocals.wav not found in {stems_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Stems: {stems_dir}")
    print(f"Output: {args.out}")
    print(f"Settings: carrier={args.carrier_hz}Hz | pitch=+{args.pitch_st}st | "
          f"vocal={args.vocal_db}dB | inst={args.inst_db}dB")
    print()

    with tempfile.TemporaryDirectory() as tmp:
        inst_path  = os.path.join(tmp, "instrumental.wav")
        robot_path = os.path.join(tmp, "vocals_robot.wav")

        print("1/3 Міксую інструментал (bass+drums+other)...")
        mix_instrumental(stems_dir, inst_path)

        print("2/3 Роботизую вокал...")
        robotize_vocals(
            vocals_path, robot_path,
            carrier_hz=args.carrier_hz,
            pitch_st=args.pitch_st,
        )

        print("3/3 Зводжу фінальний файл...")
        combine(inst_path, robot_path, args.out,
                inst_db=args.inst_db,
                vocal_db=args.vocal_db)

    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"\nГотово: {args.out} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
