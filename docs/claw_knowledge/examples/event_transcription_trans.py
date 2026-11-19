"""Event-level transcription of the whole reference (stems from demucs): drums (kick/snare-clap/hat by band), bass and 'other' notes with pitch per onset. -> events.json"""
import librosa, numpy as np, json, scipy.signal as sg
sr = 22050; hop = 256; ev = {}
def load(s): return librosa.load(f"stems/htdemucs/ref/{s}.wav", sr=sr)[0]
d = load("drums")
for name, (lo, hi), delta in (("kick", (30, 140), .1), ("snare", (180, 2500), .12), ("hat", (6500, 10500), .08)):
    x = sg.sosfilt(sg.butter(4, [lo, hi], "band", fs=sr, output="sos"), d)
    on = librosa.onset.onset_detect(y=x, sr=sr, units="samples", hop_length=hop, delta=delta, backtrack=False)
    ev[name] = [(round(o / sr, 3), round(float(np.abs(x[o:o + int(.05 * sr)]).max()), 3)) for o in on]
    print(name, len(on), flush=True)
def notes(stem, fmin, fmax, delta):
    y = load(stem); f0, v, p = librosa.pyin(y, fmin=fmin, fmax=fmax, sr=sr, frame_length=4096, hop_length=hop); t = librosa.times_like(f0, sr=sr, hop_length=hop)
    on = list(librosa.onset.onset_detect(y=y, sr=sr, units="time", hop_length=hop, delta=delta)) + [len(y) / sr]; res = []
    for a, b in zip(on[:-1], on[1:]):
        k = (t >= a + .02) & (t < min(b, a + .3)) & v & ~np.isnan(f0)
        if k.sum() < 2: continue
        res.append((round(a, 3), int(round(np.median(librosa.hz_to_midi(f0[k])))), round(min(b - a, .5), 3), round(float(np.abs(y[int(a * sr):int((a + .05) * sr)]).max()), 3)))
    return res
ev["bass"] = notes("bass", 30, 250, .05); print("bass", len(ev["bass"]), flush=True)
ev["other"] = notes("other", 80, 2000, .05); print("other", len(ev["other"]), flush=True)
json.dump(ev, open("events.json", "w"))
