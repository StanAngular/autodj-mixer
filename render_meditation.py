#!/usr/bin/env python3
"""
render_meditation.py — 1-hour ambient trance meditation track

"Starlight Meadow" — 60:00, 72 BPM (subconscious pulse), Am

Architecture:
  - Chunk-based rendering (30s chunks) to stay within RAM
  - 8 melody periods of 7.5 minutes each
  - Each period: different scale/voicing, crossfades 60s into next
  - Nature sounds: rain, crickets, frogs, wind — always present, slowly varying
  - All effects extremely smooth: cosine fades, long tails
  - 3D stereo: binaural panning, rotating elements
  - Occasional gentle sub-beat (sine kick) every 2-3 minutes

Layers per chunk:
  1. Rain        — constant, intensity oscillates
  2. Crickets    — constant, density varies with "night progression"
  3. Frogs       — intermittent, density varies
  4. Wind        — slow gusts
  5. Pad         — evolving supersaw chords, very long attack
  6. Melody      — sine/triangle lead, slow meditative notes
  7. Sub-beat    — very gentle sine kick, sparse

Each layer is rendered per-chunk with deterministic seeds for continuity.
Final mix is written to WAV incrementally, then converted to MP3.
"""

import sys, os, logging, numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt
sys.path.insert(0, "/opt/autodj-mixer")

from autodj.generate.nature_synth import rain, crickets, frogs, wind_gust
from autodj.generate.synthcore import (
    midi_to_hz, supersaw, sine_wave, _wavetable_osc,
    adsr, lpf, hpf,
    apply_reverb, apply_chorus, apply_delay,
    mono_to_stereo, normalize_master
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("meditation")

SR     = 44100
BPM    = 72.0
DUR    = 3600.0       # 60 minutes
BEAT_S = 60 / BPM
BAR_S  = BEAT_S * 4
STEP_S = BAR_S / 16
CHUNK  = 30.0         # 30-second render chunks
CHUNK_N = int(CHUNK * SR)

# 8 melody periods, each 7.5 minutes = 450 seconds
PERIOD_S = 450.0
N_PERIODS = 8
XFADE_S = 60.0        # 60-second crossfade between periods

# ---------------------------------------------------------------------------
# Scales and chords per period (meditative progression)
# ---------------------------------------------------------------------------
# MIDI notes
PERIODS = [
    {   # Period 0: Am pentatonic — calm, introspective
        "name": "Am pent",
        "scale": [57, 60, 62, 64, 67, 69, 72, 74],    # A C D E G A C D (oct up)
        "chord": [57, 60, 64, 67],                      # Am7 wide
        "pad_cutoff": 1200,
        "melody_speed": 1.0,    # notes per beat
    },
    {   # Period 1: Dm7 — deeper
        "name": "Dm7",
        "scale": [62, 65, 67, 69, 72, 74, 77, 79],
        "chord": [50, 53, 57, 60],                      # Dm7
        "pad_cutoff": 1400,
        "melody_speed": 0.8,
    },
    {   # Period 2: G lydian — ethereal, lifting
        "name": "G lyd",
        "scale": [55, 59, 62, 66, 67, 71, 74, 78],     # G B D F# G B D F#
        "chord": [55, 59, 62, 66],                       # Gmaj7#11
        "pad_cutoff": 1800,
        "melody_speed": 0.6,
    },
    {   # Period 3: Cmaj9 — warm, wide
        "name": "Cmaj9",
        "scale": [60, 62, 64, 67, 69, 71, 72, 74],
        "chord": [48, 52, 55, 59, 62],                  # Cmaj9
        "pad_cutoff": 1600,
        "melody_speed": 0.5,
    },
    {   # Period 4: Em pent — melancholic return
        "name": "Em pent",
        "scale": [52, 55, 57, 59, 62, 64, 67, 69],
        "chord": [52, 55, 59, 62],                       # Em7
        "pad_cutoff": 1300,
        "melody_speed": 0.7,
    },
    {   # Period 5: Bbmaj7 — unexpected warmth
        "name": "Bbmaj7",
        "scale": [58, 60, 62, 65, 67, 70, 72, 74],
        "chord": [46, 50, 53, 57],                       # Bbmaj7
        "pad_cutoff": 1500,
        "melody_speed": 0.6,
    },
    {   # Period 6: F#m pent — otherworldly
        "name": "F#m pent",
        "scale": [54, 57, 59, 61, 64, 66, 69, 71],
        "chord": [54, 57, 61, 64],                       # F#m7
        "pad_cutoff": 1700,
        "melody_speed": 0.4,    # very slow
    },
    {   # Period 7: Am again — return home
        "name": "Am return",
        "scale": [57, 60, 62, 64, 67, 69, 72, 74],
        "chord": [45, 48, 52, 57, 60],                  # Am add9
        "pad_cutoff": 1100,
        "melody_speed": 0.3,    # almost still
    },
]


def period_at(t):
    """Return current and next period indices + crossfade weight."""
    idx = int(t / PERIOD_S)
    idx = min(idx, N_PERIODS - 1)
    t_in_period = t - idx * PERIOD_S

    next_idx = min(idx + 1, N_PERIODS - 1)
    if t_in_period > PERIOD_S - XFADE_S and idx < N_PERIODS - 1:
        # In crossfade zone
        xfade_progress = (t_in_period - (PERIOD_S - XFADE_S)) / XFADE_S
        xfade = 0.5 * (1 - np.cos(np.pi * xfade_progress))  # cosine
        return idx, next_idx, 1 - xfade, xfade
    return idx, next_idx, 1.0, 0.0


# ---------------------------------------------------------------------------
# Nature layers (per chunk)
# ---------------------------------------------------------------------------
def render_rain_chunk(chunk_idx, chunk_n):
    t_start = chunk_idx * CHUNK
    # Intensity varies slowly: 0.3-0.7, period 5 minutes
    t_mid = t_start + CHUNK / 2
    intensity = 0.4 + 0.2 * np.sin(2 * np.pi * t_mid / 300)
    seed = 10000 + chunk_idx
    r = rain(chunk_n, SR, intensity=intensity, seed=seed)
    # Normalize
    peak = np.abs(r).max()
    if peak > 0:
        r *= 0.3 / peak
    return r


def render_crickets_chunk(chunk_idx, chunk_n):
    t_start = chunk_idx * CHUNK
    # Crickets: denser in "nighttime" (middle of track), quieter at edges
    night_curve = np.sin(np.pi * t_start / DUR)
    n_crickets = max(2, int(4 + 4 * night_curve))
    density = 0.3 + 0.5 * night_curve
    seed = 20000 + chunk_idx
    c = crickets(chunk_n, SR, n_crickets=n_crickets, density=density, seed=seed)
    peak = np.abs(c).max()
    if peak > 0:
        c *= 0.2 / peak
    return c


def render_frogs_chunk(chunk_idx, chunk_n):
    t_start = chunk_idx * CHUNK
    # Frogs: present from minute 5 to 50
    if t_start < 300 or t_start > 3000:
        return np.zeros(chunk_n, dtype=np.float32)
    # Cosine envelope for frog presence
    frog_t = (t_start - 300) / (3000 - 300)
    frog_amp = np.sin(np.pi * frog_t)
    n_frogs = max(1, int(2 + 3 * frog_amp))
    seed = 30000 + chunk_idx
    f = frogs(chunk_n, SR, n_frogs=n_frogs, density=0.3 + 0.4 * frog_amp, seed=seed)
    peak = np.abs(f).max()
    if peak > 0:
        f *= 0.18 * frog_amp / peak
    return f


def render_wind_chunk(chunk_idx, chunk_n):
    t_start = chunk_idx * CHUNK
    speed = 0.3 + 0.2 * np.sin(2 * np.pi * t_start / 600)
    seed = 40000 + chunk_idx
    w = wind_gust(chunk_n, SR, speed=speed, seed=seed)
    peak = np.abs(w).max()
    if peak > 0:
        w *= 0.12 / peak
    return w


# ---------------------------------------------------------------------------
# Pad (per chunk)
# ---------------------------------------------------------------------------
def render_pad_chunk(chunk_idx, chunk_n):
    t_start = chunk_idx * CHUNK
    buf = np.zeros(chunk_n, dtype=np.float32)

    # Get current/next period
    p_idx, p_next, w_cur, w_next = period_at(t_start + CHUNK / 2)
    p_cur = PERIODS[p_idx]
    p_nxt = PERIODS[p_next]

    # Render current period pad (one long chord for the whole chunk)
    def make_pad(period_info, n_samples):
        chord = period_info["chord"]
        cutoff = period_info["pad_cutoff"]
        pad_buf = np.zeros(n_samples, dtype=np.float32)
        for note in chord:
            freq = midi_to_hz(note)
            osc = supersaw(freq, n_samples, SR, detune_cents=10.0, n_voices=5)
            osc = lpf(osc, cutoff, sr=SR)
            pad_buf += osc
        # Normalize
        peak = np.abs(pad_buf).max()
        if peak > 0:
            pad_buf *= 0.4 / peak
        return pad_buf

    pad_a = make_pad(p_cur, chunk_n)
    if w_next > 0.01:
        pad_b = make_pad(p_nxt, chunk_n)
        buf = pad_a * w_cur + pad_b * w_next
    else:
        buf = pad_a

    # Global amplitude: fade in first 5min, fade out last 5min
    t_mid = t_start + CHUNK / 2
    global_amp = 1.0
    if t_mid < 300:
        global_amp = 0.5 * (1 - np.cos(np.pi * t_mid / 300))
    elif t_mid > DUR - 300:
        global_amp = 0.5 * (1 + np.cos(np.pi * (t_mid - (DUR - 300)) / 300))

    buf *= global_amp
    return buf


# ---------------------------------------------------------------------------
# Melody (per chunk)
# ---------------------------------------------------------------------------
def render_melody_chunk(chunk_idx, chunk_n):
    t_start = chunk_idx * CHUNK
    buf = np.zeros(chunk_n, dtype=np.float32)

    p_idx, p_next, w_cur, w_next = period_at(t_start + CHUNK / 2)
    p_cur = PERIODS[p_idx]
    scale = p_cur["scale"]
    speed = p_cur["melody_speed"]

    # Note spacing: beats between notes
    note_interval = BEAT_S / speed * 2  # longer = more meditative
    note_dur = note_interval * 0.85     # sustain most of the interval

    # Deterministic melody: seed from period index for consistency within period
    rng = np.random.RandomState(50000 + p_idx * 100 + chunk_idx)

    # Walk through time in this chunk
    # Start from nearest note grid point
    t_first = (int(t_start / note_interval) + 1) * note_interval
    t = t_first
    prev_note_idx = rng.randint(0, len(scale))

    while t < t_start + CHUNK:
        t_local = t - t_start
        if t_local < 0:
            t += note_interval
            continue
        if t_local + note_dur * SR > chunk_n:
            break

        # Pick next note: prefer step motion (adjacent scale tones)
        step = rng.choice([-2, -1, -1, 0, 1, 1, 2])
        note_idx = (prev_note_idx + step) % len(scale)
        note = scale[note_idx]
        prev_note_idx = note_idx

        freq = midi_to_hz(note)
        n_note = int(min(note_dur, CHUNK - t_local) * SR)
        if n_note <= 0:
            t += note_interval
            continue

        # Triangle wave for warmth
        osc = _wavetable_osc(freq, n_note, SR, "tri")
        # Gentle LPF
        osc = lpf(osc, min(freq * 4, 3000), sr=SR)

        # Very long attack/release envelope
        attack_ms = 400 + rng.uniform(0, 300)
        release_ms = 600 + rng.uniform(0, 400)
        env = adsr(attack_ms, 100, -3, release_ms, n_note / SR, SR)
        tone = (osc * env).astype(np.float32)

        # Velocity variation
        vel = 0.5 + rng.uniform(-0.15, 0.15)
        tone *= vel

        start = int(t_local * SR)
        end = min(start + n_note, chunk_n)
        buf[start:end] += tone[:end - start]

        t += note_interval

    # Apply crossfade weight
    buf *= w_cur

    # Global amplitude: not present in first 2 min, fades in, fades out last 3 min
    t_mid = t_start + CHUNK / 2
    global_amp = 1.0
    if t_mid < 120:
        global_amp = 0.0
    elif t_mid < 300:
        global_amp = 0.5 * (1 - np.cos(np.pi * (t_mid - 120) / 180))
    elif t_mid > DUR - 180:
        global_amp = 0.5 * (1 + np.cos(np.pi * (t_mid - (DUR - 180)) / 180))

    buf *= global_amp
    return buf


# ---------------------------------------------------------------------------
# Sub-beat: very gentle sine kick, sparse
# ---------------------------------------------------------------------------
def render_beat_chunk(chunk_idx, chunk_n):
    t_start = chunk_idx * CHUNK
    buf = np.zeros(chunk_n, dtype=np.float32)

    # Beat only from minute 8 to 52 (not at edges)
    t_mid = t_start + CHUNK / 2
    if t_mid < 480 or t_mid > 3120:
        return buf

    # Gentle presence envelope
    beat_p = np.sin(np.pi * (t_mid - 480) / (3120 - 480))
    if beat_p < 0.1:
        return buf

    # Beat pattern: kick every 2 bars, very gentle
    kick_interval = BAR_S * 2  # every 2 bars = ~6.7s at 72 BPM
    t_first = (int(t_start / kick_interval) + 1) * kick_interval

    for t_kick in np.arange(t_first, t_start + CHUNK, kick_interval):
        t_local = t_kick - t_start
        if t_local < 0 or t_local >= CHUNK:
            continue

        # Sine kick: 60 Hz, long decay
        kick_dur = 0.8  # 800ms
        n_kick = int(kick_dur * SR)
        t_k = np.arange(n_kick, dtype=np.float64) / SR

        # Very gentle sine with slight pitch drop
        freq = 60 + 20 * np.exp(-t_k / 0.1)
        phase = 2 * np.pi * np.cumsum(freq) / SR
        kick = np.sin(phase)
        kick_env = np.exp(-t_k / 0.25)
        kick = (kick * kick_env * 0.3 * beat_p).astype(np.float32)

        start = int(t_local * SR)
        end = min(start + n_kick, chunk_n)
        buf[start:end] += kick[:end - start]

    return buf


# ---------------------------------------------------------------------------
# Stereo processing: 3D effects
# ---------------------------------------------------------------------------
def stereo_3d(mono_layers, chunk_idx, chunk_n):
    """
    Apply stereo/3D effects to mono layers.
    Returns stereo (chunk_n, 2) array.
    """
    t_start = chunk_idx * CHUNK
    t_arr = np.arange(chunk_n, dtype=np.float64) / SR + t_start

    rain_m, crickets_m, frogs_m, wind_m, pad_m, melody_m, beat_m = mono_layers

    # ---- RAIN: centered, slight width variation ----
    rain_st = mono_to_stereo(rain_m, pan=0.0)

    # ---- CRICKETS: rotating slowly around listener (period 35s) ----
    crick_pan = np.sin(2 * np.pi * t_arr / 35.0).astype(np.float32)
    crick_l = np.sqrt(0.5 * (1 - crick_pan)) * crickets_m
    crick_r = np.sqrt(0.5 * (1 + crick_pan)) * crickets_m
    crick_st = np.stack([crick_l, crick_r], axis=1)

    # ---- FROGS: positioned mostly left, slow drift (period 45s) ----
    frog_pan = -0.3 + 0.4 * np.sin(2 * np.pi * t_arr / 45.0)
    frog_pan = frog_pan.astype(np.float32)
    frog_l = np.sqrt(0.5 * (1 - frog_pan)) * frogs_m
    frog_r = np.sqrt(0.5 * (1 + frog_pan)) * frogs_m
    frog_st = np.stack([frog_l, frog_r], axis=1)

    # ---- WIND: wide sweep R→L (period 25s) ----
    wind_pan = np.sin(2 * np.pi * t_arr / 25.0).astype(np.float32)
    wind_l = np.sqrt(0.5 * (1 - wind_pan)) * wind_m
    wind_r = np.sqrt(0.5 * (1 + wind_pan)) * wind_m
    wind_st = np.stack([wind_l, wind_r], axis=1)

    # ---- PAD: wide stereo with chorus-like L/R offset ----
    # Slight delay difference between L/R for width
    delay_samples = int(0.015 * SR)  # 15ms Haas effect
    pad_l = pad_m.copy()
    pad_r = np.zeros_like(pad_m)
    pad_r[delay_samples:] = pad_m[:-delay_samples]
    pad_st = np.stack([pad_l * 0.9, pad_r * 0.9], axis=1)

    # ---- MELODY: slow circular pan (period 50s), very subtle ----
    mel_pan = 0.3 * np.sin(2 * np.pi * t_arr / 50.0).astype(np.float32)
    mel_l = np.sqrt(0.5 * (1 - mel_pan)) * melody_m
    mel_r = np.sqrt(0.5 * (1 + mel_pan)) * melody_m
    mel_st = np.stack([mel_l, mel_r], axis=1)

    # ---- BEAT: centered (sub) ----
    beat_st = mono_to_stereo(beat_m, pan=0.0)

    # ---- MIX ----
    mix = np.zeros((chunk_n, 2), dtype=np.float32)
    mix += rain_st    * 0.60
    mix += crick_st   * 0.50
    mix += frog_st    * 0.45
    mix += wind_st    * 0.35
    mix += pad_st     * 0.55
    mix += mel_st     * 0.50
    mix += beat_st    * 0.50

    return mix


# ---------------------------------------------------------------------------
# Chunk crossfade: smooth seam between adjacent chunks
# ---------------------------------------------------------------------------
XFADE_CHUNK_N = int(0.1 * SR)  # 100ms crossfade between chunks


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    log.info(f"Starlight Meadow | BPM={BPM} | {DUR:.0f}s (60:00)")

    n_chunks = int(np.ceil(DUR / CHUNK))
    log.info(f"Rendering in {n_chunks} chunks of {CHUNK:.0f}s each")

    out_wav = "/tmp/meditation.wav"
    out_mp3 = "/tmp/meditation.mp3"

    # Open output file for streaming write
    with sf.SoundFile(out_wav, 'w', SR, 2, 'PCM_16') as outfile:
        prev_tail = None  # last 100ms of previous chunk for crossfade

        for ci in range(n_chunks):
            t_start = ci * CHUNK
            remaining = DUR - t_start
            actual_chunk = min(CHUNK, remaining)
            actual_n = int(actual_chunk * SR)

            if ci % 10 == 0:
                pct = ci / n_chunks * 100
                log.info(f"  Chunk {ci}/{n_chunks} ({pct:.0f}%) t={t_start:.0f}s")

            # Render each mono layer
            rain_m     = render_rain_chunk(ci, actual_n)
            crickets_m = render_crickets_chunk(ci, actual_n)
            frogs_m    = render_frogs_chunk(ci, actual_n)
            wind_m     = render_wind_chunk(ci, actual_n)
            pad_m      = render_pad_chunk(ci, actual_n)
            melody_m   = render_melody_chunk(ci, actual_n)
            beat_m     = render_beat_chunk(ci, actual_n)

            # 3D stereo mix
            stereo = stereo_3d(
                [rain_m, crickets_m, frogs_m, wind_m, pad_m, melody_m, beat_m],
                ci, actual_n
            )

            # Chunk crossfade with previous
            if prev_tail is not None and actual_n > XFADE_CHUNK_N:
                xf_n = min(XFADE_CHUNK_N, actual_n, len(prev_tail))
                fade_out = 0.5 * (1 + np.cos(np.pi * np.arange(xf_n) / xf_n))
                fade_in  = 0.5 * (1 - np.cos(np.pi * np.arange(xf_n) / xf_n))
                stereo[:xf_n, 0] = stereo[:xf_n, 0] * fade_in + prev_tail[:xf_n, 0] * fade_out
                stereo[:xf_n, 1] = stereo[:xf_n, 1] * fade_in + prev_tail[:xf_n, 1] * fade_out

            # Save tail for next crossfade
            if actual_n > XFADE_CHUNK_N:
                prev_tail = stereo[-XFADE_CHUNK_N:].copy()
                # Write everything except the tail (which will be crossfaded next)
                write_chunk = stereo[:-XFADE_CHUNK_N]
            else:
                prev_tail = None
                write_chunk = stereo

            # Soft clip
            write_chunk = np.tanh(write_chunk * 1.1) / 1.1

            # Normalize to -1 dB headroom
            peak = np.abs(write_chunk).max()
            if peak > 0.9:
                write_chunk *= 0.89 / peak

            outfile.write(write_chunk)

        # Write final tail
        if prev_tail is not None:
            outfile.write(prev_tail)

    log.info(f"WAV written: {out_wav}")
    wav_size = os.path.getsize(out_wav) / 1024**2
    log.info(f"  Size: {wav_size:.0f} MB")

    # Convert to MP3 (192 kbps for 1-hour file — keeps it under 100 MB)
    log.info("Converting to MP3 (192k)...")
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 192k "{out_mp3}" 2>/dev/null')
    mp3_size = os.path.getsize(out_mp3) / 1024**2
    log.info(f"Done: {out_mp3} ({mp3_size:.1f} MB)")
    return out_mp3


if __name__ == "__main__":
    mp3 = main()
    print(f"\nOutput: {mp3}")
