#!/usr/bin/env python3
"""
Track Order Optimizer
Analyzes BPM, key (Camelot wheel), energy, intro/outro types to find
the optimal track order for DJ mixing via exhaustive permutation search.

Usage:
  python3 analyze_order.py --wav-dir ./wav --ann-dir ./annotations
"""
import sys, os, argparse
import numpy as np
import soundfile as sf
import scipy.signal as sig
from itertools import permutations

SR = 44100

def load_dbeats(ann_path):
    beats = np.loadtxt(ann_path)
    return np.array([r[0] for r in beats if round(r[1]) == 1])

def calc_bpm(db):
    if len(db) < 4: return 120.0
    iv = np.diff(db); iv = iv[iv > 0.3]
    if not len(iv): return 120.0
    p25 = np.percentile(iv, 25)
    r = iv[iv <= p25 * 1.3]
    if not len(r): r = iv
    bpm = 4 * 60.0 / np.mean(r)
    return bpm * 2 if bpm < 90 else bpm

def get_key(audio_mono, sr):
    """Key detection via chroma + Krumhansl profiles."""
    import librosa
    chroma = librosa.feature.chroma_cqt(y=audio_mono, sr=sr)
    profile = chroma.mean(axis=1)
    keys = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    maj = [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
    minn = [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]
    best_corr = -1; best_key = "?"
    for shift in range(12):
        rolled = np.roll(profile, -shift)
        cm = np.corrcoef(rolled, maj)[0,1]
        cn = np.corrcoef(rolled, minn)[0,1]
        if cm > best_corr: best_corr = cm; best_key = f"{keys[shift]} maj"
        if cn > best_corr: best_corr = cn; best_key = f"{keys[shift]} min"
    return best_key

# Camelot wheel
CAMELOT = {
    'C maj':'8B','C# maj':'3B','D maj':'10B','D# maj':'5B','E maj':'12B',
    'F maj':'7B','F# maj':'2B','G maj':'9B','G# maj':'4B','A maj':'11B',
    'A# maj':'6B','B maj':'1B',
    'C min':'5A','C# min':'12A','D min':'7A','D# min':'2A','E min':'9A',
    'F min':'4A','F# min':'11A','G min':'6A','G# min':'1A','A min':'8A',
    'A# min':'3A','B min':'10A',
}

def key_compat(k1, k2):
    c1 = CAMELOT.get(k1, '?'); c2 = CAMELOT.get(k2, '?')
    if '?' in (c1, c2): return 0.5
    n1, t1 = int(c1[:-1]), c1[-1]
    n2, t2 = int(c2[:-1]), c2[-1]
    if c1 == c2: return 1.0
    if t1 == t2 and abs(n1-n2) in (1, 11): return 0.9
    if n1 == n2 and t1 != t2: return 0.8
    return 0.3

def analyze_tracks(wav_dir, ann_dir):
    wav_files = sorted(f for f in os.listdir(wav_dir) if f.endswith('.wav'))
    info = {}

    print("=== TRACK ANALYSIS ===\n")
    for wf in wav_files:
        base = os.path.splitext(wf)[0]
        ann = base + '.txt'
        ann_path = os.path.join(ann_dir, ann)
        if not os.path.exists(ann_path):
            continue

        name = base.split(' - ')[0] if ' - ' in base else base[:20]
        audio, sr = sf.read(os.path.join(wav_dir, wf), always_2d=True)
        mono = audio.mean(1).astype(np.float32)
        db = load_dbeats(ann_path)
        bpm = calc_bpm(db)
        key = get_key(mono, SR)
        dur = len(mono) / SR

        # Energy analysis
        win = int(2 * SR)
        n_w = len(mono) // win
        energies = np.array([np.sqrt(np.mean(mono[i*win:(i+1)*win]**2)) for i in range(n_w)])
        med_e = np.median(energies)

        # Outro type
        last_5_bars = db[-6:] if len(db) > 6 else db
        outro_zone = mono[int(last_5_bars[0]*SR):] if len(last_5_bars) else mono[-int(30*SR):]
        outro_type = "quiet" if np.sqrt(np.mean(outro_zone**2)) < med_e * 0.4 else "loud"

        # Intro type
        first_5_bars = db[:6] if len(db) > 6 else db
        intro_zone = mono[:int(first_5_bars[-1]*SR)] if len(first_5_bars) > 1 else mono[:int(30*SR)]
        intro_type = "quiet" if np.sqrt(np.mean(intro_zone**2)) < med_e * 0.4 else "loud"

        info[name] = {
            'bpm': bpm, 'key': key, 'dur': dur,
            'intro_type': intro_type, 'outro_type': outro_type,
            'wav': wf, 'ann': ann
        }

        print(f"  {name:15s}  BPM={bpm:5.1f}  Key={key:8s}  "
              f"Intro={intro_type:5s}  Outro={outro_type:5s}  "
              f"Dur={int(dur//60)}:{int(dur%60):02d}")

    return info

def find_optimal_order(info):
    names = list(info.keys())
    n = len(names)

    if n > 10:
        print(f"\n{n} tracks = {np.math.factorial(n)} permutations, too many for exhaustive. Using greedy.")
        # Greedy nearest-neighbor
        order = [names[0]]
        remaining = set(names[1:])
        while remaining:
            best_score = -1; best_next = None
            cur = order[-1]
            for nxt in remaining:
                bpm_diff = abs(info[cur]['bpm'] - info[nxt]['bpm']) / info[cur]['bpm']
                bpm_score = max(0, 1 - bpm_diff * 10)
                kc = key_compat(info[cur]['key'], info[nxt]['key'])
                score = bpm_score * 0.5 + kc * 0.3 + 0.2
                if score > best_score:
                    best_score = score; best_next = nxt
            order.append(best_next)
            remaining.remove(best_next)
        return [order]

    # Exhaustive search
    cost = {}
    for a in names:
        for b in names:
            if a == b: continue
            ia = info[a]; ib = info[b]
            bpm_diff = abs(ia['bpm'] - ib['bpm']) / ia['bpm']
            kc = key_compat(ia['key'], ib['key'])
            outro_intro = 1.0
            if ia['outro_type'] == 'quiet' and ib['intro_type'] == 'quiet': outro_intro = 0.9
            elif ia['outro_type'] == 'loud' and ib['intro_type'] == 'quiet': outro_intro = 0.7
            elif ia['outro_type'] == 'quiet' and ib['intro_type'] == 'loud': outro_intro = 0.5
            else: outro_intro = 0.4
            bpm_score = max(0, 1 - bpm_diff * 10)
            cost[(a,b)] = bpm_score * 0.5 + kc * 0.3 + outro_intro * 0.2

    results = []
    for perm in permutations(names):
        total = sum(cost.get((perm[i], perm[i+1]), 0) for i in range(len(perm)-1))
        results.append((total, list(perm)))
    results.sort(key=lambda x: -x[0])

    print(f"\n=== TOP 5 ORDERS ===\n")
    for i, (score, order) in enumerate(results[:5]):
        bpms = " -> ".join(f"{info[n]['bpm']:.0f}" for n in order)
        print(f"  #{i+1}  score={score:.2f}  {' -> '.join(order)}")
        print(f"       BPM: {bpms}")
        for j in range(len(order)-1):
            a, b = order[j], order[j+1]
            bd = abs(info[a]['bpm'] - info[b]['bpm'])
            kc = key_compat(info[a]['key'], info[b]['key'])
            print(f"       {a}->{b}: BPM diff {bd:.1f}  key={kc:.1f}  {info[a]['outro_type']}->{info[b]['intro_type']}")
        print()

    return [order for _, order in results[:5]]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find optimal track order for DJ mixing")
    parser.add_argument("--wav-dir", required=True)
    parser.add_argument("--ann-dir", required=True)
    args = parser.parse_args()

    info = analyze_tracks(args.wav_dir, args.ann_dir)
    find_optimal_order(info)
