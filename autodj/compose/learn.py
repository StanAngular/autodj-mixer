"""Learn from a reference track (stems from demucs htdemucs: drums/bass/other/vocals).
python3 -m autodj.compose.learn STEMS_DIR NAME [BPM]  ->  $AUTODJ_ASSETS/grooves/refs/NAME.json
Extracted: grid phase from the kick, micro-timing + accent + occupancy per 16th step for kick / hats (>5 kHz) /
perc (1-5 kHz), the bass line (pitch classes, rhythm occupancy, note lengths), stem levels relative to the drums
(role norms for this style) and stereo width. Each reference adds a style the engine can use (Groove.from_ref)."""
import json, os, sys
import numpy as np, soundfile as sf, librosa
from scipy.signal import butter, sosfiltfilt
from .assets import ASSETS

def _mono(path, sr=22050):
    x, s = sf.read(path, dtype="float32"); m = x.mean(1) if x.ndim == 2 else x
    return librosa.resample(m, orig_sr=s, target_sr=sr), (x if x.ndim == 2 else None), s

def _band(y, lo, hi, sr):
    if lo and hi: return sosfiltfilt(butter(4, [lo, hi], "band", fs=sr, output="sos"), y)
    return sosfiltfilt(butter(4, lo or hi, "high" if lo else "low", fs=sr, output="sos"), y)

def _onsets(y, sr):
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=128)
    on = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=128, units="time", backtrack=False)
    st = env[np.clip((on * sr / 128).astype(int), 0, len(env) - 1)]
    return on, st / (np.percentile(st, 95) + 1e-9)

def learn(stems, name, bpm=None, sr=22050):
    d, _, _ = _mono(os.path.join(stems, "drums.wav"), sr); b, _, _ = _mono(os.path.join(stems, "bass.wav"), sr)
    o, _, _ = _mono(os.path.join(stems, "other.wav"), sr); v, _, _ = _mono(os.path.join(stems, "vocals.wav"), sr)
    if not bpm: bpm = float(np.atleast_1d(librosa.beat.beat_track(y=d, sr=sr)[0])[0])
    s16 = 15 / bpm
    kb = _band(d, None, 150, sr); kenv = librosa.onset.onset_strength(y=kb, sr=sr, hop_length=128)
    _, beats = librosa.beat.beat_track(onset_envelope=kenv, sr=sr, hop_length=128, start_bpm=bpm, tightness=800, units="time")
    beats = np.asarray(beats); bi = np.arange(len(beats))
    to16 = lambda tt: np.interp(tt, beats, bi, left=np.nan, right=np.nan) * 4          # follows tempo drift beat by beat
    prof = {"name": name, "bpm": round(float(60 / np.median(np.diff(beats))), 2), "beats": len(beats), "classes": {}}
    for cls, (lo, hi) in {"kick": (None, 150), "hh": (5000, None), "perc": (1000, 5000)}.items():
        on, st = _onsets(_band(d, lo, hi, sr), sr); pos = to16(on); keep = ~np.isnan(pos); on, st, pos = on[keep], st[keep], pos[keep]
        step = np.round(pos).astype(int); off = pos - step
        bars = max(1, int(step.max() // 16) + 1) if len(step) else 1; tpl = {}
        for s in range(16):
            m = (step % 16 == s) & (np.abs(off) < .45)
            if m.sum() >= 3: tpl[str(s)] = [round(float(np.median(off[m])), 3), round(float(np.std(off[m])), 3), round(float(np.median(st[m])), 3), round(float(m.sum() / bars), 3)]
        prof["classes"][cls] = tpl
    # bass line: pitch per 16th step
    f0, vo, _ = librosa.pyin(b, fmin=30, fmax=300, sr=sr, frame_length=4096, hop_length=256)
    t = librosa.times_like(f0, sr=sr, hop_length=256); ok = vo & ~np.isnan(f0)
    midi = np.round(librosa.hz_to_midi(f0[ok])).astype(int); pcs = np.bincount(midi % 12, minlength=12)
    b_on, b_st = _onsets(_band(b, None, 400, sr), sr); bp = to16(b_on); b_on = b_on[~np.isnan(bp)]; bstep = np.round(bp[~np.isnan(bp)]).astype(int)
    bars = max(1, int(bstep.max() // 16) + 1) if len(bstep) else 1
    prof["bass"] = {"pitch_classes": {librosa.midi_to_note(60 + i, octave=False): round(float(c / pcs.sum()), 3) for i, c in enumerate(pcs) if c / pcs.sum() > .03},
                    "median_midi": int(np.median(midi)) if len(midi) else None,
                    "occupancy": {str(s): round(float(((bstep % 16) == s).sum() / bars), 3) for s in range(16)},
                    "median_note_s": round(float(np.median(np.diff(b_on))) if len(b_on) > 2 else 0, 3)}
    lvl = lambda y: round(float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12)), 1)
    ref = lvl(_band(d, None, 150, sr))
    prof["levels_vs_kick_db"] = {"drums_all": round(lvl(d) - ref, 1), "hats": round(lvl(_band(d, 5000, None, sr)) - ref, 1), "perc": round(lvl(_band(d, 1000, 5000, sr)) - ref, 1),
                                 "bass": round(lvl(b) - ref, 1), "other": round(lvl(o) - ref, 1), "vocals": round(lvl(v) - ref, 1)}
    seg = int(30 * sr); prof["other_vocals_timeline_db"] = [[round(i / sr / 60, 1), lvl(o[i:i + seg]), lvl(v[i:i + seg])] for i in range(0, len(o) - seg, seg)]
    out = os.path.join(ASSETS, "grooves", "refs"); os.makedirs(out, exist_ok=True)
    json.dump(prof, open(os.path.join(out, f"{name}.json"), "w"), ensure_ascii=False, indent=1); return prof

if __name__ == "__main__":
    p = learn(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else None)
    print(json.dumps(p, ensure_ascii=False)[:3000])
