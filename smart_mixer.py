#!/usr/bin/env python3
"""
Smart Mixer v7 (Bar-by-Bar Warp + LR4 Crossover)
Developed by Hermes & Stas. Beat alignment fix by ClaudeClaw.

Bar-by-bar warping: each bar of slave is individually stretched to match
the corresponding master bar length. Eliminates phase drift over 16-bar crossfades.

Usage:
  python3 smart_mixer.py --wav-dir ./wav --ann-dir ./annotations --output mix.mp3

Or configure via a Python config file:
  python3 smart_mixer.py --config mix_config.py
"""
import sys, os, time, subprocess, argparse

import numpy as np
import soundfile as sf
import scipy.signal as signal
import pyrubberband as pyrb
import librosa
import pyloudnorm as pyln

SR = 44100
CF_BARS = 16                # Crossfade duration in bars
RAMP_SEC = 15               # Post-crossfade BPM ramp-back duration (seconds)
RAMP_MIN_RMS = 0.08         # Min slave entry RMS for BPM ramp; below this => volume fade only
TAIL_FADE_BARS = 2          # Extra fade-out bars at end of crossfade (smoother endpoint)
TARGET_LUFS = -14.0         # Loudness normalization target
BPM_DIFF_LIMIT = 0.08      # Max BPM difference ratio for crossfade (8%)

# ---- 3-Band Linkwitz-Riley Filter ----------------------------------------

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

# ---- Audio Helpers --------------------------------------------------------

def load_stereo(path, sr=SR):
    data, file_sr = sf.read(path, always_2d=True)
    if data.shape[1] == 1:
        data = np.hstack([data, data])
    if file_sr != sr:
        tmp = f"/tmp/_rs_{os.path.basename(path)}.wav"
        subprocess.run(["ffmpeg", "-y", "-i", path, "-ar", str(sr), "-ac", "2", tmp],
                       capture_output=True)
        data, _ = sf.read(tmp, always_2d=True)
        os.unlink(tmp)
    return data.astype("float32")

def norm_lufs(audio, target=TARGET_LUFS, sr=SR):
    meter = pyln.Meter(sr)
    # Fast: analyze only first 30s (representative of track energy)
    sample = audio[:int(min(30 * sr, len(audio)))]
    loud = meter.integrated_loudness(sample.astype("float64"))
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
    sh = list(a.shape); sh[0] = n - len(a)
    return np.concatenate([a, np.zeros(sh, dtype=a.dtype)])

def bar_s(bpm):
    """Duration of one bar (4 beats) in seconds."""
    return 240.0 / bpm

def load_dbeats(ann_path, sr=SR):
    """Load downbeat positions from madmom annotation file."""
    beats = np.loadtxt(ann_path)
    return np.array([int(r[0] * sr) for r in beats if round(r[1]) == 1], dtype=int)

def calc_bpm(db, sr=SR):
    """Calculate BPM from downbeat array."""
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
    return 4 * 60.0 / np.mean(r)

def fix_ht(db, bpm):
    """Fix half-time BPM detection by doubling downbeat density."""
    if bpm >= 90:
        return db, bpm
    new = []
    for i in range(len(db) - 1):
        new.append(db[i])
        new.append((db[i] + db[i+1]) // 2)
    new.append(db[-1])
    return np.array(new, dtype=int), bpm * 2

# ---- Structural Analysis -------------------------------------------------

def sections(audio, db, sr=SR, name=""):
    """Classify bars as QUIET/BUILD/ACTIVE/DROP based on RMS energy + bass ratio."""
    mono = audio.mean(1) if audio.ndim == 2 else audio
    n = len(db) - 1
    if n < 4:
        return [(0, n, "ACTIVE")]

    br = np.array([np.sqrt(np.mean(mono[db[i]:db[i+1]]**2))
                    if db[i+1] > db[i] else 0.0 for i in range(n)])

    b_low, a_low = signal.butter(2, 200.0 / (0.5 * sr), btype='low')
    mono_low = signal.filtfilt(b_low, a_low, mono)

    bl = np.array([np.sqrt(np.mean(mono_low[db[i]:db[i+1]]**2))
                    if db[i+1] > db[i] else 0.0 for i in range(n)])
    bl = bl / (br + 1e-12)

    k = np.ones(4) / 4
    de = np.convolve(br, k, 'same') * np.convolve(bl, k, 'same')
    med = np.median(de[de > 0]) if np.any(de > 0) else 1e-12

    lb = ['DROP' if e > med * 1.2 else 'ACTIVE' if e > med * 0.5
          else 'BUILD' if e > med * 0.2 else 'QUIET' for e in de]

    sc = []; cur = lb[0]; s = 0
    for i in range(1, n):
        if lb[i] != cur:
            sc.append((s, i, cur))
            cur = lb[i]; s = i
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
            t1 = db[s] / sr; t2 = db[min(e, len(db) - 1)] / sr
            print(f"    {int(t1 // 60)}:{int(t1 % 60):02d}-{int(t2 // 60)}:{int(t2 % 60):02d}  "
                  f"bars {s:3d}-{e:3d} ({e-s:2d})  {l}")
    return mg

def quiet_exit(secs):
    """Find a quiet/build section in the second half suitable for exit."""
    total = secs[-1][1]
    for s, e, l in secs:
        if s >= total * 0.55 and l in ('QUIET', 'BUILD') and e - s >= 8:
            return s
    return None

def first_active(secs, mn=8):
    """Find first active/drop section with at least mn bars."""
    for s, e, l in secs:
        if l in ('DROP', 'ACTIVE') and e - s >= mn:
            return s
    return 0

# ---- Onset & Phase Micro-alignment ---------------------------------------

def onset_micro_align(m_mono, s_mono, bpm, sr=SR, max_shift_sec=0.2):
    """
    Sub-bar transient alignment using onset strength cross-correlation.
    Uses scipy.signal.fftconvolve for O(N log N) speed.
    """
    hop = 128
    mo = librosa.onset.onset_strength(y=m_mono.astype(np.float32), sr=sr, hop_length=hop)
    so = librosa.onset.onset_strength(y=s_mono.astype(np.float32), sr=sr, hop_length=hop)
    mo /= (mo.max() + 1e-8)
    so /= (so.max() + 1e-8)

    max_hop_shift = int(max_shift_sec * sr / hop)
    corr = signal.fftconvolve(mo, so[::-1], mode='full')
    center = len(corr) // 2

    lo = max(0, center - max_hop_shift)
    hi = min(len(corr), center + max_hop_shift + 1)

    best = np.argmax(corr[lo:hi]) + lo - center
    return best * hop

# ---- Bar-by-Bar Warp -----------------------------------------------------

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

    bars = []
    consumed = 0
    for i in range(n_bars):
        m_bar_len = int(m_db[i + 1]) - int(m_db[i])
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

# ---- BPM Ramp-back -------------------------------------------------------

def ramp_to_native(slave_audio, s_db, m_bpm, s_bpm, sr, ramp_sec=RAMP_SEC, slave_entry_rms=1.0):
    """
    After crossfade, the slave was warped to master BPM.
    Smoothly ramp it back to native BPM over ramp_sec seconds.
    Linear interpolation: bar length goes from master-bar to native-bar.

    If slave_entry_rms < RAMP_MIN_RMS: BPM stretch on silence creates audible
    artefacts (rubberband distortion, tape-chew effect). Instead apply a
    volume fade-in over the same duration — no stretch, just gain ramp.
    """
    bpm_diff = abs(m_bpm - s_bpm)
    if bpm_diff < 0.5:
        return None, 0

    # ── Quiet entry guard: volume fade instead of BPM stretch ──────────
    if slave_entry_rms < RAMP_MIN_RMS:
        print(f"    Slave entry RMS={slave_entry_rms:.3f} < {RAMP_MIN_RMS}: volume fade instead of BPM ramp")
        fade_samples = int(ramp_sec * sr)
        fade = np.linspace(0.0, 1.0, fade_samples).astype(np.float32)
        n_bars = min(int(ramp_sec / bar_s(s_bpm)) + 1, len(s_db) - 1)
        consumed = int(s_db[min(n_bars, len(s_db)-1)]) if len(s_db) > 1 else 0
        fade_out = pt(slave_audio[:fade_samples], fade_samples)
        result = (fade_out * fade[:, None]).astype(np.float32)
        print(f"    Volume fade: {len(result)/sr:.1f}s")
        return result, consumed

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
            pad = np.zeros((target_len - len(warped), slave_audio.shape[1]), dtype="float32")
            bars.append(np.concatenate([warped, pad]))
        consumed = s_end

    if not bars:
        return None, 0
    result = np.concatenate(bars)
    print(f"    BPM ramp: {m_bpm:.1f}->{s_bpm:.1f} over {len(result)/sr:.1f}s ({n_bars} bars)")
    return result, consumed

# ---- Transitions ----------------------------------------------------------

def eq_power_fades(n):
    """Equal-power fade shapes (fo^2 + fi^2 = 1 at all points)."""
    t = np.linspace(0, np.pi/2, n).astype("float32")
    return np.cos(t), np.sin(t)

def build_cf_lr4(m_cf, s_cf, m_bpm, s_bpm, m_db, s_db, mode, sr=SR):
    """
    Build crossfade with LR4 3-band bass swap.

    mode='hpss': LR4 bass swap (bass switches instantly, mids/highs crossfade)
    mode='quiet': simple equal-power crossfade
    """
    cf_len = int(CF_BARS * bar_s(m_bpm) * sr)

    # 1. Bar-by-bar warp (primary method)
    n_m = min(CF_BARS + 1, len(m_db))
    n_s = min(CF_BARS + 1, len(s_db))
    use_barwarp = (n_m >= CF_BARS and n_s >= CF_BARS)

    if use_barwarp:
        m_db_zone = m_db[:CF_BARS + 1]
        s_db_zone = s_db[:CF_BARS + 1]
        warped, consumed = warp_to_grid(s_cf, s_db_zone, m_db_zone, sr)
        if warped is not None:
            print(f"    Bar-by-bar warp: {n_m-1} bars | consumed {consumed/sr:.1f}s slave audio")
            s_zone = pt(warped, cf_len)
        else:
            use_barwarp = False

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

    m_zone = pt(m_cf, cf_len)

    # 2. Residual micro-align (+/-50ms window)
    mm = m_zone.mean(1)
    sm = s_zone.mean(1)
    shift = onset_micro_align(mm, sm, m_bpm, sr=sr, max_shift_sec=0.05)
    print(f"    Residual shift after warp: {shift/sr*1000:.1f}ms")
    if abs(shift) > 0:
        if int(shift) > 0:
            s_zone = np.concatenate([s_zone[int(shift):], np.zeros((int(shift), 2), dtype="float32")])
        else:
            pad_n = -int(shift)
            s_zone = np.concatenate([np.zeros((pad_n, 2), dtype="float32"), s_zone[:-pad_n]])

    # 3. LR4 3-Band blend
    if mode == 'hpss':
        print(f"    LR4 3-Band split & Bass Swap...", flush=True)
        m_low, m_mid, m_high = three_band_split(m_zone, 150.0, 3000.0, sr)
        s_low, s_mid, s_high = three_band_split(s_zone, 150.0, 3000.0, sr)

        fo, fi = eq_power_fades(cf_len)
        blended_mid = m_mid * fo[:, None] + s_mid * fi[:, None]
        blended_high = m_high * fo[:, None] + s_high * fi[:, None]

        bar_samples = int(bar_s(m_bpm) * sr)
        swap_center = cf_len // 2
        trans_width = int(1.5 * bar_samples)
        swap_start = max(0, swap_center - trans_width // 2)
        swap_end = min(cf_len, swap_center + trans_width // 2)
        actual_width = swap_end - swap_start

        sfo, sfi = eq_power_fades(actual_width)
        blended_low = np.zeros_like(m_low)
        blended_low[:swap_start] = m_low[:swap_start]
        blended_low[swap_start:swap_end] = (m_low[swap_start:swap_end] * sfo[:, None] +
                                             s_low[swap_start:swap_end] * sfi[:, None])
        blended_low[swap_end:] = s_low[swap_end:]
        blended = blended_low + blended_mid + blended_high
    else:
        fo, fi = eq_power_fades(cf_len)
        blended = m_zone * fo[:, None] + s_zone * fi[:, None]

    pk = np.max(np.abs(blended))
    if pk > 0.99:
        blended *= 0.99 / pk

    # ── Tail fade: smooth master exit at crossfade endpoint ────────────
    # Last TAIL_FADE_BARS of master get a gentle fade-out so the transition
    # doesn't end with a hard amplitude cut.  Only applies to the master
    # side — the slave is already fully faded in at this point.
    tail_bars_samp = int(TAIL_FADE_BARS * bar_s(m_bpm) * sr)
    if tail_bars_samp < cf_len:
        tail_fade = np.linspace(1.0, 0.0, tail_bars_samp).astype(np.float32)
        # Compute master-only contribution at the tail: blended = master * fo + slave
        # We need to apply the fade on top of whatever master component remains.
        # Safest: apply fade on the entire blended signal's last tail, but only
        # on a small enough window that slave is dominant.
        fo, fi = eq_power_fades(cf_len)
        master_frac = fo[-tail_bars_samp:]  # master fade curve at tail
        fade_amount = master_frac * tail_fade + (1.0 - master_frac)
        blended[-tail_bars_samp:] *= fade_amount[:, None]
        print(f"    Tail fade: {TAIL_FADE_BARS} bars ({tail_bars_samp/SR:.1f}s)")

    return blended, shift, consumed

# ---- Main Mixing Pipeline ------------------------------------------------

def mix_tracks(tracks, wav_dir, ann_dir, output_mp3, bitrate="320k", sr=SR):
    """
    Main entry point. Mix a list of tracks into a continuous DJ mix.

    Args:
        tracks: list of (name, wav_filename, annotation_filename) tuples
        wav_dir: directory containing WAV files
        ann_dir: directory containing madmom annotation .txt files
        output_mp3: output MP3 path
        bitrate: MP3 bitrate (default "320k")
        sr: sample rate (default 44100)
    """
    print(f"=== Smart Mixer v7: Bar-by-Bar Warp + LR4 Crossover ===\n")
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
            'secs': st, 'qe': qe, 'fa': fa
        })

    # Build the continuous mix
    print(f"\n\nBuilding mix ({CF_BARS}-bar crossfades)...\n")
    parts = []; stamps = []; mix_pos = 0
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
            cur = nxt; cur_off = 0
            continue

        cf_len = int(CF_BARS * bar_s(mb) * sr)

        if cur['qe'] is not None:
            exit_bar = cur['qe']; mode = 'quiet'
        else:
            total = len(cur['db']) - 1
            exit_bar = max(0, total - CF_BARS - 4); mode = 'hpss'

        exit_samp = int(cur['db'][min(exit_bar, len(cur['db']) - 1)])
        body = cur['audio'][cur_off:exit_samp]
        print(f"    Master exit bar {exit_bar} ({exit_samp / sr:.1f}s)  mode={mode}")

        m_cf = cur['audio'][exit_samp:exit_samp + cf_len + sr * 3]
        m_cf_db = cur['db'][cur['db'] >= exit_samp] - exit_samp

        s_entry = nxt['fa']
        s_samp = int(nxt['db'][min(s_entry, len(nxt['db']) - 1)])
        s_cf = nxt['audio'][s_samp:]
        s_cf_db = nxt['db'][nxt['db'] >= s_samp] - s_samp
        # Measure slave entry RMS for smart ramp decision
        entry_rms = float(np.sqrt(np.mean(s_cf[:min(int(sr), len(s_cf))]**2)))
        print(f"    Slave entry bar {s_entry} ({s_samp / sr:.1f}s)  entry_rms={entry_rms:.3f}")

        blended, shift, consumed = build_cf_lr4(m_cf, s_cf, mb, sb, m_cf_db, s_cf_db, mode, sr)

        ts = (mix_pos + len(body)) / sr
        stamps.append({
            'from': cur['name'], 'to': nxt['name'],
            't': ts, 'dur': CF_BARS * bar_s(mb), 'mode': mode,
            'shift': shift / sr, 'entry_rms': entry_rms
        })

        parts.append(body)
        parts.append(blended)
        mix_pos += len(body) + len(blended)

        cur = nxt
        ramp_off = s_samp + consumed

        ramp_audio = nxt['audio'][ramp_off:]
        ramp_db = nxt['db'][nxt['db'] >= ramp_off] - ramp_off
        ramp_result, ramp_consumed = ramp_to_native(ramp_audio, ramp_db, mb, sb, sr, ramp_sec=RAMP_SEC, slave_entry_rms=entry_rms)
        if ramp_result is not None:
            parts.append(ramp_result)
            mix_pos += len(ramp_result)
            cur_off = ramp_off + ramp_consumed
        else:
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
    sf.write(wav_out, mix, sr, subtype="PCM_16")

    print(f"Encoding MP3 ({bitrate})...")
    r = subprocess.run([
        "ffmpeg", "-y", "-i", wav_out, "-b:a", bitrate,
        "-id3v2_version", "3",
        "-metadata", "title=AutoDJ Mix",
        "-metadata", "artist=AutoDJ Mixer",
        output_mp3
    ], capture_output=True, text=True)

    if r.returncode:
        print(f"  FFmpeg error: {r.stderr[-300:]}")
    else:
        os.unlink(wav_out)
        sz = os.path.getsize(output_mp3) / 1e6
        print(f"  Output: {output_mp3} ({sz:.1f} MB)")

    print("\n=== TRANSITIONS ===")
    for st in stamps:
        m = int(st['t'] // 60); s = int(st['t'] % 60)
        m2 = int((st['t'] + st['dur']) // 60); s2 = int((st['t'] + st['dur']) % 60)
        print(f"  {m:02d}:{s:02d}-{m2:02d}:{s2:02d}  "
              f"{st['from']} -> {st['to']}  "
              f"[{'BASS SWAP' if st['mode'] == 'hpss' else 'QUIET CROSS'}]  "
              f"micro_shift={st['shift'] * 1000:.1f}ms")

    total_t = time.time() - t_start
    print(f"\nCompleted in {total_t:.1f}s")
    # Save stamps for mix_analyzer
    stamps_path = output_mp3.replace('.mp3', '_stamps.npy').replace('.wav', '_stamps.npy')
    np.save(stamps_path, np.array(stamps, dtype=object))
    return stamps

# ---- CLI ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoDJ Smart Mixer v7")
    parser.add_argument("--wav-dir", required=True, help="Directory with WAV files")
    parser.add_argument("--ann-dir", required=True, help="Directory with madmom annotation files")
    parser.add_argument("--output", default="mix.mp3", help="Output MP3 path")
    parser.add_argument("--bitrate", default="320k", help="MP3 bitrate (default: 320k)")
    parser.add_argument("--config", help="Python config file with TRACKS list")
    args = parser.parse_args()

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

    mix_tracks(tracks, args.wav_dir, args.ann_dir, args.output, args.bitrate)
