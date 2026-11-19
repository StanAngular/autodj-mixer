"""Bear Sax lead renderer (played velocity-layer samples for short notes, played attack -> looped sustain for long ones, vibrato on held notes, breaths). From the parking-reel recreation."""
import os, numpy as np, soundfile as sf, librosa
SR = 44100; SAX = "/home/cclaw/samples/sfz/karoryfer.bear-sax/Samples/"; NAMES = ["c", "db", "d", "eb", "e", "f", "gb", "g", "ab", "a", "bb", "b"]; _c = {}
def ld(f):
    if f in _c: return _c[f]
    x, s = sf.read(SAX + f, dtype="float32", always_2d=True); x = x.mean(1); _c[f] = librosa.resample(x, orig_sr=s, target_sr=SR) if s != SR else x; return _c[f]
def nm(m): return f"{NAMES[m % 12]}{m // 12 - 2}"
def shifted(f, st):
    k = (f, st)
    if k not in _c: _c[k] = librosa.effects.pitch_shift(ld(f), sr=SR, n_steps=st) if st else ld(f)
    return _c[k]
def sample(m, kind):
    base = min(max(m, 37), 65); f = f"{nm(base)}_{kind}.wav"
    return shifted(f, m - base) if os.path.exists(SAX + f) else None
def played(m, vel, rr):
    base = min(max(m, 37), 65); lay = 1 + min(3, int(vel * 4)); f = f"{nm(base)}_vl{lay}_rr{rr}.wav"
    if not os.path.exists(SAX + f): f = f"{nm(base)}_vl{lay}_rr1.wav"
    return shifted(f, m - base)
def render(notes, N, rng):
    """notes: (t_sec, midi, dur_sec, vel 0-1) -> mono float32 buffer of N samples"""
    dry = np.zeros(N, np.float32); vib = np.zeros(N, np.float32); br = ld("breath_osc_1.wav"); breath = np.zeros(N, np.float32); notes = sorted(notes)
    for i, (a, m, d, vel) in enumerate(notes):
        st = played(m, vel, 1 + i % 3); n = int((d + .1) * SR); rel = int(.09 * SR)
        if d <= .4: seg = st[:n].copy() if len(st) >= n else np.pad(st, (0, n - len(st)))
        else:
            lp = sample(m, "looped_f" if vel > .7 else "looped_p"); lp = np.pad(lp, (0, max(0, n - len(lp))))[:n] * .8; xf = int(.12 * SR); seg = lp.copy(); head = st[:xf] if len(st) >= xf else np.pad(st, (0, xf - len(st)))
            seg[:xf] = head * np.linspace(1, 0, xf) + seg[:xf] * np.linspace(0, 1, xf)
        seg = seg.astype(np.float32); seg[:int(.004 * SR)] *= np.linspace(0, 1, int(.004 * SR)); seg[-rel:] *= np.linspace(1, 0, rel)
        i0 = int(a * SR); k = min(len(seg), N - i0)
        if k > 0: dry[i0:i0 + k] += seg[:k] * vel
        gap = a - (notes[i - 1][0] + notes[i - 1][2]) if i else 1.0
        if gap > .4:
            b0 = max(0, i0 - int(.35 * SR)); bl = min(len(br), int(.3 * SR)); breath[b0:b0 + bl] += br[:bl] * np.hanning(bl) * .22
        if d > .4: vib[i0 + int(.22 * SR):min(N, i0 + int(d * SR))] = 1.0
    ve = np.convolve(vib, np.hanning(int(.15 * SR)) / np.hanning(int(.15 * SR)).sum(), "same"); tt = np.arange(N) / SR
    ph = 2 * np.pi * np.cumsum(5.2 + .4 * np.sin(2 * np.pi * .3 * tt)) / SR; depth = (2 ** (24 / 1200) - 1) / (2 * np.pi * 5.3); dl = .004 + ve * depth * np.sin(ph)
    out = np.interp(np.arange(N) - dl * SR, np.arange(N), dry).astype(np.float32) + breath
    return out
