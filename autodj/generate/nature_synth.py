"""
nature_synth.py — Synthesized nature sounds for ambient tracks

All generated from first principles (no samples needed):
  - rain():      pink noise shaped with "rain EQ" + random drop impacts
  - crickets():  narrow bandpass tones with chirp amplitude modulation
  - frogs():     low sine bursts (ribbits) at random intervals
  - wind_gust(): filtered noise with slow amplitude LFO

Each function returns float32 mono numpy arrays for a given duration.
Designed for chunk-based rendering (call per 30s chunk with time offset).
"""

import numpy as np
from scipy.signal import butter, sosfilt

SR_DEFAULT = 44100


def _butter_bp(lo, hi, sr, order=4):
    lo = max(lo, 20)
    hi = min(hi, sr // 2 - 100)
    if lo >= hi:
        lo = hi - 50
    return butter(order, [lo, hi], btype='bandpass', fs=sr, output='sos')


def _butter_lp(cutoff, sr, order=4):
    cutoff = min(cutoff, sr // 2 - 100)
    return butter(order, cutoff, btype='lowpass', fs=sr, output='sos')


# ---------------------------------------------------------------------------
# RAIN
# ---------------------------------------------------------------------------
def rain(n_samples: int, sr: int = SR_DEFAULT,
         intensity: float = 0.5, seed: int = None) -> np.ndarray:
    """
    Rain synthesis: pink-ish noise + random drop impacts.

    intensity: 0.0 (light drizzle) to 1.0 (heavy rain)
    """
    if seed is not None:
        rng = np.random.RandomState(seed)
    else:
        rng = np.random.RandomState()

    # Pink noise approximation: white noise -> 1/f shaping via LP cascade
    white = rng.randn(n_samples).astype(np.float32)

    # Shape to rain spectrum: emphasis 200-4000 Hz, gentle rolloff above
    sos1 = _butter_bp(150, 5000, sr)
    rain_base = sosfilt(sos1, white).astype(np.float32)

    # Additional high-frequency sparkle (rain hitting surfaces)
    sos2 = _butter_bp(3000, min(10000, sr // 2 - 100), sr)
    sparkle = sosfilt(sos2, rng.randn(n_samples).astype(np.float32))
    sparkle *= 0.15 * intensity

    # Random drop impacts: short bandpass bursts
    drops = np.zeros(n_samples, dtype=np.float32)
    n_drops = int(n_samples / sr * 8 * intensity)  # ~8 drops/sec at full intensity
    for _ in range(n_drops):
        pos = rng.randint(0, max(1, n_samples - 1000))
        drop_len = rng.randint(50, 300)
        end = min(pos + drop_len, n_samples)
        n = end - pos
        drop_noise = rng.randn(n).astype(np.float32)
        freq = rng.randint(800, 4000)
        sos_d = _butter_bp(freq - 200, freq + 200, sr, order=2)
        drop_filt = sosfilt(sos_d, drop_noise)
        env = np.exp(-np.arange(n, dtype=np.float32) / (0.005 * sr))
        drops[pos:end] += drop_filt * env * 0.3

    out = rain_base * (0.3 + 0.7 * intensity) + sparkle + drops
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# CRICKETS
# ---------------------------------------------------------------------------
def crickets(n_samples: int, sr: int = SR_DEFAULT,
             n_crickets: int = 5, density: float = 0.6,
             seed: int = None) -> np.ndarray:
    """
    Cricket chorus: multiple crickets with individual chirp patterns.

    Each cricket:
    - Narrow band tone at 3500-5500 Hz (species variation)
    - Chirp = amplitude modulation at 20-40 Hz (wing stridulation)
    - Chirp bursts: 80-200ms on, 200-800ms off
    - Each cricket has its own timing
    """
    if seed is not None:
        rng = np.random.RandomState(seed)
    else:
        rng = np.random.RandomState()

    out = np.zeros(n_samples, dtype=np.float32)

    for i in range(n_crickets):
        # This cricket's frequency and chirp rate
        base_freq = rng.uniform(3800, 5200)
        chirp_rate = rng.uniform(25, 40)  # Hz, wing speed
        chirp_on_ms = rng.uniform(80, 180)
        chirp_off_ms = rng.uniform(200, 700)
        volume = rng.uniform(0.3, 1.0) * density

        # Generate tone
        t = np.arange(n_samples, dtype=np.float64) / sr
        tone = np.sin(2 * np.pi * base_freq * t)
        # Add slight harmonic
        tone += 0.3 * np.sin(2 * np.pi * base_freq * 2 * t)
        tone *= 0.5

        # Chirp amplitude modulation
        am = 0.5 + 0.5 * np.sin(2 * np.pi * chirp_rate * t)

        # On/off gating pattern
        chirp_on_s = chirp_on_ms / 1000
        chirp_off_s = chirp_off_ms / 1000
        cycle_s = chirp_on_s + chirp_off_s
        cycle_n = int(cycle_s * sr)

        gate = np.zeros(n_samples, dtype=np.float32)
        pos = int(rng.uniform(0, cycle_n))  # random start offset

        while pos < n_samples:
            on_end = min(pos + int(chirp_on_s * sr), n_samples)
            n_on = on_end - pos
            if n_on > 0:
                # Smooth envelope for chirp burst
                env = np.ones(n_on, dtype=np.float32)
                fade = min(int(0.01 * sr), n_on // 4)
                if fade > 0:
                    env[:fade] = np.linspace(0, 1, fade)
                    env[-fade:] = np.linspace(1, 0, fade)
                gate[pos:on_end] = env

            # Slight random variation in timing
            jitter = rng.uniform(0.8, 1.2)
            pos += int(cycle_n * jitter)

        cricket = (tone * am * gate * volume).astype(np.float32)

        # Bandpass to clean up
        sos = _butter_bp(base_freq - 300, base_freq + 600, sr)
        cricket = sosfilt(sos, cricket).astype(np.float32)

        out += cricket

    return out


# ---------------------------------------------------------------------------
# FROGS
# ---------------------------------------------------------------------------
def frogs(n_samples: int, sr: int = SR_DEFAULT,
          n_frogs: int = 3, density: float = 0.5,
          seed: int = None) -> np.ndarray:
    """
    Frog chorus: individual frogs with "ribbit" patterns.

    Each ribbit = 2-3 rapid tone pulses (40-60ms each, 25ms gap)
    Tone frequency: 200-700 Hz (species variation)
    Inter-ribbit interval: 2-8 seconds (random)
    """
    if seed is not None:
        rng = np.random.RandomState(seed)
    else:
        rng = np.random.RandomState()

    out = np.zeros(n_samples, dtype=np.float32)

    for i in range(n_frogs):
        frog_freq = rng.uniform(250, 650)
        frog_freq2 = frog_freq * rng.uniform(1.1, 1.4)  # slight glide up
        n_pulses = rng.randint(2, 4)
        pulse_ms = rng.uniform(40, 70)
        gap_ms = rng.uniform(20, 40)
        volume = rng.uniform(0.4, 1.0) * density

        pulse_n = int(pulse_ms / 1000 * sr)
        gap_n = int(gap_ms / 1000 * sr)
        ribbit_n = n_pulses * (pulse_n + gap_n)

        # Build one ribbit waveform
        ribbit = np.zeros(ribbit_n, dtype=np.float32)
        for p in range(n_pulses):
            start = p * (pulse_n + gap_n)
            end = start + pulse_n
            if end > ribbit_n:
                break
            t_pulse = np.arange(pulse_n, dtype=np.float64) / sr
            # Frequency glides slightly within each pulse
            f = frog_freq + (frog_freq2 - frog_freq) * (p / n_pulses)
            tone = np.sin(2 * np.pi * f * t_pulse)
            # Pulse envelope
            env = np.ones(pulse_n, dtype=np.float32)
            fade = min(int(0.008 * sr), pulse_n // 4)
            if fade > 0:
                env[:fade] = np.linspace(0, 1, fade)
                env[-fade:] = np.linspace(1, 0, fade)
            ribbit[start:end] = tone * env

        # Place ribbits at random intervals
        interval_range = (2.0 / density, 8.0 / density)
        pos = int(rng.uniform(0, 3) * sr)  # random start
        while pos + ribbit_n < n_samples:
            out[pos:pos + ribbit_n] += ribbit * volume
            interval = rng.uniform(*interval_range)
            pos += int(interval * sr)

    # Low-pass to keep it natural
    sos = _butter_lp(min(800, sr // 2 - 100), sr)
    out = sosfilt(sos, out).astype(np.float32)

    return out


# ---------------------------------------------------------------------------
# WIND GUST
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# SAND ON GLASS
# ---------------------------------------------------------------------------
def sand_on_glass(n_samples: int, sr: int = SR_DEFAULT,
                  density: float = 0.5, pan_speed: float = 1.0,
                  seed: int = None) -> tuple:
    """
    Sand pouring / spilling on glass — vectorized, fast.

    Strategy:
    - Filter ONCE with two bandpass filters (3 kHz grain, 7 kHz sparkle)
    - Create random amplitude modulation mask (grain ON/OFF pattern)
    - Multiply filtered noise × grain_mask → grainy texture
    - Stereo: two independent filtered noise channels + slow LFO pan

    Returns (left, right) float32 mono arrays.
    """
    if seed is not None:
        rng = np.random.RandomState(seed)
    else:
        rng = np.random.RandomState()

    t_arr = np.arange(n_samples, dtype=np.float64) / sr

    # --- Two noise channels (for stereo independence) ---
    noise_l = rng.randn(n_samples).astype(np.float32)
    noise_r = rng.randn(n_samples).astype(np.float32)

    # Grain band: 2500-7000 Hz
    sos_grain = _butter_bp(2500, min(7000, sr // 2 - 100), sr)
    grain_l = sosfilt(sos_grain, noise_l).astype(np.float32)
    grain_r = sosfilt(sos_grain, noise_r).astype(np.float32)

    # Sparkle band: 7000-14000 Hz (very quiet)
    sos_sparkle = _butter_bp(7000, min(14000, sr // 2 - 100), sr)
    sparkle_l = sosfilt(sos_sparkle, noise_l).astype(np.float32) * 0.3
    sparkle_r = sosfilt(sos_sparkle, noise_r).astype(np.float32) * 0.3

    # --- Grain amplitude mask (vectorized) ---
    # Grain rate: grains_per_sec grains per second
    # Each grain is ~1-3ms wide. We model as: random binary mask at grain rate.
    grains_per_sec = int(300 + 600 * density)
    grain_dur_samples = int(0.002 * sr)  # 2ms average grain

    # Build mask: start with zeros, turn on random grain_dur_samples blocks
    grain_env = np.zeros(n_samples, dtype=np.float32)
    n_events = int(grains_per_sec * n_samples / sr)
    positions = rng.randint(0, max(1, n_samples - grain_dur_samples), n_events)
    amplitudes = rng.uniform(0.3, 1.0, n_events).astype(np.float32)

    # Vectorized grain placement using numpy add.at
    for i, pos in enumerate(positions):
        end = min(pos + grain_dur_samples, n_samples)
        gl = end - pos
        if gl > 0:
            # Decaying grain shape
            env_g = np.exp(-np.arange(gl, dtype=np.float32) / max(1, gl * 0.5))
            grain_env[pos:end] = np.maximum(grain_env[pos:end], env_g * amplitudes[i])

    # --- Slow stereo panning LFO ---
    pan_lfo = np.sin(2 * np.pi * t_arr * pan_speed / 12.0).astype(np.float32)
    # Derive L/R gain from pan
    pan_l = np.sqrt(np.clip(0.5 * (1 - pan_lfo), 0, 1))
    pan_r = np.sqrt(np.clip(0.5 * (1 + pan_lfo), 0, 1))

    # --- Mix ---
    left  = (grain_l * grain_env + sparkle_l) * pan_l
    right = (grain_r * grain_env + sparkle_r) * pan_r

    # --- Glass resonance taps (few events, so loop is fine) ---
    n_taps = max(2, int(n_samples / sr * 2 * density))
    for _ in range(n_taps):
        pos = rng.randint(0, max(1, n_samples - sr // 8))
        glass_hz = rng.uniform(800, 3500)
        tap_len = int(rng.uniform(0.03, 0.12) * sr)
        end = min(pos + tap_len, n_samples)
        t_tap = np.arange(end - pos, dtype=np.float64) / sr
        tone = (np.sin(2 * np.pi * glass_hz * t_tap) *
                np.exp(-t_tap / 0.035) *
                rng.uniform(0.006, 0.025)).astype(np.float32)
        pan = rng.uniform(-0.7, 0.7)
        left[pos:end]  += tone * np.sqrt(0.5 * (1 - pan))
        right[pos:end] += tone * np.sqrt(0.5 * (1 + pan))

    # Normalize
    peak = max(np.abs(left).max(), np.abs(right).max(), 1e-9)
    left  *= 0.15 / peak
    right *= 0.15 / peak

    return left.astype(np.float32), right.astype(np.float32)


def wind_gust(n_samples: int, sr: int = SR_DEFAULT,
              speed: float = 0.5, seed: int = None) -> np.ndarray:
    """
    Wind: filtered noise with slow amplitude undulation.
    speed: 0.0 (calm) to 1.0 (gusty)
    """
    if seed is not None:
        rng = np.random.RandomState(seed)
    else:
        rng = np.random.RandomState()

    noise = rng.randn(n_samples).astype(np.float32)

    # Wind spectrum: 50-2000 Hz
    sos = _butter_bp(50, 2000, sr)
    wind_raw = sosfilt(sos, noise).astype(np.float32)

    # Slow amplitude LFO (gusts)
    t = np.arange(n_samples, dtype=np.float64) / sr
    period = 5.0 + (1 - speed) * 15  # 5-20s period
    lfo = 0.3 + 0.7 * (0.5 + 0.5 * np.sin(2 * np.pi * t / period))

    # Add second slower LFO for organic feel
    lfo2 = 0.5 + 0.5 * np.sin(2 * np.pi * t / (period * 2.3) + 1.7)
    combined = (lfo * 0.7 + lfo2 * 0.3).astype(np.float32)

    return (wind_raw * combined * (0.3 + 0.7 * speed)).astype(np.float32)
