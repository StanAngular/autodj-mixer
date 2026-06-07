#!/usr/bin/env python3
"""House mix config -- 2 tracks, same BPM."""

WAV_DIR = "/opt/autodj-mixer/tracks"
ANN_DIR = "/opt/autodj-mixer/ann"
TARGET_LUFS = -14.0
MAX_SHIFT_SEC = 0.05

TRACKS = [
    ("GardenOfEden",  "Franz Matthews - Garden of Eden (Extended Mix).wav",  "Franz Matthews - Garden of Eden (Extended Mix).txt"),
    ("FeverDreams",   "El Mundo, Tal Groenman - Fever Dreams (Extended Mix).wav", "El Mundo, Tal Groenman - Fever Dreams (Extended Mix).txt"),
]