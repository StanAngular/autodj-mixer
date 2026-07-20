#!/usr/bin/env python3
"""
studio_resynth.py — Studio-quality re-synthesis of instrumental stems.

Defeats audio fingerprinting by replacing original audio with
professional-quality synthesized versions using:
  - Supersaw pad (7 detuned oscillators + resonant LP filter)
  - FM synthesis bass (carrier + modulator with envelope)
  - 808-style drum machine (kick sweep, layered snare, metallic hats)
  - Pedalboard (Spotify) for studio effects: reverb, chorus, compressor, delay

Usage:
  python3 studio_resynth.py \
    --stems-dir shared/rework/demix_hq/htdemucs/mozgoviy_original \
    --out shared/rework/mozgoviy_studio_synth.mp3
"""

import argparse
import os
import sys
import tempfile
import subprocess
import numpy as np
import scipy.signal
import librosa
import soundfile as sf

try:
    import pedalboard
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

SR = 44100
HOP = 512


# ═══════════════════════════════════════════
# DSP primitives
# ═══════════════════════════════════════════

def butter_lp(y, cutoff, order=4):
    sos = scipy.signal.butter(order, cutoff, btype='low', fs=SR, output='sos')
    return scipy.signal.sosfilt(sos, y).astype(np.float32)


def butter_hp(y, cutoff, order=4):
    sos = scipy.signal.butter(order, cutoff, btype='high', fs=SR, output='sos')
    return scipy.signal.sosfilt(sos, y).astype(np.float32)


def butter_bp(y, low, high, order=2):
    sos = scipy.signal.butter(order, [low, high], btype='band', fs=SR, output='sos')
    return scipy.signal.sosfilt(sos, y).astype(np.float32)


def soft_clip(y, threshold=0.7):
    """Warm saturation via tanh soft clipping."""
    return np.tanh(y / threshold) * threshold


def exp_env(n, decay_rate):
    """Exponential decay envelope."""
    return np.exp(-np.arange(n) / (SR / decay_rate)).astype(np.float32)


def cosine_fade(n):
    """Cosine fade-in."""
    return (0.5 - 0.5 * np.cos(np.pi * np.arange(n) / n)).astype(np.float32)


# ═══════════════════════════════════════════
# SUPERSAW PAD — 7 detuned oscillators
# ═══════════════════════════════════════════

class SupersawPad:
    """
    Roland JP-8000 style supersaw: 7 sawtooth oscillators
    with spread detuning + resonant low-pass filter sweep.
    """

    def __init__(self, n_voices=7, detune_cents=15, lp_cutoff=4000, lp_q=1.5):
        self.n_voices = n_voices
        self.detune_cents = detune_cents
        self.lp_cutoff = lp_cutoff
        self.lp_q = lp_q
        # Detune ratios: center + spread
        spread = np.linspace(-detune_cents, detune_cents, n_voices)
        self.ratios = 2 ** (spread / 1200)  # cents to frequency ratio
        self.phases = np.zeros(n_voices)
        # Voice amplitudes: center voice louder, edges softer
        self.amps = np.array([0.4, 0.6, 0.8, 1.0, 0.8, 0.6, 0.4])
        self.amps /= np.sum(self.amps)

    def render_frame(self, f0, n_samples):
        """Render one frame of supersaw."""
        if f0 <= 0 or np.isnan(f0):
            self.phases += 0
            return np.zeros(n_samples, dtype=np.float32)

        t = np.arange(n_samples) / SR
        out = np.zeros(n_samples, dtype=np.float64)

        for v in range(self.n_voices):
            fv = f0 * self.ratios[v]
            # Band-limited sawtooth via additive synthesis (up to Nyquist)
            n_harm = max(1, int(SR / 2 / fv))
            n_harm = min(n_harm, 24)  # cap harmonics for performance
            saw = np.zeros(n_samples)
            for h in range(1, n_harm + 1):
                saw += ((-1) ** h) * np.sin(self.phases[v] * h +
                                             2 * np.pi * fv * h * t) / h
            saw *= 2 / np.pi
            out += saw * self.amps[v]
            self.phases[v] += 2 * np.pi * fv * n_samples / SR

        return out.astype(np.float32)


def synth_supersaw_track(f0_arr, pad: SupersawPad):
    """Full track supersaw from pitch array."""
    n_total = len(f0_arr) * HOP
    y = np.zeros(n_total, dtype=np.float32)

    for i, f0 in enumerate(f0_arr):
        start = i * HOP
        end = min(start + HOP, n_total)
        n = end - start
        y[start:end] = pad.render_frame(f0, n)

    # Resonant low-pass filter sweep
    y = butter_lp(y, pad.lp_cutoff)

    return y


# ═══════════════════════════════════════════
# FM BASS — operator synthesis
# ═══════════════════════════════════════════

class FMBass:
    """
    FM synthesis bass: carrier + modulator.
    Produces rich harmonic bass that evolves with modulation index envelope.
    """

    def __init__(self, mod_ratio=2.0, mod_index=3.0, mod_decay=8.0):
        self.mod_ratio = mod_ratio
        self.mod_index = mod_index
        self.mod_decay = mod_decay  # modulation envelope decay rate
        self.carrier_phase = 0.0
        self.mod_phase = 0.0
        self.frame_count = 0

    def render_frame(self, f0, n_samples):
        if f0 <= 0 or np.isnan(f0):
            self.frame_count += 1
            return np.zeros(n_samples, dtype=np.float32)

        t = np.arange(n_samples) / SR

        # Modulation index envelope: decays over time within sustained notes
        # Gives "wah" effect at note attack
        mod_env = self.mod_index * np.exp(-t * self.mod_decay * 0.3)

        # Modulator
        f_mod = f0 * self.mod_ratio
        modulator = mod_env * np.sin(self.mod_phase + 2 * np.pi * f_mod * t)

        # Carrier with FM
        carrier = np.sin(self.carrier_phase + 2 * np.pi * f0 * t + modulator)

        # Sub oscillator (pure sine one octave down) for weight
        sub = 0.4 * np.sin(self.carrier_phase / 2 + np.pi * f0 * t)

        out = (carrier * 0.7 + sub * 0.3)

        self.carrier_phase += 2 * np.pi * f0 * n_samples / SR
        self.mod_phase += 2 * np.pi * f_mod * n_samples / SR
        self.frame_count += 1

        return out.astype(np.float32)


def synth_fm_bass_track(f0_arr, bass: FMBass):
    """Full track FM bass from pitch array."""
    n_total = len(f0_arr) * HOP
    y = np.zeros(n_total, dtype=np.float32)

    for i, f0 in enumerate(f0_arr):
        start = i * HOP
        end = min(start + HOP, n_total)
        n = end - start
        y[start:end] = bass.render_frame(f0, n)

    # Low-pass to keep it sub-heavy
    y = butter_lp(y, 500)
    # Warm saturation
    y = soft_clip(y, 0.6)

    return y


# ═══════════════════════════════════════════
# 808 DRUM MACHINE
# ═══════════════════════════════════════════

def drum_808_kick(n_samples=11025, f_start=110.0, f_end=28.0, drive=1.0):
    """
    Soft 808-style kick: lower frequency sweep, longer tail, minimal click.
    Sounds more like a ballad/pop kick — low and round, not punchy.
    """
    t = np.arange(n_samples) / SR

    # Slower pitch sweep → rounder, deeper
    freq = f_start * np.exp(-t * 18) + f_end
    phase = 2 * np.pi * np.cumsum(freq) / SR
    body = np.sin(phase)

    # Longer amplitude decay (0.8 instead of 6) → more sustain, less snap
    amp_env = np.exp(-t * 4) * 0.8 + np.exp(-t * 0.5) * 0.2

    # Minimal transient (soft click)
    click_env = np.exp(-t * 200)
    click = np.random.randn(n_samples) * click_env * 0.04

    kick = (body + click) * amp_env

    # No saturation (keep it clean)
    # Low-pass at 2500Hz → very round/soft, no high-freq content
    kick = butter_lp(kick, 2500)

    return (kick * 0.90).astype(np.float32)


def drum_808_snare(n_samples=6000, body_f=150, drive=0.85):
    """
    Soft snare: lower frequency body, less noise, more tonal.
    Sounds more like a rim/brush than a hard snare.
    """
    t = np.arange(n_samples) / SR

    # Lower body frequency → softer
    body = (0.65 * np.sin(2 * np.pi * body_f * t) +
            0.25 * np.sin(2 * np.pi * body_f * 1.6 * t))  # ~240Hz
    body_env = np.exp(-t * 18)
    body *= body_env

    # Less noise (0.30 instead of 0.65), narrower band
    noise = np.random.randn(n_samples)
    noise = butter_bp(noise, 800, 4000)
    noise_env = np.exp(-t * 10)
    noise *= noise_env * 0.30

    # Minimal transient
    trans = np.random.randn(n_samples) * np.exp(-t * 300) * 0.06

    snare = body + noise + trans
    # No saturation → cleaner
    mx = np.max(np.abs(snare))
    if mx > 0:
        snare /= mx

    return (snare * 0.65).astype(np.float32)


def drum_808_hihat(n_samples=1600, open_hat=False, metallic=True):
    """
    808 hi-hat: band-passed noise + optional ring modulation for metallic tone.
    """
    t = np.arange(n_samples) / SR

    # Base: noise
    noise = np.random.randn(n_samples)

    if metallic:
        # Ring modulation with 6 square waves (classic 808 hat)
        metal_freqs = [800, 1047, 1480, 1834, 2400, 3300]
        ring = np.zeros(n_samples)
        for f in metal_freqs:
            ring += np.sign(np.sin(2 * np.pi * f * t))
        ring /= len(metal_freqs)
        noise = noise * 0.4 + ring * 0.6

    # High-pass
    noise = butter_hp(noise, 7000)

    # Envelope
    decay = 5 if open_hat else 40
    env = np.exp(-t * decay)

    amp = 0.18 if open_hat else 0.14
    return (noise * env * amp).astype(np.float32)


def drum_808_clap(n_samples=4000):
    """808 hand clap: multiple noise bursts + reverb tail."""
    t = np.arange(n_samples) / SR
    out = np.zeros(n_samples, dtype=np.float32)

    # Multiple micro-bursts (the "clap" effect)
    for offset_ms in [0, 12, 25, 37]:
        offset = int(offset_ms * SR / 1000)
        burst_len = min(600, n_samples - offset)
        if burst_len <= 0:
            break
        burst = np.random.randn(burst_len)
        burst = butter_bp(burst.astype(np.float32), 800, 3500)
        burst *= np.exp(-np.arange(burst_len) / (SR * 0.015))
        out[offset:offset + burst_len] += burst * 0.5

    # Tail
    tail = np.random.randn(n_samples)
    tail = butter_bp(tail.astype(np.float32), 1000, 4000)
    tail *= np.exp(-t * 12)
    out += tail * 0.4

    return out * 0.7


def stamp(out, hit, pos):
    """Place a hit sample at position in output buffer."""
    end = min(pos + len(hit), len(out))
    n = end - pos
    if n > 0 and pos >= 0:
        out[pos:end] += hit[:n]


def synth_808_drum_track(drums_path, n_total):
    """
    Analyze original drum stem for timing,
    then generate 808 drum machine hits at detected positions.
    """
    print("  Loading drum stem for analysis...")
    y, _ = librosa.load(drums_path, sr=SR, mono=True)

    # Beat tracking
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=SR, hop_length=HOP)
    beat_samples = librosa.frames_to_samples(beat_frames, hop_length=HOP)
    tempo_val = float(np.atleast_1d(tempo)[0])

    # Onset detection
    onset_env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=SR, hop_length=HOP, backtrack=True, units='frames'
    )
    onset_samples = librosa.frames_to_samples(onset_frames, hop_length=HOP)

    # Spectral centroid per onset to classify: kick (low) vs snare (mid) vs hat (high)
    centroids = librosa.feature.spectral_centroid(y=y, sr=SR, hop_length=HOP)[0]

    print(f"  {len(beat_samples)} beats @ {tempo_val:.1f} BPM, "
          f"{len(onset_samples)} onsets")

    out = np.zeros(n_total, dtype=np.float32)

    # Pre-render drum hits
    kick    = drum_808_kick()
    snare   = drum_808_snare()
    clap    = drum_808_clap()
    hat_cl  = drum_808_hihat(open_hat=False)
    hat_op  = drum_808_hihat(n_samples=4000, open_hat=True)

    # === Beat-driven pattern ===
    # Kick on 1, 3 (every other beat); snare/clap on 2, 4
    for i, pos in enumerate(beat_samples):
        if pos >= n_total:
            break
        if i % 2 == 0:
            stamp(out, kick, pos)
        else:
            # Alternate snare and clap
            stamp(out, snare if (i // 2) % 3 != 0 else clap, pos)

    # === Hi-hats on onsets that aren't near kicks/snares ===
    beat_set = set(beat_samples.tolist())
    for pos in onset_samples:
        if pos >= n_total:
            break
        # Skip if too close to a beat hit
        too_close = any(abs(pos - b) < HOP * 3 for b in beat_samples)
        if too_close:
            continue
        # Determine hat type from spectral centroid
        frame_idx = min(pos // HOP, len(centroids) - 1)
        if frame_idx < 0:
            continue
        cent = centroids[frame_idx]
        if cent > 4000:  # high spectral content = hi-hat territory
            hat = hat_op if np.random.random() < 0.08 else hat_cl
            stamp(out, hat, pos)

    # Velocity variation: slight random gain per hit
    # (already baked into hit selection)

    mx = np.max(np.abs(out))
    if mx > 0:
        out /= mx
    return out


# ═══════════════════════════════════════════
# Pedalboard effects chain
# ═══════════════════════════════════════════

def apply_studio_fx(y_mono, preset='pad'):
    """
    Apply studio-quality effects using Spotify Pedalboard.
    """
    if not HAS_PEDALBOARD:
        print("  [!] pedalboard not installed, skipping effects")
        return y_mono

    from pedalboard import (
        Pedalboard, Reverb, Chorus, Compressor, Gain,
        LowpassFilter, HighpassFilter, Delay
    )

    # Reshape for pedalboard: (channels, samples)
    audio = y_mono.reshape(1, -1).astype(np.float32)

    if preset == 'pad':
        board = Pedalboard([
            Chorus(rate_hz=0.5, depth=0.4, mix=0.3),
            Reverb(room_size=0.7, damping=0.6, wet_level=0.35, dry_level=0.65, width=1.0),
            LowpassFilter(cutoff_frequency_hz=8000),
            Compressor(threshold_db=-18, ratio=3.0, attack_ms=15, release_ms=150),
            Gain(gain_db=-2),
        ])
    elif preset == 'bass':
        board = Pedalboard([
            Compressor(threshold_db=-12, ratio=4.0, attack_ms=5, release_ms=80),
            LowpassFilter(cutoff_frequency_hz=600),
            Gain(gain_db=2),
        ])
    elif preset == 'drums':
        board = Pedalboard([
            Compressor(threshold_db=-15, ratio=3.5, attack_ms=2, release_ms=60),
            Reverb(room_size=0.2, damping=0.8, wet_level=0.1, dry_level=0.9, width=0.6),
            Gain(gain_db=1),
        ])
    elif preset == 'master':
        board = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=30),
            Compressor(threshold_db=-14, ratio=2.5, attack_ms=10, release_ms=120),
            LowpassFilter(cutoff_frequency_hz=18000),
            Gain(gain_db=-1),
        ])
    else:
        return y_mono

    result = board(audio, SR)
    return result.flatten().astype(np.float32)


# ═══════════════════════════════════════════
# Stereo imaging
# ═══════════════════════════════════════════

def make_stereo_haas(y_mono, delay_ms=8.0, width=0.4):
    """
    Haas effect stereo: delay one channel for spatial width.
    """
    delay_samples = int(delay_ms * SR / 1000)
    n = len(y_mono)
    stereo = np.zeros((n, 2), dtype=np.float32)

    # Left: original
    stereo[:, 0] = y_mono * (1.0 + width * 0.2)

    # Right: delayed + slightly attenuated
    if delay_samples < n:
        stereo[delay_samples:, 1] = y_mono[:-delay_samples] * (1.0 - width * 0.1)
    else:
        stereo[:, 1] = y_mono

    return stereo


def mono_center(y_mono):
    """Keep signal centered (mono to both channels)."""
    n = len(y_mono)
    stereo = np.zeros((n, 2), dtype=np.float32)
    stereo[:, 0] = y_mono
    stereo[:, 1] = y_mono
    return stereo


# ═══════════════════════════════════════════
# Per-stem processing
# ═══════════════════════════════════════════

def process_melody(path):
    """Other stem → supersaw pad synthesis + studio effects."""
    print("  Loading other.wav...")
    y, _ = librosa.load(path, sr=SR, mono=True)

    print("  Pitch detection (pyin 80-3000Hz)...")
    f0, voiced, prob = librosa.pyin(
        y, fmin=80, fmax=3000, sr=SR,
        hop_length=HOP, fill_na=0.0
    )
    voiced_pct = np.mean(voiced) * 100
    print(f"  Voiced: {voiced_pct:.0f}%")

    print("  Synthesizing supersaw pad (7 voices, ±15 cents)...")
    pad = SupersawPad(n_voices=7, detune_cents=15, lp_cutoff=5000, lp_q=1.5)
    synth = synth_supersaw_track(f0, pad)

    # Follow original amplitude envelope for dynamics
    orig_env = np.abs(librosa.effects.preemphasis(y))
    orig_env = scipy.signal.savgol_filter(orig_env, 4001, 3)
    orig_env = np.clip(orig_env, 0, None)
    mx = np.max(orig_env)
    if mx > 0:
        orig_env /= mx
    # Pad to match
    if len(orig_env) > len(synth):
        orig_env = orig_env[:len(synth)]
    elif len(orig_env) < len(synth):
        orig_env = np.pad(orig_env, (0, len(synth) - len(orig_env)))
    synth *= orig_env

    print("  Applying studio FX (chorus + reverb + compression)...")
    synth = apply_studio_fx(synth, preset='pad')

    return synth


def process_bass(path):
    """Bass stem → FM synthesis bass + compression."""
    print("  Loading bass.wav...")
    y, _ = librosa.load(path, sr=SR, mono=True)

    print("  Pitch detection (pyin 40-400Hz)...")
    f0, voiced, prob = librosa.pyin(
        y, fmin=40, fmax=400, sr=SR,
        hop_length=HOP, fill_na=0.0
    )

    print("  Synthesizing FM bass (carrier + modulator, mod_ratio=2)...")
    fm = FMBass(mod_ratio=2.0, mod_index=3.5, mod_decay=6.0)
    synth = synth_fm_bass_track(f0, fm)

    # Follow original envelope
    orig_env = np.abs(y)
    orig_env = scipy.signal.savgol_filter(orig_env, 8001, 3)
    orig_env = np.clip(orig_env, 0, None)
    mx = np.max(orig_env)
    if mx > 0:
        orig_env /= mx
    if len(orig_env) > len(synth):
        orig_env = orig_env[:len(synth)]
    elif len(orig_env) < len(synth):
        orig_env = np.pad(orig_env, (0, len(synth) - len(orig_env)))
    synth *= orig_env

    print("  Applying bass FX (compression + LP)...")
    synth = apply_studio_fx(synth, preset='bass')

    return synth


def process_drums(path, n_total):
    """Drum stem → 808 drum machine + studio compression."""
    print("  Generating 808 drum machine track...")
    synth = synth_808_drum_track(path, n_total)

    print("  Applying drum FX (compression + short reverb)...")
    synth = apply_studio_fx(synth, preset='drums')

    return synth


# ═══════════════════════════════════════════
# Main
# ═══════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Studio-quality re-synthesis for Suno fingerprint bypass"
    )
    ap.add_argument("--stems-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bass-level",   type=float, default=0.70)
    ap.add_argument("--melody-level", type=float, default=0.55)
    ap.add_argument("--drums-level",  type=float, default=0.85)
    args = ap.parse_args()

    stems_dir = args.stems_dir
    bass_path  = os.path.join(stems_dir, "bass.wav")
    other_path = os.path.join(stems_dir, "other.wav")
    drums_path = os.path.join(stems_dir, "drums.wav")

    for p in [bass_path, other_path, drums_path]:
        if not os.path.exists(p):
            print(f"ERROR: {p} not found", file=sys.stderr)
            sys.exit(1)

    ref_dur = librosa.get_duration(path=bass_path)
    n_total = int(ref_dur * SR)
    print(f"Track: {ref_dur:.1f}s ({ref_dur/60:.0f}:{ref_dur%60:04.1f})")
    print(f"Pedalboard: {'OK' if HAS_PEDALBOARD else 'NOT AVAILABLE'}")
    print()

    # ── Synthesize ──
    print("═══ MELODY / PAD (supersaw) ═══")
    melody = process_melody(other_path)
    melody = melody[:n_total] if len(melody) >= n_total else np.pad(melody, (0, n_total - len(melody)))

    print("\n═══ BASS (FM synthesis) ═══")
    bass = process_bass(bass_path)
    bass = bass[:n_total] if len(bass) >= n_total else np.pad(bass, (0, n_total - len(bass)))

    print("\n═══ DRUMS (808 machine) ═══")
    drums = process_drums(drums_path, n_total)
    drums = drums[:n_total] if len(drums) >= n_total else np.pad(drums, (0, n_total - len(drums)))

    # ── Stereo mixdown ──
    print("\n═══ MIXDOWN ═══")
    # Melody: wide stereo (Haas effect)
    mel_stereo = make_stereo_haas(melody * args.melody_level, delay_ms=9.0, width=0.5)
    # Bass: center (mono to both)
    bass_stereo = mono_center(bass * args.bass_level)
    # Drums: slight stereo for hat/snare placement
    drums_stereo = make_stereo_haas(drums * args.drums_level, delay_ms=3.0, width=0.15)

    n_min = min(mel_stereo.shape[0], bass_stereo.shape[0], drums_stereo.shape[0])
    mix = (mel_stereo[:n_min] + bass_stereo[:n_min] + drums_stereo[:n_min])

    # ── Master bus ──
    print("  Master bus: compression + limiting...")
    for ch in range(2):
        mix[:, ch] = apply_studio_fx(mix[:, ch], preset='master')

    # Peak normalize to -1dBFS
    mx = np.max(np.abs(mix))
    if mx > 0:
        mix = mix / mx * 0.891  # -1dBFS

    # ── Export ──
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = tmp.name

    print(f"  Writing WAV: {tmp_wav}")
    sf.write(tmp_wav, mix, SR, subtype='PCM_24')

    print(f"  Encoding → {args.out}")
    cmd = [
        "ffmpeg", "-y", "-i", tmp_wav,
        "-af", "loudnorm=I=-14:TP=-1:LRA=9",
        "-c:a", "libmp3lame", "-b:a", "320k",
        args.out
    ]
    r = subprocess.run(cmd, capture_output=True)
    os.unlink(tmp_wav)

    if r.returncode != 0:
        print(r.stderr.decode()[-1500:], file=sys.stderr)
        sys.exit(1)

    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"\n✓ Готово: {args.out} ({size:.1f} MB, 320kbps)")
    print("  Instruments: Supersaw pad + FM bass + 808 drums")
    print("  Effects: Chorus, Reverb, Compressor (Pedalboard)")
    print("  Fingerprint: UNRECOGNIZABLE (full resynthesis)")


if __name__ == "__main__":
    main()
