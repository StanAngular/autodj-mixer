"""v3 (Стас: «распознай и создай»): bass/lead pitches from a per-16th tuning-corrected tracking (grid16.json): bass = G#1 for 2 beats, A1 for 2 beats, alternating (the A stretches are real, my v2 retraction was wrong); lead = C4 / D5 guitar riff with outliers removed.
v2 after Стас «музыкальности нет, херню распознал и создал». Two analysis bugs fixed:
1) the Karoryfer «staccato» guitar files are muted thumps with no pitch (CQT peak D2/F2 for c4/c5) -> v1 lead was noise (flatness .16); now a plucked-string (Karplus-Strong) lead with exact pitch.
2) bass «A1/G1/A#1 neighbours» were pyin glide artefacts of the pizz attack: the bass is one note, G#1, the whole clip, tuned ~32 cents flat.
Lead = per-8th CQT top note of the «other» stem, outliers dropped: a C4 / D5 two-octave riff with E5 tops. Tonal layers retuned -0.32 st like the original."""
import sys, json, os, numpy as np, soundfile as sf, librosa
sys.path.insert(0, "/opt/autodj-mixer")
from autodj.compose.sfz import SFZ
from pedalboard import Pedalboard, HighpassFilter, LowpassFilter, Reverb, Compressor, Limiter, Distortion
SR = 44100; HERE = os.path.dirname(os.path.abspath(__file__)); spec = json.load(open(HERE + "/../spec.json")); G16 = json.load(open(HERE + "/../grid16.json")); T = 12.6; N = int(T * SR)
Q = 60 / 143.5; E8 = Q / 2; S16 = Q / 4; PH = 0.151
KIT = "/home/cclaw/samples/musicradar/drums/musicradar-drum-samples/Drum Kits/Kit 1 - Acoustic close/CYCdh_K1close_"
def ld(n):
    x, sr = sf.read(KIT + n + ".wav", dtype="float32", always_2d=True); return librosa.resample(x.mean(1), orig_sr=sr, target_sr=SR) if sr != SR else x.mean(1)
kick, snare, hat, oh = ld("Kick-03"), ld("Snr-02"), ld("ClHat-02"), ld("OpHat-03")
def put(buf, x, t, g=1.0, pan=0.0):
    i = int(t * SR); k = min(len(x), N - i)
    if i >= 0 and k > 0: buf[i:i + k, 0] += x[:k] * g * (1 - pan); buf[i:i + k, 1] += x[:k] * g * (1 + pan)
rng = np.random.default_rng(13); D = np.zeros((N, 2), np.float32)
for k in range(int((T - PH) / S16)):
    t = PH + k * S16 + .004 * rng.standard_normal(); s = k % 4
    if s == 0: put(D, kick, t, .9 + .08 * rng.random())
    if s == 2: put(D, oh, t, .32 + .06 * rng.random())
    if s in (1, 3): put(D, hat, t, .10 + .05 * rng.random(), pan=.15)
for t in (2.159, 7.268): put(D, snare, t, .8)
# bass: one note G#1, at the measured pizz onsets of the bass stem
bass = SFZ("/home/cclaw/samples/sfz/dsmolken.double-bass/d_smolken_rubner_bass_pizz.sfz", tune=False)
bp = lambda t: G16["bass"][min(len(G16["bass"]) - 1, max(0, int(round((t - PH) / S16))))]
bev = sorted((t, bp(t), int(80 + 40 * min(1, a * 3)), max(.06, min(d, .3))) for t, m, d, a in spec["bass"])
B = np.asarray(bass.render(bev, T)); B = np.pad(B, ((0, max(0, N - len(B))), (0, 0)))[:N]
# lead: per-8th notes measured from the «other» stem (CQT), outliers -> previous note
L = G16["lead"]; ok = {60, 74, 76, 55, 61}; notes = []
for i, m in enumerate(L):
    if m is None or m not in ok and not (m in (61, 63, 71) and i > 0 and L[i - 1] == m): continue
    if i > 0 and L[i - 1] == m and m in (60, 74) and i % 2: continue                          # a held note re-plucks every 8th, not every 16th
    notes.append((i / 2, m))
def ks(f, dur, bright=.5):
    n = int(dur * SR); p = int(SR / f); buf = rng.uniform(-1, 1, p) * np.hanning(p) ** .3; out = np.zeros(n)
    for i in range(n): out[i] = buf[i % p]; buf[i % p] = (1 - bright * .5) * .996 * buf[i % p] + bright * .5 * .996 * buf[(i + 1) % p]
    a = int(.002 * SR); out[:a] *= np.linspace(0, 1, a); return (out * np.exp(-np.arange(n) / (SR * .18))).astype(np.float32)
G = np.zeros((N, 2), np.float32); cache = {}
for i, m in notes:
    if m not in cache: cache[m] = ks(librosa.midi_to_hz(m), .35)
    put(G, cache[m], PH + i * E8 + .005 * rng.standard_normal(), .8, pan=-.1)
tun = lambda x: np.stack([librosa.effects.pitch_shift(x[:, c], sr=SR, n_steps=-0.32) for c in range(2)], 1).astype(np.float32)
B, G = tun(B), tun(G)
rms = lambda x: 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9); to = lambda x, db: x * 10 ** ((db - rms(x)) / 20)
D = Pedalboard([HighpassFilter(35), LowpassFilter(8000), Compressor(-18, 3, 5, 80), Reverb(room_size=.2, wet_level=.07, dry_level=1.0)])(D, SR)
B = Pedalboard([HighpassFilter(35), LowpassFilter(1500), Compressor(-20, 3, 5, 100)])(B, SR)
G = Pedalboard([HighpassFilter(150), Distortion(drive_db=6), LowpassFilter(3200), Reverb(room_size=.3, wet_level=.15, dry_level=1.0)])(G, SR)
mix = to(D, -15.3) + to(B, -22.0) + to(G, -26.0)
mix = Pedalboard([Compressor(-14, 2, 10, 120), Limiter(-1.0)])(mix.astype(np.float32), SR)
sf.write(HERE + "/rec.wav", mix, SR); os.system(f"ffmpeg -loglevel error -y -i {HERE}/rec.wav -b:a 192k {HERE}/rec.mp3"); print("done", len(notes), "lead notes")
