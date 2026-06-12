#!/usr/bin/env python3
"""
Generate madmom beat/downbeat annotations for WAV files.
These annotations are required by the mixer for bar-grid alignment.

Usage:
  python3 generate_annotations.py --wav-dir ./wav --ann-dir ./annotations

Dependencies:
  pip install madmom
"""
import os, sys, argparse, time
import numpy as np

def annotate(wav_dir, ann_dir):
    try:
        import madmom
    except ImportError:
        print("madmom not installed. Run: pip install madmom")
        sys.exit(1)

    os.makedirs(ann_dir, exist_ok=True)

    proc = madmom.features.downbeats.DBNDownBeatTrackingProcessor(
        beats_per_bar=[4], fps=100
    )
    act_proc = madmom.features.downbeats.RNNDownBeatProcessor()

    wav_files = sorted(f for f in os.listdir(wav_dir) if f.endswith('.wav'))
    print(f"Found {len(wav_files)} WAV files\n")

    for wf in wav_files:
        base = os.path.splitext(wf)[0]
        out_path = os.path.join(ann_dir, base + '.txt')
        if os.path.exists(out_path):
            print(f"  {wf}: already annotated, skipping")
            continue

        print(f"  {wf}...", end=" ", flush=True)
        t0 = time.time()
        wav_path = os.path.join(wav_dir, wf)
        activations = act_proc(wav_path)
        beats = proc(activations)
        np.savetxt(out_path, beats, fmt='%.4f\t%d')
        print(f"{len(beats)} beats in {time.time()-t0:.1f}s")

    print("\nDone")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate madmom annotations")
    parser.add_argument("--wav-dir", required=True)
    parser.add_argument("--ann-dir", required=True)
    args = parser.parse_args()
    annotate(args.wav_dir, args.ann_dir)
