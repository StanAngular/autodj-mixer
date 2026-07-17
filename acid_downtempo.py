#!/usr/bin/env python3
"""
acid_downtempo.py — Post-process studio synth minus into acid downtempo style.

What it does:
  1. Takes existing studio_soft.mp3 (supersaw + FM bass + 808 drums)
  2. Extracts original bass stem, re-synthesizes as TB-303 acid bass
     (sawtooth + resonant LP filter sweep per note, Q=10, cutoff sweep on onsets)
  3. Replaces the bass in the mix with acid bass (HP filter removes old bass)
  4. Low-pass shelf cut on low-mids/sub for cleaner downtempo feel
  5. Half volume (-6dB) for background/reference use
  6. No reverb, no extra compression artifacts

Usage:
  python3 acid_downtempo.py \
    --input shared/rework/mozgoviy_studio_soft.mp3 \
    --bass-stem shared/rework/demix_hq/htdemucs/mozgoviy_original/bass.wav \
    --out shared/rework/mozgoviy_acid_downtempo.mp3
"""

import argparse, os, sys, tempfile, subprocess
import numpy as np
import scipy.signal
import librosa
import soundfile as sf

try:
    from pedalboard import Pedalboard, Compressor, Gain, HighpassFilter, LowpassFilter
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

SR = 44100
HOP = 512


# ─────────────────────────────────────────
# TB-303 resonant filter (biquad)
# ─────────────────────────────────────────

def resonant_lp_coeffs(cutoff_hz, Q=8.0):
    """
    2nd order resonant low-pass biquad coefficients.
    Q > 1 → resonance peak at cutoff (acid character).
    """
    cutoff_hz = np.clip(cutoff_hz, 20.0, SR / 2 - 100)
    w0 = 2 * np.pi * cutoff_hz / SR
    alpha = np.sin(w0) / (2 * Q)
    cos_w0 = np.cos(w0)

    b0 = (1 - cos_w0) / 2
    b1 =  1 - cos_w0
    b2 = (1 - cos_w0) / 2
    a0 =  1 + alpha
    a1 = -2 * cos_w0
    a2 =  1 - alpha

    b = np.array([b0 / a0, b1 / a0, b2 / a0])
    a = np.array([1.0, a1 / a0, a2 / a0])
    return b, a


def apply_resonant_lp(y, cutoff_hz, Q=8.0):
    b, a = resonant_lp_coeffs(cutoff_hz, Q)
    return scipy.signal.lfilter(b, a, y).astype(np.float32)


# ─────────────────────────────────────────
# Acid bass synthesis
# ─────────────────────────────────────────

def synth_acid_bass(bass_stem_path, Q=10.0, cutoff_max=2200.0, cutoff_min=100.0,
                    sweep_ms=380.0):
    """
    Generate TB-303 acid bass from original bass stem.

    Pipeline:
    1. pyin pitch detection on bass stem
    2. Sawtooth oscillator with portamento
    3. Note onset detection (each onset = new filter sweep trigger)
    4. Per-onset cutoff envelope: cutoff_max → cutoff_min over sweep_ms
       with high Q resonance → characteristic "wob/squelch" acid sound
    5. Follow original dynamics envelope
    """
    print("  Loading bass stem...")
    y_bass, _ = librosa.load(bass_stem_path, sr=SR, mono=True)

    print("  Pitch detection (pyin 40-400Hz)...")
    f0, voiced, _ = librosa.pyin(
        y_bass, fmin=40, fmax=400, sr=SR,
        hop_length=HOP, fill_na=0.0
    )

    # Detect note onsets for envelope triggers
    onset_frames = librosa.onset.onset_detect(
        y=y_bass, sr=SR, hop_length=HOP, backtrack=True, units='frames'
    )
    onset_samples = librosa.frames_to_samples(onset_frames, hop_length=HOP)
    print(f"  Onsets: {len(onset_samples)} (filter envelope triggers)")

    n_total = len(f0) * HOP

    # ── Sawtooth synthesis with portamento ──
    print("  Synthesizing acid sawtooth...")
    y_saw = np.zeros(n_total, dtype=np.float32)
    phase = 0.0
    prev_f = 0.0
    glide_frames = 6  # ~70ms at 105 BPM glide

    for i in range(len(f0)):
        start = i * HOP
        end = min(start + HOP, n_total)
        n = end - start
        f = f0[i]

        if f <= 0 or np.isnan(f):
            prev_f = 0.0
            continue

        # Portamento: glide from previous pitch
        if prev_f > 0 and abs(f - prev_f) > 1.0:
            glide_active = True
            glide_f = prev_f + (f - prev_f) * min(1.0, (i % glide_frames) / glide_frames)
        else:
            glide_f = f

        t_local = np.arange(n) / SR
        n_harm = min(int(SR / 2 / max(glide_f, 1)), 20)
        saw = np.zeros(n)
        for h in range(1, n_harm + 1):
            saw += ((-1) ** h) * np.sin(phase * h + 2 * np.pi * glide_f * h * t_local) / h
        saw *= 2 / np.pi
        y_saw[start:end] = saw
        phase += 2 * np.pi * glide_f * n / SR
        prev_f = f

    # ── Per-onset filter sweep ──
    print(f"  Applying acid filter (Q={Q}, sweep {cutoff_max:.0f}→{cutoff_min:.0f}Hz)...")
    y_acid = np.zeros(n_total, dtype=np.float32)
    sweep_len = int(sweep_ms * SR / 1000)

    # Build cutoff envelope per sample
    cutoff_env = np.full(n_total, cutoff_min, dtype=np.float64)
    for pos in onset_samples:
        if pos >= n_total:
            break
        end = min(pos + sweep_len, n_total)
        seg = end - pos
        # Exponential sweep: sounds more natural than linear
        cutoff_env[pos:end] = np.exp(
            np.linspace(np.log(cutoff_max), np.log(cutoff_min), seg)
        )

    # Apply filter in 256-sample chunks (per-chunk coefficient update)
    chunk = 256
    zi = scipy.signal.lfilter_zi(*resonant_lp_coeffs(cutoff_min, Q))
    zi = zi * y_saw[0] if len(y_saw) > 0 else zi

    for c in range(0, n_total, chunk):
        c_end = min(c + chunk, n_total)
        avg_cut = float(np.mean(cutoff_env[c:c_end]))
        b, a = resonant_lp_coeffs(avg_cut, Q)
        zi_in = zi if c == 0 else zi
        filtered, zi = scipy.signal.lfilter(b, a, y_saw[c:c_end], zi=zi)
        y_acid[c:c_end] = filtered.astype(np.float32)

    # Follow original bass dynamics
    orig_env = np.abs(y_bass)
    orig_env = scipy.signal.savgol_filter(orig_env, min(8001, len(orig_env)//2*2-1), 3)
    orig_env = np.clip(orig_env, 0, None)
    mx = np.max(orig_env)
    if mx > 0:
        orig_env /= mx
    n_env = min(len(orig_env), len(y_acid))
    y_acid[:n_env] *= orig_env[:n_env].astype(np.float32)

    # Sub-filter: keep acid bass below 600Hz for warmth
    sos_lp = scipy.signal.butter(4, 600, btype='low', fs=SR, output='sos')
    y_acid = scipy.signal.sosfilt(sos_lp, y_acid).astype(np.float32)

    # Normalize
    mx = np.max(np.abs(y_acid))
    if mx > 0:
        y_acid /= mx

    return y_acid


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",     required=True, help="Studio synth MP3 to process")
    ap.add_argument("--bass-stem", required=True, help="Original bass.wav for acid resynthesis")
    ap.add_argument("--out",       required=True, help="Output MP3")
    ap.add_argument("--volume",    type=float, default=0.5,
                    help="Overall volume multiplier (0.5 = half = -6dB). Default: 0.5")
    ap.add_argument("--acid-level",type=float, default=0.70,
                    help="Acid bass level in mix. Default: 0.70")
    ap.add_argument("--Q",         type=float, default=10.0,
                    help="Resonance Q (higher = more squelchy). Default: 10.0")
    args = ap.parse_args()

    print(f"Input: {args.input}")
    print(f"Bass stem: {args.bass_stem}")
    print(f"Volume: ×{args.volume} ({20*np.log10(args.volume):.1f}dB)")
    print()

    # Load existing studio mix
    print("Loading studio synth mix...")
    y_mix, _ = librosa.load(args.input, sr=SR, mono=False)
    if y_mix.ndim == 1:
        y_mix = np.stack([y_mix, y_mix])
    n_mix = y_mix.shape[1]

    # Remove original bass from mix (HP filter at 220Hz)
    print("Removing old bass from mix (HP 220Hz)...")
    sos_hp = scipy.signal.butter(4, 220, btype='high', fs=SR, output='sos')
    y_mix_hp = np.stack([
        scipy.signal.sosfilt(sos_hp, y_mix[0]),
        scipy.signal.sosfilt(sos_hp, y_mix[1]),
    ]).astype(np.float32)

    # Also reduce low-mids (sub shelf cut)
    sos_shelf = scipy.signal.butter(2, 180, btype='high', fs=SR, output='sos')
    y_mix_hp[0] = scipy.signal.sosfilt(sos_shelf, y_mix_hp[0]).astype(np.float32)
    y_mix_hp[1] = scipy.signal.sosfilt(sos_shelf, y_mix_hp[1]).astype(np.float32)

    # Generate acid bass
    print("\n── ACID BASS ──")
    y_acid = synth_acid_bass(
        args.bass_stem,
        Q=args.Q,
        cutoff_max=2200.0,
        cutoff_min=100.0,
        sweep_ms=380.0
    )

    # Trim/pad acid to match mix length
    if len(y_acid) > n_mix:
        y_acid = y_acid[:n_mix]
    else:
        y_acid = np.pad(y_acid, (0, n_mix - len(y_acid)))

    # ── Mixdown ──
    print("\n── MIXDOWN ──")
    mix = np.zeros((2, n_mix), dtype=np.float32)
    mix[0] = y_mix_hp[0] * 0.85 + y_acid * args.acid_level
    mix[1] = y_mix_hp[1] * 0.85 + y_acid * args.acid_level

    # Apply volume (2x quieter = 0.5)
    mix *= args.volume

    # Light master compression via pedalboard
    if HAS_PEDALBOARD:
        print("  Master bus compression (light, no pumping)...")
        board = Pedalboard([
            Compressor(threshold_db=-16, ratio=2.0, attack_ms=20, release_ms=200),
            Gain(gain_db=1),
        ])
        for ch in range(2):
            mix[ch] = board(mix[ch].reshape(1, -1), SR).flatten().astype(np.float32)

    # Peak normalize to -4dBFS
    mx = np.max(np.abs(mix))
    if mx > 0:
        mix = mix / mx * 0.631  # -4dBFS

    # ── Export ──
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = tmp.name

    print(f"  Writing WAV...")
    sf.write(tmp_wav, mix.T, SR, subtype='PCM_24')

    print(f"  Encoding → {args.out}")
    cmd = ["ffmpeg", "-y", "-i", tmp_wav,
           "-af", "loudnorm=I=-20:TP=-2:LRA=11",
           "-c:a", "libmp3lame", "-b:a", "320k",
           args.out]
    r = subprocess.run(cmd, capture_output=True)
    os.unlink(tmp_wav)

    if r.returncode != 0:
        print(r.stderr.decode()[-1000:], file=sys.stderr)
        sys.exit(1)

    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"\n✓ Готово: {args.out} ({size:.1f} MB, 320kbps)")
    print("  Style: Acid downtempo (TB-303 bass + supersaw pads + soft 808)")
    print("  Level: quiet background mix (-6dB)")


if __name__ == "__main__":
    main()
