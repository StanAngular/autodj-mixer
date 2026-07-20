"""
synth909.py — Mathematical Roland TR-909 drum synthesis

All sounds synthesized from first principles (no samples needed):
- kick_909:      sine-frequency-sweep + exponential decay + saturation
- snare_909:     tone burst (200 Hz) + bandpass noise
- hihat_c_909:   high-pass noise short decay
- hihat_o_909:   high-pass noise longer decay
- clap_909:      layered noise bursts with reverb tail
- tom_909:       sine sweep, pitched
- rim_909:       short click + sine

All return float32 mono numpy arrays, normalized to -6 dBFS peak.
Call drum_hit(name, sr) for the samples; results are cached.
"""

import numpy as np
from functools import lru_cache
from scipy.signal import butter, sosfilt, sosfiltfilt

SR_DEFAULT = 44100


def _butter_hp(cutoff, sr, order=4):
    return butter(order, cutoff, btype='highpass', fs=sr, output='sos')


def _butter_lp(cutoff, sr, order=4):
    return butter(order, cutoff, btype='lowpass', fs=sr, output='sos')


def _butter_bp(lo, hi, sr, order=4):
    lo = max(lo, 20)
    hi = min(hi, sr // 2 - 100)
    return butter(order, [lo, hi], btype='bandpass', fs=sr, output='sos')


def normalize(x, db=-6.0):
    peak = np.abs(x).max()
    if peak < 1e-9:
        return x
    target = 10 ** (db / 20)
    return x * (target / peak)


# ---------------------------------------------------------------------------
# KICK 909
# ---------------------------------------------------------------------------
def kick_909(sr=SR_DEFAULT, decay_ms=550, start_hz=155, end_hz=50,
             sweep_ms=80, click_db=-8, punch=2.2):
    """
    Classic 909 kick:
    - Sine wave with exponential frequency sweep (start→end over sweep_ms)
    - Body: exponential amplitude decay
    - Click transient: very short broadband click layered on top
    - Soft saturation for punch
    """
    dur = decay_ms / 1000
    n = int(dur * sr)
    t = np.linspace(0, dur, n, dtype=np.float64)

    # --- frequency envelope ---
    sweep_t = sweep_ms / 1000
    freq = np.where(
        t < sweep_t,
        start_hz * (end_hz / start_hz) ** (t / sweep_t),
        end_hz
    )

    # --- oscillator ---
    phase = 2 * np.pi * np.cumsum(freq) / sr
    body = np.sin(phase)

    # --- amplitude envelope: fast attack, exponential decay ---
    tau = dur / 5.5
    amp = np.exp(-t / tau)
    # Slight pitch envelope click (0-5ms very fast transient boost)
    click_len = int(0.005 * sr)
    amp[:click_len] *= np.linspace(1.5, 1.0, click_len)

    body = body * amp

    # --- click transient (broadband noise burst, very short) ---
    click_n = int(0.005 * sr)
    click_noise = np.random.randn(click_n).astype(np.float64)
    click_env = np.exp(-np.arange(click_n, dtype=np.float64) / (0.001 * sr))
    click = click_noise * click_env * (10 ** (click_db / 20))

    out = body.copy()
    out[:click_n] += click[:click_n]

    # --- soft saturation (punch) ---
    out = np.tanh(out * punch) / punch

    return normalize(out.astype(np.float32))


# ---------------------------------------------------------------------------
# SNARE 909
# ---------------------------------------------------------------------------
def snare_909(sr=SR_DEFAULT, tone_hz=185, tone_decay_ms=250,
              noise_decay_ms=130, tone_mix=0.55):
    """
    909 snare = pitched sine burst + bandpass noise.
    """
    dur = max(tone_decay_ms, noise_decay_ms) / 1000 + 0.05
    n = int(dur * sr)
    t = np.linspace(0, dur, n, dtype=np.float64)

    # --- tone component ---
    tone_tau = tone_decay_ms / 1000 / 4
    tone_env = np.exp(-t / tone_tau)
    tone = np.sin(2 * np.pi * tone_hz * t) * tone_env

    # --- noise component: bandpass 1000-8000 Hz ---
    noise_raw = np.random.randn(n).astype(np.float64)
    sos_bp = _butter_bp(800, 8000, sr)
    noise_filt = sosfilt(sos_bp, noise_raw)
    noise_tau = noise_decay_ms / 1000 / 4
    noise_env = np.exp(-t / noise_tau)
    noise_component = noise_filt * noise_env

    # --- mix ---
    out = tone_mix * tone + (1 - tone_mix) * noise_component

    # --- transient click ---
    click_n = int(0.003 * sr)
    click = np.random.randn(click_n) * np.exp(-np.arange(click_n) / (0.001 * sr)) * 0.3
    out[:click_n] += click

    return normalize(out.astype(np.float32))


# ---------------------------------------------------------------------------
# HI-HAT 909
# ---------------------------------------------------------------------------
def hihat_c_909(sr=SR_DEFAULT, decay_ms=60):
    """Closed hi-hat: high-pass noise with fast decay."""
    dur = decay_ms / 1000 + 0.02
    n = int(dur * sr)
    noise = np.random.randn(n).astype(np.float64)

    # --- bandpass: 6 kHz – 18 kHz ---
    sos_hp = _butter_bp(5500, min(17000, sr // 2 - 100), sr)
    filt = sosfilt(sos_hp, noise)

    t = np.arange(n, dtype=np.float64) / sr
    tau = decay_ms / 1000 / 3
    env = np.exp(-t / tau)

    # Metallic tone addition (squares of multiple pitches)
    for hz in [204, 311, 419, 523]:
        filt += 0.15 * np.sin(2 * np.pi * hz * t) * env

    return normalize((filt * env).astype(np.float32))


def hihat_o_909(sr=SR_DEFAULT, decay_ms=380):
    """Open hi-hat: same but longer with slight pitch tail."""
    dur = decay_ms / 1000 + 0.05
    n = int(dur * sr)
    noise = np.random.randn(n).astype(np.float64)

    sos_hp = _butter_bp(5000, min(16000, sr // 2 - 100), sr)
    filt = sosfilt(sos_hp, noise)

    t = np.arange(n, dtype=np.float64) / sr
    tau = decay_ms / 1000 / 2.5
    env = np.exp(-t / tau)

    return normalize((filt * env).astype(np.float32))


# ---------------------------------------------------------------------------
# CLAP 909
# ---------------------------------------------------------------------------
def clap_909(sr=SR_DEFAULT, layers=4, layer_gap_ms=8, reverb_ms=200):
    """
    909 clap: 3-4 layered noise bursts (tight) + reverb tail.
    """
    burst_len = int(0.012 * sr)
    gap = int(layer_gap_ms / 1000 * sr)
    total = burst_len + gap * layers + int(reverb_ms / 1000 * sr)
    out = np.zeros(total, dtype=np.float64)

    for i in range(layers):
        start = i * gap
        noise = np.random.randn(burst_len)
        # bandpass 600-8000
        sos = _butter_bp(600, min(8000, sr // 2 - 100), sr)
        noise_f = sosfilt(sos, noise)
        env = np.exp(-np.arange(burst_len, dtype=np.float64) / (0.004 * sr))
        amp = 0.4 + 0.6 * (i / layers)
        out[start:start + burst_len] += noise_f * env * amp

    # Simple reverb: comb filter
    delay_s = int(0.022 * sr)
    feedback = 0.45
    wet = np.zeros_like(out)
    for k in range(delay_s, len(out)):
        wet[k] = out[k] + feedback * wet[k - delay_s]
    out = 0.7 * out + 0.3 * wet

    return normalize(out.astype(np.float32))


# ---------------------------------------------------------------------------
# TOM 909
# ---------------------------------------------------------------------------
def tom_909(sr=SR_DEFAULT, start_hz=100, end_hz=55, decay_ms=400):
    """Low tom: sine sweep like kick but lower/softer."""
    dur = decay_ms / 1000 + 0.05
    n = int(dur * sr)
    t = np.linspace(0, dur, n, dtype=np.float64)
    sweep_t = 0.04

    freq = np.where(t < sweep_t,
                    start_hz * (end_hz / start_hz) ** (t / sweep_t),
                    end_hz)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tau = decay_ms / 1000 / 4
    env = np.exp(-t / tau)
    tone = np.sin(phase) * env * 0.9

    return normalize(tone.astype(np.float32))


# ---------------------------------------------------------------------------
# RIM 909
# ---------------------------------------------------------------------------
def rim_909(sr=SR_DEFAULT):
    """Rimshot: sharp click + short sine burst."""
    dur = 0.06
    n = int(dur * sr)
    t = np.arange(n, dtype=np.float64) / sr

    click_n = int(0.003 * sr)
    noise = np.random.randn(click_n)
    sos = _butter_hp(2000, sr)
    noise_f = sosfilt(sos, noise)
    env = np.exp(-np.arange(click_n, dtype=np.float64) / (0.001 * sr))

    out = np.zeros(n)
    out[:click_n] = noise_f * env
    out += 0.3 * np.sin(2 * np.pi * 450 * t) * np.exp(-t / 0.015)

    return normalize(out.astype(np.float32))


# ---------------------------------------------------------------------------
# Cache and lookup
# ---------------------------------------------------------------------------
_CACHE = {}

def drum_hit(name: str, sr: int = SR_DEFAULT) -> np.ndarray:
    """Return cached drum hit as float32 mono array."""
    key = (name, sr)
    if key not in _CACHE:
        if name == "kick":
            _CACHE[key] = kick_909(sr)
        elif name == "snare":
            _CACHE[key] = snare_909(sr)
        elif name == "hat_c":
            _CACHE[key] = hihat_c_909(sr)
        elif name == "hat_o":
            _CACHE[key] = hihat_o_909(sr)
        elif name == "clap":
            _CACHE[key] = clap_909(sr)
        elif name == "tom":
            _CACHE[key] = tom_909(sr)
        elif name == "rim":
            _CACHE[key] = rim_909(sr)
        else:
            raise ValueError(f"Unknown drum hit: {name}")
    return _CACHE[key]


def render_drums(events, total_samples: int, sr: int = SR_DEFAULT,
                 stereo: bool = True) -> np.ndarray:
    """
    Render a list of (time_s, name, velocity) drum events into a buffer.

    Returns: float32 array shape (total_samples,) or (total_samples, 2).
    """
    # Name map supports aliases
    NAME_MAP = {
        "k": "kick", "bd": "kick", "kick": "kick",
        "s": "snare", "sd": "snare", "snare": "snare",
        "hc": "hat_c", "hat_c": "hat_c", "chh": "hat_c",
        "ho": "hat_o", "hat_o": "hat_o", "ohh": "hat_o",
        "cl": "clap", "clap": "clap",
        "t": "tom", "tom": "tom",
        "r": "rim", "rim": "rim",
    }

    buf = np.zeros(total_samples, dtype=np.float32)

    for (t_s, name, vel) in events:
        hit_name = NAME_MAP.get(name, name)
        sample = drum_hit(hit_name, sr)
        start = int(t_s * sr)
        end = min(start + len(sample), total_samples)
        n = end - start
        if n <= 0:
            continue
        gain = (vel / 127.0) ** 1.5  # velocity curve
        buf[start:end] += sample[:n] * gain

    if stereo:
        # Slight stereo spread: kick mono, snare slight L, hats slight R
        out = np.stack([buf, buf], axis=1)
        return out
    return buf
