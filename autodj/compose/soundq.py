"""P120: judge a sound BEFORE it goes into a track (Стас 2026-10-28: «нужно оценивать семплы перед применением; если нет, искать что-то новое,
предлагать; генерировать, но не ставить что попало»). The ear cannot be replaced, so this is a measuring filter + a catalog + audition reels
that Стас votes on (the votes land in timbre_verdicts.json through timbre_guard.add_verdict and exclude / favour sounds from then on).

Measured per sound (first 4-6 s, mono):
- buzz      energy 1.5-5 kHz / 0.1-1.5 kHz: the reedy «гармошка» upper-mid (liked reference stems 0.08, the squeezed W.A. pad of Orbit 0.6-0.75);
- rough     Vassilakis-style roughness of the strongest partials (beating neighbours);
- sharp     Zwicker/Aures sharpness from a Bark-band loudness estimate;
- beat      share of the amplitude envelope motion at 3-12 Hz (tremolo / reed beating);
- tonal     pyin voiced fraction, native pitch (keycenter), chroma agreement;
- attack_ms, dur_s (until -30 dB), flat (spectral flatness).
The role (pad / pluck / lead / bass / texture) is guessed from those; score 0-100 = 100 minus penalties, + a bonus / malus from the nearest judged
sound in timbre_verdicts.json. Register rule (P119): a sound is only offered for notes within ±7 semitones of its own pitch."""
import json, os, glob
import numpy as np, soundfile as sf
from .core import SR

CATALOG = os.environ.get("AUTODJ_SOUND_CATALOG", "/opt/autodj-mixer/shared/sound_catalog.json")
MAX_SHIFT = 7

def _mono(path, sr=22050, seconds=6.0):
    import librosa
    info = sf.info(path); n = int(min(info.frames, seconds * info.samplerate))
    x, s = sf.read(path, frames=n, dtype="float32", always_2d=True); y = x.mean(1)
    return librosa.resample(y, orig_sr=s, target_sr=sr) if s != sr else y

def _band(S, fr, lo, hi): return float(S[(fr >= lo) & (fr < hi)].sum() + 1e-12)

def roughness(y, sr, n_peaks=14):
    """Vassilakis-style: sum over pairs of strongest partials of (a1 a2)^.1 * .5 (2 a_min/(a1+a2))^3.11 * (exp(-3.5 s d) - exp(-5.75 s d))"""
    seg = y[: sr * 2]
    if len(seg) < 4096: return 0.0
    X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))); f = np.fft.rfftfreq(len(seg), 1 / sr); m = (f > 60) & (f < 5000)
    ix = np.where(m & (X > np.roll(X, 1)) & (X > np.roll(X, -1)))[0]; ix = ix[np.argsort(-X[ix])[:n_peaks]]
    if len(ix) < 2: return 0.0
    a = X[ix] / (X[ix].max() + 1e-12); fr = f[ix]; R = 0.0
    for i in range(len(ix)):
        for j in range(i + 1, len(ix)):
            f1, f2 = sorted((fr[i], fr[j])); d = f2 - f1; s = .24 / (.0207 * f1 + 18.96)
            R += (a[i] * a[j]) ** .1 * .5 * (2 * min(a[i], a[j]) / (a[i] + a[j] + 1e-12)) ** 3.11 * (np.exp(-3.5 * s * d) - np.exp(-5.75 * s * d))
    return float(R)

def sharpness(y, sr):
    """Zwicker/Aures sharpness (acum-like units) from a crude Bark-band specific loudness"""
    S = np.abs(np.fft.rfft(y[: sr * 3] * np.hanning(min(len(y), sr * 3)))) ** 2; f = np.fft.rfftfreq(min(len(y), sr * 3), 1 / sr)
    z = 13 * np.arctan(.00076 * f) + 3.5 * np.arctan((f / 7500) ** 2); N = np.zeros(24)
    for b in range(24): N[b] = (S[(z >= b) & (z < b + 1)].sum() + 1e-12) ** .23
    zc = np.arange(24) + .5; g = np.where(zc < 15.8, 1.0, .15 * np.exp(.171 * (zc - 15.8)))
    return float(.11 * (N * g * zc).sum() / (N.sum() + 1e-12))

def metrics(y, sr=22050):
    """-> dict of the measures above, or None for silence"""
    import librosa
    if len(y) < sr // 4 or np.abs(y).max() < 1e-4: return None
    y = y / (np.abs(y).max() + 1e-9); S = np.abs(librosa.stft(y, n_fft=4096, hop_length=1024)) ** 2; fr = librosa.fft_frequencies(sr=sr, n_fft=4096); P = S.sum(1)
    hi_, lo_ = _band(P[:, None], fr, 1500, 5000), _band(P[:, None], fr, 100, 1500); buzz = hi_ / (hi_ + lo_)       # bounded share: liked stem .05, squeezed Orbit pad .4-.55
    env = librosa.feature.rms(y=y, frame_length=1024, hop_length=256)[0]; e = env / (env.max() + 1e-9); t = np.arange(len(e)) * 256 / sr
    att = float(t[np.argmax(e > .9)] * 1000); below = np.where((e < 10 ** (-30 / 20)) & (t > t[np.argmax(e)]))[0]; dur = float(t[below[0]] if len(below) else t[-1])
    seg = e[np.argmax(e):][: int(4 * sr / 256)]
    if len(seg) > 64:
        E = np.abs(np.fft.rfft((seg - seg.mean()) * np.hanning(len(seg)))); ff = np.fft.rfftfreq(len(seg), 256 / sr)
        beat = float(E[(ff > 3) & (ff < 12)].sum() / (E[(ff > .3) & (ff < 30)].sum() + 1e-9))
    else: beat = 0.0
    f0, v, _ = librosa.pyin(y[: sr * 2], fmin=30, fmax=2000, sr=sr, frame_length=4096)
    tonal = float(np.mean(v)) if len(v) else 0.0
    kc = int(round(float(np.nanmedian(librosa.hz_to_midi(f0[v]))))) if np.any(v) else None
    pc = int(np.argmax(librosa.feature.chroma_cqt(y=y[: sr * 2], sr=sr).mean(1)))
    cen = float((fr[:, None] * P[:, None]).sum() / P.sum())
    return {"buzz": round(buzz, 3), "rough": round(roughness(y, sr), 3), "sharp": round(sharpness(y, sr), 2), "beat": round(beat, 3), "tonal": round(tonal, 2), "kc": kc,
            "pc_ok": (kc % 12 == pc) if kc is not None else False, "attack_ms": round(att), "dur_s": round(dur, 2), "flat": round(float(np.median(librosa.feature.spectral_flatness(y=y))), 4), "cen": round(cen)}

def guess_role(m):
    if m is None: return None
    if m["tonal"] < .35: return "texture" if m["dur_s"] >= 1.5 else "perc"
    if m["kc"] is not None and m["kc"] < 46 and m["dur_s"] < 3.5: return "bass"
    if m["dur_s"] >= 2.5 and m["attack_ms"] >= 120: return "pad"
    if m["dur_s"] >= 2.5: return "drone" if m["kc"] is not None and m["kc"] < 52 else "pad"
    if m["attack_ms"] < 40 and m["dur_s"] < 2.0: return "pluck"
    return "lead"

def score(m, role=None):
    """0-100. Penalties are scaled on the liked reference stems (buzz .08, beat .31) and on the squeezed W.A. pad (buzz .6-.75): everything above a 22 % share hurts."""
    if m is None: return 0.0
    role = role or guess_role(m); s = 100.0
    if m["kc"] is None or m["kc"] < 80: s -= 150 * max(0.0, m["buzz"] - .22)    # reedy upper mids (not for sounds whose fundamental is already above 1 kHz)
    s -= 25 * max(0.0, m["sharp"] - 1.9)                    # bright / harsh
    s -= 40 * max(0.0, m["rough"] - 1.2)                    # beating neighbours
    s -= 35 * max(0.0, m["beat"] - .45)                     # unwanted tremolo
    if role in ("pad", "lead", "pluck", "bass", "drone"):
        s -= 60 * max(0.0, .5 - m["tonal"])                 # needs a clear pitch
        if not m["pc_ok"]: s -= 15
    if role == "pad" and m["dur_s"] < 3.0: s -= 15 * (3.0 - m["dur_s"])
    return round(max(0.0, min(100.0, s)), 1)

def judge(path, role=None):
    y = _mono(path); m = metrics(y)
    if m is None: return None
    r = role or guess_role(m); return {"path": path, "role": r, **m, "score": score(m, r)}

def _verdict_adjust(path, entry):
    """nearest judged sound (timbre_guard) moves the score: near a rejected one -30, near a liked one +10 (needs the same feature vector as the guard)"""
    try:
        from . import timbre_guard as G
        y = _mono(path, sr=SR, seconds=4.0); r = G.nearest(np.stack([y, y], 1), entry["role"] if entry["role"] in ("lead", "pad", "bass", "pluck") else None)
        if not r: return 0.0, None
        d, name, good = r["ranked"][0]
        if d < 1.2: return (10.0 if good else -30.0), f"{'near liked' if good else 'near rejected'} {name} ({d:.2f})"
    except Exception: pass
    return 0.0, None

AUDIO_EXT = (".wav", ".flac", ".aif", ".aiff")

def _scan_one(path):
    try: return judge(path)
    except Exception as e: return {"path": path, "error": str(e)}

def scan(dirs, out=CATALOG, limit=None, procs=5, skip_words=("loop", "kit", "beat", "drum", "kick", "snare", "hat", "clap", "perc", "tom", "cymbal", "crash")):
    """measure every tonal-looking file under dirs and write the catalog (path, role, native pitch, window, score, measures)"""
    from multiprocessing import Pool
    files = []
    for d in dirs:
        for p in glob.glob(os.path.join(d, "**", "*"), recursive=True):
            if p.lower().endswith(AUDIO_EXT) and not any(w in p.lower() for w in skip_words): files.append(p)
    files = sorted(set(files))[:limit]
    with Pool(procs) as pool: res = pool.map(_scan_one, files, chunksize=4)
    old = json.load(open(out)) if os.path.exists(out) else {}
    for r in res:
        if not r or "error" in r: continue
        r["window"] = [r["kc"] - MAX_SHIFT, r["kc"] + MAX_SHIFT] if r["kc"] is not None else None; old[r["path"]] = r
    json.dump(old, open(out, "w"), ensure_ascii=False, indent=0); return len(old)

def load_catalog(path=None):
    p = path or CATALOG
    return json.load(open(p)) if os.path.exists(p) else {}

def pick(role, midi_lo, midi_hi, n=5, min_score=60.0, catalog=None, use_verdicts=True):
    """best catalog sounds for a role whose own pitch fits the register of the notes (every note within ±MAX_SHIFT semitones of the centre)"""
    cat = catalog if catalog is not None else load_catalog(); mid = (midi_lo + midi_hi) / 2; half = (midi_hi - midi_lo) / 2; out = []
    for e in cat.values():
        if e.get("kc") is None or e["role"] != role or e["score"] < min_score: continue
        if abs(e["kc"] - mid) + half > MAX_SHIFT + 5: continue                   # the whole range must stay near the sample's pitch (+5 st slack for wide chords)
        adj, why = _verdict_adjust(e["path"], e) if use_verdicts else (0.0, None)
        if adj <= -30: continue
        out.append({**e, "final": round(e["score"] + adj, 1), "why": why})
    return sorted(out, key=lambda e: -e["final"])[:n]

def reel(entries, midi, out_mp3, seconds=4.0, gap_s=.8, sr=SR):
    """audition reel: each candidate played as one held note at `midi` (pitch kept within ±7 of its own pitch by octave folding), separated by silence.
    Returns the timeline [(start_s, name, score)]."""
    import subprocess
    from .sfz import oneshot
    parts, tl, t = [], [], 0.0
    for e in entries:
        o = oneshot(e["path"], keycenter=e["kc"], policy="fold"); x = o.render([(.05, midi, 100, seconds - .6)], seconds)
        x = x / (np.abs(x).max() + 1e-9) * .6; x[-int(.3 * sr):] *= np.linspace(1, 0, int(.3 * sr))[:, None]
        parts += [x, np.zeros((int(gap_s * sr), 2), np.float32)]; tl.append((round(t, 1), os.path.basename(e["path"]), e.get("final", e["score"]))); t += seconds + gap_s
    wav = out_mp3 + ".wav"; sf.write(wav, np.concatenate(parts), sr)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-q:a", "3", out_mp3], check=True); os.remove(wav); return tl

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "scan": print(scan(sys.argv[2:]), "sounds in the catalog")

def multisample(entries, name, release=1.2, cache_dir=None):
    """P120: real multisampling from catalog entries of one instrument (one file per native pitch, regions split halfway between neighbours):
    every note then sits within a few semitones of a sample that was recorded there"""
    from .sfz import SFZ, SFZ_ROOT
    cache_dir = cache_dir or os.path.join(SFZ_ROOT, "_oneshots"); os.makedirs(cache_dir, exist_ok=True)
    by_kc = {}
    for e in sorted(entries, key=lambda e: -e["score"]): by_kc.setdefault(e["kc"], e)
    ks = sorted(by_kc); lines = []
    for i, k in enumerate(ks):
        lo = 0 if i == 0 else (ks[i - 1] + k) // 2 + 1; hi = 127 if i == len(ks) - 1 else (k + ks[i + 1]) // 2
        lines.append(f"<region> sample={by_kc[k]['path']} lokey={lo} hikey={hi} pitch_keycenter={k} ampeg_release={release}")
    path = os.path.join(cache_dir, f"ms_{name}.sfz"); open(path, "w").write("\n".join(lines) + "\n"); return SFZ(path)
