#!/usr/bin/env python3
"""
track_analyzer.py — pre-analyze tracks, sort by BPM + Camelot, build optimal config.
Step 0 of the Mix Pipeline.

Usage:
  python3 track_analyzer.py --config techno_mix_config.py --out optimized_config.py
  python3 track_analyzer.py --wav-dir ./shared/tracks --ann-dir ./shared/ann --out optimized.py
"""
import sys, os, argparse, importlib.util, json
import numpy as np
import librosa

# Try importing from smart_mixer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smart_mixer import SR, load_dbeats, calc_bpm, fix_ht, sections, quiet_exit, bar_s

# Camelot wheel: major keys
CAMELOT_MAJOR = {
    'C': '8B', 'G': '9B', 'D': '10B', 'A': '11B', 'E': '12B', 'B': '1B',
    'F#': '2B', 'C#': '3B', 'F': '4B', 'Bb': '5B', 'Eb': '6B', 'Ab': '7B',
    'C#': '3B', 'Db': '3B', 'Gb': '2B'
}
CAMELOT_MINOR = {
    'c': '5A', 'g': '6A', 'd': '7A', 'a': '8A', 'e': '9A', 'b': '10A',
    'f#': '11A', 'c#': '12A', 'f': '4A', 'bb': '3A', 'eb': '2A', 'ab': '1A',
    'g#': '6A', 'd#': '7A', 'a#': '10A',
}

def detect_key(audio, sr):
    """Detect key + Camelot using librosa chroma (same as smart_mixer)."""
    mono = audio.mean(1) if audio.ndim == 2 else audio
    chroma = librosa.feature.chroma_cqt(y=mono.astype(np.float64), sr=sr)
    chroma_mean = chroma.mean(1)
    key_idx = int(np.argmax(chroma_mean))
    keys_major = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    keys_minor = ['c', 'c#', 'd', 'd#', 'e', 'f', 'f#', 'g', 'g#', 'a', 'a#', 'b']

    maj_strength = (chroma_mean[key_idx] +
                    chroma_mean[(key_idx + 4) % 12] * 0.5 +
                    chroma_mean[(key_idx + 7) % 12] * 0.3)
    min_strength = (chroma_mean[key_idx] +
                    chroma_mean[(key_idx + 3) % 12] * 0.5 +
                    chroma_mean[(key_idx + 7) % 12] * 0.3)

    key = keys_major[key_idx] if maj_strength >= min_strength else keys_minor[key_idx]
    return key

def camelot_score(c1, c2):
    """Camelot compatibility: 0=identical, 1=adjacent, 2=relative, else distant."""
    if c1 == c2:
        return 0  # perfect
    # Parse number and letter
    try:
        num1, letter1 = int(c1[:-1]), c1[-1]
        num2, letter2 = int(c2[:-1]), c2[-1]
    except:
        return 99
    diff = abs(num1 - num2)
    if diff == 0 and letter1 != letter2:
        return 0  # same number, diff letter = same key
    if diff == 1 or diff == 11:
        return 1  # adjacent
    if diff == 2 or diff == 10:
        return 2  # one step away
    return diff  # distant

def analyze_track(wav_path, ann_path, name):
    """Analyze a single track: BPM, key, sections, duration."""
    print(f"  Analyzing {name}...", end=" ", flush=True)

    # Load audio
    audio, fs = librosa.load(wav_path, sr=SR, mono=False)
    if audio.ndim == 2 and audio.shape[0] == 2:
        audio = audio.T
    elif audio.ndim == 1:
        audio = audio[:, None]

    # Load downbeats
    db = load_dbeats(ann_path, SR)
    raw_bpm = calc_bpm(db, SR)
    db_fixed, bpm = fix_ht(db, raw_bpm)

    # Key detection
    key = detect_key(audio, SR)
    camelot = CAMELOT_MAJOR.get(key, CAMELOT_MINOR.get(key, '??'))

    # Sections analysis
    segs = sections(audio, db_fixed)
    qe = quiet_exit(segs)
    cf_bars = 16
    if qe is not None:
        exit_bar = max(0, qe - 2)
        exit_bar = (exit_bar // 16) * 16
    else:
        exit_bar = max(0, len(db_fixed) - cf_bars - 4)
        exit_bar = (exit_bar // 16) * 16

    # Guard: enough room for crossfade
    cf_needed = cf_bars + 3  # bars + buffer
    while exit_bar >= 16:
        test_samp = int(db_fixed[min(exit_bar, len(db_fixed) - 1)])
        if test_samp + int(cf_needed * bar_s(bpm) * SR) <= len(audio):
            break
        exit_bar -= 16

    # Entry bar: first ACTIVE section
    fa = 0
    for s, e, l in segs:
        if l in ('DROP', 'ACTIVE') and e - s >= 8:
            fa = s
            break
    entry_bar = fa

    dur = len(audio) / SR
    print(f"BPM={bpm:.0f} key={key}({camelot}) dur={dur:.0f}s")

    return {
        'name': name,
        'wav': os.path.basename(wav_path),
        'ann': os.path.basename(ann_path),
        'bpm': float(bpm),
        'key': key,
        'camelot': camelot,
        'duration': dur,
        'exit_bar': exit_bar,
        'entry_bar': entry_bar,
        'segs': [(s, e, l) for s, e, l in segs],
    }

def sort_tracks(results):
    """
    Sort tracks by BPM + Camelot compatibility.
    Primary: BPM ascending.
    Secondary: starting from first track, prefer Camelot-compatible next track.
    """
    if len(results) <= 1:
        return results

    # Sort by BPM first
    sorted_by_bpm = sorted(results, key=lambda r: r['bpm'])
    
    # Greedy Camelot optimization: start from first track,
    # for each position pick the closest BPM track with best Camelot match
    ordered = [sorted_by_bpm[0]]
    remaining = sorted_by_bpm[1:]

    while remaining:
        last = ordered[-1]
        # Score each remaining track by Camelot + BPM proximity
        best_idx = 0
        best_score = float('inf')
        for i, r in enumerate(remaining):
            c_score = camelot_score(last['camelot'], r['camelot'])
            b_diff = abs(r['bpm'] - last['bpm'])
            # Weight: Camelot 3×, BPM diff 1×
            score = c_score * 3 + b_diff * 0.5
            if score < best_score:
                best_score = score
                best_idx = i
        ordered.append(remaining.pop(best_idx))

    return ordered

def build_config(tracks_info, wav_dir, ann_dir, output_path):
    """Write optimized config file."""
    with open(output_path, 'w') as f:
        f.write("# Optimized mix config — auto-generated by track_analyzer.py\n")
        f.write(f"# Tracks: {len(tracks_info)}\n")
        f.write(f"# BPM range: {tracks_info[0]['bpm']:.0f} - {tracks_info[-1]['bpm']:.0f}\n")
        f.write(f"# Camelot path: {' → '.join(t['camelot'] for t in tracks_info)}\n")
        f.write('WAV_DIR = "%s"\n' % wav_dir)
        f.write('ANN_DIR = "%s"\n' % ann_dir)
        f.write('TARGET_LUFS = -14.0\n')
        f.write('MAX_SHIFT_SEC = 0.05\n')
        f.write('TRACKS = [\n')
        for t in tracks_info:
            # Name with BPM + key for identification
            name = f"{t['name']}_{t['bpm']:.0f}BPM_{t['camelot']}"
            f.write(f'    ("{name}", "{t["wav"]}", "{t["ann"]}"),\n')
        f.write(']\n')
    print(f"  Config written → {output_path}")

def main():
    p = argparse.ArgumentParser(description="Pre-analyze tracks, sort by BPM+Camelot, build config")
    p.add_argument("--wav-dir", default=None)
    p.add_argument("--ann-dir", default=None)
    p.add_argument("--config", default=None, help="Existing config to load tracks from")
    p.add_argument("--out", default="optimized_config.py", help="Output config path")
    p.add_argument("--json", default=None, help="JSON output with full analysis")
    args = p.parse_args()

    wav_dir = args.wav_dir
    ann_dir = args.ann_dir
    tracks_to_analyze = []

    # Load from config or scan directories
    if args.config:
        spec = importlib.util.spec_from_file_location("cfg", args.config)
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        tracks_to_analyze = cfg.TRACKS
        if wav_dir is None:
            wav_dir = getattr(cfg, 'WAV_DIR', '.')
        if ann_dir is None:
            ann_dir = getattr(cfg, 'ANN_DIR', '.')
    elif wav_dir and ann_dir:
        # Scan directories
        for f in sorted(os.listdir(wav_dir)):
            if f.endswith('.wav'):
                name = f.replace('.wav', '')
                txt = f.replace('.wav', '.txt')
                if os.path.exists(os.path.join(ann_dir, txt)):
                    tracks_to_analyze.append((name, f, txt))

    if not tracks_to_analyze:
        print("No tracks to analyze")
        sys.exit(1)

    print(f"\\n{'=' * 55}")
    print("  Step 0: Track Pre-Analysis")
    print(f"{'=' * 55}\\n")

    results = []
    for name, wav, ann in tracks_to_analyze:
        r = analyze_track(
            os.path.join(wav_dir, wav),
            os.path.join(ann_dir, ann),
            name
        )
        results.append(r)

    print(f"\\n  Camelot path: {' → '.join(r['camelot'] for r in results)}")
    print(f"  BPM range: {results[0]['bpm']:.0f} - {results[-1]['bpm']:.0f}")
    print()

    # Sort
    ordered = sort_tracks(results)
    build_config(ordered, wav_dir, ann_dir, args.out)

    # JSON export
    if args.json:
        with open(args.json, 'w') as f:
            json.dump({'tracks': ordered}, f, indent=2)
        print(f"  JSON → {args.json}")

    print(f"\\n  Sorted order:")
    for i, t in enumerate(ordered):
        print(f"    {i+1}. {t['name']} — {t['bpm']:.0f} BPM — {t['camelot']} ({t['key']})")
    print(f"  Camelot score: sum={sum(camelot_score(ordered[i]['camelot'], ordered[i+1]['camelot']) for i in range(len(ordered)-1))}")

if __name__ == '__main__':
    main()