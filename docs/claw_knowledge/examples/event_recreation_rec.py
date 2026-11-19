"""Recreation of «Quadratic Helm» (SIM80, 5:52) from an event-level transcription of the demucs stems (events.json): ~133 BPM, G pedal bass (G1, G#1 accents) as rolling 16ths, 3+3+2 kick,
plucked low arp on F2/C3/D#3 + a high line C4/C#4/F4, structure from stem loudness. Recorded samples only (Tidal drum machines, W.A. bass/lead shots picked by the sound gate for pitch)."""
import sys, os, glob, json, numpy as np, soundfile as sf, librosa
sys.path.insert(0, "/opt/autodj-mixer")
from autodj.compose import fresh, soundgate as SG, load_sample
from autodj.compose.sfz import oneshot
from autodj.compose.core import sat
from pedalboard import Pedalboard, HighpassFilter, LowpassFilter, Reverb, Compressor, Limiter, Delay
SR = 44100; HERE = os.path.dirname(os.path.abspath(__file__)); ev = json.load(open(HERE + "/events.json")); T = 352.6; N = int(T * SR); TITLE = "Quadratic Helm recreation"
TDM = "/home/cclaw/samples/tidal-drum-machines/machines/"; WA = "/home/cclaw/samples/wa_techno/WAV MIDI Presets/Synth & Bass Shots/"
rng = np.random.default_rng(1119); db = fresh.load()
def hs(p):
    x, sr = sf.read(p, frames=int(.5 * 44100), dtype="float32", always_2d=True); y = x.mean(1)
    if len(y) < 2048 or np.abs(y).max() < .05: return None
    n = min(len(y), int(.2 * sr)); S = np.abs(np.fft.rfft(y[:n] * np.hanning(n))) ** 2; f = np.fft.rfftfreq(n, 1 / sr)
    return dict(lf=float(S[f < 150].sum() / (S.sum() + 1e-12)), cen=float((f * S).sum() / (S.sum() + 1e-12)), rms=float(np.sqrt((y[:int(.15 * sr)] ** 2).mean())), dur=len(x) / sr)
def strong(pat, kind):
    rows = []
    for p in sorted(glob.glob(TDM + pat)):
        h = hs(p)
        if not h: continue
        sc = {"kick": h["rms"] * h["lf"] if h["dur"] >= .1 else 0, "snare": h["rms"] * (1200 < h["cen"] < 6000) * (h["dur"] > .1)}[kind]
        if sc > 0: rows.append((sc, p))
    rows.sort(reverse=True); return fresh.pick([p for _, p in rows[:14]], rng, db=db, title=TITLE)
kp = strong("*/*-bd/*.wav", "kick"); sp = strong("*/*-sd/*.wav", "snare"); cp = fresh.pick(sorted(glob.glob(TDM + "*/*-cp/*.wav")), rng, db=db, title=TITLE)
hp = fresh.pick([p for p in sorted(glob.glob(TDM + "*/*-hh/*.wav")) if "rev" not in p.lower()], rng, db=db, title=TITLE)
pool = lambda *k: sorted({p for x in k for p in glob.glob(WA + x)})
bp = SG.pick(pool("*Bass*.wav"), "bass", 29, 36, rng, db=db, title=TITLE, strict=False); lp = SG.pick(pool("*Bass*.wav", "*Pluck*.wav"), "bass", 38, 52, np.random.default_rng(7), db=db, title=TITLE, strict=False)
hip = SG.pick(pool("*Pluck*.wav", "*Lead*.wav"), "lead", 58, 70, rng, db=db, title=TITLE, strict=False)
print("drums", [os.path.basename(x) for x in (kp, sp, cp, hp)], "sounds", [os.path.basename(x) for x in (bp, lp, hip)], flush=True)
K, S_, C_, H_ = load_sample(kp, .45), load_sample(sp, .3), load_sample(cp, .3), load_sample(hp, .08)
def put(buf, x, t, g=1.0):
    i = int(t * SR); k = min(len(x), N - i)
    if i >= 0 and k > 0: buf[i:i + k] += x[:k] * g
Dm = np.zeros((N, 2), np.float32)
for t, a in ev["kick"]:
    if a > .3: put(Dm, K, t, .8 + .3 * min(1, a))
for t, a in ev["snare"]:
    if a > .15: put(Dm, S_, t, .5 * min(1, a * 1.5)); put(Dm, C_, t, .25 * min(1, a * 1.5))
for t, a in ev["hat"]:
    if a > .05: put(Dm, H_, t, .7 * min(1, a * 3))
def render(path, evs, rel):
    ins = oneshot(path, release=rel, policy="warn"); x = np.asarray(ins.render(sorted(evs), T)); return np.pad(x, ((0, max(0, N - len(x))), (0, 0)))[:N]
bev = [(t, m if 30 <= m <= 36 else 31, int(60 + 60 * min(1, a * 2)), max(.06, d * .9)) for t, m, d, a in ev["bass"] if 30 <= m <= 36 and a > .08]
lev = [(t, m, int(55 + 65 * min(1, a * 3)), max(.08, d)) for t, m, d, a in ev["other"] if 38 <= m <= 56 and a > .06]
hev = [(t, m, int(55 + 65 * min(1, a * 3)), max(.08, d)) for t, m, d, a in ev["other"] if 58 <= m <= 80 and a > .06]
print("events bass/low/high", len(bev), len(lev), len(hev), flush=True)
Bx, Lx, Hx = render(bp, bev, .06), render(lp, lev, .15), render(hip, hev, .3)
rms = lambda x: 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9); to = lambda x, db_: x * 10 ** ((db_ - rms(x)) / 20)
Dm = Pedalboard([HighpassFilter(30), Compressor(-16, 3, 4, 70)])(Dm, SR)
Bx = Pedalboard([HighpassFilter(28), LowpassFilter(900), Compressor(-20, 3, 4, 80)])(Bx, SR)
Lx = Pedalboard([HighpassFilter(70), LowpassFilter(3200), Reverb(room_size=.3, wet_level=.12, dry_level=1.0)])(Lx, SR)
Hx = Pedalboard([HighpassFilter(250), LowpassFilter(4500), Delay(delay_seconds=60 / 133 * .75, feedback=.35, mix=.25), Reverb(room_size=.5, wet_level=.2, dry_level=1.0)])(Hx, SR)
from autodj.compose import stereo
Lx = stereo.steady(Lx, .35, 1); Hx = stereo.steady(Hx, .45, 2); Dm = (Dm + .35 * sat(Dm, 2.5)).astype(np.float32)
mix = to(Dm, -12.8) + to(Bx, -34.0) + to(Lx, -22.0) + to(Hx, -28.0)
mix = Pedalboard([Compressor(-14, 2, 10, 120), Limiter(-1.0)])(mix.astype(np.float32), SR)
sf.write(HERE + "/raw.wav", mix, SR)
from autodj.compose.master import warm
warm(HERE + "/raw.wav", HERE + "/rec.wav", target=-11.0)
os.system(f"ffmpeg -loglevel error -y -i {HERE}/rec.wav -b:a 192k {HERE}/rec.mp3"); print("done", rms(mix))
