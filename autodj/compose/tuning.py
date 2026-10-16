"""Tuning: measure where a sound source really sounds versus the MIDI note it was asked for.
Found 2026-10-17: Vital «Psychill Bass Clean» sounds an octave AND a semitone below the written note (plus ~2 c),
so in «Тепло рук» v1/v2 the bass played a minor second against every chord. That is what Стас heard as layers
that «не попадают гармонично» (Gemini missed it). Every preset is now measured once and corrected by MIDI transpose."""
import json, os
import numpy as np

def pitch_offset(y, midi, sr=44100, start=.12, dur=1.0):
    """semitones (float) between the sounding pitch and `midi`, from a wide-range pyin (catches octave+semitone shifts)"""
    import librosa
    y = y.mean(1) if y.ndim == 2 else y; y = y[int(start * sr):int((start + dur) * sr)]
    if len(y) < sr // 4 or np.abs(y).max() < 1e-5: return None
    y22 = librosa.resample(y, orig_sr=sr, target_sr=22050)
    f, v, _ = librosa.pyin(y22, fmin=25, fmax=2000, sr=22050, frame_length=4096)
    f = f[v] if np.any(v) else f[~np.isnan(f)]
    if not len(f): return None
    return float(12 * np.log2(np.median(f) / (440 * 2 ** ((midi - 69) / 12))))

def split(off):
    """-> (transpose semitones to apply to MIDI so the pitch class is right, residual cents); octave shifts are kept"""
    if off is None: return 0, 0.0
    semis = round(off); pc_fix = -((semis + 6) % 12 - 6)          # undo the non-octave part only
    return int(pc_fix), round((off - semis) * 100, 1)

def cents_off(y, midi, sr=44100, start=.15, dur=1.0):
    """fine deviation (cents) of harmonics 1-3 near the expected pitch (use after the pitch class is known to be right)"""
    y = y.mean(1) if y.ndim == 2 else y; y = y[int(start * sr):int((start + dur) * sr)]
    if len(y) < sr // 4 or np.abs(y).max() < 1e-5: return 0.0
    n = len(y) * 8; X = np.abs(np.fft.rfft(y * np.hanning(len(y)), n)); fr = np.fft.rfftfreq(n, 1 / sr); out = []
    f0 = 440 * 2 ** ((midi - 69) / 12)
    for h in (1, 2, 3):
        m = (fr > f0 * h * 2 ** (-.6 / 12)) & (fr < f0 * h * 2 ** (.6 / 12))
        if m.any(): i = np.where(m)[0][np.argmax(X[m])]; out.append(1200 * np.log2(fr[i] / (f0 * h)))
    return float(np.median(out)) if out else 0.0

class Cache:
    def __init__(self, path):
        self.path = path; self.d = json.load(open(path)) if os.path.exists(path) else {}
    def get(self, key, measure):
        if key not in self.d:
            self.d[key] = measure()
            try: json.dump(self.d, open(self.path, "w"), indent=0)
            except OSError: pass
        return self.d[key]
