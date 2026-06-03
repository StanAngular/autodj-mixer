#!/usr/bin/env python3
"""
Smart Mixer — automated EDM DJ mixing with bar-by-bar warping,
multi-band EQ crossovers, BPM ramping, and RMS stabilisation.
"""

import numpy as np
import soundfile as sf
import scipy.signal as signal
import pyrubberband as pyrb
import librosa
import pyloudnorm as pyln

import os, sys, time, subprocess, json
from pathlib import Path

np.float = np.float64
np.int = np.int64
np.complex = np.complex128
np.bool = np.bool_

SR = 44100  # sample rate


def three_band_split(audio, lc, hc, sr=SR):
    """Split audio into low/mid/high using Butterworth LR2 (6dB/oct)."""
    nyq = 0.5 * sr
    b_low, a_low = signal.butter(2, lc / nyq, btype='low')
    b_high, a_high = signal.butter(2, hc / nyq, btype='high')

    low = np.zeros_like(audio, dtype=np.float32)
    high = np.zeros_like(audio, dtype=np.float32)
    for ch in range(audio.shape[1]):
        x = audio[:, ch].astype(np.float64)
        low[:, ch] = signal.filtfilt(b_low, a_low, x).astype(np.float32)
        high[:, ch] = signal.filtfilt(b_high, a_high, x).astype(np.float32)

    return low, audio - low - high, high


def load_stereo(path, sr=SR):
    """Load stereo WAV, resampling to SR if needed. Returns float32 array."""
    data, file_sr = sf.read(path, always_2d=True)
    if data.shape[1] == 1:
        data = np.hstack([data, data])
    if file_sr != sr:
        tmp = f"/tmp/_rs_{os.path.basename(path)}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", str(sr), "-ac", "2", tmp],
            capture_output=True
        )
        data, _ = sf.read(tmp, always_2d=True)
    return data.astype(np.float32)


def pt(audio, n):
    """Pad or truncate audio to length n.  If longer, truncate.  If shorter, zero-pad."""
    if len(audio) >= n:
        return audio[:n]
    shape = list(audio.shape)
    shape[0] = n - len(audio)
    return np.concatenate([audio, np.zeros(shape, dtype=audio.dtype)])


def bar_s(bpm):
    """Bar duration in seconds (4 beats in 4/4 time)."""
    return 240.0 / bpm


def load_dbeats(ann_path, sr=SR):
    """Load downbeat positions from madmom annotation file."""
    beats = np.loadtxt(ann_path)
    return np.array([int(r[0] * sr) for r in beats if round(r[1]) == 1], dtype=int)


def calc_bpm(db, sr=SR):
    """Calculate BPM from downbeat array using IQR-based outlier rejection."""
    if len(db) < 4:
        return 120.0
    iv = np.diff(db.astype(float)) / sr
    iv = iv[iv > 0.1]
    if not len(iv):
        return 120.0
    p25, p75 = np.percentile(iv, [25, 75])
    ok = iv[(iv >= p25 - 1.5 * (p75 - p25)) & (iv <= p75 + 1.5 * (p75 - p25))]
    return 4 * 60.0 / np.mean(ok) if len(ok) else 120.0


def fix_ht(db, bpm, sr=SR):
    """
    Fix half-time / double-time / quarter-beat annotations.

    Uses median entry-interval (seconds) to detect annotation density
    and either decimate (too dense) or interpolate (too sparse).
    No dependency on calc_bpm as reference — works universally.

    Key assumption: beat-level (quarter-note) entries have
    med in [0.25s, 1.0s] corresponding to [240, 60] BPM.

    Cases:
      med < 0.25  → multiple entries per beat → decimate
      med 0.25–1.0 → beat-level → correct (no action)
      med ≥ 1.0   → sparser → subdivide (bar-level, half-time, etc.)
    """
    if len(db) < 3:
        return db, bpm

    intervals = np.diff(db.astype(float)) / sr
    intervals = intervals[intervals > 0.01]
    if len(intervals) < 2:
        return db, bpm

    med = float(np.median(intervals))

    if med < 0.25:
        # Too dense — multiple entries per quarter-note
        n = max(2, int(round(0.25 / med)))
        if len(db) >= n * 4:
            db = db[::n]

    elif med < 1.0:
        # Beat-level spacing — correct for 60-240 BPM
        pass

    elif med < 2.0:
        # Could be half-time (1/2-beat) OR fast bar-level (4-beat at ≥200 BPM)
        # Use bpm to disambiguate: for bar-level, bpm = actual musical BPM
        beat_sec = max(0.25, 60.0 / bpm)
        beats_per_entry = med / beat_sec  # how many beats each entry spans

        if beats_per_entry < 2.5:
            # Half-time or slow beat: insert midpoint between each pair
            new_db = []
            for i in range(len(db) - 1):
                new_db.append(db[i])
                new_db.append(int((db[i] + db[i + 1]) // 2))
            new_db.append(db[-1])
            db = np.array(new_db, dtype=int)
        else:
            # Fast bar-level (≥200 BPM): split fully
            n_split = max(2, round(beats_per_entry))
            new_db = []
            for i in range(len(db) - 1):
                gap = db[i + 1] - db[i]
                for j in range(n_split):
                    new_db.append(int(db[i] + j * gap // n_split))
            new_db.append(db[-1])
            db = np.array(new_db, dtype=int)

    else:
        # 1 entry per ≥4 beats (bar-level or sparser): split into beats
        # For bar-level, bpm = actual musical BPM, so beat = 60/bpm
        beat_sec = max(0.25, 60.0 / bpm)
        n_split = max(2, round(med / beat_sec))
        new_db = []
        for i in range(len(db) - 1):
            gap = db[i + 1] - db[i]
            for j in range(n_split):
                new_db.append(int(db[i] + j * gap // n_split))
        new_db.append(db[-1])
        db = np.array(new_db, dtype=int)

    return db, calc_bpm(db, sr)


# ============================================================
# Structural Analysis
# ============================================================

def sections(audio, db, sr=SR, name=""):
    """Classify bars as QUIET/BUILD/ACTIVE/DROP based on RMS energy + bass ratio."""
    mono = audio.mean(1) if audio.ndim == 2 else audio
    n = len(db) - 1
    if n < 4:
        return [(0, n, "ACTIVE")]

    br = np.array([
        np.sqrt(np.mean(mono[db[i]:db[i+1]]**2))
        if db[i+1] > db[i] else 0.0 for i in range(n)
    ])

    b_low, a_low = signal.butter(2, 200.0 / (0.5 * sr), btype='low')
    mono_low = signal.filtfilt(b_low, a_low, mono)

    bl = np.array([
        np.sqrt(np.mean(mono_low[db[i]:db[i+1]]**2)) / (br[i] + 1e-12)
        if db[i+1] > db[i] else 0.0 for i in range(n)
    ])

    k = np.ones(4) / 4
    de = np.convolve(br, k, 'same') * np.convolve(bl, k, 'same')
    med = np.median(de[de > 0]) if np.any(de > 0) else 1e-12

    lb = [
        'DROP' if e > med * 1.2 else
        'ACTIVE' if e > med * 0.5 else
        'BUILD' if e > med * 0.2 else 'QUIET'
        for e in de
    ]

    segs = []
    cur, st = lb[0], 0
    for i in range(1, n):
        if lb[i] != cur:
            segs.append((st, i, cur))
            cur, st = lb[i], i
    segs.append((st, n, cur))

    merged = []
    for s, e, l in segs:
        if merged and e - s < 4:
            merged[-1] = (merged[-1][0], e, merged[-1][2])
        else:
            merged.append((s, e, l))
    return merged


def quiet_exit(segs):
    """Find first bar index ≥8 bars into a QUIET/BUILD section."""
    for s, e, l in segs:
        if l in ('QUIET', 'BUILD') and e - s >= 8:
            return s
    return None


def first_active(segs):
    """Find first bar index that is a DROP or ACTIVE section ≥8 bars long."""
    for s, e, l in segs:
        if l in ('DROP', 'ACTIVE') and e - s >= 8:
            return s
    return 0


# ============================================================
# RMS Stabilization
# ============================================================

def rms_stabilizer(blended, cf_len, sr=SR, thr=0.3, boost=1.3, kernel=3):
    """
    Smooth envelope with dynamic gain for deep RMS dips.

    Parameters
    ----------
    thr : float
        DIP threshold as fraction of median RMS (e.g. 0.5 = 50 % of median)
    boost : float
        Gain multiplier applied to DIP windows
    kernel : int
        Hann-smoothing kernel length in windows

    Returns
    -------
    blended : array_like
        RMS-stabilized audio
    """
    dw = int(0.1 * sr)        # 100 ms window
    nd = max(1, cf_len // dw - 2)
    rms = np.array([
        np.sqrt(np.mean(blended[j*dw:(j+1)*dw]**2))
        for j in range(nd)
    ])
    med = np.median(rms)
    ge = np.ones(nd)
    dc = 0

    # Recompute envelope via local-median lookahead
    for j in range(1, nd - 1):
        if rms[j] < thr * med:
            # Consecutive dips check
            if j > 0 and rms[j-1] < thr * med:
                continue  # allow slow fades
            lm = max(np.median(rms[max(0, j-2):j+3]), 1e-12)
            if lm > rms[j] * 1.5:
                ge[j] = min(boost, lm / (rms[j] + 1e-12))
                dc += 1
    if dc:
        from scipy.signal.windows import hann
        k = hann(kernel)
        k /= k.sum()
        ge = np.convolve(ge, k, mode='same')
        for j in range(nd):
            blended[j*dw:(j+1)*dw] *= ge[j]
    return blended


# ============================================================
# Mix Building
# ============================================================

def eq_pow(n):
    """Equal-power crossfade coefficients (cos², sin²)."""
    t = np.linspace(0, np.pi / 2, n).astype(np.float32)
    return np.cos(t), np.sin(t)


def onset_micro_align(master_mono, slave_mono, bpm, max_shift_sec=0.05,
                       m_db_zone=None, s_db_zone=None, sr=SR):
    """
    Micro-align slave onset energy to master in ±max_shift_sec window.

    Uses onset_strength cross-correlation.  If downbeat arrays (db_zone) are
    available, energy is weighted by downbeat positions (per-beat alignment).
    Otherwise, full-spectrum onset envelope is used.
    """
    hop = 128
    mo = librosa.onset.onset_strength(y=master_mono, sr=sr, hop_length=hop)
    so = librosa.onset.onset_strength(y=slave_mono, sr=sr, hop_length=hop)
    mo /= (mo.max() + 1e-8)
    so /= (so.max() + 1e-8)

    if m_db_zone is not None and s_db_zone is not None and len(m_db_zone) > 4 and len(s_db_zone) > 4:
        # Downbeat-weighted: highlight onset energy near downbeats
        m_db_sec = m_db_zone[:min(len(m_db_zone), 17)].astype(float) / sr
        s_db_sec = s_db_zone[:min(len(s_db_zone), 17)].astype(float) / sr
        mw = np.zeros_like(mo)
        sw = np.zeros_like(so)
        for db in m_db_sec:
            idx = int(db * sr / hop)
            if 0 <= idx < len(mw):
                mw[max(0, idx-2):min(len(mw), idx+3)] = 1.0
        for db in s_db_sec:
            idx = int(db * sr / hop)
            if 0 <= idx < len(sw):
                sw[max(0, idx-2):min(len(sw), idx+3)] = 1.0
        mo = mo * mw
        so = so * sw

    mh = int(max_shift_sec * sr / hop)
    corr = signal.fftconvolve(mo, so[::-1], mode='full')
    center = len(corr) // 2
    lo = max(0, center - mh)
    hi = min(len(corr), center + mh + 1)
    return (np.argmax(corr[lo:hi]) + lo - center) * hop


def warp_to_grid(slave_audio, s_db, m_db, sr=SR):
    """
    Bar-by-bar warp: each bar of slave is independently stretched to
    match the corresponding bar-length of master, using pyrubberband.

    Returns
    -------
    warped : ndarray | None
        Warped slave audio (padded/truncated to master bar grid)
    consumed : int
        Number of slave samples consumed (for position tracking)
    """
    nb = min(len(m_db) - 1, len(s_db) - 1)
    if nb < 2:
        return None, 0

    bars = []
    consumed = 0
    for i in range(nb):
        ml = int(m_db[i + 1]) - int(m_db[i])
        ss = int(s_db[i])
        se = int(s_db[i + 1])
        if se > len(slave_audio) or ml <= 0:
            break
        bar = slave_audio[ss:se].astype(np.float64)
        if len(bar) == 0:
            bars.append(np.zeros((ml, slave_audio.shape[1]), dtype=np.float32))
            consumed = se
            continue
        rate = len(bar) / ml
        if abs(rate - 1.0) > 0.002:
            w = pyrb.time_stretch(bar, sr, rate).astype(np.float32)
        else:
            w = bar.astype(np.float32)
        if len(w) >= ml:
            bars.append(w[:ml])
        else:
            bars.append(np.concatenate([w, np.zeros(
                (ml - len(w), slave_audio.shape[1]), dtype=np.float32)]))
        consumed = se
    if not bars:
        return None, 0
    return np.concatenate(bars), consumed


def build_cf_lr4(master_zone, slave_zone, m_bpm, s_bpm,
                  m_db, s_db, mode, sr=SR, cf_bars=16, tail_fade_bars=2):
    """
    Build a single crossfade transition using LR4 3-band crossover + bass swap.

    Parameters
    ----------
    master_zone : ndarray
        Master audio segment for the transition (≥ crossfade length)
    slave_zone : ndarray
        Slave audio segment for the transition (≥ crossfade length)
    m_bpm, s_bpm : float
        Master / slave BPM (from fix_ht)
    m_db, s_db : ndarray
        Master / slave downbeat arrays (start-aligned to zone)
    mode : str
        'hpss' for 3-band crossover + bass swap, otherwise simple power fade
    sr : int
        Sample rate
    cf_bars : int
        Number of bars for the crossfade
    tail_fade_bars : int
        Number of bars for tail fade-out at the end of the crossfade

    Returns
    -------
    blended : ndarray
        Crossfaded audio
    shift : float
        Residual onset alignment shift in seconds
    consumed : int
        Number of slave samples used for the warped portion
    """
    cf_len = int(cf_bars * bar_s(m_bpm) * sr)

    # ---- Pre-conditions for warp ----
    n_m = min(cf_bars + 1, len(m_db))
    n_s = min(cf_bars + 1, len(s_db))
    uw = n_m >= cf_bars and n_s >= cf_bars
    if uw:
        warped, c = warp_to_grid(slave_zone, s_db[:cf_bars + 1], m_db[:cf_bars + 1], sr)
        if warped is not None:
            s_zone = pt(warped, cf_len)
        else:
            uw = False

    if not uw:
        # Fallback: global stretch
        rate = m_bpm / s_bpm
        s_raw = pt(slave_zone, int(cf_bars * bar_s(s_bpm) * sr) + sr * 2)
        s_stretched = pyrb.time_stretch(s_raw.astype(np.float64), sr, rate).astype(np.float32)
        s_zone = pt(s_stretched, cf_len)
        c = int(cf_bars * bar_s(s_bpm) * sr)

    m_zone = pt(master_zone, cf_len)

    # 2. Residual micro-align (+/-50ms window, downbeat-weighted)
    mm = m_zone.mean(1)
    sm = s_zone.mean(1)
    shift = onset_micro_align(
        mm, sm, m_bpm, max_shift_sec=0.05,
        m_db_zone=m_db[:cf_bars + 1] if n_m >= cf_bars else None,
        s_db_zone=s_db[:cf_bars + 1] if n_s >= cf_bars else None,
        sr=sr
    )
    print(f"    Residual shift after warp: {shift/sr*1000:.1f}ms")

    if abs(shift) > 0:
        if int(shift) > 0:
            s_zone = np.concatenate(
                [s_zone[int(shift):], np.zeros((int(shift), 2), dtype=np.float32)]
            )
        else:
            s_zone = np.concatenate(
                [np.zeros((-int(shift), 2), dtype=np.float32), s_zone[:-int(shift)]]
            )

    # 3. LR4 3-band split & bass swap
    if mode == 'hpss':
        print("    LR4 3-Band split & Bass Swap...", flush=True)
        ml, mm, mh = three_band_split(m_zone, 150.0, 3000.0, sr)
        sl, sm, sh = three_band_split(s_zone, 150.0, 3000.0, sr)

        # ---- Bass polarity check ----
        bs = int(bar_s(m_bpm) * sr)
        sc = cf_len // 2
        bw = int(0.10 * sr)
        aw = ml[sc - bw:sc + bw].flatten()
        bl2 = sl[sc - bw:sc + bw].flatten()
        if len(aw) == len(bl2) and len(aw) > 0:
            co = np.corrcoef(aw, bl2)[0, 1]
            print(f"    Bass polarity: corr={co:.2f}", end='')
            if co < -0.3:
                sl = -sl
                print(" → INVERTED")
            else:
                print(" → OK")

        # ---- Bass swap + mid/high power crossfade ----
        fo, fi = eq_pow(cf_len)
        bm = mm * fo[:, None] + sm * fi[:, None]
        bh = mh * fo[:, None] + sh * fi[:, None]

        tw = int(1.5 * bs)
        sw = max(0, sc - tw // 2)
        ew = min(cf_len, sc + tw // 2)
        aw2 = ew - sw
        sfo, sfi = eq_pow(aw2)

        bl_new = np.zeros_like(ml)
        bl_new[:sw] = ml[:sw]
        bl_new[sw:ew] = ml[sw:ew] * sfo[:, None] + sl[sw:ew] * sfi[:, None]
        bl_new[ew:] = sl[ew:]

        blended = bl_new + bm + bh
        blended = rms_stabilizer(blended, cf_len, sr)
    else:
        fo, fi = eq_pow(cf_len)
        blended = m_zone * fo[:, None] + s_zone * fi[:, None]

    # Tail fade-out
    tbs = int(tail_fade_bars * bar_s(m_bpm) * sr)
    if tbs < cf_len:
        tf = np.linspace(1.0, 0.0, tbs).astype(np.float32)
        blended[-tbs:] *= (fo[-tbs:] * tf + (1.0 - fo[-tbs:]))[:, None]

    pk = np.max(np.abs(blended))
    if pk > 0.99:
        blended *= 0.99 / pk
    return blended, shift / sr, c


def ramp_to_native(slave_audio, s_db, m_bpm, s_bpm, sr=SR,
                    ramp_sec=15, slave_entry_rms=1.0):
    """
    After a crossfade, gradually stretch slave from master BPM back to
    native BPM over ramp_sec seconds (bar-by-bar).  If slave_entry_rms
    is below RAMP_MIN_RMS, do a simple volume fade instead.
    """
    RAMP_MIN_RMS = 0.08

    if abs(m_bpm - s_bpm) < 0.5:
        return None, 0

    if slave_entry_rms < RAMP_MIN_RMS:
        fade_samples = int(ramp_sec * sr)
        fade_samples = min(fade_samples, len(slave_audio))
        fd = np.linspace(0.0, 1.0, fade_samples).astype(np.float32)
        faded = slave_audio[:fade_samples].copy().astype(np.float32) * fd[:, None]
        print(f"    Volume fade (quiet entry rms={slave_entry_rms:.4f}): {fade_samples/sr:.1f}s")
        return faded, fade_samples

    m_bar = (240.0 / m_bpm) * sr
    s_bar = (240.0 / s_bpm) * sr
    nb = min(int(ramp_sec / (240.0 / s_bpm)) + 1, len(s_db) - 1)
    if nb < 2:
        return None, 0

    bars = []
    consumed = 0
    for i in range(nb):
        t = i / max(1, nb - 1)
        tl = int(m_bar + t * (s_bar - m_bar))
        st = int(s_db[i])
        en = int(s_db[i + 1])
        if en > len(slave_audio) or tl <= 0:
            break
        bar = slave_audio[st:en]
        if len(bar) == 0:
            consumed = en
            continue
        rate = len(bar) / tl
        if abs(rate - 1.0) > 0.002:
            w = pyrb.time_stretch(bar.astype(np.float64), sr, rate).astype(np.float32)
        else:
            w = bar.astype(np.float32)
        if len(w) >= tl:
            bars.append(w[:tl])
        else:
            bars.append(np.concatenate([w, np.zeros(
                (tl - len(w), slave_audio.shape[1]), dtype=np.float32)]))
        consumed = en
    if not bars:
        return None, 0
    result = np.concatenate(bars)
    print(f"    BPM ramp: {m_bpm:.1f}->{s_bpm:.1f} over {len(result)/sr:.1f}s ({nb} bars)")
    return result, consumed


# ============================================================
# Main Mixing Pipeline
# ============================================================

def smart_mix(tracks, sr=SR, wav_dir="", ann_dir="",
              cf_bars=16, ramp_sec=15, tail_fade_bars=2,
              use_quiet_exit=True, no_stabilizer=False,
              style="", author=""):
    """
    Run the full smart mixing pipeline over a track list.

    Parameters
    ----------
    tracks : list of (name, wav_file, ann_file)
        Track list : (track_name, filename.wav, annotation.txt)
    sr : int
        Target sample rate
    wav_dir : str
        Path to WAV directory
    ann_dir : str
        Path to annotation directory
    cf_bars : int
        Crossfade duration in bars
    ramp_sec : int
        BPM ramp-back duration in seconds
    tail_fade_bars : int
        Tail fade length in bars
    use_quiet_exit : bool
        Whether to find QUIET/BUILD section for exit point
    no_stabilizer : bool
        Skip RMS stabilizer if True
    style : str
        Mix style label (for output filename)
    author : str
        Author label (for output filename)

    Returns
    -------
    mix : ndarray
        Final mixed audio
    stamps : list of dict
        Transition stamps for mix_analyzer
    """
    print("=" * 60)
    print("  Smart Mixer")
    print("=" * 60)

    # ---- Load, normalise, analyse each track ----
    t_start = time.time()
    track_data = []

    for name, wav_file, ann_file in tracks:
        print(f"\n  {name}:")
        t0 = time.time()
        audio = load_stereo(f'{wav_dir}/{wav_file}', sr)
        db = load_dbeats(f'{ann_dir}/{ann_file}', sr)
        raw = calc_bpm(db, sr)
        db, bpm = fix_ht(db, raw)
        print(f"    Detected BPM: {bpm:.1f} (in {time.time()-t0:.1f}s)")

        # Key detection + Camelot
        t_key = time.time()
        from essentia.standard import Key, KeyExtractor
        import essentia

        mono = audio.mean(1)
        # Estimate key via essentia
        key_extractor = KeyExtractor(
            profile='diy',
            frameSize=4096,
            hopSize=2048,
            maximumTuningDeviation=20
        )
        key, scale, strength = key_extractor(mono)

        # Map to Camelot
        camelot_map = {
            'C': '8B', 'G': '9B', 'D': '10B', 'A': '11B', 'E': '12B', 'B': '1B',
            'F#': '2B', 'C#': '3B', 'G#': '4B', 'D#': '5B', 'A#': '6B', 'F': '7B',
            'c': '5A', 'g': '6A', 'd': '7A', 'a': '8A', 'e': '9A', 'b': '10A',
            'f#': '11A', 'c#': '12A', 'g#': '1A', 'd#': '2A', 'a#': '3A', 'f': '4A',
        }
        camelot = camelot_map.get(key, '?')
        print(f"    Key: {key} {scale} → Camelot {camelot} ({time.time()-t_key:.1f}s)")

        # LUFS normalisation (first 30s reference, then normalise to -14 LUFS)
        t_loud = time.time()
        meter = pyln.Meter(sr)
        loud = meter.integrated_loudness(
            audio[:int(min(30 * sr, len(audio)))].astype(np.float64)
        )
        if loud != float('-inf'):
            audio_out = pyln.normalize.loudness(
                audio.astype(np.float64), loud, -14.0
            ).astype(np.float32)
            pk = np.max(np.abs(audio_out))
            if pk > 0.99:
                audio_out *= 0.99 / pk
        else:
            audio_out = audio.astype(np.float32)
        print(f"    LUFS: {loud:.1f} → -14 (in {time.time()-t_loud:.1f}s)")

        # Structural analysis
        t_sec = time.time()
        segs = sections(audio_out, db)
        qe_idx = quiet_exit(segs) if use_quiet_exit else None
        fa_idx = first_active(segs)
        dur = len(audio_out) / sr

        # Extract segment boundaries
        exit_bar = max(0, qe_idx - 2) if qe_idx is not None else max(0, len(db) - cf_bars - 4)
        entry_bar = fa_idx

        # Ensure multiples of 16 for phrase alignment
        exit_bar = (exit_bar // 16) * 16
        print(f"    Segment: {dur/60:.1f} min  exit_bar={exit_bar} entry_bar={entry_bar}")
        print(f"    → Q:{[l for s,e,l in segs if e-s>=4]}")

        track_data.append({
            'name': name,
            'audio': audio_out,
            'db': db,
            'bpm': bpm,
            'key': key,
            'scale': scale,
            'camelot': camelot,
            'exit_bar': exit_bar,
            'entry_bar': entry_bar,
            'segs': segs,
        })

    # ---- Build transitions ----
    print(f"\n{'='*60}")
    print("  Building transitions...")
    print('='*60)

    mix_parts = []
    stamps = []
    mix_pos = 0  # sample position in final mix

    cur = track_data[0]
    cur_offset = 0  # where we are in current track's audio

    for i in range(1, len(track_data)):
        nxt = track_data[i]
        mb, sb = cur['bpm'], nxt['bpm']
        bpm_diff = abs(sb - mb) / mb
        print(f"\n  {cur['name']} ({mb:.1f} BPM) → {nxt['name']} ({sb:.1f} BPM)  diff={bpm_diff*100:.1f}%")

        # Skip if BPM mismatch > 8%
        if bpm_diff > 0.08:
            print(f"    BPM diff too large → direct cut")
            body = cur['audio'][cur_offset:]
            mix_parts.append(body)
            mix_pos += len(body)
            cur = nxt
            cur_offset = 0
            continue

        cf_len = int(cf_bars * bar_s(mb) * sr)
        total_bars = len(cur['db']) - 1

        # Exit point
        exit_bar = cur['exit_bar']
        if exit_bar <= 0 or exit_bar < cf_bars + 4:
            exit_bar = max(0, total_bars - cf_bars - 4)
            exit_bar = (exit_bar // 16) * 16

        exit_samp = int(cur['db'][min(exit_bar, len(cur['db']) - 1)])
        entry_bar = nxt['entry_bar']
        entry_samp = int(nxt['db'][min(entry_bar, len(nxt['db']) - 1)])

        mode = 'hpss'
        print(f"    Exit bar {exit_bar} ({exit_samp/sr:.1f}s)  Entry bar {entry_bar} ({entry_samp/sr:.1f}s)  mode={mode}")

        # Master crossfade zone
        m_cf = cur['audio'][exit_samp:exit_samp + cf_len + sr * 3]
        m_db = cur['db'][cur['db'] >= exit_samp] - exit_samp

        # Slave crossfade zone
        s_cf = nxt['audio'][entry_samp:]
        s_db = nxt['db'][nxt['db'] >= entry_samp] - entry_samp

        # Entry RMS (for ramp decision)
        ec = int(2 * bar_s(sb) * sr)
        entry_rms = float(np.sqrt(np.mean(
            (nxt['audio'][entry_samp:entry_samp + ec] if ec < len(nxt['audio'][entry_samp:])
             else nxt['audio'][entry_samp:]) ** 2
        )))

        # Build crossfade
        blended, shift, consumed = build_cf_lr4(
            m_cf, s_cf, mb, sb, m_db, s_db, mode, sr,
            cf_bars=cf_bars, tail_fade_bars=tail_fade_bars
        )

        ts = (mix_pos + len(mix_parts[-1] if mix_parts else [])) / sr if mix_parts else 0
        stamps.append({
            'from': cur['name'],
            'to': nxt['name'],
            't': ts,
            'dur': cf_bars * bar_s(mb),
            'mode': mode,
            'shift': shift,
            'entry_rms': entry_rms,
            'camelot_from': cur['camelot'],
            'camelot_to': nxt['camelot'],
        })

        # Body before crossfade
        if cur_offset < exit_samp:
            body = cur['audio'][cur_offset:exit_samp]
            mix_parts.append(body)

        mix_parts.append(blended)
        mix_pos += len(body) + len(blended) if 'body' in dir() else len(blended)
        cur = nxt

        # BPM ramp after crossfade
        ramp_offset = entry_samp + consumed
        ramp_audio = nxt['audio'][ramp_offset:]
        ramp_db = nxt['db'][nxt['db'] >= ramp_offset] - ramp_offset
        ramp_result, ramp_consumed = ramp_to_native(
            ramp_audio, ramp_db, mb, sb, sr,
            ramp_sec=ramp_sec, slave_entry_rms=entry_rms
        )

        if ramp_result is not None:
            # Check if audio content crosses boundary cleanly
            # Crossfade last part of blended with start of ramp
            xfade_samples = min(int(0.5 * sr), len(blended) - 500, len(ramp_result) - 500)
            if xfade_samples > 0:
                blended[-xfade_samples:] *= np.linspace(1.0, 0.0, xfade_samples).astype(np.float32)[:, None]
                ramp_result[:xfade_samples] *= np.linspace(0.0, 1.0, xfade_samples).astype(np.float32)[:, None]
                print(f"    blend→ramp xfade: {xfade_samples/sr:.1f}s")
            mix_parts.append(ramp_result)
            mix_pos += len(ramp_result)
            cur_offset = ramp_offset + ramp_consumed
        else:
            cur_offset = ramp_offset

        # Safety: don't run off end of track
        if cur_offset >= len(cur['audio']):
            cur_offset = entry_samp + int(cf_bars * bar_s(sb) * sr) // 2

        print(f"    Continued at {cur_offset/sr:.1f}s")

    # ---- Final tail ----
    if cur_offset < len(cur['audio']):
        tail = cur['audio'][cur_offset:]
        mix_parts.append(tail)

    # ---- Consolidate ----
    mix = np.concatenate([p for p in mix_parts if len(p) > 0])

    # Master peak normalisation to -1 dB
    pk = np.max(np.abs(mix))
    if pk > 0:
        mix *= (10 ** (-1 / 20) / pk)
    mix = np.clip(mix, -1.0, 1.0)

    duration = len(mix) / sr
    print(f"\n{'='*60}")
    print(f"  Mix complete: {int(duration//60)}:{int(duration%60):02d}")
    print(f"  Transitions: {len(stamps)}")
    print('='*60)

    return mix, stamps


# ============================================================
# CLI Entry Point
# ============================================================

def main():
    """Parse CLI arguments and run the mixer."""
    import argparse

    parser = argparse.ArgumentParser(description='Smart DJ Mixer')
    parser.add_argument('--config', help='Path to config file (e.g. mix_config.py)')
    parser.add_argument('--wav-dir', default='wav', help='WAV directory')
    parser.add_argument('--ann-dir', default='ann', help='Annotation directory')
    parser.add_argument('--output', default='', help='Output MP3 path')
    parser.add_argument('--no-stabilizer', action='store_true', help='Skip RMS stabilizer')
    parser.add_argument('--style', default='', help='Mix style label')
    parser.add_argument('--author', default='', help='Author name')
    parser.add_argument('--cf-bars', type=int, default=16, help='Crossfade length in bars')
    parser.add_argument('--ramp-sec', type=int, default=15, help='BPM ramp duration')
    parser.add_argument('--tail-fade-bars', type=int, default=2, help='Tail fade bars')
    parser.add_argument('--use-quiet-exit', action='store_true', default=True,
                        help='Find quiet exit point (default: on)')
    args = parser.parse_args()

    # Load config if provided
    tracks = []
    sr = SR

    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"Config file not found: {args.config}")
            sys.exit(1)

        # Read config variables
        config_vars = {}
        exec(open(config_path).read(), config_vars)
        tracks = config_vars.get('TRACKS', [])
        sr = config_vars.get('SR', SR)
        if not tracks and 'tracks' in config_vars:
            tracks = config_vars['tracks']
        print(f"Loaded config: {config_path}")
        print(f"  Tracks: {len(tracks)}")
        print(f"  SR: {sr}")

    if not tracks:
        print("No tracks defined. Use --config or provide TRACKS list in config.")
        sys.exit(1)

    wav_dir = args.wav_dir
    ann_dir = args.ann_dir

    # Run mix
    mix, stamps = smart_mix(
        tracks, sr=sr, wav_dir=wav_dir, ann_dir=ann_dir,
        cf_bars=args.cf_bars, ramp_sec=args.ramp_sec,
        tail_fade_bars=args.tail_fade_bars,
        use_quiet_exit=args.use_quiet_exit,
        no_stabilizer=args.no_stabilizer,
        style=args.style, author=args.author
    )

    # Export
    if not args.output:
        date_str = time.strftime('%Y-%m-%d')
        style_label = f"_{args.style}" if args.style else ""
        author_label = f"_{args.author}" if args.author else ""
        args.output = f"Mix_{date_str}{style_label}{author_label}.wav"

    wav_path = args.output
    mp3_path = wav_path.replace('.wav', '.mp3')

    print(f"\nExporting {wav_path}...")
    sf.write(wav_path, mix, sr, subtype='PCM_24')

    # Convert to MP3 320kbps
    if shutil.which('ffmpeg'):
        print(f"Converting to MP3: {mp3_path}")
        subprocess.run([
            'ffmpeg', '-y', '-i', wav_path,
            '-b:a', '320k',
            '-id3v2_version', '3',
            '-metadata', f'title={os.path.basename(mp3_path)}',
            '-metadata', f'artist={args.author or "SmartMixer"}',
            mp3_path
        ], check=True)
        size_mb = os.path.getsize(mp3_path) / 1e6
        print(f"Done: {mp3_path} ({size_mb:.1f} MB)")
    else:
        print(f"No ffmpeg found — keeping WAV: {wav_path}")

    # Save stamps for analyzer
    stamps_path = wav_path.replace('.wav', '_stamps.npy')
    np.save(stamps_path, np.array(stamps, dtype=object))
    print(f"Stamps saved: {stamps_path}")

    # Print transition table
    print(f"\n{'='*60}")
    print("  Transition Table")
    print('='*60)
    for i, st in enumerate(stamps):
        t_start = st['t']
        t_end = t_start + st['dur']
        m, s = int(t_start // 60), int(t_start % 60)
        m2, s2 = int(t_end // 60), int(t_end % 60)
        print(f"  {i+1}. {m:02d}:{s:02d}-{m2:02d}:{s2:02d}  "
              f"{st['from']} → {st['to']}  "
              f"shift={st['shift']*1000:.1f}ms  "
              f"entry_rms={st.get('entry_rms', 0):.4f}  "
              f"Camelot: {st.get('camelot_from', '?')}→{st.get('camelot_to', '?')}")

    return 0


if __name__ == '__main__':
    import shutil
    sys.exit(main())