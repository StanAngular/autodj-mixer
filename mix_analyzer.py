#!/usr/bin/env python3
"""
Mix Analyzer v2 — comprehensive post-mix quality diagnostics.

v2 changes:
  • Fixed false-positive thresholds (HF noise, stutter, speed glitch, spectral disc)
  • Beat drift measurement per bar via onset cross-correlation with annotations
  • Source integrity check — solo sections before/after transition vs source audio
  • Per-band phase cancellation detection within crossfade zones
  • Cleaner output with meaningful event types

Usage:
  python3 mix_analyzer.py --mix /tmp/mix.mp3 --wav-dir ./wav --ann-dir ./annotations
  python3 mix_analyzer.py --mix /tmp/mix.mp3 --config mix_config.py
  python3 mix_analyzer.py --mix /tmp/mix.mp3 --config mix_config.py --feedback
"""
import sys, os, time, argparse, importlib.util
import numpy as np
import soundfile as sf
import scipy.signal as sig
import librosa
import pyloudnorm as pyln

SR = 44100
TARGET_LUFS = -14.0

def _ts(sec):
    m = int(sec // 60)
    s = sec % 60
    return f"{m:02d}:{s:05.2f}"

def _load_wav(path, sr=SR):
    data, file_sr = sf.read(path, always_2d=True)
    if data.shape[1] == 1:
        data = np.hstack([data, data])
    if file_sr != sr:
        import subprocess
        tmp = f"/tmp/_ma_{os.path.basename(path)}.wav"
        subprocess.run(["ffmpeg", "-y", "-i", path, "-ar", str(sr), "-ac", "2", tmp], capture_output=True)
        data, _ = sf.read(tmp, always_2d=True)
        os.unlink(tmp)
    return data.astype("float32")

def _load_dbeats(ann_path, sr=SR):
    beats = np.loadtxt(ann_path)
    return np.array([int(r[0] * sr) for r in beats if round(r[1]) == 1], dtype=int)

def _calc_bpm(db, sr=SR):
    if len(db) < 4:
        return 120.0
    iv = np.diff(db.astype(float)) / sr
    iv = iv[iv > 0.3]
    if not len(iv):
        return 120.0
    p25 = np.percentile(iv, 25)
    r = iv[iv <= p25 * 1.3]
    if not len(r):
        r = iv
    bpm = 4 * 60.0 / np.mean(r)
    return bpm * 2 if bpm < 90 else bpm

def _fix_ht(db, bpm):
    if bpm >= 90:
        return db, bpm
    new = []
    for i in range(len(db) - 1):
        new.append(db[i])
        new.append((db[i] + db[i+1]) // 2)
    new.append(db[-1])
    return np.array(new, dtype=int), bpm * 2

CAMELOT = {
    'C maj':'8B','C# maj':'3B','D maj':'10B','D# maj':'5B','E maj':'12B',
    'F maj':'7B','F# maj':'2B','G maj':'9B','G# maj':'4B','A maj':'11B',
    'A# maj':'6B','B maj':'1B',
    'C min':'5A','C# min':'12A','D min':'7A','D# min':'2A','E min':'9A',
    'F min':'4A','F# min':'11A','G min':'6A','G# min':'1A','A min':'8A',
    'A# min':'3A','B min':'10A',
}
KEYS_LABELS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
MAJ_PROFILE = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
MIN_PROFILE = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])

def detect_key(audio_mono, sr=SR):
    chroma = librosa.feature.chroma_cqt(y=audio_mono.astype(np.float32), sr=sr)
    profile = chroma.mean(axis=1)
    best_corr = -1.0; best_key = "?"
    for shift in range(12):
        rolled = np.roll(profile, -shift)
        cm = np.corrcoef(rolled, MAJ_PROFILE)[0, 1]
        cn = np.corrcoef(rolled, MIN_PROFILE)[0, 1]
        if cm > best_corr: best_corr = cm; best_key = f"{KEYS_LABELS[shift]} maj"
        if cn > best_corr: best_corr = cn; best_key = f"{KEYS_LABELS[shift]} min"
    return best_key, best_corr

def key_compatibility(k1, k2):
    c1 = CAMELOT.get(k1); c2 = CAMELOT.get(k2)
    if not c1 or not c2: return 0.5, "unknown"
    n1, t1 = int(c1[:-1]), c1[-1]; n2, t2 = int(c2[:-1]), c2[-1]
    if c1 == c2: return 1.0, f"identical ({c1})"
    if n1 == n2 and t1 != t2: return 0.8, f"relative ({c1}↔{c2})"
    if t1 == t2 and abs(n1 - n2) in (1, 11): return 0.9, f"adjacent ({c1}→{c2})"
    return 0.3, f"distant ({c1}→{c2})"

# ── Source analysis ──────────────────────────────────────────────────────────

def analyze_source_tracks(tracks, wav_dir, ann_dir):
    """Analyze source tracks, returning info + audio arrays for later comparison."""
    results = {}
    audio_cache = {}
    for name, wav_file, ann_file in tracks:
        info = {'name': name}
        audio = _load_wav(os.path.join(wav_dir, wav_file), SR)
        mono = audio.mean(1).astype(np.float32)
        ann_path = os.path.join(ann_dir, ann_file)
        if os.path.exists(ann_path):
            db = _load_dbeats(ann_path, SR)
            raw = _calc_bpm(db, SR)
            db, bpm = _fix_ht(db, raw)
            info['bpm'] = bpm; info['dbeats'] = db
        else:
            info['bpm'] = 0; info['dbeats'] = np.array([], dtype=int)
        key, conf = detect_key(mono, SR)
        info['key'] = key; info['key_confidence'] = conf
        info['dur_sec'] = len(mono) / SR
        info['source_artefacts'] = _scan_source_artefacts(mono, SR)
        results[name] = info
        audio_cache[name] = audio  # keep for later comparison
    return results, audio_cache

def _scan_source_artefacts(mono, sr):
    """Scan source tracks for pre-existing issues."""
    artefacts = []
    hop = int(0.05 * sr)
    n_w = len(mono) // hop
    crest = np.zeros(n_w)
    for i in range(n_w):
        seg = mono[i*hop:(i+1)*hop]
        rms = np.sqrt(np.mean(seg**2)) + 1e-12
        crest[i] = np.max(np.abs(seg)) / rms
    cm = np.median(crest)
    for s in np.where(crest > cm * 5)[0]:
        artefacts.append({'t': s*hop/sr, 'type': 'transient_spike',
                          'severity': 'high' if crest[s]>cm*10 else 'mid',
                          'detail': f'crest={crest[s]:.1f}x median'})
    rms_win = int(0.01 * sr)
    n_r = len(mono) // rms_win
    rms_arr = np.array([np.sqrt(np.mean(mono[i*rms_win:(i+1)*rms_win]**2)) for i in range(n_r)])
    silent = np.where(rms_arr < 0.0003)[0]
    if len(silent):
        for g in np.split(silent, np.where(np.diff(silent)>1)[0]+1):
            if len(g) > 5:
                artefacts.append({'t': g[0]*rms_win/sr, 'type': 'dropout',
                                  'severity': 'high' if len(g)>50 else 'mid',
                                  'detail': f'silence {len(g)*10}ms'})
    b_hp, a_hp = sig.butter(2, 15000.0/(0.5*sr), btype='high')
    hf = sig.filtfilt(b_hp, a_hp, mono)
    hf_win = int(0.1 * sr)
    n_h = len(mono) // hf_win
    hf_e = np.array([np.sqrt(np.mean(hf[i*hf_win:(i+1)*hf_win]**2)) for i in range(n_h)])
    hm = np.median(hf_e)
    for h in np.where(hf_e > hm * 8)[0]:
        artefacts.append({'t': h*hf_win/sr, 'type': 'hf_noise',
                          'severity': 'high' if hf_e[h]>hm*15 else 'mid',
                          'detail': f'hf_energy={hf_e[h]:.6f}'})
    return artefacts

# ── Beat drift measurement ──────────────────────────────────────────────────

def _measure_beat_drift(mix_mono, sr, master_db, slave_db, t_start, dur,
                         hop_onset=256):
    """
    Measure beat drift from the PRE-crossfade section (master-only).

    Instead of cross-correlating inside the crossfade (where both tracks play and
    onset envelopes are unreliable), this measures the inter-beat-interval (IBI)
    consistency in the 4 bars before the transition and compares it to the
    expected IBI from the master's annotations.

    If the mix shows inconsistent IBI compared to the source, the mixer's
    warp_to_grid is introducing temporal jitter.
    """
    # Analyze 4 bars BEFORE the crossfade (master only section)
    pre_start = max(0, t_start - 8)
    pre_end = max(0, t_start - 0.5)  # leave 0.5s gap before transition
    if pre_end - pre_start < 3:
        return None

    s_frame = int(pre_start * sr)
    e_frame = int(pre_end * sr)
    pre_zone = mix_mono[s_frame:e_frame]
    if len(pre_zone) < sr:
        return None

    # Detect onset positions in the pre-crossfade zone
    onset_env = librosa.onset.onset_strength(y=pre_zone.astype(np.float32), sr=sr, hop_length=hop_onset)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=hop_onset)
    if len(onsets) < 4:
        return None

    onset_times = onsets * hop_onset / sr  # seconds relative to pre_zone start

    # Compute inter-onset-intervals (IOIs)
    iois = np.diff(onset_times)

    # Compute expected IOI from master BPM
    m_bpm = _calc_bpm(master_db, sr)
    if m_bpm <= 0:
        return None
    expected_ioi = 60.0 / m_bpm  # one beat interval at 4/4

    # Filter IOIs: keep only those close to expected beat interval or multiple
    # (onsets may detect 8th notes → IOI = expected/2, or full beats → IOI = expected)
    # Accept IOIs between 0.7*expected and 1.4*expected (quarter notes)
    # and also 1.7*expected to 2.4*expected (half notes)
    mask = ((iois > expected_ioi * 0.7) & (iois < expected_ioi * 1.4)) | \
           ((iois > expected_ioi * 1.7) & (iois < expected_ioi * 2.4))
    valid_iois = iois[mask]
    if len(valid_iois) < 3:
        # Fallback: accept wider range
        valid_iois = iois[(iois > expected_ioi * 0.3) & (iois < expected_ioi * 2.5)]
        if len(valid_iois) < 3:
            return None

    # Normalize IOIs to the beat level: if the mean IOI is ~2x expected, it's half-notes
    # If it's ~0.5x expected, it's 8th notes. Normalize to the closest multiple.
    raw_mean = float(np.mean(valid_iois))
    best_ratio = raw_mean / expected_ioi
    if best_ratio > 1.5:
        # Half notes or larger — divide by the nearest integer factor
        factor = round(best_ratio)
        norm_iois = valid_iois / factor
    elif best_ratio < 0.7:
        # 8th/16th notes — multiply by the nearest integer factor
        factor = round(1.0 / best_ratio)
        norm_iois = valid_iois * factor
    else:
        norm_iois = valid_iois

    # Now use normalized IOIs
    ioi_mean = float(np.mean(norm_iois))
    ioi_std = float(np.std(norm_iois))
    ioi_cv = ioi_std / (ioi_mean + 1e-12)  # coefficient of variation

    # How much does the observed IBI deviate from expected?
    ioi_error_pct = float(abs(ioi_mean - expected_ioi) / expected_ioi * 100)

    # Drift per single bar: difference between observed and expected IBI
    drift_per_bar_ms = float((ioi_mean - expected_ioi) * 1000)
    # Cumulative drift over analyzed section
    cumulative_drift_ms = float(np.sum(norm_iois - expected_ioi) * 1000)
    # Max single-bar drift (worst individual interval deviation)
    bar_drifts_ms = np.abs(norm_iois - expected_ioi) * 1000
    max_single_drift_ms = float(np.max(bar_drifts_ms))

    return {
        'n_onsets_analyzed': len(valid_iois),
        'median_ioi_s': float(np.median(valid_iois)),
        'observed_bpm': float(60.0 / ioi_mean) if ioi_mean > 0 else 0,
        'expected_bpm': m_bpm,
        'ioi_cv': ioi_cv,
        'ioi_error_pct': ioi_error_pct,
        'drift_per_bar_ms': drift_per_bar_ms,
        'max_single_drift_ms': max_single_drift_ms,
        'cumulative_drift_ms': cumulative_drift_ms,
    }

# ── Source integrity check ─────────────────────────────────────────────────

def _check_source_integrity(mix_mono, source_audio, sr, t_zone_start, dur,
                             expected_position, stretch_ratio=1.0):
    """
    Compare a section of the mix to the expected source audio.

    `expected_position` is the approximate time position in the source track.
    `stretch_ratio` accounts for warping (1.0 = native).

    Returns spectral deviation score. Low = clean, high = mangled.
    """
    s = int(t_zone_start * sr)
    e = int(min(t_zone_start + dur, len(mix_mono)/sr) * sr)
    if e - s < sr:
        return None

    mix_seg = mix_mono[s:e].astype(np.float32)

    # Extract source at expected position, accounting for stretch
    src_start = int(expected_position * sr)
    src_end = int(min(expected_position + dur * stretch_ratio, len(source_audio)/sr) * sr)
    if src_end - src_start < sr:
        return None

    src_seg = source_audio[src_start:src_end]
    src_mono = src_seg.mean(1).astype(np.float32) if src_seg.ndim > 1 else src_seg

    # Time-stretch source to match mix duration if needed
    if abs(stretch_ratio - 1.0) > 0.001:
        import pyrubberband as pyrb
        try:
            src_mono = pyrb.time_stretch(src_mono, sr, stretch_ratio)
        except Exception:
            # Fall back to librosa
            src_mono = librosa.effects.time_stretch(src_mono, rate=stretch_ratio)

    # Trim or pad to match mix segment
    min_len = min(len(mix_seg), len(src_mono))
    if min_len < sr:
        return None
    mix_seg = mix_seg[:min_len]
    src_mono = src_mono[:min_len]

    # Spectral comparison
    n_fft = 2048
    hop = 512
    S_mix = np.abs(librosa.stft(mix_seg, n_fft=n_fft, hop_length=hop))
    S_src = np.abs(librosa.stft(src_mono, n_fft=n_fft, hop_length=hop))

    # Normalize both
    S_mix = S_mix / (np.mean(S_mix) + 1e-12)
    S_src = S_src / (np.mean(S_src) + 1e-12)

    # Per-band comparison
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    bands = [(20, 200), (200, 500), (500, 2000), (2000, 8000), (8000, 20000)]
    band_devs = {}
    for f_low, f_high in bands:
        mask = (freqs >= f_low) & (freqs <= f_high)
        if not np.any(mask):
            continue
        en_mix = np.sqrt(np.mean(np.abs(S_mix[mask]) ** 2, axis=0))
        en_src = np.sqrt(np.mean(np.abs(S_src[mask]) ** 2, axis=0))
        band_dev = np.abs(en_mix - en_src) / (en_src + 1e-12)
        band_devs[f'{f_low}-{f_high}Hz'] = {
            'mean': float(np.mean(band_dev)),
            'max': float(np.max(band_dev)),
            'p95': float(np.percentile(band_dev, 95)),
        }

    # Overall spectral deviation
    spec_diff = S_mix - S_src
    overall_dev = float(np.mean(np.sqrt(np.mean(spec_diff ** 2, axis=0))))

    return {
        'overall_deviation': overall_dev,
        'segments_compared_s': min_len / sr,
        'per_band': band_devs,
        'integrity_score': max(0, 100 - overall_dev * 50),
        'degraded': overall_dev > 0.15,
    }

# ── Transition analysis ────────────────────────────────────────────────────

def analyze_transition(mix_mono, sr, t_start, dur, master_name, slave_name,
                       stamps_entry, source_info, source_audio, master_t_start=0,
                       slave_s_entry=0, sr_full=SR):
    """Enhanced transition analysis with beat drift + source integrity."""
    s = int(t_start * sr); e = int(min(t_start + dur, len(mix_mono)/sr) * sr)
    zone = mix_mono[s:e]
    if len(zone) < sr:
        return None

    findings = {}
    oe = librosa.onset.onset_strength(y=zone.astype(np.float32), sr=sr, hop_length=256)
    tb = librosa.beat.tempo(onset_envelope=oe, sr=sr, hop_length=256)
    findings['zone_bpm'] = float(tb[0]) if len(tb) else 0
    m_bpm = source_info.get(master_name, {}).get('bpm', 0)
    s_bpm = source_info.get(slave_name, {}).get('bpm', 0)
    findings['master_bpm'] = m_bpm; findings['slave_bpm'] = s_bpm
    findings['bpm_diff_pct'] = abs(s_bpm - m_bpm) / max(m_bpm, 1) * 100 if m_bpm > 0 else 0
    findings['reported_shift_ms'] = stamps_entry.get('shift', 0) * 1000

    # LUFS jump
    pre_s = int(max(0, t_start-5)*sr); pre_e = int(t_start*sr)
    post_s = int(min(t_start+dur, len(mix_mono)/sr) * sr)
    post_e = int(min(len(mix_mono), (t_start+dur+5)*sr))
    if pre_e > pre_s and post_e > post_s:
        pr = np.sqrt(np.mean(mix_mono[pre_s:pre_e]**2)) + 1e-12
        po = np.sqrt(np.mean(mix_mono[post_s:post_e]**2)) + 1e-12
        findings['lufs_jump_db'] = round(20 * np.log10(po / pr), 2)
    else:
        findings['lufs_jump_db'] = 0

    # Spectral centroid shift
    sc_pre = librosa.feature.spectral_centroid(y=mix_mono[pre_s:pre_e], sr=sr)[0].mean() if pre_e>pre_s else 0
    sc_post = librosa.feature.spectral_centroid(y=mix_mono[post_s:post_e], sr=sr)[0].mean() if post_e>post_s else 0
    findings['centroid_shift_hz'] = round(sc_post - sc_pre, 0)

    # ── Beat drift ──
    m_db = source_info.get(master_name, {}).get('dbeats', np.array([], dtype=int))
    s_db = source_info.get(slave_name, {}).get('dbeats', np.array([], dtype=int))
    if len(m_db) > 4:
        drift = _measure_beat_drift(mix_mono, sr, m_db, s_db, t_start, dur)
        findings['beat_drift_ms'] = 0
        findings['beat_drift_ioi_cv'] = 0
        findings['beat_drift_ioi_error_pct'] = 0
        if drift:
            findings['beat_drift_ms'] = drift['max_single_drift_ms']
            findings['beat_drift_ioi_cv'] = drift['ioi_cv']
            findings['beat_drift_ioi_error_pct'] = drift['ioi_error_pct']

    # ── Source integrity: master solo before transition ──
    if master_name in source_audio and master_t_start > 2:
        master_src = source_audio[master_name]
        duration_check = min(3.0, master_t_start - 1)
        src_check = _check_source_integrity(
            mix_mono, master_src, sr,
            t_zone_start=t_start - duration_check,
            dur=duration_check,
            expected_position=master_t_start - duration_check,
            stretch_ratio=1.0  # master plays at native speed
        )
        if src_check:
            findings['master_integrity'] = src_check

    # ── Source integrity: slave solo after transition ──
    if slave_name in source_audio and dur > 2:
        slave_src = source_audio[slave_name]
        post_start = t_start + dur + 2
        post_dur = min(3.0, len(mix_mono)/sr - post_start - 1)
        if post_dur > 1:
            # Slave plays at native speed after ramp, but may still be near transition
            # Approximate slave position: starts at slave_s_entry, plays for t_start + dur
            slave_pos = slave_s_entry + (t_start + dur)
            stretch_ratio = m_bpm / s_bpm if m_bpm > 0 and s_bpm > 0 else 1.0
            src_check = _check_source_integrity(
                mix_mono, slave_src, sr,
                t_zone_start=post_start,
                dur=post_dur,
                expected_position=slave_pos,
                stretch_ratio=stretch_ratio
            )
            if src_check:
                findings['slave_integrity'] = src_check

    return findings

# ── Mix artefact detection ───────────────────────────────────────────────────

def detect_mix_artefacts(mono, sr, stamps=None):
    """
    v2 artefact detection with fixed thresholds.
    
    Key changes from v1:
    - Stutter: corr > 0.99 (was 0.999), 20ms windows (was 50ms)
    - Speed glitch: 20% BPM jump (was 15%), ramp zone 30s (was 18s)
    - Spectral discontinuity: 12x median (was 5x)
    - HF noise: absolute threshold -40dBFS OR 10x median, whichever is LESS sensitive
    """
    artefacts = []

    # ── 1. Stutter detection (v2: difference-based, 20ms windows) ──────
    # Instead of cross-correlation (which flags sustained synth pads),
    # check if consecutive windows are NEAR-IDENTICAL (difference near zero).
    # A stutter repeats the exact same PCM samples, not just similar content.
    win_st = int(0.020 * sr)  # 20ms windows
    n_st = len(mono) // win_st
    consecutive_st = 0
    for i in range(1, n_st):
        a = mono[(i-1)*win_st:i*win_st]
        b = mono[i*win_st:(i+1)*win_st]
        if len(a) != len(b):
            continue
        a_rms = np.sqrt(np.mean(a**2)) + 1e-12
        if a_rms < 0.001:
            consecutive_st = 0
            continue
        diff_rms = np.sqrt(np.mean((a - b)**2))
        diff_ratio = diff_rms / a_rms
        if diff_ratio < 0.001:  # <0.1% difference = digital repeat
            consecutive_st += 1
            if consecutive_st >= 3:  # 60ms+ of repeated audio
                artefacts.append({
                    't': i*win_st/sr, 'type': 'stutter',
                    'severity': 'high' if diff_ratio < 0.0001 else 'mid',
                    'detail': f'diff_ratio={diff_ratio:.5f} dur={consecutive_st*20}ms'
                })
        else:
            consecutive_st = 0

    # ── 2. Speed glitch (v2: 20% threshold, 30s ramp zone) ───────────────
    hop_bpm = int(0.5 * sr)
    win_bpm = int(4 * sr)
    n_bpm = max(1, (len(mono) - win_bpm) // hop_bpm)
    lb = []
    for i in range(n_bpm):
        s = i * hop_bpm
        e = s + win_bpm
        if e > len(mono):
            break
        seg = mono[s:e].astype(np.float32)
        if np.max(np.abs(seg)) < 0.001:
            lb.append(0)
            continue
        oe = librosa.onset.onset_strength(y=seg, sr=sr, hop_length=256)
        tb = librosa.beat.tempo(onset_envelope=oe, sr=sr, hop_length=256)
        lb.append(float(tb[0]) if len(tb) and tb[0] > 0 else 0)
    lb = np.array(lb)
    # Filter out impossible BPM values (BPM estimator returns garbage on silent sections)
    valid_bpm = lb[lb > 0]
    if len(valid_bpm) > 0:
        mb = np.median(valid_bpm)
        # Clamp individual BPM estimates to ±30% of median (anything beyond is garbage)
        lb_clamped = np.where((lb > mb * 0.7) & (lb < mb * 1.3), lb, mb)
        for j in range(len(lb_clamped) - 1):
            if lb_clamped[j] <= 0 or lb_clamped[j+1] <= 0:
                continue
            jump_pct = abs(lb_clamped[j+1] - lb_clamped[j]) / mb
            if jump_pct > 0.20:  # was 0.15
                t_glitch = j * hop_bpm / sr
                # Suppress inside ramp zones (v2: 30s)
                if stamps:
                    in_ramp = False
                    for s in stamps:
                        ramp_start = s['t']
                        ramp_end = s['t'] + 30  # was 18
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
    n_cr = len(mono) // hop_cr
    crest = np.array([
        np.max(np.abs(mono[i*hop_cr:(i+1)*hop_cr])) /
        (np.sqrt(np.mean(mono[i*hop_cr:(i+1)*hop_cr]**2)) + 1e-12)
        for i in range(n_cr)
    ])
    cm = np.median(crest)
    for s in np.where(crest > cm * 5)[0]:
        artefacts.append({'t': s*hop_cr/sr, 'type': 'transient_spike',
                          'severity': 'high' if crest[s] > cm * 10 else 'mid',
                          'detail': f'crest={crest[s]:.1f}x median'})

    # ── 4. HF noise (v2: absolute + relative threshold) ──────────────────
    b_hp, a_hp = sig.butter(2, 16000.0 / (0.5 * sr), btype='high')
    hf = sig.filtfilt(b_hp, a_hp, mono)
    hop_hf = int(0.15 * sr)
    n_hf = len(mono) // hop_hf
    hf_e = np.array([
        np.sqrt(np.mean(hf[i*hop_hf:(i+1)*hop_hf]**2))
        for i in range(n_hf)
    ])
    hm = np.median(hf_e)

    # v2: Use two thresholds, pick the LESS sensitive one (higher absolute value)
    # Relative: 10x median (was 8x)
    # Absolute: -40dBFS = 0.01 in linear scale
    # Only flag if BOTH thresholds are exceeded (reduces false positives from hi-hats)
    abs_thresh = 0.01  # -40dBFS
    rel_thresh = hm * 10  # was hm * 8

    for h in range(len(hf_e)):
        if hf_e[h] > rel_thresh and hf_e[h] > abs_thresh:
            artefacts.append({'t': h*hop_hf/sr, 'type': 'hf_noise',
                              'severity': 'high' if hf_e[h] > hm * 20 else 'mid',
                              'detail': f'hf_energy={hf_e[h]:.6f}'})

    # ── 5. Spectral discontinuity (v2: 12x median) ───────────────────────
    hop_sf = int(0.1 * sr)
    n_sf = max(1, len(mono) // hop_sf)
    sf_arr = np.zeros(n_sf - 1)
    for i in range(n_sf - 1):
        a = mono[i*hop_sf:(i+1)*hop_sf]
        b = mono[(i+1)*hop_sf:(i+2)*hop_sf]
        if len(a) < 2 or len(b) < 2:
            continue
        sa = np.abs(np.fft.rfft(a))
        sb = np.abs(np.fft.rfft(b))
        sf_arr[i] = np.sqrt(np.mean((sa - sb)**2)) / (np.mean(sa) + 1e-12)

    valid_sf = sf_arr[~np.isnan(sf_arr) & ~np.isinf(sf_arr)]
    if len(valid_sf) > 0:
        sm = np.median(valid_sf)
        thr = sm * 12  # was sm * 5
        for d in np.where(sf_arr > thr)[0]:
            artefacts.append({'t': d*hop_sf/sr, 'type': 'spectral_discontinuity',
                              'severity': 'high' if sf_arr[d] > sm * 20 else 'mid',
                              'detail': f'flux={sf_arr[d]:.3f}x median'})

    # ── 6. Onset stability within crossfade ──────────────────────────────
    hop_oc = int(0.5 * sr)
    win_oc = int(0.5 * sr)
    n_oc = max(1, len(mono) // hop_oc - 1)
    oe_full = librosa.onset.onset_strength(y=mono.astype(np.float32), sr=sr, hop_length=256)
    for i in range(n_oc - 1):
        t_oc = i * hop_oc / sr
        in_cf = False
        if stamps:
            for s in stamps:
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

    # ── 7. RMS dip within crossfade (phase cancellation) ─────────────────
    hop_dip = int(0.1 * sr)
    n_dip = max(1, len(mono) // hop_dip)
    rms_dip = np.array([
        np.sqrt(np.mean(mono[i*hop_dip:(i+1)*hop_dip]**2))
        for i in range(n_dip)
    ])
    med_dip = np.median(rms_dip)
    for i in range(2, n_dip - 2):
        t_dip = i * hop_dip / sr
        in_cf = False
        if stamps:
            for s in stamps:
                cf_start = s['t'] - 2
                cf_end = s['t'] + s.get('dur', 30) + 5
                if cf_start <= t_dip <= cf_end:
                    in_cf = True
                    break
        if not in_cf:
            continue
        local_med = np.median(rms_dip[max(0, i-2):i+3])
        if rms_dip[i] < med_dip * 0.5 and rms_dip[i] < local_med * 0.5:
            artefacts.append({'t': i*hop_dip/sr, 'type': 'rms_dip',
                              'severity': 'high' if rms_dip[i] < med_dip * 0.3 else 'mid',
                              'detail': f'rms={rms_dip[i]:.4f} (med={med_dip:.4f})'})

    # ── 8. Harsh endpoint ────────────────────────────────────────────────
    if stamps and len(valid_sf) > 0:
        sm = np.median(valid_sf)
        for s in stamps:
            t_end = s['t'] + s.get('dur', 16 * 240.0 / 120)
            s_frame = int(t_end * sr)
            if s_frame + hop_sf * 2 >= len(mono):
                continue
            pre = mono[s_frame - hop_sf:s_frame]
            post = mono[s_frame:s_frame + hop_sf]
            if len(pre) < 2 or len(post) < 2:
                continue
            sp = np.abs(np.fft.rfft(pre))
            sp2 = np.abs(np.fft.rfft(post))
            endpoint_flux = np.sqrt(np.mean((sp - sp2)**2)) / (np.mean(sp) + 1e-12)
            if endpoint_flux > sm * 3:
                artefacts.append({'t': t_end, 'type': 'harsh_endpoint',
                                  'severity': 'high' if endpoint_flux > sm * 5 else 'mid',
                                  'detail': f'endpoint_flux={endpoint_flux:.3f}x median'})

    # ── 8b. Blend→ramp boundary glitch (micro-stutter at transition end) ──
    # After each crossfade, the mixer does blend→ramp transition. The boundary
    # can produce a micro-stutter: 10-50ms audio glitch from sudden phase change.
    # Detect by looking for a sharp energy spike in the 50ms around the endpoint.
    if stamps:
        hop_ms = int(0.001 * sr)  # 1ms resolution
        for s in stamps:
            t_end = s['t'] + s.get('dur', 16 * 240.0 / 120)
            s_frame = int(t_end * sr)
            # 100ms window centered on endpoint
            win_pre = int(0.050 * sr)
            win_post = int(0.050 * sr)
            if s_frame - win_pre < 0 or s_frame + win_post >= len(mono):
                continue
            boundary = mono[s_frame - win_pre:s_frame + win_post]
            # RMS envelope at 1ms resolution
            rms_env = np.array([
                np.sqrt(np.mean(boundary[i:i+hop_ms]**2))
                for i in range(0, len(boundary) - hop_ms, hop_ms)
            ])
            if len(rms_env) < 10:
                continue
            # Smooth
            rms_smooth = sig.medfilt(rms_env, kernel_size=3)
            # Check for sharp spike at center (the boundary)
            center_idx = len(rms_smooth) // 2
            left_med = np.median(rms_smooth[max(0, center_idx-5):center_idx])
            right_med = np.median(rms_smooth[center_idx:min(len(rms_smooth), center_idx+5)])
            boundary_peak = np.max(rms_smooth[center_idx-2:center_idx+3])
            spike_ratio = boundary_peak / (max(left_med, right_med) + 1e-12)
            if spike_ratio > 1.8:
                artefacts.append({'t': t_end, 'type': 'boundary_glitch',
                                  'severity': 'high' if spike_ratio > 3.0 else 'mid',
                                  'detail': f'spike={spike_ratio:.1f}x at blend→ramp boundary'})
            # Also check RMS envelope discontinuity (sudden drop then recovery)
            env_grad = np.abs(np.diff(rms_smooth))
            max_grad = np.max(env_grad[center_idx-3:center_idx+3]) if center_idx+3 < len(env_grad) else 0
            med_grad = np.median(env_grad) + 1e-12
            if max_grad > med_grad * 5:
                artefacts.append({'t': t_end, 'type': 'boundary_glitch',
                                  'severity': 'mid',
                                  'detail': f'gradient_spike={max_grad/med_grad:.1f}x at boundary'})

    # ── 8c. Beat confusion (short-term arrhythmia in crossfade zone) ─────
    # Detects 0.5-2s sections where the beat pattern falls apart.
    # Uses 50ms onset windows (coarser = cleaner peaks) and looks for
    # a sudden burst of irregular IOI = garbled pyrubberband bar.
    if stamps:
        hop_ir = int(0.050 * sr)  # 50ms resolution (cleaner peaks)
        oe_full = librosa.onset.onset_strength(y=mono.astype(np.float32), sr=sr, hop_length=hop_ir)
        for s in stamps:
            t_start_ir = s['t']
            t_dur_ir = s.get('dur', 30)
            s_frame = int(max(0, t_start_ir - 1) * sr / hop_ir)
            e_frame = int(min(t_start_ir + t_dur_ir + 2, len(mono)/sr) * sr / hop_ir)
            if e_frame - s_frame < 20:
                continue
            seg_oe = oe_full[s_frame:e_frame]
            if np.max(seg_oe) < 0.001:
                continue
            # Find strong onset peaks (>3x median to filter noise)
            thr = max(np.median(seg_oe) * 3, np.mean(seg_oe) * 1.5)
            peaks, _ = sig.find_peaks(seg_oe, height=thr, distance=2)
            if len(peaks) < 4:
                continue
            peak_times = (s_frame + peaks) * hop_ir / sr
            iois = np.diff(peak_times)
            if len(iois) < 3:
                continue
            # Scan with 3-IOI window, flag if any IOI is >2x the local median
            # (a garbled bar has one anomalously long or short IOI)
            for i in range(len(iois)):
                local_med = float(np.median(iois[max(0,i-2):i+3]))
                if local_med < 0.05:
                    continue
                ratio = iois[i] / local_med
                if ratio > 2.0 or ratio < 0.4:  # IOI 2x longer or 0.4x shorter
                    artefacts.append({
                        't': peak_times[i],
                        'type': 'beat_irregularity',
                        'severity': 'high' if ratio > 3.0 or ratio < 0.25 else 'mid',
                        'detail': f'ioi_ratio={ratio:.2f} ({iois[i]:.3f}s vs med {local_med:.3f}s)'
                    })

    # ── 9. Per-band phase cancellation (post-hoc, no source tracks) ──────
    if stamps and len(stamps) > 0:
        for s in stamps:
            t_start = s['t']
            if t_start < 2.0:  # skip very start of mix — no crossfade yet
                continue
            t_dur = s.get('dur', 30)
            s_frame = int(t_start * sr)
            e_frame = int(min(t_start + t_dur, len(mono)/sr) * sr)
            if e_frame - s_frame < sr:
                continue
            zone = mono[s_frame:e_frame]
            if len(zone) < sr:
                continue
            n_fft = 1024
            hop = 256
            S = np.abs(librosa.stft(zone.astype(np.float32), n_fft=n_fft, hop_length=hop))
            freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

            bands = [(20, 60), (60, 120), (120, 500), (500, 2000), (2000, 8000)]
            for f_low, f_high in bands:
                mask = (freqs >= f_low) & (freqs <= f_high)
                if not np.any(mask):
                    continue
                band_mag = np.sqrt(np.mean(np.abs(S[mask])**2, axis=0))
                # Smooth with median filter
                band_smooth = sig.medfilt(band_mag, kernel_size=5)
                # Local median for dip detection
                local_med = np.array([
                    np.median(band_smooth[max(0, i-5):i+6])
                    for i in range(len(band_smooth))
                ])
                dip_ratio = band_smooth / (local_med + 1e-12)
                deep_dips = np.where(dip_ratio < 0.5)[0]
                if len(deep_dips) > 3:
                    # Group consecutive dips
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

# ── Cross-reference ─────────────────────────────────────────────────────────

def cross_reference(mix_arts, source_infos, stamps, sr=SR):
    """Map mix artefacts to source tracks, identify mixer-induced vs source issues."""
    timeline = []
    names = list(source_infos.keys())
    prev_t = 0
    for i, s in enumerate(stamps):
        t_start = s['t']
        pt = s.get('prev_track', stamps[i-1]['from'] if i > 0 else names[0])
        if t_start > prev_t:
            timeline.append((prev_t, t_start, pt))
        prev_t = t_start
    if stamps:
        timeline.append((prev_t, 1e9, stamps[-1]['to']))

    for art in mix_arts:
        t = art['t']
        src = None
        for ts, te, n in timeline:
            if ts <= t <= te:
                src = n
                break
        if src and src in source_infos:
            matched = any(
                sa['type'] == art['type'] and abs(sa['t'] - t) < 2.0
                for sa in source_infos[src].get('source_artefacts', [])
            )
            art['origin'] = 'source_issue' if matched else 'mixer_induced'
            art['source_track'] = src
        else:
            art['origin'] = 'unknown'
            art['source_track'] = src or '?'
    return mix_arts

# ── Feedback generation ────────────────────────────────────────────────────

def generate_feedback(transitions, mix_artefacts):
    recs = []
    for tr in (transitions or []):
        if tr is None:
            continue
        if tr.get('reported_shift_ms', 0) > 5:
            recs.append({'severity': 'mid', 'parameter': 'build_cf_lr4(max_shift_sec)',
                         'suggestion': f"Increase max_shift_sec to {tr['reported_shift_ms']/1000+0.02:.3f}"})
        if abs(tr.get('lufs_jump_db', 0)) > 2.0:
            recs.append({'severity': 'mid', 'parameter': 'norm_lufs(gain_offset)',
                         'suggestion': f"Apply ±{abs(tr['lufs_jump_db'])/2:.1f}dB gain on slave entry"})

        # Beat drift feedback
        drift = tr.get('beat_drift_ms', 0)
        if drift > 10:
            recs.append({'severity': 'high', 'parameter': 'warp_to_grid/onset_micro_align',
                         'suggestion': f"Beat drift {drift:.1f}ms per bar — check warp_to_grid precision"})
        elif drift > 3:
            recs.append({'severity': 'mid', 'parameter': 'onset_micro_align',
                         'suggestion': f"Minor beat drift {drift:.1f}ms per bar"})

        # Master integrity feedback
        mi = tr.get('master_integrity', {})
        if mi and mi.get('degraded', False):
            recs.append({'severity': 'high', 'parameter': 'build_cf_lr4(master_blend)',
                         'suggestion': f"Master source degraded before crossfade (dev={mi.get('overall_deviation', 0):.3f})"})

        # Slave integrity feedback
        si = tr.get('slave_integrity', {})
        if si and si.get('degraded', False):
            recs.append({'severity': 'high', 'parameter': 'ramp_to_native(slave_warp)',
                         'suggestion': f"Slave audio mangled after transition (dev={si.get('overall_deviation', 0):.3f})"})

    mx = [a for a in mix_artefacts if a.get('origin') == 'mixer_induced']

    st = [a for a in mx if a['type'] == 'stutter']
    if len(st) > 3:
        recs.append({'severity': 'high', 'parameter': 'warp_to_grid(rate_threshold)',
                     'suggestion': f"Reduce rate_threshold 0.002→0.001 ({len(st)} stutters)"})

    hf = [a for a in mx if a['type'] == 'hf_noise']
    if len(hf) > 5:
        recs.append({'severity': 'mid', 'parameter': 'ramp_to_native(ramp_sec)',
                     'suggestion': f"Increase RAMP_SEC 15→20 ({len(hf)} HF events)"})

    sp = [a for a in mx if a['type'] == 'speed_glitch']
    if sp:
        recs.append({'severity': 'high', 'parameter': 'ramp_to_native(ramp_sec)',
                     'suggestion': 'Ramp too aggressive — increase RAMP_SEC or skip for <1 BPM diff'})

    qe = [a for a in mix_artefacts if a.get('type') == 'quiet_slave_entry']
    for q in qe[:3]:
        recs.append({'severity': 'high', 'parameter': 'RAMP_MIN_RMS / entry_point',
                     'suggestion': f"The slave track at {_ts(q['t'])} enters too quietly (RMS={q.get('detail','?')}). "
                                   f"Increase RAMP_MIN_RMS or shift entry point ({int(q.get('suggest_delay',15))}s)"})

    os_issues = [a for a in mx if a['type'] == 'onset_stability']
    if len(os_issues) > 2:
        recs.append({'severity': 'high', 'parameter': 'onset_micro_align(max_shift_sec/downbeat_weight)',
                     'suggestion': f'{len(os_issues)} onset stability events — downbeat-weighted alignment may need tighter window'})

    rd = [a for a in mx if a['type'] == 'rms_dip']
    if rd:
        recs.append({'severity': 'high', 'parameter': 'build_cf_lr4(LR4_polarity)',
                     'suggestion': f'{len(rd)} RMS dip events — phase cancellation in crossfade. Check LR4 band polarity'})

    bc = [a for a in mx if a['type'] == 'band_cancellation']
    if bc:
        recs.append({'severity': 'high', 'parameter': 'build_cf_lr4(phase_coherence)',
                     'suggestion': f'{len(bc)} band cancellation events — sub/mid phase issues in crossfade'})

    he = [a for a in mx if a['type'] == 'harsh_endpoint']
    if he:
        recs.append({'severity': 'mid', 'parameter': 'build_cf_lr4(blend→ramp_crossfade)',
                     'suggestion': f'{len(he)} harsh endpoint(s) — 50ms blend→ramp crossfade should fix these'})

    bg = [a for a in mx if a['type'] == 'boundary_glitch']
    if bg:
        recs.append({'severity': 'high' if any(a['severity'] == 'high' for a in bg) else 'mid',
                     'parameter': 'build_cf_lr4(boundary_blend)',
                     'suggestion': f'{len(bg)} blend→ramp boundary glitch(es) — the crossfade endpoint has a '
                                   f'sharp discontinuity. Add 10-20ms overlap or cross-fade the blend→ramp transition'})

    bi = [a for a in mx if a['type'] == 'beat_irregularity']
    if bi:
        n_bi = len(bi)
        recs.append({'severity': 'high' if any(a['severity'] == 'high' for a in bi) else 'mid',
                     'parameter': 'warp_to_grid(pyrubberband_quality)',
                     'suggestion': f'{n_bi} beat irregularity event(s) at problematic IOI zones — '
                                   f'the bar-by-bar warp produced a garbled bar. '
                                   f'Check pyrubberband stretch ratio limits or use phase-vocoder fallback'})

    pk = [a for a in mx if a['type'] == 'transient_spike']
    if len(pk) > 2:
        recs.append({'severity': 'mid', 'parameter': 'mix_tracks(headroom_db)',
                     'suggestion': f"Increase headroom -1→-2dB ({len(pk)} spikes)"})

    # Per-band cancellation specific feedback
    if bc:
        bands_seen = set(a['detail'].split(' ')[0] for a in bc)
        if any('60-120' in b for b in bands_seen):
            recs.append({'severity': 'high', 'parameter': 'build_cf_lr4(kick_alignment)',
                         'suggestion': 'Kick drum phase cancellation (60-120Hz). Check polarity or shift crossfade to avoid kick overlap'})
        if any('20-60' in b for b in bands_seen):
            recs.append({'severity': 'high', 'parameter': 'build_cf_lr4(sub_alignment)',
                         'suggestion': 'Sub-bass cancellation (20-60Hz). Use HPF or align phase on sub content'})

    return recs

# ── Main analysis entry point ──────────────────────────────────────────────

def analyze(mix_path, wav_dir, ann_dir, tracks=None, feedback=False):
    print("=== Mix Analyzer v2 ===\n")
    print("Loading mix audio...")
    audio = _load_wav(mix_path, SR)
    mono = audio.mean(1).astype(np.float32)
    dm = len(mono) / SR
    print(f"  Duration: {int(dm//60)}:{int(dm%60):02d}  ({dm:.1f}s)\n")

    if tracks is None:
        wav_files = sorted(f for f in os.listdir(wav_dir) if f.endswith('.wav'))
        tracks = []
        for wf in wav_files:
            base = os.path.splitext(wf)[0]
            ann = base + '.txt'
            if os.path.exists(os.path.join(ann_dir, ann)):
                tracks.append((base.split(' - ')[0] if ' - ' in base else base[:20], wf, ann))

    ts = time.time()
    print("── Phase 1: Source Analysis ──\n")
    si, audio_cache = analyze_source_tracks(tracks, wav_dir, ann_dir)

    for n, i in si.items():
        a = i.get('source_artefacts', [])
        print(f"  {n:20s}  BPM={i['bpm']:5.1f}  Key={i['key']:8s}  conf={i['key_confidence']:.2f}{f', {len(a)} artefacts' if a else ''}")

    print(f"\n── Phase 2: Transition Analysis ──\n")
    stamps = []
    sp = mix_path.replace('.mp3', '_stamps.npy').replace('.wav', '_stamps.npy')
    if os.path.exists(sp):
        stamps = list(np.load(sp, allow_pickle=True))
        print(f"  Loaded {len(stamps)} stamps\n")
    else:
        print("  (No stamps — estimating for source analysis only)\n")
        # Estimate stamps for source analysis, but DON'T pass to artefact detection
        # (estimated stamps have incorrect positions and cause false positives)
        cum = 0
        pn = None
        for n, i in si.items():
            if pn:
                stamps.append({'from': pn, 'to': n, 't': max(0, cum - 30),
                                'dur': 16 * 240.0 / si[pn]['bpm'], 'mode': '?', 'shift': 0})
            cum += si[pn]['dur_sec'] if pn else 0
            pn = n

    # Use stamps for transition analysis but pass SEPARATE stamp list
    # for artefact zone detection (omit first estimated stamp if t < 5s)
    stamps_for_artefacts = []
    if stamps and os.path.exists(sp):
        # Real stamps — use as-is
        stamps_for_artefacts = stamps
    else:
        # Estimated stamps — skip any with t < 5s (false positions)
        stamps_for_artefacts = [s for s in stamps if s.get('t', 0) > 5]

    transitions = []
    for i_s, s in enumerate(stamps):
        fn = s['from']
        tn = s['to']
        s['prev_track'] = stamps[i_s-1]['from'] if i_s > 0 else list(si.keys())[0]

        # Estimate master/slave positions for source integrity check
        # Master plays at native speed, so at crossfade start, master time ≈ t_start
        master_t_start = s['t']
        slave_s_entry = s['t']  # rough estimate

        tr = analyze_transition(
            mono, SR, s['t'], s.get('dur', 30), fn, tn, s, si, audio_cache,
            master_t_start=master_t_start, slave_s_entry=slave_s_entry, sr_full=SR
        )
        if tr:
            tr['master_name'] = fn
            tr['slave_name'] = tn
            tr['t'] = s['t']
            transitions.append(tr)

            # Build status line
            drift = tr.get('beat_drift_ms', 0)
            drift_ic = "✅" if drift < 5 else "⚠️" if drift < 15 else "❌"
            ic = "✅" if abs(tr['reported_shift_ms']) < 5 else "⚠️" if abs(tr['reported_shift_ms']) < 10 else "❌"
            print(f"  {ic} {fn:15s} → {tn:15s}  @ {_ts(s['t'])}  "
                  f"drift={drift:.1f}ms{drift_ic}  shift={tr['reported_shift_ms']:.1f}ms  "
                  f"LUFS={tr['lufs_jump_db']:+.1f}dB")

            # Source integrity summary
            mi = tr.get('master_integrity', {})
            si_check = tr.get('slave_integrity', {})
            if mi and mi.get('degraded'):
                print(f"    ⚠️ Master source degraded before transition (dev={mi['overall_deviation']:.3f})")
            if si_check and si_check.get('degraded'):
                print(f"    ⚠️ Slave source degraded after transition (dev={si_check['overall_deviation']:.3f})")

    # ── Quiet entry detection ──────────────────────────────────────────────
    quiet_entries = []
    for s in stamps:
        entry_rms = s.get('entry_rms', 1.0)
        if entry_rms < 0.08:
            quiet_entries.append({
                't': s['t'], 'type': 'quiet_slave_entry',
                'severity': 'high',
                'detail': f'{entry_rms:.3f}',
                'suggest_delay': int(15 * (0.08 / max(entry_rms, 0.01)))
            })
    if quiet_entries:
        print(f"\n  ⚠️ Quiet slave entries ({len(quiet_entries)}):")
        for q in quiet_entries:
            print(f"    @ {_ts(q['t'])}  entry RMS={q['detail']}")

    print(f"\n── Phase 3: Mix Artefact Scan ──\n  Scanning...", end=' ', flush=True)
    ma = detect_mix_artefacts(mono, SR, stamps_for_artefacts)
    ma.extend(quiet_entries)
    print(f"{len(ma)} events\n")

    print(f"── Phase 4: Source vs Mixer ──\n")
    ma = cross_reference(ma, si, stamps, SR)
    src_i = [a for a in ma if a.get('origin') == 'source_issue']
    mix_i = [a for a in ma if a.get('origin') == 'mixer_induced']

    # Group mixer-induced by type for cleaner display
    if src_i:
        print(f"  In source ({len(src_i)}):")
        # Show only significant source issues (high + non-noise)
        sig_src = [a for a in src_i if a['type'] not in ('hf_noise',) or a['severity'] == 'high']
        for a in sig_src[:10]:
            print(f"    @ {_ts(a['t'])}  [{a['type']}]  {a['detail']}  in {a.get('source_track','?')}")
        if len(sig_src) > 10:
            print(f"    ... +{len(sig_src) - 10}")

    if mix_i:
        print(f"\n  Mixer-induced ({len(mix_i)}):")
        # Group by type for readability
        by_type = {}
        for a in mix_i:
            by_type.setdefault(a['type'], []).append(a)
        for ttype, events in sorted(by_type.items()):
            high = [e for e in events if e['severity'] == 'high']
            mid = [e for e in events if e['severity'] == 'mid']
            print(f"    [{ttype}]  {len(high)} high, {len(mid)} mid")
            # Show first 3 high events
            for a in high[:3]:
                print(f"      @ {_ts(a['t'])}  {a['detail']}")
            if len(high) > 3:
                print(f"      ... +{len(high) - 3} more")
            if not high:
                for a in mid[:2]:
                    print(f"      @ {_ts(a['t'])}  {a['detail']}")

    print(f"\n── Key Compatibility ──\n")
    names = list(si.keys())
    for i in range(len(names) - 1):
        k1 = si[names[i]]['key']
        k2 = si[names[i + 1]]['key']
        sc, desc = key_compatibility(k1, k2)
        ic = "✅" if sc >= 0.8 else "⚠️" if sc >= 0.5 else "❌"
        print(f"  {ic} {names[i]:15s} ({k1:8s}) → {names[i+1]:15s} ({k2:8s})  score={sc:.1f}  {desc}")

    print(f"\n── Phase 5: Feedback ──\n")
    recs = generate_feedback(transitions, ma)
    if feedback:
        if recs:
            for r in recs:
                ic = "🔴" if r['severity'] == 'high' else "🟡"
                print(f"  {ic} [{r['parameter']}] {r['suggestion']}")
        else:
            print("  ✅ No adjustments needed.\n")
    else:
        print("  (Run with --feedback for recommendations)\n")

    print(f"Analysis completed in {time.time() - ts:.1f}s")

    return {
        'source_info': si,
        'transitions': transitions,
        'mix_artefacts': ma,
        'source_issues': src_i,
        'mixer_issues': mix_i,
        'feedback': recs,
    }


def _json_safe(obj):
    """Recursively convert numpy scalars to Python native types for JSON serialization."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Mix Analyzer v2")
    p.add_argument("--mix", required=True)
    p.add_argument("--wav-dir")
    p.add_argument("--ann-dir")
    p.add_argument("--config")
    p.add_argument("--feedback", action="store_true")
    p.add_argument("--json-out", metavar="FILE",
                   help="Save structured analysis as JSON (for mix_validator.py)")
    a = p.parse_args()
    wd = a.wav_dir
    ad = a.ann_dir
    tr = None
    if a.config:
        s = importlib.util.spec_from_file_location("cfg", a.config)
        c = importlib.util.module_from_spec(s)
        s.loader.exec_module(c)
        tr = c.TRACKS
        if wd is None:
            wd = getattr(c, 'WAV_DIR', None) or '.'
        if ad is None:
            ad = getattr(c, 'ANN_DIR', None) or '.'
    if not wd or not ad:
        p.error("Need --wav-dir and --ann-dir (or --config)")
    result = analyze(a.mix, wd, ad, tr, feedback=a.feedback)
    if a.json_out:
        import json
        with open(a.json_out, 'w') as f:
            json.dump(_json_safe(result), f, indent=2)
        print(f"\n  JSON saved → {a.json_out}")
