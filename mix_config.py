#!/usr/bin/env python3
"""Mix config for optimal Camelot order (#1 from analyze_order.py)."""

# Shared paths -- both cclaw and hermes have write access (group: users)
WAV_DIR = "/opt/autodj-mixer/tracks"
ANN_DIR = "/opt/autodj-mixer/ann"

TRACKS = [
    ("Gamgi",        "Benji, Rina, Shubostar - Gamgi (Original Mix).wav",
                     "Benji, Rina, Shubostar - Gamgi (Original Mix).txt"),
    ("Garden",       "Franz Matthews - Garden of Eden (Extended Mix).wav",
                     "Franz Matthews - Garden of Eden (Extended Mix).txt"),
    ("Lakeside",     "Carina Lawrence - Lakeside Reverie (Extended Mix).wav",
                     "Carina Lawrence - Lakeside Reverie (Extended Mix).txt"),
    ("Eleonora",     "Eleonora,_Flowers_on_Monday_What_If_I_Told_You_Extended_Mix.wav",
                     "Eleonora,_Flowers_on_Monday_What_If_I_Told_You_Extended_Mix.txt"),
    ("Fever",        "El Mundo, Tal Groenman - Fever Dreams (Extended Mix).wav",
                     "El Mundo, Tal Groenman - Fever Dreams (Extended Mix).txt"),
    ("GetOnMyLevel", "Sasha, Franky Wah - Get On My Level (Instrumental).wav",
                     "Sasha, Franky Wah - Get On My Level (Instrumental).txt"),
]
