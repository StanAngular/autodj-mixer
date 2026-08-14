"""
synthcore.py — Core synthesis: oscillators, envelopes, filters, effects

Provides:
  - Waveforms: sawtooth, square, sine, supersaw (detuned saws)
  - ADSR envelope
  - Resonant LPF / HPF
  - 303-style acid bass note
  - Pad synthesis (slow attack, filter sweep)
  - Pedalboard reverb/delay/chorus wrappers
  - Smooth section envelope (cosine crossfade)
  - Buffer mix helper
"""

import numpy as np
from scipy.signal import butter, sosfilt
from typing import List, Tuple

# Pedalboard for high-quality effects
try:
    import pedalboard as pb
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

SR_DEFAULT = 44100


# ---------------------------------------------------------------------------
# MIDI helpers
# ---------------------------------------------------------------------------
def midi_to_hz(note: int) -> float:
    return 440.0 * (2 ** ((note - 69) / 12))


# ---------------------------------------------------------------------------
# Bandlimited oscillators
# ---------------------------------------------------------------------------
def _wavetable_osc(freq_hz: float, n_samples: int, sr: int,
                   wave_type: str = "saw", phase_offset: float = 0.0) -> np.ndarray:
    """
    Fast wavetable oscillator. Generates phase array then looks up shape.
    Orders of magnitude faster than additive synthesis for long buffers.
    """
    # Phase accumulation
    phase_inc = freq_hz / sr
    phase = (np.arange(n_samples, dtype=np.float64) * phase_inc + phase_offset) % 1.0

    if wave_type == "saw":
        # Sawtooth: phase 0→1 maps to -1→+1
        wave = (phase * 2 - 1).astype(np.float32)
    elif wave_type == "square":
        wave = np.where(phase < 0.5, 1.0, -1.0).astype(np.float32)
    elif wave_type == "tri":
        wave = (2 * np.abs(2 * phase - 1) - 1).astype(np.float32)
    elif wave_type == "sine":
        wave = np.sin(2 * np.pi * phase).astype(np.float32)
    else:
        wave = (phase * 2 - 1).astype(np.float32)

    return wave


def sawtooth_bl(freq_hz: float, n_samples: int, sr: int = SR_DEFAULT,
                n_harmonics: int = 0) -> np.ndarray:
    """Sawtooth via wavetable (fast). n_harmonics ignored for speed."""
    return _wavetable_osc(freq_hz, n_samples, sr, "saw")


def square_bl(freq_hz: float, n_samples: int, sr: int = SR_DEFAULT,
              n_harmonics: int = 0) -> np.ndarray:
    """Square via wavetable (fast). n_harmonics ignored for speed."""
    out = _wavetable_osc(freq_hz, n_samples, sr, "square")
    # Light LPF to reduce aliasing
    cutoff = min(freq_hz * 8, sr // 2 - 100)
    return lpf(out, cutoff, sr=sr)


def sine_wave(freq_hz: float, n_samples: int, sr: int = SR_DEFAULT,
              phase_offset: float = 0.0) -> np.ndarray:
    return _wavetable_osc(freq_hz, n_samples, sr, "sine", phase_offset)


def supersaw(freq_hz: float, n_samples: int, sr: int = SR_DEFAULT,
             detune_cents: float = 12.0, n_voices: int = 7) -> np.ndarray:
    """
    Supersaw: N detuned sawtooth voices, wavetable-based (fast).
    """
    offsets_cents = np.linspace(-detune_cents, detune_cents, n_voices)
    out = np.zeros(n_samples, dtype=np.float32)
    for i, dc in enumerate(offsets_cents):
        f = freq_hz * (2 ** (dc / 1200))
        phase_off = i / n_voices  # stagger phases
        out += _wavetable_osc(f, n_samples, sr, "saw", phase_off)
    out /= n_voices
    # Light LPF to tame top-end aliasing
    cutoff = min(freq_hz * 15, 12000, sr // 2 - 100)
    return lpf(out, cutoff, sr=sr)


# ---------------------------------------------------------------------------
# ADSR
# ---------------------------------------------------------------------------
def adsr(attack_ms: float, decay_ms: float, sustain_db: float,
         release_ms: float, dur_s: float, sr: int = SR_DEFAULT) -> np.ndarray:
    """Returns an amplitude envelope array of length int(dur_s * sr)."""
    n = int(dur_s * sr)
    env = np.zeros(n, dtype=np.float32)

    a = int(attack_ms / 1000 * sr)
    d = int(decay_ms / 1000 * sr)
    r = int(release_ms / 1000 * sr)
    sustain = 10 ** (sustain_db / 20)

    # Attack: linear ramp
    a = min(a, n)
    env[:a] = np.linspace(0, 1, a)

    # Decay: exponential drop to sustain
    d_end = min(a + d, n)
    if d_end > a:
        env[a:d_end] = np.linspace(1, sustain, d_end - a)

    # Sustain
    s_end = max(a + d, n - r)
    s_end = min(s_end, n)
    if s_end > d_end:
        env[d_end:s_end] = sustain

    # Release
    if n > s_end:
        env[s_end:n] = np.linspace(sustain, 0, n - s_end)

    return env


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def lpf(x: np.ndarray, cutoff_hz: float, q: float = 0.707,
        sr: int = SR_DEFAULT) -> np.ndarray:
    """Resonant low-pass filter."""
    cutoff_hz = min(cutoff_hz, sr / 2 - 100)
    cutoff_hz = max(cutoff_hz, 10)
    sos = butter(2, cutoff_hz, btype='lowpass', fs=sr, output='sos')
    return sosfilt(sos, x).astype(np.float32)


def hpf(x: np.ndarray, cutoff_hz: float, sr: int = SR_DEFAULT) -> np.ndarray:
    """High-pass filter."""
    cutoff_hz = min(cutoff_hz, sr / 2 - 100)
    cutoff_hz = max(cutoff_hz, 10)
    sos = butter(2, cutoff_hz, btype='highpass', fs=sr, output='sos')
    return sosfilt(sos, x).astype(np.float32)


def lpf_sweep(x: np.ndarray, start_hz: float, end_hz: float,
              sr: int = SR_DEFAULT, segments: int = 32) -> np.ndarray:
    """
    Time-varying low-pass filter: sweeps cutoff from start_hz to end_hz.
    Splits into segments, applies static LPF to each.
    """
    n = len(x)
    out = np.zeros(n, dtype=np.float32)
    seg_len = n // segments

    for i in range(segments):
        t_norm = i / segments
        # Exponential sweep sounds more natural
        cutoff = start_hz * (end_hz / start_hz) ** t_norm
        start = i * seg_len
        end = start + seg_len if i < segments - 1 else n
        seg = x[start:end]
        out[start:end] = lpf(seg, cutoff, sr=sr)

    return out


# ---------------------------------------------------------------------------
# 303-style acid bass note
# ---------------------------------------------------------------------------
def acid_bass_note(midi_note: int, dur_s: float, sr: int = SR_DEFAULT,
                   cutoff_start: float = 800, cutoff_end: float = 200,
                   resonance_q: float = 4.0, accent: bool = False,
                   slide: bool = False) -> np.ndarray:
    """
    TB-303 style note:
    - Sawtooth oscillator
    - Exponential filter envelope sweep (cutoff_start → cutoff_end)
    - Fast attack ADSR
    - Slight overdrive

    Returns float32 mono array.
    """
    n = int(dur_s * sr)
    freq = midi_to_hz(midi_note)

    # Oscillator
    osc = sawtooth_bl(freq, n, sr)

    # Accent: louder, sharper filter sweep
    if accent:
        cutoff_start *= 2.5
        volume_boost = 1.3
    else:
        volume_boost = 1.0

    # Filter envelope: exponential decay
    t = np.arange(n, dtype=np.float64) / sr
    sweep_time = min(dur_s * 0.8, 0.3)
    tau = sweep_time / 4
    cutoff_env = cutoff_end + (cutoff_start - cutoff_end) * np.exp(-t / tau)

    # Apply time-varying filter in segments
    segments = max(8, int(dur_s * 20))
    filtered = np.zeros(n, dtype=np.float32)
    seg_len = n // segments
    for i in range(segments):
        start = i * seg_len
        end = start + seg_len if i < segments - 1 else n
        cutoff = float(cutoff_env[start])
        cutoff = min(cutoff, sr / 2 - 100)
        cutoff = max(cutoff, 20)
        sos = butter(2, cutoff, btype='lowpass', fs=sr, output='sos')
        seg_raw = osc[start:end]
        filtered[start:end] = sosfilt(sos, seg_raw).astype(np.float32)

    # Amplitude envelope: fast attack, slight decay, sustain
    env = adsr(attack_ms=2, decay_ms=50, sustain_db=-3,
               release_ms=30, dur_s=dur_s, sr=sr)
    out = filtered * env * volume_boost

    # Soft overdrive
    out = np.tanh(out * 1.8) / 1.8

    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# Supersaw pad note
# ---------------------------------------------------------------------------
def pad_note(midi_note: int, dur_s: float, sr: int = SR_DEFAULT,
             attack_ms: float = 800, cutoff_hz: float = 2000,
             detune_cents: float = 15.0, n_voices: int = 7) -> np.ndarray:
    """
    Supersaw pad: slow attack, resonant LPF, wide detune.
    Returns float32 mono.
    """
    n = int(dur_s * sr)
    freq = midi_to_hz(midi_note)

    osc = supersaw(freq, n, sr, detune_cents=detune_cents, n_voices=n_voices)

    # Filter
    osc = lpf(osc, cutoff_hz, q=0.5, sr=sr)

    # Slow attack envelope
    env = adsr(attack_ms=attack_ms, decay_ms=200, sustain_db=-2,
               release_ms=600, dur_s=dur_s, sr=sr)
    return (osc * env).astype(np.float32)


# ---------------------------------------------------------------------------
# Chord rendering (multiple notes summed)
# ---------------------------------------------------------------------------
def render_chord(midi_notes: List[int], dur_s: float, sr: int = SR_DEFAULT,
                 osc_fn=None, **kwargs) -> np.ndarray:
    """Render multiple notes and sum."""
    if osc_fn is None:
        osc_fn = pad_note
    n = int(dur_s * sr)
    out = np.zeros(n, dtype=np.float32)
    for note in midi_notes:
        voice = osc_fn(note, dur_s, sr, **kwargs)
        out[:len(voice)] += voice[:n]
    return out / max(1, len(midi_notes) ** 0.6)


# ---------------------------------------------------------------------------
# Pedalboard effects
# ---------------------------------------------------------------------------
def apply_reverb(x: np.ndarray, sr: int = SR_DEFAULT,
                 room_size: float = 0.6, wet: float = 0.3,
                 damping: float = 0.5) -> np.ndarray:
    """Apply reverb using pedalboard."""
    if not HAS_PEDALBOARD:
        return x
    board = pb.Pedalboard([
        pb.Reverb(room_size=room_size, wet_level=wet,
                  dry_level=1.0 - wet, damping=damping)
    ])
    stereo = x.ndim == 2
    if not stereo:
        x2 = np.stack([x, x], axis=1)
    else:
        x2 = x
    out = board(x2.T.astype(np.float32), sr).T
    if not stereo:
        return ((out[:, 0] + out[:, 1]) / 2).astype(np.float32)
    return out.astype(np.float32)


def apply_delay(x: np.ndarray, sr: int = SR_DEFAULT,
                delay_ms: float = 375, feedback: float = 0.35,
                wet: float = 0.25) -> np.ndarray:
    """Apply stereo delay."""
    if not HAS_PEDALBOARD:
        return x
    board = pb.Pedalboard([
        pb.Delay(delay_seconds=delay_ms / 1000, feedback=feedback, mix=wet)
    ])
    stereo = x.ndim == 2
    if not stereo:
        x2 = np.stack([x, x], axis=1)
    else:
        x2 = x
    out = board(x2.T.astype(np.float32), sr).T
    if not stereo:
        return ((out[:, 0] + out[:, 1]) / 2).astype(np.float32)
    return out.astype(np.float32)


def apply_chorus(x: np.ndarray, sr: int = SR_DEFAULT,
                 rate_hz: float = 0.5, depth: float = 0.25,
                 wet: float = 0.4) -> np.ndarray:
    """Apply chorus for stereo width."""
    if not HAS_PEDALBOARD:
        return x
    board = pb.Pedalboard([
        pb.Chorus(rate_hz=rate_hz, depth=depth, mix=wet)
    ])
    stereo = x.ndim == 2
    if not stereo:
        x2 = np.stack([x, x], axis=1)
    else:
        x2 = x
    out = board(x2.T.astype(np.float32), sr).T
    if not stereo:
        return ((out[:, 0] + out[:, 1]) / 2).astype(np.float32)
    return out.astype(np.float32)


def apply_compressor(x: np.ndarray, sr: int = SR_DEFAULT,
                     threshold_db: float = -12.0, ratio: float = 4.0,
                     attack_ms: float = 5.0, release_ms: float = 100.0) -> np.ndarray:
    """Apply compressor."""
    if not HAS_PEDALBOARD:
        return x
    board = pb.Pedalboard([
        pb.Compressor(threshold_db=threshold_db, ratio=ratio,
                      attack_ms=attack_ms, release_ms=release_ms)
    ])
    stereo = x.ndim == 2
    if not stereo:
        x2 = np.stack([x, x], axis=1)
    else:
        x2 = x
    out = board(x2.T.astype(np.float32), sr).T
    if not stereo:
        return ((out[:, 0] + out[:, 1]) / 2).astype(np.float32)
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# Smooth section envelope — cosine crossfade
# ---------------------------------------------------------------------------
def make_section_envelope(total_samples: int, sections: List[Tuple],
                          sr: int = SR_DEFAULT,
                          crossfade_bars: int = 4,
                          bpm: float = 133.0) -> np.ndarray:
    """
    Build a per-element gain envelope for smooth section transitions.

    sections: list of (start_s, end_s, peak_gain) tuples.
    Between sections, uses cosine crossfade over crossfade_bars bars.

    Returns float32 array of shape (total_samples,).
    """
    crossfade_s = crossfade_bars * 4 * 60 / bpm
    crossfade_n = int(crossfade_s * sr)

    env = np.zeros(total_samples, dtype=np.float32)

    for (start_s, end_s, peak_gain) in sections:
        s_start = int(start_s * sr)
        s_end   = min(int(end_s * sr), total_samples)

        # Full gain in body
        env[s_start:s_end] = peak_gain

        # Fade-in: cosine
        fi_end = min(s_start + crossfade_n, s_end)
        fi_n = fi_end - s_start
        if fi_n > 0:
            fi_curve = peak_gain * 0.5 * (1 - np.cos(np.pi * np.arange(fi_n) / fi_n))
            env[s_start:fi_end] = fi_curve

        # Fade-out: cosine
        fo_start = max(s_end - crossfade_n, s_start)
        fo_n = s_end - fo_start
        if fo_n > 0:
            fo_curve = peak_gain * 0.5 * (1 + np.cos(np.pi * np.arange(fo_n) / fo_n))
            env[fo_start:s_end] = fo_curve

    return env


# ---------------------------------------------------------------------------
# Buffer helpers
# ---------------------------------------------------------------------------
def mono_to_stereo(x: np.ndarray, pan: float = 0.0) -> np.ndarray:
    """
    Convert mono to stereo with panning.
    pan: -1.0 (full left) to 1.0 (full right), 0.0 = center.
    """
    l = np.sqrt(0.5 * (1 - pan)) * x
    r = np.sqrt(0.5 * (1 + pan)) * x
    return np.stack([l, r], axis=1).astype(np.float32)


def apply_envelope_stereo(buf: np.ndarray, env: np.ndarray) -> np.ndarray:
    """Apply mono envelope to stereo buffer."""
    n = min(len(buf), len(env))
    out = buf[:n].copy()
    out[:, 0] *= env[:n]
    out[:, 1] *= env[:n]
    return out


def mix_into(dest: np.ndarray, src: np.ndarray, gain: float = 1.0,
             offset: int = 0) -> None:
    """Add src into dest at offset with gain (in-place)."""
    n = min(len(src), len(dest) - offset)
    if n <= 0:
        return
    dest[offset:offset + n] += src[:n] * gain


def normalize_master(x: np.ndarray, target_db: float = -0.5) -> np.ndarray:
    """Normalize stereo buffer to target peak dB."""
    peak = np.abs(x).max()
    if peak < 1e-9:
        return x
    target = 10 ** (target_db / 20)
    return (x * (target / peak)).astype(np.float32)


def _eq_shelf(x: np.ndarray, sr: int, freq: float, gain_db: float, shelf: str = "high") -> np.ndarray:
    """
    Simple first-order high or low shelf EQ.
    shelf: "high" boosts/cuts above freq, "low" boosts/cuts below freq.
    gain_db: positive = boost, negative = cut.
    """
    from scipy.signal import bilinear
    A   = 10 ** (gain_db / 40.0)
    w0  = 2 * np.pi * freq / sr
    if shelf == "high":
        # High shelf: boost highs
        b_s = [A,  np.sqrt(A), 1]
        a_s = [1,  np.sqrt(A), A]
    else:
        # Low shelf: boost lows
        b_s = [A * A, A * np.sqrt(A), 1]
        a_s = [1,     np.sqrt(A),     A * A]
    # Bilinear transform
    b, a = bilinear([b_s[0] * w0**2, b_s[1] * w0, b_s[2]],
                    [a_s[0] * w0**2, a_s[1] * w0, a_s[2]], fs=sr)
    from scipy.signal import lfilter
    out = np.zeros_like(x)
    out[:, 0] = lfilter(b, a, x[:, 0])
    out[:, 1] = lfilter(b, a, x[:, 1])
    return out.astype(np.float32)


def master_chain(x: np.ndarray, sr: int = SR_DEFAULT,
                 air_db: float = 2.5, bass_db: float = 1.5) -> np.ndarray:
    """
    Master bus: soft clip → EQ (air + bass) → compressor → normalize.

    air_db:  high-shelf boost above 8kHz (adds sparkle, cosmic feel)
    bass_db: low-shelf boost below 120Hz (adds sub warmth)
    """
    # Soft saturation
    x = np.tanh(x * 1.05) / 1.05

    # Master EQ: gentle air and bass enhancement
    if air_db != 0:
        x = _eq_shelf(x, sr, freq=8000, gain_db=air_db, shelf="high")
    if bass_db != 0:
        x = _eq_shelf(x, sr, freq=120,  gain_db=bass_db, shelf="low")

    # Compressor
    x = apply_compressor(x, sr, threshold_db=-6, ratio=2.5,
                         attack_ms=8, release_ms=150)

    # Final normalize
    return normalize_master(x)
