#!/usr/bin/env python3
"""
render_dark_cosmic.py — "Void Protocol"
Dark cosmic techno for the dancefloor. 8 minutes, 134 BPM, D minor.

Architecture — EPISODIC + SMOOTH:
  Each layer is rendered as a full-length audio buffer.
  Section envelopes use cosine crossfades (4-bar = ~7s).
  Layers enter/exit asynchronously — no element cuts simultaneously.
  No hard-edge sections, everything bleeds into the next.

Layers:
  1. Drums (909 synthesis): kick, snare, hat, clap, rim
  2. Sub bass: pure sine, sidechain-ducked
  3. Acid bass (303): detuned sawtooth + resonant filter sweep
  4. Dark pad: supersaw, slow attack, heavily reverbed
  5. Lead arp: square wave arpeggios in Dm
  6. Cosmic texture: pitch-shifted noise + reverb (space ambience)
  7. Noise riser/downlifter at transition points

Sections (smooth, 4-bar crossfades):
  Intro        0:00 - 1:00   texture + kick only
  Tension      1:00 - 2:00   +sub bass + filtered acid
  Pre-drop     2:00 - 2:30   +all drums, filter sweep open
  Drop A       2:30 - 4:30   full arrangement
  Breakdown    4:30 - 5:30   stripped: pad + texture + kick
  Build        5:30 - 6:00   gradual return
  Drop B       6:00 - 7:30   peak energy, +1 semitone
  Outro        7:30 - 8:00   dissolve
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
# Запустить всё-таки:  AUTODJ_ALLOW_LEGACY=1 python3 render_dark_cosmic.py
# ═══════════════════════════════════════════════════════════════════════════
import os as _os, sys as _sys
if __name__ == "__main__" and not _os.environ.get("AUTODJ_ALLOW_LEGACY"):
    print(__doc__ or "")
    print("\n⚠️  УСТАРЕЛО: render_dark_cosmic.py не использует улучшения P82-P88 "
          "(мотив, аранжировка, уникальная гармония).")
    print("   Рендерь через:  python3 render_track.py <жанр>")
    print("   Форс:           AUTODJ_ALLOW_LEGACY=1 python3 render_dark_cosmic.py\n")
    _sys.exit(3)


import sys, os, logging, numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt
sys.path.insert(0, "/opt/autodj-mixer")

from autodj.generate.synth909 import render_drums
from autodj.generate.synthcore import (
    midi_to_hz, sawtooth_bl, square_bl, supersaw, sine_wave,
    adsr, lpf, hpf, lpf_sweep, acid_bass_note, pad_note,
    apply_reverb, apply_delay, apply_chorus, apply_compressor,
    make_section_envelope, mono_to_stereo, apply_envelope_stereo,
    mix_into, master_chain, normalize_master
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("dark_cosmic")

SR = 44100
BPM = 134.0
DUR = 480.0          # 8 minutes
BAR_S = 60 / BPM * 4
BEAT_S = 60 / BPM
STEP_S = BAR_S / 16
TOTAL = int(DUR * SR)

# Section boundaries
S_INTRO    = (0.0,   60.0)
S_TENSION  = (50.0,  120.0)   # overlaps intro by 10s
S_PREDROP  = (112.0, 150.0)
S_DROPA    = (142.0, 270.0)   # overlaps predrop 8s
S_BREAK    = (262.0, 330.0)
S_BUILD    = (322.0, 360.0)
S_DROPB    = (352.0, 450.0)   # overlaps build
S_OUTRO    = (442.0, 480.0)

# D minor key notes (MIDI)
# Dm: D3=50 E3=52 F3=53 G3=55 A3=57 Bb3=58 C4=60 D4=62
DM_SCALE  = [50, 52, 53, 55, 57, 58, 60, 62, 64, 65, 67, 69, 70, 72]
DM_CHORD  = [50, 53, 57]       # Dm root position (D F A)
AM_CHORD  = [45, 48, 52]       # Am
GM_CHORD  = [43, 47, 50]       # Gm
BB_CHORD  = [46, 50, 53]       # Bb
CHORD_PROG = [DM_CHORD, GM_CHORD, BB_CHORD, AM_CHORD]  # 4-bar cycle

# Acid bass sequence (16-step, D minor, 303 style)
ACID_SEQ = [
    50, 0,  50, 0,  53, 0,  50, 0,
    55, 0,  55, 53, 0,  50, 0,  48,
]  # D - D - F - D | G - G F - D - C#


# ---------------------------------------------------------------------------
# 1. DRUM LAYER
# ---------------------------------------------------------------------------
def build_drum_events():
    events = []
    total_beats = int(DUR / BEAT_S) + 1
    total_steps = int(DUR / STEP_S) + 4

    for beat in range(total_beats):
        t = beat * BEAT_S
        if t >= DUR:
            break
        beat_in_bar = beat % 4

        in_intro   = S_INTRO[0] <= t < S_INTRO[1]
        in_tension = S_TENSION[0] <= t < S_TENSION[1]
        in_predrop = S_PREDROP[0] <= t < S_PREDROP[1]
        in_dropa   = S_DROPA[0] <= t < S_DROPA[1]
        in_break   = S_BREAK[0] <= t < S_BREAK[1]
        in_build   = S_BUILD[0] <= t < S_BUILD[1]
        in_dropb   = S_DROPB[0] <= t < S_DROPB[1]
        in_outro   = S_OUTRO[0] <= t < S_OUTRO[1]

        # ---- KICK: 4-on-the-floor, from tension onwards ----
        kick_active = (not in_intro) and t < S_OUTRO[1] - 4.0
        if in_break:
            # Half-time kick in break: beats 1 and 3 only
            kick_active = beat_in_bar in (0, 2)

        if kick_active:
            vel = 127
            if in_tension:
                # Gradual fade-in of kick
                p = (t - S_TENSION[0]) / (S_TENSION[1] - S_TENSION[0])
                vel = int(60 + p * 67)
            elif in_outro:
                p = (t - S_OUTRO[0]) / (S_OUTRO[1] - S_OUTRO[0])
                vel = max(50, int(127 * (1 - p)))
            events.append((t, "kick", vel))

        # ---- SNARE: beats 2 & 4 ----
        snare_active = in_dropa or in_predrop or in_dropb or in_build
        if snare_active and beat_in_bar in (1, 3):
            vel = 110 if in_dropa or in_dropb else 80
            events.append((t, "snare", vel))

        # ---- CLAP: on snare hits in Drop B for energy ----
        if in_dropb and beat_in_bar in (1, 3):
            events.append((t + 0.004, "clap", 90))

        # ---- RIM: in breakdown on offbeats ----
        if in_break and beat_in_bar in (0, 2):
            events.append((t + BEAT_S * 0.5, "rim", 80))

    # ---- HI-HAT: 16th notes ----
    for step in range(total_steps):
        t = step * STEP_S
        if t >= DUR:
            break

        in_dropa  = S_DROPA[0] <= t < S_DROPA[1]
        in_predrop = S_PREDROP[0] <= t < S_PREDROP[1]
        in_dropb  = S_DROPB[0] <= t < S_DROPB[1]
        in_build  = S_BUILD[0] <= t < S_BUILD[1]
        in_tension = S_TENSION[0] <= t < S_TENSION[1]

        if in_dropa or in_dropb:
            # 16th hats; open on every 4th offbeat
            step_in_bar = step % 16
            if step_in_bar % 2 == 0:
                events.append((t, "hat_c", 80))
            else:
                hat = "hat_o" if step_in_bar in (7, 15) else "hat_c"
                vel = 95 if hat == "hat_o" else 65
                events.append((t, hat, vel))
        elif in_predrop or in_build:
            # 8th hats only
            if step % 2 == 0:
                events.append((t, "hat_c", 70))
        elif in_tension:
            # sparse: every 4 steps
            if step % 4 == 0:
                events.append((t, "hat_c", 50))

    return events


# ---------------------------------------------------------------------------
# 2. SUB BASS LAYER  (pure sine, sidechain target)
# ---------------------------------------------------------------------------
def build_sub_bass(drum_events):
    """Pure sine sub bass following chord progression."""
    log.info("  Sub bass...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    # Section envelope: active from tension drop
    active_secs = [
        (S_TENSION[0], S_BREAK[0],  1.0),
        (S_BUILD[0],   S_OUTRO[1],  0.9),
    ]
    sec_env = make_section_envelope(TOTAL, active_secs, SR, crossfade_bars=4, bpm=BPM)

    # One note per bar, following chord roots
    bar_count = int(DUR / BAR_S) + 2
    for bar in range(bar_count):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break
        chord = CHORD_PROG[bar % len(CHORD_PROG)]
        root_midi = chord[0]

        # Drop B: shift up 2 semitones
        if S_DROPB[0] <= t_bar:
            root_midi += 2

        freq = midi_to_hz(root_midi - 12)  # down octave = sub

        note_dur = BAR_S * 0.95
        n_note = int(note_dur * SR)
        t_arr = np.arange(n_note, dtype=np.float64) / SR
        tone = np.sin(2 * np.pi * freq * t_arr)

        # Sub envelope: fast attack, sustain, fast release
        env = adsr(attack_ms=5, decay_ms=50, sustain_db=-2,
                   release_ms=40, dur_s=note_dur, sr=SR)
        tone = (tone * env).astype(np.float32)

        start = int(t_bar * SR)
        end = min(start + n_note, TOTAL)
        buf[start:end] += tone[:end - start]

    # Apply section envelope
    buf *= sec_env

    # Sidechain: duck on kick hits
    for ev in drum_events:
        if ev[1] == "kick":
            s = int(ev[0] * SR)
            r_s = int(0.12 * SR)  # 120ms recovery
            end = min(s + r_s, TOTAL)
            n = end - s
            if n > 0:
                recovery = 0.15 + 0.85 * 0.5 * (1 - np.cos(np.pi * np.arange(n) / n))
                buf[s:end] *= recovery.astype(np.float32)

    stereo = mono_to_stereo(buf, pan=0.0)
    return apply_compressor(stereo, SR, threshold_db=-8, ratio=6, attack_ms=2, release_ms=80)


# ---------------------------------------------------------------------------
# 3. ACID BASS (303-style)
# ---------------------------------------------------------------------------
def build_acid_bass():
    """303 acid line: 16-step sequencer, filter sweeps over sections."""
    log.info("  Acid bass...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    # Section envelope
    active_secs = [
        (S_TENSION[0] + 8, S_BREAK[0],    1.0),
        (S_BUILD[0],       S_OUTRO[0],    0.85),
    ]
    sec_env = make_section_envelope(TOTAL, active_secs, SR, crossfade_bars=4, bpm=BPM)

    total_steps = int(DUR / STEP_S) + 4
    seq_len = len(ACID_SEQ)

    # Filter cutoff: closed in early sections, open in drops
    def cutoff_at(t):
        if t < S_PREDROP[0]:
            p = max(0, (t - S_TENSION[0]) / (S_PREDROP[0] - S_TENSION[0]))
            return 200 + p * 600
        if t < S_DROPA[1]:
            return 1200
        if S_BREAK[0] <= t < S_BUILD[1]:
            return 400
        if S_DROPB[0] <= t:
            return 1800
        return 800

    prev_note = None
    for step in range(total_steps):
        t = step * STEP_S
        if t >= DUR:
            break

        note = ACID_SEQ[step % seq_len]
        if note == 0:
            continue

        # Drop B semitone shift
        if S_DROPB[0] <= t:
            note += 2

        accent = (step % 8 == 0)
        slide = (prev_note is not None and abs(note - prev_note) <= 2)

        dur = STEP_S * 0.85 if not slide else STEP_S * 1.05
        cutoff = cutoff_at(t)

        tone = acid_bass_note(note, dur, SR,
                              cutoff_start=cutoff * 2.5,
                              cutoff_end=cutoff * 0.4,
                              accent=accent)

        start = int(t * SR)
        end = min(start + len(tone), TOTAL)
        buf[start:end] += tone[:end - start]
        prev_note = note

    buf *= sec_env

    # Subtle distortion for grit
    buf = np.tanh(buf * 1.5) / 1.5

    stereo = mono_to_stereo(buf, pan=-0.05)
    return apply_compressor(stereo, SR, threshold_db=-10, ratio=4, attack_ms=3, release_ms=60)


# ---------------------------------------------------------------------------
# 4. DARK PAD (supersaw, heavily reverbed)
# ---------------------------------------------------------------------------
def build_dark_pad():
    """Supersaw pad, 1 chord per 2 bars, very slow attack, hall reverb."""
    log.info("  Dark pad (slow, ~2min render)...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    active_secs = [
        (0.0,          S_DROPA[1],   1.0),
        (S_BREAK[0],   S_OUTRO[1],   0.9),
    ]
    sec_env = make_section_envelope(TOTAL, active_secs, SR, crossfade_bars=8, bpm=BPM)

    # Render one chord per 2 bars
    chord_dur = BAR_S * 2 * 0.98
    chord_count = int(DUR / (BAR_S * 2)) + 2

    for i in range(chord_count):
        t_chord = i * BAR_S * 2
        if t_chord >= DUR:
            break
        chord = CHORD_PROG[(i // 1) % len(CHORD_PROG)]

        # Drop B shift
        shift = 2 if S_DROPB[0] <= t_chord else 0
        notes = [n + shift for n in chord]

        # Supersaw chord
        n_samples = int(chord_dur * SR)
        chord_buf = np.zeros(n_samples, dtype=np.float32)

        for note in notes:
            voice = pad_note(note, chord_dur, SR,
                             attack_ms=1200, cutoff_hz=1800,
                             detune_cents=14.0, n_voices=7)
            chord_buf[:len(voice)] += voice[:n_samples]

        # Normalize chord
        peak = np.abs(chord_buf).max()
        if peak > 0:
            chord_buf /= peak * 1.5

        start = int(t_chord * SR)
        end = min(start + n_samples, TOTAL)
        buf[start:end] += chord_buf[:end - start]

    buf *= sec_env

    # Hall reverb: long tail = cosmic space
    stereo = mono_to_stereo(buf, pan=0.0)
    stereo = apply_reverb(stereo, SR, room_size=0.85, wet=0.5, damping=0.3)
    stereo = apply_chorus(stereo, SR, rate_hz=0.3, depth=0.3, wet=0.35)

    return stereo


# ---------------------------------------------------------------------------
# 5. LEAD ARP (dark melodic hook in Dm)
# ---------------------------------------------------------------------------
def build_lead_arp():
    """
    Square wave arpeggio, 8th-note triplets over Dm scale.
    Active in drops only.
    """
    log.info("  Lead arp...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    active_secs = [
        (S_DROPA[0] + 16,  S_DROPA[1],   1.0),
        (S_BUILD[0] + 4,   S_DROPB[1],   1.0),
    ]
    sec_env = make_section_envelope(TOTAL, active_secs, SR, crossfade_bars=4, bpm=BPM)

    # Melodic pattern in Dm — dark, minor feel
    # Pattern: 8-step, uses scale degrees
    ARP_PATTERN = [62, 60, 57, 55, 53, 50, 53, 55]  # D4 C4 A3 G3 F3 D3 F3 G3
    step_dur = BEAT_S / 2  # 8th notes
    total_arp_steps = int(DUR / step_dur) + 4

    for step in range(total_arp_steps):
        t = step * step_dur
        if t >= DUR:
            break

        # Active check via sec_env (sampled)
        s_idx = min(int(t * SR), TOTAL - 1)
        if sec_env[s_idx] < 0.01:
            continue

        note = ARP_PATTERN[step % len(ARP_PATTERN)]
        # Drop B shift
        if S_DROPB[0] <= t:
            note += 2

        freq = midi_to_hz(note)
        dur_s = step_dur * 0.7
        n = int(dur_s * SR)

        osc = square_bl(freq, n, SR, n_harmonics=min(20, int(SR / (2 * freq))))
        env = adsr(attack_ms=3, decay_ms=60, sustain_db=-6,
                   release_ms=20, dur_s=dur_s, sr=SR)
        tone = (osc * env).astype(np.float32)

        gain = sec_env[s_idx]
        start = int(t * SR)
        end = min(start + n, TOTAL)
        buf[start:end] += tone[:end - start] * gain

    # Add delay (8th-note sync = 60/BPM/2 * 1000 ms)
    delay_ms = (BEAT_S / 2) * 1000
    stereo = mono_to_stereo(buf, pan=0.15)
    stereo = apply_delay(stereo, SR, delay_ms=delay_ms, feedback=0.4, wet=0.3)
    stereo = apply_reverb(stereo, SR, room_size=0.4, wet=0.2)

    return stereo


# ---------------------------------------------------------------------------
# 6. COSMIC TEXTURE (pitched noise + ambience, stereo rotation)
# ---------------------------------------------------------------------------
def build_cosmic_texture():
    """
    Layered cosmic ambience:
    - Low rumble + drone (tonal D1)
    - Wind: slow-LFO bandpass noise (period 8-25s), very smooth attack/decay
    - Stars shimmer: high-frequency bandpass, gentle
    - Stereo rotation: slow LFO pans sound right→left (period ~22s, like head turning)
    - All envelopes: 15-20s fades, smooth cosine shapes
    """
    log.info("  Cosmic texture...")
    n = TOTAL
    t_arr = np.arange(n, dtype=np.float64) / SR

    # ---- Layer 1: sub-low rumble 30-100 Hz ----
    noise1 = np.random.randn(n).astype(np.float32)
    sos_lo = butter(4, [30, 100], btype='bandpass', fs=SR, output='sos')
    lo_rumble = sosfilt(sos_lo, noise1).astype(np.float32)

    # ---- Layer 2: tonal D1 drone ----
    drone_freq = midi_to_hz(26)  # D1 ≈ 36.7 Hz
    drone = (0.25 * np.sin(2 * np.pi * drone_freq * t_arr) +
             0.12 * np.sin(2 * np.pi * drone_freq * 2 * t_arr) +
             0.06 * np.sin(2 * np.pi * drone_freq * 3 * t_arr)).astype(np.float32)

    # ---- Layer 3: wind — slow amplitude LFO on LP noise ----
    # Wind = 80-600 Hz noise with very slow envelope cycles
    noise_wind = np.random.randn(n).astype(np.float32)
    sos_wind = butter(4, [80, 600], btype='bandpass', fs=SR, output='sos')
    wind_raw = sosfilt(sos_wind, noise_wind).astype(np.float32)

    # Wind LFO envelope: multiple overlapping sine cycles, period 8-25s
    # Each "gust" is independent so they feel organic
    wind_env = np.zeros(n, dtype=np.float32)
    for period_s, amp, offset_s in [
        (18.0, 0.7, 0.0),
        (11.0, 0.5, 7.5),
        (25.0, 0.4, 3.0),
        (14.0, 0.3, 20.0),
    ]:
        period_n = period_s * SR
        offset_n = offset_s * SR
        lfo = 0.5 * (1 - np.cos(2 * np.pi * (t_arr - offset_s) / period_s))
        lfo = np.clip(lfo, 0, 1)
        wind_env += amp * lfo.astype(np.float32)

    wind_env = np.clip(wind_env / wind_env.max(), 0, 1)
    wind = wind_raw * wind_env * 0.5

    # ---- Layer 4: high stars shimmer 6000-12000 Hz ----
    noise4 = np.random.randn(n).astype(np.float32)
    hi_cut = min(12000, SR // 2 - 100)
    sos_hi = butter(4, [6000, hi_cut], btype='bandpass', fs=SR, output='sos')
    stars = sosfilt(sos_hi, noise4).astype(np.float32)

    # Stars: very quiet, slow gentle twinkling LFO
    stars_lfo = 0.5 + 0.5 * np.sin(2 * np.pi * t_arr / 7.3).astype(np.float32)
    stars = stars * stars_lfo * 0.06

    # ---- Mix mono signal ----
    mono = (lo_rumble * 0.28 +
            drone    * 0.40 +
            wind     * 0.55 +
            stars    * 1.0).astype(np.float32)

    # ---- Global amplitude envelope: 18s fade-in, 18s fade-out ----
    global_env = np.ones(n, dtype=np.float32)
    fade_in_n = int(18 * SR)
    global_env[:fade_in_n] = 0.5 * (1 - np.cos(np.pi * np.arange(fade_in_n) / fade_in_n))
    fade_out_n = int(18 * SR)
    fo_ramp = 0.5 * (1 + np.cos(np.pi * np.arange(fade_out_n) / fade_out_n))
    global_env[-fade_out_n:] = fo_ramp.astype(np.float32)
    mono *= global_env

    # ---- Stereo rotation: LFO pan Right → Left, period 22s ----
    # pan = sin(t/period * 2π), slow positive→negative = R→L
    pan_lfo = np.sin(2 * np.pi * t_arr / 22.0).astype(np.float32)  # -1..+1
    # Smooth with a 3s rolling mean (approx: just use LFO directly, it's already smooth)

    # Convert pan LFO to L/R gains (constant power panning)
    # When pan = +1: R louder, L quieter. When pan = -1: L louder
    pan_l = np.sqrt(0.5 * (1 - pan_lfo))
    pan_r = np.sqrt(0.5 * (1 + pan_lfo))

    stereo = np.stack([mono * pan_l, mono * pan_r], axis=1).astype(np.float32)

    # Hall reverb — very long tail for cosmic feel
    stereo = apply_reverb(stereo, SR, room_size=0.92, wet=0.55, damping=0.15)

    return stereo


# ---------------------------------------------------------------------------
# 7. NOISE RISER / DOWNLIFTER at transitions
# ---------------------------------------------------------------------------
def build_risers():
    """White noise sweeps at key transition points."""
    buf = np.zeros((TOTAL, 2), dtype=np.float32)

    transitions = [
        (S_PREDROP[0], "up"),     # before drop A
        (S_DROPA[1] - 2, "down"), # before breakdown
        (S_BUILD[0], "up"),       # rebuild
        (S_DROPB[0] - 2, "up"),  # before drop B
    ]

    for (t_center, direction) in transitions:
        riser_dur = 4.0  # 4 second riser
        if direction == "up":
            t_start = t_center - riser_dur
            f_start, f_end = 100, 8000
        else:
            t_start = t_center
            f_start, f_end = 8000, 80

        if t_start < 0:
            continue

        n_riser = int(riser_dur * SR)
        noise = np.random.randn(n_riser).astype(np.float32)

        # Sweep filter
        segments = 40
        seg_len = n_riser // segments
        swept = np.zeros(n_riser, dtype=np.float32)
        for i in range(segments):
            p = i / segments
            cutoff = f_start * (f_end / f_start) ** p
            cutoff = min(max(cutoff, 20), SR // 2 - 100)
            sos = butter(4, cutoff, btype='lowpass', fs=SR, output='sos')
            s = i * seg_len
            e = s + seg_len if i < segments - 1 else n_riser
            swept[s:e] = sosfilt(sos, noise[s:e])

        # Amplitude envelope — cosine for smooth entry/exit
        t_riser = np.arange(n_riser, dtype=np.float32) / n_riser
        if direction == "up":
            amp_env = 0.45 * (1 - np.cos(np.pi * t_riser))  # 0→0.9 cosine
        else:
            amp_env = 0.45 * (1 + np.cos(np.pi * t_riser))  # 0.9→0 cosine

        swept *= amp_env
        s_start = int(t_start * SR)
        s_end = min(s_start + n_riser, TOTAL)
        seg_n = s_end - s_start

        buf[s_start:s_end, 0] += swept[:seg_n]
        buf[s_start:s_end, 1] += swept[:seg_n]

    return buf


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    log.info(f"Void Protocol | BPM={BPM} | Dm | {DUR:.0f}s (8:00)")
    os.makedirs("/tmp", exist_ok=True)

    log.info("Building drum events...")
    drum_events = build_drum_events()
    log.info(f"  {len(drum_events)} drum hits")

    log.info("Rendering 909 drums...")
    drum_buf = render_drums(drum_events, TOTAL, SR, stereo=True)
    log.info(f"  drums peak={np.abs(drum_buf).max():.3f}")

    # Compress drums
    drum_buf = apply_compressor(drum_buf, SR, threshold_db=-10, ratio=4,
                                attack_ms=2, release_ms=100)

    log.info("Building sub bass...")
    sub_buf = build_sub_bass(drum_events)

    log.info("Building acid bass...")
    acid_buf = build_acid_bass()

    log.info("Building dark pad...")
    pad_buf = build_dark_pad()

    log.info("Building lead arp...")
    arp_buf = build_lead_arp()

    log.info("Building risers...")
    riser_buf = build_risers()

    # ---------------------------------------------------------------------------
    # MIX
    # Levels tuned so no layer overwhelms
    # ---------------------------------------------------------------------------
    log.info("Mixing...")

    def trim(buf, n=TOTAL):
        if len(buf) >= n:
            return buf[:n]
        return np.pad(buf, ((0, n - len(buf)), (0, 0)))

    mix = np.zeros((TOTAL, 2), dtype=np.float32)
    mix += trim(drum_buf) * 0.85        # drums: prominent
    mix += trim(sub_buf)  * 0.70        # sub: felt more than heard
    mix += trim(acid_buf) * 0.55        # acid: midrange punch
    mix += trim(pad_buf)  * 0.50        # pad: atmospheric
    mix += trim(arp_buf)  * 0.45        # arp: melodic hook
    mix += trim(riser_buf) * 0.60       # risers: transitions

    # Global fade-in (2s) and fade-out (4s)
    fi = int(2 * SR)
    mix[:fi, 0] *= np.linspace(0, 1, fi)
    mix[:fi, 1] *= np.linspace(0, 1, fi)
    fo = int(4 * SR)
    mix[-fo:, 0] *= np.linspace(1, 0, fo)
    mix[-fo:, 1] *= np.linspace(1, 0, fo)

    # Master chain
    log.info("Mastering...")
    mix = master_chain(mix, SR)

    # Check for NaN/inf
    if not np.isfinite(mix).all():
        log.warning("NaN/Inf detected, clipping")
        mix = np.nan_to_num(mix, nan=0.0, posinf=1.0, neginf=-1.0)

    # Export
    out_wav = "/tmp/dark_cosmic.wav"
    out_mp3 = "/tmp/dark_cosmic.mp3"
    log.info(f"Writing WAV: {out_wav}")
    sf.write(out_wav, mix, SR)

    log.info("Converting to MP3 (320k)...")
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 320k "{out_mp3}" 2>/dev/null')

    size_mb = os.path.getsize(out_mp3) / 1024**2
    log.info(f"Done: {out_mp3} ({size_mb:.1f} MB)")
    return out_mp3


if __name__ == "__main__":
    mp3 = main()
    print(f"\nOutput: {mp3}")
