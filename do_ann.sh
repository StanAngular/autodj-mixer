#!/usr/bin/env bash
set -euo pipefail
cd /opt/autodj-mixer
ANN_DIR="shared/ann"
mkdir -p "$ANN_DIR"
PY="/opt/autodj-mixer/.venv/bin/python3"

do_annotate() {
    local vid="$1"
    local wav="shared/tracks/$vid.wav"
    local out="$ANN_DIR/$vid.txt"
    if [ -f "$out" ]; then
        echo "SKIP $vid (exists)"
        return 0
    fi
    echo "ANN $vid..."
    PYTHONUNBUFFERED=1 $PY -u -c "
import numpy as np
np.float = np.float64; np.int = np.int64; np.complex = np.complex128; np.bool = np.bool_
import collections
from collections.abc import MutableSequence; collections.MutableSequence = MutableSequence
from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor
t0 = __import__('time').time()
act = RNNDownBeatProcessor()('$wav')
proc = DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)
beats = proc(act)
beats_samps = [(int(b[0]*44100), int(round(b[1]))) for b in beats if int(round(b[1])) in (1,2,3,4)]
np.savetxt('$out', beats_samps, fmt='%d %d')
print(f'  {vid}: {len(beats_samps)} beats, {sum(1 for _,bt in beats_samps if bt==1)} dbs, {__import__(\"time\").time()-t0:.1f}s')
" 2>&1
}

do_annotate cxxZ-E-KEYM
do_annotate iYqWdf4ii7E
do_annotate xpYbL1ArlqU
do_annotate PRLo6j65MPc
do_annotate X_K8DN3Usfs
do_annotate _nkPZA8_uwA

echo "=== ALL DONE ==="