#!/usr/bin/env python3
"""
render_spa_breakbeat.py — "Steam Garden"
11:11  |  88 BPM  |  Am  |  chillout deep indie breakbeat

For lounge / spa zone. Everything soft, warm, organic.
No harsh edges. Light, magical, non-synthesizer feel.

Sound palette:
  - Pluck arp (multi-partial sine, natural decay — harp/marimba character)
  - Warm sine pad (stacked sinusoids, no sawtooth)
  - Flute-like melody (vibrato sine, slow attack)
  - Upright-bass-like sine bass
  - Very soft swung breakbeat (low velocity, heavy swing)
  - Rain + wind (very quiet ambient texture)
  - Vinyl noise floor
"""
# ═══════════════════════════════════════════════════════════════════════════
# ⚠️  УСТАРЕВШИЙ СКРИПТ-ФОРК — НЕ ИСПОЛЬЗОВАТЬ ДЛЯ НОВЫХ ТРЕКОВ (P89)
#
# Этот файл содержит СОБСТВЕННУЮ копию композиции (мелодия/гармония/структура),
# написанную до P82-P88. Он НЕ использует:
#   • мотивную мелодию с развитием (P86)      • секционную аранжировку (P82/P83)
#   • уникальную гармонию на трек (P88)       • личность трека: свинг/синкопа/регистры
# Поэтому треки из него звучат одинаково от рендера к рендеру — что бы мы ни улучшали.
#
# ПРАВИЛЬНО:  python3 render_track.py <жанр>      (жанры см. GENRES в render_track.py)
# Запустить всё-таки:  AUTODJ_ALLOW_LEGACY=1 python3 render_spa_breakbeat.py
# ═══════════════════════════════════════════════════════════════════════════
import os as _os, sys as _sys
if __name__ == "__main__" and not _os.environ.get("AUTODJ_ALLOW_LEGACY"):
    print(__doc__ or "")
    print("\n⚠️  УСТАРЕЛО: render_spa_breakbeat.py не использует улучшения P82-P88 "
          "(мотив, аранжировка, уникальная гармония).")
    print("   Рендерь через:  python3 render_track.py <жанр>")
    print("   Форс:           AUTODJ_ALLOW_LEGACY=1 python3 render_spa_breakbeat.py\n")
    _sys.exit(3)

import os, sys, time
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

sys.path.insert(0, "/opt/autodj-mixer")
from autodj.generate.synth909 import render_drums
from autodj.generate.synthcore import (
    midi_to_hz, sine_wave, adsr, lpf, hpf,
    apply_reverb, apply_delay, apply_chorus, apply_compressor,
    make_section_envelope, mono_to_stereo, apply_envelope_stereo,
    master_chain,
)
from autodj.generate.nature_synth import rain, wind_gust, crickets
from autodj.generate.music_theory import (
    resolve_progression, voice_lead_sequence,
    humanize_drum_events, humanize_velocity,
    get_reverb, hp_for_role, mix_gain, scale_notes,
)

# ── constants ──────────────────────────────────────────────────────
SR     = 44100
BPM    = 88.0
DUR    = 671.0           # 11:11
BAR_S  = 60.0 / BPM * 4  # ~2.727s
BEAT_S = 60.0 / BPM       # ~0.682s
STEP_S = BAR_S / 16       # 16th note ~0.170s
TOTAL  = int(DUR * SR)
SWING  = 0.28             # swing amount: 28% of STEP_S pushed late

ROOT   = 45               # A2

# Lounge/jazz chord progression with 7ths — warm, non-aggressive
_raw = resolve_progression(ROOT, "lounge", use_7ths=True)
CHORDS = voice_lead_sequence(_raw)

# Am lounge scale for melody/arp
SCALE = scale_notes(57, "pentatonic_min", 2)  # A3 pentatonic, 2 octaves

# ── sections ─────────────────────────────────────────────────────
S_INTRO      = (0.0,    55.0)
S_BASS_IN    = (45.0,   120.0)
S_SOFT_GRV   = (108.0,  220.0)
S_DEVELOP    = (208.0,  360.0)
S_PEAK       = (348.0,  450.0)
S_BREAKDOWN  = (438.0,  540.0)
S_RETURN     = (528.0,  631.0)
S_OUTRO      = (619.0,  671.0)


def _hp(sig, cutoff, sr=SR):
    sos = butter(2, min(cutoff, sr//2-100), btype="highpass", fs=sr, output="sos")
    return sosfilt(sos, sig).astype(np.float32)


def _lp(sig, cutoff, sr=SR):
    sos = butter(2, min(cutoff, sr//2-100), btype="lowpass", fs=sr, output="sos")
    return sosfilt(sos, sig).astype(np.float32)


def swung_time(step: int) -> float:
    """
    Apply swing to 16th note grid.
    Every odd step (off-beat) pushed late by SWING fraction.
    Creates relaxed, human groove feel.
    """
    t = step * STEP_S
    if step % 2 == 1:
        t += STEP_S * SWING
    return t


# ── CUSTOM INSTRUMENTS (non-synthesizer character) ─────────────────

def pluck_note(midi_note: int, dur_s: float, sr: int = SR,
               brightness: float = 0.6) -> np.ndarray:
    """
    Harp / marimba / vibraphone character.
    Stacked sine partials with exponential decay —
    higher partials decay faster (physical string/bar behaviour).
    """
    freq = midi_to_hz(midi_note)
    n = int(dur_s * sr)
    t = np.arange(n, dtype=np.float64) / sr
    buf = np.zeros(n, dtype=np.float64)

    # Partials with natural amplitude and decay
    partials = [
        (1, 1.00, 2.5),
        (2, 0.40, 5.0),
        (3, 0.18, 9.0),
        (4, 0.08, 14.0),
        (5, 0.03, 20.0),
    ]
    for k, amp, decay in partials:
        buf += amp * np.sin(2 * np.pi * freq * k * t) * np.exp(-t * decay)

    # Slight random phase variation per note for organic feel
    buf *= np.exp(-t * 0.3)  # gentle overall decay tail

    peak = np.abs(buf).max()
    if peak > 0:
        buf *= 0.7 / peak
    return buf.astype(np.float32)


def flute_note(midi_note: int, dur_s: float, sr: int = SR) -> np.ndarray:
    """
    Breathy flute-like tone: sine + 2nd harmonic + slow vibrato.
    Very gentle, floaty feel.
    """
    freq = midi_to_hz(midi_note)
    n = int(dur_s * sr)
    t = np.arange(n, dtype=np.float64) / sr

    # Vibrato: slow 5.2 Hz, grows over first 0.3s
    vibrato_depth = 0.018
    vibrato_onset = np.clip(t / 0.3, 0, 1)
    vibrato = 1.0 + vibrato_depth * vibrato_onset * np.sin(2 * np.pi * 5.2 * t)

    # Fundamental + breath-harmonic (2nd partial, softer)
    osc = np.sin(2 * np.pi * freq * t * vibrato)
    osc += 0.12 * np.sin(2 * np.pi * freq * 2 * t)

    # Breath noise (very subtle)
    rng = np.random.RandomState(int(freq))
    breath = rng.randn(n) * 0.04
    sos = butter(2, [2000, 8000], btype="bandpass", fs=sr, output="sos")
    breath = sosfilt(sos, breath)

    signal = (osc + breath).astype(np.float64)

    # Slow attack, gentle release
    env = adsr(400, 80, -3, 600, dur_s, sr).astype(np.float64)
    min_n = min(len(signal), len(env), n)
    return (signal[:min_n] * env[:min_n]).astype(np.float32)


def warm_pad_voice(midi_note: int, dur_s: float, sr: int = SR) -> np.ndarray:
    """
    Warm, organ-like pad: stacked sines (not sawtooth).
    Sounds like distant strings or pipe organ.
    """
    freq = midi_to_hz(midi_note)
    n = int(dur_s * sr)
    t = np.arange(n, dtype=np.float64) / sr

    # Additive: fundamentals + harmonics with phase offsets
    osc = np.zeros(n, dtype=np.float64)
    harmonics = [(1, 1.0, 0.0), (2, 0.45, 0.4), (3, 0.22, 0.8),
                 (4, 0.10, 1.2), (5, 0.04, 1.6)]
    for k, amp, phase in harmonics:
        osc += amp * np.sin(2 * np.pi * freq * k * t + phase)

    # Very slow tremolo
    tremolo = 1 + 0.04 * np.sin(2 * np.pi * 0.8 * t)
    osc *= tremolo

    env = adsr(1800, 300, -4, 3000, dur_s, sr).astype(np.float64)
    min_n = min(len(osc), len(env), n)
    out = osc[:min_n] * env[:min_n]

    peak = np.abs(out).max()
    return ((out / peak * 0.6) if peak > 0 else out).astype(np.float32)


def round_bass_note(midi_note: int, dur_s: float, sr: int = SR) -> np.ndarray:
    """
    Upright-bass-like round sine bass.
    Very warm — just fundamental + small 2nd harmonic.
    """
    freq = midi_to_hz(midi_note)
    n = int(dur_s * sr)
    t = np.arange(n, dtype=np.float64) / sr

    osc = np.sin(2 * np.pi * freq * t)
    osc += 0.12 * np.sin(2 * np.pi * freq * 2 * t)

    # Pluck-like envelope: quick attack, long decay
    attack = min(int(0.012 * sr), n // 4)
    osc[:attack] *= np.linspace(0, 1, attack)

    decay_factor = np.exp(-t * 1.8)
    sustain = 0.5
    env = sustain + (1.0 - sustain) * decay_factor
    out = osc * env

    # Fade out
    fade = min(int(0.08 * sr), n // 4)
    out[-fade:] *= np.linspace(1, 0, fade)

    peak = np.abs(out).max()
    return ((out / peak * 0.7) if peak > 0 else out).astype(np.float32)


# ── LAYER: DRUMS (soft swung breakbeat) ───────────────────────────

def build_drum_events():
    """
    Chill spa breakbeat: Amen-inspired but ultra-gentle.
    - Kick: very soft, sparse
    - Snare: brush-like (low velocity 909 snare)
    - Hats: swung 16ths, light
    - Rim: occasional decorative
    All velocities 25-60 (not 80-127 like club techno).
    """
    rng = np.random.RandomState(88)
    events = []

    # 16-step patterns (velocity 0 = rest, spa = max ~60)
    #              1  .  .  .  2  .  .  .  3  .  .  .  4  .  .  .
    PAT_KICK  = [ 48, 0, 0, 0, 0, 0, 0, 0, 0, 0,40, 0, 0, 0, 0, 0]
    PAT_SNARE = [  0, 0, 0, 0,40, 0, 0, 0, 0, 0, 0, 0,40, 0,30, 0]
    PAT_HAT   = [ 45, 0,38, 0,35, 0,40, 0,45, 0,38, 0,35, 0,40, 0]
    PAT_RIM   = [  0, 0, 0,30, 0, 0, 0, 0, 0, 0, 0,28, 0, 0, 0, 0]

    # Breakdown variation: even sparser
    PAT_KICK_B = [40, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    PAT_HAT_B  = [35, 0, 0, 0,30, 0, 0, 0,35, 0, 0, 0,30, 0, 0, 0]

    n_bars = int(DUR / BAR_S) + 1
    for bar in range(n_bars):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break

        in_groove    = S_SOFT_GRV[0] <= t_bar < S_BREAKDOWN[0]
        in_peak      = S_PEAK[0] <= t_bar < S_BREAKDOWN[0]
        in_breakdown = S_BREAKDOWN[0] <= t_bar < S_RETURN[0]
        in_return    = S_RETURN[0] <= t_bar < S_OUTRO[0]
        in_outro     = t_bar >= S_OUTRO[0]

        if in_outro or (not in_groove and not in_return):
            continue

        for step in range(16):
            t = t_bar + swung_time(step)
            if t >= DUR:
                break

            if in_breakdown:
                k = PAT_KICK_B[step]
                h = PAT_HAT_B[step]
                if k > 0:
                    events.append((t, "kick", k))
                if h > 0:
                    events.append((t, "hat_c", h))
                continue

            if PAT_KICK[step] > 0:
                events.append((t, "kick", PAT_KICK[step]))
            if PAT_SNARE[step] > 0:
                events.append((t, "snare", PAT_SNARE[step]))
            if PAT_HAT[step] > 0:
                events.append((t, "hat_c", PAT_HAT[step]))
            if PAT_RIM[step] > 0 and in_peak:
                events.append((t, "rim", PAT_RIM[step]))

    return events


def build_drums(drum_events):
    print("  drums: humanizing + rendering...")
    drum_events = humanize_drum_events(
        drum_events, vel_variation=0.14, apply_timing=True, seed=88
    )
    buf = render_drums(drum_events, TOTAL, SR, stereo=True)

    # Light room reverb: spa acoustic, not club
    buf_wet = apply_reverb(buf, SR, room_size=0.55, wet=0.25, damping=0.55)
    buf = buf * 0.72 + buf_wet * 0.28

    # Section envelope
    env = make_section_envelope(
        TOTAL,
        [
            (S_SOFT_GRV[0], S_BREAKDOWN[0], 1.0),
            (S_BREAKDOWN[0], S_RETURN[0], 0.5),
            (S_RETURN[0], S_OUTRO[0], 1.0),
        ],
        sr=SR, crossfade_bars=8, bpm=BPM,
    )
    apply_envelope_stereo(buf, env)
    return buf.astype(np.float32)


# ── LAYER: ROUND BASS ──────────────────────────────────────────────

def build_bass():
    print("  warm bass...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    bass_roots = [ch[0] for ch in CHORDS]
    note_dur = BAR_S * 4 * 0.92  # hold for 4 bars

    n_cycles = int(DUR / (BAR_S * 4)) + 1
    for cy in range(n_cycles):
        t_start = cy * BAR_S * 4
        if t_start >= DUR:
            break

        root = bass_roots[cy % 4]
        dur_s = min(note_dur, DUR - t_start)

        # Sub bass note, one octave below chord root
        note = root - 12  # very low
        freq = midi_to_hz(note)
        # Clamp to audible sub range
        if freq < 30:
            note += 12

        note_buf = round_bass_note(note, dur_s, SR)
        n = min(len(note_buf), TOTAL - int(t_start * SR))
        if n > 0:
            start = int(t_start * SR)
            buf[start:start + n] += note_buf[:n]

    env = make_section_envelope(
        TOTAL,
        [
            (S_BASS_IN[0], S_BREAKDOWN[0], 1.0),
            (S_BREAKDOWN[0], S_RETURN[0], 0.4),
            (S_RETURN[0], S_OUTRO[0], 0.9),
        ],
        sr=SR, crossfade_bars=10, bpm=BPM,
    )
    buf *= env
    buf = _lp(buf, 180, SR)  # keep it sub only

    stereo = mono_to_stereo(buf, pan=0.0)
    # Gentle sidechain from kick timing
    return stereo.astype(np.float32)


# ── LAYER: PLUCK ARP (harp/marimba character) ──────────────────────

def build_pluck_arp():
    print("  pluck arp...")
    buf_l = np.zeros(TOTAL, dtype=np.float32)
    buf_r = np.zeros(TOTAL, dtype=np.float32)

    rng = np.random.RandomState(77)

    # Pentatonic arp pattern over chord changes
    # Uses 8th notes (every 2 steps), swung
    note_dur = STEP_S * 2 * 0.8  # slightly shorter than 8th note

    # Different arp patterns per 8-bar phrase
    ARP_A = [0, 2, 4, 7, 9, 7, 4, 2]  # ascending + descending
    ARP_B = [9, 7, 4, 2, 0, 2, 4, 7]  # descending + ascending
    ARP_C = [0, 4, 7, 9, 7, 4, 9, 0]  # jumping

    n_steps = int(DUR / (STEP_S * 2)) + 1
    for si in range(n_steps):
        t = si * STEP_S * 2
        if t >= DUR:
            break

        bar_idx = int(t / BAR_S)
        phrase_bar = bar_idx % 8
        chord_idx = (bar_idx // 4) % 4

        # Choose arp pattern
        if phrase_bar < 3:
            arp = ARP_A
        elif phrase_bar < 6:
            arp = ARP_B
        else:
            arp = ARP_C

        degree = arp[si % len(arp)]
        if degree < len(SCALE):
            midi_note = SCALE[degree]
        else:
            midi_note = SCALE[-1]

        # Pan alternates for stereo spread
        pan = rng.uniform(-0.5, 0.5)
        note = pluck_note(midi_note, note_dur, SR)

        pos = int(t * SR)
        end = min(pos + len(note), TOTAL)
        n = end - pos
        if n > 0:
            l_amp = np.sqrt(0.5 * (1 - pan))
            r_amp = np.sqrt(0.5 * (1 + pan))
            buf_l[pos:end] += note[:n] * l_amp
            buf_r[pos:end] += note[:n] * r_amp

    # Section envelope
    env = make_section_envelope(
        TOTAL,
        [
            (S_SOFT_GRV[0], S_BREAKDOWN[0], 1.0),
            (S_BREAKDOWN[0], S_RETURN[0], 0.7),  # stays in breakdown
            (S_RETURN[0], S_OUTRO[0], 0.8),
        ],
        sr=SR, crossfade_bars=8, bpm=BPM,
    )
    buf_l *= env
    buf_r *= env

    stereo = np.column_stack([buf_l, buf_r]).astype(np.float32)
    stereo = apply_reverb(stereo, SR, room_size=0.65, wet=0.4, damping=0.4)
    stereo = apply_delay(stereo, SR, delay_ms=int(BEAT_S * 500),
                         feedback=0.2, wet=0.18)
    return stereo


# ── LAYER: FLUTE MELODY ────────────────────────────────────────────

def build_melody():
    print("  flute melody...")
    buf_l = np.zeros(TOTAL, dtype=np.float32)
    buf_r = np.zeros(TOTAL, dtype=np.float32)

    rng = np.random.RandomState(42)

    # Melody triggers every 2-4 beats, pentatonic
    # Call-and-response structure (Manifesto 2.1)
    melody_scale = scale_notes(57, "pentatonic_min", 2)  # A3 up
    high_notes = [n for n in melody_scale if 60 <= n <= 76]  # C4-E5 range

    beat = 0
    while beat < DUR / BEAT_S:
        t = beat * BEAT_S
        if t >= DUR:
            break

        # Choose note duration (2-6 beats)
        dur_beats = rng.choice([2, 2, 3, 4, 4, 6])
        dur_s = dur_beats * BEAT_S * 0.85  # slightly detached

        midi_note = rng.choice(high_notes)
        note_buf = flute_note(midi_note, dur_s, SR)

        # Stereo placement
        pan = rng.uniform(-0.4, 0.4)
        l_amp = np.sqrt(0.5 * (1 - pan))
        r_amp = np.sqrt(0.5 * (1 + pan))

        pos = int(t * SR)
        end = min(pos + len(note_buf), TOTAL)
        n = end - pos
        if n > 0:
            buf_l[pos:end] += note_buf[:n] * l_amp
            buf_r[pos:end] += note_buf[:n] * r_amp

        # Move forward (leave breathing gaps)
        beat += dur_beats + rng.choice([1, 2, 3])  # mandatory rest

    env = make_section_envelope(
        TOTAL,
        [
            (S_DEVELOP[0], S_BREAKDOWN[0], 1.0),
            (S_BREAKDOWN[0], S_RETURN[0], 0.6),
            (S_RETURN[0], S_OUTRO[0], 0.8),
        ],
        sr=SR, crossfade_bars=10, bpm=BPM,
    )
    buf_l *= env
    buf_r *= env

    stereo = np.column_stack([buf_l, buf_r]).astype(np.float32)
    rs, wet, damp = get_reverb("lead")
    stereo = apply_reverb(stereo, SR, room_size=rs + 0.1, wet=wet + 0.1, damping=damp)
    stereo = apply_chorus(stereo, SR, rate_hz=0.3, depth=0.18, wet=0.25)
    return stereo


# ── LAYER: WARM PAD ────────────────────────────────────────────────

def build_pad():
    print("  warm pad...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    cycle_s = BAR_S * 4
    n_cycles = int(DUR / cycle_s) + 1

    for cy in range(n_cycles):
        t_start = cy * cycle_s
        if t_start >= DUR:
            break

        chord = CHORDS[cy % 4]
        dur_s = min(cycle_s + 1.5, DUR - t_start)  # slight overlap
        n = int(dur_s * SR)

        chord_buf = np.zeros(n, dtype=np.float32)
        for note in chord:
            v = warm_pad_voice(note, dur_s, SR)
            min_n = min(len(v), n)
            chord_buf[:min_n] += v[:min_n]
        chord_buf /= len(chord) ** 0.6

        # Crossfade edges
        fade = min(int(2.5 * SR), n // 4)
        if fade > 0:
            chord_buf[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            chord_buf[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)

        # Slow filter sweep per cycle
        from scipy.signal import butter, sosfilt
        t_progress = t_start / DUR
        cutoff = 900 + 1200 * t_progress
        sos = butter(2, min(cutoff, SR // 2 - 100), btype="lowpass", fs=SR, output="sos")
        chord_buf = sosfilt(sos, chord_buf).astype(np.float32)

        pos = int(t_start * SR)
        end = min(pos + n, TOTAL)
        buf[pos:end] += chord_buf[:end - pos]

    # Always present but changes intensity
    env = make_section_envelope(
        TOTAL,
        [
            (S_INTRO[0],     S_BASS_IN[0],    0.5),
            (S_BASS_IN[0],   S_DEVELOP[0],    0.7),
            (S_DEVELOP[0],   S_BREAKDOWN[0],  0.85),
            (S_BREAKDOWN[0], S_RETURN[0],     1.0),   # prominent in breakdown
            (S_RETURN[0],    S_OUTRO[0],      0.75),
            (S_OUTRO[0],     DUR,             1.0),
        ],
        sr=SR, crossfade_bars=12, bpm=BPM,
    )
    buf *= env

    buf = hp_for_role(buf, "pad", SR)
    stereo = mono_to_stereo(buf, pan=0.0)
    rs, wet, damp = get_reverb("pad")
    stereo = apply_reverb(stereo, SR, room_size=rs, wet=wet, damping=damp)
    stereo = apply_chorus(stereo, SR, rate_hz=0.12, depth=0.18, wet=0.35)
    return stereo.astype(np.float32)


# ── LAYER: AMBIENT TEXTURE (rain + wind) ──────────────────────────

def build_nature():
    print("  nature texture (rain + wind)...")
    rng = np.random.RandomState(11)

    # Very quiet rain: only 10% intensity
    rain_buf = rain(TOTAL, SR, intensity=0.1, seed=5).astype(np.float32)
    rain_buf = _hp(rain_buf, 200, SR)

    # Occasional very soft wind
    wind_buf = np.zeros(TOTAL, dtype=np.float32)
    for i in range(6):
        t_start = rng.uniform(0, DUR - 20)
        dur_w = rng.uniform(15, 35)
        n_w = int(dur_w * SR)
        w = wind_gust(n_w, SR, seed=i).astype(np.float32)
        fade_w = int(4 * SR)
        w[:fade_w] *= np.linspace(0, 1, fade_w, dtype=np.float32)
        w[-fade_w:] *= np.linspace(1, 0, fade_w, dtype=np.float32)
        pos = int(t_start * SR)
        end = min(pos + n_w, TOTAL)
        wind_buf[pos:end] += w[:end - pos] * 0.3

    # Vinyl noise: very high frequency, very quiet
    vinyl = rng.randn(TOTAL).astype(np.float32) * 0.012
    vinyl = _hp(vinyl, 5000, SR)
    # Occasional light crackle
    n_cracks = int(DUR * 0.5)
    for _ in range(n_cracks):
        pos = rng.randint(0, TOTAL - 20)
        length = rng.randint(4, 16)
        vinyl[pos:pos + length] += rng.randn(length) * 0.006

    texture = rain_buf * 0.5 + wind_buf + vinyl * 0.6

    # Global fade in/out matching track
    fade_in = int(5 * SR)
    texture[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)

    stereo = mono_to_stereo(texture, pan=0.0)
    stereo = apply_reverb(stereo, SR, room_size=0.88, wet=0.55, damping=0.15)
    return stereo.astype(np.float32)


# ── MAIN ──────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print(f"Steam Garden — {int(DUR//60)}:{int(DUR%60):02d}, {BPM} BPM, Am, spa breakbeat")
    print(f"  {TOTAL:,} samples @ {SR} Hz")
    print(f"  CHORDS (voice-led): {CHORDS}")

    drum_events = build_drum_events()
    print(f"  {len(drum_events)} drum events")

    drums   = build_drums(drum_events)
    bass    = build_bass()
    arp     = build_pluck_arp()
    melody  = build_melody()
    pad     = build_pad()

    print("  mixing...")
    mix = np.zeros((TOTAL, 2), dtype=np.float32)

    # Gain structure: very gentle levels, spa is quiet
    mix += drums  * 0.55   # soft drums, not loud
    mix += bass   * 0.45   # round sub bass
    mix += arp    * 0.55   # pluck arp — main melodic feature
    mix += melody * 0.48   # flute melody
    mix += pad    * 0.38   # warm pad bed

    # Long gentle fade in + very long fade out
    fi = int(10.0 * SR)    # 10s fade in
    fo = int(25.0 * SR)    # 25s fade out
    mix[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)[:, None]

    # Safety clip
    mix = np.clip(mix, -2.5, 2.5)

    # Master
    print("  mastering...")
    mix = master_chain(mix, SR)

    # Quieter master for spa (-3dB relative to normal)
    peak = np.abs(mix).max()
    if peak > 0:
        target = 10 ** (-3.5 / 20)
        mix *= target / peak

    # Output
    os.makedirs("/opt/autodj-mixer/output", exist_ok=True)
    out_wav = "/opt/autodj-mixer/output/steam_garden.wav"
    out_mp3 = "/opt/autodj-mixer/output/steam_garden.mp3"

    print("  writing WAV...")
    sf.write(out_wav, mix, SR)

    print("  encoding MP3 256k...")
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 256k "{out_mp3}" 2>/dev/null')

    elapsed = time.time() - t0
    sz = os.path.getsize(out_mp3) / 1024 / 1024
    print(f"  done in {elapsed:.1f}s — {sz:.1f} MB — {out_mp3}")


if __name__ == "__main__":
    main()
