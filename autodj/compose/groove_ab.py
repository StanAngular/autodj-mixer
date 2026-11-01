"""P124 A/B of the «кач»: one 8-bar loop (kick, clap, hats, perc, W.A. bass with a syncopated line) in three feels with identical sounds, notes and loudness.
    python -m autodj.compose.groove_ab house 126 /tmp/ab        -> /tmp/ab/house_A.mp3 B C (blind letters, shuffled) + house_key.json
Feels: grid / reference groove / drum-machine swing 60 %. Only the timing and accents differ; the level is matched to the grid version (rms)."""
import json, os, subprocess, sys
import numpy as np, soundfile as sf
from pedalboard import Pedalboard, HighpassFilter, LowpassFilter, Compressor, LadderFilter
from . import Track, pb, load_sample
from .core import mono2
from .groove_bank import Feel, REFS
from .sfz import oneshot
from .syncopation import lhl
W = "/home/cclaw/samples/wa_techno/WAV MIDI Presets"; SH = f"{W}/Synth & Bass Shots"
BASS_STEPS = (2, 5, 7, 10, 14)                                   # LHL 8: the median of the learned references
def _soft(x, ms, sr=44100):
    x = x.copy(); n = max(2, int(ms / 1000 * sr)); x[:n] *= np.linspace(0, 1, n, dtype=np.float32)[:, None]; return x

def loop(feel, bpm, seed=1, bars=8):
    trk = Track(bpm, bars, seed=seed, tail_s=2.0, humanize_s=0.0); S = trk.sr; T = trk.N / S
    kick = _soft(pb(Pedalboard([HighpassFilter(40), LowpassFilter(3500)]), load_sample(f"{W}/Kicks/WART_Kick_5.wav", .35)), 2.0)
    clap = _soft(pb(Pedalboard([HighpassFilter(300), LadderFilter(LadderFilter.Mode.LPF24, cutoff_hz=4800)]), load_sample(f"{W}/Claps/WART_Clap_6.wav", .3)), 3.0)
    hat = _soft(pb(Pedalboard([HighpassFilter(5000), LadderFilter(LadderFilter.Mode.LPF24, cutoff_hz=7000)]), load_sample(f"{W}/Cymbals/WATS_Closed_HiHat_05.wav", .08)), 3.0)
    perc = _soft(pb(Pedalboard([HighpassFilter(300), LadderFilter(LadderFilter.Mode.LPF24, cutoff_hz=5500)]), load_sample(f"{W}/Percussion/WATE_Percussion_01.wav", .2)), 3.0)
    K, C, H, P = trk.buf(), trk.buf(), trk.buf(), trk.buf(); bev = []
    for br in range(bars):
        for st in (0, 4, 8, 12): trk.place(K, kick, feel.time(trk, br, st, "kick"), 1.0)
        for st in (4, 12): trk.place(C, clap, feel.time(trk, br, st, "clap"), .75)
        for st in range(16):
            if st % 2 == 0 and st % 4: trk.place(H, hat, feel.time(trk, br, st, "hh"), feel.vel("hh", st, 96) / 127 * 1.0)         # offbeat 8ths
            elif st % 2: trk.place(H, hat, feel.time(trk, br, st, "hh"), feel.vel("hh", st, 70) / 127 * .55)                         # ghost 16ths
        for st in ((3, 11) if br % 2 else (6, 14)): trk.place(P, perc, feel.time(trk, br, st, "perc"), feel.vel("perc", st, 90) / 127 * .8)
        for st in BASS_STEPS: bev.append((feel.time(trk, br, st, "bass"), 33 + (0 if br % 4 < 3 else 5), feel.vel("bass", st, 100), trk.S16 * 1.6))
    bass = oneshot(f"{SH}/WART_Gm_Bass_Shot_7.wav", release=.12, policy="warn").render(bev, T)
    bass = pb(Pedalboard([HighpassFilter(40), LowpassFilter(900), Compressor(-18, 3, 3, 80)]), bass[:trk.N] if len(bass) >= trk.N else np.pad(bass, ((0, trk.N - len(bass)), (0, 0))))
    x = K * 1.0 + C * .5 + H * .22 + P * .35 + bass * .7
    return x[:int((bars * trk.BAR + 1.0) * S)].astype(np.float32), S

def rms_db(x): return float(20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12))

def make(style, bpm, outdir, seed=1, shuffle_seed=0):
    os.makedirs(outdir, exist_ok=True); feels = {"grid": Feel("grid"), "ref": Feel("ref", ref=REFS.get(style, REFS["house"]), seed=seed), "swing": Feel("swing", swing=60.0)}
    out = {k: loop(f, bpm, seed)[0] for k, f in feels.items()}; ref = rms_db(out["grid"])
    for k in out:
        y = out[k] * 10 ** ((ref - rms_db(out[k])) / 20); pk = np.abs(y).max(); out[k] = y * (.89 / pk) if pk > .89 else y
    names = list(out); order = np.random.default_rng(shuffle_seed).permutation(3); key = {}
    for i, j in enumerate(order):
        L = "ABC"[i]; w = os.path.join(outdir, f"{style}_{L}.wav"); sf.write(w, out[names[j]], 44100)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", w, "-q:a", "2", os.path.join(outdir, f"{style}_{L}.mp3")], check=True); os.remove(w); key[L] = names[j]
    json.dump({"style": style, "bpm": bpm, "key": key, "ref": REFS.get(style), "bass_lhl": lhl(BASS_STEPS)}, open(os.path.join(outdir, f"{style}_key.json"), "w"), ensure_ascii=False, indent=1)
    return key

if __name__ == "__main__":
    if len(sys.argv) < 4: sys.exit(__doc__)
    print(make(sys.argv[1], float(sys.argv[2]), sys.argv[3]))
