#!/usr/bin/env python3
"""
midi_resynth.py — Re-synthesize instrumental stems using pure Python synthesis.

Defeats audio fingerprinting by replacing original audio with synthesized versions:
  - Bass:   pyin pitch detection → sine + 2nd harmonic bass synth
  - Other:  pyin pitch detection → sawtooth additive synthesis (pad sound)
  - Drums:  onset/beat detection → synthetic kick/snare/hihat from scratch

No fluidsynth, no basic_pitch needed. Only librosa + scipy + numpy.

Usage:
  python3 midi_resynth.py \
    --stems-dir shared/rework/demix_hq/htdemucs/mozgoviy_original \
    --out shared/rework/mozgoviy_midi_synth.mp3 \
    [--bass-level 0.7] [--melody-level 0.5] [--drums-level 0.8]
"""

import argparse
import os
import sys
import numpy as np
import scipy.signal
import librosa
import soundfile as sf
import subprocess
import tempfile

SR = 44100
HOP = 512


# ─────────────────────────────────────────
# Synthesis primitives
# ─────────────────────────────────────────

def low_pass(y, cutoff_hz, order=4):
    sos = scipy.signal.butter(order, cutoff_hz, btype='low', fs=SR, output='sos')
    return scipy.signal.sosfilt(sos, y)


def high_pass(y, cutoff_hz, order=4):
    sos = scipy.signal.butter(order, cutoff_hz, btype='high', fs=SR, output='sos')
    return scipy.signal.sosfilt(sos, y)


def adsr_env(n, atk_s=0.005, dec_s=0.05, sus=0.6, rel_s=0.1):
    """Per-note ADSR envelope."""
    env = np.ones(n) * sus
    a = int(atk_s * SR)
    d = int(dec_s * SR)
    r = int(rel_s * SR)
    if a > 0:
        env[:min(a, n)] = np.linspace(0, 1, min(a, n))
    if d > 0 and a + d < n:
        env[a:a + d] = np.linspace(1, sus, d)
    if r > 0 and n > r:
        env[-r:] = np.linspace(sus, 0, r)
    return env.astype(np.float32)


def synth_sawtooth(f0_arr, n_harmonics=12):
    """
    Additive sawtooth from pitch track.
    f0_arr: array of Hz per HOP frame (0 = silence)
    Returns float32 mono array.
    """
    n_samples = len(f0_arr) * HOP
    y = np.zeros(n_samples, dtype=np.float64)
    phases = np.zeros(n_harmonics + 1)  # phase per harmonic

    for i, f0 in enumerate(f0_arr):
        start = i * HOP
        end = min(start + HOP, n_samples)
        n = end - start

        if f0 <= 0 or np.isnan(f0):
            phases += 0
            continue

        t = np.arange(n) / SR
        chunk = np.zeros(n)
        for h in range(1, n_harmonics + 1):
            fh = f0 * h
            if fh >= SR / 2:
                break
            amp = 1.0 / h
            chunk += amp * np.sin(phases[h] + 2 * np.pi * fh * t)
            phases[h] += 2 * np.pi * fh * n / SR

        y[start:end] += chunk

    # Normalize
    mx = np.max(np.abs(y))
    if mx > 0:
        y /= mx
    return y.astype(np.float32)


def synth_bass(f0_arr):
    """
    Sine + 2nd harmonic bass synth from pitch track.
    Low-passed at 300Hz for clean sub bass character.
    """
    n_samples = len(f0_arr) * HOP
    y = np.zeros(n_samples, dtype=np.float64)
    ph1 = 0.0
    ph2 = 0.0

    for i, f0 in enumerate(f0_arr):
        start = i * HOP
        end = min(start + HOP, n_samples)
        n = end - start

        if f0 <= 0 or np.isnan(f0):
            continue

        t = np.arange(n) / SR
        chunk = (0.75 * np.sin(ph1 + 2 * np.pi * f0 * t) +
                 0.25 * np.sin(ph2 + 2 * np.pi * 2 * f0 * t))
        y[start:end] += chunk
        ph1 += 2 * np.pi * f0 * n / SR
        ph2 += 2 * np.pi * 2 * f0 * n / SR

    # Low-pass for sub bass feel
    y = low_pass(y, 400)

    mx = np.max(np.abs(y))
    if mx > 0:
        y /= mx
    return y.astype(np.float32)


# ─────────────────────────────────────────
# Drum synthesis
# ─────────────────────────────────────────

def synth_kick(n_samples=2048, f_start=150.0, f_end=40.0, amp=1.0):
    """Synthesize a kick drum: exponential frequency sweep + noise transient."""
    t = np.arange(n_samples) / SR
    # Frequency sweep
    freq = f_start * (f_end / f_start) ** (t / t[-1])
    phase = 2 * np.pi * np.cumsum(freq) / SR
    tone = np.sin(phase)
    # Amplitude envelope: fast decay
    env = np.exp(-t * 25)
    # Noise click at attack
    click = np.random.randn(n_samples) * np.exp(-t * 200) * 0.3
    kick = (tone + click) * env * amp
    return kick.astype(np.float32)


def synth_snare(n_samples=3000, amp=0.8):
    """Synthesize a snare: tonal body + noise burst."""
    t = np.arange(n_samples) / SR
    # Tonal component
    tone = (0.5 * np.sin(2 * np.pi * 185 * t) +
            0.3 * np.sin(2 * np.pi * 320 * t)) * np.exp(-t * 30)
    # Noise component (the "snare wire" sound)
    noise = np.random.randn(n_samples) * np.exp(-t * 18) * 0.7
    noise = high_pass(noise, 800)
    snare = (tone + noise) * amp
    return snare.astype(np.float32)


def synth_hihat(n_samples=800, amp=0.4, open_hat=False):
    """Synthesize hi-hat: high-pass filtered noise."""
    t = np.arange(n_samples) / SR
    noise = np.random.randn(n_samples)
    noise = high_pass(noise, 6000)
    decay_rate = 8 if open_hat else 40
    env = np.exp(-t * decay_rate) * amp
    return (noise * env).astype(np.float32)


def stamp_hit(out, hit, position):
    """Stamp a hit sample into output array at position."""
    end = min(position + len(hit), len(out))
    n = end - position
    if n > 0:
        out[position:end] += hit[:n]


def synth_drum_track(drums_wav_path, n_total_samples):
    """
    Detect onsets and beats from original drum stem,
    then generate synthetic drum hits at those times.
    """
    print("  Loading drum stem for beat/onset detection...")
    y_drums, sr = librosa.load(drums_wav_path, sr=SR, mono=True)

    # Beat tracking
    tempo, beat_frames = librosa.beat.beat_track(y=y_drums, sr=SR, hop_length=HOP)
    beat_samples = librosa.frames_to_samples(beat_frames, hop_length=HOP)

    # Onset detection for subdivisions (8th notes, snare hits)
    onset_frames = librosa.onset.onset_detect(
        y=y_drums, sr=SR, hop_length=HOP,
        backtrack=True, units='frames'
    )
    onset_samples = librosa.frames_to_samples(onset_frames, hop_length=HOP)

    tempo_val = float(np.atleast_1d(tempo)[0])
    print(f"  Detected {len(beat_samples)} beats @ ~{tempo_val:.1f} BPM, "
          f"{len(onset_samples)} onsets")

    out = np.zeros(n_total_samples, dtype=np.float32)

    # Pre-synthesize hits
    kick = synth_kick()
    snare = synth_snare()
    hihat_closed = synth_hihat(open_hat=False)
    hihat_open = synth_hihat(n_samples=1200, open_hat=True, amp=0.3)

    # Stamp beats: kick on downbeats (every 2 beats), snare on offbeats
    for i, pos in enumerate(beat_samples):
        if pos >= n_total_samples:
            break
        if i % 2 == 0:
            stamp_hit(out, kick, pos)
        else:
            stamp_hit(out, snare, pos)

    # Stamp hi-hats on onsets (but not on beat positions already handled)
    beat_set = set(beat_samples)
    for pos in onset_samples:
        if pos >= n_total_samples:
            break
        # Skip positions too close to a kick/snare
        if any(abs(pos - b) < HOP * 2 for b in beat_samples):
            continue
        hat = hihat_open if np.random.random() < 0.1 else hihat_closed
        stamp_hit(out, hat, pos)

    # Normalize
    mx = np.max(np.abs(out))
    if mx > 0:
        out /= mx
    return out


# ─────────────────────────────────────────
# Per-stem processors
# ─────────────────────────────────────────

def process_melodic(path, n_harmonics=10):
    print(f"  Loading {os.path.basename(path)}...")
    y, _ = librosa.load(path, sr=SR, mono=True)

    print("  Detecting pitch (pyin)...")
    f0, voiced, prob = librosa.pyin(
        y, fmin=80, fmax=3000, sr=SR,
        hop_length=HOP, fill_na=0.0
    )

    voiced_pct = np.mean(voiced) * 100
    print(f"  Voiced: {voiced_pct:.0f}%  |  synthesizing sawtooth...")

    synth = synth_sawtooth(f0, n_harmonics=n_harmonics)

    # Smooth with light LP to reduce aliasing artifacts
    synth = low_pass(synth, 8000)
    return synth


def process_bass(path):
    print(f"  Loading {os.path.basename(path)}...")
    y, _ = librosa.load(path, sr=SR, mono=True)

    print("  Detecting bass pitch (pyin 30-400Hz)...")
    f0, voiced, prob = librosa.pyin(
        y, fmin=30, fmax=400, sr=SR,
        hop_length=HOP, fill_na=0.0
    )

    print(f"  Synthesizing sine bass...")
    synth = synth_bass(f0)
    return synth


def make_stereo(y_l, y_r=None, width=0.3):
    """Create stereo from mono with slight stereo widening."""
    if y_r is None:
        # Small delay + polarity for stereo effect
        delay = int(0.007 * SR)  # 7ms
        y_r = np.zeros_like(y_l)
        y_r[delay:] = y_l[:-delay] * (1 - width)
        y_l = y_l * (1 + width * 0.5)
    n = max(len(y_l), len(y_r))
    stereo = np.zeros((n, 2), dtype=np.float32)
    stereo[:len(y_l), 0] = y_l
    stereo[:len(y_r), 1] = y_r
    return stereo


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Re-synthesize instrumental stems to defeat audio fingerprinting"
    )
    ap.add_argument("--stems-dir", required=True,
                    help="Dir with bass.wav drums.wav other.wav")
    ap.add_argument("--out", required=True, help="Output MP3 path")
    ap.add_argument("--bass-level",   type=float, default=0.65)
    ap.add_argument("--melody-level", type=float, default=0.50)
    ap.add_argument("--drums-level",  type=float, default=0.80)
    ap.add_argument("--harmonics",    type=int,   default=10,
                    help="Harmonics for sawtooth synth (more = richer)")
    args = ap.parse_args()

    bass_path  = os.path.join(args.stems_dir, "bass.wav")
    other_path = os.path.join(args.stems_dir, "other.wav")
    drums_path = os.path.join(args.stems_dir, "drums.wav")

    for p in [bass_path, other_path, drums_path]:
        if not os.path.exists(p):
            print(f"ERROR: {p} not found", file=sys.stderr)
            sys.exit(1)

    # Determine total length from original
    ref_dur = librosa.get_duration(path=bass_path)
    n_total = int(ref_dur * SR)
    print(f"Track duration: {ref_dur:.1f}s = {n_total} samples\n")

    # ── Synthesize each stem ──
    print("── BASS ──")
    bass = process_bass(bass_path)
    bass = bass[:n_total] if len(bass) >= n_total else np.pad(bass, (0, n_total - len(bass)))

    print("\n── MELODY / CHORDS ──")
    melody = process_melodic(other_path, n_harmonics=args.harmonics)
    melody = melody[:n_total] if len(melody) >= n_total else np.pad(melody, (0, n_total - len(melody)))

    print("\n── DRUMS ──")
    drums = synth_drum_track(drums_path, n_total)
    drums = drums[:n_total] if len(drums) >= n_total else np.pad(drums, (0, n_total - len(drums)))

    # ── Mix ──
    print("\n── MIXING ──")
    mix = (bass   * args.bass_level +
           melody * args.melody_level +
           drums  * args.drums_level)

    # Normalize to -3dBFS
    mx = np.max(np.abs(mix))
    if mx > 0:
        mix = mix / mx * 0.707  # -3dBFS

    # Make stereo
    stereo = make_stereo(mix)

    # ── Export ──
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = tmp.name

    print(f"Saving temporary WAV: {tmp_wav}")
    sf.write(tmp_wav, stereo, SR, subtype='PCM_24')

    print(f"Encoding → {args.out}")
    cmd = [
        "ffmpeg", "-y", "-i", tmp_wav,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "libmp3lame", "-b:a", "320k",
        args.out
    ]
    r = subprocess.run(cmd, capture_output=True)
    os.unlink(tmp_wav)

    if r.returncode != 0:
        print(r.stderr.decode()[-1000:], file=sys.stderr)
        sys.exit(1)

    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"\nГотово: {args.out} ({size:.1f} MB)")
    print("Fingerprint: НОВА (повністю синтетичне аудіо)")


if __name__ == "__main__":
    main()
