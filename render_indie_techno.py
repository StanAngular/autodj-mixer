#!/usr/bin/env python3
"""
render_indie_techno.py — "Midnight Loop"
15:00  |  142 BPM  |  Am  |  indie techno

Minimalist, hypnotic, relentless.
Dry drum programming, sidechained sub-bass, syncopated analog bassline,
prickly synth stabs, filtered pad bed, breathy whispers,
Berlin school sequencer pulse, plate reverb snare, lo-fi dub feel.
"""

import os, sys, time
import numpy as np
import soundfile as sf

sys.path.insert(0, "/opt/autodj-mixer")
from autodj.generate.synth909 import (
    kick_909, snare_909, hihat_c_909, hihat_o_909, clap_909, rim_909,
    render_drums,
)
from autodj.generate.synthcore import (
    sawtooth_bl, square_bl, sine_wave, supersaw, midi_to_hz, adsr,
    lpf, hpf, lpf_sweep,
    acid_bass_note, pad_note, render_chord,
    apply_reverb, apply_delay, apply_chorus, apply_compressor,
    make_section_envelope, mono_to_stereo, apply_envelope_stereo,
    mix_into, master_chain,
)
from scipy.signal import butter, sosfilt

# ── constants ──────────────────────────────────────────────────────
SR       = 44100
BPM      = 142.0
DUR      = 900.0           # 15 minutes
BAR_S    = 60.0 / BPM * 4  # ~1.69s
BEAT_S   = 60.0 / BPM      # ~0.423s
STEP_S   = BAR_S / 16      # 16th note ~0.1056s
TOTAL    = int(DUR * SR)

# key = Am
ROOT     = 45              # A2
SCALE_AM = [45, 48, 50, 52, 53, 55, 57]  # A B C D Eb E F# (harmonic minor feel)

# chord voicings (MIDI)
CHORD_Am  = [45, 48, 52]   # A2 C3 E3
CHORD_Dm  = [50, 53, 57]   # D3 F3 A3
CHORD_F   = [41, 45, 48]   # F2 A2 C3
CHORD_G   = [43, 47, 50]   # G2 B2 D3
CHORD_Em  = [40, 43, 47]   # E2 G2 B2
CHORDS    = [CHORD_Am, CHORD_Dm, CHORD_F, CHORD_G]  # 4-bar loop

# ── sections (seconds) ────────────────────────────────────────────
# Gradual build → peak → dub strip → return → fadeout
S_INTRO      = (0.0,   90.0)    # 0:00 - 1:30  filtered pad + sequencer
S_FOUNDATION = (75.0,  180.0)   # 1:15 - 3:00  kick + hats + sub
S_GROOVE     = (165.0, 300.0)   # 2:45 - 5:00  full groove, bass, stabs
S_BUILD      = (285.0, 420.0)   # 4:45 - 7:00  whispers, intensity up
S_PEAK       = (405.0, 540.0)   # 6:45 - 9:00  everything maxed
S_DUB        = (525.0, 630.0)   # 8:45 - 10:30 dub house: delay wash
S_RETURN     = (615.0, 720.0)   # 10:15 - 12:00 groove returns
S_BREAKDOWN  = (705.0, 810.0)   # 11:45 - 13:30 pad + whispers
S_OUTRO      = (795.0, 900.0)   # 13:15 - 15:00 decay to nothing


def _bp(lo, hi, sr=SR, order=4):
    lo = max(lo, 20)
    hi = min(hi, sr // 2 - 100)
    if lo >= hi:
        lo = hi - 50
    return butter(order, [lo, hi], btype="bandpass", fs=sr, output="sos")


def _lp(cutoff, sr=SR, order=4):
    cutoff = min(cutoff, sr // 2 - 100)
    return butter(order, cutoff, btype="lowpass", fs=sr, output="sos")


# ── LAYER: DRUMS ──────────────────────────────────────────────────
def build_drum_events():
    """
    Relentless 4/4 kick, plate snare on 2&4, 16th hats with groove,
    occasional rim shots for indie feel.
    """
    events = []

    # 16-step velocity patterns
    #                   1  .  .  .  2  .  .  .  3  .  .  .  4  .  .  .
    PAT_KICK      = [127, 0, 0, 0,127, 0, 0, 0,127, 0, 0, 0,127, 0, 0, 0]
    PAT_SNARE     = [  0, 0, 0, 0,110, 0, 0, 0,  0, 0, 0, 0,110, 0, 0, 0]
    PAT_HAT_FULL  = [ 90, 0,60, 0, 80, 0,55, 0, 85, 0,60, 0, 80, 0,55,40]
    PAT_HAT_MIN   = [ 70, 0, 0, 0, 60, 0, 0, 0, 70, 0, 0, 0, 60, 0, 0, 0]
    PAT_OHH       = [  0, 0, 0, 0,  0, 0, 0,85,  0, 0, 0, 0,  0, 0, 0, 0]
    PAT_RIM       = [  0, 0, 0,70,  0, 0, 0, 0,  0, 0, 0, 0,  0, 0,65, 0]
    PAT_CLAP      = [  0, 0, 0, 0, 95, 0, 0, 0,  0, 0, 0, 0, 95, 0, 0, 0]

    # Stripped version for dub section
    PAT_DUB_KICK  = [110, 0, 0, 0,  0, 0, 0, 0,100, 0, 0, 0,  0, 0, 0, 0]
    PAT_DUB_RIM   = [  0, 0, 0, 0, 75, 0, 0, 0,  0, 0, 0,60,  0, 0, 0, 0]

    n_bars = int(DUR / BAR_S) + 1

    for bar in range(n_bars):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break

        # Section logic
        in_intro      = t_bar < S_FOUNDATION[0]
        in_foundation = S_FOUNDATION[0] <= t_bar < S_GROOVE[0]
        in_groove     = S_GROOVE[0] <= t_bar < S_DUB[0]
        in_dub        = S_DUB[0] <= t_bar < S_RETURN[0]
        in_return     = S_RETURN[0] <= t_bar < S_BREAKDOWN[0]
        in_breakdown  = S_BREAKDOWN[0] <= t_bar < S_OUTRO[0]
        in_outro      = t_bar >= S_OUTRO[0]

        for step in range(16):
            t = t_bar + step * STEP_S
            if t >= DUR:
                break

            # No drums in intro
            if in_intro:
                continue

            if in_dub:
                # Stripped dub pattern
                if PAT_DUB_KICK[step] > 0:
                    events.append((t, "kick", PAT_DUB_KICK[step]))
                if PAT_DUB_RIM[step] > 0:
                    events.append((t, "rim", PAT_DUB_RIM[step]))
                if PAT_HAT_MIN[step] > 0:
                    events.append((t, "hat_c", PAT_HAT_MIN[step]))
                continue

            if in_breakdown:
                # Sparse breakdown
                if step == 0 and bar % 2 == 0:
                    events.append((t, "kick", 80))
                if PAT_RIM[step] > 0 and bar % 2 == 1:
                    events.append((t, "rim", 50))
                continue

            if in_outro:
                # Fading out -- kick every other bar
                if step == 0 and bar % 4 == 0:
                    events.append((t, "kick", 60))
                continue

            # Foundation, groove, build, peak, return
            # Kick: always 4/4
            if PAT_KICK[step] > 0:
                events.append((t, "kick", PAT_KICK[step]))

            # Snare (plate reverbed later) or clap
            if in_groove or in_return:
                if PAT_SNARE[step] > 0:
                    events.append((t, "snare", PAT_SNARE[step]))
            elif t_bar >= S_BUILD[0]:
                # Use clap in build/peak for intensity
                if PAT_CLAP[step] > 0:
                    events.append((t, "clap", PAT_CLAP[step]))

            # Hats
            if in_foundation:
                if PAT_HAT_MIN[step] > 0:
                    events.append((t, "hat_c", PAT_HAT_MIN[step]))
            else:
                if PAT_HAT_FULL[step] > 0:
                    events.append((t, "hat_c", PAT_HAT_FULL[step]))
                if PAT_OHH[step] > 0:
                    events.append((t, "hat_o", PAT_OHH[step]))

            # Rim shots (indie touch)
            if (in_groove or in_return) and PAT_RIM[step] > 0:
                events.append((t, "rim", PAT_RIM[step]))

    return events


def build_drums(drum_events):
    """Render all drum events into stereo buffer."""
    print("  drums: rendering events...")
    buf = render_drums(drum_events, TOTAL, SR, stereo=True)

    # Apply plate reverb to snare/clap channel:
    # We apply light reverb to the full drum bus for cohesion
    # but keep it dry-sounding (indie aesthetic)
    buf_wet = apply_reverb(buf, SR, room_size=0.45, wet=0.12, damping=0.7)
    # Blend: mostly dry
    buf = buf * 0.85 + buf_wet * 0.15
    return buf.astype(np.float32)


# ── LAYER: SUB BASS (sidechained) ─────────────────────────────────
def build_sub_bass(drum_events):
    """
    Deep sine sub following chord root, sidechained to kick.
    """
    print("  sub bass...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    # Bass note per bar follows chord progression
    bass_notes = [45, 50, 41, 43]  # A2, D3, F2, G2

    n_bars = int(DUR / BAR_S) + 1
    for bar in range(n_bars):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break

        chord_idx = bar % 4
        midi_note = bass_notes[chord_idx]
        freq = midi_to_hz(midi_note)

        bar_n = int(BAR_S * SR)
        start = int(t_bar * SR)
        end = min(start + bar_n, TOTAL)
        n = end - start

        t = np.arange(n, dtype=np.float64) / SR
        # Pure sub sine + gentle second harmonic
        sub = np.sin(2 * np.pi * freq * t).astype(np.float32)
        sub += 0.15 * np.sin(2 * np.pi * freq * 2 * t).astype(np.float32)

        # Smooth bar-to-bar transition
        fade = min(int(0.01 * SR), n // 4)
        if fade > 0:
            sub[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            sub[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)

        buf[start:end] += sub[:n]

    # Sidechain ducking from kick events
    kick_times = [t for t, name, v in drum_events if name in ("kick", "k", "bd")]
    duck_env = np.ones(TOTAL, dtype=np.float32)
    duck_samples = int(0.08 * SR)  # 80ms duck

    for kt in kick_times:
        pos = int(kt * SR)
        end = min(pos + duck_samples, TOTAL)
        n = end - pos
        # Cosine recovery: 0 -> 1
        recovery = 0.5 * (1 - np.cos(np.pi * np.arange(n, dtype=np.float64) / n))
        duck_env[pos:end] = np.minimum(duck_env[pos:end], recovery.astype(np.float32))

    buf *= duck_env

    # Section envelope: sub enters in foundation, exits in outro
    env = make_section_envelope(
        TOTAL,
        [
            (S_FOUNDATION[0], S_DUB[0], 1.0),
            (S_DUB[0], S_DUB[1], 0.5),       # quieter in dub
            (S_RETURN[0], S_BREAKDOWN[1], 1.0),
        ],
        sr=SR, crossfade_bars=8, bpm=BPM,
    )
    buf *= env

    buf = lpf(buf, 120, sr=SR)
    stereo = mono_to_stereo(buf, pan=0.0)
    stereo = apply_compressor(stereo, SR, threshold_db=-10, ratio=3.0)
    return stereo.astype(np.float32)


# ── LAYER: SYNCOPATED ANALOG BASS ─────────────────────────────────
def build_analog_bass():
    """
    TB-303 style syncopated bassline. Syncopated 16th pattern with
    filter automation. Indie techno = less acid screech, more groove.
    """
    print("  analog bass...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    bass_notes = [45, 50, 41, 43]

    # Syncopated 16th pattern (velocity 0 = rest)
    #               1  .  .  .  2  .  .  .  3  .  .  .  4  .  .  .
    PAT_BASS_A = [100, 0, 0,80,  0, 0,90, 0,  0,70, 0, 0, 85, 0, 0,75]
    PAT_BASS_B = [100, 0,75, 0,  0,85, 0, 0, 90, 0, 0,70,  0, 0,80, 0]

    n_bars = int(DUR / BAR_S) + 1
    for bar in range(n_bars):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break

        chord_idx = bar % 4
        root = bass_notes[chord_idx]

        # Alternate patterns every 4 bars
        pat = PAT_BASS_A if (bar // 4) % 2 == 0 else PAT_BASS_B

        for step in range(16):
            vel = pat[step]
            if vel == 0:
                continue

            t = t_bar + step * STEP_S
            if t >= DUR:
                break

            # Note selection: mostly root, occasional 5th or octave
            note = root
            if step in (3, 9):
                note = root + 7  # 5th above
            elif step in (6, 14):
                note = root + 12  # octave up sometimes
                if bar % 3 != 0:
                    note = root  # but not too often

            dur_s = STEP_S * 0.85  # slightly shorter than step

            # Gentle filter settings (not too acid)
            t_progress = t / DUR
            cutoff_start = 600 + 400 * t_progress  # opens over time
            cutoff_end = 200 + 100 * t_progress

            note_buf = acid_bass_note(
                note, dur_s, SR,
                cutoff_start=int(cutoff_start),
                cutoff_end=int(cutoff_end),
                resonance_q=2.5,  # moderate resonance
                accent=(vel > 90),
            )

            pos = int(t * SR)
            end = min(pos + len(note_buf), TOTAL)
            n = end - pos
            buf[pos:end] += note_buf[:n] * (vel / 127.0) ** 1.3

    # Section envelope
    env = make_section_envelope(
        TOTAL,
        [
            (S_GROOVE[0], S_DUB[0], 1.0),
            (S_DUB[0], S_DUB[1], 0.3),       # very quiet in dub
            (S_RETURN[0], S_BREAKDOWN[0], 1.0),
        ],
        sr=SR, crossfade_bars=6, bpm=BPM,
    )
    buf *= env

    stereo = mono_to_stereo(buf, pan=-0.1)  # slightly left
    stereo = apply_compressor(stereo, SR, threshold_db=-8, ratio=3.0)
    return stereo.astype(np.float32)


# ── LAYER: PRICKLY SYNTH STABS ────────────────────────────────────
def build_stabs():
    """
    Short, sharp filtered square notes -- syncopated, prickly.
    Think minimal techno stabs: clicky, dry, slightly detuned.
    """
    print("  synth stabs...")
    buf_stereo = np.zeros((TOTAL, 2), dtype=np.float32)

    stab_chords = [
        [60, 64],     # C4 E4 (Am: minor third inversion)
        [62, 65],     # D4 F4
        [57, 60],     # A3 C4
        [59, 62],     # B3 D4
    ]

    # Syncopated stab pattern
    #              1  .  .  .  2  .  .  .  3  .  .  .  4  .  .  .
    PAT_STAB  = [  0, 0,90, 0,  0, 0, 0,85,  0,80, 0, 0,  0, 0,90, 0]

    n_bars = int(DUR / BAR_S) + 1
    for bar in range(n_bars):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break

        chord_idx = bar % 4
        notes = stab_chords[chord_idx]

        for step in range(16):
            vel = PAT_STAB[step]
            if vel == 0:
                continue

            t = t_bar + step * STEP_S
            if t >= DUR:
                break

            dur_s = 0.06  # very short stab

            stab = np.zeros(int(dur_s * SR), dtype=np.float32)
            for midi_n in notes:
                freq = midi_to_hz(midi_n)
                n = int(dur_s * SR)
                s = square_bl(freq, n, SR)
                # Sharp ADSR: instant attack, fast decay
                env = adsr(1, 30, -20, 10, dur_s, SR)
                min_n = min(len(s), len(env))
                stab[:min_n] += (s[:min_n] * env[:min_n]) * 0.4

            # Bandpass filter for prickly character
            sos = _bp(800, 6000, SR, order=2)
            stab = sosfilt(sos, stab).astype(np.float32)

            # Stereo placement: alternate L/R
            pan = -0.4 if step % 2 == 0 else 0.4
            stab_s = mono_to_stereo(stab, pan=pan)

            pos = int(t * SR)
            end = min(pos + stab_s.shape[0], TOTAL)
            n = end - pos
            if n > 0:
                gain = (vel / 127.0) ** 1.3
                buf_stereo[pos:end] += stab_s[:n] * gain

    # Section envelope
    env = make_section_envelope(
        TOTAL,
        [
            (S_GROOVE[0], S_DUB[0], 1.0),
            (S_DUB[0], S_DUB[1], 0.15),
            (S_RETURN[0], S_BREAKDOWN[0], 1.0),
        ],
        sr=SR, crossfade_bars=4, bpm=BPM,
    )
    apply_envelope_stereo(buf_stereo, env)

    # Light delay for space
    buf_stereo = apply_delay(buf_stereo, SR, delay_ms=int(BEAT_S * 750), feedback=0.2, wet=0.15)
    return buf_stereo.astype(np.float32)


# ── LAYER: FILTERED PAD BED ───────────────────────────────────────
def build_pad():
    """
    Wide supersaw pad, slowly evolving filter. Always present but
    very quiet, bed of warmth underneath everything.
    """
    print("  filtered pad...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    # Render pad per 4-bar chord cycle
    cycle_s = BAR_S * 4
    n_cycles = int(DUR / cycle_s) + 1

    for cy in range(n_cycles):
        t_start = cy * cycle_s
        if t_start >= DUR:
            break

        chord_idx = cy % 4
        chord = CHORDS[chord_idx]

        dur_s = min(cycle_s + 0.5, DUR - t_start)  # slight overlap
        n = int(dur_s * SR)

        pad_buf = np.zeros(n, dtype=np.float32)
        for midi_note in chord:
            p = pad_note(midi_note, dur_s, SR,
                         attack_ms=2000,
                         cutoff_hz=1800,
                         detune_cents=18.0,
                         n_voices=7)
            min_n = min(len(p), n)
            pad_buf[:min_n] += p[:min_n]
        pad_buf /= len(chord) ** 0.6

        # Slow filter sweep: opens and closes over cycle
        t_progress = t_start / DUR
        sweep_lo = 400 + 300 * t_progress
        sweep_hi = 2000 + 1000 * t_progress
        pad_buf = lpf_sweep(pad_buf, sweep_lo, sweep_hi, SR, segments=16)

        # Crossfade edges
        fade = min(int(1.5 * SR), n // 4)
        if fade > 0:
            pad_buf[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            pad_buf[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)

        pos = int(t_start * SR)
        end = min(pos + n, TOTAL)
        actual_n = end - pos
        buf[pos:end] += pad_buf[:actual_n]

    # Section envelope (always present, varying intensity)
    env = make_section_envelope(
        TOTAL,
        [
            (S_INTRO[0], S_INTRO[1], 0.6),
            (S_FOUNDATION[0], S_DUB[0], 0.8),
            (S_DUB[0], S_DUB[1], 1.0),        # prominent in dub section
            (S_RETURN[0], S_BREAKDOWN[0], 0.7),
            (S_BREAKDOWN[0], S_OUTRO[1], 1.0),  # prominent in breakdown/outro
        ],
        sr=SR, crossfade_bars=8, bpm=BPM,
    )
    buf *= env

    stereo = mono_to_stereo(buf, pan=0.0)
    stereo = apply_reverb(stereo, SR, room_size=0.75, wet=0.45, damping=0.3)
    stereo = apply_chorus(stereo, SR, rate_hz=0.15, depth=0.2, wet=0.3)
    return stereo.astype(np.float32)


# ── LAYER: BERLIN SEQUENCER PULSE ─────────────────────────────────
def build_sequencer():
    """
    Monotone 16th-note pulse. Classic Berlin school: repetitive,
    hypnotic, slightly filtered. Think Tangerine Dream meets techno.
    """
    print("  Berlin sequencer...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    # Sequence: 16th notes, repeating pattern on scale degrees
    # A3(57), C4(60), A3(57), E3(52), A3(57), C4(60), D4(62), C4(60)
    SEQ_NOTES = [57, 60, 57, 52, 57, 60, 62, 60,
                 57, 60, 57, 55, 57, 60, 64, 62]

    note_dur = STEP_S * 0.7  # slightly detached
    note_n = int(note_dur * SR)

    # Pre-compute envelope for efficiency
    env = adsr(2, 40, -12, 20, note_dur, SR)

    n_steps = int(DUR / STEP_S) + 1
    for si in range(n_steps):
        t = si * STEP_S
        if t >= DUR:
            break

        midi_note = SEQ_NOTES[si % 16]
        freq = midi_to_hz(midi_note)

        # Sawtooth oscillator with slight detune (analog imperfection)
        detune = 1.0 + 0.001 * np.sin(2 * np.pi * t * 0.07)
        osc = sawtooth_bl(freq * detune, note_n, SR)

        min_n = min(len(osc), len(env))
        note = (osc[:min_n] * env[:min_n]).astype(np.float32)

        # Time-varying filter (opens during build/peak, closes during dub)
        t_ratio = t / DUR
        if S_DUB[0] <= t < S_DUB[1]:
            cutoff = 800  # muffled in dub
        elif S_PEAK[0] <= t < S_PEAK[1]:
            cutoff = 4000  # bright at peak
        else:
            cutoff = 1200 + 1500 * t_ratio

        note = lpf(note, cutoff, sr=SR)

        pos = int(t * SR)
        end = min(pos + len(note), TOTAL)
        n = end - pos
        if n > 0:
            # Velocity variation for groove
            vel = 0.7 + 0.3 * abs(np.sin(si * 0.7))
            buf[pos:end] += note[:n] * vel * 0.4

    # Section envelope
    env_sec = make_section_envelope(
        TOTAL,
        [
            (S_INTRO[0], S_INTRO[1], 0.5),     # faint in intro
            (S_FOUNDATION[0], S_DUB[0], 0.8),
            (S_DUB[0], S_DUB[1], 0.4),          # background in dub
            (S_RETURN[0], S_OUTRO[0], 0.9),
            (S_OUTRO[0], S_OUTRO[1], 0.6),
        ],
        sr=SR, crossfade_bars=6, bpm=BPM,
    )
    buf *= env_sec

    stereo = mono_to_stereo(buf, pan=0.15)  # slightly right
    stereo = apply_delay(stereo, SR, delay_ms=int(STEP_S * 1000 * 3),
                         feedback=0.25, wet=0.2)
    return stereo.astype(np.float32)


# ── LAYER: BREATHY WHISPERS ───────────────────────────────────────
def build_whispers():
    """
    Synthesized breathy whispers: filtered noise shaped through
    formant bands. Very quiet, atmospheric, stereo movement.
    Morphs slowly between vowel shapes.
    """
    print("  breathy whispers...")
    buf_stereo = np.zeros((TOTAL, 2), dtype=np.float32)

    rng = np.random.RandomState(42)

    # Formant frequencies (approximate female whisper)
    FORMANTS = {
        "a": [(800, 150), (1200, 100), (2800, 200)],
        "e": [(400, 100), (2000, 150), (2800, 200)],
        "i": [(350, 80),  (2300, 150), (3000, 200)],
        "u": [(325, 80),  (700, 100),  (2500, 200)],
    }
    vowels = list(FORMANTS.keys())

    # Whisper events: long breathy sounds at random times
    n_whispers = int(DUR / 8)  # roughly one every 8 seconds
    whisper_times = np.sort(rng.uniform(S_BUILD[0], S_OUTRO[1] - 5, n_whispers))

    for wt in whisper_times:
        w_dur = rng.uniform(2.0, 5.0)
        w_n = int(w_dur * SR)
        if w_n < 100:
            continue

        # Base: bandpass noise (whisper spectrum)
        noise = rng.randn(w_n).astype(np.float32)

        # Choose start and end vowel for morphing
        v1 = FORMANTS[vowels[rng.randint(0, len(vowels))]]
        v2 = FORMANTS[vowels[rng.randint(0, len(vowels))]]

        whisper = np.zeros(w_n, dtype=np.float32)

        # Apply formant filters (3 formants, morphing)
        n_segments = 8
        seg_len = w_n // n_segments
        for seg in range(n_segments):
            start = seg * seg_len
            end = min(start + seg_len, w_n)
            morph = seg / max(n_segments - 1, 1)

            seg_buf = noise[start:end].copy()
            formant_out = np.zeros(end - start, dtype=np.float32)

            for fi in range(3):
                freq1, bw1 = v1[fi]
                freq2, bw2 = v2[fi]
                freq = freq1 + (freq2 - freq1) * morph
                bw = bw1 + (bw2 - bw1) * morph

                lo = max(20, freq - bw)
                hi = min(SR // 2 - 100, freq + bw)
                if lo >= hi:
                    continue
                sos = _bp(lo, hi, SR, order=2)
                formant_out += sosfilt(sos, seg_buf).astype(np.float32)

            whisper[start:end] = formant_out

        # Envelope: very slow fade in/out
        env_w = np.ones(w_n, dtype=np.float32)
        fade = int(w_dur * 0.3 * SR)
        fade = min(fade, w_n // 3)
        if fade > 0:
            env_w[:fade] = 0.5 * (1 - np.cos(np.pi * np.arange(fade) / fade))
            env_w[-fade:] = 0.5 * (1 + np.cos(np.pi * np.arange(fade) / fade))
        whisper *= env_w

        # Stereo placement: slow drift
        pan = rng.uniform(-0.6, 0.6)
        w_stereo = mono_to_stereo(whisper, pan=pan)

        pos = int(wt * SR)
        end_pos = min(pos + w_n, TOTAL)
        actual_n = end_pos - pos
        if actual_n > 0:
            buf_stereo[pos:end_pos] += w_stereo[:actual_n] * 0.5

    # Section envelope: only build through outro
    env = make_section_envelope(
        TOTAL,
        [
            (S_BUILD[0], S_DUB[0], 0.6),
            (S_DUB[0], S_DUB[1], 0.8),
            (S_RETURN[0], S_BREAKDOWN[0], 0.5),
            (S_BREAKDOWN[0], S_OUTRO[1], 1.0),
        ],
        sr=SR, crossfade_bars=8, bpm=BPM,
    )
    apply_envelope_stereo(buf_stereo, env)

    buf_stereo = apply_reverb(buf_stereo, SR, room_size=0.9, wet=0.6, damping=0.2)
    return buf_stereo.astype(np.float32)


# ── LAYER: LO-FI TEXTURE ──────────────────────────────────────────
def build_texture():
    """
    Subtle lo-fi atmosphere: tape hiss, vinyl crackle sim,
    and wash of reverbed noise. Very quiet underpinning.
    """
    print("  lo-fi texture...")
    rng = np.random.RandomState(77)

    # Tape hiss: gentle highpass noise
    hiss = rng.randn(TOTAL).astype(np.float32) * 0.03
    hiss = hpf(hiss, 4000, SR).astype(np.float32)

    # Vinyl crackle: sparse random clicks
    crackle = np.zeros(TOTAL, dtype=np.float32)
    n_clicks = int(DUR * 3)  # ~3 clicks per second
    positions = rng.randint(0, TOTAL - 100, n_clicks)
    for pos in positions:
        click_len = rng.randint(5, 30)
        end = min(pos + click_len, TOTAL)
        crackle[pos:end] = rng.randn(end - pos) * rng.uniform(0.005, 0.02)

    texture = hiss + crackle

    # Slow amplitude modulation
    t = np.arange(TOTAL, dtype=np.float64) / SR
    mod = 0.6 + 0.4 * np.sin(2 * np.pi * t / 30.0)  # 30s period
    texture *= mod.astype(np.float32)

    # Section envelope (always present, very subtle)
    env = make_section_envelope(
        TOTAL,
        [
            (0, DUR, 0.5),
        ],
        sr=SR, crossfade_bars=16, bpm=BPM,
    )
    texture *= env

    stereo = mono_to_stereo(texture, pan=0.0)
    # Very wide stereo via chorus
    stereo = apply_chorus(stereo, SR, rate_hz=0.08, depth=0.15, wet=0.5)
    return stereo.astype(np.float32)


# ── LAYER: DUB DELAY WASH ─────────────────────────────────────────
def build_dub_fx():
    """
    Extra heavy delay effect that blooms during the dub section.
    Uses filtered noise bursts that feed into long delay.
    """
    print("  dub delay FX...")
    rng = np.random.RandomState(99)
    buf = np.zeros(TOTAL, dtype=np.float32)

    # Sparse filtered hits during dub section
    n_hits = 25
    hit_times = np.sort(rng.uniform(S_DUB[0], S_DUB[1] - 2, n_hits))

    for ht in hit_times:
        dur = rng.uniform(0.05, 0.15)
        n = int(dur * SR)
        freq = rng.uniform(400, 2000)
        hit = sine_wave(freq, n, SR) * adsr(1, 20, -15, 15, dur, SR)[:n]
        hit *= rng.uniform(0.1, 0.3)

        pos = int(ht * SR)
        end = min(pos + n, TOTAL)
        actual_n = end - pos
        if actual_n > 0:
            buf[pos:end] += hit[:actual_n]

    # Heavy dub delay
    stereo = mono_to_stereo(buf, pan=0.2)
    stereo = apply_delay(stereo, SR, delay_ms=int(BEAT_S * 1500),
                         feedback=0.55, wet=0.7)
    stereo = apply_reverb(stereo, SR, room_size=0.85, wet=0.5, damping=0.3)

    # Only active during/after dub
    env = make_section_envelope(
        TOTAL,
        [(S_DUB[0] - 10, S_RETURN[0] + 30, 1.0)],
        sr=SR, crossfade_bars=8, bpm=BPM,
    )
    apply_envelope_stereo(stereo, env)

    return stereo.astype(np.float32)


# ── MASTER MIX ─────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print(f"Midnight Loop — {int(DUR//60)}:{int(DUR%60):02d}, {BPM} BPM, Am")
    print(f"  {TOTAL:,} samples @ {SR} Hz")

    # Build all layers
    drum_events = build_drum_events()
    drums    = build_drums(drum_events)
    sub      = build_sub_bass(drum_events)
    bass     = build_analog_bass()
    stabs    = build_stabs()
    pad      = build_pad()
    seq      = build_sequencer()
    whispers = build_whispers()
    texture  = build_texture()
    dub_fx   = build_dub_fx()

    print("  mixing...")

    # Mix with gain structure
    mix = np.zeros((TOTAL, 2), dtype=np.float32)
    mix += drums    * 0.80
    mix += sub      * 0.60
    mix += bass     * 0.55
    mix += stabs    * 0.45
    mix += pad      * 0.35
    mix += seq      * 0.40
    mix += whispers * 0.30
    mix += texture  * 0.15
    mix += dub_fx   * 0.35

    # Global fade in/out
    fade_in_n = int(8.0 * SR)   # 8s fade in
    fade_out_n = int(15.0 * SR)  # 15s fade out
    mix[:fade_in_n] *= np.linspace(0, 1, fade_in_n, dtype=np.float32)[:, None]
    mix[-fade_out_n:] *= np.linspace(1, 0, fade_out_n, dtype=np.float32)[:, None]

    # Safety clip
    mix = np.clip(mix, -3.0, 3.0)

    # Master chain
    print("  mastering...")
    mix = master_chain(mix, SR)

    # Write
    out_wav = "/opt/autodj-mixer/output/midnight_loop.wav"
    out_mp3 = "/opt/autodj-mixer/output/midnight_loop.mp3"
    os.makedirs(os.path.dirname(out_wav), exist_ok=True)

    print(f"  writing WAV...")
    sf.write(out_wav, mix, SR)

    print(f"  encoding MP3...")
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 256k "{out_mp3}" 2>/dev/null')

    elapsed = time.time() - t0
    sz = os.path.getsize(out_mp3) / 1024 / 1024
    print(f"  done in {elapsed:.1f}s — {sz:.1f} MB")
    print(f"  {out_mp3}")


if __name__ == "__main__":
    main()
