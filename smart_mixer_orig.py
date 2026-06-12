#!/usr/bin/env python3
"""
Smart Mixer v7+v13 (Bar-by-Bar Warp + LR4 Crossover + Narrow RMS + Seamless blend→ramp)
Combines v7 argparse/track-loading with v13 algorithm improvements.

Usage:
  python3 smart_mixer.py --wav-dir ./wav --ann-dir ./annotations --output mix.mp3

Or configure via a Python config file:
  python3 smart_mixer.py --config mix_config.py
"""

import sys, os, time, subprocess, argparse
from datetime import datetime

import numpy as np
np.float = np.float64
np.int = np.int64
np.complex = np.complex128
np.bool = np.bool_

import soundfile as sf
import scipy.signal as signal
import pyrubberband as pyrb
import librosa
import pyloudnorm as pyln

# Ensure rubberband is in PATH
os.environ['PATH'] = '/tmp/rubberband-extract/usr/bin:' + os.environ.get('PATH', '')

SR = 44100
CF_BARS = 16                # Crossfade duration in bars
RAMP_SEC = 15               # Post-crossfade BPM ramp-back duration (seconds)
RAMP_MIN_RMS = 0.08         # If entry RMS below this, volume-only fade instead of BPM ramp
TAIL_FADE_BARS = 0          # Redundant with seamless blend→ramp (17th bar warp bridge)
TARGET_LUFS = -14.0         # Loudness normalization target
BPM_DIFF_LIMIT = 0.08       # Max BPM difference ratio for crossfade (8%)


# ============================================================
# Key Detection + Camelot Wheel (from analyze_order.py)
# ============================================================

CAMELOT = {
    'C maj':'8B','C# maj':'3B','D maj':'10B','D# maj':'5B','E maj':'12B',
    'F maj':'7B','F# maj':'2B','G maj':'9B','G# maj':'4B','A maj':'11B',
    'A# maj':'6B','B maj':'1B',
    'C min':'5A','C# min':'12A','D min':'7A','D# min':'2A','E min':'9A',
    'F min':'4A','F# min':'11A','G min':'6A','G# min':'1A','A min':'8A',
    'A# min':'3A','B min':'10A',
}

KEYS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
MAJ_PROFILE = [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
MIN_PROFILE = [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]

def detect_key(audio_mono, sr):
    """Detect musical key via chroma CQT + Krumhansl-Schmuckler profiles."""
    chroma = librosa.feature.chroma_cqt(y=audio_mono, sr=sr)
    profile = chroma.mean(axis=1)
    best_corr = -1
    best_key = "?"
    for shift in range(12):
        rolled = np.roll(profile, -shift)
        cm = np.corrcoef(rolled, MAJ_PROFILE)[0, 1]
        cn = np.corrcoef(rolled, MIN_PROFILE)[0, 1]
        if cm > best_corr:
            best_corr = cm
            best_key = f"{KEYS[shift]} maj"
        if cn > best_corr:
            best_corr = cn
            best_key = f"{KEYS[shift]} min"
    return best_key

def camelot_code(key_str):
    """Convert key string to Camelot code (e.g. 'D maj' → '10B')."""
    return CAMELOT.get(key_str, '?')

def key_compat(k1, k2):
    """Camelot compatibility score: 1.0 (same), 0.9 (adjacent), 0.8 (relative), 0.3 (bad)."""
    c1 = camelot_code(k1)
    c2 = camelot_code(k2)
    if '?' in (c1, c2):
        return 0.5
    n1, t1 = int(c1[:-1]), c1[-1]
    n2, t2 = int(c2[:-1]), c2[-1]
    if c1 == c2:
        return 1.0
    if t1 == t2 and abs(n1 - n2) in (1, 11):
        return 0.9
    if n1 == n2 and t1 != t2:
        return 0.8
    return 0.3

def three_band_split(audio, low_cut, high_cut, sr):
    """
    Splits audio into Low, Mid, and High bands using filtfilt
    and 4th-order Linkwitz-Riley crossovers for zero phase-distortion reconstruction.
    """
    nyq = 0.5 * sr
    b_low, a_low = signal.butter(2, low_cut / nyq, btype='low')
    b_high, a_high = signal.butter(2, high_cut / nyq, btype='high')

    low = np.zeros_like(audio, dtype=np.float32)
    high = np.zeros_like(audio, dtype=np.float32)

    for ch in range(audio.shape[1]):
        x = audio[:, ch].astype(np.float64)
        low[:, ch] = signal.filtfilt(b_low, a_low, x).astype(np.float32)
        high[:, ch] = signal.filtfilt(b_high, a_high, x).astype(np.float32)

    mid = audio - low - high
    return low, mid, high


# ============================================================
# Audio Helpers
# ============================================================

def load_stereo(path, sr=SR):
    """Load stereo WAV, convert mono to stereo, resample if needed."""
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
        os.unlink(tmp)
    return data.astype("float32")


def norm_lufs(audio, target=TARGET_LUFS, sr=SR):
    """Loudness normalize to target LUFS using full audio."""
    meter = pyln.Meter(sr)
    loud = meter.integrated_loudness(audio.astype("float64"))
    if loud == float('-inf'):
        return audio
    n = pyln.normalize.loudness(audio.astype("float64"), loud, target).astype("float32")
    pk = np.max(np.abs(n))
    if pk > 0.99:
        n *= 0.99 / pk
    return n


def pt(a, n):
    """Pad or trim array to length n."""
    if len(a) >= n:
        return a[:n]
    sh = list(a.shape)
    sh[0] = n - len(a)
    return np.concatenate([a, np.zeros(sh, dtype=a.dtype)])


def bar_s(bpm):
    """Duration of one bar (4 beats) in seconds."""
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
    iv = iv[iv > 0.3]
    if not len(iv):
        return 120.0
    p25, p75 = np.percentile(iv, [25, 75])
    ok = iv[(iv >= p25 - 1.5 * (p75 - p25)) & (iv <= p75 + 1.5 * (p75 - p25))]
    return 4 * 60.0 / np.mean(ok) if len(ok) else 120.0


def fix_ht(db, bpm):
    """
    Fix half-time (or double-time) BPM detection by checking beat-to-beat
    distance ratios against expected 4-beat-bar spacing.
    """
    if len(db) < 8:
        return db, bpm
    ns = int(db[8]) - int(db[4])
    if ns <= 0:
        return db, bpm
    ratio = ns / max(int(bar_s(bpm) * SR / 4), 1)

    if 1.9 < ratio < 2.1:
        # Half-time detected: skip every other downbeat to go from 1 every 2 beats → 1 per beat
        db = db[::2]
    elif 2.9 < ratio < 3.1:
        # Third-time detected
        db = db[::3]
    elif 0.45 < ratio < 0.55:
        # Double-time detected: insert a downbeat midway between each pair
        dl = []
        for d in db:
            dl.extend([d, d + (db[1] - db[0]) // 2])
        db = np.array(dl, dtype=int)

    return db, calc_bpm(db)


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

    sc = []
    cur = lb[0]
    s = 0
    for i in range(1, n):
        if lb[i] != cur:
            sc.append((s, i, cur))
            cur = lb[i]
            s = i
    sc.append((s, n, cur))

    # Merge short sections (<4 bars) into neighbors
    mg = []
    for s, e, l in sc:
        if mg and e - s < 4:
            mg[-1] = (mg[-1][0], e, mg[-1][2])
        else:
            mg.append((s, e, l))

    if name:
        for s, e, l in mg:
            t1 = db[s] / sr
            t2 = db[min(e, len(db) - 1)] / sr
            print(
                f"    {int(t1 // 60)}:{int(t1 % 60):02d}-"
                f"{int(t2 // 60)}:{int(t2 % 60):02d}  "
                f"bars {s:3d}-{e:3d} ({e-s:2d})  {l}"
            )
    return mg


def quiet_exit(secs):
    """Find a quiet/build section in the second half suitable for exit."""
    for s, e, l in secs:
        if l in ('QUIET', 'BUILD') and e - s >= 8:
            return s
    return None


def first_active(secs, mn=8):
    """Find first active/drop section with at least mn bars."""
    for s, e, l in secs:
        if l in ('DROP', 'ACTIVE') and e - s >= mn:
            return s
    return 0


# ============================================================
# Onset & Phase Micro-alignment (v13: downbeat-weighted)
# ============================================================

def onset_micro_align(m_mono, s_mono, bpm, max_shift_sec=0.05,
                      m_db_zone=None, s_db_zone=None, sr=SR):
    """
    Sub-bar transient alignment using onset strength cross-correlation.
    Downbeat frames weighted at 1.0, others at 0.3 for sharper alignment.

    Args:
        m_db_zone, s_db_zone: downbeat sample positions for weighting
    """
    hop = 128
    mo = librosa.onset.onset_strength(y=m_mono.astype(np.float32), sr=sr, hop_length=hop)
    so = librosa.onset.onset_strength(y=s_mono.astype(np.float32), sr=sr, hop_length=hop)

    # Downbeat-weight: frames at downbeat positions get 1.0, others 0.3
    if m_db_zone is not None and len(m_db_zone) > 1:
        wm = np.full_like(mo, 0.3)
        for db_s in m_db_zone:
            df = int(db_s / hop)
            if 0 <= df < len(wm):
                wm[df] = 1.0
        mo *= wm
    if s_db_zone is not None and len(s_db_zone) > 1:
        ws = np.full_like(so, 0.3)
        for db_s in s_db_zone:
            df = int(db_s / hop)
            if 0 <= df < len(ws):
                ws[df] = 1.0
        so *= ws

    mo /= (mo.max() + 1e-8)
    so /= (so.max() + 1e-8)

    max_hop_shift = int(max_shift_sec * sr / hop)
    corr = signal.fftconvolve(mo, so[::-1], mode='full')
    center = len(corr) // 2

    lo = max(0, center - max_hop_shift)
    hi = min(len(corr), center + max_hop_shift + 1)

    best = np.argmax(corr[lo:hi]) + lo - center
    return best * hop


# ============================================================
# Bar-by-Bar Warp (v13: CF_BARS+1 for extra bar)
# ============================================================

def warp_to_grid(slave_audio, s_db, m_db, sr):
    """
    Bar-by-bar time warp: stretch each slave bar to exactly match
    the corresponding master bar length. Eliminates phase drift
    accumulation over 16-bar crossfades.

    rate = s_bar_len / m_bar_len  (pyrubberband speed multiplier)
      >1: slave bar longer than master -> speed up
      <1: slave bar shorter than master -> slow down
    """
    n_bars = min(len(m_db) - 1, len(s_db) - 1)
    if n_bars < 2:
        return None, 0

    # Compute master bar lengths and smooth outliers
    m_raw_lens = np.array([int(m_db[i + 1]) - int(m_db[i]) for i in range(n_bars)])
    m_med = np.median(m_raw_lens)
    # Clamp outliers to ±25% of median (annotation jitter protection)
    m_lens = np.where((m_raw_lens > m_med * 0.75) & (m_raw_lens < m_med * 1.25),
                      m_raw_lens, int(m_med))

    bars = []
    consumed = 0
    for i in range(n_bars):
        m_bar_len = int(m_lens[i])
        s_start = int(s_db[i])
        s_end = int(s_db[i + 1])
        if s_end > len(slave_audio) or m_bar_len <= 0:
            break
        bar = slave_audio[s_start:s_end].astype("float64")
        if len(bar) == 0:
            bars.append(np.zeros((m_bar_len, slave_audio.shape[1]), dtype="float32"))
            consumed = s_end
            continue

        rate = len(bar) / m_bar_len
        if abs(rate - 1.0) > 0.002:
            warped = pyrb.time_stretch(bar, sr, rate).astype("float32")
        else:
            warped = bar.astype("float32")

        if len(warped) >= m_bar_len:
            bars.append(warped[:m_bar_len])
        else:
            pad = np.zeros((m_bar_len - len(warped), slave_audio.shape[1]), dtype="float32")
            bars.append(np.concatenate([warped, pad]))
        consumed = s_end

    if not bars:
        return None, 0
    return np.concatenate(bars), consumed


# ============================================================
# BPM Ramp-back
# ============================================================

def ramp_to_native(slave_audio, s_db, m_bpm, s_bpm, sr, ramp_sec=RAMP_SEC, ser=1.0):
    """
    After crossfade, the slave was warped to master BPM.
    Smoothly ramp it back to native BPM over ramp_sec seconds.
    Linear interpolation: bar length goes from master-bar to native-bar.

    If ser (entry RMS) is below RAMP_MIN_RMS, do a simple volume fade instead.
    """
    bpm_diff = abs(m_bpm - s_bpm)
    if bpm_diff < 0.5:
        return None, 0

    if ser < RAMP_MIN_RMS:
        fs = int(ramp_sec * sr)
        fs = min(fs, len(slave_audio))
        fd = np.linspace(0.0, 1.0, fs).astype("float32")
        faded = slave_audio[:fs].copy().astype("float32") * fd[:, None]
        print(f"    Volume fade (quiet rms={ser:.4f}): {fs/sr:.1f}s")
        return faded, fs

    m_bar_samp = bar_s(m_bpm) * sr
    s_bar_samp = bar_s(s_bpm) * sr

    n_bars_needed = int(ramp_sec / bar_s(s_bpm)) + 1
    n_bars = min(n_bars_needed, len(s_db) - 1)
    if n_bars < 2:
        return None, 0

    bars = []
    consumed = 0
    for i in range(n_bars):
        t = i / max(1, n_bars - 1)
        target_len = int(m_bar_samp + t * (s_bar_samp - m_bar_samp))

        s_start = int(s_db[i])
        s_end = int(s_db[i + 1])
        if s_end > len(slave_audio) or target_len <= 0:
            break
        bar = slave_audio[s_start:s_end]
        if len(bar) == 0:
            consumed = s_end
            continue

        rate = len(bar) / target_len
        if abs(rate - 1.0) > 0.002:
            warped = pyrb.time_stretch(bar.astype("float64"), sr, rate).astype("float32")
        else:
            warped = bar.astype("float32")

        if len(warped) >= target_len:
            bars.append(warped[:target_len])
        else:
            pad = np.zeros((target_len - len(warped), bar.shape[1]), dtype="float32")
            bars.append(np.concatenate([warped, pad]))
        consumed = s_end

    if not bars:
        return None, 0
    result = np.concatenate(bars)
    print(f"    BPM ramp: {m_bpm:.1f}->{s_bpm:.1f} over {len(result)/sr:.1f}s ({n_bars} bars)")
    return result, consumed


# ============================================================
# RMS Stabilizer with Lookahead (v13: narrow + lookahead)
# ============================================================

def rms_stabilizer_lookahead(blended, cf_len):
    """
    Narrow RMS stabilizer + lookahead:
    Only boosts dips < 0.3*median with a sharp drop (>30%) and quick recovery.
    Also checks next 3 windows for a recovery >2x (lookahead).
    Uses Hann kernel size=3 for shorter smoothing.
    """
    dw = int(0.1 * SR)
    nd = max(1, cf_len // dw - 2)
    rms = np.array([
        np.sqrt(np.mean(blended[j*dw:(j+1)*dw]**2)) for j in range(nd)
    ])
    med = np.median(rms)
    ge = np.ones(nd)
    dc = 0

    for j in range(1, nd - 1):
        if rms[j] < 0.3 * med:
            # Check sharp drop
            sharp = rms[j-1] > 0 and (rms[j-1] - rms[j]) / rms[j-1] > 0.3
            qr = False
            for k in range(j + 1, min(j + 4, nd)):
                if rms[k] > rms[j] * 1.5:
                    qr = True
                    break

            if sharp and qr:
                lm = max(np.median(rms[max(0, j-2):j+3]), 1e-12)
                if lm > rms[j] * 1.5:
                    ge[j] = min(1.3, lm / (rms[j] + 1e-12))
                    dc += 1
            # Lookahead: dips that precede a big rise
            elif rms[j] < 0.3 * med:
                for k in range(j + 1, min(j + 4, nd)):
                    if rms[k] > rms[j] * 2.0:
                        lm = max(np.median(rms[max(0, j-2):j+3]), 1e-12)
                        if lm > rms[j] * 1.5:
                            ge[j] = min(1.3, lm / (rms[j] + 1e-12))
                            dc += 1
                        break

    if dc:
        from scipy.signal.windows import hann
        k = hann(3)
        k /= k.sum()
        ge = np.convolve(ge, k, mode='same')
        for j in range(nd):
            blended[j*dw:(j+1)*dw] *= ge[j]
        print(f"    RMS stabilizer: {dc} dips (narrow+lookahead)")

    return blended


# ============================================================
# Equal-Power Fade Shapes
# ============================================================

def eq_pow(n):
    """Return cos²/sin² fade curves (power-law fades, fo²+fi²=1 at all points)."""
    t = np.linspace(0, np.pi / 2, n).astype("float32")
    return np.cos(t), np.sin(t)


# ============================================================
# Crossfade Builder (v13: bass polarity, warp_extra, narrow RMS)
# ============================================================

def build_cf_lr4(m_cf, s_cf, m_bpm, s_bpm, m_db, s_db, mode, sr=SR, stabilizer=True):
    """
    Build crossfade with LR4 3-band bass swap.

    mode='hpss': LR4 bass swap (bass switches instantly, mids/highs crossfade)
    mode='quiet': simple equal-power crossfade

    Returns:
        blended, shift, consumed, warp_extra
        warp_extra: saved 17th bar of warp for seamless blend→ramp transition
    """
    cf_len = int(CF_BARS * bar_s(m_bpm) * sr)

    # 1. Bar-by-bar warp (primary method) — use CF_BARS+2 for an extra bar
    #    (CF_BARS+1 downbeats → CF_BARS bars; CF_BARS+2 downbeats → CF_BARS+1 bars,
    #     giving a real 1-bar warp_extra for seamless blend→ramp bridge)
    n_m = min(CF_BARS + 2, len(m_db))
    n_s = min(CF_BARS + 2, len(s_db))
    use_barwarp = (n_m >= CF_BARS + 1 and n_s >= CF_BARS + 1)
    warp_extra = None

    if use_barwarp:
        m_db_zone = m_db[:CF_BARS + 2]
        s_db_zone = s_db[:CF_BARS + 2]

        # ── Pre-warp phase alignment ────────────────────────────────────────
        # Align the first downbeat of the slave to the master BEFORE bar-by-bar
        # stretching.  This prevents the warp from starting with an offset
        # that the global onset_micro_align can't fully correct because it's
        # a single compromise for all 16 bars.
        pre_bars = 2
        pre_len = int(pre_bars * bar_s(m_bpm) * sr)
        pre_mm = s_cf[:pre_len].mean(1) if len(s_cf) >= pre_len else s_cf.mean(1)
        pre_sm = m_cf[:pre_len].mean(1) if len(m_cf) >= pre_len else m_cf.mean(1)
        pre_shift = onset_micro_align(
            pre_mm, pre_sm, m_bpm, max_shift_sec=0.10, sr=sr
        )
        if abs(pre_shift) > 20:  # >~0.5ms — meaningful
            if int(pre_shift) > 0:
                s_cf = np.concatenate([s_cf[int(pre_shift):],
                                       np.zeros((int(pre_shift), 2), dtype="float32")])
            else:
                pad_n = -int(pre_shift)
                s_cf = np.concatenate([np.zeros((pad_n, 2), dtype="float32"),
                                       s_cf[:-pad_n]])
            # Recompute slave downbeats for the aligned segment
            s_db_aligned = s_db - int(pre_shift)
            s_db_aligned = s_db_aligned[s_db_aligned >= 0]
            s_db_zone = s_db_aligned[:CF_BARS + 2]
            print(f"    Pre-warp phase alignment: {pre_shift/sr*1000:.1f}ms")

        warped, consumed = warp_to_grid(s_cf, s_db_zone, m_db_zone, sr)
        if warped is not None:
            print(f"    Bar-by-bar warp: {min(n_m,len(m_db_zone))-1} bars | consumed {consumed/sr:.1f}s slave audio")
            s_zone = pt(warped, cf_len)
            # Save 17th bar for seamless blend→ramp transition
            warp_extra = warped[cf_len:] if len(warped) > cf_len else None
        else:
            use_barwarp = False
            warp_extra = None

    if not use_barwarp:
        # Fallback: single global stretch
        rate = m_bpm / s_bpm
        native_len = int(CF_BARS * bar_s(s_bpm) * sr) + sr * 2
        s_raw = pt(s_cf, native_len)
        if abs(rate - 1.0) > 0.002:
            print(f"    Fallback global stretch {s_bpm:.1f}->{m_bpm:.1f}  rate={rate:.4f}")
            s_zone = pyrb.time_stretch(s_raw.astype("float64"), sr, rate).astype("float32")
        else:
            print(f"    No stretch needed ({abs(rate - 1) * 100:.2f}%)")
            s_zone = s_raw
        s_zone = pt(s_zone, cf_len)
        consumed = int(CF_BARS * bar_s(s_bpm) * sr)
        warp_extra = None

    m_zone = pt(m_cf, cf_len)

    # 2. Residual micro-align (+/-50ms window, downbeat-weighted)
    mm = m_zone.mean(1)
    sm = s_zone.mean(1)
    shift = onset_micro_align(
        mm, sm, m_bpm, max_shift_sec=0.05,
        m_db_zone=m_db[:CF_BARS + 1] if n_m >= CF_BARS else None,
        s_db_zone=s_db[:CF_BARS + 1] if n_s >= CF_BARS else None,
        sr=sr
    )
    print(f"    Residual shift after warp: {shift/sr*1000:.1f}ms")
    if abs(shift) > 0:
        if int(shift) > 0:
            s_zone = np.concatenate([s_zone[int(shift):], np.zeros((int(shift), 2), dtype="float32")])
        else:
            pad_n = -int(shift)
            s_zone = np.concatenate([np.zeros((pad_n, 2), dtype="float32"), s_zone[:-pad_n]])

    # 2b. Per-bar re-alignment — split into 2-bar chunks, ALWAYS correct
    # Prevents cumulative onset drift over long crossfades.
    # Now starts from chunk 0 (was range(1,n_chunks)) — first 2 bars
    # also get corrected, preventing drift at the start of the transition.
    n_chunks = 8  # 8 chunks × 2 bars = 16 bars
    chunk_len = cf_len // n_chunks
    if chunk_len > sr * 1.5:
        total_correction_ms = 0.0
        for ci in range(0, n_chunks):
            cs = ci * chunk_len
            ce = min((ci + 1) * chunk_len, cf_len)
            if ce - cs < sr // 2:
                continue
            mm_chunk = m_zone[cs:ce].mean(1)
            sm_chunk = s_zone[cs:ce].mean(1)
            chunk_shift = onset_micro_align(
                mm_chunk, sm_chunk, m_bpm, max_shift_sec=0.03, sr=sr
            )
            if abs(chunk_shift) > 10:  # only apply if meaningful (>10 samples ≈ 0.2ms)
                s_chunk = s_zone[cs:ce].copy()
                if int(chunk_shift) > 0:
                    s_zone[cs:ce] = np.concatenate([
                        s_chunk[int(chunk_shift):],
                        np.zeros((int(chunk_shift), 2), dtype="float32")
                    ])
                else:
                    pad_n = -int(chunk_shift)
                    s_zone[cs:ce] = np.concatenate([
                        np.zeros((pad_n, 2), dtype="float32"),
                        s_chunk[:-pad_n]
                    ])
                total_correction_ms += abs(chunk_shift) / sr * 1000
        if total_correction_ms > 0.5:
            print(f"    Per-bar re-align: {total_correction_ms:.2f}ms total correction across {n_chunks} chunks")

    # 3. LR4 3-Band blend with bass polarity check
    if mode == 'hpss':
        print("    LR4 3-Band split & Bass Swap...", flush=True)
        m_low, m_mid, m_high = three_band_split(m_zone, 150.0, 3000.0, sr)
        s_low, s_mid, s_high = three_band_split(s_zone, 150.0, 3000.0, sr)

        # Bass polarity check — weighted consensus across 5 points
        bar_samples = int(bar_s(m_bpm) * sr)
        bws = int(0.10 * SR)  # analysis window (100ms)
        n_points = 5
        polarities = []
        for pi in range(n_points):
            pc = int(cf_len * (pi + 1) / (n_points + 1))
            aw2 = m_low[pc - bws:pc + bws].flatten()
            bl3 = s_low[pc - bws:pc + bws].flatten()
            if len(aw2) == len(bl3) and len(aw2) > 50:
                co = np.corrcoef(aw2, bl3)[0, 1]
                if not np.isnan(co):
                    polarities.append(co)
        if polarities:
            mean_corr = float(np.mean(polarities))
            print(f"    Bass polarity: mean_corr={mean_corr:.2f} ({n_points} pts)", end='')
            # Also check kick band (60-120Hz) separately — more critical for phase cancellation
            sos = signal.butter(4, [60, 120], btype='band', fs=sr, output='sos')
            m_kick = signal.sosfilt(sos, m_low.mean(1))
            s_kick = signal.sosfilt(sos, s_low.mean(1))
            kick_corr = np.corrcoef(m_kick, s_kick)[0, 1] if len(m_kick) > 100 else 0
            if not np.isnan(kick_corr):
                print(f"  kick_corr={kick_corr:.2f}", end='')
            # Invert if EITHER full-band or kick band shows significant negative correlation
            if mean_corr < -0.3 or kick_corr < -0.5:
                s_low = -s_low
                print(" → INVERTED")
            else:
                print(" → OK")
        else:
            print("    Bass polarity: skipped (insufficient data)")

        fo, fi = eq_pow(cf_len)
        blended_mid = m_mid * fo[:, None] + s_mid * fi[:, None]
        blended_high = m_high * fo[:, None] + s_high * fi[:, None]

        trans_width = int(1.5 * bar_samples)
        cf_center = cf_len // 2
        swap_start = max(0, cf_center - trans_width // 2)
        swap_end = min(cf_len, cf_center + trans_width // 2)
        actual_width = swap_end - swap_start

        sfo, sfi = eq_pow(actual_width)

        # ── Adaptive sub crossfade: low band transitions faster ────────────
        # Sub (20-150Hz) overlaps for fewer bars (5 vs 16), reducing
        # phase cancellation time by 3x.  Mid/high still use full CF_BARS.
        sub_bars = 5  # sub transitions in 5 bars (was 16)
        sub_len = int(sub_bars * bar_s(m_bpm) * sr)
        sub_len = min(sub_len, cf_len)

        blended_low = np.zeros_like(m_low)
        blended_low[:swap_start] = m_low[:swap_start]

        if sub_len < swap_end:
            # Fast crossfade for sub within transition zone
            sub_mask = (np.arange(cf_len) >= swap_start) & (np.arange(cf_len) < swap_start + sub_len)
            sub_end_idx = min(swap_start + sub_len, swap_end)
            sub_w = sub_end_idx - swap_start
            if sub_w > 64:
                sfo_sub, sfi_sub = eq_pow(sub_w)
                blended_low[swap_start:sub_end_idx] = (
                    m_low[swap_start:sub_end_idx] * sfo_sub[:, None] +
                    s_low[swap_start:sub_end_idx] * sfi_sub[:, None]
                )
            else:
                blended_low[swap_start:sub_end_idx] = (
                    m_low[swap_start:sub_end_idx] * sfo[:sub_w, None] +
                    s_low[swap_start:sub_end_idx] * sfi[:sub_w, None]
                )
            # Remaining zone: slave takes over fast
            blended_low[sub_end_idx:swap_end] = s_low[sub_end_idx:swap_end]
        else:
            blended_low[swap_start:swap_end] = (
                m_low[swap_start:swap_end] * sfo[:, None] +
                s_low[swap_start:swap_end] * sfi[:, None]
            )
        blended_low[swap_end:] = s_low[swap_end:]
        blended = blended_low + blended_mid + blended_high

        # Narrow RMS stabilizer with lookahead
        if stabilizer:
            blended = rms_stabilizer_lookahead(blended, cf_len)
    else:
        fo, fi = eq_pow(cf_len)
        blended = m_zone * fo[:, None] + s_zone * fi[:, None]

    # Tail fade (TAIL_FADE_BARS) — redundant with seamless blend→ramp, disabled by default
    tbs = int(TAIL_FADE_BARS * bar_s(m_bpm) * sr)
    if tbs > 0 and tbs < cf_len:
        tf = np.linspace(1.0, 0.0, tbs).astype("float32")
        blended[-tbs:] *= (fo[-tbs:] * tf + (1.0 - fo[-tbs:]))[:, None]

    pk = np.max(np.abs(blended))
    if pk > 0.99:
        blended *= 0.99 / pk

    return blended, shift, consumed, warp_extra


# ============================================================
# Main Mixing Pipeline
# ============================================================

def mix_tracks(tracks, wav_dir, ann_dir, output_mp3, bitrate="320k", sr=SR,
               style=None, author=None,
               use_quiet_exit=False, stabilizer=True):
    """
    Main entry point. Mix a list of tracks into a continuous DJ mix.

    Args:
        tracks: list of (name, wav_filename, annotation_filename) tuples
        wav_dir: directory containing WAV files
        ann_dir: directory containing madmom annotation .txt files
        output_mp3: output MP3 path
        bitrate: MP3 bitrate (default "320k")
        sr: sample rate (default 44100)
        style: genre/style name for metadata
        author: DJ/artist name for metadata
    """
    today = time.strftime("%Y-%m-%d")
    print(f"=== Smart Mixer: Bar-by-Bar Warp + LR4 + Narrow RMS + Seamless blend→ramp ===\n")
    if style:
        print(f"  Style: {style}  |  Date: {today}")
    if author:
        print(f"  Author: {author}")
    print()
    t_start = time.time()

    # Load + analyze tracks
    print("Loading and preparing tracks...")
    TD = []
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
        mono = audio.mean(1) if audio.ndim == 2 else audio
        key = detect_key(mono, sr)
        cam = camelot_code(key)
        print(f"    Key: {key:8s}  Camelot: {cam}  (in {time.time()-t_key:.1f}s)")

        secs = sections(audio, db, sr, name=name)
        act = [(s, e) for s, e, l in secs if l in ('ACTIVE', 'DROP')]
        if act:
            eb = max(0, act[0][0] - 2)
            xb = min(len(db) - 1, act[-1][1] + 2)
        else:
            eb, xb = 0, len(db) - 1

        s0 = int(db[eb])
        e0 = int(db[xb]) if xb < len(db) else len(audio)
        at = audio[s0:e0]
        dbt = db[eb:xb+1] - s0
        st = sections(at, dbt, sr)

        at = norm_lufs(at, TARGET_LUFS, sr)

        qe = quiet_exit(st)
        fa = first_active(st)
        dur = len(at) / sr
        print(f"    Trimmed: {int(dur // 60)}:{int(dur % 60):02d}  bars {eb}-{xb}")
        print(f"    quiet_exit={'bar' + str(qe) if qe is not None else 'none'}  first_active=bar{fa}")

        TD.append({
            'name': name, 'audio': at, 'db': dbt, 'bpm': bpm,
            'key': key, 'cam': cam,
            'secs': st, 'qe': qe, 'fa': fa
        })

    # Print Camelot overview
    print(f"\n  === Camelot Wheel Overview ===")
    for td in TD:
        print(f"    {td['name']:15s}  {td['bpm']:5.1f} BPM  {td['key']:8s}  {td['cam']}")
    for i in range(len(TD) - 1):
        kc = key_compat(TD[i]['key'], TD[i+1]['key'])
        label = "SAME" if kc == 1.0 else "ADJ" if kc >= 0.9 else "REL" if kc >= 0.8 else "POOR"
        print(f"    {TD[i]['cam']} → {TD[i+1]['cam']}: compat={kc:.1f}  [{label}]")

    # Build the continuous mix
    print(f"\n\nBuilding mix ({CF_BARS}-bar crossfades)...\n")
    parts = []
    stamps = []
    mix_pos = 0
    cur = TD[0]
    cur_off = 0

    for i in range(1, len(TD)):
        nxt = TD[i]
        mb, sb = cur['bpm'], nxt['bpm']
        diff = abs(sb - mb) / mb

        print(f"  {cur['name']} ({mb:.1f}) -> {nxt['name']} ({sb:.1f})  diff={diff * 100:.1f}%")

        if diff > BPM_DIFF_LIMIT:
            print(f"    BPM difference too high (>{BPM_DIFF_LIMIT*100:.0f}%). Hard cut.")
            body = cur['audio'][cur_off:]
            parts.append(body)
            mix_pos += len(body)
            cur = nxt
            cur_off = 0
            continue

        cf_len = int(CF_BARS * bar_s(mb) * sr)

        # Determine exit point — align to bar grid
        if use_quiet_exit and cur['qe'] is not None:
            exit_bar = cur['qe']
            print(f"    Quiet exit at bar {exit_bar}")
        else:
            total = len(cur['db']) - 1
            exit_bar = max(0, total - CF_BARS - 4)
            exit_bar = (exit_bar // 16) * 16
        mode = 'hpss'

        exit_samp = int(cur['db'][min(exit_bar, len(cur['db']) - 1)])
        body = cur['audio'][cur_off:exit_samp]
        print(f"    Master exit bar {exit_bar} ({exit_samp / sr:.1f}s)  mode={mode}")

        m_cf = cur['audio'][exit_samp:exit_samp + cf_len + sr * 3]
        m_cf_db = cur['db'][cur['db'] >= exit_samp] - exit_samp

        s_entry = nxt['fa']
        s_samp = int(nxt['db'][min(s_entry, len(nxt['db']) - 1)])
        s_cf = nxt['audio'][s_samp:]
        s_cf_db = nxt['db'][nxt['db'] >= s_samp] - s_samp
        print(f"    Slave entry bar {s_entry} ({s_samp / sr:.1f}s)")

        # Calculate entry RMS for ramp decision
        ec = int(2 * bar_s(sb) * sr)
        entry_segment = nxt['audio'][s_samp:s_samp + ec] if ec < len(nxt['audio'][s_samp:]) else nxt['audio'][s_samp:]
        entry_rms = float(np.sqrt(np.mean(entry_segment**2)))

        # ── Entry LUFS normalization ──────────────────────────────────────────
        # Compare last 4 bars of master exit with first 4 bars of slave entry.
        # Apply gain to slave if RMS differs by >2x, reducing LUFS jumps.
        lufs_bars = 4
        lufs_len = int(lufs_bars * bar_s(mb) * sr)
        master_tail_rms = np.sqrt(np.mean(m_cf[max(0, lufs_len - int(sr*0.5)):lufs_len]**2)) + 1e-12
        slave_head = nxt['audio'][s_samp:s_samp + int(lufs_bars * bar_s(sb) * sr)]
        slave_head_rms = np.sqrt(np.mean(slave_head**2)) + 1e-12
        rms_ratio = master_tail_rms / slave_head_rms
        if rms_ratio > 1.5 or rms_ratio < 0.6:
            lufs_gain = min(2.0, max(0.5, rms_ratio))
            print(f"    Entry LUFS match: master_tail_rms={master_tail_rms:.4f} "
                  f"slave_head_rms={slave_head_rms:.4f}  gain={lufs_gain:.2f}")
            s_cf = s_cf * lufs_gain

        blended, shift, consumed, warp_extra = build_cf_lr4(
            m_cf, s_cf, mb, sb, m_cf_db, s_cf_db, mode, sr,
            stabilizer=stabilizer
        )

        ts = (mix_pos + len(body)) / sr
        stamps.append({
            'from': cur['name'], 'to': nxt['name'],
            'from_key': cur.get('cam', '?'), 'to_key': nxt.get('cam', '?'),
            'key_compat': key_compat(cur.get('key', '?'), nxt.get('key', '?')),
            't': ts, 'dur': CF_BARS * bar_s(mb), 'mode': mode,
            'shift': shift / sr, 'entry_rms': entry_rms
        })

        parts.append(body)
        mix_pos += len(body)

        cur = nxt
        ramp_off = s_samp + consumed

        ramp_audio = nxt['audio'][ramp_off:]
        ramp_db = nxt['db'][nxt['db'] >= ramp_off] - ramp_off
        ramp_result, ramp_consumed = ramp_to_native(
            ramp_audio, ramp_db, mb, sb, sr, ser=entry_rms
        )

        if ramp_result is not None:
            # ── Seamless blend→ramp boundary ─────────────────────────────────
            # blended (LR4-processed crossfade) is followed by ramp_result
            # (raw pyrubberband bars at master BPM → ramped to native BPM).
            # The LR4 processing + RMS stabilizer phase-shifts the audio,
            # creating a hard boundary.  Crossfade last/first 20ms to fix it.
            if warp_extra is not None:
                ramp_result = np.concatenate([warp_extra, ramp_result])
            # Crossfade between blended tail and ramp_result head
            bf_ms = int(0.020 * sr)  # 20ms crossfade
            if len(blended) >= bf_ms and len(ramp_result) >= bf_ms:
                fade_out = np.linspace(1.0, 0.0, bf_ms).astype("float32")[:, None]
                fade_in = np.linspace(0.0, 1.0, bf_ms).astype("float32")[:, None]
                blended_tail = blended[-bf_ms:] * fade_out
                ramp_head = ramp_result[:bf_ms] * fade_in
                smooth_boundary = blended_tail + ramp_head
                blended = np.concatenate([blended[:-bf_ms], smooth_boundary])
                ramp_result = ramp_result[bf_ms:]
            print(f"    blend->ramp: seamless {warp_extra is not None}")
            parts.append(blended)
            mix_pos += len(blended)
            parts.append(ramp_result)
            mix_pos += len(ramp_result)
            cur_off = ramp_off + ramp_consumed
        else:
            parts.append(blended)
            mix_pos += len(blended)
            cur_off = ramp_off

        if cur_off >= len(cur['audio']):
            cur_off = s_samp + int(CF_BARS * bar_s(sb) * sr) // 2
        print(f"    Slave continues at {cur_off / sr:.1f}s\n")

    parts.append(cur['audio'][cur_off:])

    print("Concatenating...")
    mix = np.concatenate([p for p in parts if len(p) > 0])
    pk = np.max(np.abs(mix))
    if pk > 0:
        mix = mix * (10**(-1/20) / pk)
    mix = np.clip(mix, -1.0, 1.0)

    dur = len(mix) / sr
    print(f"Total mix duration: {int(dur // 60)}:{int(dur % 60):02d}")

    wav_out = output_mp3.replace('.mp3', '.wav')
    print("Exporting WAV...")
    sf.write(wav_out, mix, sr, subtype="PCM_24")

    # Build title + metadata
    today = time.strftime("%Y-%m-%d")
    mp3_title = f"AutoDJ Mix"
    mp3_artist = "AutoDJ Mixer"
    if style:
        mp3_title = f"{style} Mix"
    if author:
        mp3_artist = author
    print(f"Encoding MP3 ({bitrate})...")
    r = subprocess.run([
        "ffmpeg", "-y", "-i", wav_out, "-b:a", bitrate,
        "-id3v2_version", "3",
        "-metadata", f"title={mp3_title}",
        "-metadata", f"artist={mp3_artist}",
        output_mp3
    ], capture_output=True, text=True)

    if r.returncode:
        print(f"  FFmpeg error: {r.stderr[-300:]}")
    else:
        sz = os.path.getsize(output_mp3) / 1e6
        print(f"  MP3: {output_mp3} ({sz:.1f} MB)")
        sz_wav = os.path.getsize(wav_out) / 1e6
        print(f"  WAV (24-bit master): {wav_out} ({sz_wav:.1f} MB)")

    print("\n=== TRANSITIONS ===")
    for st in stamps:
        m = int(st['t'] // 60)
        s = int(st['t'] % 60)
        m2 = int((st['t'] + st['dur']) // 60)
        s2 = int((st['t'] + st['dur']) % 60)
        kc = st.get('key_compat', 0)
        kc_label = "SAME" if kc >= 1.0 else "ADJ" if kc >= 0.9 else "REL" if kc >= 0.8 else "POOR"
        print(
            f"  {m:02d}:{s:02d}-{m2:02d}:{s2:02d}  "
            f"{st['from']} -> {st['to']}  "
            f"[{'BASS SWAP' if st['mode'] == 'hpss' else 'QUIET CROSS'}]  "
            f"{st.get('from_key','?')}→{st.get('to_key','?')} [{kc_label}]  "
            f"micro_shift={st['shift'] * 1000:.1f}ms  "
            f"entry_rms={st.get('entry_rms', 0):.4f}"
        )

    total_t = time.time() - t_start
    print(f"\nCompleted in {total_t:.1f}s")

    # Save stamps alongside output for analyzer
    if output_mp3:
        stamps_path = output_mp3.replace('.mp3', '_stamps.npy')
        np.save(stamps_path, np.array(stamps, dtype=object), allow_pickle=True)
        print(f"  Stamps saved → {stamps_path}")

    return stamps


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoDJ Smart Mixer (v7+v13)")
    parser.add_argument("--wav-dir", required=True, help="Directory with WAV files")
    parser.add_argument("--ann-dir", required=True, help="Directory with madmom annotation files")
    parser.add_argument("--output", default=None, help="Output MP3 path (default: auto-generated from style+date)")
    parser.add_argument("--style", default=None, help="Genre/style name (e.g. 'Melodic House', 'Techno')")
    parser.add_argument("--author", default=None, help="DJ/artist name for metadata")
    parser.add_argument("--bitrate", default="320k", help="MP3 bitrate (default: 320k)")
    parser.add_argument("--config", help="Python config file with TRACKS list")
    parser.add_argument("--use-quiet-exit", action="store_true", help="Exit on QUIET/BUILD section (shorter mix)")
    parser.add_argument("--no-stabilizer", action="store_true", help="Disable RMS stabilizer (may increase dips, less pumping)")
    args = parser.parse_args()

    # Auto-generate output filename if not provided
    if args.output is None:
        today = datetime.now().strftime("%Y-%m-%d")
        base = today
        if args.style:
            base = f"{args.style} Mix {today}"
        args.output = base.replace(" ", "_") + ".mp3"

    if args.config:
        import importlib.util
        spec = importlib.util.spec_from_file_location("config", args.config)
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        tracks = cfg.TRACKS
    else:
        # Auto-discover: pair .wav with .txt files by matching base names
        wav_files = sorted(f for f in os.listdir(args.wav_dir) if f.endswith('.wav'))
        tracks = []
        for wf in wav_files:
            base = os.path.splitext(wf)[0]
            ann = base + '.txt'
            if os.path.exists(os.path.join(args.ann_dir, ann)):
                name = base.split(' - ')[0] if ' - ' in base else base[:20]
                tracks.append((name, wf, ann))
            else:
                print(f"  Warning: no annotation for {wf}, skipping")

        if not tracks:
            print("No tracks found. Provide WAV files in --wav-dir with matching .txt annotations in --ann-dir")
            sys.exit(1)

    mix_tracks(tracks, args.wav_dir, args.ann_dir, args.output, args.bitrate,
               style=args.style, author=args.author,
               use_quiet_exit=args.use_quiet_exit, stabilizer=not args.no_stabilizer)