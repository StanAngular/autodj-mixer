"""Recreation of reel De3UtoQRS4e: solo sax in a concrete parking garage, rubato, C minor.
Стас 2026-11-19: do not copy the analyzer blindly; correct the melody by harmony + style so the result is pleasant, and keep it as a rule.
Corrections applied to the raw pyin transcription (each one printed): octave errors folded to the neighbour contour, stray out-of-key notes snapped (A, E, F# kept only as short chromatic neighbours/trills),
glitch notes < 70 ms merged, re-attacks of the same pitch merged, legato durations, the phrase resolves to the tonic at the end.
Instrument: Karoryfer Bear Sax (a real 1926 baritone): looped forte/piano sustains + staccato layer for the attack, played an octave below the transcription (baritone range; same key).
Space: synthetic concrete-garage IR (RT60 ~2.8 s, bright early reflections), delay-line vibrato on held notes, breath before phrases, quiet room tone."""
import os, json, numpy as np, soundfile as sf, librosa
from scipy.signal import sosfilt, butter, fftconvolve
SR = 44100; HERE = os.path.dirname(os.path.abspath(__file__)); SAX = "/home/cclaw/samples/sfz/karoryfer.bear-sax/Samples/"; rng = np.random.default_rng(3)
y, sr = librosa.load(HERE + "/../stems/htdemucs/reel/other.wav", sr=22050)
f0, v, p = librosa.pyin(y, fmin=90, fmax=1300, sr=sr, frame_length=2048, hop_length=256); t = librosa.times_like(f0, sr=sr, hop_length=256); mm = librosa.hz_to_midi(f0)
on = list(librosa.onset.onset_detect(y=y, sr=sr, units="time", hop_length=256, delta=.04)) + [len(y) / sr]; raw = []
for a, b in zip(on[:-1], on[1:]):
    k = (t >= a + .03) & (t < b) & v & ~np.isnan(mm)
    if k.sum() >= 3: raw.append([a, int(np.round(np.median(mm[k]))), b - a, float(np.abs(y[int(a * sr):int((a + .05) * sr)]).max())])
SCALE = {0, 2, 3, 5, 7, 8, 10}; log = []
# 1) merge glitches and same-pitch re-attacks
notes = []
for n in raw:
    if notes and (n[2] < .07 or (n[1] == notes[-1][1] and n[0] - notes[-1][0] < .2)):
        notes[-1][2] = n[0] + n[2] - notes[-1][0]; log.append(f"merge {n[0]:.2f}"); continue
    notes.append(list(n))
# 2) octave errors: a jump > 9 st that comes back is folded to the octave nearest the neighbours; whole line kept inside G3..G5
for i in range(len(notes)):
    m = notes[i][1]; prev = notes[i - 1][1] if i else m; nxt = notes[i + 1][1] if i + 1 < len(notes) else m
    while m < 49: m += 12                                                          # alto sax concert range Db3..Ab5
    while m > 80: m -= 12
    if abs(m - prev) > 9 and abs(nxt - prev) <= 9:
        c = min((m + 12 * k for k in (-1, 1)), key=lambda q: abs(q - (prev + nxt) / 2))
        if 49 <= c <= 80: m = c
    if m != notes[i][1]: log.append(f"octave {notes[i][0]:.2f} {notes[i][1]}->{m}")
    notes[i][1] = m
# 3) key: C minor (+B as leading tone into C). Out-of-key notes kept only as short chromatic neighbours between in-key notes, otherwise snapped to the nearer neighbour in the scale
for i, n in enumerate(notes):
    pc = n[1] % 12
    if pc in SCALE: continue
    prev = notes[i - 1][1] if i else n[1]; nxt = notes[i + 1][1] if i + 1 < len(notes) else n[1]
    if pc == 11 and nxt % 12 == 0 and nxt - n[1] == 1: continue                                   # B -> C leading tone
    if n[2] < .16 and abs(prev - n[1]) == 1 and abs(nxt - n[1]) <= 2: continue                    # trill / chromatic neighbour
    PREF = {0: 0, 3: 0, 5: 0, 7: 0, 10: 0, 8: 1, 2: 2}                              # minor pentatonic first, then Ab, D last
    c = min((n[1] - 1, n[1] + 1, n[1] - 2, n[1] + 2), key=lambda q: (PREF.get(q % 12, 9), abs(q - n[1]), abs(q - nxt))); log.append(f"key {n[0]:.2f} {n[1]}->{c}"); n[1] = c
# 4) legato inside phrases (gap < .35 s), the last note resolves to the tonic and rings
for i in range(len(notes) - 1):
    gap = notes[i + 1][0] - (notes[i][0] + notes[i][2])
    if gap < .35: notes[i][2] = notes[i + 1][0] - notes[i][0] - .01
if notes[-1][1] % 12 != 0:
    last = notes[-1]; c = min((q for q in range(last[1] - 7, last[1] + 8) if q % 12 == 0), key=lambda q: abs(q - last[1])); last[2] = .45
    notes.append([last[0] + last[2] + .02, c, 2.2, last[3]]); log.append(f"resolve -> {c}")
print(len(raw), "raw ->", len(notes), "notes;", len(log), "corrections:", "; ".join(log[:40]))
json.dump(notes, open(HERE + "/notes.json", "w"))
# --- sax render (octave down = baritone register, same key)
def ld(f):
    x, s = sf.read(SAX + f, dtype="float32", always_2d=True); x = x.mean(1); return librosa.resample(x, orig_sr=s, target_sr=SR) if s != SR else x
NAMES = ["c", "db", "d", "eb", "e", "f", "gb", "g", "ab", "a", "bb", "b"]
fname = lambda m, kind: f"{NAMES[m % 12]}{m // 12 - 2}_{kind}"
cache = {}
def sample(m, kind):
    base = min(max(m, 37), 65); key = (base, kind)
    if key not in cache:
        f = fname(base, kind) + (".wav" if "looped" in kind else "_rr1.wav")
        cache[key] = ld(f) if os.path.exists(SAX + f) else None
    x = cache[key]
    if x is None: return None
    return librosa.effects.pitch_shift(x, sr=SR, n_steps=m - base) if m != base else x
T = 30.0; N = int(T * SR); dry = np.zeros(N, np.float32); vib_env = np.zeros(N, np.float32); breath = np.zeros(N, np.float32)
br = ld("breath_osc_1.wav")
def played(m, vel, rr):
    base = min(max(m, 37), 65); lay = 1 + min(3, int(vel * 4)); f = f"{NAMES[base % 12]}{base // 12 - 2}_vl{lay}_rr{rr}.wav"
    if not os.path.exists(SAX + f): f = f"{NAMES[base % 12]}{base // 12 - 2}_vl{lay}_rr1.wav"
    key = (f, m - base)
    if key not in cache: x = ld(f); cache[key] = librosa.effects.pitch_shift(x, sr=SR, n_steps=m - base) if m != base else x
    return cache[key]
for i, (a, m, d, amp) in enumerate(notes):
    m -= 7; vel = min(1, .45 + amp * 2.5); cents = rng.normal(0, 6) / 100
    st = played(m, vel, 1 + i % 3); n = int((d + .1) * SR); rel = int(.08 * SR)
    if d <= .4:                                                                  # a real played note (velocity layer, round-robin), trimmed to its length
        seg = st[:n].copy() if len(st) >= n else np.pad(st, (0, n - len(st)))
    else:                                                                        # long: the played attack crossfades into the forte/piano sustain
        lp = sample(m, "looped_f" if vel > .7 else "looped_p"); lp = lp[:n] if lp is not None and len(lp) >= n else np.pad(lp if lp is not None else np.zeros(1), (0, max(0, n - (len(lp) if lp is not None else 1))))[:n]
        xf = int(.12 * SR); seg = lp.copy() * 0.8; head = st[:xf] if len(st) >= xf else np.pad(st, (0, xf - len(st)))
        seg[:xf] = head * np.linspace(1, 0, xf) + seg[:xf] * np.linspace(0, 1, xf)
    seg = seg.astype(np.float32); seg[:int(.004 * SR)] *= np.linspace(0, 1, int(.004 * SR)); seg[-rel:] *= np.linspace(1, 0, rel)
    i0 = int(a * SR); k = min(len(seg), N - i0); dry[i0:i0 + k] += seg[:k] * vel
    gap_before = a - (notes[i - 1][0] + notes[i - 1][2]) if i else 1.0
    if gap_before > .3:
        b0 = max(0, i0 - int(.35 * SR)); bl = min(len(br), int(.3 * SR)); breath[b0:b0 + bl] += br[:bl] * np.hanning(bl) * .25
    if d > .4: vib_env[i0 + int(.22 * SR):i0 + int(d * SR)] = 1.0
# delay-line vibrato: 5.3 Hz, depth ~ 18 cents, smoothed envelope
ve = np.convolve(vib_env, np.hanning(int(.15 * SR)) / (np.hanning(int(.15 * SR)).sum()), "same")
tt = np.arange(N) / SR; rate = 5.2 + .4 * np.sin(2 * np.pi * .3 * tt); ph = 2 * np.pi * np.cumsum(rate) / SR; depth_s = (2 ** (24 / 1200) - 1) / (2 * np.pi * 5.3); dl = 0.004 + ve * depth_s * np.sin(ph)
idx = np.arange(N) - dl * SR; dry = np.interp(idx, np.arange(N), dry).astype(np.float32)
dry = (dry + breath).astype(np.float32)
# concrete garage IR
L = int(3.6 * SR); ti = np.arange(L) / SR; ir = np.zeros((L, 2), np.float32)
for c in range(2):
    nz = rng.standard_normal(L); out = np.zeros(L)
    for lo, hi, rt in ((80, 400, 3.0), (400, 2000, 2.8), (2000, 6000, 2.3), (6000, 12000, 1.4)):
        out += sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), nz) * np.exp(-6.91 * ti / rt)
    pre = int(.012 * SR); out = np.concatenate([np.zeros(pre), out[:-pre]]) * np.minimum(1, ti / .03)
    for ms, g in ((14, .5), (23, .4), (31, .35), (47, .3), (58, .25), (79, .2)): out[int((ms + 3 * c) * SR / 1000)] += g * 8
    ir[:, c] = out / np.abs(out).max()
wet = np.stack([fftconvolve(dry, ir[:, c])[:N] for c in range(2)], 1); wet /= np.abs(wet).max() + 1e-9
drys = np.stack([dry, dry], 1) / (np.abs(dry).max() + 1e-9)
room = np.stack([sosfilt(butter(2, [60, 3000], "band", fs=SR, output="sos"), rng.standard_normal(N)) for _ in range(2)], 1) * .004
mix = .62 * drys + .55 * wet + room
mix = mix / np.abs(mix).max() * .89
end = int(min(T, notes[-1][0] + notes[-1][2] + 3.0) * SR); mix = mix[:end]; mix[-int(.5 * SR):] *= np.linspace(1, 0, int(.5 * SR))[:, None]
sf.write(HERE + "/rec.wav", mix.astype(np.float32), SR); os.system(f"ffmpeg -loglevel error -y -i {HERE}/rec.wav -b:a 192k {HERE}/rec.mp3"); print("done", end / SR)
