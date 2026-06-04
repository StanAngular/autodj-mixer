#!/usr/bin/env python3
"""
yt_download.py — download YouTube tracks, convert to WAV, detect downbeats.
Outputs a TRACKS snippet ready for mix_config.py.

Usage (single URL):
  python3 yt_download.py "https://youtube.com/watch?v=..."

Usage (multiple URLs):
  python3 yt_download.py \
    "https://youtube.com/watch?v=URL1" \
    "https://youtube.com/watch?v=URL2"

Usage (from file, one URL per line):
  python3 yt_download.py --url-file urls.txt

Output:
  - WAV files → /opt/autodj-mixer/tracks/
  - Annotations → /opt/autodj-mixer/ann/
  - Prints a TRACKS block for mix_config.py
"""

import os, sys, subprocess, argparse, time, shutil

# Shared paths (same as mix_config.py)
WAV_DIR = "/opt/autodj-mixer/tracks"
ANN_DIR = "/opt/autodj-mixer/ann"
YTDLP = shutil.which("yt-dlp") or os.path.expanduser("~/.local/bin/yt-dlp")
PROXY = "socks5://127.0.0.1:40000"
SR = 44100

os.makedirs(WAV_DIR, exist_ok=True)
os.makedirs(ANN_DIR, exist_ok=True)

def download(url, out_dir):
    """Download audio from YouTube URL as best-quality MP3."""
    # Get video ID from yt-dlp
    rid = subprocess.run(
        [YTDLP, "--proxy", PROXY, "--print", "id", url],
        capture_output=True, text=True, timeout=30
    )
    vid = rid.stdout.strip() if rid.returncode == 0 and rid.stdout.strip() else None
    if not vid:
        print(f"  ❌ Cannot extract video ID from {url}")
        return None

    cmd = [
        YTDLP, "--proxy", PROXY,
        "-x", "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", os.path.join(out_dir, f"{vid}.%(ext)s"),
        url
    ]
    print(f"  [{vid}] Downloading...", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"  ❌ yt-dlp failed:\n{r.stderr.strip()}")
        return None
    mp3 = os.path.join(out_dir, f"{vid}.mp3")
    if not os.path.exists(mp3):
        print(f"  ❌ MP3 not found: {mp3}")
        print(f"  stderr: {r.stderr.strip()}")
        return None
    print(f"  ✅ {vid}.mp3 ({os.path.getsize(mp3)/1e6:.1f} MB)")
    return mp3

def mp3_to_wav(mp3_path, wav_path):
    """Convert MP3 to WAV (44100, stereo, PCM_24)."""
    subprocess.run([
        "ffmpeg", "-y", "-i", mp3_path,
        "-ar", str(SR), "-ac", "2",
        "-sample_fmt", "s32", "-acodec", "pcm_s24le",
        wav_path
    ], capture_output=True, check=True)
    os.unlink(mp3_path)  # remove MP3 after conversion
    print(f"  WAV: {os.path.basename(wav_path)}")

def detect_downbeats(wav_path, ann_path):
    """Detect downbeats using madmom (with numpy compat fix)."""
    # Fix numpy 2.0 compat for madmom
    import numpy as np
    np.float = np.float64
    np.int = np.int64
    np.complex = np.complex128
    np.bool = np.bool_

    # Fix collections.abc compat for madmom
    import collections
    if not hasattr(collections, 'MutableSequence'):
        from collections.abc import MutableSequence
        collections.MutableSequence = MutableSequence

    from madmom.features.beats import DBNBeatTrackingProcessor, RNNBeatProcessor
    from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor

    print(f"  Detecting beats...", end=" ", flush=True)
    proc = DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)
    act = RNNDownBeatProcessor()(wav_path)
    beats = proc(act)

    # Save: time_in_seconds beat_type (1=downbeat)
    beats_samps = [(b[0], int(round(b[1]))) for b in beats if int(round(b[1])) in (1, 2, 3, 4)]
    np.savetxt(ann_path, beats_samps, fmt="%.6f %d")
    n_down = sum(1 for _, bt in beats_samps if bt == 1)
    print(f"{n_down} downbeats")


def main():
    p = argparse.ArgumentParser(description="Download YouTube tracks + detect downbeats")
    p.add_argument("urls", nargs="*", help="YouTube URLs")
    p.add_argument("--url-file", help="File with one URL per line")
    p.add_argument("--wav-dir", default=WAV_DIR)
    p.add_argument("--ann-dir", default=ANN_DIR)
    p.add_argument("--dry-run", action="store_true", help="Print URLs without downloading")
    p.add_argument("--config-out", metavar="FILE",
                   help="Write a TRACKS config file for smart_mixer.py")
    args = p.parse_args()

    urls = list(args.urls)
    if args.url_file:
        with open(args.url_file) as f:
            urls.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))

    if not urls:
        print("No URLs provided. Pass URLs as args or use --url-file.")
        sys.exit(1)

    if args.dry_run:
        for u in urls:
            print(u)
        return

    tracks = []
    for i, url in enumerate(urls):
        print(f"\n[{i+1}/{len(urls)}] {url}")
        mp3 = download(url, args.wav_dir)
        if mp3 is None:
            continue

        base = os.path.splitext(os.path.basename(mp3))[0]
        wav_path = os.path.join(args.wav_dir, f"{base}.wav")
        ann_path = os.path.join(args.ann_dir, f"{base}.txt")

        mp3_to_wav(mp3, wav_path)
        detect_downbeats(wav_path, ann_path)

        tracks.append((base, f"{base}.wav", f"{base}.txt"))

    print(f"\n{'='*60}")
    print(f"  Downloaded {len(tracks)}/{len(urls)} tracks")
    print(f"  WAV → {args.wav_dir}/")
    print(f"  ANN → {args.ann_dir}/")
    print(f"{'='*60}")
    print()
    print("TRACKS list (paste into mix_config.py):")
    print("TRACKS = [")
    for name, wav, ann in tracks:
        print(f"    (\"{name}\", \"{wav}\", \"{ann}\"),")
    print("]")
    print(f"\nQuick test: python3 smart_mixer.py --config mix_config.py --quick-test")

    # Write config file if requested
    if args.config_out:
        with open(args.config_out, "w") as f:
            f.write(f"# Auto-generated by yt_download.py\n")
            f.write(f"WAV_DIR = \"{args.wav_dir}\"\n")
            f.write(f"ANN_DIR = \"{args.ann_dir}\"\n")
            f.write("TRACKS = [\n")
            for name, wav, ann in tracks:
                f.write(f"    (\"{name}\", \"{wav}\", \"{ann}\"),\n")
            f.write("]\n")
        print(f"\n  Config saved → {args.config_out}")


if __name__ == "__main__":
    main()