#!/usr/bin/env python3
"""
render_zaycev_trance.py — Deep Trance 10min
Melody: "Песня про зайцев" (Бриллиантовая рука, 1969)
       composed by Alexander Zatsepin, lyrics by Leonid Derbenev

Original key: D minor (folk scale)
Trance adaptation: 138 BPM, key Am (relative, brighter for trance)
Duration: 10:00 (600s)

"Песня про зайцев" main melody (simplified, first verse):
    E4 E4 D4 C4 D4 | E4 E4 E4 D4 C4 | D4 D4 D4 E4 D4 C4 | B3 -- -- -- --
    E4 E4 D4 C4 D4 | E4 E4 E4 G4 E4 | D4 C4 B3 A3 -- -- | A3 -- -- -- --

In Am pentatonic/natural: A B C D E (G)
Trance arrangement:
  - Melody: resequenced as 16th-note melodic loop (8-bar phrase)
  - Bass: driving 138 BPM quarter/eighth bass line in Am
  - Pads: Am → F → C → G progression
  - Arp: 16th-note arpeggios on chord tones
  - Kick: 4-on-the-floor at 138 BPM
  - Snare: on beats 2 and 4
  - Hi-hat: 16th note pattern with open on off-beats

Sections:
  [Intro]      0:00-1:30  pads + filtered melody, no kick
  [Build-1]    1:30-2:30  +kick+bass, melody filtered
  [Rise]       2:30-3:00  white noise riser, clap roll
  [Drop-1]     3:00-5:00  full arrangement, clear melody
  [Break]      5:00-6:00  breakdown — pads + reversed melody echo
  [Build-2]    6:00-6:30  rebuild tension
  [Drop-2]     6:30-9:00  peak energy, key change to Bm (+2 semitones)
  [Outro]      9:00-10:00 fadeout, melody echoes

Mixed backend:
  - FluidSynth: melody (GM 80 Ocarina / GM 88 Pad5), bass (GM33 Finger Bass),
                choir pad (GM 91 Pad Choir), drums (ch9)
  - DawDreamer Faust: supersaw lead, arpeggios, noise riser
"""

import sys, os, logging, numpy as np, soundfile as sf
sys.path.insert(0, "/opt/autodj-mixer")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("zaycev_trance")

SR = 44100
BPM = 138
DUR = 600.0   # 10:00
BAR_S = 60.0 / BPM * 4   # ~1.739s per bar
BEAT_S = 60.0 / BPM       # ~0.435s
STEP_S = BAR_S / 16        # 16th note ~0.109s
TOTAL = int(DUR * SR)

# ---------------------------------------------------------------------------
# "Песня про зайцев" melody — quantized to Am scale
# MIDI notes, original phrasing adapted for 8-bar trance loop
# Am natural scale: A3=57 B3=59 C4=60 D4=62 E4=64 F4=65 G4=67 A4=69
# ---------------------------------------------------------------------------
# Main theme: 32 16th-note slots = 2 bars at 138 BPM
ZAYCEV_THEME_A = [
    64, 0, 64, 62, 60, 62, 0, 0,   # E E D C D (2 bars phrase 1)
    64, 64, 64, 0, 62, 60, 0, 0,   # E E E D C
    62, 62, 62, 64, 62, 60, 0, 0,  # D D D E D C
    59, 0,  0,  0,  0,  0, 0, 0,   # B3 (held)
]
# Second half (resolves to A)
ZAYCEV_THEME_B = [
    64, 0, 64, 62, 60, 62, 0, 0,   # E E D C D
    64, 64, 64, 0, 67, 64, 0, 0,   # E E E G E (variant: G instead of D)
    62, 60, 59, 57, 0,  0, 0, 0,   # D C B A (descending)
    57, 0,  0,  0,  0,  0, 0, 0,   # A (held)
]

# Full 8-bar melody = A + B repeated
ZAYCEV_FULL = ZAYCEV_THEME_A + ZAYCEV_THEME_B   # 64 steps = 4 bars

# Key shift +2 semitones for Drop-2 (Bm feel)
def shift_notes(seq, semitones):
    return [n + semitones if n != 0 else 0 for n in seq]

ZAYCEV_FULL_BM = shift_notes(ZAYCEV_FULL, 2)

# Am chord progression (4 bars = 64 16th steps, repeats)
# Am - F - C - G
CHORD_ROOTS = [57, 53, 60, 55]   # A3 F3 C4 G3
CHORD_TYPES = {
    57: [57, 60, 64],   # Am: A C E
    53: [53, 57, 60],   # F:  F A C
    60: [60, 64, 67],   # C:  C E G
    55: [55, 59, 62],   # G:  G B D
}
CHORD_DUR_BARS = 1  # each chord = 1 bar

# ---------------------------------------------------------------------------
# Section boundaries (seconds)
# ---------------------------------------------------------------------------
SEC_INTRO   = (0.0,   90.0)
SEC_BUILD1  = (90.0,  150.0)
SEC_RISE    = (150.0, 180.0)
SEC_DROP1   = (180.0, 300.0)
SEC_BREAK   = (300.0, 360.0)
SEC_BUILD2  = (360.0, 390.0)
SEC_DROP2   = (390.0, 540.0)
SEC_OUTRO   = (540.0, 600.0)

def in_section(t, sec):
    return sec[0] <= t < sec[1]

def section_amp(t):
    if in_section(t, SEC_INTRO):
        return min(1.0, (t - SEC_INTRO[0]) / 12.0)
    if in_section(t, SEC_BUILD1):
        return 1.0
    if in_section(t, SEC_RISE):
        return 1.0
    if in_section(t, SEC_DROP1):
        return 1.0
    if in_section(t, SEC_BREAK):
        return 0.6
    if in_section(t, SEC_BUILD2):
        return 0.8 + 0.2 * ((t - SEC_BUILD2[0]) / (SEC_BUILD2[1] - SEC_BUILD2[0]))
    if in_section(t, SEC_DROP2):
        return 1.0
    if in_section(t, SEC_OUTRO):
        p = (t - SEC_OUTRO[0]) / (SEC_OUTRO[1] - SEC_OUTRO[0])
        return max(0.0, 1.0 - p)
    return 0.0

# ---------------------------------------------------------------------------
# Melody filter envelope (low pass sweep, 0=closed 1=open)
# ---------------------------------------------------------------------------
def melody_filter_open(t):
    if in_section(t, SEC_INTRO):
        p = (t - SEC_INTRO[0]) / (SEC_INTRO[1] - SEC_INTRO[0])
        return min(0.3, p * 0.4)  # barely open
    if in_section(t, SEC_BUILD1):
        p = (t - SEC_BUILD1[0]) / (SEC_BUILD1[1] - SEC_BUILD1[0])
        return 0.3 + p * 0.5  # sweeping open
    if in_section(t, SEC_RISE):
        return 0.9
    if in_section(t, SEC_DROP1):
        return 1.0
    if in_section(t, SEC_BREAK):
        return 0.5
    if in_section(t, SEC_BUILD2):
        p = (t - SEC_BUILD2[0]) / (SEC_BUILD2[1] - SEC_BUILD2[0])
        return 0.5 + p * 0.5
    if in_section(t, SEC_DROP2):
        return 1.0
    if in_section(t, SEC_OUTRO):
        p = (t - SEC_OUTRO[0]) / (SEC_OUTRO[1] - SEC_OUTRO[0])
        return 1.0 - p * 0.7
    return 0.5

# ---------------------------------------------------------------------------
# Build MIDI events — FluidSynth channels
# ch0 = melody (Ocarina/Lead), ch1 = bass (Finger Bass)
# ch2 = choir pad (Pad 4 Choir), ch9 = drums
# ---------------------------------------------------------------------------

def build_melody_events():
    """Main Зайцев melody loop, 16th notes, active in all sections with filter."""
    events = []
    seq_len = len(ZAYCEV_FULL)
    total_steps = int(DUR / STEP_S) + 1

    for step in range(total_steps):
        t = step * STEP_S
        if t >= DUR:
            break

        # Which sequence to use
        if in_section(t, SEC_DROP2) or in_section(t, SEC_OUTRO):
            seq = ZAYCEV_FULL_BM
        else:
            seq = ZAYCEV_FULL

        note = seq[step % seq_len]
        if note == 0:
            continue

        # Section gating
        if in_section(t, SEC_BREAK):
            # breakdown: melody echoes, very quiet
            vel = 30
            note = note - 12  # down octave
        else:
            f = melody_filter_open(t)
            vel = int(40 + f * 80)
            vel = max(20, min(120, vel))

        dur = STEP_S * 0.85
        # ch0 = melody
        events.append((t, "note_on",  0, note, vel))
        events.append((t + dur, "note_off", 0, note, 0))

    return events

def build_bass_events():
    """Driving trance bass: root + fifth pattern."""
    events = []
    bar_count = int(DUR / BAR_S) + 1
    chord_idx = 0

    for bar in range(bar_count):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break

        # Bass only from Build-1 onwards
        if in_section(t_bar, SEC_INTRO):
            if t_bar < SEC_INTRO[1] - 16.0:  # last 16s of intro: sub rumble
                continue

        chord_root = CHORD_ROOTS[bar % len(CHORD_ROOTS)]
        bass_note = chord_root - 12  # octave down
        fifth = bass_note + 7

        # Shift for Drop-2
        if in_section(t_bar, SEC_DROP2) or in_section(t_bar, SEC_OUTRO):
            bass_note += 2
            fifth += 2

        # Pattern: root on beat1, root+5th alternating 8ths in Drop
        if in_section(t_bar, SEC_DROP1) or in_section(t_bar, SEC_DROP2):
            for beat in range(4):
                t_beat = t_bar + beat * BEAT_S
                # Main root hit
                events.append((t_beat, "note_on", 1, bass_note, 110))
                events.append((t_beat + BEAT_S * 0.4, "note_off", 1, bass_note, 0))
                # Offbeat fifth
                t_off = t_beat + BEAT_S * 0.5
                events.append((t_off, "note_on", 1, fifth, 80))
                events.append((t_off + BEAT_S * 0.4, "note_off", 1, fifth, 0))
        else:
            # Simple quarter notes
            for beat in range(4):
                t_beat = t_bar + beat * BEAT_S
                if t_beat >= DUR:
                    break
                events.append((t_beat, "note_on", 1, bass_note, 90))
                events.append((t_beat + BEAT_S * 0.9, "note_off", 1, bass_note, 0))

    return events

def build_pad_events():
    """Choir/string pad: whole bar chords."""
    events = []
    bar_count = int(DUR / BAR_S) + 1

    for bar in range(bar_count):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break

        chord_root = CHORD_ROOTS[bar % len(CHORD_ROOTS)]
        chord_notes = CHORD_TYPES[chord_root]

        # Velocity by section
        if in_section(t_bar, SEC_INTRO):
            p = (t_bar - SEC_INTRO[0]) / (SEC_INTRO[1] - SEC_INTRO[0])
            vel = int(40 + p * 30)
        elif in_section(t_bar, SEC_BUILD1):
            vel = 55
        elif in_section(t_bar, SEC_RISE):
            vel = 60
        elif in_section(t_bar, SEC_DROP1):
            vel = 45
        elif in_section(t_bar, SEC_BREAK):
            vel = 65
        elif in_section(t_bar, SEC_BUILD2):
            vel = 60
        elif in_section(t_bar, SEC_DROP2):
            vel = 40
        elif in_section(t_bar, SEC_OUTRO):
            p = (t_bar - SEC_OUTRO[0]) / (SEC_OUTRO[1] - SEC_OUTRO[0])
            vel = max(15, int(50 * (1 - p)))
        else:
            vel = 45

        # Shift for Drop-2
        shift = 2 if (in_section(t_bar, SEC_DROP2) or in_section(t_bar, SEC_OUTRO)) else 0
        dur = BAR_S * 0.97

        for note in chord_notes:
            n = note + shift
            events.append((t_bar, "note_on", 2, n, vel))
            events.append((t_bar + dur, "note_off", 2, n, 0))

    return events

def build_drum_events():
    """4/4 trance drums: kick, snare, hihat."""
    events = []
    total_beats = int(DUR / BEAT_S) + 1
    total_steps = int(DUR / STEP_S) + 1

    # Kick = MIDI 36, Snare = 38, Closed HH = 42, Open HH = 46, Clap = 39
    for beat in range(total_beats):
        t = beat * BEAT_S
        if t >= DUR:
            break

        # No kick in intro/break
        if in_section(t, SEC_INTRO) or in_section(t, SEC_BREAK):
            pass
        else:
            # 4-on-the-floor kick
            vel = 120
            if in_section(t, SEC_BUILD1):
                p = (t - SEC_BUILD1[0]) / (SEC_BUILD1[1] - SEC_BUILD1[0])
                vel = int(80 + p * 40)
            elif in_section(t, SEC_BUILD2):
                p = (t - SEC_BUILD2[0]) / (SEC_BUILD2[1] - SEC_BUILD2[0])
                vel = int(90 + p * 30)
            events.append((t, "note_on", 9, 36, vel))
            events.append((t + 0.05, "note_off", 9, 36, 0))

        # Snare on beats 2 and 4
        beat_in_bar = beat % 4
        if beat_in_bar in (1, 3):
            if not (in_section(t, SEC_INTRO) or in_section(t, SEC_BREAK)):
                events.append((t, "note_on", 9, 38, 100))
                events.append((t + 0.04, "note_off", 9, 38, 0))

        # Clap roll in Rise
        if in_section(t, SEC_RISE):
            for sub in range(4):
                t_c = t + sub * STEP_S
                if t_c >= SEC_RISE[1]:
                    break
                v = min(127, 60 + sub * 15)
                events.append((t_c, "note_on", 9, 39, v))
                events.append((t_c + 0.02, "note_off", 9, 39, 0))

    # Hi-hats: 16th notes
    for step in range(total_steps):
        t = step * STEP_S
        if t >= DUR:
            break

        if in_section(t, SEC_INTRO):
            # sparse closed hats, quiet
            if step % 4 != 0:
                continue
            vel = 40
            events.append((t, "note_on", 9, 42, vel))
            events.append((t + 0.03, "note_off", 9, 42, 0))
        elif in_section(t, SEC_BREAK):
            # no hats in breakdown
            continue
        else:
            # 16th closed hh, open on offbeats
            if step % 2 == 0:
                vel = 65
                note = 42  # closed
            else:
                vel = 50
                note = 46  # open
            events.append((t, "note_on", 9, note, vel))
            events.append((t + STEP_S * 0.8, "note_off", 9, note, 0))

    return events

# ---------------------------------------------------------------------------
# Noise riser (for Rise section) — synthesized via numpy
# ---------------------------------------------------------------------------
def build_noise_riser():
    """White noise band-pass filtered, sweeping upward."""
    from scipy.signal import butter, sosfilt

    buf = np.zeros(TOTAL, dtype=np.float32)

    s_start = int(SEC_RISE[0] * SR)
    s_end   = int(SEC_RISE[1] * SR)
    dur_s = int((SEC_RISE[1] - SEC_RISE[0]) * SR)

    noise = np.random.randn(dur_s).astype(np.float32)

    # Sweep filter 200Hz → 8kHz over the riser
    SEGMENTS = 20
    seg_len = dur_s // SEGMENTS
    swept = np.zeros(dur_s, dtype=np.float32)

    for i in range(SEGMENTS):
        lo = 200 + int(i / SEGMENTS * 4000)
        hi = lo * 3
        hi = min(hi, SR // 2 - 100)
        sos = butter(4, [lo, hi], btype="bandpass", fs=SR, output="sos")
        seg = noise[i*seg_len:(i+1)*seg_len]
        swept[i*seg_len:(i+1)*seg_len] = sosfilt(sos, seg)

    # Envelope: ramp up
    env = np.linspace(0.0, 1.0, dur_s, dtype=np.float32)
    swept *= env * 0.4

    buf[s_start:s_start + dur_s] = swept[:min(dur_s, TOTAL - s_start)]
    return buf

# ---------------------------------------------------------------------------
# Sidechain
# ---------------------------------------------------------------------------
def build_sidechain_envelope(kick_events, release_ms=90):
    env = np.ones(TOTAL, dtype=np.float32)
    release_samples = int(release_ms / 1000 * SR)
    for ev in kick_events:
        if ev[1] != "note_on" or ev[2] != 9 or ev[3] != 36:
            continue
        s = int(ev[0] * SR)
        end = min(TOTAL, s + release_samples)
        n = end - s
        if n > 0:
            recovery = 0.5 * (1 - np.cos(np.pi * np.arange(n) / n))
            env[s:end] = np.minimum(env[s:end], recovery)
    return env

# ---------------------------------------------------------------------------
# Supersaw arp via DawDreamer Faust (16th notes on chord tones)
# ---------------------------------------------------------------------------
def build_arp_events():
    """Arpeggio events for FluidSynth ch3 (Synth Lead)."""
    events = []
    total_steps = int(DUR / STEP_S) + 1

    for step in range(total_steps):
        t = step * STEP_S
        if t >= DUR:
            break

        # Arp only in drops
        if not (in_section(t, SEC_DROP1) or in_section(t, SEC_DROP2)):
            continue

        bar_idx = int(t / BAR_S)
        chord_root = CHORD_ROOTS[bar_idx % len(CHORD_ROOTS)]
        chord = CHORD_TYPES[chord_root]

        # Cycle through chord tones
        arp_note = chord[step % len(chord)]
        if in_section(t, SEC_DROP2):
            arp_note += 2

        vel = 70 + (step % 3) * 10
        dur = STEP_S * 0.6
        events.append((t, "note_on", 3, arp_note + 12, vel))  # ch3 synth lead, up octave
        events.append((t + dur, "note_off", 3, arp_note + 12, 0))

    return events

# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------
def render_fluidsynth(events, duration_s):
    from autodj.generate.backends.fluidsynth import FluidSynthBackend
    with FluidSynthBackend(sample_rate=SR) as backend:
        synth = backend.synth
        # ch0: Lead (Ocarina GM80)
        synth.bank_select(0, 0)
        synth.program_change(0, 80)   # Ocarina
        # ch1: Finger Bass GM33
        synth.program_change(1, 33)
        # ch2: Choir Pad GM91
        synth.program_change(2, 91)
        # ch3: Synth Lead GM81 (arp)
        synth.program_change(3, 81)   # Synth Lead 2 (sawtooth)
        # ch9: drums (standard)
        return backend.render(events, duration_s)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info(f"Зайцев Trance | BPM={BPM} | Am→Bm | {DUR:.0f}s")

    # Build MIDI
    log.info("Building events...")
    melody_evs = build_melody_events()
    bass_evs   = build_bass_events()
    pad_evs    = build_pad_events()
    drum_evs   = build_drum_events()
    arp_evs    = build_arp_events()

    log.info(f"  melody: {len(melody_evs)//2} notes")
    log.info(f"  bass: {len(bass_evs)//2} notes")
    log.info(f"  pad: {len(pad_evs)//2} notes")
    log.info(f"  drums: {len(drum_evs)//2} hits")
    log.info(f"  arp: {len(arp_evs)//2} notes")

    # Merge all FluidSynth events (melody + bass + pad + drums + arp)
    fluid_events = melody_evs + bass_evs + pad_evs + drum_evs + arp_evs

    # Render FluidSynth layer
    log.info("Rendering FluidSynth layer (melody + bass + pad + drums + arp)...")
    fluid_wav = render_fluidsynth(fluid_events, DUR)
    log.info(f"  FluidSynth: peak={np.abs(fluid_wav).max():.3f}")

    # Render noise riser
    log.info("Synthesizing noise riser...")
    riser_mono = build_noise_riser()
    riser_wav  = np.stack([riser_mono, riser_mono], axis=1).astype(np.float32)

    # Align lengths
    min_len = min(len(fluid_wav), TOTAL)
    fluid_wav = fluid_wav[:min_len]
    riser_wav = riser_wav[:min_len]

    # Sidechain kick → mix
    log.info("Applying sidechain...")
    sc_env = build_sidechain_envelope(drum_evs)[:min_len]
    duck_env = 0.7 + 0.3 * sc_env
    fluid_sc = fluid_wav.copy()
    fluid_sc[:, 0] *= duck_env
    fluid_sc[:, 1] *= duck_env

    # Mix
    log.info("Mixing layers...")
    mix = fluid_sc * 0.8
    mix[:, 0] += riser_wav[:, 0] * 0.5
    mix[:, 1] += riser_wav[:, 1] * 0.5

    # Section amplitude envelope
    log.info("Applying section envelope...")
    env = np.array([section_amp(i / SR) for i in range(min_len)], dtype=np.float32)
    mix[:, 0] *= env
    mix[:, 1] *= env

    # Master: soft clip + normalize
    log.info("Mastering...")
    mix = np.tanh(mix * 1.15) / 1.15
    peak = np.abs(mix).max()
    if peak > 1e-6:
        mix *= (10 ** (-0.3 / 20)) / peak

    # Save
    out_wav = "/tmp/zaycev_trance.wav"
    out_mp3 = "/tmp/zaycev_trance.mp3"
    sf.write(out_wav, mix, SR)
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 320k -q:a 0 "{out_mp3}" 2>/dev/null')

    size_mb = os.path.getsize(out_mp3) / 1024 / 1024
    log.info(f"Done: {out_mp3} ({size_mb:.1f} MB, {min_len/SR:.0f}s)")
    return out_mp3

if __name__ == "__main__":
    mp3 = main()
    print(f"\nOutput: {mp3}")
