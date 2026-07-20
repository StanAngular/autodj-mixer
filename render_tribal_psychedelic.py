#!/usr/bin/env python3
"""
render_tribal_psychedelic.py — "Sand Ritual"
7 minutes. Psychedelic Tribal Breakbeat. Accelerates 92→128 BPM.
African tribal meditation feel. Very quiet. No harsh edges anywhere.

Concept:
  The track is a gradual awakening — like a meditation ritual that builds
  from silence and sand textures to an organic, psychedelic drum trance.
  Everything enters whisper-quiet and swells imperceptibly.

Layers:
  1. Sand on glass — stereo textural constant background
  2. Djembe (synthesized) — main tribal kick drum
  3. Talking drum — pitch-bent mid percussion
  4. Shaker — high-frequency rattle with stereo spread
  5. Tribal bass — deep sine drone following root note
  6. Pad — atmospheric background, Am scale
  7. Psychedelic lead — slow melodic notes with deep reverb+delay+phaser

Structure (sections blend over 8-16 bars, no abrupt cuts):
  0:00-0:45  Silence + sand only, fade in very slowly
  0:45-1:30  Shaker enters (barely audible), drone underneath
  1:30-2:15  Djembe appears (very soft), tribal bass starts
  2:15-3:30  Full tribal pattern, lead melody enters
  3:30-5:00  Psychedelic peak — heavy panning, filter sweeps
  5:00-6:00  Gradual dissolution, elements drop out one by one
  6:00-7:00  Sand and drone only, fade to silence

Tempo acceleration: 92 BPM at t=0, 128 BPM at t=7:00
Beat times computed via quadratic formula from integral of BPM(t).
"""

import sys, os, logging, numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt
sys.path.insert(0, "/opt/autodj-mixer")

from autodj.generate.nature_synth import sand_on_glass, wind_gust
from autodj.generate.synthcore import (
    midi_to_hz, _wavetable_osc, adsr, lpf, hpf,
    apply_reverb, apply_delay, apply_chorus,
    mono_to_stereo, master_chain
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("tribal")

SR    = 44100
DUR   = 420.0        # 7:00
TOTAL = int(DUR * SR)

BPM_START = 92.0
BPM_END   = 128.0

# Am scale for tribal feel — pentatonic + blue note
# A2=45 C3=48 D3=50 E3=52 G3=55 A3=57 C4=60 E4=64 G4=67
SCALE = [45, 48, 50, 52, 55, 57, 60, 62, 64, 67]
ROOT  = 45   # A2

# Section envelopes (smooth cosine, 20s crossfades)
def section_gain(t, start, end, crossfade=20.0):
    """Returns 0→1→0 with cosine crossfade."""
    if t < start - crossfade or t >= end + crossfade:
        return 0.0
    if t < start:
        p = (t - (start - crossfade)) / crossfade
        return 0.5 * (1 - np.cos(np.pi * p))
    if t >= end:
        p = (t - end) / crossfade
        return 0.5 * (1 + np.cos(np.pi * p))
    return 1.0


# ---------------------------------------------------------------------------
# Accelerating tempo: compute beat times
# ---------------------------------------------------------------------------
def compute_beat_times():
    """
    BPM(t) = BPM_START + (BPM_END - BPM_START) * t / DUR
    beat_position(t) = integral_0^t BPM(tau)/60 dtau
                     = BPM_START*t/60 + rate*t^2/(2*60)
    where rate = (BPM_END - BPM_START) / DUR

    Given beat n, find t: solve quadratic for t.
    (rate/120)*t^2 + (BPM_START/60)*t - n = 0
    """
    rate = (BPM_END - BPM_START) / DUR
    beat_times = []
    n = 0
    while True:
        # Solve: (rate/120)*t^2 + (BPM_START/60)*t - n = 0
        a = rate / 120.0
        b = BPM_START / 60.0
        c = -n

        if a == 0:
            t = -c / b
        else:
            discriminant = b*b - 4*a*c
            if discriminant < 0:
                break
            t = (-b + np.sqrt(discriminant)) / (2 * a)

        if t > DUR:
            break
        beat_times.append(t)
        n += 1

    return np.array(beat_times, dtype=np.float64)


def compute_step_times(swing_pct=0.20):
    """
    Compute 16th-note step times with swing.
    African feel: triplet-ish swing (20%).
    For each beat, 4 16th-note steps:
    - step 0: on the beat
    - step 1: pushed forward by swing
    - step 2: half-beat
    - step 3: pushed forward by swing
    """
    beat_times = compute_beat_times()
    step_times = []

    for i in range(len(beat_times) - 1):
        t0 = beat_times[i]
        t1 = beat_times[i + 1]
        beat_dur = t1 - t0
        step_dur = beat_dur / 4.0

        # Swing: odd 16th notes pushed forward
        offsets = [0.0,
                   step_dur * (1.0 + swing_pct),
                   step_dur * 2.0,
                   step_dur * (3.0 + swing_pct)]

        for off in offsets:
            t = t0 + off
            if t < DUR:
                step_times.append(t)

    return np.array(step_times, dtype=np.float64)


# ---------------------------------------------------------------------------
# SYNTHESIZED TRIBAL DRUMS
# ---------------------------------------------------------------------------
def djembe(pitch_hz=220, decay_ms=180, tone_mix=0.65, sr=SR):
    """
    Djembe synthesis: sine burst + thump noise.
    Lower pitch = bass slap, higher = tone strike.
    """
    n = int(decay_ms / 1000 * sr * 2)
    t = np.arange(n, dtype=np.float64) / sr

    # Slight pitch drop (djembe characteristic)
    freq = pitch_hz * np.exp(-t / 0.025)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tone = np.sin(phase).astype(np.float32)

    # Body envelope
    tau = decay_ms / 1000 / 4
    body_env = np.exp(-t / tau).astype(np.float32)
    tone_part = tone * body_env

    # Thump: bandpass noise 150-600 Hz
    noise = np.random.randn(n).astype(np.float32)
    sos = butter(4, [150, 600], btype='bandpass', fs=sr, output='sos')
    thump = sosfilt(sos, noise).astype(np.float32)
    thump_env = np.exp(-t / (tau * 0.5)).astype(np.float32)
    thump_part = thump * thump_env

    out = tone_mix * tone_part + (1 - tone_mix) * thump_part
    peak = np.abs(out).max()
    if peak > 0:
        out *= 0.5 / peak
    return out.astype(np.float32)


def talking_drum(start_hz=400, end_hz=200, dur_ms=120, sr=SR):
    """Talking drum: pitch-bent tone, hand pressure simulation."""
    n = int(dur_ms / 1000 * sr)
    t = np.arange(n, dtype=np.float64) / sr

    # Pitch glides from start to end
    freq = start_hz * (end_hz / start_hz) ** (t / (dur_ms / 1000))
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tone = np.sin(phase).astype(np.float32)

    # Add harmonic texture
    tone += 0.3 * np.sin(2 * phase).astype(np.float32)
    tone += 0.1 * np.sin(3 * phase).astype(np.float32)

    # Envelope: fast attack, medium decay
    env = np.exp(-t / (dur_ms / 1000 / 3)).astype(np.float32)
    fade_in = min(int(0.004 * sr), n)
    env[:fade_in] *= np.linspace(0, 1, fade_in)

    out = tone * env * 0.4
    peak = np.abs(out).max()
    if peak > 0:
        out *= 0.45 / peak
    return out.astype(np.float32)


def shaker_grain(dur_ms=30, sr=SR):
    """Single shaker grain: short noise burst."""
    n = int(dur_ms / 1000 * sr)
    noise = np.random.randn(n).astype(np.float32)
    sos = butter(4, [6000, min(14000, sr // 2 - 100)],
                 btype='bandpass', fs=sr, output='sos')
    filt = sosfilt(sos, noise).astype(np.float32)
    env = np.exp(-np.arange(n, dtype=np.float32) / (n * 0.3))
    out = filt * env * 0.3
    peak = np.abs(out).max()
    if peak > 0:
        out *= 0.3 / peak
    return out.astype(np.float32)


# Pre-compute drum samples
DJEMBE_BASS  = djembe(pitch_hz=100, decay_ms=280, tone_mix=0.7)
DJEMBE_MID   = djembe(pitch_hz=180, decay_ms=160, tone_mix=0.75)
DJEMBE_HIGH  = djembe(pitch_hz=320, decay_ms=100, tone_mix=0.8)
TALKING_DOWN = talking_drum(start_hz=480, end_hz=180, dur_ms=130)
TALKING_UP   = talking_drum(start_hz=180, end_hz=400, dur_ms=100)
SHAKER       = shaker_grain(dur_ms=25)


def stamp(buf, sample, t_s, vel=0.8, pan=0.0, sr=SR):
    """Place sample into stereo buffer at time t_s with velocity and pan."""
    start = int(t_s * sr)
    n = min(len(sample), TOTAL - start)
    if n <= 0:
        return
    s = sample[:n]

    # Tiny fade-in to avoid clicks (0.5ms)
    fi = min(int(0.0005 * sr), n)
    if fi > 1:
        fade = np.linspace(0, 1, fi).astype(np.float32)
        s = s.copy()
        s[:fi] *= fade

    l_gain = vel * np.sqrt(0.5 * (1 - pan))
    r_gain = vel * np.sqrt(0.5 * (1 + pan))
    buf[start:start + n, 0] += s * l_gain
    buf[start:start + n, 1] += s * r_gain


# ---------------------------------------------------------------------------
# BUILD LAYERS
# ---------------------------------------------------------------------------

def build_drums(step_times, beat_times):
    """
    Tribal drum patterns — evolve over time.

    Djembe pattern (12/8 African feel, mapped to 16th grid):
    Bass:  1 . . . . . . . | 1 . . . . . . .
    Mid:   . . 1 . . 1 . . | . . 1 . . 1 . .
    High:  . 1 . 1 . . 1 . | . 1 . 1 . . 1 .
    Talk:  . . . . 1 . . . | . . . . . . 1 .

    Pattern slowly becomes more complex as BPM rises.
    """
    log.info("  Tribal drums...")
    buf = np.zeros((TOTAL, 2), dtype=np.float32)

    n_steps = len(step_times)
    n_beats = len(beat_times)

    rng = np.random.RandomState(42)

    for si, t in enumerate(step_times):
        if t >= DUR:
            break

        step_in_bar = si % 16
        beat_in_bar = si // 4 % 4

        # Progression intensity: 0 at t=0, 1 at peak (3:30-5:00), back to 0
        intensity = section_gain(t, 90, 360, crossfade=45)
        if intensity < 0.01:
            continue

        # Velocity: also follows intensity + small random variation
        vel_base = intensity * 0.5  # max 0.5 (very quiet)
        vel_rand = rng.uniform(0.9, 1.1)

        # ----- DJEMBE BASS: steps 0, 8 (beat 1 and 3) -----
        if step_in_bar in (0, 8):
            vel = vel_base * vel_rand * 0.9
            # Bass djembe slightly panned center with mic width
            pan = rng.uniform(-0.1, 0.1)
            stamp(buf, DJEMBE_BASS, t, vel=vel, pan=pan)

        # ----- DJEMBE MID: steps 2, 5, 10, 13 -----
        if step_in_bar in (2, 5, 10, 13):
            vel = vel_base * vel_rand * 0.7
            pan = rng.uniform(-0.3, 0.3)
            stamp(buf, DJEMBE_MID, t, vel=vel, pan=pan)

        # ----- DJEMBE HIGH: emerges after 2:15 -----
        if t > 135 and step_in_bar in (1, 3, 6, 9, 11, 14):
            complex_gate = section_gain(t, 135, 360, crossfade=30)
            vel = vel_base * vel_rand * 0.5 * complex_gate
            if vel > 0.02:
                pan = rng.uniform(-0.4, 0.4)
                stamp(buf, DJEMBE_HIGH, t, vel=vel, pan=pan)

        # ----- TALKING DRUM: sparse, cross-rhythm -----
        if step_in_bar in (4, 12) and t > 90:
            talk_intensity = section_gain(t, 90, 300, crossfade=30)
            vel = vel_base * vel_rand * 0.6 * talk_intensity
            if vel > 0.02:
                # Alternate up/down
                sample = TALKING_DOWN if (si // 4) % 2 == 0 else TALKING_UP
                pan = rng.uniform(-0.5, 0.5)
                stamp(buf, sample, t, vel=vel, pan=pan)

        # ----- SHAKER: 8th notes from 0:45, very quiet -----
        if step_in_bar % 2 == 0 and t > 45:
            shaker_intensity = section_gain(t, 45, 330, crossfade=25)
            vel = vel_base * vel_rand * 0.35 * shaker_intensity
            if vel > 0.01:
                # Shaker: wide stereo, rotating
                pan = np.sin(2 * np.pi * t / 7.0) * 0.7
                stamp(buf, SHAKER, t, vel=vel, pan=float(pan))

    return buf


def build_tribal_bass(beat_times):
    """Deep sine drone on root A, with octave jumps."""
    log.info("  Tribal bass...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    sec_env = np.array([section_gain(i / SR, 90, 330, crossfade=40)
                        for i in range(TOTAL)], dtype=np.float32)

    # Root note A2 + A1 octave
    f1 = midi_to_hz(ROOT)      # A2 = 110 Hz
    f2 = midi_to_hz(ROOT - 12) # A1 = 55 Hz

    t_arr = np.arange(TOTAL, dtype=np.float64) / SR

    # Slow filter LFO (period 15s)
    filter_lfo = 0.5 + 0.5 * np.sin(2 * np.pi * t_arr / 15.0)

    tone = (np.sin(2 * np.pi * f1 * t_arr) * 0.6 +
            np.sin(2 * np.pi * f2 * t_arr) * 0.4).astype(np.float32)

    # Slow LP filter sweep
    from scipy.signal import butter, sosfilt
    sos = butter(4, 300, btype='lowpass', fs=SR, output='sos')
    tone = sosfilt(sos, tone).astype(np.float32)

    tone *= sec_env * 0.35

    stereo = mono_to_stereo(tone, pan=0.0)
    return stereo


def build_pad(beat_times):
    """Atmospheric Am pad, very slow attack, barely there."""
    log.info("  Tribal pad...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    from autodj.generate.synthcore import supersaw, lpf

    # Am chord: A2 C3 E3 G3 (Am7)
    chord_notes = [45, 48, 52, 55]  # A2 C3 E3 G3

    for note in chord_notes:
        freq = midi_to_hz(note)
        osc = _wavetable_osc(freq, TOTAL, SR, "tri")
        osc = lpf(osc, 800, sr=SR)
        buf += osc * 0.12

    # Global envelope: fade in 45s, fade out at end
    env = np.ones(TOTAL, dtype=np.float32)
    fi = int(45 * SR)
    env[:fi] = 0.5 * (1 - np.cos(np.pi * np.arange(fi) / fi))
    fo = int(60 * SR)
    env[-fo:] = 0.5 * (1 + np.cos(np.pi * np.arange(fo) / fo))
    buf *= env * 0.2

    stereo = mono_to_stereo(buf, pan=0.0)
    stereo = apply_reverb(stereo, SR, room_size=0.88, wet=0.6, damping=0.3)
    return stereo


def build_psychedelic_lead(step_times):
    """
    Slow tribal melody, Am pentatonic, very long notes.
    Active from 2:15–5:30 with psychedelic processing.
    """
    log.info("  Psychedelic lead...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    lead_scale = [45, 48, 52, 55, 57, 60, 64, 67]  # Am pent + b7
    rng = np.random.RandomState(77)

    # Notes triggered every 2-3 beats
    beat_times_arr = np.array(
        [t for t in step_times if t < DUR][::8]  # every 8 steps = 2 beats
    )

    prev_idx = 4  # start mid-scale
    for t_note in beat_times_arr:
        if t_note < 135 or t_note > 330:
            continue

        intensity = section_gain(t_note, 135, 330, crossfade=30)
        if intensity < 0.01:
            continue

        # Step motion preference
        step = rng.choice([-2, -1, -1, 0, 0, 1, 1, 2])
        note_idx = (prev_idx + step) % len(lead_scale)
        note = lead_scale[note_idx]
        prev_idx = note_idx

        freq = midi_to_hz(note)

        # Long note duration: 1.5-3 seconds
        dur_s = rng.uniform(1.5, 3.0)
        n_note = int(min(dur_s, DUR - t_note) * SR)
        if n_note < 1000:
            continue

        # Triangle oscillator — warm, not harsh
        osc = _wavetable_osc(freq, n_note, SR, "tri")
        osc = lpf(osc, min(freq * 5, 3000), sr=SR)

        # Very slow attack
        attack_ms = rng.uniform(600, 1200)
        env = adsr(attack_ms, 200, -4, 800, n_note / SR, SR)
        min_n = min(len(osc), len(env))
        tone = (osc[:min_n] * env[:min_n] * intensity * 0.3).astype(np.float32)
        n_note = min_n

        # Psychedelic pan: slow LFO per note + drift
        pan = float(np.sin(2 * np.pi * t_note / 13.0) * 0.5)

        start = int(t_note * SR)
        end = min(start + n_note, TOTAL)
        n = end - start
        buf[start:end] += tone[:n] * np.sqrt(0.5 * (1 - pan))
        buf_r = buf.copy()  # temp for R side
        buf_r[start:end] = tone[:n] * np.sqrt(0.5 * (1 + pan))

    # Apply psychedelic effects
    stereo = np.stack([buf, buf], axis=1).astype(np.float32)

    # Delay: tribal echo (dotted 8th synced)
    delay_ms = 60000 / 110 * 0.75  # approx middle of tempo range
    stereo = apply_delay(stereo, SR, delay_ms=delay_ms, feedback=0.45, wet=0.4)
    stereo = apply_reverb(stereo, SR, room_size=0.75, wet=0.5, damping=0.25)
    stereo = apply_chorus(stereo, SR, rate_hz=0.2, depth=0.3, wet=0.35)

    return stereo


def build_sand_texture():
    """Sand on glass — constant background, density evolves."""
    log.info("  Sand texture...")
    buf_l = np.zeros(TOTAL, dtype=np.float32)
    buf_r = np.zeros(TOTAL, dtype=np.float32)

    # Render in 10-second chunks with evolving density
    chunk_s = 10.0
    chunk_n = int(chunk_s * SR)
    n_chunks = int(np.ceil(DUR / chunk_s))

    for ci in range(n_chunks):
        t_start = ci * chunk_s
        t_mid = t_start + chunk_s / 2
        actual_n = min(chunk_n, TOTAL - int(t_start * SR))
        if actual_n <= 0:
            break

        # Density: starts sparse, builds, then sparse again
        density = 0.2 + 0.5 * np.sin(np.pi * t_mid / DUR)
        # Add periodic "pour" moments
        pour_pulse = 0.3 * abs(np.sin(2 * np.pi * t_mid / 45.0))
        density = min(0.9, density + pour_pulse)

        pan_speed = 0.5 + 1.0 * (t_mid / DUR)  # speeds up as track accelerates

        l, r = sand_on_glass(actual_n, SR,
                             density=density,
                             pan_speed=pan_speed,
                             seed=1000 + ci)

        # Smooth crossfade between chunks (500ms)
        xf_n = min(int(0.5 * SR), actual_n)
        if ci > 0 and xf_n > 0:
            fade_in = 0.5 * (1 - np.cos(np.pi * np.arange(xf_n) / xf_n)).astype(np.float32)
            l[:xf_n] *= fade_in
            r[:xf_n] *= fade_in

        start = int(t_start * SR)
        end = min(start + actual_n, TOTAL)
        n = end - start
        buf_l[start:end] += l[:n]
        buf_r[start:end] += r[:n]

    # Global volume envelope
    env = np.ones(TOTAL, dtype=np.float32)
    fi = int(8 * SR)
    env[:fi] = 0.5 * (1 - np.cos(np.pi * np.arange(fi) / fi))
    fo = int(12 * SR)
    env[-fo:] = 0.5 * (1 + np.cos(np.pi * np.arange(fo) / fo))
    buf_l *= env
    buf_r *= env

    return np.stack([buf_l, buf_r], axis=1).astype(np.float32)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    log.info(f"Sand Ritual | {BPM_START}→{BPM_END} BPM | Am | {DUR:.0f}s (7:00)")

    log.info("Computing beat grid (accelerating tempo)...")
    beat_times = compute_beat_times()
    step_times = compute_step_times(swing_pct=0.20)
    log.info(f"  {len(beat_times)} beats, {len(step_times)} steps")

    sand_buf  = build_sand_texture()
    drum_buf  = build_drums(step_times, beat_times)
    bass_buf  = build_tribal_bass(beat_times)
    pad_buf   = build_pad(beat_times)
    lead_buf  = build_psychedelic_lead(step_times)

    def trim(b):
        if len(b) >= TOTAL:
            return b[:TOTAL]
        return np.pad(b, ((0, TOTAL - len(b)), (0, 0)))

    log.info("Mixing...")
    mix = np.zeros((TOTAL, 2), dtype=np.float32)
    mix += trim(sand_buf)  * 0.80   # sand: always present, quiet
    mix += trim(drum_buf)  * 0.90   # drums: organic, not too loud
    mix += trim(bass_buf)  * 0.70   # bass: subliminal
    mix += trim(pad_buf)   * 0.60   # pad: background
    mix += trim(lead_buf)  * 0.65   # lead: psychedelic, present

    # Global fade in/out
    fi = int(5 * SR)
    fo = int(8 * SR)
    fi_env = (0.5 * (1 - np.cos(np.pi * np.arange(fi) / fi))).astype(np.float32)
    fo_env = (0.5 * (1 + np.cos(np.pi * np.arange(fo) / fo))).astype(np.float32)
    mix[:fi, 0] *= fi_env;  mix[:fi, 1] *= fi_env
    mix[-fo:, 0] *= fo_env; mix[-fo:, 1] *= fo_env

    log.info("Mastering...")
    # Very gentle master — no aggressive compression (user wants quiet, clean)
    mix = np.clip(mix, -2.0, 2.0)
    mix = np.tanh(mix * 0.9) / 0.9
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= (10 ** (-3.0 / 20)) / peak  # -3 dBFS peak (quiet)

    if not np.isfinite(mix).all():
        mix = np.nan_to_num(mix, nan=0.0, posinf=0.5, neginf=-0.5)

    out_wav = "/tmp/tribal_psychedelic.wav"
    out_mp3 = "/tmp/tribal_psychedelic.mp3"
    log.info(f"Writing {out_wav}...")
    sf.write(out_wav, mix, SR)
    log.info("Converting to MP3 320k...")
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 320k "{out_mp3}" 2>/dev/null')

    size_mb = os.path.getsize(out_mp3) / 1024**2
    log.info(f"Done: {out_mp3} ({size_mb:.1f} MB)")
    return out_mp3


if __name__ == "__main__":
    mp3 = main()
    print(f"\nOutput: {mp3}")
