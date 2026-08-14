#!/usr/bin/env python3
"""
render_track.py -- Universal FluidSynth + Pedalboard track renderer.

Usage:
    python3 render_track.py liquid_dnb --send
    python3 render_track.py afro_house --bpm 122
    python3 render_track.py --list
"""
import sys, os, time, argparse
sys.path.insert(0, '/opt/autodj-mixer')

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

from autodj.generate.instrument import render_notes, render_chords, render_drums
from autodj.generate.music_theory import resolve_progression, voice_lead_sequence
from autodj.generate.synthcore import (
    apply_reverb, apply_delay, apply_chorus, apply_compressor, master_chain,
)

SR = 44100

# ── key / scale helpers ────────────────────────────────────────────────────

NOTE_MAP = {
    "C": 60, "C#": 61, "Db": 61, "D": 62, "D#": 63, "Eb": 63,
    "E": 64, "F": 65, "F#": 66, "Gb": 66, "G": 67, "G#": 68,
    "Ab": 68, "A": 69, "A#": 70, "Bb": 70, "B": 71,
}

MINOR_IV  = [0, 2, 3, 5, 7, 8, 10]     # natural minor
MINOR_MEL = [0, 2, 3, 5, 7, 9, 11]     # melodic minor (ascending)
DORIAN    = [0, 2, 3, 5, 7, 9, 10]     # dark but with major 6th
MAJOR_IV  = [0, 2, 4, 5, 7, 9, 11]     # major
PHRYGIAN  = [0, 1, 3, 5, 7, 8, 10]     # very dark, Spanish/Techno feel
PENTA_MIN = [0, 3, 5, 7, 10]           # minor pentatonic

MODE_MAP = {
    "minor": MINOR_IV, "major": MAJOR_IV, "dorian": DORIAN,
    "phrygian": PHRYGIAN, "melodic_minor": MINOR_MEL, "pentatonic": PENTA_MIN,
}

def parse_key(key_str: str) -> Tuple[int, str]:
    key_str = key_str.strip()
    if key_str.endswith('m'):
        return NOTE_MAP.get(key_str[:-1], 69), "minor"
    return NOTE_MAP.get(key_str, 69), "major"

def build_scale(root: int, mode: str = "minor") -> List[int]:
    intervals = MODE_MAP.get(mode, MINOR_IV)
    notes = []
    for oct in range(-1, 4):
        for iv in intervals:
            n = root + oct * 12 + iv
            if 24 <= n <= 108:
                notes.append(n)
    return sorted(set(notes))


# ── genre config ───────────────────────────────────────────────────────────

@dataclass
class GenreConfig:
    name: str
    bpm: int
    key: str
    dur: int
    progression: str
    scale_mode: str         = "minor"
    swing: float            = 0.0

    # Melodic style: "flowing" | "staccato" | "legato" | "syncopated" | "default"
    melodic_style: str      = "default"

    # GM instruments per role
    inst_pad:    str = "slow_strings"
    inst_lead:   str = "flute"
    inst_arp:    str = "vibraphone"
    inst_bass:   str = "fretless_bass"
    inst_accent: str = "kalimba"
    inst_counter: Optional[str] = None

    # Chord pad: how many bars per chord (8 = ambient drone, 4 = techno punchy)
    pad_bars: int = 8

    # Drum style
    drum_pattern: str = "four_on_floor"
    # Section structure (seconds)
    intro_s: float = 64.0
    drop_s:  float = 0.0
    break_s: float = 0.0
    drop2_s: float = 0.0
    outro_s: float = 0.0

    # Mix gains
    gain_drums: float = 0.50
    gain_pad:   float = 0.50
    gain_lead:  float = 0.52
    gain_arp:   float = 0.52
    gain_bass:  float = 0.55
    gain_accent:float = 0.45
    gain_counter:float = 0.42
    duck_db:    float = -4.5   # Q1: глубина сайдчейн-пампинга
    seed:       int = 0        # P86: 0 = НОВЫЙ трек каждый раз; явный = воспроизвести
    melody_engine: str = "motif"  # P86: motif | legacy
    arrange:    bool = True    # Q2: секционная аранжировка (филлы/плотность/ghosts)
    drum_bank:  str = ""       # S4: банк драм-машины (RolandTR909/TR808/AkaiLinn…); '' = env/дефолт

    # Reverb presets per layer: (room, wet, damp)
    fx_pad:    Tuple = (0.82, 0.32, 0.48)
    fx_lead:   Tuple = (0.80, 0.42, 0.38)
    fx_arp:    Tuple = (0.68, 0.32, 0.48)
    fx_bass:   Tuple = (0.28, 0.10, 0.72)
    fx_drums:  Tuple = (0.22, 0.10, 0.68)
    fx_accent: Tuple = (0.72, 0.36, 0.44)
    fx_counter:Tuple = (0.75, 0.40, 0.42)

    # Optional effects
    delay_arp:   bool = True
    delay_lead:  bool = False
    chorus_pad:  bool = True
    chorus_lead: bool = False

    # Composition params
    lead_density:   float = 0.5
    arp_density:    float = 0.6
    accent_density: float = 0.35
    bass_syncopation: float = 0.5
    lead_register: str = "high"

    target_db: float = -2.0


GENRES: Dict[str, GenreConfig] = {
    # ── SPA / CHILL ───────────────────────────────────────────────────────
    "spa_downbeat": GenreConfig(
        name="Spa Downbeat", bpm=85, key="Cm", dur=610,
        progression="lounge", scale_mode="minor", swing=0.24,
        melodic_style="legato",
        inst_pad="slow_strings", inst_lead="pan_flute",
        inst_arp="kalimba", inst_bass="fretless_bass", inst_accent="vibraphone",
        inst_counter="harp",
        drum_pattern="breakbeat",
        gain_bass=0.58, gain_pad=0.52,
        fx_pad=(0.82, 0.35, 0.48),
        lead_density=0.35, arp_density=0.45, accent_density=0.30,
        bass_syncopation=0.4, target_db=-3.5,
        intro_s=60,
    ),

    # ── TECHNO ────────────────────────────────────────────────────────────
    "indie_techno": GenreConfig(
        name="Indie Techno", bpm=142, key="Am", dur=600,
        progression="indie", scale_mode="dorian", swing=0.0,
        melodic_style="staccato",
        inst_pad="synth_pad_warm", inst_lead="electric_piano",
        inst_arp="synth_lead_square", inst_bass="synth_bass_1", inst_accent="glockenspiel",
        inst_counter="synth_lead_sawtooth",
        pad_bars=4,
        drum_pattern="four_on_floor",
        gain_drums=0.65, gain_lead=0.55, gain_arp=0.50, gain_bass=0.60,
        fx_drums=(0.12, 0.07, 0.72), delay_arp=True, delay_lead=True,
        lead_density=0.60, arp_density=0.72, bass_syncopation=0.3,
        target_db=-1.5, intro_s=80,
    ),
    "dark_matter": GenreConfig(
        name="Dark Matter Techno", bpm=138, key="Dm", dur=720,
        progression="dark_techno", scale_mode="phrygian", swing=0.0,
        melodic_style="staccato",
        inst_pad="synth_pad_warm", inst_lead="synth_lead_sawtooth",
        inst_arp="synth_lead_square", inst_bass="synth_bass_1", inst_accent="tubular_bells",
        inst_counter="electric_piano",
        pad_bars=4,
        drum_pattern="four_on_floor",
        gain_drums=0.70, gain_pad=0.42, gain_lead=0.55, gain_arp=0.48, gain_bass=0.65,
        fx_pad=(0.88, 0.38, 0.42), fx_drums=(0.10, 0.06, 0.78),
        delay_arp=True, chorus_pad=True,
        lead_density=0.50, arp_density=0.65, bass_syncopation=0.25,
        target_db=-1.0, intro_s=96,
    ),
    "dark_cosmic": GenreConfig(
        name="Dark Cosmic", bpm=133, key="Dm", dur=600,
        progression="dark_techno", scale_mode="phrygian", swing=0.0,
        melodic_style="staccato",
        inst_pad="synth_pad_warm", inst_lead="synth_lead_sawtooth",
        inst_arp="synth_lead_square", inst_bass="synth_bass_1", inst_accent="tubular_bells",
        pad_bars=4,
        drum_pattern="four_on_floor",
        gain_drums=0.65, gain_pad=0.45, gain_lead=0.52, gain_arp=0.50, gain_bass=0.62,
        fx_pad=(0.92, 0.42, 0.35), delay_arp=True,
        lead_density=0.48, arp_density=0.65, bass_syncopation=0.2,
        target_db=-1.5, intro_s=80,
    ),

    # ── TRANCE ────────────────────────────────────────────────────────────
    "deep_trance": GenreConfig(
        name="Deep Trance", bpm=138, key="Am", dur=600,
        progression="trance", scale_mode="minor", swing=0.0,
        melodic_style="flowing",
        inst_pad="synth_pad_choir", inst_lead="ocarina",
        inst_arp="synth_lead_sawtooth", inst_bass="electric_bass_finger",
        inst_accent="celesta", inst_counter="violin",
        drum_pattern="four_on_floor",
        gain_drums=0.65, gain_lead=0.55, gain_arp=0.58, gain_bass=0.60, gain_counter=0.42,
        delay_arp=True, delay_lead=True, chorus_pad=True,
        lead_density=0.55, arp_density=0.78, bass_syncopation=0.2,
        target_db=-1.5, intro_s=80,
    ),

    # ── TRIBAL / PSYCHEDELIC ──────────────────────────────────────────────
    "tribal_psychedelic": GenreConfig(
        name="Tribal Psychedelic", bpm=128, key="Em", dur=600,
        progression="psychedelic", scale_mode="dorian", swing=0.15,
        melodic_style="syncopated",
        inst_pad="synth_pad_sweep", inst_lead="sitar",
        inst_arp="kalimba", inst_bass="synth_bass_2", inst_accent="steel_drums",
        inst_counter="ocarina",
        drum_pattern="breakbeat",
        gain_drums=0.60, gain_pad=0.45, gain_lead=0.52, gain_arp=0.55, gain_bass=0.55,
        delay_arp=True, chorus_pad=True, chorus_lead=True,
        lead_density=0.45, arp_density=0.60, accent_density=0.42, bass_syncopation=0.55,
        target_db=-1.5, intro_s=70,
    ),

    # ── DRUM AND BASS ─────────────────────────────────────────────────────
    "liquid_dnb": GenreConfig(
        name="Liquid DnB", bpm=174, key="Am", dur=480,
        progression="neo_soul", scale_mode="melodic_minor", swing=0.08,
        melodic_style="flowing",
        inst_pad="synth_pad_warm", inst_lead="electric_piano",
        inst_arp="vibraphone", inst_bass="electric_bass_finger",
        inst_accent="celesta", inst_counter="harp",
        pad_bars=4,
        drum_pattern="dnb_halftime",
        gain_drums=0.65, gain_pad=0.48, gain_lead=0.55, gain_arp=0.50,
        gain_bass=0.62, gain_counter=0.42,
        fx_pad=(0.78, 0.30, 0.50), fx_lead=(0.72, 0.38, 0.42),
        delay_arp=True, chorus_pad=True,
        lead_density=0.55, arp_density=0.55, bass_syncopation=0.6,
        target_db=-1.5, intro_s=64,
    ),

    # ── AFRO HOUSE ────────────────────────────────────────────────────────
    "afro_house": GenreConfig(
        name="Afro House", bpm=122, key="Gm", dur=540,
        progression="deep_house", scale_mode="dorian", swing=0.18,
        melodic_style="syncopated",
        inst_pad="synth_pad_warm", inst_lead="shakuhachi",
        inst_arp="kalimba", inst_bass="electric_bass_finger",
        inst_accent="steel_drums", inst_counter="marimba",
        pad_bars=4,
        drum_pattern="afro",
        gain_drums=0.65, gain_pad=0.45, gain_lead=0.50, gain_arp=0.58,
        gain_bass=0.60, gain_counter=0.48, gain_accent=0.48,
        fx_arp=(0.60, 0.28, 0.52),
        delay_arp=True, chorus_pad=True,
        lead_density=0.40, arp_density=0.65, accent_density=0.5, bass_syncopation=0.65,
        target_db=-1.5, intro_s=56,
    ),

    # ── MINIMAL TECHNO ────────────────────────────────────────────────────
    "berlin_minimal": GenreConfig(
        name="Berlin Minimal", bpm=128, key="Dm", dur=600,
        progression="industrial", scale_mode="phrygian", swing=0.0,
        melodic_style="staccato",
        inst_pad="synth_pad_warm", inst_lead="synth_lead_square",
        inst_arp="music_box", inst_bass="synth_bass_1", inst_accent="tubular_bells",
        pad_bars=4,
        drum_pattern="minimal",
        gain_drums=0.72, gain_pad=0.40, gain_lead=0.48, gain_arp=0.42, gain_bass=0.65,
        fx_pad=(0.88, 0.40, 0.38), fx_drums=(0.08, 0.05, 0.80),
        delay_arp=True,
        lead_density=0.30, arp_density=0.50, bass_syncopation=0.15,
        target_db=-1.0, intro_s=96,
    ),

    # ── AMBIENT ───────────────────────────────────────────────────────────
    "ambient_meditation": GenreConfig(
        name="Ambient Meditation", bpm=72, key="Am", dur=1800,
        progression="ambient", scale_mode="minor", swing=0.0,
        melodic_style="legato",
        inst_pad="slow_strings", inst_lead="pan_flute",
        inst_arp="harp", inst_bass="acoustic_bass", inst_accent="celesta",
        drum_pattern="none",
        gain_drums=0.0, gain_pad=0.55, gain_lead=0.45, gain_arp=0.48, gain_bass=0.38,
        fx_pad=(0.92, 0.55, 0.28), fx_lead=(0.90, 0.52, 0.30),
        target_db=-5.5, intro_s=120,
        lead_density=0.22, arp_density=0.28, bass_syncopation=0.2,
    ),
    "cosmic_massage": GenreConfig(
        name="Cosmic Massage", bpm=75, key="Fm", dur=420,
        progression="deep_lounge", scale_mode="minor", swing=0.10,
        melodic_style="legato",
        inst_pad="string_ensemble", inst_lead="flute",
        inst_arp="electric_piano", inst_bass="fretless_bass", inst_accent="vibraphone",
        drum_pattern="halftime",
        gain_drums=0.38, gain_pad=0.55, gain_lead=0.50,
        gain_arp=0.50, gain_bass=0.48, gain_accent=0.42,
        fx_pad=(0.85, 0.38, 0.45),
        chorus_pad=True,
        lead_density=0.32, arp_density=0.40, bass_syncopation=0.35,
        target_db=-3.5, intro_s=50,
    ),

    # ── COSMIC DOWNTEMPO ────────────────────────────────────────────────
    "cosmic_downtempo": GenreConfig(
        name="Cosmic Downtempo", bpm=84, key="Dm", dur=300,
        progression="ambient", scale_mode="phrygian", swing=0.12,
        melodic_style="legato",
        inst_pad="synth_pad_halo", inst_lead="pan_flute",
        inst_arp="celesta", inst_bass="fretless_bass", inst_accent="tubular_bells",
        inst_counter="synth_pad_choir",
        pad_bars=8,
        drum_pattern="halftime",
        gain_drums=0.42, gain_pad=0.62, gain_lead=0.58,
        gain_arp=0.48, gain_bass=0.70, gain_accent=0.38, gain_counter=0.45,
        fx_pad=(0.88, 0.38, 0.35), fx_lead=(0.85, 0.35, 0.38),
        fx_arp=(0.80, 0.30, 0.42), fx_bass=(0.35, 0.10, 0.68),
        fx_drums=(0.30, 0.10, 0.65), fx_accent=(0.85, 0.38, 0.38),
        fx_counter=(0.90, 0.42, 0.32),
        delay_arp=True, chorus_pad=True, chorus_lead=True,
        lead_density=0.40, arp_density=0.45, accent_density=0.22,
        bass_syncopation=0.3, lead_register="high",
        target_db=-1.5, intro_s=45,
    ),

    # ── NEW AGE TECHNO (synth voices P84) ───────────────────────────────────
    "new_age_techno": GenreConfig(
        name="New Age Techno", bpm=125, key="Am", dur=360,
        progression="dark_techno", scale_mode="dorian", swing=0.0,
        melodic_style="staccato",
        inst_pad="synth:pad?spread=1&detune=18", inst_lead="synth:supersaw",
        inst_arp="synth:pluck", inst_bass="synth:acid?drive=0.5&detune=20",
        inst_accent="tubular_bells", inst_counter="electric_piano",
        pad_bars=4,
        drum_pattern="four_on_floor",
        gain_drums=0.72, gain_pad=0.52, gain_lead=0.60,
        gain_arp=0.45, gain_bass=0.75, gain_accent=0.35, gain_counter=0.38,
        fx_pad=(0.88, 0.38, 0.40), fx_lead=(0.72, 0.28, 0.55),
        fx_arp=(0.80, 0.30, 0.50), fx_bass=(0.22, 0.06, 0.78),
        fx_drums=(0.15, 0.06, 0.82),
        fx_accent=(0.85, 0.35, 0.40), fx_counter=(0.80, 0.32, 0.45),
        delay_arp=True, chorus_pad=True, chorus_lead=False,
        lead_density=0.45, arp_density=0.65, accent_density=0.18,
        bass_syncopation=0.25, lead_register="high",
        target_db=-1.0, intro_s=48,
        duck_db=-4.5, arrange=True,
    ),

    # ── DEEP JANGLE ──────────────────────────────────────────────────────────
    # Dark melodic techno с jangly arpeggios — Moderat / Stephan Bodzin style.
    # Глубокий кислотный бас, звенящий арп на высоком регистре, плотный грув.
    "deep_jangle": GenreConfig(
        # Jangle = звонкий металлический arp в высоком регистре (вибрафон),
        # лёгкий бас, swing, много реверба на arpе — не acid/dark.
        name="Deep Jangle", bpm=118, key="Am", dur=360,
        progression="indie", scale_mode="minor", swing=0.12,
        melodic_style="staccato",
        inst_pad="synth:pad?spread=1&detune=18",
        inst_lead="synth:square",       # яркий тонкий лид
        inst_arp="vibraphone",           # GM вибрафон = THE jangle звук, звенит
        inst_bass="synth:acid?drive=0.2&detune=8",  # лёгкий бас, не агрессивный
        inst_accent="celesta",           # звонкие акценты
        inst_counter="electric_piano",   # тёплый Rhodes для глубины
        pad_bars=8,
        drum_pattern="four_on_floor",
        gain_drums=0.62, gain_pad=0.38, gain_lead=0.48,
        gain_arp=0.78, gain_bass=0.58, gain_accent=0.32, gain_counter=0.28,
        fx_pad=(0.88, 0.38, 0.35), fx_lead=(0.75, 0.28, 0.50),
        fx_arp=(0.92, 0.45, 0.42),   # много реверба — вибрафон пусть звенит
        fx_bass=(0.15, 0.05, 0.85),
        fx_drums=(0.15, 0.06, 0.82),
        fx_accent=(0.90, 0.40, 0.38), fx_counter=(0.82, 0.35, 0.48),
        delay_arp=True, chorus_pad=True, chorus_lead=False,
        lead_density=0.38, arp_density=0.82, accent_density=0.20,
        bass_syncopation=0.18, lead_register="high",
        target_db=-1.0, intro_s=48,
        duck_db=-3.0, arrange=True,
    ),

    # ── NU-DISCO / ELECTROPOP ─────────────────────────────────────────────────
    # Warm punchy Nu-Disco: 909 kick, disco syncopated bass, Rhodes, modular arp.
    # Am7-Dm7-G7-Cmaj7 (neo_soul = i7-iv7-VII7-III7). No vocals, no foley.
    "nu_disco": GenreConfig(
        name="Nu-Disco", bpm=122, key="Am", dur=270,
        progression="neo_soul", scale_mode="minor", swing=0.08,
        melodic_style="flowing",
        inst_pad="synth:pad?spread=1&detune=15",    # lush 80s analog pad
        inst_lead="synth:supersaw",                  # brassy synth hooks
        inst_arp="synth:square",                     # bright modular synth arp
        inst_bass="synth:acid?drive=0.25&detune=10", # warm disco bass, not harsh
        inst_accent="electric_piano",                # Rhodes accents
        inst_counter="synth:pluck",                  # counter melody
        pad_bars=4,
        drum_pattern="four_on_floor",
        gain_drums=0.72, gain_pad=0.45, gain_lead=0.55,
        gain_arp=0.52, gain_bass=0.75, gain_accent=0.40, gain_counter=0.28,
        fx_pad=(0.85, 0.35, 0.40), fx_lead=(0.70, 0.30, 0.55),
        fx_arp=(0.80, 0.35, 0.48), fx_bass=(0.18, 0.05, 0.82),
        fx_drums=(0.15, 0.06, 0.80),
        fx_accent=(0.82, 0.32, 0.45), fx_counter=(0.78, 0.30, 0.50),
        delay_arp=True, chorus_pad=True, chorus_lead=False,
        lead_density=0.42, arp_density=0.75, accent_density=0.18,
        bass_syncopation=0.35, lead_register="mid",
        target_db=-1.0, intro_s=45,
        duck_db=-4.0, arrange=True,
    ),
}


# ── smooth envelope ────────────────────────────────────────────────────────

def rcos_env(on, peak, off, out, total):
    env = np.zeros(total, dtype=np.float32)
    i0, i1, i2, i3 = (max(0, min(int(x * SR), total)) for x in (on, peak, off, out))
    if i1 > i0:
        n = i1 - i0
        env[i0:i1] = (0.5 - 0.5 * np.cos(np.pi * np.arange(n) / n)).astype(np.float32)
    env[i1:i2] = 1.0
    if i3 > i2:
        n = i3 - i2
        env[i2:i3] = (0.5 + 0.5 * np.cos(np.pi * np.arange(n) / n)).astype(np.float32)
    return env

def apply_env(buf, env):
    n = min(len(buf), len(env))
    out = buf[:n].copy()
    out[:, 0] *= env[:n]
    out[:, 1] *= env[:n]
    return out


# ── composition engine ──────────────────────────────────────────────────────

def _bar(bpm): return 4 * 60.0 / bpm
def _beat(bpm): return 60.0 / bpm

def _jitter(rng, ms: float) -> float:
    """Random timing offset in seconds (±ms milliseconds).
    Makes notes fall slightly off the mathematical grid, like a real musician.
    """
    return rng.uniform(-ms, ms) / 1000.0

def _swung(bar_start, step_16, bar, swing):
    step_dur = bar / 16
    t = bar_start + step_16 * step_dur
    if step_16 % 2 == 1:
        t += step_dur * swing
    return t


# ── Rhythm templates by melodic style ─────────────────────────────────────
# Each template is a list of note durations in BEATS.
# Sum = total phrase duration in beats (typically 4 or 8).

_RHYTHM_TEMPLATES = {
    # Liquid DnB, trance: flowing 16th-note runs
    "flowing": [
        [0.25, 0.25, 0.25, 0.25, 0.5, 0.5, 1.0, 0.5, 0.5],
        [0.5, 0.25, 0.25, 0.5, 0.25, 0.25, 0.5, 0.5, 1.0],
        [0.25, 0.25, 0.5, 0.25, 0.25, 0.5, 0.5, 1.0, 0.5],
        [0.5, 0.5, 0.25, 0.25, 0.25, 0.25, 0.5, 1.0, 0.5],
    ],
    # Techno, minimal: punchy quarter/eighth patterns
    "staccato": [
        [1.0, 0.5, 0.5, 1.0, 1.0],
        [0.5, 0.5, 1.0, 1.0, 0.5, 0.5],
        [1.5, 0.5, 0.5, 0.5, 1.0],
        [0.75, 0.25, 1.0, 0.5, 0.5, 1.0],
        [1.0, 1.0, 0.5, 0.5, 0.5, 0.5],
    ],
    # Ambient, spa: long held notes with slow motion
    "legato": [
        [2.0, 2.0, 2.0, 2.0],
        [3.0, 1.0, 2.0, 2.0],
        [2.0, 1.0, 1.0, 2.0, 2.0],
        [4.0, 2.0, 1.0, 1.0],
        [1.5, 1.5, 1.0, 2.0, 2.0],
    ],
    # Afro house, tribal: syncopated off-beat patterns
    "syncopated": [
        [0.75, 0.25, 0.5, 0.5, 0.5, 0.5, 1.0],
        [0.5, 0.25, 0.25, 0.75, 0.25, 0.5, 0.5, 1.0],
        [1.0, 0.25, 0.25, 0.25, 0.25, 1.0, 1.0],
        [0.5, 0.5, 0.75, 0.25, 0.5, 0.5, 1.0],
    ],
    # Generic
    "default": [
        [1.0, 0.5, 0.5, 1.0, 1.0],
        [0.5, 0.5, 1.0, 0.5, 0.5, 1.0],
        [1.5, 0.5, 0.5, 0.5, 1.0],
        [0.75, 0.25, 0.5, 0.5, 1.0, 1.0],
        [1.0, 0.5, 0.5, 0.5, 0.5, 1.0],
    ],
}

# ── Melodic shapes (relative scale-degree steps from start note) ──────────
# Each shape defines a contour: 0 = start note, positive = higher scale degrees.
# These are TEMPLATES -- actual pitches snap to the note pool.
_MELODIC_SHAPES = [
    [0, 2, 4, 5, 4, 2, 1, 0],     # arch: rise to peak, fall back to root
    [0, 1, 2, 4, 5, 7, 5, 3],     # stepwise rise then fall
    [5, 4, 3, 2, 1, 0, 1, 0],     # descent to root
    [0, 2, 1, 3, 2, 4, 2, 0],     # zigzag ascending
    [0, 4, 3, 2, 5, 3, 1, 0],     # leaping, falls to root
    [0, 0, 2, 4, 2, 1, 0, 0],     # neighbor motion around root
    [3, 4, 5, 3, 2, 1, 0, 2],     # start mid, oscillate down
    [0, 3, 2, 4, 1, 3, 0, 2],     # jagged but resolves
]


def _snap_to_pool(target_idx: int, pool: List[int]) -> int:
    """Clip index to pool bounds and return the MIDI note."""
    return pool[int(np.clip(target_idx, 0, len(pool) - 1))]


def build_pad_events(cfg, chords, dur):
    """Chord pad with overlap and chord strum (notes slightly offset).
    pad_bars controls chord hold time: 8 = ambient drone, 4 = techno/house.
    """
    bar = _bar(cfg.bpm)
    chord_bars = cfg.pad_bars
    chord_dur = bar * chord_bars
    overlap = 3.0
    events, t, ci = [], 0.0, 0
    while t < dur - 1:
        chord = chords[ci % len(chords)]
        d = min(chord_dur + overlap, dur - t)
        # Strum: each chord note offset by 8-14ms so chord "strums" instead of slamming
        strum_ms = 0.011  # 11ms between each chord note
        strum_t  = t
        for ni, note in enumerate(chord):
            events.append((strum_t, [note], 58, d))
            strum_t += strum_ms
        ci += 1
        t += chord_dur
    return events


def build_lead_events(cfg, chords, scale, dur, seed=None):
    """
    Motif-based melody with proper musical structure:

    1. Pick ONE rhythmic template (style-aware: flowing/staccato/legato/syncopated)
    2. Pick ONE melodic shape (arch/rise/fall/zigzag/etc)
    3. Build each phrase by mapping shape degrees onto note pool
    4. Transpose phrase root to follow chord changes
    5. Apply variation on repeats (±1 scale degree, velocity arc)
    6. CADENCE: last note of each phrase resolves to chord tone (tonic or 5th)
    7. Variable seed = new melody every render
    """
    if seed is None:
        seed = int(time.time() * 1000) % 2**31
    rng = np.random.RandomState(seed)

    bar  = _bar(cfg.bpm)
    beat = _beat(cfg.bpm)

    # Register
    if cfg.lead_register == "high":
        note_pool = [n for n in scale if 72 <= n <= 96]
    elif cfg.lead_register == "mid":
        note_pool = [n for n in scale if 60 <= n <= 84]
    else:
        note_pool = [n for n in scale if 48 <= n <= 72]
    if not note_pool:
        note_pool = scale[-10:]

    style     = getattr(cfg, "melodic_style", "default")
    templates = _RHYTHM_TEMPLATES.get(style, _RHYTHM_TEMPLATES["default"])

    # Pick ONE rhythm and ONE shape -- they define the track's melodic identity
    rhythm = list(templates[rng.randint(0, len(templates))])
    shape  = list(_MELODIC_SHAPES[rng.randint(0, len(_MELODIC_SHAPES))])

    # Trim/extend shape to match rhythm length
    n = len(rhythm)
    while len(shape) < n:
        shape = shape + shape
    shape = shape[:n]

    # Ensure shape ends at 0 (cadence back to root area)
    shape[-1] = 0

    events       = []
    phrase_count = 0
    t = cfg.intro_s * 0.6

    while t < dur - bar * 4:
        ci        = int(t / (bar * 8)) % len(chords)
        chord     = chords[ci]
        chord_pcs = set(m % 12 for m in chord)

        # Anchor: chord tone in note pool for phrase start
        anchors = [m for m in note_pool if m % 12 in chord_pcs]
        if not anchors:
            anchors = note_pool

        # First phrase: start on tonic. Later phrases: vary (1st, 3rd, 5th of chord)
        if phrase_count == 0:
            start_note = anchors[0]
        else:
            anchor_choice = int(rng.choice([0, min(1, len(anchors)-1),
                                             min(2, len(anchors)-1)]))
            start_note = anchors[anchor_choice]

        try:
            start_idx = note_pool.index(start_note)
        except ValueError:
            start_idx = len(note_pool) // 2

        # Pitch variation on repeats: shift entire phrase ±1-2 scale degrees
        variation = 0 if phrase_count == 0 else int(rng.randint(-1, 3))

        # Place motif notes
        phrase_start_t = t
        for i, (sh, dur_b) in enumerate(zip(shape, rhythm)):
            if t >= dur - beat:
                break

            is_last = (i == n - 1)

            if is_last:
                # CADENCE: snap to nearest chord tone
                candidates = sorted(anchors, key=lambda m: abs(m - note_pool[
                    min(max(0, start_idx + sh + variation), len(note_pool)-1)]))
                midi = candidates[0]
            else:
                raw_idx = start_idx + sh + variation
                midi    = _snap_to_pool(raw_idx, note_pool)

            # Velocity: downbeat accent, velocity arc over phrase
            beat_pos   = sum(rhythm[:i]) % 4.0
            is_downbeat = beat_pos < 0.12 or abs(beat_pos - 2.0) < 0.12
            # Velocity arc: louder in the middle of the phrase
            arc_factor = float(np.sin(np.pi * i / max(1, n - 1)))
            vel_base   = int(58 + 28 * arc_factor + (15 if is_downbeat else 0))
            vel        = int(np.clip(vel_base + rng.randint(-7, 7), 36, 115))

            # Gate: legato for slow notes, slight staccato for fast
            gate = 0.92 if dur_b >= 1.0 else 0.78
            ndur = dur_b * beat * gate * rng.uniform(0.96, 1.02)

            # Timing humanization: ±12ms (lead player is expressive but loose)
            t_human = max(0.0, t + _jitter(rng, 12.0))
            events.append((t_human, int(midi), vel, ndur))
            t += dur_b * beat

        phrase_count += 1

        # Rest between phrases (controlled by lead_density)
        rest_mult = 1.4 / max(0.25, cfg.lead_density)
        t += bar * rng.uniform(rest_mult * 0.5, rest_mult * 1.2)

        # Occasional longer breath (silence before next phrase)
        if rng.random() < 0.22:
            t += bar * rng.uniform(0.8, 2.0)

    return events


def build_counter_events(cfg, chords, scale, dur, seed=None):
    """
    Counter-melody: harmonizes with lead at 3rd or 6th below.
    Uses the same rhythmic approach but simpler shape, lower register.
    Fills the gaps where the lead rests.
    """
    if not cfg.inst_counter:
        return []
    if seed is None:
        seed = int(time.time() * 1000) % 2**31
    rng = np.random.RandomState(seed)

    bar  = _bar(cfg.bpm)
    beat = _beat(cfg.bpm)

    # Mid register, slightly below lead
    mid_notes = [n for n in scale if 57 <= n <= 79]
    if not mid_notes:
        mid_notes = scale

    style     = getattr(cfg, "melodic_style", "default")
    templates = _RHYTHM_TEMPLATES.get(style, _RHYTHM_TEMPLATES["default"])

    # Counter uses shorter, simpler rhythm (2-4 notes only)
    simple_rhythms = [[1.0, 1.0, 2.0], [0.5, 0.5, 1.0, 2.0],
                      [1.5, 0.5, 2.0], [2.0, 1.0, 1.0]]
    rhythm = list(simple_rhythms[rng.randint(0, len(simple_rhythms))])
    n = len(rhythm)

    # Simple descending shape (answers the lead's phrases)
    shapes = [
        [3, 2, 1, 0],
        [2, 3, 1, 0],
        [4, 2, 1, 0],
        [3, 1, 2, 0],
    ]
    shape = list(shapes[rng.randint(0, len(shapes))])
    while len(shape) < n: shape.extend(shape)
    shape = shape[:n]
    shape[-1] = 0

    events = []
    # Counter enters after lead intro (fills gaps, slightly offset)
    t = cfg.intro_s * 1.2

    while t < dur - bar * 3:
        ci        = int(t / (bar * 8)) % len(chords)
        chord     = chords[ci]
        chord_pcs = set(m % 12 for m in chord)

        anchors = [m for m in mid_notes if m % 12 in chord_pcs] or mid_notes
        start_note = anchors[rng.randint(0, min(2, len(anchors)))]
        try:
            start_idx = mid_notes.index(start_note)
        except ValueError:
            start_idx = len(mid_notes) // 2

        for i, (sh, dur_b) in enumerate(zip(shape, rhythm)):
            if t >= dur - beat:
                break
            is_last = (i == n - 1)
            if is_last:
                candidates = sorted(anchors, key=lambda m: abs(m - start_note))
                midi = candidates[0]
            else:
                midi = _snap_to_pool(start_idx + sh, mid_notes)

            vel = int(np.clip(42 + rng.randint(0, 25), 32, 80))
            ndur = dur_b * beat * rng.uniform(0.85, 0.97)
            t_human = max(0.0, t + _jitter(rng, 10.0))
            events.append((t_human, int(midi), vel, ndur))
            t += dur_b * beat

        # Long rest so counter doesn't crowd the lead
        t += bar * rng.uniform(4, 8)

    return events


def build_arp_events(cfg, chords, scale, dur, seed=None):
    """
    Directional arpeggio patterns (up/down/bounce/strum/thirds).
    """
    if seed is None:
        seed = int(time.time() * 1000) % 2**31
    rng = np.random.RandomState(seed)

    bar  = _bar(cfg.bpm)
    beat = _beat(cfg.bpm)

    mid_notes = [n for n in scale if 55 <= n <= 84]
    if not mid_notes:
        mid_notes = scale

    PATTERNS = {
        "up":     [0, 1, 2, 3],
        "down":   [3, 2, 1, 0],
        "bounce": [0, 2, 1, 3, 1, 2],
        "strum":  [0, 3, 2, 4, 1, 3],
        "thirds": [0, 2, 1, 3, 2, 4],
    }
    pattern_names = list(PATTERNS.keys())

    events = []
    t = 15.0

    while t < dur - bar:
        ci = int(t / (bar * 8)) % len(chords)
        chord = chords[ci]

        chord_tones = list(chord) + [n + 12 for n in chord if n + 12 <= 96]
        chord_tones = sorted(set(chord_tones))

        pat_name = rng.choice(pattern_names)
        pattern  = PATTERNS[pat_name]

        phrase_bars = rng.choice([1, 2, 2, 4])
        phrase_end  = t + bar * phrase_bars

        step_dur = beat * rng.choice([0.25, 0.25, 0.5, 0.5, 0.5, 0.75])

        while t < phrase_end and t < dur - 0.5:
            for idx in pattern:
                if t >= phrase_end or t >= dur - 0.5:
                    break
                ct_idx = idx % len(chord_tones)
                midi   = int(chord_tones[ct_idx])

                beat_pos = (t % bar) / beat
                is_beat1 = abs(beat_pos % 4) < 0.15
                vel = int(np.clip(
                    (85 if is_beat1 else 60) + rng.randint(-10, 10),
                    35, 115
                ))
                ndur = step_dur * rng.uniform(0.7, 1.1)
                # Arp jitter: ±5ms (tighter than lead, arp players are more mechanical)
                t_human = max(0.0, t + _jitter(rng, 5.0))
                events.append((t_human, midi, vel, ndur))
                t += step_dur

        t += bar * rng.uniform(0.5, 2.0 / max(0.2, cfg.arp_density))

    return events


def build_accent_events(cfg, chords, scale, dur, seed=None):
    """Short accent hits -- bells, kalimba, etc."""
    if seed is None:
        seed = int(time.time() * 1000) % 2**31
    rng = np.random.RandomState(seed)

    bar   = _bar(cfg.bpm)
    beat  = _beat(cfg.bpm)
    notes = [n for n in scale if 55 <= n <= 84]
    events = []
    t = cfg.intro_s * 1.5

    while t < dur - bar * 2:
        n_hits = rng.randint(1, max(2, int(4 * cfg.accent_density)))
        for _ in range(n_hits):
            midi = int(rng.choice(notes))
            vel  = rng.randint(50, 90)
            ndur = rng.uniform(0.3, 2.0)
            events.append((t, midi, vel, ndur))
            t += beat * rng.uniform(0.5, 1.5)
            if t >= dur - bar:
                break
        t += bar * rng.uniform(2.0, 5.0 / max(0.2, cfg.accent_density))

    return events


def build_bass_events(cfg, chords, scale, dur, seed=None):
    """
    Groovy bass with syncopation control.
    bass_syncopation=0: straight root hits
    bass_syncopation=1: funky off-beat patterns
    """
    if seed is None:
        seed = int(time.time() * 1000) % 2**31
    rng = np.random.RandomState(seed)

    bar  = _bar(cfg.bpm)
    beat = _beat(cfg.bpm)
    events = []
    t = 20.0

    while t < dur - bar:
        ci    = int(t / (bar * 8)) % len(chords)
        root  = chords[ci][0] - 12
        fifth = root + 7
        octv  = root + 12

        vel  = rng.randint(78, 108)
        ndur = beat * rng.uniform(0.65, 0.85)
        # Bass jitter: ±8ms (bass player "lays back" or "pushes" the beat)
        t_human = max(0.0, t + _jitter(rng, 8.0))
        events.append((t_human, root, vel, ndur))

        n_fills    = int(rng.uniform(0, 4 * cfg.bass_syncopation))
        fill_times = sorted(rng.uniform(beat * 0.8, bar * 0.9, n_fills))

        for ft in fill_times:
            note_t = t + ft
            if note_t >= t + bar - beat * 0.1:
                continue
            note  = int(rng.choice([root, fifth, octv, root - 12]))
            vel2  = rng.randint(62, 92)
            ndur2 = beat * rng.uniform(0.3, 0.7)
            events.append((note_t, note, vel2, ndur2))

        if cfg.bass_syncopation > 0.5 and rng.random() < cfg.bass_syncopation:
            ci_next    = (ci + 1) % len(chords)
            next_root  = chords[ci_next][0] - 12
            anticipate = t + bar - (bar / 16)
            events.append((anticipate, next_root, rng.randint(50, 75), beat * 0.35))

        t += bar

    return events


def build_drum_events(cfg, dur, seed=None):
    """Drum patterns with velocity automation and section-aware dynamics."""
    if seed is None:
        seed = int(time.time() * 1000) % 2**31
    rng = np.random.RandomState(seed)

    bar  = _bar(cfg.bpm)
    hits = []
    if cfg.drum_pattern == "none":
        return hits

    intro = cfg.intro_s
    outro = cfg.outro_s if cfg.outro_s > 0 else dur - 60
    t = 0.0

    while t < dur - 0.5:
        if t < intro * 0.5:
            v = 0.25 + 0.30 * (t / (intro * 0.5))
        elif t < intro:
            v = 0.55 + 0.35 * ((t - intro * 0.5) / (intro * 0.5))
        elif t < outro:
            v = 0.95
        else:
            v = max(0.20, 0.95 - 0.70 * ((t - outro) / max(1, dur - outro)))

        sw = cfg.swing

        if cfg.drum_pattern == "four_on_floor":
            _four_on_floor(hits, t, bar, v, rng, sw)
        elif cfg.drum_pattern == "breakbeat":
            _breakbeat(hits, t, bar, v, rng, sw)
        elif cfg.drum_pattern == "halftime":
            _halftime(hits, t, bar, v, rng, sw)
        elif cfg.drum_pattern == "dnb_halftime":
            _dnb_halftime(hits, t, bar, v, rng, sw)
        elif cfg.drum_pattern == "afro":
            _afro(hits, t, bar, v, rng, sw)
        elif cfg.drum_pattern == "minimal":
            _minimal(hits, t, bar, v, rng, sw)

        t += bar * 2

    return hits


def _swt(bs, step, bar, sw):
    s = bar / 16
    t = bs + step * s
    if step % 2 == 1:
        t += s * sw
    return t

def _humanize_drums(hits: list, rng) -> list:
    """Post-process drum hit list with per-instrument timing jitter.
    Kick is tightest (real drummers lock kick to click), hats are loosest.
      kick/tom: ±2ms
      snare/clap: ±4ms
      hats/ride/crash: ±7ms
    """
    JITTER_MS = {
        "kick": 2.0, "tom_mid": 3.0, "tom_low": 3.0,
        "snare": 4.0, "clap": 4.0,
        "closed_hat": 7.0, "open_hat": 7.0,
        "ride": 6.0, "crash": 5.0,
    }
    result = []
    for t, drum, vel in hits:
        ms = JITTER_MS.get(drum, 5.0)
        t_h = max(0.0, t + rng.uniform(-ms, ms) / 1000.0)
        result.append((t_h, drum, vel))
    return result

def _four_on_floor(hits, t, bar, v, rng, sw):
    for b in range(2):
        bs = t + b * bar
        for bi in range(4):
            hits.append((_swt(bs, bi*4, bar, sw), "kick", int(np.clip(v*rng.randint(100,120),30,127))))
        for ss in [4, 12]:
            hits.append((_swt(bs, ss, bar, sw), "snare", int(np.clip(v*rng.randint(80,105),25,127))))
        for hs in range(0, 16, 2):
            d = "open_hat" if hs in [6,14] and b==1 else "closed_hat"
            hits.append((_swt(bs, hs, bar, sw), d, int(np.clip(v*rng.randint(50,85),20,120))))

def _breakbeat(hits, t, bar, v, rng, sw):
    for b in range(2):
        bs = t + b * bar
        kicks = [0, 8] if b == 0 else [0, 3, 10, 14]
        for ks in kicks:
            hits.append((_swt(bs, ks, bar, sw), "kick", int(np.clip(v*rng.randint(95,120),30,127))))
        for ss in [4, 10]:
            hits.append((_swt(bs, ss, bar, sw), "snare", int(np.clip(v*rng.randint(75,100),25,127))))
        for hs in range(0, 16, 2):
            d = "open_hat" if hs in [6,14] and b==1 else "closed_hat"
            hits.append((_swt(bs, hs, bar, sw), d, int(np.clip(v*rng.randint(55,85),20,120))))

def _halftime(hits, t, bar, v, rng, sw):
    for b in range(2):
        bs = t + b * bar
        hits.append((_swt(bs, 0, bar, sw), "kick", int(np.clip(v*rng.randint(90,115),30,127))))
        hits.append((_swt(bs, 8, bar, sw), "snare", int(np.clip(v*rng.randint(75,100),25,127))))
        for hs in range(0, 16, 4):
            hits.append((_swt(bs, hs, bar, sw), "closed_hat", int(np.clip(v*rng.randint(50,80),20,110))))

def _dnb_halftime(hits, t, bar, v, rng, sw):
    for b in range(2):
        bs = t + b * bar
        hits.append((_swt(bs, 0, bar, sw), "kick", int(np.clip(v*rng.randint(100,125),30,127))))
        if rng.random() < 0.5:
            hits.append((_swt(bs, rng.choice([9, 11]), bar, sw), "kick",
                         int(np.clip(v*rng.randint(80,105),30,127))))
        for ss in [4, 12]:
            hits.append((_swt(bs, ss, bar, sw), "snare", int(np.clip(v*rng.randint(90,115),30,127))))
        for ghost_s in [2, 6, 10, 14]:
            if rng.random() < 0.35:
                hits.append((_swt(bs, ghost_s, bar, sw), "snare",
                             int(np.clip(v*rng.randint(30,55),15,80))))
        for hs in range(16):
            d   = "open_hat" if hs % 4 == 2 else "closed_hat"
            vel = int(np.clip(v * (rng.randint(60,90) if hs%2==0 else rng.randint(35,60)), 20, 115))
            hits.append((_swt(bs, hs, bar, sw), d, vel))

def _afro(hits, t, bar, v, rng, sw):
    for b in range(2):
        bs = t + b * bar
        for ks in [0, 8]:
            hits.append((_swt(bs, ks, bar, sw), "kick", int(np.clip(v*rng.randint(95,118),30,127))))
        for ss in [4, 12]:
            hits.append((_swt(bs, ss, bar, sw), "clap", int(np.clip(v*rng.randint(75,100),25,127))))
        hat_vel = [1.0,0.5,0.8,0.4,0.9,0.45,0.75,0.4,0.95,0.5,0.8,0.4,0.85,0.45,0.7,0.4]
        for hs, hv in enumerate(hat_vel):
            d = "open_hat" if hs in [3,7,11,15] else "closed_hat"
            hits.append((_swt(bs, hs, bar, sw), d, int(np.clip(v*hv*rng.randint(65,95),20,120))))

def _minimal(hits, t, bar, v, rng, sw):
    for b in range(2):
        bs = t + b * bar
        hits.append((_swt(bs, 0, bar, sw), "kick", int(np.clip(v*rng.randint(100,122),30,127))))
        if rng.random() < 0.5:
            hits.append((_swt(bs, rng.choice([8, 10]), bar, sw), "kick",
                         int(np.clip(v*rng.randint(75,100),30,120))))
        if b == 1:
            hits.append((_swt(bs, 4, bar, sw), "snare", int(np.clip(v*rng.randint(70,95),25,115))))
        for hs in [0, 4, 8, 12]:
            if rng.random() < 0.6:
                hits.append((_swt(bs, hs, bar, sw), "closed_hat",
                             int(np.clip(v*rng.randint(45,75),20,100))))


# ── render pipeline ────────────────────────────────────────────────────────

def render(cfg: GenreConfig) -> str:
    t0 = time.time()
    dur   = cfg.dur
    total = int(dur * SR)

    root, mode = parse_key(cfg.key)
    scale      = build_scale(root, cfg.scale_mode)

    print(f"\nrender_track.py -- {cfg.name}")
    print(f"  {dur // 60:.0f}:{dur % 60:02.0f} / {cfg.bpm} BPM / {cfg.key} / {cfg.melodic_style}")

    try:
        chords = voice_lead_sequence(resolve_progression(root, cfg.progression))
    except Exception:
        chords = voice_lead_sequence(resolve_progression(root, "lounge"))

    if cfg.outro_s <= 0:
        cfg.outro_s = dur - 65

    # Single time-based seed → all generators produce new material each render
    # P86: КАЖДЫЙ РЕНДЕР — НОВЫЙ ТРЕК (требование: никакого наследования/шаблонов).
    # Явный cfg.seed = режим «дорабатываем уже созданный» (точное воспроизведение).
    from autodj.generate.motif import track_identity
    _ident = track_identity(getattr(cfg, "seed", None) or None)
    render_seed = _ident["seed"] % 2**31
    print(f"  seed={render_seed}  отпечаток={_ident['fingerprint']}  "
          f"мотив={len(_ident['motif'])} нот, регистр лида {_ident['lead_octave']:+d}, "
          f"плотность {_ident['lead_density']}")

    # 1. Compose
    print("  composing...")
    pad_ev     = build_pad_events(cfg, chords, dur)
    # P86: мелодия = ТЕМА с развитием по секциям (было: случайные ноты из гаммы).
    if getattr(cfg, "melody_engine", "motif") == "motif":
        import random as _rnd
        from autodj.generate.motif import melody_for_sections
        from autodj.generate.arrangement import default_plan as _dp
        _bs2 = 60.0 / cfg.bpm * 4
        _root = chords[0][0] if chords else 57
        lead_ev = melody_for_sections(_dp(max(1, int(dur / _bs2))), chords, scale,
                                      _root, cfg.bpm, _ident, _rnd.Random(render_seed))
        print(f"    мелодия: тема {len(_ident['motif'])} нот → {len(lead_ev)} событий "
              f"(инверсия/секвенция/аугментация по секциям)")
    else:
        lead_ev = build_lead_events(cfg, chords, scale, dur, seed=render_seed)
    counter_ev = build_counter_events(cfg, chords, scale, dur, seed=render_seed + 1)
    arp_ev     = build_arp_events(cfg, chords, scale, dur,   seed=render_seed + 2)
    accent_ev  = build_accent_events(cfg, chords, scale, dur, seed=render_seed + 3)
    bass_ev    = build_bass_events(cfg, chords, scale, dur,   seed=render_seed + 4)
    drum_ev    = build_drum_events(cfg, dur,                  seed=render_seed + 5)

    # Apply drum timing humanization (post-process with same seed for reproducibility)
    _drum_rng  = np.random.RandomState(render_seed + 6)
    drum_ev    = _humanize_drums(drum_ev, _drum_rng)

    print(f"  events: pad={len(pad_ev)} lead={len(lead_ev)} counter={len(counter_ev)} "
          f"arp={len(arp_ev)} accent={len(accent_ev)} bass={len(bass_ev)} drums={len(drum_ev)}")

    # 2. FluidSynth
    print("  rendering (FluidSynth)...")

    def rn(inst, evs, ch=0):
        t1  = time.time()
        if not evs:
            return np.zeros((total, 2), np.float32)
        # G4a (P84): "synth:supersaw" / "synth:acid?drive=0.5" → СОБСТВЕННЫЙ синт
        # (движущийся фильтр, расстройка, драйв). Иначе — GM-патч FluidSynth.
        from autodj.generate.synthvoice import parse_instrument, render_notes_synth
        voice, prm = parse_instrument(inst)
        if voice:
            buf = render_notes_synth(voice, evs, dur, SR,
                                     detune=prm.get("detune", 14.0),
                                     drive=prm.get("drive", 0.25),
                                     cutoff_base=prm.get("cutoff", 900.0))
        else:
            buf = render_notes(inst, evs, dur, SR, channel=ch)
        print(f"    {inst}: {time.time()-t1:.1f}s ({len(evs)} notes)")
        return buf

    # P85: пад тоже может идти своим синтом (разнос голосов + дышащий фильтр).
    # GM-пад тесным трезвучием в среднем регистре = звук «баяна/гармошки».
    from autodj.generate.synthvoice import parse_instrument as _pi, render_chords_synth
    _pv, _pp = _pi(cfg.inst_pad)
    pad_buf     = (render_chords_synth(_pv, pad_ev, dur, SR,
                                       detune=_pp.get("detune", 18.0),
                                       drive=_pp.get("drive", 0.12),
                                       cutoff_base=_pp.get("cutoff", 1100.0),
                                       spread=_pp.get("spread", 1.0))
                   if _pv else render_chords(cfg.inst_pad, pad_ev, dur, SR))
    lead_buf    = rn(cfg.inst_lead, lead_ev, ch=0)
    counter_buf = rn(cfg.inst_counter or cfg.inst_accent, counter_ev, ch=3) if counter_ev else np.zeros((total,2), np.float32)
    arp_buf     = rn(cfg.inst_arp, arp_ev, ch=1)
    accent_buf  = rn(cfg.inst_accent, accent_ev, ch=4)
    bass_buf    = rn(cfg.inst_bass, bass_ev, ch=2)

    # Q2 (P82): секционная аранжировка барабанов — секции отличаются СОДЕРЖИМЫМ
    # (не громкостью), на стыках филлы, в дропе ghost-удары. Отключается arrange=False.
    if drum_ev and getattr(cfg, "arrange", True):
        from autodj.generate.arrangement import default_plan, apply_sections
        _bar_sec = 60.0 / cfg.bpm * 4
        _plan = default_plan(max(1, int(dur / _bar_sec)))
        _before = len(drum_ev)
        drum_ev = apply_sections(drum_ev, _bar_sec, _plan, seed=getattr(cfg, "seed", 0) or 0)
        print("    аранжировка: " + " → ".join(f"{k}({b-a}b)" for a, b, k in _plan)
              + f" | ударов {_before}→{len(drum_ev)}")

    t1       = time.time()
    drum_buf = (render_drums(drum_ev, dur, SR, bank=(cfg.drum_bank or None))
                if drum_ev else np.zeros((total, 2), np.float32))
    print(f"    drums: {time.time()-t1:.1f}s")

    # 3. Pedalboard effects
    print("  effects...")

    def fx(buf, r, w, d): return apply_reverb(buf, SR, room_size=r, wet=w, damping=d)

    pad_buf     = fx(pad_buf,     *cfg.fx_pad)
    lead_buf    = fx(lead_buf,    *cfg.fx_lead)
    counter_buf = fx(counter_buf, *cfg.fx_counter)
    arp_buf     = fx(arp_buf,     *cfg.fx_arp)
    accent_buf  = fx(accent_buf,  *cfg.fx_accent)
    bass_buf    = fx(bass_buf,    *cfg.fx_bass)
    drum_buf    = fx(drum_buf,    *cfg.fx_drums)

    if cfg.delay_arp:
        dm      = _beat(cfg.bpm) * 375
        arp_buf = apply_delay(arp_buf, SR, delay_ms=dm, feedback=0.28, wet=0.20)
    if cfg.delay_lead:
        dm       = _beat(cfg.bpm) * 500
        lead_buf = apply_delay(lead_buf, SR, delay_ms=dm, feedback=0.20, wet=0.15)
    if cfg.chorus_pad:
        pad_buf = apply_chorus(pad_buf, SR, rate_hz=0.35, depth=0.25, wet=0.30)
    if cfg.chorus_lead:
        lead_buf = apply_chorus(lead_buf, SR, rate_hz=0.6, depth=0.20, wet=0.25)

    if drum_ev:
        drum_buf = apply_compressor(drum_buf, SR, threshold_db=-10, ratio=3,
                                    attack_ms=3, release_ms=100)

    # 4. Smooth automation
    print("  mixing...")
    intro = cfg.intro_s
    outro = cfg.outro_s

    def trim(b):
        return b[:total] if len(b) >= total else np.pad(b, ((0, total - len(b)), (0,0)))

    pad_env     = rcos_env(0,          25,         outro + 20, dur,       total)
    lead_env    = rcos_env(intro*0.65, intro*1.4,  outro - 5,  outro + 45, total)
    counter_env = rcos_env(intro*1.1,  intro*2.0,  outro - 20, outro + 30, total)
    arp_env     = rcos_env(15,         intro*0.45, outro + 5,  dur - 5,    total)
    accent_env  = rcos_env(intro*1.2,  intro*1.8,  outro - 25, outro + 25, total)
    bass_env    = rcos_env(18,         intro*0.55, outro + 12, outro + 52, total)
    drum_env    = rcos_env(5,          intro*0.35, outro + 15, dur - 3,    total)

    # Q1: слои идут в МИКС-ШИНУ (частотные роли -> гейн по RMS -> сайдчейн), а не
    # складываются вслепую. gain_* из GenreConfig остаются ручной подстройкой поверх.
    from autodj.generate.mixbus import mix_layers
    # Q2 (P83): структура и для МЕЛОДИЧЕСКИХ слоёв — лид молчит в интро, пад ведёт
    # брейкдаун, бас проваливается. Умножается на rcos_env (тот — общий вход/выход).
    if getattr(cfg, "arrange", True):
        from autodj.generate.arrangement import default_plan, section_gain_envelope
        _bs = 60.0 / cfg.bpm * 4
        _pl = default_plan(max(1, int(dur / _bs)))
        _senv = {r: section_gain_envelope(r, _pl, _bs, total, SR)
                 for r in ("pad", "lead", "counter", "arp", "accent", "bass")}
    else:
        _senv = {}

    def _sec(role, env):
        e = _senv.get(role)
        return env if e is None else env * e[:len(env)]

    layers = {
        "pad":     apply_env(trim(pad_buf),     _sec('pad', pad_env))     * cfg.gain_pad,
        "lead":    apply_env(trim(lead_buf),    _sec('lead', lead_env))    * cfg.gain_lead,
        "counter": apply_env(trim(counter_buf), _sec('counter', counter_env)) * cfg.gain_counter,
        "arp":     apply_env(trim(arp_buf),     _sec('arp', arp_env))     * cfg.gain_arp,
        "accent":  apply_env(trim(accent_buf),  _sec('accent', accent_env))  * cfg.gain_accent,
        "bass":    apply_env(trim(bass_buf),    _sec('bass', bass_env))    * cfg.gain_bass,
        "drums":   apply_env(trim(drum_buf),    drum_env)    * cfg.gain_drums,
    }
    mix, _gains = mix_layers(layers, SR, int(_beat(cfg.bpm) * SR),
                             duck_db=getattr(cfg, "duck_db", -4.5))
    print("    mixbus gains: " + ", ".join(f"{k}={v}" for k, v in _gains.items()))

    # 4b. Filter automation (THE signature of electronic music)
    # LPF sweep during intro: track opens dark, gradually reveals full spectrum
    # HPF rise at very end: graceful exit without hard cut
    def _lpf_sweep_stereo(buf, start_hz, end_hz, segments=64):
        """Apply exponential LPF sweep to stereo buffer."""
        from scipy.signal import butter, sosfilt
        n = len(buf)
        out = buf.copy()
        seg_len = max(1, n // segments)
        for i in range(segments):
            t = i / segments
            cutoff = float(start_hz * (end_hz / start_hz) ** t)
            cutoff = max(20.0, min(cutoff, SR / 2 - 100))
            sos = butter(2, cutoff / (SR / 2), btype='low', output='sos')
            s = i * seg_len
            e = s + seg_len if i < segments - 1 else n
            for ch in range(out.shape[1]):
                out[s:e, ch] = sosfilt(sos, buf[s:e, ch]).astype(np.float32)
        return out

    def _hpf_sweep_stereo(buf, start_hz, end_hz, segments=32):
        """Apply exponential HPF sweep to stereo buffer (low-end exit)."""
        from scipy.signal import butter, sosfilt
        n = len(buf)
        out = buf.copy()
        seg_len = max(1, n // segments)
        for i in range(segments):
            t = i / segments
            cutoff = float(start_hz * (end_hz / start_hz) ** t)
            cutoff = max(20.0, min(cutoff, SR / 2 - 100))
            sos = butter(2, cutoff / (SR / 2), btype='high', output='sos')
            s = i * seg_len
            e = s + seg_len if i < segments - 1 else n
            for ch in range(out.shape[1]):
                out[s:e, ch] = sosfilt(sos, buf[s:e, ch]).astype(np.float32)
        return out

    # Apply LPF sweep over the first intro_s * 0.8 seconds
    # (starts muffled, fully opens at 80% of intro = at the drop)
    buildup_end = int(min(intro * 0.80, dur * 0.35) * SR)
    if buildup_end > SR * 8:  # only if buildup > 8s
        mix[:buildup_end] = _lpf_sweep_stereo(
            mix[:buildup_end], start_hz=220, end_hz=16000)

    # HPF sweep on the last 20s (bass fades out gracefully)
    outro_start = int(max(dur - 20, dur * 0.88) * SR)
    if outro_start < total and (total - outro_start) > SR * 5:
        mix[outro_start:] = _hpf_sweep_stereo(
            mix[outro_start:], start_hz=30, end_hz=400)

    # Global fades
    fi = int(10 * SR)
    fo = int(22 * SR)
    mix[:fi]  *= np.linspace(0, 1, fi, dtype=np.float32)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)[:, None]

    # 5. Master
    print("  mastering...")
    mix  = master_chain(mix, SR)
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= (10 ** (cfg.target_db / 20)) / peak

    # 6. Export
    os.makedirs("/opt/autodj-mixer/output", exist_ok=True)
    safe = cfg.name.lower().replace(" ", "_")
    wav  = f"/opt/autodj-mixer/output/{safe}.wav"
    mp3  = f"/opt/autodj-mixer/output/{safe}.mp3"

    import soundfile as sf
    sf.write(wav, mix, SR)
    # P87: паспорт рендера рядом с треком — каким КОДОМ и с какими параметрами сделано.
    # Ловит «работает только у меня»: незакоммиченные модули видны прямо в логе.
    try:
        from autodj.generate.manifest import write_manifest
        write_manifest(wav, cfg, _ident, {"duration_s": round(len(mix) / SR, 1)})
    except Exception as _e:
        print(f"    манифест пропущен: {type(_e).__name__}")
    os.system(f'ffmpeg -y -i "{wav}" -b:a 320k "{mp3}" 2>/dev/null')
    if os.path.exists(wav):
        os.remove(wav)

    elapsed = time.time() - t0
    sz      = os.path.getsize(mp3) / 1024 / 1024
    print(f"  done {elapsed:.1f}s -- {sz:.1f} MB -- {mp3}")
    return mp3


# ── CLI ────────────────────────────────────────────────────────────────────

def _send(mp3_path, cfg):
    import subprocess
    env_file = "/home/cclaw/claudeclaw-build/.env"
    def genv(k):
        try:
            with open(env_file) as f:
                for line in f:
                    if line.startswith(f"{k}="):
                        return line.split("=",1)[1].strip().strip('"').strip("'")
        except Exception: pass
    tok = genv("TELEGRAM_BOT_TOKEN"); cid = genv("ALLOWED_CHAT_ID")
    if not tok or not cid: return
    cap = f"{cfg.name} / {cfg.dur//60}:{cfg.dur%60:02d} / {cfg.bpm} BPM / {cfg.key}"
    subprocess.run(["curl","-s","-X","POST",
        f"https://api.telegram.org/bot{tok}/sendAudio",
        "-F", f"chat_id={cid}", "-F", f"audio=@{mp3_path}",
        "-F", f"caption={cap}", "-F", f"title={cfg.name}", "-F", "performer=AutoDJ"],
        capture_output=True)
    print("  sent to Telegram")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("genre", nargs="?")
    p.add_argument("--list", action="store_true")
    p.add_argument("--bpm", type=int)
    p.add_argument("--key", type=str)
    p.add_argument("--dur", type=int)
    p.add_argument("--send", action="store_true")
    args = p.parse_args()

    if args.list or not args.genre:
        print("Genres:")
        for k, c in GENRES.items():
            print(f"  {k:22s} {c.bpm} BPM / {c.key:4s} / {c.melodic_style:12s} / {c.dur//60}:{c.dur%60:02d}")
        if not args.genre:
            print("\nUsage: python3 render_track.py <genre> [options]")
        return

    gk = args.genre.lower().replace("-","_").replace(" ","_")
    if gk not in GENRES:
        print(f"Unknown: {args.genre}. Available: {', '.join(GENRES.keys())}"); sys.exit(1)

    cfg = GENRES[gk]
    if args.bpm: cfg.bpm = args.bpm
    if args.key: cfg.key = args.key
    if args.dur: cfg.dur = args.dur

    mp3 = render(cfg)
    if args.send: _send(mp3, cfg)


if __name__ == "__main__":
    main()
