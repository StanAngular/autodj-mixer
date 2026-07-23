"""
instrument.py — High-level FluidSynth rendering for render scripts.

Each instrument call gets proper MIDI CC setup:
  CC1  (Modulation)   — vibrato for strings/wind after note attack
  CC10 (Pan)          — stereo positioning
  CC11 (Expression)   — dynamics shaping
  CC64 (Sustain Ped.) — overlapping pad/piano notes
  CC91 (Reverb Send)  — FluidSynth built-in reverb per instrument

Usage:
    from autodj.generate.instrument import render_notes, render_chords, render_drums, GM

    notes  = [(0.0, 72, 80, 1.5), (1.5, 75, 70, 1.0)]
    flute  = render_notes("flute", notes, duration=120.0)

    chords = [(0.0, [60, 63, 67], 60, 8.0)]
    pad    = render_chords("slow_strings", chords, duration=120.0)

    hits   = [(0.0, "kick", 110), (0.5, "snare", 90)]
    drums  = render_drums(hits, duration=120.0)

All return np.ndarray shape (N, 2) float32 stereo.
"""

import logging
import numpy as np

from autodj.generate.backends.fluidsynth import (
    FluidSynthBackend, GM_PROGRAMS, GM_DRUMS, find_sf2,
)

log = logging.getLogger(__name__)

# ── Extended GM program map ─────────────────────────────────────────────────

EXTRA_PROGRAMS = {
    # Chromatic percussion
    "celesta": 8, "glockenspiel": 9, "music_box": 10,
    "vibraphone": 11, "marimba": 12, "xylophone": 13,
    "tubular_bells": 14, "dulcimer": 15,
    # Organ
    "accordion": 21, "harmonica": 22, "tango_accordion": 23,
    # Guitar
    "nylon_guitar": 24, "steel_guitar": 25, "jazz_guitar": 26,
    "muted_guitar": 28, "distortion_guitar": 30,
    # Bass (extended)
    "slap_bass": 36, "synth_bass_2": 39,
    # Strings (extended)
    "tremolo_strings": 44, "pizzicato_strings": 45,
    "harp": 46, "timpani": 47,
    # Ensemble
    "choir_aahs": 52, "voice_oohs": 53, "synth_choir": 54,
    # Brass (extended)
    "muted_trumpet": 59,
    # Reed
    "oboe": 68, "english_horn": 69, "bassoon": 70, "clarinet": 71,
    # Pipe
    "piccolo": 72, "recorder": 74, "shakuhachi": 77, "whistle": 78, "ocarina": 79,
    # Synth lead
    "synth_calliope": 82, "synth_chiff": 83, "charang": 84,
    "synth_voice": 85, "fifths": 86, "bass_lead": 87,
    # Synth pad
    "synth_pad_new_age": 88, "synth_pad_polysynth": 90,
    "synth_pad_metallic": 93, "synth_pad_halo": 94, "synth_pad_sweep": 95,
    # Ethnic
    "sitar": 104, "banjo": 105, "shamisen": 106, "koto": 107,
    "kalimba": 108, "bagpipe": 109, "fiddle": 110, "shanai": 111,
    # Sound effects
    "tinkle_bell": 112, "steel_drums": 114,
}

GM = {**GM_PROGRAMS, **EXTRA_PROGRAMS}


# ── Instrument categories and CC behaviour ──────────────────────────────────

# Each category defines how notes should be played (CC values, release, sustain)
_CATEGORIES = {
    "strings": {
        "instruments": {"violin", "viola", "cello", "string_ensemble", "slow_strings",
                         "synth_strings", "tremolo_strings", "pizzicato_strings"},
        "note_release": 0.92,
        "modulation": 22,      # CC1 vibrato depth -- 50 was too eerie on GM strings
        "mod_delay": 0.35,     # longer delay so attack is clean
        "expression": 108,     # CC11
        "reverb_send": 48,     # CC91
        "sustain": False,
    },
    "lead_wind": {
        "instruments": {"flute", "pan_flute", "shakuhachi", "ocarina", "clarinet",
                         "oboe", "english_horn", "bassoon", "piccolo", "recorder", "whistle"},
        "note_release": 0.88,
        "modulation": 28,      # gentle vibrato for winds
        "mod_delay": 0.35,     # clean attack, vibrato enters after
        "expression": 105,
        "reverb_send": 45,
        "sustain": False,
    },
    "lead_synth": {
        "instruments": {"synth_lead_square", "synth_lead_sawtooth", "synth_calliope",
                         "synth_chiff", "charang", "bass_lead", "fifths"},
        "note_release": 0.82,
        "modulation": 0,
        "mod_delay": 0.0,
        "expression": 100,
        "reverb_send": 28,
        "sustain": False,
    },
    "pad": {
        "instruments": {"synth_pad_warm", "synth_pad_choir", "synth_pad_metallic",
                         "synth_pad_halo", "synth_pad_sweep", "synth_pad_new_age",
                         "synth_pad_polysynth", "choir_aahs", "voice_oohs", "synth_choir",
                         "synth_voice"},
        "note_release": 1.08,   # notes overlap slightly for seamless pads
        "modulation": 15,
        "mod_delay": 0.5,
        "expression": 98,
        "reverb_send": 64,
        "sustain": True,
    },
    "keys": {
        "instruments": {"grand_piano", "electric_piano", "harpsichord", "celesta",
                         "music_box", "vibraphone", "marimba", "xylophone", "glockenspiel",
                         "kalimba", "tubular_bells", "tinkle_bell", "dulcimer"},
        "note_release": 0.88,
        "modulation": 0,
        "mod_delay": 0.0,
        "expression": 95,
        "reverb_send": 38,
        "sustain": False,
    },
    "bass": {
        "instruments": {"acoustic_bass", "electric_bass_finger", "electric_bass_pick",
                         "fretless_bass", "synth_bass_1", "synth_bass_2", "slap_bass"},
        "note_release": 0.72,
        "modulation": 0,
        "mod_delay": 0.0,
        "expression": 100,
        "reverb_send": 12,
        "sustain": False,
    },
    "ethnic": {
        "instruments": {"sitar", "harp", "steel_drums", "shanai", "banjo", "koto",
                         "shamisen", "fiddle", "bagpipe", "tango_accordion", "accordion"},
        "note_release": 0.90,
        "modulation": 28,
        "mod_delay": 0.20,
        "expression": 100,
        "reverb_send": 42,
        "sustain": False,
    },
    "brass": {
        "instruments": {"trumpet", "trombone", "french_horn", "brass_section",
                         "muted_trumpet", "tuba"},
        "note_release": 0.86,
        "modulation": 22,
        "mod_delay": 0.25,
        "expression": 105,
        "reverb_send": 36,
        "sustain": False,
    },
    "guitar": {
        "instruments": {"nylon_guitar", "steel_guitar", "jazz_guitar", "acoustic_guitar",
                         "electric_guitar_clean", "overdriven_guitar", "muted_guitar",
                         "distortion_guitar"},
        "note_release": 0.82,
        "modulation": 18,
        "mod_delay": 0.30,
        "expression": 100,
        "reverb_send": 38,
        "sustain": False,
    },
}

_DEFAULT_CAT = {
    "note_release": 0.88,
    "modulation": 10,
    "mod_delay": 0.30,
    "expression": 100,
    "reverb_send": 32,
    "sustain": False,
}

# Build reverse lookup
_INST_TO_CAT: dict = {}
for _cat_name, _cat_data in _CATEGORIES.items():
    for _inst in _cat_data["instruments"]:
        _INST_TO_CAT[_inst] = _cat_name


def _get_cat(instrument: str) -> dict:
    """Return category settings for an instrument name."""
    cat_name = _INST_TO_CAT.get(instrument)
    if cat_name:
        return _CATEGORIES[cat_name]
    return _DEFAULT_CAT


def _resolve_program(instrument: str) -> int:
    """Resolve instrument name to GM program number."""
    prog = GM.get(instrument)
    if prog is not None:
        return prog
    try:
        return int(instrument)
    except (TypeError, ValueError):
        pass
    log.warning(f"Unknown instrument '{instrument}', falling back to grand_piano (0)")
    return 0


def _cc_init(channel: int, cat: dict) -> list:
    """
    Build CC setup events at t=0.001s for a channel.
    Sets expression, reverb send, resets modulation.
    Pan is left at center (64) by default.
    """
    return [
        (0.001, "control", channel, 7,  120),             # CC7  Volume = 120
        (0.001, "control", channel, 10, 64),              # CC10 Pan = center
        (0.001, "control", channel, 11, cat["expression"]),  # CC11 Expression
        (0.001, "control", channel, 91, cat["reverb_send"]),  # CC91 Reverb Send
        (0.001, "control", channel, 1,  0),               # CC1  Modulation = 0 start
    ]


def _vibrato_events(channel: int, cat: dict, notes: list) -> list:
    """
    Add CC1 (modulation = vibrato) events for each note longer than mod_delay.
    - CC1 ramps to cat["modulation"] after cat["mod_delay"] seconds
    - CC1 drops back to 0 when note ends
    This creates natural vibrato that starts after the attack.
    """
    if cat["modulation"] == 0:
        return []

    events = []
    depth      = cat["modulation"]
    delay      = cat["mod_delay"]
    nr         = cat["note_release"]

    for t, note, vel, dur in notes:
        if dur < delay + 0.05:
            continue  # too short for vibrato
        note_off_t = t + dur * nr
        # Modulation ON after delay
        events.append((t + delay, "control", channel, 1, depth))
        # Modulation OFF just before note off (prevents bleed to next note)
        events.append((max(t + delay + 0.05, note_off_t - 0.08), "control", channel, 1, 0))

    return events


def _sustain_events(channel: int, cat: dict, notes: list) -> list:
    """
    CC64 (Sustain Pedal) for pad/piano instruments.
    Opens sustain on each note, closes just after note_off.
    Lets samples ring naturally instead of cutting off.
    """
    if not cat.get("sustain"):
        return []

    events = []
    nr = cat["note_release"]
    for t, note, vel, dur in notes:
        events.append((t,             "control", channel, 64, 127))  # sustain on
        events.append((t + dur * nr + 0.05, "control", channel, 64, 0))   # sustain off
    return events


# ── Core render functions ───────────────────────────────────────────────────

def render_notes(instrument: str, notes: list, duration: float,
                 sr: int = 44100, channel: int = 0,
                 note_release: float = None) -> np.ndarray:
    """
    Render note events through a GM instrument with full CC expression.

    Args:
        instrument:   GM name (see GM dict) or program number as string
        notes:        [(time_s, midi_note, velocity, note_dur_s), ...]
        duration:     total output length in seconds
        sr:           sample rate
        channel:      MIDI channel (0-8, 10-15; avoid 9 = drums)
        note_release: override release fraction (default: per-category)

    Returns:
        np.ndarray (N, 2) float32 stereo
    """
    program = _resolve_program(instrument)
    cat     = _get_cat(instrument)
    nr      = note_release if note_release is not None else cat["note_release"]

    events  = [(0.0, "program", channel, 0, program)]
    events += _cc_init(channel, cat)
    events += _vibrato_events(channel, cat, notes)
    events += _sustain_events(channel, cat, [(t, n, v, d) for t, n, v, d in notes])

    for t, note, vel, dur in notes:
        events.append((t,          "note_on",  channel, int(note), int(vel)))
        events.append((t + dur*nr, "note_off", channel, int(note), 0))

    with FluidSynthBackend(find_sf2(), sr) as backend:
        return backend.render(events, duration)


def render_chords(instrument: str, chords: list, duration: float,
                  sr: int = 44100, channel: int = 1,
                  note_release: float = None) -> np.ndarray:
    """
    Render chord events through a GM instrument.

    Args:
        instrument: GM name
        chords:     [(time_s, [midi_note, ...], velocity, chord_dur_s), ...]
        duration:   total output length
        note_release: override release fraction (default: per-category)
    """
    program = _resolve_program(instrument)
    cat     = _get_cat(instrument)
    nr      = note_release if note_release is not None else cat["note_release"]

    # Build flat note list for vibrato/sustain helpers
    flat_notes = [(t, notes[0] if notes else 60, vel, dur)
                  for t, notes, vel, dur in chords]

    events  = [(0.0, "program", channel, 0, program)]
    events += _cc_init(channel, cat)
    events += _vibrato_events(channel, cat, flat_notes)
    events += _sustain_events(channel, cat, flat_notes)

    for t, midi_notes, vel, dur in chords:
        for note in midi_notes:
            events.append((t,          "note_on",  channel, int(note), int(vel)))
            events.append((t + dur*nr, "note_off", channel, int(note), 0))

    with FluidSynthBackend(find_sf2(), sr) as backend:
        return backend.render(events, duration)


def render_drums(hits: list, duration: float,
                 sr: int = 44100) -> np.ndarray:
    """
    Render drum hits using GM drum kit (channel 9).

    Args:
        hits:     [(time_s, drum_name_or_note, velocity), ...]
                  drum_name: "kick", "snare", "clap", "closed_hat", "open_hat",
                             "ride", "crash", "tom_mid", "tom_low"
    """
    # Drum CC setup: expression = 110, reverb = 20 (minimal)
    events = [
        (0.001, "control", 9, 7,  120),
        (0.001, "control", 9, 11, 110),
        (0.001, "control", 9, 91, 20),
    ]
    for t, drum, vel in hits:
        note = drum if isinstance(drum, int) else GM_DRUMS.get(drum, 36)
        events.append((t,        "note_on",  9, note, int(vel)))
        events.append((t + 0.08, "note_off", 9, note, 0))

    with FluidSynthBackend(find_sf2(), sr) as backend:
        return backend.render(events, duration)


def render_multi(layers: list, duration: float,
                 sr: int = 44100) -> np.ndarray:
    """
    Render multiple instrument layers in a single FluidSynth pass.
    More efficient when per-layer effects are not needed.

    Args:
        layers: [
            {"instrument": "flute",  "channel": 0, "notes": [(t, midi, vel, dur), ...]},
            {"instrument": "drums",  "channel": 9, "hits":  [(t, drum_name, vel), ...]},
            ...
        ]
    """
    events = []
    for layer in layers:
        ch   = layer.get("channel", 0)
        inst = layer.get("instrument", "grand_piano")

        if ch == 9 or inst == "drums":
            events += [
                (0.001, "control", 9, 7,  120),
                (0.001, "control", 9, 11, 110),
                (0.001, "control", 9, 91, 20),
            ]
            for t, drum, vel in layer.get("hits", []):
                note = GM_DRUMS.get(drum, 36) if isinstance(drum, str) else drum
                events.append((t,        "note_on",  9, note, int(vel)))
                events.append((t + 0.08, "note_off", 9, note, 0))
        else:
            program   = _resolve_program(inst)
            cat       = _get_cat(inst)
            nr        = cat["note_release"]
            flat_notes = layer.get("notes", [])

            events.append((0.0, "program", ch, 0, program))
            events += _cc_init(ch, cat)
            events += _vibrato_events(ch, cat, flat_notes)
            events += _sustain_events(ch, cat, flat_notes)

            for t, note, vel, dur in flat_notes:
                events.append((t,          "note_on",  ch, int(note), int(vel)))
                events.append((t + dur*nr, "note_off", ch, int(note), 0))

    with FluidSynthBackend(find_sf2(), sr) as backend:
        return backend.render(events, duration)


# ── Quick reference ─────────────────────────────────────────────────────────

def list_instruments() -> list:
    return sorted(GM.keys())

def list_drums() -> list:
    return sorted(GM_DRUMS.keys())
