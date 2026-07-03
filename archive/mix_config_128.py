#!/usr/bin/env python3
"""4-track mix — only 125-130 BPM tracks."""
WAV_DIR = "/opt/autodj-mixer/shared/tracks"
ANN_DIR = "/opt/autodj-mixer/shared/ann"
TARGET_LUFS = -14.0
MAX_SHIFT_SEC = 0.05

TRACKS = [
    ("Closer",            "2zPJXn7awOw.wav",   "2zPJXn7awOw.txt"),
    ("Free Your Mind",    "WZLKDS1sj1c.wav",   "WZLKDS1sj1c.txt"),
    ("Following The Sun", "uZsY4S4ckMU.wav",   "uZsY4S4ckMU.txt"),
    ("Die For You",       "uPD0QOGTmMI.wav",   "uPD0QOGTmMI.txt"),
]