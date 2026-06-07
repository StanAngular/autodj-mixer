#!/usr/bin/env python3
"""
Mix Analyzer v3 -- per-transition beat alignment diagnostics.

Approach: source madmom annotations (pre-computed, accurate) + extrapolation
into the CF zone. Onset detection on mixed audio for actual beat comparison.
NEVER re-runs madmom on the mix -- uses pre-annotated source files only.

Core metric: master beat grid extrapolated forward vs actual onsets in CF zone.

Usage:
  python3 mix_analyzer.py --mix output.wav --stamps output.wav.npy
    --ann-dir ./ann --config mix_config.py

  python3 mix_analyzer.py --mix output.wav \
    --stamps-json '[{"t":154,"dur":31,"from":"InTheMoment","to":"Nomacita"}]' \
    --ann-dir ./ann --config mix_config.py
"""
import sys, os, argparse, json, importlib.util
import numpy as np
import soundfile as sf
import scipy.signal as sig
import librosa

SR = 44100
BEAT_DRIFT_WARN_MS = 20.0


def _ts(sec):
    m = int(sec // 60)
    s = sec % 60
    return f"{m:02d}:{s:05.2f}"


def _load_mix(path, sr=SR):
    """Load mix, return (mono float32, stereo, sr)."""
    data, file_sr = sf.read(path, always_2d=True, dtype="float32")
    if file_sr != sr:
        import subprocess, tempfile
        tmp = tempfile.mktemp(suffix=".wav")
        subprocess.run(["ffmpeg", "-y", "-i", path, "-ar", str(sr), "-ac", "2", tmp],
                       capture_output=True)
        data, _ = sf.read(tmp, always_2d=True, dtype="float32")
        os.unlink(tmp)
    return data.mean(axis=1), data, sr


def _load_dbeats(ann_path, sr=SR, downbeats_only=True):
    """
    Load madmom annotation file.
    downbeats_only=True  -> beat==1 only (bar level, for structure)
    downbeats_only=False -> all beats 1-4 (beat level, for alignment measurement)
    """
    beats = np.loadtxt(ann_path)
    if beats.ndim == 1:
        beats = beats.reshape(1, -1)
    # Format: seconds (<100) or samples (>1000)
    is_secs = beats[0, 0] < 100
    if downbeats_only:
        sel = beats[np.array([round(r[1]) == 1 for r in beats])]
    else:
        sel = beats  # all beats
    if is_secs:
        return np.array([int(r[0] * sr) for r in sel], dtype=int)
    else:
        return np.array([int(r[0]) for r in sel], dtype=int)


def _calc_bpm(db, sr=SR):
    """BPM from bar-level downbeat positions."""
    if len(db) < 4:
        return 120.0
    iv = np.diff(db.astype(float)) / sr
    iv = iv[iv > 0.3]
    if not len(iv):
        return 120.0
    p25, p75 = np.percentile(iv, [25, 75])
    ok = iv[(iv >= p25 - 1.5*(p75-p25)) & (iv <= p75 + 1.5*(p75-p25))]
    return 4 * 60.0 / np.mean(ok) if len(ok) else 120.0


# ============================================================
# Beat grid from source annotations
# ============================================================

def build_beat_grid(db_samples, sr=SR):
    """
    Fit a steady beat grid from madmom downbeat positions.
    db_samples: bar-level positions in samples (beat==1 only).

    Returns dict with:
      period_samp: bar period in samples
      bpm: detected BPM
      jitter_ms: std of residuals vs fitted grid
    """
    if len(db_samples) < 4:
        return None
    iois = np.diff(db_samples.astype(float))
    med = float(np.median(iois))
    if med <= 0:
        return None
    # Reject outliers > 30% from median
    good = iois[(iois > med*0.7) & (iois < med*1.3)]
    if len(good) < 2:
        good = iois
    period = float(np.mean(good))
    # Beat-level period (not bar-level): BPM = 60 / period_s
    bpm = 60.0 / (period / sr)

    # Grid residuals
    residuals = []
    for i, d in enumerate(db_samples):
        expected = db_samples[0] + round((d - db_samples[0]) / period) * period
        residuals.append((d - expected) / sr * 1000)
    jitter = float(np.std(residuals))

    return {
        'period_samp': period,
        'period_s': period / sr,
        'bpm': bpm,
        'jitter_ms': jitter,
        'phase_samp': float(db_samples[0]),
        'n_bars': len(db_samples),
    }


def extrapolate_grid(grid, t_start_s, t_end_s, sr=SR):
    """
    Generate expected bar positions from t_start to t_end (seconds)
    based on fitted grid.
    Returns array of beat times in seconds.
    """
    period_s = grid['period_s']
    phase_s = grid['phase_samp'] / sr
    n_start = int(np.ceil((t_start_s - phase_s) / period_s))
    n_end = int(np.floor((t_end_s - phase_s) / period_s))
    return np.array([phase_s + n * period_s for n in range(n_start, n_end + 1)])


# ============================================================
# Onset detection on mix segment (for actual beat comparison)
# ============================================================

def detect_onsets_in_segment(mix_mono, t_start_s, t_end_s, sr=SR, hop=256):
    """
    Detect onset times (seconds, absolute in mix) in a mix segment.
    Uses librosa onset detection -- acceptable for comparison (not primary tracking).
    Returns sorted array of onset times in seconds.
    """
    s = max(0, int(t_start_s * sr))
    e = min(len(mix_mono), int(t_end_s * sr))
    if e - s < sr // 4:
        return np.array([])
    segment = mix_mono[s:e].astype(np.float32)
    env = librosa.onset.onset_strength(y=segment, sr=sr, hop_length=hop)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop)
    if len(frames) == 0:
        return np.array([])
    times = frames * hop / sr + t_start_s
    return times


def compare_grid_to_onsets(expected_beats_s, actual_onsets_s, tolerance_frac=0.25):
    """
    Compare expected beat grid to actual onsets. Returns:
    - mean/std offset (ms)
    - CMLc: longest continuous correctly-aligned segment (% of total)
    - Cemgil: Gaussian-weighted accuracy score (0-1)

    tolerance_frac: 25% of beat period (madmom standard P-score tolerance).
    """
    if len(expected_beats_s) < 2 or len(actual_onsets_s) < 3:
        return None
    period = float(np.median(np.diff(expected_beats_s)))
    tol = period * tolerance_frac

    # Match each expected beat to closest onset
    beat_offsets_ms = []   # offset per expected beat (None if no match)
    beat_correct = []      # True/False per expected beat
    cemgil_scores = []     # Gaussian weight per beat
    sigma_ms = tol * 1000 * 0.8  # Gaussian sigma ~80% of tolerance window

    for eb in expected_beats_s:
        diffs = actual_onsets_s - eb
        idx = int(np.argmin(np.abs(diffs)))
        offset = float(diffs[idx])
        offset_ms = offset * 1000

        # Cemgil: Gaussian weight regardless of tolerance
        cemgil_scores.append(float(np.exp(-0.5 * (offset_ms / sigma_ms)**2)))

        if abs(offset) < tol:
            beat_offsets_ms.append(offset_ms)
            beat_correct.append(True)
        else:
            beat_correct.append(False)

    if len(beat_offsets_ms) < 3:
        return None

    arr = np.array(beat_offsets_ms)

    # --- CMLc: longest continuous correct segment ---
    max_run = 0
    cur_run = 0
    for c in beat_correct:
        if c:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 0
    cmlc = max_run / len(beat_correct) if beat_correct else 0.0

    # --- Cemgil score: mean Gaussian weight ---
    cemgil = float(np.mean(cemgil_scores)) if cemgil_scores else 0.0

    # --- P-score: fraction of beats within tolerance ---
    p_score = sum(beat_correct) / len(beat_correct) if beat_correct else 0.0

    return {
        'mean_ms': float(np.mean(arr)),
        'median_ms': float(np.median(arr)),
        'std_ms': float(np.std(arr)),
        'max_abs_ms': float(np.max(np.abs(arr))),
        'n_matched': len(arr),
        'n_expected': len(expected_beats_s),
        'p_score': round(p_score, 3),
        'cmlc': round(cmlc, 3),
        'cemgil': round(cemgil, 3),
        'flagged': abs(float(np.mean(arr))) > BEAT_DRIFT_WARN_MS,
    }


# ============================================================
# Per-transition analysis
# ============================================================

def analyze_transition(mix_mono, sr, t_cf, cf_dur, master_db, slave_db,
                        master_mix_offset=0.0, label=""):
    """
    Per-transition analysis using source madmom annotations.

    master_db: downbeat sample positions for master track (from .txt file)
    slave_db:  downbeat sample positions for slave track
    master_mix_offset: where master track starts in the mix (seconds).
                       Used to translate source positions to mix positions.

    Algorithm:
    1. Find master downbeats in pre-CF zone (mix timeline)
    2. Fit beat grid
    3. Extrapolate into CF zone
    4. Detect onsets in CF zone (mix audio)
    5. Compare expected vs actual → offset_ms
    6. LUFS continuity, phase cancellation
    """
    mix_dur = len(mix_mono) / sr
    findings = {'label': label, 't_cf': t_cf, 'cf_dur': cf_dur}

    # --- Master beat grid from annotations ---
    if master_db is not None and len(master_db) > 4:
        # master_db = ALL beats (1-4) from madmom annotations, in source samples
        # Convert source positions to mix timeline (add offset where master started)
        master_beats_mix_s = master_db / sr + master_mix_offset
        # Only beats before CF
        pre_beats = master_beats_mix_s[master_beats_mix_s < t_cf]
        # Use last 32 beats (8 bars) before CF for grid fitting
        pre_beats = pre_beats[-32:] if len(pre_beats) > 32 else pre_beats
        grid = build_beat_grid((pre_beats * sr).astype(int), sr) if len(pre_beats) >= 8 else None
    else:
        grid = None

    if grid:
        findings['master_grid'] = {
            'bpm': round(grid['bpm'], 1),
            'period_ms': round(grid['period_s'] * 1000, 1),
            'jitter_ms': round(grid['jitter_ms'], 1),
            'n_bars': grid['n_bars'],
        }

        # Extrapolate into CF zone
        expected_cf = extrapolate_grid(grid, t_cf, t_cf + cf_dur, sr)

        # Detect onsets in CF zone
        cf_onsets = detect_onsets_in_segment(mix_mono, t_cf, t_cf + cf_dur, sr)

        # Compare
        cf_cmp = compare_grid_to_onsets(expected_cf, cf_onsets)
        findings['cf_alignment'] = cf_cmp

        if cf_cmp:
            findings['beat_offset_ms'] = round(cf_cmp['mean_ms'], 1)
            findings['beat_ok'] = not cf_cmp['flagged']
        else:
            findings['beat_offset_ms'] = None
            findings['beat_ok'] = True

        # Post-CF: onsets in first 8s after CF vs extrapolated grid
        post_expected = extrapolate_grid(grid, t_cf + cf_dur, t_cf + cf_dur + 8.0, sr)
        post_onsets = detect_onsets_in_segment(mix_mono, t_cf + cf_dur, t_cf + cf_dur + 8.0, sr)
        post_cmp = compare_grid_to_onsets(post_expected, post_onsets)
        findings['post_alignment'] = post_cmp
    else:
        findings['master_grid'] = None
        findings['beat_offset_ms'] = None
        findings['beat_ok'] = True
        findings['cf_alignment'] = None
        findings['post_alignment'] = None

    # --- LUFS continuity ---
    pre_s = max(0, int((t_cf - 3) * sr))
    pre_e = int(t_cf * sr)
    post_s = int((t_cf + cf_dur) * sr)
    post_e = min(len(mix_mono), int((t_cf + cf_dur + 3) * sr))

    pre_rms = np.sqrt(np.mean(mix_mono[pre_s:pre_e]**2)) + 1e-12 if pre_e > pre_s else 1e-12
    post_rms = np.sqrt(np.mean(mix_mono[post_s:post_e]**2)) + 1e-12 if post_e > post_s else 1e-12
    lufs_db = 20 * np.log10(post_rms / pre_rms)
    findings['lufs_jump_db'] = round(float(lufs_db), 2)
    # Note: QUIET exit -> ACTIVE slave = expected jump. Flag only >6dB as likely problem
    findings['lufs_ok'] = abs(lufs_db) < 6.0

    # --- Phase cancellation in CF zone ---
    cf_s = int(t_cf * sr)
    cf_e = int((t_cf + cf_dur) * sr)
    cf_audio = mix_mono[cf_s:cf_e]
    if len(cf_audio) > sr:
        hop = int(0.1 * sr)
        n = len(cf_audio) // hop
        rms_env = np.array([
            np.sqrt(np.mean(cf_audio[i*hop:(i+1)*hop]**2))
            for i in range(n)
        ])
        med = np.median(rms_env)
        dips = int(np.sum(rms_env < med * 0.4))
        findings['phase_dips'] = dips
        findings['phase_ok'] = dips <= 3
    else:
        findings['phase_dips'] = 0
        findings['phase_ok'] = True

    # --- Spectral centroid shift ---
    pre_audio = mix_mono[pre_s:pre_e]
    post_audio = mix_mono[post_s:post_e]
    if len(pre_audio) > sr//4 and len(post_audio) > sr//4:
        sc_pre = float(librosa.feature.spectral_centroid(y=pre_audio, sr=sr)[0].mean())
        sc_post = float(librosa.feature.spectral_centroid(y=post_audio, sr=sr)[0].mean())
        findings['centroid_shift_hz'] = round(sc_post - sc_pre)
    else:
        findings['centroid_shift_hz'] = 0

    return findings


# ============================================================
# Full mix analysis
# ============================================================

def analyze_mix(mix_path, stamps, ann_dir=None, track_map=None, verbose=True):
    """
    Analyze each transition independently.

    stamps: list of dicts {t, dur, from, to}
    ann_dir: directory with .txt madmom annotation files
    track_map: dict {track_label -> (wav_file, ann_file)} from config
    """
    print(f"\n{'='*60}")
    print(f"  Mix Analyzer v3 -- Madmom-based Per-Transition Analysis")
    print(f"{'='*60}\n")

    mono, stereo, sr = _load_mix(mix_path)
    mix_dur = len(mono) / sr
    print(f"  Mix: {os.path.basename(mix_path)}")
    print(f"  Duration: {mix_dur/60:.1f} min | SR={sr}")
    print(f"  Transitions: {len(stamps)}")
    if ann_dir:
        print(f"  Annotations: {ann_dir}\n")
    else:
        print(f"  Note: no ann_dir -- beat grid analysis skipped\n")

    # Preload annotations (all beats for alignment, downbeats for structure)
    ann_cache = {}   # label -> all-beat positions (samples)
    if ann_dir and track_map:
        for label, (wav_f, ann_f) in track_map.items():
            ann_path = os.path.join(ann_dir, ann_f)
            if os.path.exists(ann_path):
                try:
                    ann_cache[label] = _load_dbeats(ann_path, sr, downbeats_only=False)
                except Exception:
                    ann_cache[label] = None

    results = []
    issues = []

    for i, stamp in enumerate(stamps):
        t_cf = float(stamp.get('t', 0))
        cf_dur = float(stamp.get('dur', 30))
        frm = stamp.get('from', '?')
        to = stamp.get('to', '?')
        label = f"{frm} -> {to}"
        # master_mix_offset: where master track plays from in the mix
        # Not always known from stamps alone; default to 0
        master_off = float(stamp.get('master_mix_offset', 0.0))

        if verbose:
            print(f"  [{i+1}/{len(stamps)}] {label}  @{_ts(t_cf)}")

        master_db = ann_cache.get(frm)
        slave_db = ann_cache.get(to)

        finding = analyze_transition(
            mono, sr, t_cf, cf_dur,
            master_db=master_db,
            slave_db=slave_db,
            master_mix_offset=master_off,
            label=label,
        )
        results.append(finding)

        if verbose:
            grid = finding.get('master_grid')
            if grid:
                print(f"        Master grid:  {grid['bpm']} BPM  "
                      f"jitter={grid['jitter_ms']}ms  ({grid['n_bars']} bars)")
            else:
                print(f"        Master grid:  N/A (no annotations)")

            off = finding.get('beat_offset_ms')
            if off is not None:
                flag = " ⚠" if not finding['beat_ok'] else " ✓"
                print(f"        Beat offset:  {off:+.1f}ms{flag}")
                cf_a = finding.get('cf_alignment')
                if cf_a:
                    print(f"          CF zone:  mean={cf_a['mean_ms']:+.1f}ms  "
                          f"std={cf_a['std_ms']:.1f}ms  "
                          f"({cf_a['n_matched']}/{cf_a['n_expected']} beats)")
                    print(f"          Scores:   P={cf_a['p_score']:.0%}  "
                          f"CMLc={cf_a['cmlc']:.0%}  "
                          f"Cemgil={cf_a['cemgil']:.3f}")
                post_a = finding.get('post_alignment')
                if post_a:
                    print(f"          Post-CF:  mean={post_a['mean_ms']:+.1f}ms  "
                          f"std={post_a['std_ms']:.1f}ms")
            else:
                print(f"        Beat offset:  unmeasurable")

            ldb = finding['lufs_jump_db']
            flag = " ⚠" if not finding['lufs_ok'] else " ✓"
            print(f"        LUFS jump:    {ldb:+.1f}dB{flag}  "
                  f"(note: QUIET→ACTIVE up to +6dB expected)")

            dips = finding['phase_dips']
            if dips > 3:
                print(f"        Phase cancel: {dips} dips ⚠")
            print()

        # Collect issues
        off = finding.get('beat_offset_ms')
        if off is not None and not finding['beat_ok']:
            issues.append({'n': i+1, 'label': label, 'type': 'beat',
                           'detail': f"{off:+.1f}ms"})
        if not finding['lufs_ok']:
            issues.append({'n': i+1, 'label': label, 'type': 'lufs',
                           'detail': f"{finding['lufs_jump_db']:+.1f}dB"})
        if not finding['phase_ok']:
            issues.append({'n': i+1, 'label': label, 'type': 'phase',
                           'detail': f"{finding['phase_dips']} dips"})

    # --- Summary ---
    print(f"{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}\n")

    offsets = [r['beat_offset_ms'] for r in results if r.get('beat_offset_ms') is not None]
    if offsets:
        ok_n = sum(1 for o in offsets if abs(o) <= BEAT_DRIFT_WARN_MS)
        print(f"  Beat alignment ({len(offsets)} transitions):")
        print(f"    Max |offset|: {np.max(np.abs(offsets)):.1f}ms")
        print(f"    Mean offset:  {np.mean(offsets):+.1f}ms")
        print(f"    Pass (<{BEAT_DRIFT_WARN_MS:.0f}ms): {ok_n}/{len(offsets)}")

        # CMLc and Cemgil averages
        cmlc_vals = [r['cf_alignment']['cmlc'] for r in results
                     if r.get('cf_alignment') and 'cmlc' in r['cf_alignment']]
        cemgil_vals = [r['cf_alignment']['cemgil'] for r in results
                       if r.get('cf_alignment') and 'cemgil' in r['cf_alignment']]
        p_vals = [r['cf_alignment']['p_score'] for r in results
                  if r.get('cf_alignment') and 'p_score' in r['cf_alignment']]
        if cmlc_vals:
            print(f"\n  Quality scores (mean across transitions):")
            print(f"    P-score:  {np.mean(p_vals):.0%}  (beats within 25% tolerance)")
            print(f"    CMLc:     {np.mean(cmlc_vals):.0%}  (longest correct segment)")
            print(f"    Cemgil:   {np.mean(cemgil_vals):.3f}  (Gaussian accuracy 0-1)")
    else:
        print(f"  Beat alignment: N/A (provide --ann-dir and --config)")

    lufs = [abs(r['lufs_jump_db']) for r in results]
    ok_lufs = sum(1 for j in lufs if j < 6.0)
    print(f"\n  LUFS continuity: {ok_lufs}/{len(lufs)} pass (<6dB)")

    ok_phase = sum(1 for r in results if r['phase_ok'])
    print(f"  Phase cancel:    {ok_phase}/{len(results)} pass (≤3 dips)")

    if issues:
        print(f"\n  ⚠ Issues ({len(issues)}):")
        for iss in issues:
            print(f"    [{iss['n']}] {iss['label']}: "
                  f"{iss['type']} {iss['detail']}")
    else:
        print(f"\n  ✓ All transitions pass.")

    print()
    return {'results': results, 'issues': issues, 'offsets': offsets}


# ============================================================
# CLI
# ============================================================

def main():
    p = argparse.ArgumentParser(description="Mix Analyzer v3")
    p.add_argument("--mix", required=True)
    p.add_argument("--stamps", help=".npy file from smart_mixer")
    p.add_argument("--stamps-json", help="JSON string or file path")
    p.add_argument("--config", help="mix_config.py path")
    p.add_argument("--ann-dir", help="Annotation .txt directory")
    p.add_argument("--wav-dir", help="Source WAV directory (optional)")
    p.add_argument("--threshold", type=float, default=20.0,
                   help="Beat drift warning ms (default 20)")
    args = p.parse_args()

    global BEAT_DRIFT_WARN_MS
    BEAT_DRIFT_WARN_MS = args.threshold

    # Load stamps
    stamps = []
    if args.stamps and os.path.exists(args.stamps):
        data = np.load(args.stamps, allow_pickle=True)
        stamps = list(data.item() if data.ndim == 0 else data)
        if isinstance(stamps, dict):
            stamps = stamps.get('stamps', [])
    elif args.stamps_json:
        src = args.stamps_json
        stamps = json.load(open(src)) if os.path.isfile(src) else json.loads(src)

    if not stamps:
        print("ERROR: no stamps. Use --stamps or --stamps-json", file=sys.stderr)
        sys.exit(1)

    # Load config for track_map
    track_map = None
    ann_dir = args.ann_dir
    if args.config and os.path.exists(args.config):
        spec = importlib.util.spec_from_file_location("cfg", args.config)
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        track_map = {name: (wav, ann) for name, wav, ann in cfg.TRACKS}
        if not ann_dir:
            ann_dir = getattr(cfg, 'ANN_DIR', None)

    result = analyze_mix(
        args.mix, stamps,
        ann_dir=ann_dir,
        track_map=track_map,
        verbose=True,
    )
    sys.exit(0 if not result['issues'] else 1)


if __name__ == "__main__":
    main()
