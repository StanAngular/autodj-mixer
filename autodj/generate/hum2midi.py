"""
autodj/generate/hum2midi.py — Hum/voice recording → quantized MIDI melody (SPEC 008, G3)

Pipeline:
  audio file (WAV/MP3/OGG) → pitch tracking (librosa.pyin)
  → Hz → MIDI notes → quantize to grid + key → MIDI event list
  → ready for FluidSynth or synth backend

Usage:
    from autodj.generate.hum2midi import hum_to_events, hum_to_freqs

    # Minimal: hum file → MIDI events (for FluidSynth)
    events = hum_to_events("hum.wav", bpm=120, key="Am", channel=0, program=56)

    # Intermediate: hum → freq list (for music_engine style JSON)
    freqs, step_s = hum_to_freqs("hum.wav", bpm=120, key="Am", steps_per_bar=8)

    # CLI: python3 -m autodj.generate.hum2midi hum.wav --bpm 120 --key Am
"""

import os
import sys
import logging
import argparse

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Musical constants
# ---------------------------------------------------------------------------

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Scale degrees (semitones from root) for common modes
SCALES = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "phrygian":   [0, 1, 3, 5, 7, 8, 10],
    "lydian":     [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "pentatonic_minor": [0, 3, 5, 7, 10],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "blues":      [0, 3, 5, 6, 7, 10],
    "chromatic":  list(range(12)),
}

# Camelot → (root note, mode) mapping
CAMELOT_MAP = {
    "1A": ("Ab", "minor"), "1B": ("B",  "major"),
    "2A": ("Eb", "minor"), "2B": ("F#", "major"),
    "3A": ("Bb", "minor"), "3B": ("Db", "major"),
    "4A": ("F",  "minor"), "4B": ("Ab", "major"),
    "5A": ("C",  "minor"), "5B": ("Eb", "major"),
    "6A": ("G",  "minor"), "6B": ("Bb", "major"),
    "7A": ("D",  "minor"), "7B": ("F",  "major"),
    "8A": ("A",  "minor"), "8B": ("C",  "major"),
    "9A": ("E",  "minor"), "9B": ("G",  "major"),
    "10A": ("B", "minor"), "10B": ("D", "major"),
    "11A": ("F#","minor"), "11B": ("A", "major"),
    "12A": ("Db","minor"), "12B": ("E", "major"),
}


def parse_key(key_str: str) -> tuple:
    """
    Parse key string to (root_semitone, scale_degrees).

    Accepts:
        "Am"  → minor, root A
        "C"   → major, root C
        "Fm"  → minor, root F
        "Dorian" / "Am/dorian" → dorian
        "8A"  → Camelot notation → A minor

    Returns:
        (root_semitone, scale_degrees)
        root_semitone: 0=C, 1=C#, 2=D ... 11=B
    """
    key_str = key_str.strip()

    # Camelot notation
    if key_str in CAMELOT_MAP:
        root_name, mode = CAMELOT_MAP[key_str]
        return _note_to_semitone(root_name), SCALES[mode]

    # Check for explicit mode suffix
    mode = "major"
    note_part = key_str

    if "/" in key_str:
        note_part, mode_part = key_str.split("/", 1)
        mode = mode_part.lower()
        if mode not in SCALES:
            mode = "minor" if "m" in mode_part.lower() else "major"
    elif key_str.lower().endswith("m") and not key_str.lower().endswith("am"):
        # "Fm", "Cm", etc — but not "Am" prefix ambiguity with F#m
        # Handle: trailing 'm' = minor unless it's just a note name
        candidate = key_str[:-1]
        if candidate.upper() in [n.upper() for n in NOTES]:
            note_part = candidate
            mode = "minor"
    elif key_str.endswith("m"):
        note_part = key_str[:-1]
        mode = "minor"

    # Explicit mode keywords
    for scale_name in SCALES:
        if key_str.lower().endswith(scale_name):
            parts = key_str[:-(len(scale_name))].strip()
            if parts:
                note_part = parts.rstrip("/ ")
                mode = scale_name
                break

    root_semi = _note_to_semitone(note_part.strip().upper())
    scale_degrees = SCALES.get(mode, SCALES["minor"])
    return root_semi, scale_degrees


def _note_to_semitone(note: str) -> int:
    """Convert note name to semitone (C=0, C#=1 ... B=11)."""
    aliases = {
        "DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#",
        "CB": "B",  "FB": "E",  "ES": "F",  "AS": "A#",
    }
    note = note.upper().replace("♭", "B").replace("♯", "#")
    note = aliases.get(note, note)
    if note in NOTES:
        return NOTES.index(note)
    # Try without accidental
    base = note[0]
    if base in NOTES:
        return NOTES.index(base)
    return 0  # fallback C


def hz_to_midi(freq: float) -> int:
    """Convert Hz to MIDI note (A4=440=69)."""
    if freq <= 0:
        return 0
    return int(round(69 + 12 * np.log2(freq / 440.0)))


def midi_to_hz(note: int) -> float:
    """Convert MIDI note to Hz."""
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def quantize_to_scale(midi_note: int, root_semitone: int, scale_degrees: list) -> int:
    """
    Snap a MIDI note to the nearest scale degree.

    Args:
        midi_note: raw MIDI note from pitch tracker
        root_semitone: key root (0=C, 9=A ...)
        scale_degrees: list of semitone offsets from root

    Returns:
        quantized MIDI note number
    """
    octave_base = (midi_note // 12) * 12
    pitch_class = midi_note % 12
    # Distance from root
    relative = (pitch_class - root_semitone) % 12
    # Find nearest scale degree
    best_deg = min(scale_degrees, key=lambda d: min(abs(relative - d), 12 - abs(relative - d)))
    quantized_pc = (root_semitone + best_deg) % 12
    # Keep same octave (may need +12 adjustment)
    result = octave_base + quantized_pc
    if result < midi_note - 6:
        result += 12
    elif result > midi_note + 6:
        result -= 12
    return max(0, min(127, result))


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def load_audio(path: str, sr: int = 22050, mono: bool = True) -> tuple:
    """Load audio file. Returns (samples, sample_rate)."""
    try:
        import librosa
        y, loaded_sr = librosa.load(path, sr=sr, mono=mono)
        return y, loaded_sr
    except ImportError:
        raise RuntimeError("librosa required: pip install librosa")


def extract_pitch(
    y: np.ndarray,
    sr: int,
    fmin: float = 80.0,
    fmax: float = 1500.0,
    frame_length: int = 2048,
    hop_length: int = 512,
) -> tuple:
    """
    Extract fundamental frequency using librosa.pyin.

    Returns:
        f0: np.ndarray of Hz values per frame (NaN where unvoiced)
        times: np.ndarray of frame timestamps in seconds
        voiced: np.ndarray of bool (True where pitch is detected)
    """
    try:
        import librosa
    except ImportError:
        raise RuntimeError("librosa required: pip install librosa")

    f0, voiced_flag, voiced_prob = librosa.pyin(
        y,
        fmin=fmin,
        fmax=fmax,
        sr=sr,
        frame_length=frame_length,
        hop_length=hop_length,
    )

    times = librosa.frames_to_time(
        np.arange(len(f0)), sr=sr, hop_length=hop_length
    )

    # Replace NaN with 0
    f0_clean = np.where(voiced_flag, f0, 0.0)
    f0_clean = np.nan_to_num(f0_clean, nan=0.0)

    return f0_clean, times, voiced_flag


def segment_notes(
    f0: np.ndarray,
    times: np.ndarray,
    voiced: np.ndarray,
    min_note_s: float = 0.06,
    gap_tolerance_s: float = 0.05,
    pitch_jump_semitones: float = 0.8,
) -> list:
    """
    Group consecutive voiced frames into note segments.
    Splits on: unvoiced gaps OR sudden pitch jumps (>pitch_jump_semitones).

    Returns:
        list of (t_start, t_end, median_hz)
    """
    notes = []
    if len(times) == 0:
        return notes

    frame_s = (times[1] - times[0]) if len(times) > 1 else 0.023
    max_gap = max(1, int(gap_tolerance_s / frame_s))

    in_note = False
    t_start = 0.0
    freqs_buf = []
    gap_frames = 0
    prev_hz = 0.0

    def flush(t_end):
        if freqs_buf:
            dur = t_end - t_start
            if dur >= min_note_s:
                notes.append((t_start, t_end, float(np.median(freqs_buf))))

    for i, (t, hz, v) in enumerate(zip(times, f0, voiced)):
        if v and hz > 0:
            # Check for pitch jump (new note while still voiced)
            if in_note and prev_hz > 0:
                semitones_diff = abs(12 * np.log2(hz / prev_hz))
                if semitones_diff >= pitch_jump_semitones:
                    # New note — flush current
                    flush(t)
                    t_start = t
                    freqs_buf = []
                    gap_frames = 0

            if not in_note:
                t_start = t
                freqs_buf = []
                in_note = True
                gap_frames = 0

            freqs_buf.append(hz)
            prev_hz = hz
            gap_frames = 0

        elif in_note:
            gap_frames += 1
            if gap_frames > max_gap:
                flush(t - gap_frames * frame_s)
                in_note = False
                freqs_buf = []
                gap_frames = 0
                prev_hz = 0.0

    # Flush last note
    if in_note and freqs_buf:
        flush(times[-1])

    return notes


def quantize_to_grid(
    notes: list,
    bpm: float,
    steps_per_bar: int = 16,
    swing: float = 0.0,
) -> list:
    """
    Snap note onset/offsets to rhythmic grid.

    Args:
        notes: list of (t_start, t_end, hz)
        bpm: beats per minute
        steps_per_bar: 8 = eighth notes, 16 = sixteenth notes
        swing: 0..1 (0 = straight, 0.1 = light swing)

    Returns:
        list of (grid_step, duration_steps, hz)
    """
    beat_s = 60.0 / bpm
    bar_s = beat_s * 4
    step_s = bar_s / steps_per_bar

    quantized = []
    for t_start, t_end, hz in notes:
        # Snap onset to nearest step
        step_on = round(t_start / step_s)
        step_off = max(step_on + 1, round(t_end / step_s))
        dur = step_off - step_on
        quantized.append((step_on, dur, hz))

    # Sort and merge overlapping
    quantized.sort(key=lambda x: x[0])
    merged = []
    for step, dur, hz in quantized:
        if merged and step < merged[-1][0] + merged[-1][1]:
            # Overlap: keep louder / first
            pass
        else:
            merged.append((step, dur, hz))

    return merged


def notes_to_freq_list(
    quantized_notes: list,
    total_steps: int,
) -> list:
    """
    Convert quantized note list to a flat step array (0 = rest).

    Returns:
        list of Hz values, length = total_steps (0 = rest)
    """
    freqs = [0.0] * total_steps
    for step, dur, hz in quantized_notes:
        for s in range(step, min(step + dur, total_steps)):
            freqs[s] = float(hz)
    return freqs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hum_to_freqs(
    audio_path: str,
    bpm: float = 120.0,
    key: str = "Am",
    steps_per_bar: int = 8,
    n_bars: int = None,
    swing: float = 0.0,
    fmin: float = 80.0,
    fmax: float = 1500.0,
) -> tuple:
    """
    Audio file → quantized frequency list (for music_engine JSON patterns).

    Args:
        audio_path: path to WAV/MP3 recording
        bpm: tempo
        key: key string ("Am", "C", "Fm", "8A", ...)
        steps_per_bar: rhythmic grid (8=eighths, 16=sixteenths)
        n_bars: output length in bars (None = auto from audio length)
        swing: swing amount 0..1
        fmin/fmax: pitch detection range

    Returns:
        (freqs, step_s)
        freqs: list of Hz values per step (0 = rest)
        step_s: duration of each step in seconds
    """
    log.info(f"hum_to_freqs: {audio_path} bpm={bpm} key={key}")

    y, sr = load_audio(audio_path)
    f0, times, voiced = extract_pitch(y, sr, fmin=fmin, fmax=fmax)

    # Parse key
    root_semi, scale_degrees = parse_key(key)

    # Segment into notes
    raw_notes = segment_notes(f0, times, voiced)
    log.info(f"  Detected {len(raw_notes)} raw notes")

    # Quantize pitch to scale
    scale_notes = []
    for t_start, t_end, hz in raw_notes:
        midi = hz_to_midi(hz)
        midi_q = quantize_to_scale(midi, root_semi, scale_degrees)
        scale_notes.append((t_start, t_end, midi_to_hz(midi_q)))

    # Quantize to rhythmic grid
    quantized = quantize_to_grid(scale_notes, bpm, steps_per_bar, swing)

    # Determine output length
    beat_s = 60.0 / bpm
    bar_s = beat_s * 4
    step_s = bar_s / steps_per_bar

    if n_bars is None:
        audio_dur = len(y) / sr
        n_bars = max(1, int(np.ceil(audio_dur / bar_s)))

    total_steps = n_bars * steps_per_bar
    freqs = notes_to_freq_list(quantized, total_steps)

    log.info(f"  Output: {n_bars} bars × {steps_per_bar} steps = {total_steps} steps")
    log.info(f"  Non-rest steps: {sum(1 for f in freqs if f > 0)}")

    return freqs, step_s


def hum_to_events(
    audio_path: str,
    bpm: float = 120.0,
    key: str = "Am",
    channel: int = 0,
    program: int = 56,
    bank: int = 0,
    velocity: int = 90,
    steps_per_bar: int = 8,
    note_frac: float = 0.85,
    fmin: float = 80.0,
    fmax: float = 1500.0,
) -> list:
    """
    Audio file → MIDI event list (for FluidSynth backend).

    Args:
        audio_path: WAV/MP3 recording
        bpm: tempo
        key: key string
        channel: MIDI channel (0-15)
        program: GM program number
        bank: SF2 bank
        velocity: note velocity 0-127
        steps_per_bar: rhythmic grid
        note_frac: note length fraction of step
        fmin/fmax: pitch detection range

    Returns:
        List of MIDI events: [(time_s, type, channel, ...)]
    """
    freqs, step_s = hum_to_freqs(
        audio_path, bpm=bpm, key=key,
        steps_per_bar=steps_per_bar, fmin=fmin, fmax=fmax,
    )

    events = [(0.0, "program", channel, bank, program)]

    for i, freq in enumerate(freqs):
        if freq <= 0:
            continue
        t_on = i * step_s
        t_off = t_on + step_s * note_frac
        note = hz_to_midi(freq)
        events.append((t_on,  "note_on",  channel, note, velocity))
        events.append((t_off, "note_off", channel, note, 0))

    return events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="hum2midi: voice/hum recording → quantized MIDI melody"
    )
    parser.add_argument("audio", help="Input audio file (WAV/MP3/OGG)")
    parser.add_argument("--bpm",  type=float, default=120.0, help="Tempo (default 120)")
    parser.add_argument("--key",  default="Am",  help="Musical key (e.g. Am, C, Fm, 8A)")
    parser.add_argument("--steps", type=int, default=8, help="Grid steps per bar (8 or 16)")
    parser.add_argument("--bars",  type=int, default=None, help="Output bars (auto)")
    parser.add_argument("--fmin",  type=float, default=80.0,  help="Min pitch Hz (def 80)")
    parser.add_argument("--fmax",  type=float, default=1500.0, help="Max pitch Hz (def 1500)")
    parser.add_argument("--swing", type=float, default=0.0, help="Swing 0..1")
    parser.add_argument("--out",   default=None, help="Output JSON freq list path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s"
    )

    if not os.path.exists(args.audio):
        print(f"Error: file not found: {args.audio}", file=sys.stderr)
        sys.exit(1)

    freqs, step_s = hum_to_freqs(
        args.audio,
        bpm=args.bpm,
        key=args.key,
        steps_per_bar=args.steps,
        n_bars=args.bars,
        swing=args.swing,
        fmin=args.fmin,
        fmax=args.fmax,
    )

    non_rest = [(i, f) for i, f in enumerate(freqs) if f > 0]
    print(f"\nKey: {args.key}  BPM: {args.bpm}  Grid: 1/{args.steps} notes")
    print(f"Steps: {len(freqs)} total, {len(non_rest)} notes, step={step_s*1000:.0f}ms")
    print(f"\nFrequency list (0=rest):")
    print(freqs)

    if non_rest:
        print(f"\nDetected melody:")
        from itertools import groupby
        for step, hz in non_rest:
            midi = hz_to_midi(hz)
            note_name = NOTES[midi % 12]
            octave = midi // 12 - 1
            t = step * step_s
            print(f"  step {step:3d} ({t:.2f}s): {hz:.1f} Hz → {note_name}{octave} (MIDI {midi})")

    if args.out:
        import json
        with open(args.out, "w") as f:
            json.dump({"freqs": freqs, "step_s": step_s, "bpm": args.bpm, "key": args.key}, f, indent=2)
        print(f"\nSaved: {args.out}")


if __name__ == "__main__":
    main()
