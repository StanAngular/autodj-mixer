#!/usr/bin/env python3
"""
Cryogenesis v2 — Meditative Sleep Ambient / Drone
Duration: 22:22 (1342s)
BPM: 50 | Key: C Major Pentatonic (A=432 Hz)
Pure numpy/scipy synth — no VST3, no DawDreamer, predictable.
"""
import os, sys, math, time, logging
import numpy as np

sys.path.insert(0, '/opt/autodj-mixer')
os.chdir('/opt/autodj-mixer')

from autodj.generate.synthcore import (
    sine_wave, sawtooth_bl, square_bl, supersaw,
    lpf, hpf,
    adsr,
    apply_reverb, apply_compressor,
    midi_to_hz,
    normalize_master, mono_to_stereo,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('cryogenesis')

# ── Constants ──
BPM = 50
SR = 44100
BAR_S = 60.0 / BPM * 4          # 4.8 s
BEAT_S = BAR_S / 4               # 1.2 s
DURATION_S = 1342                 # 22:22
N_SAMPLES = int(DURATION_S * SR)

A432_RATIO = 432.0 / 440.0

def c_pent(octave=4):
    c = 261.63 * A432_RATIO * (2 ** (octave - 4))
    return {
        'C': c, 'D': c * 2**(2/12), 'E': c * 2**(4/12),
        'G': c * 2**(7/12), 'A': c * 2**(9/12),
    }

C1, C2, C3, C4, C5 = c_pent(1), c_pent(2), c_pent(3), c_pent(4), c_pent(5)

# Phase timing
PHASES = {
    'liquid':        (0,    300),     # 0:00-5:00
    'freezing':      (300,  660),     # 5:00-11:00
    'absolute_zero': (660,  1222),    # 11:00-20:22
    'void':          (1222, 1342),    # 20:22-22:22
}

def phase_at(t):
    for name, (s, e) in PHASES.items():
        if s <= t < e:
            return name, (t - s) / (e - s)
    return 'void', 1.0


def build_breathing_drone():
    """Brown noise + sub-bass with 10s breathing cycle (4s rise, 6s fall)."""
    log.info("Building breathing drone...")
    t0 = time.time()

    t = np.arange(N_SAMPLES) / SR

    # Brown noise: integrated white noise (low shelf)
    np.random.seed(0)
    white = np.random.randn(N_SAMPLES)
    brown = np.cumsum(white)
    brown = brown / np.max(np.abs(brown)) * 0.3
    # LP filter to tame highs
    brown = lpf(brown, 400, q=0.0, sr=SR)

    # Sub-bass: C1, G1, C2 pedal tones with slow chord shifts
    drone_roots = [C1['C'], C1['G'], C2['G'], C1['C'],
                   C2['C'], C2['G'], C1['G'], C1['C']]
    sub = np.zeros(N_SAMPLES)
    chord_dur = 16 * BAR_S  # ~77s per chord
    for i, root in enumerate(drone_roots):
        s = int(i * chord_dur * SR)
        e = int(min((i + 1) * chord_dur, DURATION_S) * SR)
        chunk = sine_wave(root, e - s if e > s else 0, sr=SR)
        # Add fifth
        fifth = sine_wave(root * 1.5, e - s if e > s else 0, sr=SR)
        sub[s:e] = (chunk * 0.6 + fifth * 0.3)

    # Breathing LFO: 10s cycle, 4s rise 6s fall, range 0.5-1.0
    phase = (t % 10.0) / 10.0
    rise_fraction = 4.0 / 10.0
    breath = np.where(phase < rise_fraction,
                      phase / rise_fraction,
                      1.0 - (phase - rise_fraction) / (1.0 - rise_fraction))
    breath = 0.5 + 0.5 * breath  # 0.5-1.0 range

    drone = brown * 0.4 + sub * 0.6
    drone = drone * breath
    drone = lpf(drone, 600, q=0.3, sr=SR)

    log.info(f"  Drone done: {time.time()-t0:.1f}s")
    return drone  # (N_SAMPLES,)


def build_binaural_pad():
    """Warm synth pad with L/R detune for 5 Hz binaural beat (theta waves)."""
    log.info("Building binaural pad...")
    t0 = time.time()

    t = np.arange(N_SAMPLES) / SR
    n_per_side = int(N_SAMPLES / SR)

    pad_chords = [
        [C4['C'], C4['E'], C4['G'], C5['C']],
        [C4['G'], C4['D'], C5['G'], C4['C']],
        [C4['A'], C4['C'], C4['E'], C5['A']],
        [C4['D'], C4['G'], C5['D'], C5['G']],
        [C4['C'], C4['G'], C4['A'], C5['E']],
        [C3['C'], C3['G'], C4['C'], C4['E']],
    ]

    left = np.zeros(N_SAMPLES)
    right = np.zeros(N_SAMPLES)
    chord_dur = 8 * BAR_S  # ~38s per chord

    for ci, chord in enumerate(pad_chords):
        s = int(ci * chord_dur * SR)
        e = int(min((ci + 1) * chord_dur, DURATION_S) * SR)
        if s >= N_SAMPLES:
            break
        n = e - s

        # Build chord mix: saw waves + sine sub
        l_ch = np.zeros(n)
        r_ch = np.zeros(n)
        for freq in chord:
            # Left: exact frequency
            l_ch += sawtooth_bl(freq, n, sr=SR) * 0.2
            # Right: +5 Hz detune for binaural beat
            r_ch += sawtooth_bl(freq + 5.0, n, sr=SR) * 0.2
            # Add soft sine
            l_ch += sine_wave(freq, n, sr=SR) * 0.15
            r_ch += sine_wave(freq + 5.0, n, sr=SR) * 0.15

        # LP filter for warmth
        l_ch = lpf(l_ch, 3000, q=0.15, sr=SR)
        r_ch = lpf(r_ch, 3000, q=0.15, sr=SR)

        left[s:e] = l_ch
        right[s:e] = r_ch

    # Phase-based volume envelope
    for i in range(N_SAMPLES):
        t_s = i / SR
        phase, prog = phase_at(t_s)
        if phase == 'liquid':
            vol = 0.08 + 0.12 * prog  # very quiet → growing
        elif phase == 'freezing':
            vol = 0.20 + 0.30 * prog
        elif phase == 'absolute_zero':
            vol = 0.50
        elif phase == 'void':
            fade_t = (t_s - PHASES['void'][0]) / 120.0
            vol = 0.50 * max(0, 1 - fade_t)
        else:
            vol = 0.0
        left[i] *= vol
        right[i] *= vol

    stereo = np.column_stack([left, right])

    # Reverb
    stereo = apply_reverb(stereo, sr=SR, room_size=0.6, damping=0.4)

    log.info(f"  Pad done: {time.time()-t0:.1f}s")
    return stereo  # (N_SAMPLES, 2)


def build_water_drops():
    """Muted plucks — gourd/tongue drum style, velocity-clamped 40-60."""
    log.info("Building water drops...")
    t0 = time.time()

    stereo = np.zeros((N_SAMPLES, 2), dtype=np.float32)
    np.random.seed(13)
    count = 0

    for t_s in np.arange(0, DURATION_S, 0.4):
        phase, prog = phase_at(t_s)
        prob = 0.0
        if phase == 'liquid':
            prob = 0.10 + 0.02 * np.sin(t_s * 0.08)
        elif phase == 'freezing':
            prob = 0.06 - 0.04 * prog
        elif phase in ('absolute_zero', 'void'):
            prob = 0.0

        if prob > 0 and np.random.random() < prob:
            # Short pluck: damped sine + noise burst
            pitches = [C5['C'], C5['D'], C5['E'], C5['G'], C5['A'],
                       C4['C'], C4['E'], C4['G']]
            freq = np.random.choice(pitches)
            vel = np.random.uniform(0.3, 0.5)  # clamped 30-50%
            dur_s = 0.08 + np.random.random() * 0.12

            s = int(t_s * SR)
            n = int(dur_s * SR)
            if s + n > N_SAMPLES:
                n = N_SAMPLES - s

            plonk = sine_wave(freq, max(n, 1), sr=SR)
            plonk = plonk * np.exp(-np.linspace(0, 15, max(n, 1)))
            plonk = plonk * vel

            # Pan randomly
            p = np.random.uniform(-0.6, 0.6)
            stereo[s:s+n, 0] += plonk * (1 - p) * 0.5
            stereo[s:s+n, 1] += plonk * (1 + p) * 0.5
            count += 1

    log.info(f"  {count} drops done: {time.time()-t0:.1f}s")
    return stereo


def build_ice_crystals():
    """Celesta/Music Box tones — high chimes, shimmer reverb."""
    log.info("Building ice crystals...")
    t0 = time.time()

    stereo = np.zeros((N_SAMPLES, 2), dtype=np.float32)
    np.random.seed(42)
    count = 0

    for t_s in np.arange(0, DURATION_S, 0.8):
        phase, prog = phase_at(t_s)
        prob = 0.0
        if phase == 'liquid':
            prob = 0.0
        elif phase == 'freezing':
            prob = 0.03 + 0.04 * prog
        elif phase == 'absolute_zero':
            prob = 0.035
        elif phase == 'void':
            fade_t = (t_s - PHASES['void'][0]) / 120.0
            prob = 0.035 * max(0, 1 - fade_t * 2)

        if prob > 0 and np.random.random() < prob:
            pitches = [C5['C']*2, C5['E']*2, C5['G']*2, C5['A']*2,
                       C5['E'],   C5['C'],   C4['C']]
            freq = np.random.choice(pitches)
            vel = np.random.uniform(0.3, 0.6)
            dur_s = np.random.uniform(0.5, 3.0)
            s = int(t_s * SR)
            n = int(dur_s * SR)
            if s + n > N_SAMPLES:
                n = N_SAMPLES - s

            # FM bell: carrier = freq * 1, modulator = freq * 2
            t_env = np.linspace(0, dur_s, max(n, 1))
            bell = np.sin(2 * np.pi * freq * t_env) * np.exp(-t_env * 2)
            # Add shimmer: higher partial
            bell += np.sin(2 * np.pi * freq * 4.1 * t_env) * np.exp(-t_env * 4) * 0.3
            bell = bell * vel
            # HP filter for sparkle
            bell = hpf(bell, 2000, sr=SR)

            # Wide pan
            p = np.random.uniform(-0.8, 0.8)
            stereo[s:s+n, 0] += bell * (1 - p) * 0.5
            stereo[s:s+n, 1] += bell * (1 + p) * 0.5
            count += 1

    # Shimmer reverb
    stereo = apply_reverb(stereo, sr=SR, room_size=0.85, damping=0.2)

    log.info(f"  {count} crystals done: {time.time()-t0:.1f}s")
    return stereo


def fast_limiter(audio, ceiling_db=-1.0):
    """Brickwall limiter using vectorized operations (no sample loop)."""
    ceiling = 10 ** (ceiling_db / 20)
    # RMS-based gain reduction
    rms = np.sqrt(np.mean(audio ** 2))
    target_rms = 10 ** (-20 / 20)  # -20 dB RMS
    if rms > 1e-10:
        audio = audio * (target_rms / rms)

    # Hard clip to ceiling
    np.clip(audio, -ceiling, ceiling, out=audio)
    return audio


def render():
    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║  CRYOGENESIS v2 — Pure Math Synth Meditative    ║")
    log.info("║  50 BPM · C Pentatonic (432 Hz) · 22:22         ║")
    log.info("╚══════════════════════════════════════════════════╝")
    total_t0 = time.time()

    # ── Build layers ──
    drone_mono = build_breathing_drone()
    pad_stereo = build_binaural_pad()
    water_stereo = build_water_drops()
    ice_stereo = build_ice_crystals()

    # ── Mix ──
    log.info("Mixing layers...")
    t0 = time.time()

    out = np.zeros((N_SAMPLES, 2), dtype=np.float32)
    # Drone → stereo
    for ch in range(2):
        out[:, ch] += drone_mono * 0.35
    # Pad
    out += pad_stereo * 0.30
    # Water drops
    out += water_stereo * 0.15
    # Ice crystals
    out += ice_stereo * 0.20

    # Phase-based volume automation
    log.info("Applying phase automation...")
    for i in range(0, N_SAMPLES, 1000):  # every 23ms
        t_s = i / SR
        phase, prog = phase_at(t_s)
        if phase == 'liquid':
            pass  # baseline
        elif phase == 'freezing':
            pass  # already handled per-layer
        elif phase == 'absolute_zero':
            pass
        elif phase == 'void':
            fade_t = max(0, (t_s - PHASES['void'][0]) / 120.0)
            out[i:i+1000] *= (1 - fade_t)

    # ── Master bus ──
    log.info("Compressor + limiter...")
    out = apply_compressor(out, sr=SR, threshold_db=-20, ratio=2.0,
                        attack_ms=50, release_ms=500)
    out = fast_limiter(out, ceiling_db=-1.0)

    peak = np.abs(out).max()
    rms = np.sqrt(np.mean(out ** 2))
    log.info(f"Render complete: peak={peak:.4f}, RMS={20*np.log10(rms+1e-10):.1f} dBFS")
    log.info(f"Total time: {time.time()-total_t0:.0f}s")

    # ── Save ──
    import soundfile as sf
    wav_path = "/opt/autodj-mixer/Cryogenesis.wav"
    sf.write(wav_path, out, SR, subtype='PCM_24')
    log.info(f"Saved: {wav_path}")

    import subprocess
    mp3_path = wav_path.replace(".wav", ".mp3")
    subprocess.run([
        "ffmpeg", "-y", "-i", wav_path,
        "-b:a", "320k", "-q:a", "0",
        "-write_id3v1", "1",
        "-metadata", "title=Cryogenesis",
        "-metadata", "artist=Xenolith",
        "-metadata", "genre=Ambient Drone",
        mp3_path
    ], capture_output=True)
    size_mb = os.path.getsize(mp3_path) / 1024 / 1024
    log.info(f"MP3: {mp3_path} ({size_mb:.1f} MB)")

    wav_size = os.path.getsize(wav_path) / 1024 / 1024
    print(f"\n✅ Cryogenesis v2 rendered!")
    print(f"   WAV: {wav_path} ({wav_size:.0f} MB)")
    print(f"   MP3: {mp3_path} ({size_mb:.1f} MB)")
    print(f"   Duration: {DURATION_S//60}:{DURATION_S%60:02d}")
    print(f"   Peak: {peak:.3f}  RMS: {20*np.log10(rms+1e-10):.1f} dBFS")

    return wav_path, mp3_path


if __name__ == "__main__":
    render()
