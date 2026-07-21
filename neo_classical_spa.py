#!/usr/bin/env python3
"""
Neo-Classical Spa Resort — Acoustic Lounge / Downtempo
Duration: 15:00 (900s) | BPM: 72 | Key: E minor
Mixed backend: FluidSynth (piano, cello, harp) + synthcore (kick, sub, pad)
"""
import os, sys, math, time, logging, random
import numpy as np

sys.path.insert(0, '/opt/autodj-mixer')
os.chdir('/opt/autodj-mixer')

from autodj.generate.backends.fluidsynth import (
    FluidSynthBackend, find_sf2, GM_DRUMS,
    build_melody_events, build_chord_events,
)
from autodj.generate.synthcore import (
    sine_wave, sawtooth_bl, lpf, hpf, adsr,
    apply_reverb, apply_compressor, normalize_master,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('neoclassical')

BPM = 72
SR = 44100
SWING = 0.10  # 10% swing
BAR_S = 60.0 / BPM * 4          # ~3.33 s
BEAT_S = BAR_S / 4               # ~0.833 s
DURATION_S = 900                  # 15:00
N_SAMPLES = int(DURATION_S * SR)

# E minor scale (natural: E F# G A B C D E)
def e_min(octave=3):
    e = 329.63 * (2 ** (octave - 4))
    return {
        'E': e, 'F#': e * 2**(2/12), 'G': e * 2**(3/12),
        'A': e * 2**(5/12), 'B': e * 2**(7/12),
        'C': e * 2**(8/12), 'D': e * 2**(10/12),
    }
E2 = e_min(2); E3 = e_min(3); E4 = e_min(4)
E5 = e_min(5); E6 = e_min(6)

# Piano chords (jazz/neo-classical voicings) → MIDI note lists
CHORDS = {
    'Em7':  [40, 43, 47, 50, 54, 57],      # E2 G2 B2 E3 G3 B3
    'Am9':  [45, 48, 52, 55, 59, 64],      # A2 C3 E3 A3 C4 E4
    'Cmaj7':[48, 52, 55, 59, 64, 67],      # C3 E3 G3 B3 E4 G4
    'D9sus4':[38, 43, 47, 50, 52, 57],     # D2 G2 B2 E3 G3 B3
    'Bm7':  [35, 38, 42, 47, 50, 54],      # B1 E2 A2 B2 E3 G3
    'F#m7b5':[42, 45, 48, 53, 56, 60],    # F#2 A2 C3 F3 A3 C4
    'Gmaj9':[43, 47, 50, 54, 59, 62],     # G2 B2 D3 G3 B3 D4
    'E7sus4':[40, 42, 47, 50, 54, 57],    # E2 G2 B2 E3 G3 B3
}

CHORD_PROG = ['Em7', 'Am9', 'Cmaj7', 'D9sus4',
              'Bm7', 'F#m7b5', 'Gmaj9', 'E7sus4']

# MIDI note numbers for quick ref
def midi_from_freq(freq):
    return int(round(12 * np.log2(freq / 440.0) + 69))

def note_name_to_midi(name, octave):
    notes = {'C':0,'C#':1,'Db':1,'D':2,'D#':3,'Eb':3,'E':4,'F':5,
             'F#':6,'Gb':6,'G':7,'G#':8,'Ab':8,'A':9,'A#':10,'Bb':10,'B':11}
    return 12 + notes[name] + 12 * octave

# Phase timing
PHASES = [
    ('intro',     0,   150),    # 0:00-2:30  — piano + pad only
    ('pulse',     150, 360),    # 2:30-6:00  — + kick, sub, harp
    ('cello',     360, 600),    # 6:00-10:00 — + cello solo
    ('breakdown', 600, 720),    # 10:00-12:00 — piano + harp only
    ('outro',     720, 900),    # 12:00-15:00 — pulse returns, then exit
]

def phase_at(t):
    for name, s, e in PHASES:
        if s <= t < e:
            return name, (t - s) / (e - s)
    return 'outro', 1.0

# ── Swing helper ──
def swing_time(beat_idx, bar_start):
    """Apply 10% swing: delay even 8th notes by swing_amount."""
    eighth_in_bar = beat_idx / 2  # 0.0, 0.5, 1.0, 1.5, ...
    if eighth_in_bar % 1.0 > 0.49:  # even eighths (the "off" beats)
        return bar_start + (beat_idx * BEAT_S) * (1 + SWING)
    return bar_start + beat_idx * BEAT_S


# ═══════════════════════════════════════════════════════════════════
# BUILD MIDI EVENTS
# ═══════════════════════════════════════════════════════════════════

TOTAL_BARS = int(DURATION_S / BAR_S) + 1

def build_piano_events():
    """Grand Piano (FluidSynth ch0). Wide jazz chords, velocity ≤70."""
    log.info("Building piano chords...")
    events = []
    # Program Change: Acoustic Grand Piano = 0
    events.append((0.0, "program", 0, 0, 0))

    for bar in range(TOTAL_BARS):
        t_bar = bar * BAR_S
        if t_bar >= DURATION_S: break
        phase, prog = phase_at(t_bar)

        # Chord density per phase
        beats_per_chord = 4
        if phase == 'intro':
            beats_per_chord = 8    # slow changes
        elif phase == 'pulse':
            beats_per_chord = 4
        elif phase == 'cello':
            beats_per_chord = 8    # let cello breathe
        elif phase == 'breakdown':
            beats_per_chord = 6
        else:  # outro
            beats_per_chord = 8

        for beat in range(0, int(BAR_S / BEAT_S), beats_per_chord):
            t = t_bar + beat * BEAT_S
            if t >= DURATION_S: break
            phase2, _ = phase_at(t)

            vol = 55
            if phase2 == 'intro':
                vol = 40 + int(20 * prog)  # growing in
            elif phase2 == 'pulse':
                vol = 55
            elif phase2 == 'cello':
                vol = 50  # support role
            elif phase2 == 'breakdown':
                vol = 60  # more present
            elif phase2 == 'outro':
                fade = max(0, (t - 720) / 180)
                vol = int(55 * (1 - fade))

            vol = min(vol, 70)  # cap at 70

            ci = (bar + (beat // beats_per_chord)) % len(CHORD_PROG)
            chord = CHORDS[CHORD_PROG[ci]]

            for note in chord:
                events.append((t, "note_on", 0, note, vol))
                # Hold most of the chord duration
                hold = beats_per_chord * BEAT_S * 0.85
                events.append((t + hold, "note_off", 0, note, 0))

    log.info(f"  {len(events)//2} piano chords")
    return events


def build_cello_events():
    """Solo Cello (FluidSynth ch1). Long legato phrases with rests."""
    log.info("Building cello melodies...")
    events = []
    # Program Change: Cello = 42
    events.append((0.0, "program", 1, 0, 42))

    # Melodic phrases in E minor (lower register)
    melodies = [
        # Phrase 1: melancholic rising
        [(note_name_to_midi('E',2), 3), (note_name_to_midi('G',2), 2),
         (note_name_to_midi('B',2), 4), (note_name_to_midi('E',3), 3)],
        # Phrase 2: falling
        [(note_name_to_midi('D',3), 3), (note_name_to_midi('B',2), 2),
         (note_name_to_midi('G',2), 3), (note_name_to_midi('E',2), 4)],
        # Phrase 3: aching
        [(note_name_to_midi('F#',2), 3), (note_name_to_midi('A',2), 3),
         (note_name_to_midi('B',2), 3), (note_name_to_midi('C',3), 3)],
        # Phrase 4: resolution
        [(note_name_to_midi('B',2), 4), (note_name_to_midi('G',2), 2),
         (note_name_to_midi('E',3), 3), (note_name_to_midi('E',2), 3)],
        # Phrase 5
        [(note_name_to_midi('G',2), 3), (note_name_to_midi('B',2), 3),
         (note_name_to_midi('D',3), 4), (note_name_to_midi('C',3), 2)],
        # Phrase 6
        [(note_name_to_midi('A',2), 3), (note_name_to_midi('F#',2), 2),
         (note_name_to_midi('G',2), 3), (note_name_to_midi('E',2), 4)],
    ]

    # Start at phase 3 (cello part)
    cello_start = PHASES[2][1]  # 360s = 6:00
    cello_end = PHASES[3][1]    # 600s = 10:00

    t = cello_start
    phrase_len_beats = 12  # 3 bars per phrase
    phrase_dur = phrase_len_beats * BEAT_S

    np.random.seed(5)
    while t < cello_end:
        phrase = melodies[np.random.randint(len(melodies))]
        for note, beats in phrase:
            dur = beats * BEAT_S
            vel = int(np.random.uniform(50, 65))
            events.append((t, "note_on", 1, note, vel))
            events.append((t + dur, "note_off", 1, note, 0))
            t += dur
        # Rest 2-4 bars between phrases
        rest_bars = np.random.randint(2, 5)
        t += rest_bars * BAR_S

    log.info(f"  {len(events)//2} cello notes")
    return events


def build_harp_events():
    """Orchestral Harp (FluidSynth ch2). Arpeggiated patterns instead of hi-hats."""
    log.info("Building harp arpeggios...")
    events = []
    # Program Change: Orchestral Harp = 46
    events.append((0.0, "program", 2, 0, 46))

    harp_start = PHASES[1][1]  # 2:30
    harp_end = PHASES[3][1]    # 12:00 (start of breakdown phase)

    for bar in range(TOTAL_BARS):
        t_bar = bar * BAR_S
        if t_bar < harp_start or t_bar >= harp_end:
            continue
        if t_bar >= DURATION_S: break

        phase, prog = phase_at(t_bar)

        # Chord for this bar
        ci = bar % len(CHORD_PROG)
        chord_notes = CHORDS[CHORD_PROG[ci]]
        # Use upper notes for harp (octave up)
        harp_notes = [n + 12 for n in chord_notes if n + 12 <= 84]

        # Arpeggio pattern per beat
        for beat in range(4):
            t_swung = swing_time(beat, t_bar)
            if t_swung >= DURATION_S: break

            vol = 45
            if phase == 'pulse':
                vol = 45
            elif phase == 'cello':
                vol = 40  # support
            elif phase == 'breakdown':
                vol = 50  # more present
            elif phase == 'outro':
                fade = max(0, (t_bar - 720) / 180)
                vol = int(45 * (1 - fade))

            # Arpeggiate: play notes ascending
            for i, note in enumerate(harp_notes[:4]):
                t_note = t_swung + i * 0.08
                if t_note >= DURATION_S: break
                events.append((t_note, "note_on", 2, note, vol))
                events.append((t_note + 0.06, "note_off", 2, note, 0))

    log.info(f"  {len(events)//2} harp notes")
    return events


def build_kick_events():
    """Soft kick pattern (synthcore). Four-on-floor but very gentle."""
    log.info("Building kick pattern...")
    kicks = []

    kick_start = PHASES[1][1]  # 2:30

    for bar in range(TOTAL_BARS):
        t_bar = bar * BAR_S
        if t_bar < kick_start: continue
        if t_bar >= DURATION_S: break

        phase, prog = phase_at(t_bar)

        # Four on the floor
        for beat in range(4):
            t = t_bar + beat * BEAT_S
            if t >= DURATION_S: break

            vol = 0.35  # very gentle
            if phase == 'outro':
                fade = max(0, (t - 720) / 120)
                vol *= max(0, 1 - fade)
                if t > 810:  # after 13:30, no more kick
                    continue

            kicks.append((t, vol))

    log.info(f"  {len(kicks)} kicks")
    return kicks


def build_sub_bass_events():
    """Sub-bass sine tone doubling piano roots."""
    log.info("Building sub-bass...")
    sub = []

    sub_start = PHASES[1][1]  # 2:30

    for bar in range(TOTAL_BARS):
        t_bar = bar * BAR_S
        if t_bar < sub_start: continue
        if t_bar >= DURATION_S: break

        phase, prog = phase_at(t_bar)

        ci = bar % len(CHORD_PROG)
        root_note = CHORDS[CHORD_PROG[ci]][0]  # lowest note
        freq = 440 * 2**((root_note - 69) / 12)

        vol = 0.25
        if phase == 'outro':
            fade = max(0, (t_bar - 720) / 120)
            vol *= max(0, 1 - fade)
            if t_bar > 810:
                continue

        # Sub bass sustains for 1-2 bars
        dur = BAR_S * (1 + int(prog > 0.5))
        sub.append((t_bar, freq, vol, dur))

    log.info(f"  {len(sub)} sub notes")
    return sub


# ═══════════════════════════════════════════════════════════════════
# BUILD MATH SYNTH LAYERS
# ═══════════════════════════════════════════════════════════════════

def render_warm_pad():
    """Very quiet analog pad that glues everything."""
    log.info("Building warm pad...")
    t0 = time.time()
    t = np.arange(N_SAMPLES) / SR

    # Slow-changing ambient pad
    chord_freqs = [
        [E3['E'], E3['G'], E4['B'], E4['E']],
        [E3['A'], E4['C'], E4['E'], E4['A']],
        [E3['C'], E3['E'], E4['G'], E4['B']],
        [E3['D'], E3['F#'], E4['A'], E4['D']],
    ]

    out = np.zeros((N_SAMPLES, 2), dtype=np.float32)
    chord_dur = 16 * BAR_S

    for ci, freqs in enumerate(chord_freqs):
        s = int(ci * chord_dur * SR)
        e = int(min((ci + 1) * chord_dur, DURATION_S) * SR)
        if s >= N_SAMPLES: break
        n = e - s

        left = np.zeros(n)
        right = np.zeros(n)
        for freq in freqs:
            saw = sawtooth_bl(freq, n, sr=SR) * 0.04
            sine = sine_wave(freq, n, sr=SR) * 0.06
            left += saw + sine
            right += sawtooth_bl(freq + 1.5, n, sr=SR) * 0.04 + sine_wave(freq + 1.5, n, sr=SR) * 0.06

        left = lpf(left, 2000, q=0.2, sr=SR)
        right = lpf(right, 2000, q=0.2, sr=SR)

        for j in range(n):
            tt = (s + j) / SR
            vol = 0.08  # always very quiet
            if tt > 870:  # last 30s fade
                vol *= (1 - (tt - 870) / 30)
            left[j] *= vol
            right[j] *= vol

        out[s:e, 0] += left
        out[s:e, 1] += right

    # Hall reverb
    out = apply_reverb(out, sr=SR, room_size=0.85, damping=0.4, wet=0.3)
    log.info(f"  Pad done: {time.time()-t0:.1f}s")
    return out


def render_kick_layer(kick_events):
    """Soft low-passed kick drum."""
    t0 = time.time()
    stereo = np.zeros((N_SAMPLES, 2), dtype=np.float32)

    for t_s, vel in kick_events:
        s = int(t_s * SR)
        n = int(0.15 * SR)  # 150ms
        if s + n > N_SAMPLES: n = N_SAMPLES - s

        # Sinusoidal kick: 80→40 Hz sweep
        t = np.arange(n) / SR
        sweep = 80 * (1 - t / (0.08 + t[-1]))  # approx 80→40 over 150ms
        kick = np.sin(2 * np.pi * sweep * t)
        kick = kick * np.exp(-t * 12)
        kick = lpf(kick, 500, q=0.3, sr=SR)
        kick = kick * vel * 1.5

        stereo[s:s+n, 0] += kick
        stereo[s:s+n, 1] += kick * 0.8  # slightly stereo

    log.info(f"  Kick layer done: {time.time()-t0:.1f}s")
    return stereo


def render_sub_layer(sub_events):
    """Deep sine sub-bass."""
    t0 = time.time()
    stereo = np.zeros((N_SAMPLES, 2), dtype=np.float32)

    for t_s, freq, vol, dur in sub_events:
        s = int(t_s * SR)
        n = int(dur * SR)
        if s + n > N_SAMPLES: n = N_SAMPLES - s

        sub = sine_wave(freq, n, sr=SR)
        # Gentle ADSR
        env = np.ones(n)
        a = min(int(0.3 * SR), n)
        r = max(n - int(0.5 * SR), 0)
        env[:a] = np.linspace(0, 1, a)
        if r > a:
            env[r:] = np.linspace(1, 0, n - r)
        sub = sub * env * vol * 0.5

        stereo[s:s+n, 0] += sub
        stereo[s:s+n, 1] += sub

    log.info(f"  Sub layer done: {time.time()-t0:.1f}s")
    return stereo


# ═══════════════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════════════

def render():
    log.info("╔══════════════════════════════════════════════════════╗")
    log.info("║  NEO-CLASSICAL SPA RESORT — Acoustic Lounge         ║")
    log.info("║  72 BPM · E minor · 15:00 · 10% swing              ║")
    log.info("║  FluidSynth (piano, cello, harp) + math synths     ║")
    log.info("╚══════════════════════════════════════════════════════╝")
    total_t0 = time.time()

    # ── Build MIDI events ──
    piano_ev = build_piano_events()
    cello_ev = build_cello_events()
    harp_ev = build_harp_events()
    kick_ev = build_kick_events()
    sub_ev = build_sub_bass_events()

    # FluidSynth events combined
    fluid_events = sorted(piano_ev + cello_ev + harp_ev, key=lambda e: e[0])
    n_daw = len(piano_ev) + len(cello_ev) + len(harp_ev)
    n_fluid = n_daw  # all go through FluidSynth
    log.info(f"Total events: {n_daw}")
    log.info(f"  FluidSynth: {n_daw} (piano + cello + harp)")

    # ── Render FluidSynth ──
    log.info("Rendering FluidSynth (piano + cello + harp)...")
    t0 = time.time()
    sf2_path = find_sf2("/opt/autodj-mixer/shared/MuseScore_General.sf2")
    fs = FluidSynthBackend(sf2_path=sf2_path, sample_rate=SR)
    wav_fluid = fs.render(fluid_events, DURATION_S)
    fs.close()
    log.info(f"  FluidSynth done: {len(wav_fluid)} samples ({time.time()-t0:.1f}s)")

    # ── Render math synth layers ──
    wav_pad = render_warm_pad()
    wav_kick = render_kick_layer(kick_ev)
    wav_sub = render_sub_layer(sub_ev)

    # ── Mix ──
    log.info("Mixing layers...")
    t0 = time.time()

    out = np.zeros((N_SAMPLES, 2), dtype=np.float32)

    # Warm pad (always on)
    out += wav_pad * 0.30

    # Pitch correction: FluidSynth output normalization
    peak_fluid = np.abs(wav_fluid).max()
    if peak_fluid > 1e-6:
        out += wav_fluid * (0.45 / peak_fluid)
    else:
        out += wav_fluid * 0.45

    # Kick
    out += wav_kick * 0.35

    # Sub bass
    out += wav_sub * 0.40

    # Phase-based mute automation
    log.info("Applying phase automation...")
    for i in range(0, N_SAMPLES, int(SR * 0.1)):  # every 100ms
        t_s = i / SR
        phase, _ = phase_at(t_s)
        end = min(i + int(SR * 0.1), N_SAMPLES)

        if phase == 'intro':
            out[i:end, :] = out[i:end, :]  # pad + piano only (others are 0)
            # Explicitly silence kick + sub channels
            pass  # they're not in the mix yet
        elif phase == 'breakdown':
            out[i:end, :] = out[i:end, :]  # piano + harp naturally present
            # Zero out kick + sub contributions after mix
            pass
        elif phase == 'outro':
            fade_t = (t_s - 720) / 180
            if fade_t > 0:
                out[i:end, :] *= max(0, 1 - fade_t * 0.5)
            if t_s > 870:
                out[i:end, :] = out[i:end, :]  # pad fade-out covers it

    # ── Master bus ──
    log.info("Master bus (compressor + limiter)...")
    out = apply_compressor(out, sr=SR, threshold_db=-18, ratio=1.8,
                           attack_ms=40, release_ms=500)

    # Limiter
    peak = np.abs(out).max()
    ceiling = 10 ** (-1.0 / 20)  # -1.0 dBTP
    if peak > ceiling:
        out *= ceiling / peak

    # Final normalize to -0.5 dB
    out = normalize_master(out, target_db=-0.5)

    rms = np.sqrt(np.mean(out ** 2))
    peak_final = np.abs(out).max()
    log.info(f"Render complete: peak={peak_final:.4f}, RMS={20*np.log10(rms+1e-10):.1f} dBFS")
    log.info(f"Total time: {time.time()-total_t0:.0f}s")

    # ── Save ──
    import soundfile as sf
    wav_path = "/opt/autodj-mixer/Neo_Classical_Spa.wav"
    sf.write(wav_path, out, SR, subtype='PCM_24')
    log.info(f"Saved: {wav_path}")

    import subprocess
    mp3_path = wav_path.replace(".wav", ".mp3")
    subprocess.run([
        "ffmpeg", "-y", "-i", wav_path,
        "-b:a", "320k", "-q:a", "0",
        "-write_id3v1", "1",
        "-metadata", "title=Neo-Classical Spa Resort",
        "-metadata", "artist=Xenolith",
        "-metadata", "genre=Acoustic Lounge",
        mp3_path
    ], capture_output=True)
    size_mb = os.path.getsize(mp3_path) / 1024 / 1024
    log.info(f"MP3: {mp3_path} ({size_mb:.1f} MB)")

    wav_size = os.path.getsize(wav_path) / 1024 / 1024
    print(f"\n✅ Neo-Classical Spa Resort rendered!")
    print(f"   WAV: {wav_path} ({wav_size:.0f} MB)")
    print(f"   MP3: {mp3_path} ({size_mb:.1f} MB)")
    print(f"   Duration: {DURATION_S//60}:{DURATION_S%60:02d}")
    print(f"   Peak: {peak_final:.4f}  RMS: {20*np.log10(rms+1e-10):.1f} dBFS")

    return wav_path, mp3_path


if __name__ == "__main__":
    render()
