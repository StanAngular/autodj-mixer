#!/usr/bin/env python3
"""Batch madmom annotation for all WAVs missing .txt annotations."""
import os, sys, time
import numpy as np
np.float = np.float64; np.int = np.int64; np.complex = np.complex128; np.bool = np.bool_
import collections
from collections.abc import MutableSequence; collections.MutableSequence = MutableSequence
from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor

TRACKS = "/opt/autodj-mixer/shared/tracks"
ANN = "/opt/autodj-mixer/shared/ann"
os.makedirs(ANN, exist_ok=True)

wavs = sorted([f for f in os.listdir(TRACKS) if f.endswith(".wav")])
wavs = [f for f in wavs if not os.path.exists(os.path.join(ANN, os.path.splitext(f)[0] + ".txt"))]

print(f"Annotating {len(wavs)} tracks...", flush=True)
SR = 44100

for i, wav in enumerate(wavs):
    base = os.path.splitext(wav)[0]
    wav_path = os.path.join(TRACKS, wav)
    ann_path = os.path.join(ANN, f"{base}.txt")
    
    t0 = time.time()
    proc = DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)
    act = RNNDownBeatProcessor()(wav_path)
    beats = proc(act)
    beats_samps = [(int(b[0]*SR), int(round(b[1]))) for b in beats if int(round(b[1])) in (1,2,3,4)]
    np.savetxt(ann_path, beats_samps, fmt="%d %d")
    n_down = sum(1 for _,bt in beats_samps if bt==1)
    print(f"  [{i+1}/{len(wavs)}] {base}: {n_down} downbeats ({time.time()-t0:.1f}s)", flush=True)

print(f"\nDone. ANN dir: {len(os.listdir(ANN))} files", flush=True)