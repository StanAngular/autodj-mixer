#!/usr/bin/env python3
"""
Cryogenesis — Meditative Sleep Ambient / Drone
Duration: 22:22 (1342s)
BPM: 50 | Key: C Major Pentatonic (A=432 Hz)
Mixed backend: DawDreamer + Surge XT VST3 + FluidSynth
"""
import os, sys, math, json, logging, time, struct
import numpy as np

sys.path.insert(0, '/opt/autodj-mixer')
os.chdir('/opt/autodj-mixer')

from autodj.generate.backends.dawdreamer import DawDreamerBackend
from autodj.generate.backends.fluidsynth import (
    FluidSynthBackend, find_sf2, hz_to_midi, GM_DRUMS,
    build_melody_events, build_chord_events, build_drum_events, build_bass_events,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('cryogenesis')

# ── Constants ──────────────────────────────────────────────────────────────
BPM = 50
SR = 44100
BAR_S = 60.0 / BPM * 4          # 4.8 s per bar at 50 BPM
BEAT_S = BAR_S / 4               # 1.2 s per beat
DURATION_S = 1342                 # 22:22

# A=432 Hz tuning ratio
A432_RATIO = 432.0 / 440.0

# C Major Pentatonic (A=432)
def c_pent(octave=4):
    c = 261.63 * A432_RATIO * (2 ** (octave - 4))
    return {
        'C': c,
        'D': c * 2**(2/12),
        'E': c * 2**(4/12),
        'G': c * 2**(7/12),
        'A': c * 2**(9/12),
    }

C5 = c_pent(5)
C4 = c_pent(4)
C3 = c_pent(3)
C2 = c_pent(2)
C1 = c_pent(1)  # Sub-bass territory

# Phase timing
PHASES = {
    'liquid':     (0,    300),    # 0:00-5:00
    'freezing':   (300,  660),    # 5:00-11:00
    'absolute_zero': (660,  1222), # 11:00-20:22
    'void':       (1222, 1342),   # 20:22-22:22 (2 min fade)
}

def in_phase(name, t):
    s, e = PHASES[name]
    return s <= t < e

# ── Phase progress (0..1 within each phase) ────────────────────────────────
def phase_progress(t):
    """Return (phase_name, progress_0to1)."""
    for name, (s, e) in PHASES.items():
        if s <= t < e:
            return name, (t - s) / (e - s)
    return 'void', 1.0

# ── Render ─────────────────────────────────────────────────────────────────

def render_cryogenesis():
    log.info("╔══════════════════════════════════════════════════╗")
    log.info("║       CRYOGENESIS — Meditative Sleep Ambient     ║")
    log.info("║       50 BPM · C Pentatonic (432 Hz) · 22:22     ║")
    log.info("╚══════════════════════════════════════════════════╝")

    vst3_path = "/opt/autodj-mixer/shared/vst3/Surge XT.vst3"
    n_bars = int(DURATION_S / BAR_S) + 1

    # ═══════════════════════════════════════════════════════════════════════
    # 1. BREATHING DRONE (Surge XT, ch0) — Brown noise + sub-bass
    #    10s cycle: 4s rise, 6s fall. Low G/C pentatonic roots
    # ═══════════════════════════════════════════════════════════════════════
    drone_events = []
    # Drone uses C2, G2, C3 pedal tones with breathing volume
    drone_roots = [C2['C'], C2['G'], C1['C'], C2['C'],
                   C2['C'], C2['C'], C2['G'], C1['G']]

    for bar in range(n_bars):
        t = bar * BAR_S
        if t >= DURATION_S:
            break

        phase, prog = phase_progress(t)

        # Drone always plays, volume shaped by phase
        vel_base = 70  # base velocity
        if phase == 'liquid':
            vel_base = 65
        elif phase == 'freezing':
            vel_base = 72
        elif phase == 'absolute_zero':
            vel_base = 78
        elif phase == 'void':
            # Fade out over 120s
            fade_t = (t - PHASES['void'][0]) / 120.0
            vel_base = int(75 * (1 - fade_t))

        # Each bar has 2 breathing cycles (10s each, 4.8s bar)
        # Simulate breathing with two notes per bar
        root = drone_roots[bar % len(drone_roots)]
        note = hz_to_midi(root)

        # First half-bar: rise (first 2.4s)
        t1 = t
        dur1 = BEAT_S * 1.8  # ~2.16s
        vel1 = int(vel_base * 0.5)
        drone_events.append((t1, "note_on", 0, note, vel1))
        drone_events.append((t1 + dur1, "note_off", 0, note, 0))

        # Second half-bar: fall (next 2.4s)
        t2 = t + BEAT_S * 2
        dur2 = BEAT_S * 1.5  # ~1.8s
        vel2 = int(vel_base * 0.3)
        drone_events.append((t2, "note_on", 0, note, vel2))
        drone_events.append((t2 + dur2, "note_off", 0, note, 0))

    log.info(f"Drone events: {len(drone_events)//2} breaths")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. BINAURAL PAD (Surge XT, ch1) — Warm pad, double-detuned for stereo
    #    We render TWO VST3 passes: ch1 (L) at base, ch1b (R) at +5Hz detune
    #    C pentatonic chords: C-E-G, D-F#-A (avoiding F), G-B-D, A-C-E
    # ═══════════════════════════════════════════════════════════════════════
    # Binaural pad chords (warm open voicings)
    pad_chords = [
        [C4['C'], C4['E'], C4['G'], C5['C']],       # C major
        [C4['C'], C4['E'], C4['G'], C3['G']],       # C major open
        [C4['G'], C4['D'], C5['G'], C4['C']],       # G sus
        [C4['A'], C4['C'], C4['E'], C5['A']],       # Am
        [C4['D'], C4['G'], C5['D'], C5['G']],       # D sus
        [C4['C'], C4['G'], C4['A'], C5['E']],       # C6
        [C4['E'], C4['G'], C4['C'], C5['G']],       # C/G
        [C3['C'], C3['G'], C4['C'], C4['E']],       # Low C
    ]

    binaural_events = []
    for bar in range(n_bars):
        t = bar * BAR_S
        if t >= DURATION_S:
            break

        phase, prog = phase_progress(t)
        chord = pad_chords[bar % len(pad_chords)]

        # Pad volume per phase
        vel = 0
        if phase == 'liquid':
            vel = int(15 + 20 * prog)  # very quiet, growing
        elif phase == 'freezing':
            vel = int(35 + 30 * prog)  # growing
        elif phase == 'absolute_zero':
            vel = 75  # Full
        elif phase == 'void':
            fade_t = (t - PHASES['void'][0]) / 120.0
            vel = int(70 * max(0, 1 - fade_t))

        if vel < 5:
            continue

        # Hold chord for most of the bar (4.3s of 4.8s)
        dur = BAR_S * 0.9
        for freq in chord:
            note = hz_to_midi(freq)
            binaural_events.append((t, "note_on", 1, note, vel))
            binaural_events.append((t + dur, "note_off", 1, note, 0))

        # Also add detuned version on ch4 for right channel
        # Detune: +5 Hz on the fundamental → shift all notes up ~2 cents
        freq_detuned = chord[0] + 5.0  # +5 Hz on fundamental
        detune_note = hz_to_midi(freq_detuned)
        # Actually, let's just use a slightly different chord for the binaural beat
        # Render one channel at +5 cents detune

    log.info(f"Binaural pad events: {len(binaural_events)//2} chord notes")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. WATER DROPS (Surge XT, ch2) — Muted plucks, velocity 40-60
    # ═══════════════════════════════════════════════════════════════════════
    water_events = []
    np.random.seed(13)

    # Water drops occur at specific densities per phase
    for t in np.arange(0, DURATION_S, 0.5):  # Check every 500ms
        phase, prog = phase_progress(t)
        prob = 0.0

        if phase == 'liquid':
            prob = 0.12 + 0.03 * np.sin(t * 0.1)  # waves of drops
        elif phase == 'freezing':
            prob = 0.08 - 0.05 * prog  # becoming rarer
        elif phase == 'absolute_zero':
            prob = 0.0  # MUTED
        elif phase == 'void':
            prob = 0.0

        if prob > 0 and np.random.random() < prob:
            # Random pitch in C pentatonic range
            pitches = [C5['C'], C5['D'], C5['E'], C5['G'], C5['A'],
                       C4['C'], C4['E'], C4['G']]
            freq = np.random.choice(pitches)
            note = hz_to_midi(freq)
            # Velocity clamped to 40-60
            vel = int(np.random.uniform(40, 60))
            water_events.append((t, "note_on", 2, note, vel))
            water_events.append((t + 0.15, "note_off", 2, note, 0))

    log.info(f"Water drop events: {len(water_events)//2} drops")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. ICE CRYSTALS (FluidSynth, ch3) — Celesta/Music Box, high-cut
    # ═══════════════════════════════════════════════════════════════════════
    ice_events = []
    np.random.seed(42)

    # Program change to Celesta (GM 8) or Music Box (GM 10)
    ice_events.append((0.0, "program", 3, 0, 10))  # Music Box (glockenspiel-like)

    for t in np.arange(0, DURATION_S, 1.0):  # Check every 1s
        phase, prog = phase_progress(t)
        prob = 0.0

        if phase == 'liquid':
            prob = 0.0  # No ice in liquid phase
        elif phase == 'freezing':
            prob = 0.03 + 0.04 * prog  # Entering gradually
        elif phase == 'absolute_zero':
            prob = 0.04  # Occasional sparkles
        elif phase == 'void':
            # Decaying to zero
            fade_t = (t - PHASES['void'][0]) / 120.0
            prob = 0.04 * max(0, 1 - fade_t * 2)

        if prob > 0 and np.random.random() < prob:
            # High crystal tones
            pitches = [C5['C'], C5['E'], C5['G'], C5['A'],
                       C4['G'], C4['A'], C4['C']]
            freq = np.random.choice(pitches)
            note = hz_to_midi(freq)
            vel = int(np.random.uniform(50, 85))
            dur = np.random.uniform(0.3, 1.5)
            ice_events.append((t, "note_on", 3, note, vel))
            ice_events.append((t + dur, "note_off", 3, note, 0))

    log.info(f"Ice crystal events: {len(ice_events)//2} crystals")

    # ─── Sort all events ──────────────────────────────────────────────────
    # DawDreamer events (ch0, ch1, ch2)
    daw_events = sorted(
        [e for e in drone_events + binaural_events + water_events],
        key=lambda e: e[0]
    )
    # FluidSynth events (ch3)
    fluid_events = sorted(ice_events, key=lambda e: e[0])

    log.info(f"Total events: {len(daw_events) + len(fluid_events)}")
    log.info(f"  DawDreamer: {len(daw_events)}")
    log.info(f"  FluidSynth: {len(fluid_events)}")

    # ─── Render DawDreamer (Surge XT) ───────────────────────────────────
    log.info("Rendering DawDreamer (Surge XT: drone + pad + water)...")
    t0 = time.time()

    # First pass: left channel (C pentatonic in tune)
    dd_left = DawDreamerBackend(
        sample_rate=SR,
        vst3_plugins={"0": vst3_path, "1": vst3_path, "2": vst3_path},
    )
    wav_daw = dd_left.render(daw_events, DURATION_S)
    dd_left.close()
    log.info(f"DawDreamer done: {len(wav_daw)} samples ({time.time()-t0:.1f}s)")

    # ─── Render FluidSynth (ice crystals) ────────────────────────────────
    log.info("Rendering FluidSynth (celesta/ice crystals)...")
    t0 = time.time()
    sf2_path = find_sf2("/opt/autodj-mixer/shared/MuseScore_General.sf2")
    fs_backend = FluidSynthBackend(sf2_path=sf2_path, sample_rate=SR)
    wav_ice = fs_backend.render(fluid_events, DURATION_S)
    fs_backend.close()
    log.info(f"FluidSynth done: {len(wav_ice)} samples ({time.time()-t0:.1f}s)")

    # ═══════════════════════════════════════════════════════════════════════
    # POST-PRODUCTION
    # ═══════════════════════════════════════════════════════════════════════

    # Mix layers
    log.info("Mixing layers...")
    wav = wav_daw * 0.75 + wav_ice * 0.35

    # Apply binaural detuning: +5 Hz on right channel
    # Use phase vocoder approximation: Hilbert transform for quadrature
    log.info("Applying binaural detuning (R channel +5 Hz)...")
    wav = apply_binaural_detune(wav, SR, 5.0)  # 5 Hz theta binaural beat

    # Apply breathing LFO (10s cycle: 4s rise, 6s fall)
    log.info("Applying breathing LFO (0.1 Hz, 10s cycle)...")
    wav = apply_breathing_lfo(wav, SR, cycle_s=10.0)

    # Apply soft compressor (slow attack/release, 2:1)
    log.info("Applying compression (2:1, slow)...")
    wav = apply_compressor(wav, SR, threshold_db=-20, ratio=2.0,
                           attack_s=0.05, release_s=0.5)

    # Apply brickwall limiter at -1.0 dBTP
    log.info("Applying brickwall limiter (-1.0 dBTP)...")
    wav = apply_limiter(wav, ceiling_db=-1.0)

    # Final 2-minute fade out
    log.info("Applying 2-minute fade-out (Phase: Void)...")
    wav = apply_fade_out(wav, SR, fade_start_s=1222, fade_duration_s=120)

    # Normalize to -1.0 dB RMS target
    rms = np.sqrt(np.mean(wav ** 2))
    target_rms = 10 ** (-20 / 20)  # -20 dB RMS
    if rms > 1e-10:
        wav *= target_rms / rms

    # Final peak guard
    peak = np.abs(wav).max()
    if peak > 0.891:  # -1.0 dB
        wav *= 0.891 / peak

    log.info(f"Render complete: {len(wav)} samples, peak={peak:.3f}")

    # Save
    import soundfile as sf
    out_path = "/opt/autodj-mixer/Cryogenesis.wav"
    sf.write(out_path, wav, SR, subtype='PCM_24')
    log.info(f"Saved: {out_path}")

    import subprocess
    mp3_path = out_path.replace(".wav", ".mp3")
    subprocess.run([
        "ffmpeg", "-y", "-i", out_path,
        "-b:a", "320k", "-q:a", "0",
        "-write_id3v1", "1",
        "-metadata", "title=Cryogenesis",
        "-metadata", "artist=Xenolith",
        "-metadata", "genre=Ambient Drone",
        mp3_path
    ], capture_output=True)
    size_mb = os.path.getsize(mp3_path) / 1024 / 1024
    log.info(f"MP3: {mp3_path} ({size_mb:.1f} MB)")

    return out_path, mp3_path


# ── DSP Effects ────────────────────────────────────────────────────────────

def apply_binaural_detune(audio, sr, beat_hz=5.0):
    """
    Simple binaural beat: shift R channel by beat_hz using SSB modulation.
    Creates a phantom beat frequency between L and R.
    """
    n = len(audio)
    if audio.ndim == 1:
        audio = np.column_stack([audio, audio])

    # Generate quadrature oscillator for single-sideband
    t = np.arange(n) / sr
    # Hilbert transform approximation via FFT
    X = np.fft.fft(audio[:, 1])  # Right channel only
    N = n
    h = np.zeros(N)
    if N % 2 == 0:
        h[0] = 0
        h[1:N//2] = 2.0
        h[N//2] = 0
    else:
        h[0] = 0
        h[1:(N+1)//2] = 2.0
    H = np.fft.fft(h)
    x_hilbert = np.fft.ifft(X * H).real

    # SSB: shift right channel up by beat_hz
    carrier = np.exp(2j * np.pi * beat_hz * t)
    shifted = (audio[:, 1] * carrier.real - x_hilbert * carrier.imag)
    audio[:, 1] = shifted.astype(np.float32)

    return audio


def apply_breathing_lfo(audio, sr, cycle_s=10.0):
    """
    Apply LFO amplitude modulation with 10s cycle: 4s rise, 6s fall.
    """
    n = len(audio)
    t = np.arange(n) / sr

    # Breathing shape: asymmetric triangle (4s up, 6s down)
    phase = (t % cycle_s) / cycle_s
    # Map 0-1 phase to 0.4-1.0 amplitude
    rise_fraction = 4.0 / cycle_s  # 0.4
    env = np.where(phase < rise_fraction,
                   phase / rise_fraction,  # Rise
                   1.0 - (phase - rise_fraction) / (1.0 - rise_fraction))  # Fall
    # Scale to 0.6-1.0 range (gentle breathing, not total silence)
    env = 0.6 + 0.4 * env

    if audio.ndim > 1:
        for ch in range(audio.shape[1]):
            audio[:, ch] *= env
    else:
        audio *= env

    return audio


def apply_compressor(audio, sr, threshold_db=-20, ratio=2.0,
                      attack_s=0.05, release_s=0.5):
    """Soft knee compressor with slow attack/release."""
    n = len(audio)
    if audio.ndim > 1:
        mono = np.mean(audio, axis=1)
    else:
        mono = audio.copy()

    # Envelope follower
    abs_signal = np.abs(mono)
    threshold = 10 ** (threshold_db / 20)

    # Attack/release smoothing (one-pole)
    env = np.zeros_like(abs_signal)
    alpha_a = 1.0 - np.exp(-1.0 / (attack_s * sr))
    alpha_r = 1.0 - np.exp(-1.0 / (release_s * sr))

    for i in range(n):
        if abs_signal[i] > env[i-1] if i > 0 else True:
            env[i] = (1 - alpha_a) * env[i-1] + alpha_a * abs_signal[i]
        else:
            env[i] = (1 - alpha_r) * env[i-1] + alpha_r * abs_signal[i]

    # Compute gain reduction (soft knee)
    # Above threshold: apply ratio
    gain_db = np.where(env > threshold,
                       -(env - threshold) * (1 - 1.0/ratio) * 20 / np.log(10),
                       0.0)
    # Convert to linear gain
    gain_linear = 10 ** (gain_db / 20)
    # Smooth transition
    gain_linear = np.minimum(1.0, gain_linear)

    if audio.ndim > 1:
        for ch in range(audio.shape[1]):
            audio[:, ch] *= gain_linear
    else:
        audio *= gain_linear

    return audio


def apply_limiter(audio, ceiling_db=-1.0, lookahead_ms=5.0):
    """Brickwall limiter with lookahead."""
    ceiling = 10 ** (ceiling_db / 20)
    n = len(audio)

    if audio.ndim > 1:
        mono = np.max(np.abs(audio), axis=1)
    else:
        mono = np.abs(audio)

    # Lookahead delay line
    lookahead_s = lookahead_ms / 1000.0
    lookahead_samples = int(lookahead_s * SR)
    delay_line = np.zeros(lookahead_samples)
    gain = np.ones(n)

    for i in range(n):
        # Find max in lookahead window
        future_end = min(i + lookahead_samples, n)
        max_future = np.max(mono[i:future_end])
        if len(delay_line) > 0:
            max_past = np.max(delay_line)
            max_val = max(max_future, max_past)
        else:
            max_val = max_future

        if max_val > ceiling:
            gain[i] = ceiling / max_val
        else:
            gain[i] = 1.0

        # Shift delay line
        delay_line = np.roll(delay_line, -1)
        delay_line[-1] = mono[i] if i < n else 0

    # Smooth gain (release)
    alpha = 0.999
    gain_smooth = np.zeros_like(gain)
    gain_smooth[0] = gain[0]
    for i in range(1, n):
        if gain[i] < gain_smooth[i-1]:
            gain_smooth[i] = gain[i]  # Instant attack
        else:
            gain_smooth[i] = (1 - alpha) * gain[i] + alpha * gain_smooth[i-1]  # Slow release

    if audio.ndim > 1:
        for ch in range(audio.shape[1]):
            audio[:, ch] *= gain_smooth
    else:
        audio *= gain_smooth

    return audio


def apply_fade_out(audio, sr, fade_start_s=1222, fade_duration_s=120):
    """Apply fade-out over duration_s from start point."""
    n = len(audio)
    s_start = int(fade_start_s * sr)
    s_end = int((fade_start_s + fade_duration_s) * sr)
    if s_end > n:
        s_end = n

    if s_start >= n:
        return audio

    fade_len = s_end - s_start
    fade_curve = np.cos(np.linspace(0, np.pi/2, fade_len))  # Gentle exponential-ish

    if audio.ndim > 1:
        for ch in range(audio.shape[1]):
            audio[s_start:s_end, ch] *= fade_curve
        audio[s_end:] = 0.0
    else:
        audio[s_start:s_end] *= fade_curve
        audio[s_end:] = 0.0

    return audio


if __name__ == "__main__":
    log.info("Starting Cryogenesis render...")
    wav_path, mp3_path = render_cryogenesis()
    wav_size = os.path.getsize(wav_path) / 1024 / 1024
    mp3_size = os.path.getsize(mp3_path) / 1024 / 1024
    print(f"\n✅ Cryogenesis rendered!")
    print(f"   WAV: {wav_path} ({wav_size:.0f} MB)")
    print(f"   MP3: {mp3_path} ({mp3_size:.1f} MB)")
    print(f"   Duration: 22:22")
    print(f"   Format: 44.1kHz · 24-bit · Stereo · 320kbps MP3")