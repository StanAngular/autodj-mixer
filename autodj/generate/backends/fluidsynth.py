"""
backends/fluidsynth.py — FluidSynth + SoundFont backend (SPEC 008, G1)

Renders MIDI sequences to WAV using pyfluidsynth + SF2 soundfont banks.

Dependencies:
    apt install fluidsynth libfluidsynth-dev
    pip install pyfluidsynth mido

SF2 banks (place in /opt/autodj-mixer/shared/):
    MuseScore_General.sf2   -- full GM orchestra (206 MB)
    TimGM6mb.sf2            -- compact GM bank (5.7 MB, good fallback)

Instrument mapping (in style JSON, per channel):
    "instrument_mapping": {
        "piano":  {"channel": 0, "bank": 0, "program": 0},
        "strings":{"channel": 1, "bank": 0, "program": 48},
        "bass":   {"channel": 2, "bank": 0, "program": 32},
        "drums":  {"channel": 9, "bank": 0, "program": 0}   // ch9 = GM drums
    }

Usage from engine.py:
    from backends.fluidsynth import FluidSynthBackend
    backend = FluidSynthBackend(sf2_path, sample_rate=44100)
    wav = backend.render(midi_events, duration_s, bpm)
    backend.close()
"""

import os
import sys
import array
import tempfile
import logging

import numpy as np

log = logging.getLogger(__name__)

# Default SF2 search paths
SF2_SEARCH_PATHS = [
    "/opt/autodj-mixer/shared/MuseScore_General.sf2",
    "/opt/autodj-mixer/shared/TimGM6mb.sf2",
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/soundfonts/FluidR3_GM.sf2",
]

# General MIDI program numbers (subset for quick reference)
GM_PROGRAMS = {
    # Piano
    "grand_piano": 0, "electric_piano": 4, "harpsichord": 6,
    # Strings
    "violin": 40, "viola": 41, "cello": 42, "string_ensemble": 48,
    "slow_strings": 49, "synth_strings": 50,
    # Brass
    "trumpet": 56, "trombone": 57, "french_horn": 60, "brass_section": 61,
    # Reed / Wind
    "alto_sax": 65, "tenor_sax": 66, "flute": 73, "pan_flute": 75,
    # Bass
    "acoustic_bass": 32, "electric_bass_finger": 33, "electric_bass_pick": 34,
    "fretless_bass": 35, "synth_bass_1": 38,
    # Guitar
    "acoustic_guitar": 25, "electric_guitar_clean": 27, "overdriven_guitar": 29,
    # Organ
    "drawbar_organ": 16, "rock_organ": 18, "church_organ": 19,
    # Synth
    "synth_lead_square": 80, "synth_lead_sawtooth": 81,
    "synth_pad_warm": 89, "synth_pad_choir": 91,
    # Percussion (ch9 only)
    "drums": 0,
}

# GM drum note numbers (channel 9)
GM_DRUMS = {
    "kick": 36, "snare": 38, "clap": 39, "closed_hat": 42,
    "open_hat": 46, "ride": 51, "crash": 49, "tom_mid": 47, "tom_low": 43,
}


def find_sf2(preferred: str = None) -> str:
    """Return first available SF2 path, or raise."""
    candidates = ([preferred] if preferred else []) + SF2_SEARCH_PATHS
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    raise FileNotFoundError(
        "No SF2 soundfont found. Install one of:\n"
        "  /opt/autodj-mixer/shared/MuseScore_General.sf2\n"
        "  /opt/autodj-mixer/shared/TimGM6mb.sf2\n"
        "Or: apt install fluid-soundfont-gm"
    )


class FluidSynthBackend:
    """
    Wraps pyfluidsynth for MIDI-event-list → numpy WAV rendering.

    midi_events format:
        List of (time_s, type, channel, data...)
        type="note_on":  (time_s, "note_on",  ch, note, velocity)
        type="note_off": (time_s, "note_off", ch, note, velocity)
        type="program":  (time_s, "program",  ch, bank, program)
        type="control":  (time_s, "control",  ch, ctrl, value)
        type="pitch":    (time_s, "pitch",    ch, value)  # -8192..8191
    """

    def __init__(self, sf2_path: str = None, sample_rate: int = 44100):
        try:
            import fluidsynth as fs
        except ImportError:
            raise RuntimeError(
                "pyfluidsynth not available. Install:\n"
                "  apt install fluidsynth libfluidsynth-dev\n"
                "  pip install pyfluidsynth"
            )

        self._fs = fs
        self.sample_rate = sample_rate
        self.sf2_path = find_sf2(sf2_path)

        log.info(f"FluidSynth: loading {self.sf2_path}")

        self.synth = fs.Synth(samplerate=float(sample_rate))
        self.sfid = self.synth.sfload(self.sf2_path)
        if self.sfid < 0:
            raise RuntimeError(f"Failed to load SF2: {self.sf2_path}")

        # Activate GM bank 0, program 0 on all channels by default
        for ch in range(16):
            self.synth.bank_select(ch, 0)
            self.synth.program_change(ch, 0)

        log.info(f"FluidSynth ready: SR={sample_rate} sf2={os.path.basename(self.sf2_path)}")

    def close(self):
        try:
            self.synth.delete()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def render(self, midi_events: list, duration_s: float) -> np.ndarray:
        """
        Render midi_events to stereo float32 numpy array [-1, 1].

        Args:
            midi_events: sorted list of (time_s, type, channel, *data)
            duration_s:  total output duration in seconds

        Returns:
            np.ndarray shape (N, 2) float32, sample_rate=self.sample_rate
        """
        SR = self.sample_rate
        total_samples = int(duration_s * SR)
        # FluidSynth renders in chunks; we'll use 64-sample blocks
        CHUNK = 64

        output = np.zeros((total_samples, 2), dtype=np.float32)

        # Sort events by time
        events = sorted(midi_events, key=lambda e: e[0])
        ev_idx = 0
        n_events = len(events)

        sample_pos = 0
        while sample_pos < total_samples:
            chunk_time_s = sample_pos / SR

            # Dispatch all events up to this chunk's time
            while ev_idx < n_events and events[ev_idx][0] <= chunk_time_s:
                ev = events[ev_idx]
                ev_idx += 1
                self._dispatch(ev)

            # Render chunk
            chunk_end = min(sample_pos + CHUNK, total_samples)
            n = chunk_end - sample_pos

            samples = self.synth.get_samples(n)  # returns interleaved int16
            # Convert int16 interleaved → float32 stereo
            arr = np.frombuffer(samples, dtype=np.int16).reshape(-1, 2)
            arr_f = arr.astype(np.float32) / 32768.0
            output[sample_pos:chunk_end] = arr_f[:n]
            sample_pos = chunk_end

        return output

    def _dispatch(self, ev):
        t, etype, *rest = ev
        try:
            if etype == "note_on":
                ch, note, vel = rest
                self.synth.noteon(ch, note, vel)
            elif etype == "note_off":
                ch, note, vel = rest
                self.synth.noteoff(ch, note)
            elif etype == "program":
                ch, bank, program = rest
                self.synth.bank_select(ch, bank)
                self.synth.program_change(ch, program)
            elif etype == "control":
                ch, ctrl, val = rest
                self.synth.cc(ch, ctrl, val)
            elif etype == "pitch":
                ch, val = rest
                self.synth.pitch_bend(ch, val)
        except Exception as e:
            log.warning(f"FluidSynth event error {ev}: {e}")


# ---------------------------------------------------------------------------
# MIDI builder helpers
# ---------------------------------------------------------------------------

def hz_to_midi(freq_hz: float) -> int:
    """Convert frequency in Hz to MIDI note number (A4=440Hz=69)."""
    if freq_hz <= 0:
        return 0
    return int(round(69 + 12 * np.log2(freq_hz / 440.0)))


def build_melody_events(
    freqs: list,         # list of Hz (0 = rest), per step
    step_s: float,       # duration of each step in seconds
    channel: int = 0,
    velocity: int = 90,
    note_frac: float = 0.85,  # note length as fraction of step
) -> list:
    """
    Build note_on/note_off events from a frequency list.

    Returns list of (time_s, type, channel, note, velocity).
    """
    events = []
    for i, freq in enumerate(freqs):
        if freq <= 0:
            continue
        t_on = i * step_s
        t_off = t_on + step_s * note_frac
        note = hz_to_midi(freq)
        events.append((t_on,  "note_on",  channel, note, velocity))
        events.append((t_off, "note_off", channel, note, velocity))
    return events


def build_chord_events(
    chords: list,        # list of [freq, freq, ...], one per bar
    bar_s: float,        # bar duration in seconds
    channel: int = 1,
    velocity: int = 70,
    note_frac: float = 0.95,
) -> list:
    """
    Build chord note_on/note_off events from chord progression.
    Chords cycle if track is longer than progression.
    """
    events = []
    # We emit one chord per bar for duration_s implied by len(chords)*bar_s
    n_bars = len(chords)
    for i, chord in enumerate(chords):
        t_on = i * bar_s
        t_off = t_on + bar_s * note_frac
        for freq in chord:
            if freq <= 0:
                continue
            note = hz_to_midi(freq)
            events.append((t_on,  "note_on",  channel, note, velocity))
            events.append((t_off, "note_off", channel, note, velocity))
    return events


def build_drum_events(
    pattern: dict,       # same format as music_engine drums pattern
    bar_s: float,        # bar duration in seconds
    n_bars: int = 4,
) -> list:
    """
    Build GM drum events (channel 9) from a drum pattern dict.

    Supports:
        kick: [beat positions in 4/4]
        kick_16: [16th note positions]
        snare: [beat positions]
        snare_16: [16th note positions]
        hat: "every16" | "every8"
    """
    events = []
    step_4 = bar_s / 4       # quarter note
    step_16 = bar_s / 16     # 16th note
    VEL_KICK = 110
    VEL_SNARE = 100
    VEL_HAT = 80
    VEL_GHOST = 60
    OFF_DUR = 0.05           # drum note_off after 50ms

    for bar in range(n_bars):
        t0 = bar * bar_s

        # Kick
        if "kick" in pattern:
            for beat in pattern["kick"]:
                t = t0 + beat * step_4
                events += [
                    (t, "note_on",  9, GM_DRUMS["kick"], VEL_KICK),
                    (t + OFF_DUR, "note_off", 9, GM_DRUMS["kick"], 0),
                ]
        if "kick_16" in pattern:
            for pos in pattern["kick_16"]:
                t = t0 + pos * step_16
                events += [
                    (t, "note_on",  9, GM_DRUMS["kick"], VEL_KICK),
                    (t + OFF_DUR, "note_off", 9, GM_DRUMS["kick"], 0),
                ]

        # Snare
        snare_note = GM_DRUMS.get(pattern.get("snare_type", "snare"), GM_DRUMS["snare"])
        if "snare" in pattern:
            for beat in pattern["snare"]:
                t = t0 + beat * step_4
                events += [
                    (t, "note_on",  9, snare_note, VEL_SNARE),
                    (t + OFF_DUR, "note_off", 9, snare_note, 0),
                ]
        if "snare_16" in pattern:
            for pos in pattern["snare_16"]:
                t = t0 + pos * step_16
                events += [
                    (t, "note_on",  9, snare_note, VEL_SNARE),
                    (t + OFF_DUR, "note_off", 9, snare_note, 0),
                ]

        # Hi-hat
        hat_mode = pattern.get("hat", None)
        if hat_mode == "every16":
            for pos in range(16):
                t = t0 + pos * step_16
                vel = VEL_GHOST if (pos % 2 == 0 and pattern.get("hat_ghost")) else VEL_HAT
                events += [
                    (t, "note_on",  9, GM_DRUMS["closed_hat"], vel),
                    (t + OFF_DUR, "note_off", 9, GM_DRUMS["closed_hat"], 0),
                ]
        elif hat_mode == "every8":
            for pos in range(8):
                t = t0 + pos * (bar_s / 8)
                events += [
                    (t, "note_on",  9, GM_DRUMS["closed_hat"], VEL_HAT),
                    (t + OFF_DUR, "note_off", 9, GM_DRUMS["closed_hat"], 0),
                ]

    return events


def build_bass_events(
    roots: list,         # Hz per bar, cycles
    bar_s: float,
    n_bars: int = 4,
    channel: int = 2,
    velocity: int = 95,
) -> list:
    """
    Simple root-note bass: one note per bar.
    """
    events = []
    OFF_DUR = bar_s * 0.9
    for bar in range(n_bars):
        freq = roots[bar % len(roots)]
        if freq <= 0:
            continue
        t = bar * bar_s
        note = hz_to_midi(freq)
        events += [
            (t, "note_on",  channel, note, velocity),
            (t + OFF_DUR, "note_off", channel, note, 0),
        ]
    return events
