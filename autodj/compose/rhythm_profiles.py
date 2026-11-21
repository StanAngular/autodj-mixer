"""P167 (2026-11-21, audit 3; Gemini: «жанровые профили, чтобы не хардкодить клубные акценты в другие стили»): what rhythm means in a style, as DATA.
One place says how much swing, which roles lead or lag, how strong the hat accents are, how long the open hat rings, how dense the percussion gets, whether the
drums breathe out before the peak, what the kick pattern family is, and how much change / accent the rhythm report should EXPECT. arrange.drum_plan (P165)
and rhythm.report (P162) read it; nothing in the engine writes «club hats» for a style that has no hats.

  profile(style, mood=None, **overrides)   a copy of the style's profile; the mood scales the expectations (soft / ambient expect less change), overrides win
  ensemble(trk, style, seed)               microtiming.Ensemble(version=2) with the profile's swing and push (the kick stays on the grid)
  STYLES                                   names (aliases in ALIAS: "tech house" -> house ...)
Values are HYPOTHESES from the audit (generic practice, one track and ~14 references), not measured truth: P168 sets them by ear (A/B, one thing at a time).
All numbers are per task flexible: META["task"] = {"style": "deep", "mood": "soft", "profile": {"swing": .1}}."""
import copy

BASE = dict(
    swing=0.0,                  # metric swing, a fraction of a 16th on the odd steps (0 = straight; .16 = 16 %)
    push_ms={},                 # {role: ms} on-purpose lead (negative) or lag; the kick is never moved
    kick_family="four",         # four | two_step | half | broken | sparse
    hat_accent_db=0.0,          # level of the stronger offbeat hats over the weaker (0 = every hat the same; machine-like)
    ghost_hat_db=None,          # 16th ghost hats this many dB under the main hats (None = none)
    open_hat_s=(0.0, 0.0),      # length of the open hat at low .. high energy (0 = no open hat)
    perc_per_bar=(0, 0),        # percussion hits per bar at low .. high energy
    ghost_backbeat=False,       # soft ghost notes of the clap / snare before the next bar
    backbeat_min_energy=.5,     # the clap / snare appears from this section energy
    dropout_beats=0,            # the kick (and perc) breathe out this many beats before the peak / a home (0 = never); never longer than 4
    kick_spread_db=1.0,         # expected spread of the kick hits (accent shape), dB
    density_range_min=.12,      # report: (max - min) / mean of the drum onsets per bar over the sections
    hat_contrast_min_db=1.5,    # report: contrast of the hat hits
    hat16=False,                # P171: a steady 16th hat line (accents on the offbeat) from energy .6 instead of random ghosts
    shaker=False,               # P171: a shaker layer on 16ths (its own accent shape) from energy .5
    fill_every=0,               # P171: a short machine fill (rim / perc) in the last beat of every N bars (0 = none)
)
STYLES = {
    "house":        dict(swing=.08, push_ms={"bass": -3.0, "perc": -2.0}, kick_family="four", hat_accent_db=3.0, ghost_hat_db=14.0, open_hat_s=(.15, .35), perc_per_bar=(2, 6), backbeat_min_energy=.5, dropout_beats=2, kick_spread_db=1.2, density_range_min=.12, hat_contrast_min_db=2.0),
    "tech_house":   dict(swing=.08, push_ms={"bass": -2.0}, kick_family="four", hat_accent_db=3.0, ghost_hat_db=9.0, open_hat_s=(.06, .16), perc_per_bar=(0, 2), backbeat_min_energy=.4, dropout_beats=2, kick_spread_db=1.0, density_range_min=.12, hat_contrast_min_db=2.0, hat16=True, shaker=True, fill_every=8),
    "deep":         dict(swing=.10, push_ms={"perc": -2.0}, kick_family="four", hat_accent_db=2.0, ghost_hat_db=16.0, open_hat_s=(.1, .3), perc_per_bar=(2, 5), ghost_backbeat=True, backbeat_min_energy=.6, dropout_beats=2, kick_spread_db=1.0, density_range_min=.10, hat_contrast_min_db=1.8),
    "melodic":      dict(swing=.04, push_ms={"bass": -2.0}, kick_family="four", hat_accent_db=2.5, ghost_hat_db=16.0, open_hat_s=(.15, .4), perc_per_bar=(1, 5), backbeat_min_energy=.6, dropout_beats=3, kick_spread_db=1.0, density_range_min=.12, hat_contrast_min_db=1.8),
    "garage":       dict(swing=.16, push_ms={"hats": 2.0}, kick_family="two_step", hat_accent_db=3.5, ghost_hat_db=12.0, open_hat_s=(.1, .25), perc_per_bar=(3, 8), ghost_backbeat=True, backbeat_min_energy=.3, dropout_beats=2, kick_spread_db=1.5, density_range_min=.12, hat_contrast_min_db=2.5),
    "minimal":      dict(swing=.06, push_ms={"perc": -3.0}, kick_family="four", hat_accent_db=1.5, ghost_hat_db=None, open_hat_s=(0.0, .2), perc_per_bar=(3, 9), backbeat_min_energy=.9, dropout_beats=2, kick_spread_db=.8, density_range_min=.10, hat_contrast_min_db=1.2),
    "techno":       dict(swing=.0, push_ms={}, kick_family="four", hat_accent_db=2.0, ghost_hat_db=None, open_hat_s=(.1, .25), perc_per_bar=(2, 8), backbeat_min_energy=.7, dropout_beats=4, kick_spread_db=.8, density_range_min=.12, hat_contrast_min_db=1.5),
    "downtempo":    dict(swing=.14, push_ms={"bass": 3.0, "hats": 2.0}, kick_family="half", hat_accent_db=3.0, ghost_hat_db=10.0, open_hat_s=(.2, .45), perc_per_bar=(1, 4), ghost_backbeat=True, backbeat_min_energy=.2, dropout_beats=2, kick_spread_db=1.5, density_range_min=.10, hat_contrast_min_db=2.2),
    "witch_house":  dict(swing=.0, push_ms={}, kick_family="half", hat_accent_db=1.0, ghost_hat_db=None, open_hat_s=(.3, .6), perc_per_bar=(0, 3), backbeat_min_energy=.3, dropout_beats=4, kick_spread_db=2.0, density_range_min=.10, hat_contrast_min_db=1.0),
    "breaks":       dict(swing=.12, push_ms={"hats": 2.0}, kick_family="broken", hat_accent_db=4.0, ghost_hat_db=10.0, open_hat_s=(.1, .25), perc_per_bar=(3, 8), ghost_backbeat=True, backbeat_min_energy=.2, dropout_beats=2, kick_spread_db=2.5, density_range_min=.12, hat_contrast_min_db=3.0),
    "ambient":      dict(swing=.0, push_ms={}, kick_family="sparse", hat_accent_db=0.0, ghost_hat_db=None, open_hat_s=(0.0, 0.0), perc_per_bar=(0, 2), backbeat_min_energy=1.1, dropout_beats=0, kick_spread_db=0.0, density_range_min=.05, hat_contrast_min_db=0.0),
}
ALIAS = {"tech house": "tech_house", "techhouse": "tech_house", "berlin tech house": "tech_house", "deep house": "deep", "deep_house": "deep", "deep melodic house": "melodic", "melodic house": "melodic", "melodic_house": "melodic",
         "organic": "deep", "uk garage": "garage", "2-step": "garage", "two-step": "garage", "minimal techno": "minimal", "deep techno": "techno", "hard techno": "techno",
         "trip hop": "downtempo", "trip-hop": "downtempo", "lofi": "downtempo", "lo-fi": "downtempo", "witch house": "witch_house", "breakbeat": "breaks", "dnb": "breaks",
         "magical ambient": "ambient", "drone": "ambient"}
MOOD = {"soft": .6, "calm": .6, "ambient": .4, "neutral": 1.0, "club": 1.0, "hard": 1.2, "aggressive": 1.3}
SCALED = ("hat_accent_db", "kick_spread_db", "density_range_min", "hat_contrast_min_db")          # what a mood scales: how much change / accent is expected

def resolve(style):
    s = (style or "").lower().strip(); s = ALIAS.get(s, s)
    if s not in STYLES: raise ValueError(f"unknown rhythm style {style!r}: {sorted(STYLES)} (aliases: {sorted(ALIAS)})")
    return s

def profile(style, mood=None, **overrides):
    """the profile of a style (copy): BASE + the style, the expectations scaled by the mood, the overrides on top"""
    p = copy.deepcopy(BASE); p.update(copy.deepcopy(STYLES[resolve(style)])); k = MOOD.get(mood or "neutral", 1.0)
    for a in SCALED: p[a] = round(p[a] * k, 3)
    bad = set(overrides) - set(BASE)
    if bad: raise ValueError(f"unknown profile keys {sorted(bad)}: {sorted(BASE)}")
    p.update(overrides); p["dropout_beats"] = max(0, min(4, int(p["dropout_beats"]))); p["style"] = resolve(style); return p

def ensemble(trk, style, seed=0, mood=None, **overrides):
    """microtiming.Ensemble(version=2) with the style's swing and push (P163): the kick on the grid, the metric swing exact, the push by profile"""
    from .microtiming import Ensemble
    p = profile(style, mood, **overrides); return Ensemble(trk, seed, version=2, swing=p["swing"], push=p["push_ms"])
