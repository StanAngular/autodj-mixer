"""
music_theory.py — Compositional helpers derived from AI Music Manifesto v2.1

Bakes manifesto rules into reusable functions so render scripts don't need
to re-read 42KB of theory each time.

Provides:
  - Chord progression library (by genre/mood)
  - Voice leading algorithm (minimize pitch jumps)
  - Melody generation (period-structure, call-and-response)
  - Euclidean rhythm generator
  - Humanization (velocity variation + micro-timing)
  - Reverb/pan presets by instrument role
  - Frequency layering helpers (HP filters for non-bass)
"""

import numpy as np
from typing import List, Tuple, Optional, Dict
from scipy.signal import butter, sosfilt

# ---------------------------------------------------------------------------
# §1  CHORD PROGRESSIONS (Manifesto Module 1.1)
# ---------------------------------------------------------------------------
# Roman numeral degrees in minor key, as semitone offsets from root.
# i=0, ii=2, III=3, iv=5, v=7, VI=8, VII=10

# Triad voicings: (root_offset, [intervals from that degree])
_MINOR_DEGREES = {
    "i":   (0,  [0, 3, 7]),      # minor
    "ii":  (2,  [0, 3, 6]),      # diminished
    "III": (3,  [0, 4, 7]),      # major
    "iv":  (5,  [0, 3, 7]),      # minor
    "v":   (7,  [0, 3, 7]),      # minor
    "V":   (7,  [0, 4, 7]),      # major (harmonic minor)
    "VI":  (8,  [0, 4, 7]),      # major
    "VII": (10, [0, 4, 7]),      # major
}

# 7th chord extensions
_MINOR_DEGREES_7 = {
    "i7":   (0,  [0, 3, 7, 10]),
    "ii7":  (2,  [0, 3, 6, 10]),
    "III7": (3,  [0, 4, 7, 10]),
    "iv7":  (5,  [0, 3, 7, 10]),
    "v7":   (7,  [0, 3, 7, 10]),
    "V7":   (7,  [0, 4, 7, 10]),
    "VI7":  (8,  [0, 4, 7, 10]),
    "VII7": (10, [0, 4, 7, 10]),
}

# Progression presets by genre/mood
PROGRESSIONS: Dict[str, List[str]] = {
    # Core minor progressions
    "dark_techno":     ["i", "VI", "III", "VII"],
    "deep_house":      ["i", "v", "iv", "i"],
    "ambient":         ["VI", "VII", "i", "i"],
    "trance":          ["i", "III", "VI", "VII"],
    "indie":           ["i", "iv", "VI", "III"],

    # Extended / 7th chord progressions (lounge/deep)
    "lounge":          ["i7", "iv7", "v7", "i7"],
    "deep_lounge":     ["i7", "VI7", "III7", "VII7"],
    "neo_soul":        ["i7", "iv7", "VII7", "III7"],

    # Special cadences
    "plagal":          ["iv", "i"],           # meditative ending
    "modal_interchange": ["i", "IV", "v", "i"],  # major IV in minor
    "secondary_dom":   ["i", "V", "v", "i"],     # V/v secondary dominant

    # Breakbeat / experimental
    "breakbeat":       ["i", "VII", "VI", "v"],
    "industrial":      ["i", "i", "VII", "VII"],
    "psychedelic":     ["i", "III", "iv", "VII"],
}


def resolve_progression(root_midi: int, prog_name: str,
                        octave: int = 2, use_7ths: bool = False
                        ) -> List[List[int]]:
    """
    Convert a named progression to concrete MIDI note lists.

    Args:
        root_midi: MIDI note of the root (e.g. 45 = A2)
        prog_name: key from PROGRESSIONS dict
        octave: which octave to voice chords in (2=C2-B2 range)
        use_7ths: add 7th to each chord if available

    Returns:
        List of chords, each chord = list of MIDI notes
    """
    prog = PROGRESSIONS.get(prog_name)
    if prog is None:
        raise ValueError(f"Unknown progression: {prog_name}. "
                         f"Available: {list(PROGRESSIONS.keys())}")

    base = root_midi  # root of the key
    chords = []
    degree_map = {**_MINOR_DEGREES, **_MINOR_DEGREES_7}

    for symbol in prog:
        # Try 7th version if requested
        lookup = symbol
        if use_7ths and not symbol.endswith("7"):
            s7 = symbol + "7"
            if s7 in degree_map:
                lookup = s7

        if lookup not in degree_map:
            raise ValueError(f"Unknown degree: {lookup}")

        offset, intervals = degree_map[lookup]
        chord = [base + offset + iv for iv in intervals]
        chords.append(chord)

    return chords


# ---------------------------------------------------------------------------
# §2  VOICE LEADING (Manifesto Module 1.2)
# ---------------------------------------------------------------------------

def voice_lead(prev_chord: List[int], next_chord: List[int],
               max_delta: int = 4) -> List[int]:
    """
    Re-voice next_chord so each note is as close as possible to its
    counterpart in prev_chord. Common tones stay in place.

    Manifesto rule: max delta for pad/chord voices = 4 semitones.
    Bass voice exempt (can jump by 4th/5th).

    Args:
        prev_chord: previous chord as MIDI notes (sorted low to high)
        next_chord: target chord (same number of voices)
        max_delta: maximum allowed semitone jump per voice

    Returns:
        Re-voiced next_chord (same pitch classes, optimal octave placement)
    """
    if len(prev_chord) != len(next_chord):
        # Different voice count: just return as-is
        return list(next_chord)

    result = []
    used = set()

    for prev_note in sorted(prev_chord):
        # Find the closest pitch class match in next_chord
        best = None
        best_dist = 999

        for i, next_note in enumerate(next_chord):
            if i in used:
                continue

            # Try the note at various octaves near prev_note
            pc = next_note % 12
            for octave_shift in range(-1, 2):
                candidate = (prev_note // 12 + octave_shift) * 12 + pc
                dist = abs(candidate - prev_note)
                if dist < best_dist:
                    best_dist = dist
                    best = (i, candidate)

        if best is not None:
            idx, note = best
            used.add(idx)
            # Enforce max_delta for non-bass voices (skip first/lowest)
            if len(result) > 0 and abs(note - prev_note) > max_delta:
                # Clamp to nearest valid position
                direction = 1 if note > prev_note else -1
                note = prev_note + direction * max_delta
            result.append(note)

    return sorted(result)


def voice_lead_sequence(chords: List[List[int]],
                        max_delta: int = 4) -> List[List[int]]:
    """Apply voice leading to a sequence of chords."""
    if not chords:
        return []
    result = [chords[0]]  # first chord as-is
    for i in range(1, len(chords)):
        led = voice_lead(result[i - 1], chords[i], max_delta)
        result.append(led)
    return result


# ---------------------------------------------------------------------------
# §3  EUCLIDEAN RHYTHMS (Manifesto Module 2.3)
# ---------------------------------------------------------------------------

def euclidean_rhythm(beats: int, steps: int,
                     rotation: int = 0) -> List[bool]:
    """
    Generate a Euclidean rhythm pattern.

    Classic patterns:
        E(3, 8)  = tresillo (Cuban)
        E(5, 16) = bossa nova
        E(7, 12) = West African bell
        E(3, 16) = sparse techno hat
        E(4, 16) = 4-on-the-floor kick

    Args:
        beats: number of active hits
        steps: total steps in the pattern
        rotation: rotate pattern by N steps

    Returns:
        List of bools, True = hit, False = rest
    """
    if beats > steps:
        beats = steps
    if beats == 0:
        return [False] * steps

    # Bjorklund's algorithm
    pattern = []
    counts = []
    remainders = []

    divisor = steps - beats
    remainders.append(beats)
    level = 0

    while True:
        counts.append(divisor // remainders[level])
        remainders.append(divisor % remainders[level])
        divisor = remainders[level]
        level += 1
        if remainders[level] <= 1:
            break

    counts.append(divisor)

    def _build(level):
        if level == -1:
            pattern.append(False)
        elif level == -2:
            pattern.append(True)
        else:
            for _ in range(counts[level]):
                _build(level - 1)
            if remainders[level] != 0:
                _build(level - 2)

    _build(level)

    # Ensure correct length
    pattern = pattern[:steps]
    while len(pattern) < steps:
        pattern.append(False)

    # Apply rotation
    if rotation:
        rotation = rotation % steps
        pattern = pattern[rotation:] + pattern[:rotation]

    return pattern


def euclidean_to_velocity(pattern: List[bool],
                          strong_vel: int = 90,
                          weak_vel: int = 60) -> List[int]:
    """Convert boolean pattern to velocity array with accent on beat 0."""
    result = []
    for i, hit in enumerate(pattern):
        if not hit:
            result.append(0)
        elif i == 0:
            result.append(strong_vel)
        else:
            result.append(weak_vel)
    return result


# Preset library of useful Euclidean patterns
EUCLIDEAN_PRESETS = {
    "tresillo":       (3, 8, 0),    # Cuban
    "bossa_nova":     (5, 16, 0),   # Brazilian
    "afro_bell":      (7, 12, 0),   # West African
    "four_floor":     (4, 16, 0),   # 4-on-the-floor
    "sparse_hat":     (3, 16, 0),   # Minimal techno
    "breakbeat":      (5, 8, 0),    # Breakbeat feel
    "reggaeton":      (3, 16, 3),   # Dembow-adjacent
    "tribal_6_8":     (4, 12, 0),   # 6/8 feel
}


# ---------------------------------------------------------------------------
# §4  HUMANIZATION (Manifesto Module 4)
# ---------------------------------------------------------------------------

def humanize_velocity(pattern: List[int],
                      variation: float = 0.12,
                      seed: Optional[int] = None) -> List[int]:
    """
    Add controlled random variation to a velocity pattern.

    Manifesto: +/- 5-15% variation, never exceed 20%.
    Strong beats get less variation, weak beats get more.

    Args:
        pattern: list of velocities (0-127, 0 = rest)
        variation: fractional variation (0.12 = 12%)
        seed: random seed for reproducibility

    Returns:
        Humanized velocity pattern
    """
    rng = np.random.RandomState(seed)
    result = []
    for vel in pattern:
        if vel == 0:
            result.append(0)
            continue
        # Scale variation by velocity (louder = more stable)
        local_var = variation * (1.0 - 0.3 * (vel / 127.0))
        delta = rng.uniform(-local_var, local_var)
        new_vel = int(vel * (1.0 + delta))
        result.append(max(1, min(127, new_vel)))
    return result


def humanize_timing(events: List[Tuple[float, str, int]],
                    role: str = "default",
                    seed: Optional[int] = None
                    ) -> List[Tuple[float, str, int]]:
    """
    Apply micro-timing shifts to drum/note events based on instrument role.

    Manifesto Module 4.2:
      - kick/sub: 0 ms (strict grid, rhythmic anchor)
      - snare/clap/hat: +3 to +10 ms (lazy groove)
      - chord/pad: +5 to +15 ms (relaxed feel)
      - lead: +2 to +8 ms (slight human feel)

    Negative shift = energetic/pushing. Positive = laid-back.

    Args:
        events: list of (time_s, name, velocity)
        role: "kick", "snare", "hat", "chord", "lead", "default"
        seed: random seed

    Returns:
        Events with shifted timing
    """
    SHIFT_RANGES = {
        "kick":    (0.0, 0.0),        # strict grid
        "sub":     (0.0, 0.0),        # strict grid
        "snare":   (0.002, 0.010),    # 2-10ms late
        "clap":    (0.002, 0.010),
        "hat":     (0.001, 0.008),    # 1-8ms
        "hat_c":   (0.001, 0.008),
        "hat_o":   (0.001, 0.008),
        "rim":     (0.001, 0.006),
        "chord":   (0.005, 0.015),    # 5-15ms (lazy)
        "pad":     (0.005, 0.015),
        "lead":    (0.002, 0.008),
        "default": (0.001, 0.006),
    }

    lo, hi = SHIFT_RANGES.get(role, SHIFT_RANGES["default"])
    if lo == 0.0 and hi == 0.0:
        return events  # no shift for kick/sub

    rng = np.random.RandomState(seed)
    result = []
    for t, name, vel in events:
        shift = rng.uniform(lo, hi)
        # Occasionally push slightly early for variety (-20% chance)
        if rng.random() < 0.2:
            shift = -shift * 0.5
        result.append((t + shift, name, vel))
    return result


def humanize_drum_events(events: List[Tuple[float, str, int]],
                         vel_variation: float = 0.12,
                         apply_timing: bool = True,
                         seed: Optional[int] = None
                         ) -> List[Tuple[float, str, int]]:
    """
    All-in-one humanization for drum event lists.
    Groups events by instrument, applies role-appropriate timing
    and velocity humanization.

    Args:
        events: list of (time_s, drum_name, velocity)
        vel_variation: velocity variation fraction
        apply_timing: whether to apply micro-timing shifts
        seed: random seed

    Returns:
        Humanized events sorted by time
    """
    rng = np.random.RandomState(seed)

    # Group by instrument
    groups: Dict[str, List] = {}
    for t, name, vel in events:
        groups.setdefault(name, []).append((t, name, vel))

    result = []
    for name, group_events in groups.items():
        # Humanize velocity
        vels = [v for _, _, v in group_events]
        h_vels = humanize_velocity(vels, vel_variation,
                                   seed=rng.randint(0, 2**31) if seed else None)

        humanized = [(t, n, hv) for (t, n, _), hv in zip(group_events, h_vels)]

        # Humanize timing
        if apply_timing:
            # Determine role from name
            role_map = {
                "kick": "kick", "k": "kick", "bd": "kick",
                "snare": "snare", "s": "snare", "sd": "snare",
                "hat_c": "hat_c", "hc": "hat_c", "chh": "hat_c",
                "hat_o": "hat_o", "ho": "hat_o", "ohh": "hat_o",
                "clap": "clap", "cl": "clap",
                "rim": "rim", "r": "rim",
                "tom": "default", "t": "default",
            }
            role = role_map.get(name, "default")
            humanized = humanize_timing(
                humanized, role,
                seed=rng.randint(0, 2**31) if seed else None
            )

        result.extend(humanized)

    return sorted(result, key=lambda x: x[0])


# ---------------------------------------------------------------------------
# §5  REVERB & PAN PRESETS (Manifesto Module 5)
# ---------------------------------------------------------------------------

# Reverb matrix: role -> (room_size, wet, damping)
REVERB_PRESETS: Dict[str, Tuple[float, float, float]] = {
    "kick":      (0.0, 0.0, 0.0),     # bone dry
    "sub":       (0.0, 0.0, 0.0),     # bone dry
    "snare":     (0.45, 0.15, 0.6),   # plate, subtle
    "clap":      (0.45, 0.15, 0.6),
    "hat":       (0.3, 0.08, 0.7),    # minimal
    "rim":       (0.35, 0.10, 0.65),
    "bass":      (0.2, 0.05, 0.8),    # barely there
    "acid":      (0.3, 0.10, 0.7),
    "lead":      (0.55, 0.35, 0.4),   # medium space + delay
    "melody":    (0.55, 0.35, 0.4),
    "pad":       (0.80, 0.50, 0.3),   # lush, deep
    "strings":   (0.85, 0.55, 0.25),  # hall
    "drone":     (0.90, 0.60, 0.2),   # vast
    "texture":   (0.85, 0.50, 0.25),
    "whisper":   (0.90, 0.60, 0.2),
    "fx":        (0.75, 0.45, 0.35),
}

# Pan presets: role -> pan value (-1.0 left, +1.0 right)
PAN_PRESETS: Dict[str, float] = {
    "kick":      0.0,     # center
    "sub":       0.0,     # center (mono below 150Hz mandatory)
    "snare":     -0.05,   # barely left
    "clap":      0.0,
    "hat_c":     0.25,    # right-ish
    "hat_o":     0.20,
    "rim":       -0.15,
    "bass":      0.0,
    "acid":      -0.10,
    "lead":      0.0,
    "melody":    0.0,
    "pad":       0.0,     # stereo via chorus, not pan
    "strings":   0.0,
    "sequencer": 0.15,
    "texture":   0.0,     # stereo via LFO pan
    "whisper":   0.0,     # per-event random pan
}


def get_reverb(role: str) -> Tuple[float, float, float]:
    """Get (room_size, wet, damping) for a given instrument role."""
    return REVERB_PRESETS.get(role, (0.5, 0.25, 0.5))


def get_pan(role: str) -> float:
    """Get default pan position for a given instrument role."""
    return PAN_PRESETS.get(role, 0.0)


# ---------------------------------------------------------------------------
# §6  FREQUENCY LAYERING (Manifesto Module 3)
# ---------------------------------------------------------------------------

def hp_for_role(signal: np.ndarray, role: str,
                sr: int = 44100) -> np.ndarray:
    """
    Apply high-pass filter based on instrument role.
    Manifesto: everything non-bass gets HP to clear low-end mud.

    Cutoff frequencies:
      - kick/sub/bass: no filter (they own the lows)
      - pad/strings: 120 Hz (clear sub-bass rumble)
      - lead/melody: 200 Hz
      - hat/rim/fx: 400 Hz (they have no business below this)
      - texture/whisper: 300 Hz
    """
    HP_CUTOFFS = {
        "kick": 0, "sub": 0, "bass": 0, "acid": 0,
        "pad": 120, "strings": 100, "drone": 80,
        "lead": 200, "melody": 200, "sequencer": 180,
        "snare": 80, "clap": 100,
        "hat": 400, "hat_c": 400, "hat_o": 400, "rim": 350,
        "texture": 300, "whisper": 300, "fx": 250,
    }

    cutoff = HP_CUTOFFS.get(role, 150)
    if cutoff == 0:
        return signal

    nyq = sr / 2
    cutoff = min(cutoff, nyq - 100)
    if cutoff < 20:
        return signal

    sos = butter(2, cutoff, btype="highpass", fs=sr, output="sos")
    return sosfilt(sos, signal).astype(np.float32)


# ---------------------------------------------------------------------------
# §7  MELODY GENERATION (Manifesto Module 2)
# ---------------------------------------------------------------------------

# Common scales as semitone offsets from root
SCALES = {
    "minor":          [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "dorian":         [0, 2, 3, 5, 7, 9, 10],
    "phrygian":       [0, 1, 3, 5, 7, 8, 10],
    "pentatonic_min": [0, 3, 5, 7, 10],
    "pentatonic_maj": [0, 2, 4, 7, 9],
    "blues":          [0, 3, 5, 6, 7, 10],
    "lydian":         [0, 2, 4, 6, 7, 9, 11],
    "mixolydian":     [0, 2, 4, 5, 7, 9, 10],
    "whole_tone":     [0, 2, 4, 6, 8, 10],
}


def scale_notes(root_midi: int, scale_name: str = "minor",
                octaves: int = 2) -> List[int]:
    """Get all MIDI notes in a scale across N octaves."""
    intervals = SCALES.get(scale_name, SCALES["minor"])
    notes = []
    for octave in range(octaves):
        for iv in intervals:
            notes.append(root_midi + octave * 12 + iv)
    return notes


def generate_melody_phrase(root_midi: int,
                           scale_name: str = "minor",
                           bars: int = 4,
                           steps_per_bar: int = 16,
                           density: float = 0.4,
                           seed: Optional[int] = None
                           ) -> List[Tuple[int, int, float]]:
    """
    Generate a call-and-response melody phrase (Manifesto Module 2.1).

    Structure (4 bars):
      Bar 1-2 (question): ascending tendency, ends on 2nd or 5th degree
      Bar 3-4 (answer):   same rhythm, descending, ends on tonic (long note)
      Last 2 beats of bar 4: silence ("breath", Module 2.2)

    Args:
        root_midi: root note (e.g. 57 = A3)
        scale_name: scale to use
        bars: number of bars (should be 4 or 8)
        steps_per_bar: rhythmic resolution
        density: fraction of steps that have notes (0.0-1.0)
        seed: random seed

    Returns:
        List of (step_index, midi_note, duration_steps)
        where step_index is absolute position in the phrase
    """
    rng = np.random.RandomState(seed)
    notes = scale_notes(root_midi, scale_name, octaves=2)
    total_steps = bars * steps_per_bar
    half = total_steps // 2

    phrase = []

    # Generate rhythm pattern (same for question and answer)
    rhythm = []
    for step in range(half):
        if rng.random() < density:
            dur = rng.choice([1, 2, 2, 4, 4, 8])  # weighted toward longer
            rhythm.append((step, dur))

    # Remove notes in last 2 beats of bar 2 and bar 4 ("breath")
    breath_start_q = half - steps_per_bar // 2
    breath_start_a = total_steps - steps_per_bar // 2
    rhythm = [(s, d) for s, d in rhythm if s < breath_start_q]

    # Question (bars 1-2): ascending tendency
    center_idx = len(notes) // 2
    pitch_idx = center_idx - 2  # start low
    for step, dur in rhythm:
        # Tend upward
        move = rng.choice([-1, 0, 1, 1, 2])  # biased up
        pitch_idx = max(0, min(len(notes) - 1, pitch_idx + move))
        phrase.append((step, notes[pitch_idx], dur))

    # End question on 2nd or 5th degree
    if phrase:
        target_degrees = [2, 7]  # 2nd (whole step) or 5th (perfect fifth)
        last_step, _, last_dur = phrase[-1]
        target_note = root_midi + rng.choice(target_degrees)
        # Adjust octave to be near current range
        while target_note < notes[pitch_idx] - 6:
            target_note += 12
        while target_note > notes[pitch_idx] + 6:
            target_note -= 12
        phrase[-1] = (last_step, target_note, last_dur)

    # Answer (bars 3-4): same rhythm, descending, end on tonic
    pitch_idx = center_idx + 2  # start high
    for step, dur in rhythm:
        move = rng.choice([1, 0, -1, -1, -2])  # biased down
        pitch_idx = max(0, min(len(notes) - 1, pitch_idx + move))
        phrase.append((step + half, notes[pitch_idx], dur))

    # End answer on tonic (long note)
    if len(phrase) > len(rhythm):
        last_step, _, _ = phrase[-1]
        tonic = root_midi
        # Find nearest tonic in range
        while tonic < notes[center_idx] - 6:
            tonic += 12
        while tonic > notes[center_idx] + 6:
            tonic -= 12
        phrase[-1] = (last_step, tonic, 8)  # long resolve note

    return phrase


# ---------------------------------------------------------------------------
# §8  GAIN STAGING (Manifesto Module 7.2)
# ---------------------------------------------------------------------------

# Target peak levels in dBFS for each role
GAIN_STAGING_DBFS: Dict[str, float] = {
    "sub":       -12.0,
    "kick":      -14.0,
    "cello":     -14.0,
    "piano":     -16.0,
    "harp":      -18.0,
    "pad":       -20.0,
    "texture":   -22.0,
    "reverb":    -26.0,
}

# Linear gain equivalents (for mixing)
GAIN_STAGING_LINEAR: Dict[str, float] = {
    role: 10 ** (db / 20.0) for role, db in GAIN_STAGING_DBFS.items()
}

# Practical mix gains for render_*.py scripts (summing multiple layers)
# These are relative to each other, assuming 6-10 layers summed
MIX_GAINS: Dict[str, float] = {
    "drums":     0.80,
    "kick_extra": 0.65,
    "sub":       0.60,
    "bass":      0.55,
    "acid":      0.50,
    "stabs":     0.45,
    "sequencer": 0.40,
    "pad":       0.35,
    "lead":      0.40,
    "whisper":   0.30,
    "texture":   0.15,
    "dub_fx":    0.35,
}


def mix_gain(role: str) -> float:
    """Get recommended mix gain for a role."""
    return MIX_GAINS.get(role, 0.40)


# ---------------------------------------------------------------------------
# §9  COMPOSITION ORDER (Manifesto Module 6)
# ---------------------------------------------------------------------------

COMPOSITION_ORDER = """
1. FORM:     Define sections (intro/verse/build/drop/breakdown/outro), bar counts
2. HARMONY:  Choose progression -> voice_lead_sequence() -> contrapuntal bass
3. RHYTHM:   Kick/sub on grid -> euclidean_rhythm() for percussion
4. MELODY:   generate_melody_phrase() with mandatory rests
5. FREQUENCY: hp_for_role() on all non-bass -> check conflicts
6. GROOVE:   humanize_drum_events() AFTER notes are placed
7. SPACE:    get_reverb(role) + get_pan(role) + sidechain + mono check
"""
