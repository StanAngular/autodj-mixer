#!/usr/bin/env python3
"""
Xenolith — Underground Leftfield Acid
Mixed backend: DawDreamer + Surge XT VST3 (electronic) + FluidSynth (organic texture)
BPM: 122  |  Key: C minor  |  Swing: 25%  |  Duration: 3:15
"""
import os, sys, math, json, logging, time
import numpy as np

# Path setup
sys.path.insert(0, '/opt/autodj-mixer')
os.chdir('/opt/autodj-mixer')

from autodj.generate.backends.dawdreamer import DawDreamerBackend
from autodj.generate.backends.fluidsynth import (
    FluidSynthBackend, find_sf2, hz_to_midi, GM_DRUMS,
    build_melody_events, build_chord_events,
    build_drum_events, build_bass_events,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('xenolith')

# ── Constants ──────────────────────────────────────────────────────────────
BPM = 122
SR = 44100
BAR_S = 60.0 / BPM * 4           # ~1.9672 s
BEAT_S = BAR_S / 4               # ~0.4918 s
EIGHTH_S = BAR_S / 8             # ~0.2459 s
SIXTEENTH_S = BAR_S / 16         # ~0.12295 s
DURATION_S = 195                  # 3:15

# C minor scale (Hz)
def c_minor(octave=4):
    c = 261.63 * (2 ** (octave - 4))
    return {
        'C':  c, 'D':  c * 2**(2/12), 'Eb': c * 2**(3/12),
        'F':  c * 2**(5/12), 'G':  c * 2**(7/12),
        'Ab': c * 2**(8/12), 'Bb': c * 2**(10/12),
    }

C4 = c_minor(4)
C3 = c_minor(3)
C2 = c_minor(2)
C5 = c_minor(5)

# ── Section times (seconds) ───────────────────────────────────────────────
SECTIONS = {
    'intro':    (0.0, 45.0),      # 0:00-0:45   ~23 bars
    'build_up': (45.0, 75.0),     # 0:45-1:15   ~15 bars
    'void':     (75.0, 90.0),     # 1:15-1:30   ~8 bars
    'drop':     (90.0, 150.0),    # 1:30-2:30   ~31 bars
    'outro':    (150.0, 195.0),   # 2:30-3:15   ~23 bars
}

def in_section(name, t):
    s, e = SECTIONS[name]
    return s <= t < e

def section_time(name):
    return SECTIONS[name]

# ── Swing timing ──────────────────────────────────────────────────────────
# 25% swing = delay on even 16th notes by 25% of 16th-note duration
SWING_AMOUNT = 0.25

def swing_time(t, grid_sixteenth_idx):
    """Apply 25% swing to even 16th notes."""
    if grid_sixteenth_idx % 2 == 1:  # even 16th (offbeat)
        return t + SIXTEENTH_S * SWING_AMOUNT
    return t

# ── Build MIDI events for Xenolith ────────────────────────────────────────

def build_xenolith_events():
    """Build all MIDI events for the Xenolith track.

    Channel mapping:
      0  → Surge XT: Acid line (saw/FM lead)
      1  → Surge XT: Glitch percussion
      2  → Surge XT: Sub-bass
      3  → FluidSynth: Organic texture (cello/choir)
      9  → built-in drums (Faust or FluidSynth)
    """
    all_events = []

    # Program changes
    # Ch0: Acid lead → Surge XT
    all_events.append((0.0, "program", 0, 0, 81))   # Synth lead sawtooth
    # Ch1: Glitch percussion → Surge XT
    all_events.append((0.0, "program", 1, 0, 80))   # Synth lead square
    # Ch2: Sub-bass → Surge XT
    all_events.append((0.0, "program", 2, 0, 38))   # Synth bass 1
    # Ch3: Organic texture → FluidSynth (cello)
    all_events.append((0.0, "program", 3, 0, 42))   # Cello
    # Ch9: Drums → Faust built-in
    all_events.append((0.0, "program", 9, 0, 0))    # GM drums

    # ═══════════════════════════════════════════════════════════════════════
    # 1. ORGANIC TEXTURE (FluidSynth, ch3) — ACTIVE ALL SECTIONS
    #    Cello/choir, long sustained dissonant chords, lowered octave
    # ═══════════════════════════════════════════════════════════════════════
    # C minor open voicings (C3-Eb3-G3, F3-Ab3-C4, G3-Bb3-D4, Ab3-C4-Eb4)
    texture_chords = [
        [C3['C'], C3['Eb'], C3['G'], C4['C']],          # Cm
        [C3['F'], C3['Ab'], C4['C'], C4['F']],          # Fm
        [C3['G'], C3['Bb'], C4['D'], C4['G']],          # Gm
        [C3['Ab'], C4['C'], C4['Eb'], C4['Ab']],        # Abmaj7
        [C3['F'], C3['Ab'], C4['C'], C4['Eb']],         # Fm7
        [C3['G'], C3['Bb'], C4['D'], C4['F']],          # Gm7
        [C3['Ab'], C3['C'], C4['Eb'], C4['G']],         # Abmaj7
        [C2['Bb'], C3['D'], C3['F'], C3['Ab']],         # Bbdim (dissonant)
    ]
    # Sustained chords, 4 bars each, cycle through the track
    texture_events = []
    for bar in range(int(DURATION_S / BAR_S) + 1):
        t_on = bar * BAR_S
        t_off = t_on + BAR_S * 0.95
        chord = texture_chords[bar % len(texture_chords)]
        # Only active in sections where texture plays
        if in_section('intro', t_on) or in_section('void', t_on) or in_section('outro', t_on):
            # Intro: only texture, prominent
            # Void: texture only, reverbed
            # Outro: texture dissolves
            for freq in chord:
                note = hz_to_midi(freq)
                texture_events.append((t_on, "note_on", 3, note, 80))
                texture_events.append((t_off, "note_off", 3, note, 0))
        elif in_section('build_up', t_on) or in_section('drop', t_on):
            # Build-up & Drop: texture in background, quiet
            for freq in chord:
                note = hz_to_midi(freq)
                texture_events.append((t_on, "note_on", 3, note, 40))
                texture_events.append((t_off, "note_off", 3, note, 0))

    all_events.extend(texture_events)
    log.info(f"Texture events: {len(texture_events)//2} chords")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. ACID LINE (Surge XT, ch0) — Saw/FM with cutoff automation
    #    C minor acid pattern: 16th-note sequence
    # ═══════════════════════════════════════════════════════════════════════
    # Acid pattern in C minor (16 notes per bar)
    acid_pattern = [
        C4['C'], C4['Eb'], C4['G'],  C4['Eb'],    # Bar 1
        C4['F'], C4['Ab'], C4['C'],  C4['Ab'],
        C4['G'], C4['Bb'], C4['D'],  C4['Bb'],    # Bar 2
        C4['Ab'], C4['C'], C4['Eb'], 0.0,          # rest at end
        C4['C'], C4['Eb'], 0.0,      C4['G'],     # Bar 3 - syncopated
        C4['F'], 0.0,      C4['Ab'], C4['C'],
        C4['G'], C4['Bb'], C4['D'],  C4['F'],     # Bar 4
        C4['Ab'], C4['C'], C4['Eb'], C4['G'],
    ]

    # Acid line also has a second pattern (variation)
    acid_pattern2 = [
        C4['F'], C4['Ab'], C4['C'],  C4['Eb'],    # Bar 5
        C4['G'], C4['Bb'], C4['D'],  C4['F'],
        C4['C'], C4['Eb'], C4['G'],  C4['C'],     # Bar 6
        C4['F'], C4['Ab'], 0.0,      C4['G'],
        C4['Ab'], C4['C'], C4['Eb'], C4['G'],     # Bar 7 - higher
        C5['C'], C4['Ab'], C4['G'],  C4['Eb'],
        C4['Bb'], C4['D'], C4['F'],  C4['Ab'],    # Bar 8 - dissonant climb
        C4['G'], C4['Eb'], C4['C'],  0.0,
    ]

    acid_events = []
    for bar in range(int(DURATION_S / BAR_S) + 1):
        t_on = bar * BAR_S

        # Acid active in: build-up (quiet, closing filter), drop (full), some outro
        if in_section('intro', t_on):
            continue  # No acid in intro
        elif in_section('build_up', t_on):
            # Quiet, filter starts closed, opens gradually
            pattern = acid_pattern if (bar % 8 < 4) else acid_pattern2
            # Sub-bars within build-up: filter opens
            for i, freq in enumerate(pattern):
                t = t_on + i * SIXTEENTH_S
                t_swung = swing_time(t, i)
                if freq <= 0: continue
                note = hz_to_midi(freq)
                vel = 50  # Quiet in build-up
                acid_events.append((t_swung, "note_on", 0, note, vel))
                acid_events.append((t_swung + SIXTEENTH_S * 0.85, "note_off", 0, note, 0))
        elif in_section('void', t_on):
            continue  # No acid in void
        elif in_section('drop', t_on):
            # Full volume, aggressive
            pattern = acid_pattern if (bar % 8 < 4) else acid_pattern2
            for i, freq in enumerate(pattern):
                t = t_on + i * SIXTEENTH_S
                t_swung = swing_time(t, i)
                if freq <= 0: continue
                note = hz_to_midi(freq)
                vel = 100 + int(27 * (i % 4 == 0))  # Accent on beats
                acid_events.append((t_swung, "note_on", 0, note, vel))
                acid_events.append((t_swung + SIXTEENTH_S * 0.75, "note_off", 0, note, 0))
        elif in_section('outro', t_on):
            # Acid fades, filter closes
            if bar % 4 < 2:  # Only first 2 bars of each 4-bar group
                pattern = acid_pattern if (bar % 8 < 4) else acid_pattern2
                for i, freq in enumerate(pattern[:8]):  # Only first 8 notes
                    t = t_on + i * EIGHTH_S  # Eighth notes, slower
                    if freq <= 0: continue
                    note = hz_to_midi(freq)
                    vel = 30
                    acid_events.append((t, "note_on", 0, note, vel))
                    acid_events.append((t + EIGHTH_S * 0.7, "note_off", 0, note, 0))

    all_events.extend(acid_events)
    log.info(f"Acid events: {len(acid_events)//2} notes")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. GLITCH PERCUSSION (Surge XT, ch1) — Noise generators, off-grid
    # ═══════════════════════════════════════════════════════════════════════
    # Random metallic clicks, shifted +5-10ms from grid
    glitch_events = []
    np.random.seed(42)  # Reproducible

    for bar in range(int(DURATION_S / BAR_S) + 1):
        t0 = bar * BAR_S

        if in_section('intro', t0):
            # Sparse, scattered clicks in intro
            n_clicks = np.random.randint(3, 6)
            for _ in range(n_clicks):
                beat_pos = np.random.uniform(0, 4)
                t = t0 + beat_pos * BEAT_S + np.random.uniform(0.005, 0.010)
                pitch = np.random.choice([C4['C'], C4['Eb'], C4['F'], C4['G'], C4['Ab']])
                note = hz_to_midi(pitch)
                vel = int(np.random.uniform(30, 70))
                glitch_events.append((t, "note_on", 1, note, vel))
                glitch_events.append((t + 0.03, "note_off", 1, note, 0))
        elif in_section('build_up', t0):
            # Building up
            n_clicks = np.random.randint(4, 8)
            for _ in range(n_clicks):
                beat_pos = np.random.uniform(0, 4)
                t = t0 + beat_pos * BEAT_S + np.random.uniform(0.005, 0.012)
                pitch = np.random.choice([C4['C'], C4['Eb'], C4['F'], C4['G'], C4['Ab'], C4['Bb']])
                note = hz_to_midi(pitch)
                vel = int(np.random.uniform(50, 90))
                glitch_events.append((t, "note_on", 1, note, vel))
                glitch_events.append((t + 0.04, "note_off", 1, note, 0))
        elif in_section('void', t0):
            continue  # No glitch in void
        elif in_section('drop', t0):
            # Maximum glitch
            n_clicks = np.random.randint(6, 12)
            for _ in range(n_clicks):
                beat_pos = np.random.uniform(0, 4)
                t = t0 + beat_pos * BEAT_S + np.random.uniform(0.003, 0.015)
                pitch = np.random.choice([C4['C'], C4['Eb'], C4['F'], C4['G'], C4['Ab'], C4['Bb'], C5['C']])
                note = hz_to_midi(pitch)
                vel = int(np.random.uniform(60, 110))
                glitch_events.append((t, "note_on", 1, note, vel))
                glitch_events.append((t + 0.05, "note_off", 1, note, 0))
        elif in_section('outro', t0):
            # Fading out
            if bar % 4 == 0:  # Only first bar of each 4
                n_clicks = np.random.randint(2, 4)
                for _ in range(n_clicks):
                    beat_pos = np.random.uniform(0, 4)
                    t = t0 + beat_pos * BEAT_S + np.random.uniform(0.005, 0.010)
                    pitch = np.random.choice([C4['C'], C4['Eb'], C4['G']])
                    note = hz_to_midi(pitch)
                    vel = int(np.random.uniform(20, 50))
                    glitch_events.append((t, "note_on", 1, note, vel))
                    glitch_events.append((t + 0.03, "note_off", 1, note, 0))

    all_events.extend(glitch_events)
    log.info(f"Glitch events: {len(glitch_events)//2} hits")

    # ═══════════════════════════════════════════════════════════════════════
    # 4. SUB-BASS (Surge XT, ch2) — Monophonic sub
    # ═══════════════════════════════════════════════════════════════════════
    # C minor bassline: C2, F2, G2, Ab2 (root movement)
    bass_roots = [
        C2['C'], C2['C'], C2['F'], C2['F'],    # 4 bars
        C2['G'], C2['G'], C2['Ab'], C2['Ab'],   # 4 bars
        C2['F'], C2['F'], C2['G'], C2['G'],     # 4 bars
        C2['C'], C2['C'], C2['Ab'], C2['G'],    # 4 bars
    ]

    bass_events = []
    for bar in range(int(DURATION_S / BAR_S) + 1):
        t_on = bar * BAR_S
        root = bass_roots[bar % len(bass_roots)]

        if in_section('intro', t_on):
            continue  # No bass in intro
        elif in_section('build_up', t_on):
            # Bass comes in, but quiet
            note = hz_to_midi(root)
            bass_events.append((t_on, "note_on", 2, note, 50))
            bass_events.append((t_on + BAR_S * 0.9, "note_off", 2, note, 0))
        elif in_section('void', t_on):
            continue  # No bass in void
        elif in_section('drop', t_on):
            # Full sub-bass, pumping
            note = hz_to_midi(root)
            bass_events.append((t_on, "note_on", 2, note, 110))
            bass_events.append((t_on + BAR_S * 0.85, "note_off", 2, note, 0))
        elif in_section('outro', t_on):
            continue  # No bass in outro

    all_events.extend(bass_events)
    log.info(f"Bass events: {len(bass_events)//2} notes")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. DRUMS (ch9) — Faust built-in drums
    #    Pattern: kick on 1,2,3,4; snare on 2,4; hats every 16th
    #    With 25% swing
    # ═══════════════════════════════════════════════════════════════════════
    # Build drum sections manually for per-section control
    drum_events = []

    for bar in range(int(DURATION_S / BAR_S) + 1):
        t0 = bar * BAR_S

        # Kick pattern
        if in_section('intro', t0):
            continue  # No drums in intro
        elif in_section('build_up', t0):
            # Kick only, no snare/hat yet
            kick_positions = [0, 2]  # Half-time kick
            for bp in kick_positions:
                t = t0 + bp * BEAT_S
                drum_events.append((t, "note_on", 9, GM_DRUMS["kick"], 100))
                drum_events.append((t + 0.05, "note_off", 9, GM_DRUMS["kick"], 0))
        elif in_section('void', t0):
            continue  # No drums in void
        elif in_section('drop', t0):
            # Full drum pattern
            # Kick: 4 on the floor
            for bp in range(4):
                t = t0 + bp * BEAT_S
                vel = 120 if bp == 0 else 110
                drum_events.append((t, "note_on", 9, GM_DRUMS["kick"], vel))
                drum_events.append((t + 0.05, "note_off", 9, GM_DRUMS["kick"], 0))

            # Snare: 2 & 4
            for bp in [1, 3]:
                t = t0 + bp * BEAT_S + 0.005  # Slight off-grid for swing feel
                drum_events.append((t, "note_on", 9, GM_DRUMS["snare"], 100))
                drum_events.append((t + 0.05, "note_off", 9, GM_DRUMS["snare"], 0))

            # Hi-hat: every 16th with swing
            for sp in range(16):
                t = t0 + sp * SIXTEENTH_S
                t_swung = swing_time(t, sp)
                vel = 55 if sp % 2 == 0 else 35  # Accent on downbeats
                drum_events.append((t_swung, "note_on", 9, GM_DRUMS["closed_hat"], vel))
                drum_events.append((t_swung + 0.03, "note_off", 9, GM_DRUMS["closed_hat"], 0))

            # Open hat accent on 4+
            t = t0 + 3.5 * BEAT_S
            drum_events.append((t, "note_on", 9, GM_DRUMS["open_hat"], 60))
            drum_events.append((t + 0.15, "note_off", 9, GM_DRUMS["open_hat"], 0))
        elif in_section('outro', t0):
            # Outro: sparse drums, dissolving
            if bar % 2 == 0:
                t = t0
                drum_events.append((t, "note_on", 9, GM_DRUMS["kick"], 80))
                drum_events.append((t + 0.05, "note_off", 9, GM_DRUMS["kick"], 0))
            if bar % 4 == 2:
                t = t0 + 2 * BEAT_S
                drum_events.append((t, "note_on", 9, GM_DRUMS["snare"], 60))
                drum_events.append((t + 0.05, "note_off", 9, GM_DRUMS["snare"], 0))

    all_events.extend(drum_events)
    log.info(f"Drum events: {len(drum_events)//2} hits")

    # Sort all events by time
    all_events.sort(key=lambda e: e[0])
    log.info(f"Total events: {len(all_events)}")
    return all_events


# ── Render ────────────────────────────────────────────────────────────────

def apply_sidechain(audio, sr, bpm, depth_db=6, release_s=0.15):
    """Apply sidechain compression ducking from kick (4-on-the-floor)."""
    beat_s = 60.0 / bpm
    n_samples = len(audio)
    env = np.ones(n_samples, dtype=np.float32)
    beat_start = 0.0
    while beat_start < n_samples / sr:
        s_on = int(beat_start * sr)
        s_release = s_on + int(release_s * sr)
        if s_release <= n_samples:
            # Exponential decay duck
            duck = 10 ** (-depth_db / 20)
            decay = np.exp(-np.linspace(0, 5, s_release - s_on))
            env[s_on:s_release] = duck + (1 - duck) * decay
        beat_start += beat_s
    # Apply envelope
    result = audio * env[:, np.newaxis] if audio.ndim > 1 else audio * env
    return result.astype(np.float32)


def apply_reverb(audio, sr, wet=0.4, decay_s=1.5):
    """Simple Schroeder reverb (comb + allpass)."""
    from scipy import signal
    n = len(audio)
    if audio.ndim == 1:
        audio = np.column_stack([audio, audio])

    # Comb filters (stereo, different delays for L/R spread)
    delays = [int(sr * d) for d in [0.030, 0.037, 0.041, 0.047]]
    gains = [0.6, 0.5, 0.4, 0.3]

    wet_signal = np.zeros_like(audio)
    for delay, gain in zip(delays, gains):
        comb = np.zeros_like(audio)
        comb[delay:] = audio[:-delay] * gain
        # Feedback
        for i in range(delay, n):
            comb[i] = audio[i] * (1 - gain) + comb[i - delay] * gain * 0.7
        wet_signal += comb

    # Allpass (diffusion)
    ap_delay = int(sr * 0.005)
    ap = np.zeros_like(wet_signal)
    ap_gain = 0.7
    for i in range(ap_delay, n):
        ap[i] = wet_signal[i] + ap_gain * ap[i - ap_delay]
        wet_signal[i] = -wet_signal[i] * ap_gain + ap[i - ap_delay]

    # Mix dry/wet
    out = (1 - wet) * audio + wet * wet_signal
    # Normalize
    peak = np.abs(out).max()
    if peak > 0.95:
        out *= 0.95 / peak
    return out.astype(np.float32)


def apply_cutoff_automation(audio, sr, duration_s, bpm):
    """Simulate filter cutoff automation by ducking highs.
    Maps to the arrangement sections:
    - Intro:  low cut (muffled) → not needed, no acid in intro
    - Build-up: gradually opening
    - Void: cut completely
    - Drop: fully open
    - Outro: closing
    """
    n = len(audio)
    result = audio.copy()
    for name, (s, e) in SECTIONS.items():
        s_on = int(s * sr)
        s_off = int(e * sr)
        if s_off <= s_on:
            continue

        if name == 'intro':
            # No acid in intro, leave as is
            pass
        elif name == 'build_up':
            # Low-pass filter gradually opening
            cutoff_hz = np.linspace(200, 4000, s_off - s_on)
            for i in range(s_on, s_off):
                idx = i - s_on
                cf = cutoff_hz[idx] / (sr / 2)
                cf = max(0.01, min(0.99, cf))
                # Simple 1-pole LP
                result[i] *= cf * 0.5 + 0.5
        elif name == 'void':
            # Mute acid
            result[s_on:s_off] *= 0.0
        elif name == 'drop':
            # Fully open
            pass
        elif name == 'outro':
            # Closing filter
            cutoff_hz = np.linspace(3000, 150, s_off - s_on)
            for i in range(s_on, s_off):
                idx = i - s_on
                cf = cutoff_hz[idx] / (sr / 2)
                cf = max(0.01, min(0.99, cf))
                result[i] *= cf * 0.5 + 0.5
    return result


def render_xenolith():
    log.info("╔══════════════════════════════════════════╗")
    log.info("║       XENOLITH — Underground Leftfield   ║")
    log.info("║       122 BPM · C minor · 3:15           ║")
    log.info("╚══════════════════════════════════════════╝")

    midi_events = build_xenolith_events()

    # Split events by backend
    daw_events = [ev for ev in midi_events if ev[2] in (0, 1, 2, 9)]  # Ch0,1,2,9 → DawDreamer
    fluid_events = [ev for ev in midi_events if ev[2] == 3]            # Ch3 → FluidSynth

    log.info(f"DawDreamer events: {len(daw_events)}")
    log.info(f"FluidSynth events: {len(fluid_events)}")

    # ─── Render DawDreamer (Surge XT VST3 for acid + percussion) ───
    log.info("Rendering DawDreamer (Surge XT + Faust)...")
    vst3_path = "/opt/autodj-mixer/shared/vst3/Surge XT.vst3"
    t0 = time.time()

    # We need to render acid line (ch0) via VST3 and percussion (ch1) via VST3
    # But the DawDreamerBackend expects one VST3 per channel
    # Route ch0 and ch1 to Surge XT VST3, ch2 (bass) and ch9 (drums) to Faust
    dd_backend = DawDreamerBackend(
        sample_rate=SR,
        vst3_plugins={
            "0": vst3_path,  # Acid line → Surge XT
            "1": vst3_path,  # Glitch → Surge XT
            "2": vst3_path,  # Sub-bass → Surge XT (efficient batched render)
        },
    )
    wav_daw = dd_backend.render(daw_events, DURATION_S)
    dd_backend.close()
    log.info(f"DawDreamer done: {len(wav_daw)} samples ({time.time()-t0:.1f}s)")

    # ─── Render FluidSynth (organic texture) ───
    log.info("Rendering FluidSynth (cello/organic texture)...")
    t0 = time.time()
    sf2_path = "/opt/autodj-mixer/shared/MuseScore_General.sf2"
    fs_backend = FluidSynthBackend(sf2_path=sf2_path, sample_rate=SR)
    wav_fluid = fs_backend.render(fluid_events, DURATION_S)
    fs_backend.close()
    log.info(f"FluidSynth done: {len(wav_fluid)} samples ({time.time()-t0:.1f}s)")

    # ─── Mix ───
    log.info("Mixing layers...")
    # Levels: DawDreamer = 0 dB, FluidSynth = -6 dB (background)
    wav = wav_daw * 0.9 + wav_fluid * 0.45

    # Apply sidechain ducking (kick -> everything)
    log.info("Applying sidechain compression...")
    wav = apply_sidechain(wav, SR, BPM, depth_db=4, release_s=0.12)

    # Apply reverb to the whole mix (subtle)
    log.info("Applying reverb...")
    wav = apply_reverb(wav, SR, wet=0.15, decay_s=1.2)

    # Normalize to -0.5 dB
    peak = np.abs(wav).max()
    target = 10 ** (-0.5 / 20)
    if peak > 1e-6:
        wav *= target / peak

    log.info(f"Render complete: {len(wav)} samples, peak={peak:.3f}")

    # Save
    import soundfile as sf
    out_path = "/opt/autodj-mixer/Xenolith.wav"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sf.write(out_path, wav, SR)
    log.info(f"Saved: {out_path}")

    # Encode MP3
    import subprocess
    mp3_path = out_path.replace(".wav", ".mp3")
    subprocess.run([
        "ffmpeg", "-y", "-i", out_path,
        "-b:a", "320k", "-q:a", "0",
        mp3_path
    ], capture_output=True)
    log.info(f"MP3: {mp3_path}")

    return out_path, mp3_path


if __name__ == "__main__":
    wav, mp3 = render_xenolith()
    print(f"\n✅ Xenolith rendered!")
    print(f"   WAV: {wav}")
    print(f"   MP3: {mp3}")