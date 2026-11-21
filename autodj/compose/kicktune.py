"""P153 (2026-11-21, Slate Harbor): the kick must sit in the key. The tonal layers of that track alone were E minor (key fit 0.93), a kick whose body
sounded C# dragged the whole mix to 0.42 (musicality FAIL) and cost three extra renders. soundgate.measure() cannot judge a kick (its pitch sweep
reads as «wobble»), so the pitch used here is the chroma peak of the first 0.5 s of the hit.

  kick_pc(path)                     the pitch class (0 = C) the kick's body sounds on
  offset(pc, tonic)                 smallest shift in semitones that puts pc on the tonic or the fifth (-6..+6)
  kick_in_key(cands, tonic, rng)    the least used of the candidates whose shift is <= max_shift -> (path, shift); registers the shift
  retune(x, st)                     resample a hit by st semitones (shorter and higher when st > 0)
  TUNED                             {path: shift} of the kicks that were retuned: ears.kick_tuning reads it, so a retuned kick is not reported
Typical use:  kick, st = kicktune.kick_in_key(CI.candidates("deep round kick", 16, role="kick", max_dur=.9), "E", rng, title);  K = retune(load_sample(kick, .32), st)"""
import numpy as np

TUNED = {}                                                    # path -> semitones the score retuned the kick by
def _pc(tonic):
    from .chords import pc_of
    return pc_of(tonic)

def kick_pc(path):
    """pitch class of the body of the kick: chroma peak of its first 0.5 s (None when the file is silent)"""
    import librosa
    y, sr = librosa.load(path, sr=22050, duration=.5)
    if not len(y) or float(np.abs(y).max()) < 1e-4: return None
    ch = librosa.feature.chroma_cqt(y=y, sr=sr, fmin=librosa.note_to_hz("C1"), n_octaves=6).mean(1); return int(np.argmax(ch))

def offset(pc, tonic):
    """smallest shift (semitones, -6..+6) that moves pitch class `pc` onto the tonic or its fifth"""
    t = _pc(tonic); return float(min(((((w - pc) + 6) % 12) - 6 for w in (t, (t + 7) % 12)), key=abs))

def kick_in_key(cands, tonic, rng=None, title=None, max_shift=3.0, db=None):
    """the least used (fresh.pick) of the candidate kicks that need at most max_shift semitones to sit on the tonic or the fifth -> (path, shift);
    the shift is registered in TUNED. ValueError when no candidate qualifies."""
    from . import fresh
    ok = {}
    for p in cands:
        pc = kick_pc(p)
        if pc is None: continue
        d = offset(pc, tonic)
        if abs(d) <= max_shift: ok[p] = d
    if not ok: raise ValueError(f"kicktune.kick_in_key: none of {len(cands)} kicks is within {max_shift} st of {tonic} or its fifth")
    p = fresh.pick(list(ok), rng, title=title, db=db); TUNED[p] = ok[p]; return p, ok[p]

def retune(x, st):
    """resample a hit (n, ch) or (n,) by st semitones; |st| < .05 returns it unchanged"""
    if abs(st) < .05: return x
    from scipy.signal import resample
    return resample(x, max(8, int(round(len(x) / 2 ** (st / 12)))), axis=0).astype(np.float32)

def report(sources, tonic, tuned=None, max_off=1.5):
    """[(kick file, off semitones)] for the kicks among `sources` (file names or paths) whose body is more than max_off from the tonic and the fifth and that the score did not retune"""
    import os
    from . import fresh
    tuned = TUNED if tuned is None else tuned; out = []
    for s in sources or []:
        name = os.path.basename(str(s)); path = s if os.path.isabs(str(s)) else fresh.PATHS.get(name)           # the ledger keeps file names; fresh.PATHS the full paths of this render
        if fresh.drum_class(name) != "kick" or not path or not os.path.exists(path) or path in tuned: continue
        pc = kick_pc(path)
        if pc is None: continue
        d = offset(pc, tonic)
        if abs(d) > max_off: out.append((name, d))
    return out
