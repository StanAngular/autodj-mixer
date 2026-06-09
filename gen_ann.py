#!/usr/bin/env python3
"""Generate madmom annotations for a WAV file. Run from .venv."""
import numpy as np
np.float = np.float64
np.int = np.int64
np.complex = np.complex128
np.bool = np.bool_

import sys, os
sys.path.insert(0, '/opt/autodj-mixer')

import librosa
from madmom.features.beats import DBNBeatTrackingProcessor, RNNBeatProcessor

SR = 44100
ANN_DIR = "/opt/autodj-mixer/shared/ann"
os.makedirs(ANN_DIR, exist_ok=True)

wav_path = sys.argv[1]
base = os.path.splitext(os.path.basename(wav_path))[0]
ann_path = os.path.join(ANN_DIR, base + '.txt')

print(f"  Detecting downbeats for {base}...")

# Load audio
audio, _ = librosa.load(wav_path, sr=SR, mono=True)

# Madmom beat tracking
proc = DBNBeatTrackingProcessor(fps=100)
rnn = RNNBeatProcessor()
act = rnn(audio)
beats = proc(act)
beats = beats[beats < len(audio) / SR - 0.1]

# Write annotation (beat number cycles 1,2,3,4)
with open(ann_path, 'w') as f:
    for j, bt in enumerate(beats):
        bj = (j % 4) + 1
        f.write(f"{bt:.6f} {bj}\n")

n_down = sum(1 for j in range(len(beats)) if j % 4 == 0)
print(f"  {n_down} downbeats → {ann_path}")