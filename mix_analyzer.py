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

def transition_windows(stamps, pad=5.0):
    """
    Окна (start,end) сек вокруг каждого перехода ±pad, слитые при пересечении.
    Чистая функция — задаёт, какие участки анализировать (не весь 40-мин микс).
    Так анализатор не виснет librosa на полном WAV.
    """
    wins = []
    for s in stamps:
        t = float(s.get("t", 0) if isinstance(s, dict) else 0)
        dur = float(s.get("dur", 0) if isinstance(s, dict) else 0)
        wins.append((max(0.0, t - pad), t + dur + pad))
    wins.sort()
    merged = []
    for w in wins:
        if merged and w[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], w[1]))
        else:
            merged.append(list(w))
    return [(round(a, 2), round(b, 2)) for a, b in merged]


def detect_volume_jumps(rms_env, hop_s, jump_db=6.0):
    """
    Резкие скачки громкости между соседними окнами RMS-огибающей.
    Возвращает [{t, jump_db}] для |Δ dB| > jump_db. Чистая функция.
    Ловит внезапные скачки уровня ПОСЛЕ сведения (новый трек «влетает» громче),
    которые усреднённый pre/post lufs_jump_db пропускает.
    """
    env = np.asarray(rms_env, dtype=float) + 1e-12
    out = []
    for i in range(1, len(env)):
        d = 20.0 * np.log10(env[i] / env[i - 1])
        if abs(d) > jump_db:
            out.append({"t": round(i * hop_s, 2), "jump_db": round(float(d), 1)})
    return out


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

    # --- Volume jumps (резкие скачки громкости в зоне перехода) ---
    vj_s = max(0, int((t_cf - 5) * sr))
    vj_e = min(len(mix_mono), int((t_cf + cf_dur + 5) * sr))
    vj_zone = mix_mono[vj_s:vj_e]
    vj_hop = int(0.2 * sr)
    if len(vj_zone) > vj_hop * 2:
        nvj = len(vj_zone) // vj_hop
        vj_env = np.array([
            np.sqrt(np.mean(vj_zone[i*vj_hop:(i+1)*vj_hop]**2)) for i in range(nvj)
        ])
        vjumps = detect_volume_jumps(vj_env, 0.2, jump_db=6.0)
        findings['volume_jumps'] = len(vjumps)
        findings['volume_jump_max_db'] = max((abs(j['jump_db']) for j in vjumps), default=0.0)
        findings['volume_jump_ok'] = len(vjumps) == 0
    else:
        findings['volume_jumps'] = 0
        findings['volume_jump_max_db'] = 0.0
        findings['volume_jump_ok'] = True

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
# Artefact detection (v2 detectors, restored)
# ============================================================

def detect_mix_artefacts(mono, sr, stamps=None, zone_pad=5.0):
    """
    v2 artefact detection with fixed thresholds.

    When zone_pad > 0 and stamps are provided, only scans segments around
    each transition (CF zone ± zone_pad seconds) instead of the full mix.
    This makes 90-min mix analysis as fast as 30-min.

    Detects: stutter, speed_glitch, transient_spike, hf_noise,
    spectral_discontinuity, onset_stability, rms_dip, harsh_endpoint,
    boundary_glitch, beat_irregularity, band_cancellation.
    """
    artefacts = []

    # ── Zone extraction: scan only around transitions ────────────────
    if zone_pad > 0 and stamps and len(stamps) > 0:
        mix_dur = len(mono) / sr
        for stamp in stamps:
            t_cf = float(stamp.get('t', 0))
            cf_dur = float(stamp.get('dur', 30))
            t_start = max(0.0, t_cf - zone_pad)
            t_end = min(mix_dur, t_cf + cf_dur + zone_pad)
            s = int(t_start * sr)
            e = int(t_end * sr)
            if e - s < sr // 2:
                continue
            zone = mono[s:e]
            zone_stamps = [stamp]  # single-transition stamp list for zone detectors
            zone_arts = _scan_zone(zone, sr, zone_stamps, t_start)
            artefacts.extend(zone_arts)
        return artefacts
    else:
        # Full mix scan (original behaviour)
        return _scan_zone(mono, sr, stamps or [], 0.0)


def _scan_zone(zone_audio, sr, zone_stamps, time_offset):
    """Run all detectors on a single audio zone, offset timestamps by time_offset."""
    artefacts = []
    Z = zone_audio  # shorthand
    z_len = len(Z)

    # ── 1. Stutter detection (difference-based, 20ms windows) ──────
    win_st = int(0.020 * sr)
    n_st = z_len // win_st
    consecutive_st = 0
    for i in range(1, n_st):
        a = Z[(i-1)*win_st:i*win_st]
        b = Z[i*win_st:(i+1)*win_st]
        if len(a) != len(b):
            continue
        a_rms = np.sqrt(np.mean(a**2)) + 1e-12
        if a_rms < 0.001:
            consecutive_st = 0
            continue
        diff_rms = np.sqrt(np.mean((a - b)**2))
        diff_ratio = diff_rms / a_rms
        if diff_ratio < 0.001:
            consecutive_st += 1
            if consecutive_st >= 3:
                artefacts.append({
                    't': i*win_st/sr + time_offset, 'type': 'stutter',
                    'severity': 'high' if diff_ratio < 0.0001 else 'mid',
                    'detail': f'diff_ratio={diff_ratio:.5f} dur={consecutive_st*20}ms'
                })
        else:
            consecutive_st = 0

    # ── 2. Speed glitch (20% threshold, 30s ramp zone) ───────────────
    hop_bpm = int(0.5 * sr)
    win_bpm = int(4 * sr)
    n_bpm = max(1, (z_len - win_bpm) // hop_bpm)
    lb = []
    for i in range(n_bpm):
        s = i * hop_bpm
        e = s + win_bpm
        if e > z_len:
            break
        seg = Z[s:e].astype(np.float32)
        if np.max(np.abs(seg)) < 0.001:
            lb.append(0)
            continue
        oe = librosa.onset.onset_strength(y=seg, sr=sr, hop_length=256)
        tb = librosa.beat.tempo(onset_envelope=oe, sr=sr, hop_length=256)
        lb.append(float(tb[0]) if len(tb) and tb[0] > 0 else 0)
    lb = np.array(lb)
    valid_bpm = lb[lb > 0]
    if len(valid_bpm) > 0:
        mb = np.median(valid_bpm)
        lb_clamped = np.where((lb > mb * 0.7) & (lb < mb * 1.3), lb, mb)
        for j in range(len(lb_clamped) - 1):
            if lb_clamped[j] <= 0 or lb_clamped[j+1] <= 0:
                continue
            jump_pct = abs(lb_clamped[j+1] - lb_clamped[j]) / mb
            if jump_pct > 0.20:
                t_glitch = j * hop_bpm / sr + time_offset
                if zone_stamps:
                    in_ramp = False
                    for s in zone_stamps:
                        ramp_start = s['t']
                        ramp_end = s['t'] + 30
                        if ramp_start <= t_glitch <= ramp_end:
                            in_ramp = True
                            break
                    if in_ramp:
                        continue
                artefacts.append({'t': t_glitch, 'type': 'speed_glitch',
                                  'severity': 'high' if jump_pct > 0.35 else 'mid',
                                  'detail': f'bpm_jump={lb[j]:.1f}→{lb[j+1]:.1f}'})

    # ── 3. Transient spike ───────────────────────────────────────────────
    hop_cr = int(0.1 * sr)
    n_cr = z_len // hop_cr
    crest = np.array([
        np.max(np.abs(Z[i*hop_cr:(i+1)*hop_cr])) /
        (np.sqrt(np.mean(Z[i*hop_cr:(i+1)*hop_cr]**2)) + 1e-12)
        for i in range(n_cr)
    ])
    cm = np.median(crest)
    for si in np.where(crest > cm * 5)[0]:
        artefacts.append({'t': si*hop_cr/sr + time_offset, 'type': 'transient_spike',
                          'severity': 'high' if crest[si] > cm * 10 else 'mid',
                          'detail': f'crest={crest[si]:.1f}x median'})

    # ── 4. HF noise (absolute + relative threshold) ──────────────────
    b_hp, a_hp = sig.butter(2, 16000.0 / (0.5 * sr), btype='high')
    hf = sig.filtfilt(b_hp, a_hp, Z)
    hop_hf = int(0.15 * sr)
    n_hf = z_len // hop_hf
    hf_e = np.array([
        np.sqrt(np.mean(hf[i*hop_hf:(i+1)*hop_hf]**2))
        for i in range(n_hf)
    ])
    hm = np.median(hf_e)
    abs_thresh = 0.01  # -40dBFS
    rel_thresh = hm * 10
    for h in range(len(hf_e)):
        if hf_e[h] > rel_thresh and hf_e[h] > abs_thresh:
            artefacts.append({'t': h*hop_hf/sr + time_offset, 'type': 'hf_noise',
                              'severity': 'high' if hf_e[h] > hm * 20 else 'mid',
                              'detail': f'hf_energy={hf_e[h]:.6f}'})

    # ── 5. Spectral discontinuity (12x median) ───────────────────────
    hop_sf = int(0.1 * sr)
    n_sf = max(1, z_len // hop_sf)
    sf_arr = np.zeros(n_sf - 1)
    for i in range(n_sf - 1):
        a = Z[i*hop_sf:(i+1)*hop_sf]
        b = Z[(i+1)*hop_sf:(i+2)*hop_sf]
        if len(a) < 2 or len(b) < 2:
            continue
        sa = np.abs(np.fft.rfft(a))
        sb = np.abs(np.fft.rfft(b))
        sf_arr[i] = np.sqrt(np.mean((sa - sb)**2)) / (np.mean(sa) + 1e-12)
    valid_sf = sf_arr[~np.isnan(sf_arr) & ~np.isinf(sf_arr)]
    if len(valid_sf) > 0:
        sm = np.median(valid_sf)
        thr = sm * 12
        for d in np.where(sf_arr > thr)[0]:
            artefacts.append({'t': d*hop_sf/sr + time_offset, 'type': 'spectral_discontinuity',
                              'severity': 'high' if sf_arr[d] > sm * 20 else 'mid',
                              'detail': f'flux={sf_arr[d]:.3f}x median'})

    # ── 6. Onset stability within crossfade ──────────────────────────────
    hop_oc = int(0.5 * sr)
    n_oc = max(1, z_len // hop_oc - 1)
    oe_full = librosa.onset.onset_strength(y=Z.astype(np.float32), sr=sr, hop_length=256)
    for i in range(n_oc - 1):
        t_oc = i * hop_oc / sr + time_offset
        in_cf = False
        if zone_stamps:
            for s in zone_stamps:
                cf_start = s['t'] - 3
                cf_end = s['t'] + s.get('dur', 30) + 3
                if cf_start <= t_oc <= cf_end:
                    in_cf = True
                    break
        if not in_cf:
            continue
        a = oe_full[i*hop_oc//256:(i+1)*hop_oc//256]
        b = oe_full[(i+1)*hop_oc//256:(i+2)*hop_oc//256]
        if len(a) < 3 or len(b) < 3:
            continue
        mn = min(len(a), len(b))
        corr = np.corrcoef(a[:mn], b[:mn])[0, 1]
        if corr < 0.3 and not (np.isnan(corr) or np.isinf(corr)):
            artefacts.append({'t': t_oc, 'type': 'onset_stability',
                              'severity': 'high' if corr < 0.15 else 'mid',
                              'detail': f'onset_corr={corr:.3f}'})

    # ── 7. RMS dip within crossfade ─────────────────────────────────
    hop_dip = int(0.1 * sr)
    n_dip = max(1, z_len // hop_dip)
    rms_dip = np.array([
        np.sqrt(np.mean(Z[i*hop_dip:(i+1)*hop_dip]**2))
        for i in range(n_dip)
    ])
    med_dip = np.median(rms_dip)
    for i in range(2, n_dip - 2):
        t_dip = i * hop_dip / sr + time_offset
        in_cf = False
        if zone_stamps:
            for s in zone_stamps:
                cf_start = s['t'] - 2
                cf_end = s['t'] + s.get('dur', 30) + 5
                if cf_start <= t_dip <= cf_end:
                    in_cf = True
                    break
        if not in_cf:
            continue
        local_med = np.median(rms_dip[max(0, i-2):i+3])
        if rms_dip[i] < med_dip * 0.5 and rms_dip[i] < local_med * 0.5:
            artefacts.append({'t': i*hop_dip/sr + time_offset, 'type': 'rms_dip',
                              'severity': 'high' if rms_dip[i] < med_dip * 0.3 else 'mid',
                              'detail': f'rms={rms_dip[i]:.4f} (med={med_dip:.4f})'})

    # ── 8. Harsh endpoint ────────────────────────────────────────────────
    if zone_stamps and len(valid_sf) > 0:
        sm = np.median(valid_sf)
        for s in zone_stamps:
            t_end = s['t'] + s.get('dur', 16 * 240.0 / 120)
            s_frame = int(t_end * sr)
            if s_frame + hop_sf * 2 >= z_len:
                continue
            pre = Z[s_frame - hop_sf:s_frame] if s_frame >= hop_sf else Z[:s_frame]
            post = Z[s_frame:s_frame + hop_sf]
            if len(pre) < 2 or len(post) < 2:
                continue
            sp = np.abs(np.fft.rfft(pre))
            sp2 = np.abs(np.fft.rfft(post))
            endpoint_flux = np.sqrt(np.mean((sp - sp2)**2)) / (np.mean(sp) + 1e-12)
            if endpoint_flux > sm * 3:
                artefacts.append({'t': t_end, 'type': 'harsh_endpoint',
                                  'severity': 'high' if endpoint_flux > sm * 5 else 'mid',
                                  'detail': f'endpoint_flux={endpoint_flux:.3f}x median'})

    # ── 8b. Blend→ramp boundary glitch ──────────────────────────────────
    if zone_stamps:
        hop_ms = int(0.001 * sr)
        for s in zone_stamps:
            t_end = s['t'] + s.get('dur', 16 * 240.0 / 120)
            s_frame = int(t_end * sr)
            win_pre = int(0.050 * sr)
            win_post = int(0.050 * sr)
            if s_frame - win_pre < 0 or s_frame + win_post >= z_len:
                continue
            boundary = Z[s_frame - win_pre:s_frame + win_post]
            rms_env = np.array([
                np.sqrt(np.mean(boundary[i:i+hop_ms]**2))
                for i in range(0, len(boundary) - hop_ms, hop_ms)
            ])
            if len(rms_env) < 10:
                continue
            rms_smooth = sig.medfilt(rms_env, kernel_size=3)
            center_idx = len(rms_smooth) // 2
            left_med = np.median(rms_smooth[max(0, center_idx-5):center_idx])
            right_med = np.median(rms_smooth[center_idx:min(len(rms_smooth), center_idx+5)])
            boundary_peak = np.max(rms_smooth[center_idx-2:center_idx+3])
            spike_ratio = boundary_peak / (max(left_med, right_med) + 1e-12)
            if spike_ratio > 1.8:
                artefacts.append({'t': t_end, 'type': 'boundary_glitch',
                                  'severity': 'high' if spike_ratio > 3.0 else 'mid',
                                  'detail': f'spike={spike_ratio:.1f}x at blend→ramp boundary'})
            env_grad = np.abs(np.diff(rms_smooth))
            max_grad = np.max(env_grad[center_idx-3:center_idx+3]) if center_idx+3 < len(env_grad) else 0
            med_grad = np.median(env_grad) + 1e-12
            if max_grad > med_grad * 5:
                artefacts.append({'t': t_end, 'type': 'boundary_glitch',
                                  'severity': 'mid',
                                  'detail': f'gradient_spike={max_grad/med_grad:.1f}x at boundary'})

    # ── 8c. Beat confusion (short-term arrhythmia in crossfade zone) ─────
    if zone_stamps:
        hop_ir = int(0.050 * sr)
        oe_full = librosa.onset.onset_strength(y=Z.astype(np.float32), sr=sr, hop_length=hop_ir)
        for s in zone_stamps:
            t_start_ir = s['t']
            t_dur_ir = s.get('dur', 30)
            s_frame = int(max(0, t_start_ir - 1) * sr / hop_ir)
            e_frame = int(min(t_start_ir + t_dur_ir + 2, z_len/sr) * sr / hop_ir)
            if e_frame - s_frame < 20:
                continue
            seg_oe = oe_full[s_frame:e_frame]
            if np.max(seg_oe) < 0.001:
                continue
            thr = max(np.median(seg_oe) * 3, np.mean(seg_oe) * 1.5)
            peaks, _ = sig.find_peaks(seg_oe, height=thr, distance=2)
            if len(peaks) < 4:
                continue
            peak_times = (s_frame + peaks) * hop_ir / sr
            iois = np.diff(peak_times)
            if len(iois) < 3:
                continue
            for i in range(len(iois)):
                local_med = float(np.median(iois[max(0,i-2):i+3]))
                if local_med < 0.05:
                    continue
                ratio = iois[i] / local_med
                if ratio > 2.0 or ratio < 0.4:
                    artefacts.append({
                        't': peak_times[i],
                        'type': 'beat_irregularity',
                        'severity': 'high' if ratio > 3.0 or ratio < 0.25 else 'mid',
                        'detail': f'ioi_ratio={ratio:.2f} ({iois[i]:.3f}s vs med {local_med:.3f}s)'
                    })

    # ── 9. Per-band phase cancellation ────────────────────────────────────
        if zone_stamps and len(zone_stamps) > 0:
            for s in zone_stamps:
                t_start = s['t']
                if t_start < 2.0:
                    continue
                t_dur = s.get('dur', 30)
                # Relative to zone offset
                s_frame = int((t_start - time_offset) * sr)
                e_frame = int(min(t_start - time_offset + t_dur, z_len/sr) * sr)
                if e_frame - s_frame < sr:
                    continue
                segment = Z[s_frame:e_frame]
                if len(segment) < sr:
                    continue
                n_fft = 1024
            hop = 256
            S = np.abs(librosa.stft(segment.astype(np.float32), n_fft=n_fft, hop_length=hop))
            freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
            bands = [(20, 60), (60, 120), (120, 500), (500, 2000), (2000, 8000)]
            for f_low, f_high in bands:
                mask = (freqs >= f_low) & (freqs <= f_high)
                if not np.any(mask):
                    continue
                band_mag = np.sqrt(np.mean(np.abs(S[mask])**2, axis=0))
                band_smooth = sig.medfilt(band_mag, kernel_size=5)
                local_med = np.array([
                    np.median(band_smooth[max(0, i-5):i+6])
                    for i in range(len(band_smooth))
                ])
                dip_ratio = band_smooth / (local_med + 1e-12)
                deep_dips = np.where(dip_ratio < 0.5)[0]
                if len(deep_dips) > 3:
                    groups = np.split(deep_dips, np.where(np.diff(deep_dips) > 2)[0] + 1)
                    for g in groups:
                        if len(g) < 3:
                            continue
                        artefacts.append({
                            't': t_start + g[0] * hop / sr,
                            'type': 'band_cancellation',
                            'severity': 'high' if np.min(dip_ratio[g]) < 0.3 else 'mid',
                            'detail': f'{f_low}-{f_high}Hz dip_ratio={np.min(dip_ratio[g]):.2f} dur={len(g)*hop/sr*1000:.0f}ms'
                        })

    return artefacts






def generate_feedback(transitions, mix_artefacts):
    """Generate automated fix recommendations from analysis results."""
    recs = []

    # Beat alignment feedback (v3 format)
    for tr in (transitions or []):
        if tr is None:
            continue
        cf = tr.get('cf_alignment')
        if cf:
            if cf.get('std_ms', 0) > 15:
                recs.append({'severity': 'high', 'parameter': 'warp_to_grid',
                             'suggestion': f"Beat jitter {cf['std_ms']:.1f}ms in CF zone — check warp precision"})
            if cf.get('p_score', 1.0) < 0.7:
                recs.append({'severity': 'high', 'parameter': 'onset_micro_align',
                             'suggestion': f"P-score {cf['p_score']:.0%} — beats drifting in crossfade"})
        if abs(tr.get('lufs_jump_db', 0)) > 6.0:
            recs.append({'severity': 'mid', 'parameter': 'norm_lufs',
                         'suggestion': f"LUFS jump {tr['lufs_jump_db']:+.1f}dB — check exit/entry section choice"})

    # Artefact-based feedback
    mx = mix_artefacts

    st = [a for a in mx if a['type'] == 'stutter']
    if len(st) > 3:
        recs.append({'severity': 'high', 'parameter': 'warp_to_grid(rate_threshold)',
                     'suggestion': f"Reduce rate_threshold ({len(st)} stutters)"})

    hf = [a for a in mx if a['type'] == 'hf_noise']
    if len(hf) > 5:
        recs.append({'severity': 'mid', 'parameter': 'ramp_to_native(ramp_sec)',
                     'suggestion': f"Increase RAMP_SEC ({len(hf)} HF events)"})

    sp = [a for a in mx if a['type'] == 'speed_glitch']
    if sp:
        recs.append({'severity': 'high', 'parameter': 'ramp_to_native(ramp_sec)',
                     'suggestion': 'Ramp too aggressive — increase RAMP_SEC or skip for <1 BPM diff'})

    rd = [a for a in mx if a['type'] == 'rms_dip']
    if rd:
        recs.append({'severity': 'high', 'parameter': 'build_cf_lr4(LR4_polarity)',
                     'suggestion': f'{len(rd)} RMS dip events — phase cancellation in crossfade'})

    bc = [a for a in mx if a['type'] == 'band_cancellation']
    if bc:
        recs.append({'severity': 'high', 'parameter': 'build_cf_lr4(phase_coherence)',
                     'suggestion': f'{len(bc)} band cancellation events — sub/mid phase issues'})

    bg = [a for a in mx if a['type'] == 'boundary_glitch']
    if bg:
        recs.append({'severity': 'high' if any(a['severity'] == 'high' for a in bg) else 'mid',
                     'parameter': 'build_cf_lr4(boundary_blend)',
                     'suggestion': f'{len(bg)} blend→ramp boundary glitch(es)'})

    bi = [a for a in mx if a['type'] == 'beat_irregularity']
    if bi:
        recs.append({'severity': 'high' if any(a['severity'] == 'high' for a in bi) else 'mid',
                     'parameter': 'warp_to_grid(pyrubberband_quality)',
                     'suggestion': f'{len(bi)} beat irregularity event(s) — garbled warp bar'})

    pk = [a for a in mx if a['type'] == 'transient_spike']
    if len(pk) > 2:
        recs.append({'severity': 'mid', 'parameter': 'mix_tracks(headroom_db)',
                     'suggestion': f"Increase headroom ({len(pk)} spikes)"})

    return recs


# ============================================================
# Full mix analysis
# ============================================================

def analyze_mix(mix_path, stamps, ann_dir=None, track_map=None, verbose=True, feedback=False, pad=5.0):
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
    result = {'results': results, 'issues': issues, 'offsets': offsets}

    # ── Artefact detection + feedback (v2 detectors) ────────────────
    if feedback:
        print(f"{'='*60}")
        print(f"  ARTEFACT DETECTION (v2 detectors)")
        print(f"{'='*60}\n")

        artefacts = detect_mix_artefacts(mono, sr, stamps, zone_pad=pad)
        if artefacts:
            by_type = {}
            for a in artefacts:
                by_type.setdefault(a['type'], []).append(a)
            for t, items in sorted(by_type.items()):
                high = sum(1 for a in items if a['severity'] == 'high')
                mid = sum(1 for a in items if a['severity'] == 'mid')
                print(f"  [{t}]  {len(items)} events ({high} high, {mid} mid)")
                for a in items[:3]:
                    print(f"    @ {_ts(a['t'])}  {a['detail']}")
                if len(items) > 3:
                    print(f"    ... and {len(items)-3} more")
            print()
        else:
            print(f"  ✓ No artefacts detected.\n")

        recs = generate_feedback(results, artefacts)
        if recs:
            print(f"  FEEDBACK — recommendations:")
            for r in recs:
                icon = "🔴" if r['severity'] == 'high' else "🟡"
                print(f"    {icon} [{r['parameter']}] {r['suggestion']}")
            print()
        else:
            print(f"  ✓ No recommendations.\n")

    return result


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
    p.add_argument("--feedback", action="store_true",
                   help="Run artefact detection + recommendations")
    p.add_argument("--pad", type=float, default=5.0,
                   help="Анализ только в зоне перехода ±pad сек (default 5; не виснет на длинных миксах)")
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
        feedback=args.feedback,
        pad=args.pad,
    )
    sys.exit(0 if not result['issues'] else 1)


if __name__ == "__main__":
    main()
