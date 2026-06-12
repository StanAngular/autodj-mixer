#!/usr/bin/env python3
"""Re-annotate tracks that have sample-based annotations instead of time-based."""
import os, time
import numpy as np
np.float = np.float64; np.int = np.int64; np.complex = np.complex128; np.bool = np.bool_
import collections
from collections.abc import MutableSequence; collections.MutableSequence = MutableSequence
from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor

ANN = "/opt/autodj-mixer/shared/ann"
TRACKS = "/opt/autodj-mixer/shared/tracks"
SR = 44100

sample_based = []
for f in sorted(os.listdir(ANN)):
    if not f.endswith(".txt"):
        continue
    fp = os.path.join(ANN, f)
    with open(fp) as fh:
        first = fh.readline().strip()
    if first:
        # Sample-based format = no decimal point in first column (integers like 441, 882)
        has_decimal = '.' in first.split()[0]
        if not has_decimal:
            sample_based.append(f[:-4])

print(f"Re-annotating {len(sample_based)} files with sample-based format...", flush=True)

proc = DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)

for i, base in enumerate(sample_based):
    wav = os.path.join(TRACKS, f"{base}.wav")
    out = os.path.join(ANN, f"{base}.txt")
    if not os.path.exists(wav):
        print(f"  SKIP {base} (no WAV)", flush=True)
        continue
    t0 = time.time()
    act = RNNDownBeatProcessor()(wav)
    beats = proc(act)
    # Save as: time_in_seconds beat_number (matches load_dbeats which does r[0]*sr)
    rows = [[b[0], int(round(b[1]))] for b in beats if int(round(b[1])) in (1,2,3,4)]
    np.savetxt(out, rows, fmt="%.6f %d")
    n_down = sum(1 for _, bt in rows if bt == 1)
    print(f"  [{i+1}/{len(sample_based)}] {base}: {n_down} dbs ({time.time()-t0:.1f}s)", flush=True)

print(f"Done: {len(sample_based)} re-annotated", flush=True)