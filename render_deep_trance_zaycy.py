#!/usr/bin/env python3
"""
render_deep_trance_zaycy.py -- Deep Trance 10 min
Melody from "Песня про зайцев" (Бриллиантовая рука, А.Зацепин)

"А нам всё равно, а нам всё равно,
 Пусть боимся мы волка и сову,
 Дело есть у нас -- в самый жуткий час
 Мы волшебную косим трын-траву."

Key: Am | BPM: 138 | Duration: 10:00

Sections:
  [Intro]      0:00-1:00   Pad swell + filtered melody tease
  [Build]      1:00-2:15   +kick, arpeggios, melody unfolds
  [Drop A]     2:15-4:00   Full trance, melody prominent
  [Break]      4:00-5:00   Strip down, piano melody solo
  [Build 2]    5:00-6:00   Rising tension, snare rolls
  [Drop B]     6:00-8:00   Peak energy, melody variation
  [Breakdown]  8:00-9:00   Ambient, melody fragments
  [Outro]      9:00-10:00  Fade elements, pad tail
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
# Запустить всё-таки:  AUTODJ_ALLOW_LEGACY=1 python3 render_deep_trance_zaycy.py
# ═══════════════════════════════════════════════════════════════════════════
import os as _os, sys as _sys
if __name__ == "__main__" and not _os.environ.get("AUTODJ_ALLOW_LEGACY"):
    print(__doc__ or "")
    print("\n⚠️  УСТАРЕЛО: render_deep_trance_zaycy.py не использует улучшения P82-P88 "
          "(мотив, аранжировка, уникальная гармония).")
    print("   Рендерь через:  python3 render_track.py <жанр>")
    print("   Форс:           AUTODJ_ALLOW_LEGACY=1 python3 render_deep_trance_zaycy.py\n")
    _sys.exit(3)


import sys, os, logging, numpy as np, soundfile as sf
sys.path.insert(0, "/opt/autodj-mixer")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("deep_trance")

SR = 44100
BPM = 138
DUR = 600.0  # 10:00
BAR_S = 60.0 / BPM * 4  # ~1.739s
BEAT_S = 60.0 / BPM      # ~0.435s
TOTAL = int(DUR * SR)

# --- "Песня про зайцев" melody in Am ---
# "А нам всё рав-но, а нам всё рав-но..."
# Simplified to MIDI notes in Am (A3=57)
# Original melody approx: A A B C C B A | A A B C C B A | E E F G G F E | A...

# Main melody -- 2 bars (8 beats), repeating phrase
# "А нам всё рав-но" = pickup + descending
MELODY_A = [
    # bar 1: "А нам всё рав-но, а нам всё рав-но"
    (0.0,   69, 0.4),   # A4
    (0.5,   69, 0.3),   # A4
    (1.0,   71, 0.4),   # B4
    (1.5,   72, 0.8),   # C5
    (2.5,   71, 0.3),   # B4
    (3.0,   69, 0.8),   # A4
    # bar 2: repeat
    (4.0,   69, 0.4),   # A4
    (4.5,   69, 0.3),   # A4
    (5.0,   71, 0.4),   # B4
    (5.5,   72, 0.8),   # C5
    (6.5,   71, 0.3),   # B4
    (7.0,   69, 0.8),   # A4
]

# Second phrase: "Пусть боимся мы волка и сову"
MELODY_B = [
    (0.0,   64, 0.4),   # E4
    (0.5,   64, 0.3),   # E4
    (1.0,   65, 0.4),   # F4
    (1.5,   67, 0.8),   # G4
    (2.5,   65, 0.3),   # F4
    (3.0,   64, 0.8),   # E4
    # "Дело есть у нас"
    (4.0,   67, 0.4),   # G4
    (4.5,   69, 0.3),   # A4
    (5.0,   71, 0.4),   # B4
    (5.5,   72, 0.6),   # C5
    (6.0,   71, 0.3),   # B4
    (6.5,   69, 0.4),   # A4
    (7.0,   67, 0.8),   # G4
]

# Trance arpeggio pattern (Am - F - C - G, classic trance progression)
ARP_CHORDS = [
    [57, 60, 64],  # Am: A3 C4 E4
    [53, 57, 60],  # F:  F3 A3 C4
    [48, 52, 55],  # C:  C3 E3 G3
    [55, 59, 62],  # G:  G3 B3 D4
]

# Pad chords (lower voicing)
PAD_CHORDS = [
    [45, 48, 52, 57],  # Am: A2 C3 E3 A3
    [41, 45, 48, 53],  # F:  F2 A2 C3 F3
    [36, 40, 43, 48],  # C:  C2 E2 G2 C3
    [43, 47, 50, 55],  # G:  G2 B2 D3 G3
]

# Bass notes
BASS_NOTES = [45, 41, 36, 43]  # A2, F2, C2, G2

SEC = {
    "intro":     (0.0,   60.0),
    "build":     (60.0,  135.0),
    "drop_a":    (135.0, 240.0),
    "break_":    (240.0, 300.0),
    "build2":    (300.0, 360.0),
    "drop_b":    (360.0, 480.0),
    "breakdown": (480.0, 540.0),
    "outro":     (540.0, 600.0),
}

def in_sec(t, name):
    s = SEC[name]
    return s[0] <= t < s[1]

def section_at(t):
    for name, (s, e) in SEC.items():
        if s <= t < e:
            return name
    return "outro"

# ---------------------------------------------------------------------------
# MIDI event builders
# ---------------------------------------------------------------------------

def build_melody_events(ch=3):
    """Melody: Песня про зайцев lead. GM 81 = Lead 1 (square)."""
    events = [(0.0, "program", ch, 0, 80)]  # GM 81 (0-indexed=80) = Lead 1 square
    phrase_dur = 8 * BEAT_S  # 8 beats per phrase

    t = 0.0
    while t < DUR:
        sec = section_at(t)
        if sec in ("drop_a", "drop_b", "break_"):
            # Play melody
            use_b = (int(t / phrase_dur) % 4) >= 2  # alternate A/B every 2 phrases
            melody = MELODY_B if use_b else MELODY_A
            for offset, note, dur_beats in melody:
                note_t = t + offset * BEAT_S
                if note_t >= DUR:
                    break
                dur = dur_beats * BEAT_S
                if sec == "break_":
                    vel = 85  # solo, prominent
                elif sec == "drop_b":
                    vel = 95  # peak
                else:
                    vel = 90
                events.append((note_t, "note_on", ch, note, vel))
                events.append((note_t + dur * 0.9, "note_off", ch, note, 0))
            t += phrase_dur
        elif sec in ("intro", "build", "build2"):
            # Melody tease: just first 3 notes, filtered feel (lower velocity)
            if sec == "intro" and t > 30.0:
                for offset, note, dur_beats in MELODY_A[:3]:
                    note_t = t + offset * BEAT_S
                    if note_t >= DUR:
                        break
                    dur = dur_beats * BEAT_S
                    vel = 45
                    events.append((note_t, "note_on", ch, note, vel))
                    events.append((note_t + dur * 0.9, "note_off", ch, note, 0))
            elif sec in ("build", "build2"):
                for offset, note, dur_beats in MELODY_A[:6]:
                    note_t = t + offset * BEAT_S
                    if note_t >= DUR:
                        break
                    dur = dur_beats * BEAT_S
                    vel = 60 if sec == "build" else 70
                    events.append((note_t, "note_on", ch, note, vel))
                    events.append((note_t + dur * 0.9, "note_off", ch, note, 0))
            t += phrase_dur
        elif sec == "breakdown":
            # Sparse fragments
            if int(t / phrase_dur) % 3 == 0:
                for offset, note, dur_beats in MELODY_A[:2]:
                    note_t = t + offset * BEAT_S
                    vel = 50
                    events.append((note_t, "note_on", ch, note, vel))
                    events.append((note_t + dur_beats * BEAT_S * 0.9, "note_off", ch, note, 0))
            t += phrase_dur
        else:
            t += phrase_dur

    return events

def build_kick_events():
    """Four-on-the-floor trance kick. Only Build through Drop B."""
    events = []
    t = 0.0
    while t < DUR:
        sec = section_at(t)
        if sec in ("build", "drop_a", "build2", "drop_b"):
            vel = 100 if sec in ("drop_a", "drop_b") else 85
            events.append((t, "note_on", 9, 36, vel))
            events.append((t + 0.04, "note_off", 9, 36, 0))
        t += BEAT_S
    return events

def build_hat_events():
    """Off-beat open hat (trance style) + 16th closed hats in drops."""
    events = []
    step_16 = BEAT_S / 4
    t = 0.0
    while t < DUR:
        sec = section_at(t)
        if sec in ("build", "drop_a", "build2", "drop_b"):
            # Off-beat open hat
            t_off = t + BEAT_S / 2
            if t_off < DUR:
                vel = 70 if sec in ("drop_a", "drop_b") else 55
                events.append((t_off, "note_on", 9, 46, vel))
                events.append((t_off + 0.06, "note_off", 9, 46, 0))
            # 16th closed hats in drops
            if sec in ("drop_a", "drop_b"):
                for i in range(4):
                    t16 = t + i * step_16
                    if t16 < DUR:
                        vel_h = 40 if i % 2 == 0 else 30
                        events.append((t16, "note_on", 9, 42, vel_h))
                        events.append((t16 + 0.02, "note_off", 9, 42, 0))
        t += BEAT_S
    return events

def build_clap_events():
    """Clap on beats 2 and 4."""
    events = []
    beat = 0
    t = 0.0
    while t < DUR:
        sec = section_at(t)
        if sec in ("drop_a", "drop_b", "build2"):
            if beat % 4 in (1, 3):  # beats 2 and 4
                vel = 80
                events.append((t, "note_on", 9, 39, vel))  # hand clap
                events.append((t + 0.05, "note_off", 9, 39, 0))
        # Snare roll in build2 last 8 bars
        if sec == "build2":
            progress = (t - SEC["build2"][0]) / (SEC["build2"][1] - SEC["build2"][0])
            if progress > 0.7:
                # Accelerating snare roll
                roll_step = BEAT_S / (4 + int(progress * 8))
                for i in range(int(BEAT_S / roll_step)):
                    tr = t + i * roll_step
                    if tr < DUR:
                        events.append((tr, "note_on", 9, 38, 60))
                        events.append((tr + 0.03, "note_off", 9, 38, 0))
        beat += 1
        t += BEAT_S
    return events

def build_bass_events(ch=1):
    """Trance bass: octave bounce pattern. GM 39 = Synth Bass 2."""
    events = [(0.0, "program", ch, 0, 38)]  # GM 39 = Synth Bass 2
    bar_count = int(DUR / BAR_S) + 1
    step_8 = BEAT_S / 2  # 8th notes

    for bar in range(bar_count):
        t_bar = bar * BAR_S
        sec = section_at(t_bar)
        if sec not in ("build", "drop_a", "build2", "drop_b"):
            continue

        root = BASS_NOTES[bar % 4]
        # Trance bass pattern: root-octave bounce on 8ths
        for i in range(8):
            t = t_bar + i * step_8
            if t >= DUR:
                break
            note = root if i % 2 == 0 else root + 12
            vel = 90 if sec in ("drop_a", "drop_b") else 70
            dur = step_8 * 0.7
            events.append((t, "note_on", ch, note, vel))
            events.append((t + dur, "note_off", ch, note, 0))

    return events

def build_arp_events(ch=2):
    """Trance arpeggio. GM 82 = Lead 2 (sawtooth)."""
    events = [(0.0, "program", ch, 0, 81)]  # GM 82 = Lead 2 sawtooth
    step_16 = BEAT_S / 4
    bar_count = int(DUR / BAR_S) + 1

    for bar in range(bar_count):
        t_bar = bar * BAR_S
        sec = section_at(t_bar)
        if sec not in ("build", "drop_a", "build2", "drop_b", "breakdown"):
            continue

        chord = ARP_CHORDS[bar % 4]
        # 16th note arpeggios, cycling through chord tones + octave
        arp_notes = chord + [n + 12 for n in chord]  # 6 notes cycle
        for i in range(16):
            t = t_bar + i * step_16
            if t >= DUR:
                break
            note = arp_notes[i % len(arp_notes)]
            if sec == "breakdown":
                vel = 35
            elif sec in ("drop_a", "drop_b"):
                vel = 65
            else:
                vel = 50
            dur = step_16 * 0.6
            events.append((t, "note_on", ch, note, vel))
            events.append((t + dur, "note_off", ch, note, 0))

    return events

def build_pad_events(ch=4):
    """Trance pad: long sustained chords. GM 90 = Pad 2 (warm)."""
    events = [(0.0, "program", ch, 0, 89)]  # GM 90 = Pad 2 warm
    bar_count = int(DUR / BAR_S) + 1

    for bar in range(bar_count):
        t = bar * BAR_S
        sec = section_at(t)
        chord = PAD_CHORDS[bar % 4]

        if sec == "intro":
            vel = 50 + int((t / SEC["intro"][1]) * 20)
        elif sec in ("break_", "breakdown"):
            vel = 75
        elif sec == "outro":
            progress = (t - SEC["outro"][0]) / (SEC["outro"][1] - SEC["outro"][0])
            vel = max(10, int(60 * (1 - progress)))
        elif sec in ("drop_a", "drop_b"):
            vel = 55  # behind lead
        else:
            vel = 50

        dur = BAR_S * 0.95
        for note in chord:
            events.append((t, "note_on", ch, note, vel))
            events.append((t + dur, "note_off", ch, note, 0))

    return events

def build_piano_break_events(ch=5):
    """Piano melody in the break section. GM 1 = Acoustic Grand Piano."""
    events = [(0.0, "program", ch, 0, 0)]  # GM 1 = Piano
    phrase_dur = 8 * BEAT_S
    t = SEC["break_"][0]

    while t < SEC["break_"][1]:
        use_b = (int((t - SEC["break_"][0]) / phrase_dur) % 2) == 1
        melody = MELODY_B if use_b else MELODY_A
        for offset, note, dur_beats in melody:
            note_t = t + offset * BEAT_S
            if note_t >= SEC["break_"][1]:
                break
            dur = dur_beats * BEAT_S
            events.append((note_t, "note_on", ch, note, 80))
            events.append((note_t + dur * 0.85, "note_off", ch, note, 0))
        t += phrase_dur

    return events

# ---------------------------------------------------------------------------
# Sidechain envelope
# ---------------------------------------------------------------------------
def build_sidechain_env(kick_events):
    env = np.ones(TOTAL, dtype=np.float32)
    release = int(0.08 * SR)  # 80ms, punchy trance sidechain
    for ev in kick_events:
        if ev[1] != "note_on":
            continue
        s = int(ev[0] * SR)
        end = min(TOTAL, s + release)
        n = end - s
        if n > 0:
            recovery = 0.5 * (1 - np.cos(np.pi * np.arange(n) / n))
            depth = 0.6
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
            env[i] = min(1.0, (t - SEC["intro"][0]) / 15.0)  # 15s fade in
        elif in_sec(t, "outro"):
            progress = (t - SEC["outro"][0]) / (SEC["outro"][1] - SEC["outro"][0])
            env[i] = max(0.0, 1.0 - progress)
    return env

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info(f"Deep Trance Zaycy | BPM={BPM} | Am | {DUR:.0f}s")

    log.info("Building MIDI events...")
    melody_evs = build_melody_events(ch=3)
    kick_evs = build_kick_events()
    hat_evs = build_hat_events()
    clap_evs = build_clap_events()
    bass_evs = build_bass_events(ch=1)
    arp_evs = build_arp_events(ch=2)
    pad_evs = build_pad_events(ch=4)
    piano_evs = build_piano_break_events(ch=5)

    all_events = melody_evs + kick_evs + hat_evs + clap_evs + bass_evs + arp_evs + pad_evs + piano_evs

    for name, evs in [("melody", melody_evs), ("kick", kick_evs), ("hat", hat_evs),
                       ("clap", clap_evs), ("bass", bass_evs), ("arp", arp_evs),
                       ("pad", pad_evs), ("piano", piano_evs)]:
        n = sum(1 for e in evs if len(e) > 1 and e[1] == "note_on")
        log.info(f"  {name}: {n} notes")

    log.info("Rendering FluidSynth...")
    from autodj.generate.backends.fluidsynth import FluidSynthBackend
    with FluidSynthBackend(sample_rate=SR) as backend:
        synth = backend.synth
        synth.program_change(1, 38)   # Synth Bass 2
        synth.program_change(2, 81)   # Lead 2 sawtooth (arp)
        synth.program_change(3, 80)   # Lead 1 square (melody)
        synth.program_change(4, 89)   # Pad 2 warm
        synth.program_change(5, 0)    # Piano
        mix = backend.render(all_events, DUR)
    log.info(f"  FluidSynth: peak={np.abs(mix).max():.3f}")

    min_len = min(len(mix), TOTAL)
    mix = mix[:min_len]

    # Sidechain on everything except kick
    log.info("Applying trance sidechain...")
    sc_env = build_sidechain_env(kick_evs)[:min_len]
    # Apply only to non-kick channels (mix already has everything, apply gentle)
    # Since we can't separate channels post-render, apply lighter sidechain to full mix
    sc_mix = sc_env * 0.5 + 0.5  # softer version: 50% depth on mixed signal
    mix[:, 0] *= sc_mix
    mix[:, 1] *= sc_mix

    # Master envelope
    env = master_envelope()[:min_len]
    mix[:, 0] *= env
    mix[:, 1] *= env

    # Master
    log.info("Mastering...")
    mix = np.tanh(mix * 1.2) / 1.2  # harder saturation for trance
    peak = np.abs(mix).max()
    if peak > 1e-6:
        mix *= (10 ** (-0.5 / 20)) / peak  # -0.5dB, louder master for trance

    out_wav = "/tmp/deep_trance_zaycy.wav"
    out_mp3 = "/tmp/deep_trance_zaycy.mp3"
    sf.write(out_wav, mix, SR)
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 320k -q:a 0 "{out_mp3}" 2>/dev/null')

    size_mb = os.path.getsize(out_mp3) / 1024 / 1024
    log.info(f"Done: {out_mp3} ({size_mb:.1f} MB, {min_len/SR:.0f}s)")
    return out_mp3

if __name__ == "__main__":
    mp3 = main()
    print(f"\nOutput: {mp3}")
