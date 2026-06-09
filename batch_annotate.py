#!/usr/bin/env python3
"""Batch annotate all WAVs in shared/tracks/ with madmom downbeats."""
import os, sys, subprocess, time

TRACKS = "/opt/autodj-mixer/shared/tracks"
ANN = "/opt/autodj-mixer/shared/ann"
os.makedirs(ANN, exist_ok=True)

wavs = sorted([f for f in os.listdir(TRACKS) if f.endswith(".wav")])
wavs = [f for f in wavs if not os.path.exists(
    os.path.join(ANN, os.path.splitext(f)[0] + ".txt")
)]

print(f"Annotating {len(wavs)} tracks...")

for i, wav in enumerate(wavs):
    base = os.path.splitext(wav)[0]
    wav_path = os.path.join(TRACKS, wav)
    ann_path = os.path.join(ANN, f"{base}.txt")
    
    print(f"  [{i+1}/{len(wavs)}] {base}...", end=" ", flush=True)
    t0 = time.time()
    
    code = f'''
import numpy as np
np.float = np.float64; np.int = np.int64; np.complex = np.complex128; np.bool = np.bool_
import collections
from collections.abc import MutableSequence; collections.MutableSequence = MutableSequence
from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor
proc = DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)
act = RNNDownBeatProcessor()("{wav_path}")
beats = proc(act)
SR = 44100
beats_samps = [(int(b[0]*SR), int(round(b[1]))) for b in beats if int(round(b[1])) in (1,2,3,4)]
np.savetxt("{ann_path}", beats_samps, fmt="%d %d")
n_down = sum(1 for _,bt in beats_samps if bt==1)
print(n_down, "downbeats")
'''
    r = subprocess.run([
        "/opt/autodj-mixer/.venv/bin/python3", "-c", code
    ], capture_output=True, text=True, timeout=120)
    
    if r.returncode == 0:
        print(f"{r.stdout.strip()} ({time.time()-t0:.1f}s)")
    else:
        print(f"FAIL: {r.stderr.strip()[:100]}")

print(f"\nDone. ANN dir: {len(os.listdir(ANN))} files")