#!/usr/bin/env python3
"""
render_xenolith.py — "Xenolith" Underground Leftfield Acid
Mixed backend: Surge XT (kick, acid, glitch) + FluidSynth (organic cello/choir)

BPM: 122 | Key: C minor | Swing: 25% | Duration: 3:15
Sections:
  [Intro]     0:00-0:45  pad+glitch only
  [Build-up]  0:45-1:15  +kick, acid opens
  [Void]      1:15-1:30  solo cello+reverb
  [Drop]      1:30-2:30  ALL channels max
  [Outro]     2:30-3:15  fadeout
"""

import sys, os, logging, numpy as np, soundfile as sf
sys.path.insert(0, "/opt/autodj-mixer")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("xenolith")

SR = 44100
BPM = 122
DUR = 195.0  # 3:15
BAR_S = 60.0 / BPM * 4  # ~1.967s per bar
TOTAL = int(DUR * SR)
SWING = 0.25  # 25%

# C minor scale: C D Eb F G Ab Bb
CM_NOTES = [48, 50, 51, 53, 55, 56, 58, 60, 62, 63, 65, 67, 68, 70, 72]
# Acid sequence in Cm (16th notes, 0=rest)
ACID_SEQ = [48, 0, 51, 48, 0, 55, 53, 0, 48, 51, 0, 53, 55, 0, 58, 55,
            48, 0, 53, 51, 0, 48, 55, 0, 51, 53, 0, 55, 58, 0, 60, 0]

# Cm chords for organic texture (low cello range)
CM_CHORDS = [
    [36, 43, 48, 51],  # Cm (C2 G2 C3 Eb3)
    [34, 41, 46, 51],  # Bb (Bb1 F2 Bb2 Eb3)
    [32, 39, 44, 48],  # Ab (Ab1 Eb2 Ab2 C3)
    [34, 41, 46, 53],  # Bb (Bb1 F2 Bb2 F3)
]

# ---------------------------------------------------------------------------
# Section boundaries
# ---------------------------------------------------------------------------
SEC_INTRO  = (0.0,  45.0)
SEC_BUILD  = (45.0, 75.0)
SEC_VOID   = (75.0, 90.0)
SEC_DROP   = (90.0, 150.0)
SEC_OUTRO  = (150.0, 195.0)

def in_section(t, sec):
    return sec[0] <= t < sec[1]

def section_amp(t):
    """Master amplitude envelope per section."""
    if in_section(t, SEC_INTRO):
        return min(1.0, (t - SEC_INTRO[0]) / 8.0)  # 8s fade in
    if in_section(t, SEC_BUILD):
        return 1.0
    if in_section(t, SEC_VOID):
        return 0.7
    if in_section(t, SEC_DROP):
        return 1.0
    if in_section(t, SEC_OUTRO):
        progress = (t - SEC_OUTRO[0]) / (SEC_OUTRO[1] - SEC_OUTRO[0])
        return max(0.0, 1.0 - progress)  # linear fadeout
    return 0.0

# ---------------------------------------------------------------------------
# Swing helper
# ---------------------------------------------------------------------------
def swing_time(beat_pos, step_s, swing=SWING):
    """Apply swing to even 16th note positions."""
    if beat_pos % 2 == 1:  # odd = swung
        return beat_pos * step_s + step_s * swing * 0.5
    return beat_pos * step_s

# ---------------------------------------------------------------------------
# Build MIDI events for Surge XT channels
# ---------------------------------------------------------------------------
def build_kick_events():
    """Kick drum: quarter notes during Build + Drop."""
    events = []
    step_s = BAR_S / 4  # quarter
    total_beats = int(DUR / step_s)
    for beat in range(total_beats):
        t = beat * step_s
        # Only in Build-up and Drop
        if not (in_section(t, SEC_BUILD) or in_section(t, SEC_DROP)):
            continue
        vel = 110
        events.append((t, "note_on", 0, 36, vel))
        events.append((t + 0.05, "note_off", 0, 36, 0))
    return events

def build_acid_events():
    """Acid line: 16th notes with swing, filter opens over sections."""
    events = []
    step_s = BAR_S / 16  # 16th note
    seq_len = len(ACID_SEQ)
    total_steps = int(DUR / step_s)

    for step in range(total_steps):
        t = swing_time(step, step_s)
        if t >= DUR:
            break

        note = ACID_SEQ[step % seq_len]
        if note == 0:
            continue

        # Section gating
        if in_section(t, SEC_INTRO) or in_section(t, SEC_VOID):
            continue
        if in_section(t, SEC_BUILD):
            vel = min(127, 60 + int((t - SEC_BUILD[0]) / (SEC_BUILD[1] - SEC_BUILD[0]) * 50))
        elif in_section(t, SEC_DROP):
            vel = 100
        elif in_section(t, SEC_OUTRO):
            progress = (t - SEC_OUTRO[0]) / (SEC_OUTRO[1] - SEC_OUTRO[0])
            vel = max(30, int(100 * (1 - progress)))
        else:
            vel = 80

        dur = step_s * 0.7
        events.append((t, "note_on", 1, note, vel))
        events.append((t + dur, "note_off", 1, note, 0))

    return events

def build_glitch_events():
    """Glitch percussion: sparse noise hits with micro-shift."""
    events = []
    step_s = BAR_S / 16
    total_steps = int(DUR / step_s)

    for step in range(total_steps):
        t = swing_time(step, step_s)
        if t >= DUR:
            break

        # Sparse: every 3rd or 5th 16th, semi-random pattern
        if step % 5 != 0 and step % 7 != 0:
            continue

        # Skip void section (only texture there)
        if in_section(t, SEC_VOID):
            continue

        # Micro-shift +5-10ms
        shift = 0.005 + (step % 3) * 0.003
        t_hit = t + shift

        vel = 50 + (step % 4) * 15  # ghost note variation
        events.append((t_hit, "note_on", 2, 60, vel))
        events.append((t_hit + 0.04, "note_off", 2, 60, 0))

    return events

def build_sub_bass_events():
    """Sub-bass: root notes, only in Drop."""
    events = []
    roots = [36, 34, 32, 34]  # C2 Bb1 Ab1 Bb1
    bar_count = int(DUR / BAR_S) + 1

    for bar in range(bar_count):
        t = bar * BAR_S
        if not in_section(t, SEC_DROP):
            continue
        note = roots[bar % len(roots)]
        dur = BAR_S * 0.9
        events.append((t, "note_on", 3, note, 100))
        events.append((t + dur, "note_off", 3, note, 0))

    return events

# ---------------------------------------------------------------------------
# Build MIDI events for FluidSynth (organic texture)
# ---------------------------------------------------------------------------
def build_texture_events():
    """Cello/choir: long chords, all sections except void is solo."""
    events = []
    bar_count = int(DUR / BAR_S) + 1

    for bar in range(bar_count):
        t = bar * BAR_S
        chord = CM_CHORDS[bar % len(CM_CHORDS)]

        # Velocity by section
        if in_section(t, SEC_INTRO):
            vel = 55 + int((t / SEC_INTRO[1]) * 20)
        elif in_section(t, SEC_BUILD):
            vel = 60
        elif in_section(t, SEC_VOID):
            vel = 85  # solo, louder
        elif in_section(t, SEC_DROP):
            vel = 40  # background
        elif in_section(t, SEC_OUTRO):
            progress = (t - SEC_OUTRO[0]) / (SEC_OUTRO[1] - SEC_OUTRO[0])
            vel = max(20, int(55 * (1 - progress)))
        else:
            continue

        dur = BAR_S * 0.95
        for note in chord:
            # Channel 0 for FluidSynth (cello = GM 42)
            events.append((t, "note_on", 0, note, vel))
            events.append((t + dur, "note_off", 0, note, 0))

    return events

# ---------------------------------------------------------------------------
# Sidechain pump (applied post-render to bass/pad)
# ---------------------------------------------------------------------------
def build_sidechain_envelope(kick_events):
    """Half-cosine recovery envelope from kick positions."""
    env = np.ones(TOTAL, dtype=np.float32)
    release_samples = int(0.08 * SR)  # 80ms recovery

    for ev in kick_events:
        if ev[1] != "note_on":
            continue
        t = ev[0]
        s = int(t * SR)
        end = min(TOTAL, s + release_samples)
        n = end - s
        if n > 0:
            recovery = 0.5 * (1 - np.cos(np.pi * np.arange(n) / n))
            env[s:end] = np.minimum(env[s:end], recovery)

    return env

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def render_surge_layer(events, duration_s):
    """Render all Surge XT events via DawDreamer."""
    from autodj.generate.backends.dawdreamer import DawDreamerBackend

    backend = DawDreamerBackend(
        sample_rate=SR,
        vst3_plugins={
            0: "shared/vst3/Surge XT.vst3",  # kick
            1: "shared/vst3/Surge XT.vst3",  # acid
        },
        default_preset="fm_bell",  # glitch perc fallback
    )

    return backend.render(events, duration_s)

def render_fluidsynth_layer(events, duration_s):
    """Render FluidSynth organic texture."""
    from autodj.generate.backends.fluidsynth import FluidSynthBackend

    with FluidSynthBackend(sample_rate=SR) as backend:
        # Set cello program (GM 42)
        synth = backend.synth
        synth.bank_select(0, 0)
        synth.program_change(0, 42)  # Cello

        return backend.render(events, duration_s)

def main():
    log.info(f"Xenolith | BPM={BPM} | Cm | {DUR:.0f}s | swing={SWING}")

    # Build events
    log.info("Building MIDI events...")
    kick_evs = build_kick_events()
    acid_evs = build_acid_events()
    glitch_evs = build_glitch_events()
    sub_evs = build_sub_bass_events()
    texture_evs = build_texture_events()

    log.info(f"  kick: {len(kick_evs)//2} notes")
    log.info(f"  acid: {len(acid_evs)//2} notes")
    log.info(f"  glitch: {len(glitch_evs)//2} hits")
    log.info(f"  sub: {len(sub_evs)//2} notes")
    log.info(f"  texture: {len(texture_evs)//2} notes")

    # Merge Surge XT events
    surge_events = kick_evs + acid_evs + glitch_evs + sub_evs

    # Render layers
    log.info("Rendering Surge XT layer (kick + acid + glitch + sub)...")
    surge_wav = render_surge_layer(surge_events, DUR)
    log.info(f"  Surge: peak={np.abs(surge_wav).max():.3f}")

    log.info("Rendering FluidSynth layer (cello texture)...")
    fluid_wav = render_fluidsynth_layer(texture_evs, DUR)
    log.info(f"  FluidSynth: peak={np.abs(fluid_wav).max():.3f}")

    # Ensure same length
    min_len = min(len(surge_wav), len(fluid_wav), TOTAL)
    surge_wav = surge_wav[:min_len]
    fluid_wav = fluid_wav[:min_len]

    # Apply sidechain to texture
    log.info("Applying sidechain pump to texture...")
    sc_env = build_sidechain_envelope(kick_evs)[:min_len]
    fluid_wav[:, 0] *= sc_env
    fluid_wav[:, 1] *= sc_env

    # Mix layers
    log.info("Mixing layers...")
    mix = surge_wav * 0.7 + fluid_wav * 0.5

    # Apply section amplitude envelope
    log.info("Applying section envelope...")
    env = np.array([section_amp(i / SR) for i in range(min_len)], dtype=np.float32)
    mix[:, 0] *= env
    mix[:, 1] *= env

    # Master: soft clip + normalize
    log.info("Mastering...")
    mix = np.tanh(mix * 1.2) / 1.2
    peak = np.abs(mix).max()
    if peak > 1e-6:
        mix *= (10 ** (-0.5 / 20)) / peak

    # Save
    out_wav = "/tmp/xenolith.wav"
    out_mp3 = "/tmp/xenolith.mp3"
    sf.write(out_wav, mix, SR)
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 320k -q:a 0 "{out_mp3}" 2>/dev/null')

    size_mb = os.path.getsize(out_mp3) / 1024 / 1024
    log.info(f"Done: {out_mp3} ({size_mb:.1f} MB, {min_len/SR:.0f}s)")
    return out_mp3

if __name__ == "__main__":
    mp3 = main()
    print(f"\nOutput: {mp3}")
