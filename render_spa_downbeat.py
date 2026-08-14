#!/usr/bin/env python3
"""
render_spa_downbeat.py — 10:10 · 85 BPM · C minor
Deep indie downbeat breakbeat for spa lounge

Architecture:
- FluidSynth GM instruments (via instrument.py) — real sampled sounds
- Pedalboard effects (via synthcore.py) — professional reverb/delay/chorus
- Smooth rcos_env automation — no hard section cuts, all layers continuous
- No background noise layer
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
# Запустить всё-таки:  AUTODJ_ALLOW_LEGACY=1 python3 render_spa_downbeat.py
# ═══════════════════════════════════════════════════════════════════════════
import os as _os, sys as _sys
if __name__ == "__main__" and not _os.environ.get("AUTODJ_ALLOW_LEGACY"):
    print(__doc__ or "")
    print("\n⚠️  УСТАРЕЛО: render_spa_downbeat.py не использует улучшения P82-P88 "
          "(мотив, аранжировка, уникальная гармония).")
    print("   Рендерь через:  python3 render_track.py <жанр>")
    print("   Форс:           AUTODJ_ALLOW_LEGACY=1 python3 render_spa_downbeat.py\n")
    _sys.exit(3)

import sys, os, time
sys.path.insert(0, '/opt/autodj-mixer')

import numpy as np
from autodj.generate.instrument import render_notes, render_chords, render_drums
from autodj.generate.music_theory import (
    resolve_progression, voice_lead_sequence, get_reverb,
)
from autodj.generate.synthcore import (
    apply_reverb, apply_delay, apply_chorus, apply_compressor,
    master_chain, mono_to_stereo, normalize_master,
)

SR     = 44100
BPM    = 85
DUR    = 10 * 60 + 10           # 610 s
TOTAL  = int(DUR * SR)
BEAT   = 60.0 / BPM             # ~0.706 s
BAR    = BEAT * 4               # ~2.824 s
ROOT   = 60                     # C4
SWING  = 0.24                   # 24% swing on odd 16th steps

# Chord progression: lounge = i7 iv7 v7 i7 (Cm7 Fm7 Gm7 Cm7)
CHORDS = voice_lead_sequence(resolve_progression(ROOT, "lounge"))
CHORD_BARS = 8                  # bars per chord
CHORD_DUR  = BAR * CHORD_BARS   # ~22.6s

# C minor scale notes across octaves
SCALE = [48, 51, 53, 55, 58,    # C3 Eb3 F3 G3 Bb3
         60, 63, 65, 67, 70,    # C4 Eb4 F4 G4 Bb4
         72, 75, 77, 79, 82]    # C5 Eb5 F5 G5 Bb5


# ── smooth envelope ────────────────────────────────────────────────────────

def rcos_env(on, peak, off, out):
    """Raised-cosine volume automation over full track (seconds)."""
    env = np.zeros(TOTAL, dtype=np.float32)
    i0, i1, i2, i3 = (min(int(x * SR), TOTAL) for x in (on, peak, off, out))
    if i1 > i0:
        n = i1 - i0
        env[i0:i1] = (0.5 - 0.5 * np.cos(np.pi * np.arange(n) / n)).astype(np.float32)
    env[i1:i2] = 1.0
    if i3 > i2:
        n = i3 - i2
        env[i2:i3] = (0.5 + 0.5 * np.cos(np.pi * np.arange(n) / n)).astype(np.float32)
    return env


def apply_env(buf2d, env):
    """Multiply stereo buffer by mono envelope."""
    n = min(len(buf2d), len(env))
    out = buf2d[:n].copy()
    out[:, 0] *= env[:n]
    out[:, 1] *= env[:n]
    return out


def swung_time(bar_start, step_16, swing=SWING):
    """Time of a 16th note step within a bar, with swing on odd steps."""
    step_dur = BAR / 16
    t = bar_start + step_16 * step_dur
    if step_16 % 2 == 1:
        t += step_dur * swing
    return t


# ── build note events ───────────────────────────────────────────────────────

def build_kalimba_events():
    """Sparse arpeggio from chord tones, randomized timing."""
    print("  building kalimba events...")
    rng = np.random.RandomState(42)
    events = []
    t = 15.0

    while t < 555:
        ci = int(t / CHORD_DUR) % len(CHORDS)
        chord = CHORDS[ci]
        root = chord[0] % 12
        # Notes that fit the current chord
        available = [n for n in SCALE if n % 12 in [root, (root + 3) % 12, (root + 7) % 12]]
        if not available:
            available = SCALE[5:10]

        phrase_len = rng.randint(3, 7)
        for _ in range(phrase_len):
            midi = int(rng.choice(available))
            if rng.random() < 0.15:
                midi = min(midi + 12, 96)
            vel = rng.randint(55, 95)
            dur = rng.uniform(1.5, 4.0)
            events.append((t, midi, vel, dur))
            t += BEAT * rng.uniform(0.4, 0.85)
            if t >= 555:
                break
        t += BAR * rng.uniform(0.5, 2.5)

    return events


def build_vibes_events():
    """Vibraphone rhythmic accents, enters mid-track."""
    print("  building vibraphone events...")
    rng = np.random.RandomState(13)
    events = []
    t = 130.0

    while t < 490:
        ci = int(t / CHORD_DUR) % len(CHORDS)
        chord = CHORDS[ci]
        n_notes = rng.randint(2, 5)
        for _ in range(n_notes):
            midi = int(rng.choice([n for n in SCALE[3:12]]))
            vel = rng.randint(45, 80)
            dur = rng.uniform(1.5, 3.5)
            events.append((t, midi, vel, dur))
            t += BEAT * rng.uniform(0.5, 1.0)
            if t >= 490:
                break
        t += BAR * rng.uniform(1.2, 3.5)

    return events


def build_flute_events():
    """Pan flute melody, higher register, sparse phrases."""
    print("  building flute events...")
    rng = np.random.RandomState(77)
    events = []
    t = 80.0
    FL_NOTES = [n for n in SCALE if n >= 72]  # C5+

    while t < 510:
        phrase_bars = rng.randint(2, 5)
        phrase_end = t + BAR * phrase_bars

        while t < phrase_end and t < 510:
            midi = int(rng.choice(FL_NOTES))
            vel = rng.randint(50, 85)
            dur = rng.uniform(0.5, 2.5)
            events.append((t, midi, vel, dur))
            t += dur * rng.uniform(0.7, 1.1)

        t += BAR * rng.uniform(1.5, 4.0)

    return events


def build_pad_events():
    """Slow strings pad, full chord per change, 2s overlap."""
    print("  building pad events...")
    events = []
    t = 0.0
    ci = 0
    overlap = 2.5  # seconds overlap between chords

    while t < DUR - 1:
        chord = CHORDS[ci % len(CHORDS)]
        dur = min(CHORD_DUR + overlap, DUR - t)
        vel = 58
        events.append((t, chord, vel, dur))
        ci += 1
        t += CHORD_DUR

    return events


def build_bass_events():
    """Fretless bass: root on beat 1, optional 5th on beat 3."""
    print("  building bass events...")
    rng = np.random.RandomState(99)
    events = []
    t = 25.0

    while t < 550:
        ci = int(t / CHORD_DUR) % len(CHORDS)
        root = CHORDS[ci][0] - 12  # one octave down
        vel = rng.randint(70, 100)
        dur = BEAT * rng.uniform(0.65, 1.1)
        events.append((t, root, vel, dur))

        if rng.random() > 0.4:
            fifth = root + 7
            t2 = t + BEAT * 2
            vel2 = rng.randint(60, 85)
            dur2 = BEAT * rng.uniform(0.5, 0.9)
            events.append((t2, fifth, vel2, dur2))

        t += BAR

    return events


def build_drum_events():
    """Breakbeat pattern with swing, velocity automation."""
    print("  building drum events...")
    rng = np.random.RandomState(11)
    hits = []
    t = 0.0

    while t < DUR - 0.5:
        # Intensity curve: quiet at edges, full in middle
        if   t < 60:   v = 0.30 + 0.30 * (t / 60)
        elif t < 160:  v = 0.60 + 0.35 * ((t - 60) / 100)
        elif t < 530:  v = 0.95
        elif t < 610:  v = 0.95 - 0.60 * ((t - 530) / 80)
        else:          v = 0.35

        for bar_offset in range(2):
            bs = t + bar_offset * BAR

            # Kick pattern
            kicks = [0, 8] if bar_offset == 0 else [0, 3, 10, 14]
            for ks in kicks:
                ht = swung_time(bs, ks)
                vel = int(np.clip(v * rng.randint(95, 120), 30, 127))
                hits.append((ht, "kick", vel))

            # Snare
            for ss in [4, 10]:
                ht = swung_time(bs, ss)
                vel = int(np.clip(v * rng.randint(75, 100), 25, 127))
                hits.append((ht, "snare", vel))

            # Hats: every 2nd 16th step
            for hs in range(0, 16, 2):
                use_open = (hs in [6, 14]) and bar_offset == 1
                drum_name = "open_hat" if use_open else "closed_hat"
                vel = int(np.clip(v * rng.randint(55, 85), 20, 120))
                hits.append((swung_time(bs, hs), drum_name, vel))

        t += BAR * 2

    return hits


# ── render & mix ────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print(f"render_spa_downbeat.py -- {DUR // 60:.0f}:{DUR % 60:02.0f} / {BPM} BPM / C minor")
    print(f"FluidSynth + Pedalboard pipeline")

    # 1. Build events
    kal_ev  = build_kalimba_events()
    vib_ev  = build_vibes_events()
    fl_ev   = build_flute_events()
    pad_ev  = build_pad_events()
    bass_ev = build_bass_events()
    drum_ev = build_drum_events()

    print(f"  events: kalimba={len(kal_ev)} vibes={len(vib_ev)} "
          f"flute={len(fl_ev)} pad={len(pad_ev)} bass={len(bass_ev)} drums={len(drum_ev)}")

    # 2. Render each layer via FluidSynth (real GM samples)
    print("  rendering via FluidSynth...")

    t1 = time.time()
    kal_buf  = render_notes("kalimba", kal_ev, DUR, SR)
    print(f"    kalimba: {time.time()-t1:.1f}s")

    t1 = time.time()
    vib_buf  = render_notes("vibraphone", vib_ev, DUR, SR)
    print(f"    vibraphone: {time.time()-t1:.1f}s")

    t1 = time.time()
    fl_buf   = render_notes("pan_flute", fl_ev, DUR, SR)
    print(f"    pan_flute: {time.time()-t1:.1f}s")

    t1 = time.time()
    pad_buf  = render_chords("slow_strings", pad_ev, DUR, SR)
    print(f"    slow_strings: {time.time()-t1:.1f}s")

    t1 = time.time()
    bass_buf = render_notes("fretless_bass", bass_ev, DUR, SR)
    print(f"    fretless_bass: {time.time()-t1:.1f}s")

    t1 = time.time()
    drum_buf = render_drums(drum_ev, DUR, SR)
    print(f"    drums: {time.time()-t1:.1f}s")

    # 3. Apply per-layer Pedalboard effects
    print("  applying effects (Pedalboard)...")

    # Kalimba: warm reverb + light delay
    kal_buf = apply_reverb(kal_buf, SR, room_size=0.7, wet=0.35, damping=0.45)
    kal_buf = apply_delay(kal_buf, SR, delay_ms=BEAT * 500, feedback=0.25, wet=0.15)

    # Vibraphone: wider reverb + chorus for stereo spread
    vib_buf = apply_reverb(vib_buf, SR, room_size=0.75, wet=0.40, damping=0.40)
    vib_buf = apply_chorus(vib_buf, SR, rate_hz=0.4, depth=0.3, wet=0.35)

    # Flute: long reverb (airy)
    fl_buf = apply_reverb(fl_buf, SR, room_size=0.85, wet=0.45, damping=0.35)

    # Pad: large room reverb + chorus for width
    pad_buf = apply_reverb(pad_buf, SR, room_size=0.80, wet=0.30, damping=0.50)
    pad_buf = apply_chorus(pad_buf, SR, rate_hz=0.3, depth=0.25, wet=0.30)

    # Bass: subtle room, no delay
    bass_buf = apply_reverb(bass_buf, SR, room_size=0.3, wet=0.10, damping=0.7)

    # Drums: tight room
    drum_buf = apply_reverb(drum_buf, SR, room_size=0.25, wet=0.12, damping=0.6)
    drum_buf = apply_compressor(drum_buf, SR, threshold_db=-10, ratio=3,
                                 attack_ms=3, release_ms=100)

    # 4. Volume automation (smooth raised-cosine envelopes)
    print("  mixing with automation...")

    kal_env  = rcos_env(15,  45, 555, 610)   # kalimba: 0:15 in, 9:15 out
    vib_env  = rcos_env(130, 200, 490, 555)  # vibes: 2:10 in, 8:10 out
    fl_env   = rcos_env(80,  150, 510, 580)  # flute: 1:20 in, 8:30 out
    pad_env  = rcos_env(0,   25, 560, 610)   # pad: always, fade at ends
    bass_env = rcos_env(25,  55, 550, 600)   # bass: 0:25 in, 9:10 out
    drum_env = rcos_env(5,   35, 565, 608)   # drums: 0:05 in, 9:25 out

    kal_buf  = apply_env(kal_buf,  kal_env)
    vib_buf  = apply_env(vib_buf,  vib_env)
    fl_buf   = apply_env(fl_buf,   fl_env)
    pad_buf  = apply_env(pad_buf,  pad_env)
    bass_buf = apply_env(bass_buf, bass_env)
    drum_buf = apply_env(drum_buf, drum_env)

    # Ensure all buffers same length
    def trim(buf):
        if len(buf) >= TOTAL:
            return buf[:TOTAL]
        return np.pad(buf, ((0, TOTAL - len(buf)), (0, 0)))

    mix = np.zeros((TOTAL, 2), dtype=np.float32)
    mix += trim(kal_buf)  * 0.55
    mix += trim(vib_buf)  * 0.45
    mix += trim(fl_buf)   * 0.50
    mix += trim(pad_buf)  * 0.52
    mix += trim(bass_buf) * 0.58
    mix += trim(drum_buf) * 0.50

    # 5. Master fade in / out
    fi = int(10.0 * SR)
    fo = int(22.0 * SR)
    mix[:fi]  *= np.linspace(0, 1, fi, dtype=np.float32)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)[:, None]

    # 6. Master chain (soft saturation + compressor + normalize)
    print("  mastering...")
    mix = master_chain(mix, SR)

    # Spa target: -3 dBFS (quieter than club)
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= (10 ** (-3.0 / 20)) / peak

    # 7. Export
    os.makedirs("/opt/autodj-mixer/output", exist_ok=True)
    wav_path = "/opt/autodj-mixer/output/spa_downbeat.wav"
    mp3_path = "/opt/autodj-mixer/output/spa_downbeat.mp3"

    import soundfile as sf
    print("  writing WAV...")
    sf.write(wav_path, mix, SR)

    print("  encoding MP3 320k...")
    os.system(f'ffmpeg -y -i "{wav_path}" -b:a 320k "{mp3_path}" 2>/dev/null')

    if os.path.exists(wav_path):
        os.remove(wav_path)

    elapsed = time.time() - t0
    sz = os.path.getsize(mp3_path) / 1024 / 1024
    print(f"\n  done in {elapsed:.1f}s -- {sz:.1f} MB -- {mp3_path}")
    return mp3_path


if __name__ == "__main__":
    main()
