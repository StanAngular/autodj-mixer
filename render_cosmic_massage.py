#!/usr/bin/env python3
"""
render_cosmic_massage.py — Cosmic Acid Jazz Downtempo House
Background music for massage salon. 7 minutes.

Mixed backend: FluidSynth (Rhodes, upright bass, flute, strings) + DawDreamer Faust (sub, pad)

BPM: 82 | Key: Dm7 → Gm7 → Cmaj7 → Am7 | Duration: 7:00
Vibe: Floating, warm, cosmic, hypnotic, non-intrusive

Sections:
  [Intro]      0:00-0:45   Cosmic pad + vinyl crackle + sparse rhodes
  [Build]      0:45-1:45   +brushes, upright bass walks in
  [Flow A]     1:45-3:00   +flute melody, full groove
  [Breakdown]  3:00-3:45   Strip to rhodes solo + deep pad
  [Flow B]     3:45-5:15   Reprise, flute variation, deeper bass
  [Dissolve]   5:15-6:15   Elements fade one by one
  [Outro]      6:15-7:00   Pad tail + crackle → silence
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
# Запустить всё-таки:  AUTODJ_ALLOW_LEGACY=1 python3 render_cosmic_massage.py
# ═══════════════════════════════════════════════════════════════════════════
import os as _os, sys as _sys
if __name__ == "__main__" and not _os.environ.get("AUTODJ_ALLOW_LEGACY"):
    print(__doc__ or "")
    print("\n⚠️  УСТАРЕЛО: render_cosmic_massage.py не использует улучшения P82-P88 "
          "(мотив, аранжировка, уникальная гармония).")
    print("   Рендерь через:  python3 render_track.py <жанр>")
    print("   Форс:           AUTODJ_ALLOW_LEGACY=1 python3 render_cosmic_massage.py\n")
    _sys.exit(3)


import sys, os, logging, numpy as np, soundfile as sf
sys.path.insert(0, "/opt/autodj-mixer")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("cosmic_massage")

SR = 44100
BPM = 82
DUR = 420.0  # 7:00
BAR_S = 60.0 / BPM * 4  # ~2.927s
TOTAL = int(DUR * SR)
SWING = 0.35  # jazzy swing

# Dm scale: D E F G A Bb C
# Jazz chord progression (4 bars loop):
#   Dm7 (D F A C)  → Gm7 (G Bb D F)  → Cmaj7 (C E G B) → Am7 (A C E G)

# MIDI notes for chords (mid register, Rhodes)
RHODES_CHORDS = [
    [50, 53, 57, 60],  # Dm7: D3 F3 A3 C4
    [55, 58, 62, 65],  # Gm7: G3 Bb3 D4 F4
    [48, 52, 55, 59],  # Cmaj7: C3 E3 G3 B3
    [45, 48, 52, 55],  # Am7: A2 C3 E3 G3
]

# Bass roots (walking bass style, 2 notes per bar)
BASS_WALK = [
    [38, 40],  # D2, E2
    [43, 41],  # G2, F2
    [36, 38],  # C2, D2
    [33, 36],  # A1, C2
]

# Flute melody — Dm jazz, 8th notes per bar (0=rest)
FLUTE_A = [
    62, 0, 65, 62, 0, 60, 62, 65,   # D4 _ F4 D4 _ C4 D4 F4
    67, 65, 0, 62, 60, 0, 58, 60,   # G4 F4 _ D4 C4 _ Bb3 C4
    64, 0, 62, 60, 0, 62, 64, 67,   # E4 _ D4 C4 _ D4 E4 G4
    65, 62, 0, 60, 58, 0, 57, 0,    # F4 D4 _ C4 Bb3 _ A3 _
]
FLUTE_B = [
    65, 67, 0, 69, 67, 65, 0, 62,   # F4 G4 _ A4 G4 F4 _ D4
    60, 0, 62, 65, 67, 0, 69, 67,   # C4 _ D4 F4 G4 _ A4 G4
    62, 64, 0, 65, 62, 0, 60, 58,   # D4 E4 _ F4 D4 _ C4 Bb3
    57, 0, 60, 62, 0, 65, 0, 0,     # A3 _ C4 D4 _ F4 _ _
]

# Pad chords (lower, wider voicing for cosmic pad)
PAD_CHORDS = [
    [38, 45, 53, 60],  # Dm: D2 A2 F3 C4
    [43, 50, 58, 65],  # Gm: G2 D3 Bb3 F4
    [36, 43, 52, 59],  # C:  C2 G2 E3 B3
    [33, 40, 48, 55],  # Am: A1 E2 C3 G3
]

# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
SEC = {
    "intro":     (0.0,   45.0),
    "build":     (45.0,  105.0),
    "flow_a":    (105.0, 180.0),
    "breakdown": (180.0, 225.0),
    "flow_b":    (225.0, 315.0),
    "dissolve":  (315.0, 375.0),
    "outro":     (375.0, 420.0),
}

def in_sec(t, name):
    s = SEC[name]
    return s[0] <= t < s[1]

def swing_t(pos, step_s):
    if pos % 2 == 1:
        return pos * step_s + step_s * SWING * 0.5
    return pos * step_s

# ---------------------------------------------------------------------------
# Vinyl crackle generator (noise texture)
# ---------------------------------------------------------------------------
def gen_vinyl_crackle(total_samples, sr, amp=0.015):
    """Low-level vinyl crackle: filtered noise + random clicks."""
    from scipy.signal import butter, lfilter
    noise = np.random.randn(total_samples).astype(np.float32) * amp * 0.3
    # Bandpass 200-3000 Hz
    b, a = butter(2, [200/(sr/2), 3000/(sr/2)], btype='band')
    filtered = lfilter(b, a, noise).astype(np.float32)
    # Random clicks
    n_clicks = total_samples // (sr // 4)  # ~4 per second
    for _ in range(n_clicks):
        pos = np.random.randint(0, total_samples - 100)
        click_len = np.random.randint(5, 30)
        filtered[pos:pos+click_len] += np.random.randn(click_len).astype(np.float32) * amp * 2
    return filtered

# ---------------------------------------------------------------------------
# MIDI events for FluidSynth
# ---------------------------------------------------------------------------
def build_rhodes_events(ch=0):
    """Rhodes chords: whole bar each, velocity varies by section."""
    events = [(0.0, "program", ch, 0, 4)]  # GM 4 = Electric Piano 1
    bar_count = int(DUR / BAR_S) + 1
    for bar in range(bar_count):
        t = bar * BAR_S
        chord = RHODES_CHORDS[bar % 4]
        # Section velocity
        if in_sec(t, "intro"):
            vel = 45 + int((t / SEC["intro"][1]) * 15)
        elif in_sec(t, "breakdown"):
            vel = 70  # solo, louder
        elif in_sec(t, "dissolve"):
            progress = (t - SEC["dissolve"][0]) / (SEC["dissolve"][1] - SEC["dissolve"][0])
            vel = max(30, int(55 * (1 - progress * 0.5)))
        elif in_sec(t, "outro"):
            progress = (t - SEC["outro"][0]) / (SEC["outro"][1] - SEC["outro"][0])
            vel = max(15, int(40 * (1 - progress)))
        else:
            vel = 55
        dur = BAR_S * 0.92
        for note in chord:
            events.append((t, "note_on", ch, note, vel))
            events.append((t + dur, "note_off", ch, note, 0))
    return events

def build_bass_events(ch=1):
    """Upright bass: walking, 2 notes per bar. Only Build through Dissolve."""
    events = [(0.0, "program", ch, 0, 32)]  # GM 32 = Acoustic Bass
    step_s = BAR_S / 2
    bar_count = int(DUR / BAR_S) + 1
    for bar in range(bar_count):
        t_bar = bar * BAR_S
        if not (in_sec(t_bar, "build") or in_sec(t_bar, "flow_a") or
                in_sec(t_bar, "flow_b") or in_sec(t_bar, "dissolve")):
            continue
        walk = BASS_WALK[bar % 4]
        for i, note in enumerate(walk):
            t = t_bar + swing_t(i, step_s)
            if t >= DUR:
                break
            vel = 80 if i == 0 else 65
            if in_sec(t, "dissolve"):
                progress = (t - SEC["dissolve"][0]) / (SEC["dissolve"][1] - SEC["dissolve"][0])
                vel = max(30, int(vel * (1 - progress * 0.7)))
            dur = step_s * 0.85
            events.append((t, "note_on", ch, note, vel))
            events.append((t + dur, "note_off", ch, note, 0))
    return events

def build_flute_events(ch=2):
    """Flute melody: only in Flow A and Flow B sections."""
    events = [(0.0, "program", ch, 0, 73)]  # GM 73 = Flute
    step_s = BAR_S / 8  # 8th notes
    bar_count = int(DUR / BAR_S) + 1

    for bar in range(bar_count):
        t_bar = bar * BAR_S
        if in_sec(t_bar, "flow_a"):
            melody = FLUTE_A
        elif in_sec(t_bar, "flow_b"):
            melody = FLUTE_B
        else:
            continue

        for step in range(len(melody)):
            note = melody[step % len(melody)]
            if note == 0:
                continue
            t = t_bar + swing_t(step, step_s)
            if t >= DUR:
                break
            vel = 70 + (step % 3) * 5  # slight variation
            if in_sec(t, "dissolve"):
                progress = (t - SEC["dissolve"][0]) / (SEC["dissolve"][1] - SEC["dissolve"][0])
                vel = max(25, int(vel * (1 - progress)))
            dur = step_s * 0.75
            events.append((t, "note_on", ch, note, vel))
            events.append((t + dur, "note_off", ch, note, 0))

    return events

def build_brush_events(ch=3):
    """Jazz brushes: GM 0 on ch 9 (drums). Kick on 1,3, brush on 2,4, hats 16ths."""
    events = []
    step_16 = BAR_S / 16
    bar_count = int(DUR / BAR_S) + 1

    for bar in range(bar_count):
        t_bar = bar * BAR_S
        # Only Build through Dissolve (not intro, breakdown, outro)
        if not (in_sec(t_bar, "build") or in_sec(t_bar, "flow_a") or
                in_sec(t_bar, "flow_b")):
            continue
        if in_sec(t_bar, "dissolve"):
            progress = (t_bar - SEC["dissolve"][0]) / (SEC["dissolve"][1] - SEC["dissolve"][0])
            if progress > 0.6:
                continue  # drums gone

        for pos in range(16):
            t = t_bar + swing_t(pos, step_16)
            if t >= DUR:
                break

            # Soft kick on beats 0, 8 (beat 1, 3)
            if pos in [0, 8]:
                vel = 75
                events.append((t, "note_on", 9, 36, vel))
                events.append((t + 0.05, "note_off", 9, 36, 0))

            # Brush snare on beats 4, 12 (beat 2, 4)
            if pos in [4, 12]:
                # Micro-shift +4ms for lazy feel
                t_snare = t + 0.004
                vel = 60
                events.append((t_snare, "note_on", 9, 38, vel))
                events.append((t_snare + 0.08, "note_off", 9, 38, 0))

            # Closed hat: every 16th, ghost notes on even positions
            vel_hat = 35 if pos % 2 == 0 else 50
            # Random jitter +-3ms
            jitter = (hash((bar, pos)) % 7 - 3) * 0.001
            t_hat = t + jitter
            events.append((t_hat, "note_on", 9, 42, vel_hat))
            events.append((t_hat + 0.03, "note_off", 9, 42, 0))

            # Open hat on beat 3 sometimes
            if pos == 8 and bar % 2 == 0:
                events.append((t, "note_on", 9, 46, 40))
                events.append((t + 0.1, "note_off", 9, 46, 0))

    return events

# ---------------------------------------------------------------------------
# Cosmic pad via Faust (DawDreamer)
# ---------------------------------------------------------------------------
def build_pad_events(ch=4):
    """Cosmic pad via FluidSynth: GM 49 (Slow Strings), long chords."""
    events = [(0.0, "program", ch, 0, 49)]  # GM 49 = Slow Strings
    bar_count = int(DUR / BAR_S) + 1

    for bar in range(bar_count):
        t = bar * BAR_S
        chord = PAD_CHORDS[bar % 4]

        if in_sec(t, "intro"):
            vel = 40 + int((t / SEC["intro"][1]) * 20)
        elif in_sec(t, "breakdown"):
            vel = 75  # prominent
        elif in_sec(t, "outro"):
            progress = (t - SEC["outro"][0]) / (SEC["outro"][1] - SEC["outro"][0])
            vel = max(10, int(50 * (1 - progress)))
        elif in_sec(t, "dissolve"):
            vel = 55
        else:
            vel = 45  # background

        dur = BAR_S * 0.97
        for note in chord:
            events.append((t, "note_on", ch, note, vel))
            events.append((t + dur, "note_off", ch, note, 0))

    return events

# ---------------------------------------------------------------------------
# Sidechain from kick
# ---------------------------------------------------------------------------
def build_sidechain_env(brush_events):
    env = np.ones(TOTAL, dtype=np.float32)
    release = int(0.12 * SR)  # 120ms, gentle
    for ev in brush_events:
        if ev[1] != "note_on" or ev[3] != 36:  # kick only
            continue
        s = int(ev[0] * SR)
        end = min(TOTAL, s + release)
        n = end - s
        if n > 0:
            recovery = 0.5 * (1 - np.cos(np.pi * np.arange(n) / n))
            depth = 0.4  # gentle pump
            ducked = 1.0 - depth * (1.0 - recovery)
            env[s:end] = np.minimum(env[s:end], ducked)
    return env

# ---------------------------------------------------------------------------
# Master envelope
# ---------------------------------------------------------------------------
def master_envelope():
    env = np.ones(TOTAL, dtype=np.float32)
    for i in range(TOTAL):
        t = i / SR
        if in_sec(t, "intro"):
            env[i] = min(1.0, (t - SEC["intro"][0]) / 10.0)  # 10s fade in
        elif in_sec(t, "outro"):
            progress = (t - SEC["outro"][0]) / (SEC["outro"][1] - SEC["outro"][0])
            env[i] = max(0.0, 1.0 - progress)
    return env

# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------
def main():
    log.info(f"Cosmic Massage | BPM={BPM} | Dm7 | {DUR:.0f}s | swing={SWING}")

    # Build events
    log.info("Building MIDI events...")
    rhodes_evs = build_rhodes_events(ch=0)
    bass_evs = build_bass_events(ch=1)
    flute_evs = build_flute_events(ch=2)
    brush_evs = build_brush_events()

    pad_evs = build_pad_events(ch=4)

    # All on FluidSynth (pad too -- DawDreamer Faust too slow for 7min polyphony)
    fluid_events = rhodes_evs + bass_evs + flute_evs + brush_evs + pad_evs

    log.info(f"  rhodes: {sum(1 for e in rhodes_evs if e[1]=='note_on')} notes")
    log.info(f"  bass: {sum(1 for e in bass_evs if e[1]=='note_on')} notes")
    log.info(f"  flute: {sum(1 for e in flute_evs if e[1]=='note_on')} notes")
    log.info(f"  brushes: {sum(1 for e in brush_evs if e[1]=='note_on')} hits")
    log.info(f"  pad: {sum(1 for e in pad_evs if e[1]=='note_on')} notes")

    # Render everything via FluidSynth (fast, real samples)
    log.info("Rendering FluidSynth (Rhodes + bass + flute + brushes + pad)...")
    from autodj.generate.backends.fluidsynth import FluidSynthBackend
    with FluidSynthBackend(sample_rate=SR) as backend:
        synth = backend.synth
        synth.program_change(0, 4)   # Electric Piano 1
        synth.program_change(1, 32)  # Acoustic Bass
        synth.program_change(2, 73)  # Flute
        synth.program_change(4, 49)  # Slow Strings (pad)
        # Ch 9 is GM drums by default
        mix = backend.render(fluid_events, DUR)
    log.info(f"  FluidSynth: peak={np.abs(mix).max():.3f}")

    min_len = min(len(mix), TOTAL)
    mix = mix[:min_len]

    # Master envelope
    env = master_envelope()[:min_len]
    mix[:, 0] *= env
    mix[:, 1] *= env

    # Master: gentle compression + normalize
    log.info("Mastering...")
    mix = np.tanh(mix * 0.9) / 0.9  # gentle saturation
    peak = np.abs(mix).max()
    if peak > 1e-6:
        mix *= (10 ** (-1.0 / 20)) / peak  # -1dB (more headroom for lounge)

    # Save
    out_wav = "/tmp/cosmic_massage.wav"
    out_mp3 = "/tmp/cosmic_massage.mp3"
    sf.write(out_wav, mix, SR)
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 320k -q:a 0 "{out_mp3}" 2>/dev/null')

    size_mb = os.path.getsize(out_mp3) / 1024 / 1024
    log.info(f"Done: {out_mp3} ({size_mb:.1f} MB, {min_len/SR:.0f}s)")
    return out_mp3

if __name__ == "__main__":
    mp3 = main()
    print(f"\nOutput: {mp3}")
