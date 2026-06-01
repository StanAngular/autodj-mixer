# AutoDJ Mixer

AI-powered DJ mix engine. Takes audio tracks, analyzes BPM/structure via madmom, and builds a continuous mix with bar-aligned crossfades, LR4 bass swap, and BPM normalization.

Developed by Hermes (signal processing, LR4 math, optimization) + ClaudeClaw (bar-by-bar warp, BPM ramp, integration).

## How it works

1. **Load** - FLAC/WAV/MP3 input, convert to 44.1kHz stereo WAV
2. **Annotate** - madmom RNN beat/downbeat detection
3. **Analyze** - BPM calculation, structural segmentation (QUIET/BUILD/ACTIVE/DROP)
4. **Trim** - Cut intro silence and outro fade, keep active content
5. **Normalize** - LUFS loudness normalization (-14 LUFS, 30s sample)
6. **Mix** - 16-bar crossfades with LR4 3-band bass swap + bar-by-bar warp
7. **Ramp** - 15s BPM ramp-back to native tempo after each transition
8. **Export** - WAV intermediate, then MP3 at requested bitrate

## Key algorithms

- **Linkwitz-Riley 4th-order 3-band crossover** (150Hz / 3000Hz splits). Mids + highs get equal-power crossfade (cos/sin). Lows get instant bass swap at crossfade center with 1.5-bar smoothing. No "bass mush" from two kicks overlapping.

- **Bar-by-bar warp** via pyrubberband. Each slave bar individually stretched to match master bar length. Eliminates phase drift across 16-bar crossfade zones.

- **Onset micro-alignment** via FFT cross-correlation (scipy fftconvolve). O(N log N). Restricted to +/-50ms window since bars are already pre-aligned.

- **BPM ramp-back** after crossfade. Linear interpolation from master BPM back to native over 15s. Prevents abrupt tempo jump at crossfade exit.

- **Structural segmentation** for cue points. RMS energy + LR4 bass ratio per bar. Classifies bars as QUIET/BUILD/ACTIVE/DROP. Finds optimal exit (quiet_exit) and entry (first_active) points.

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt
# Also need: ffmpeg, rubberband-cli

# 1. Prepare WAV files
mkdir wav annotations
for f in *.flac; do ffmpeg -y -i "$f" -ar 44100 -ac 2 "wav/${f%.flac}.wav"; done

# 2. Generate beat annotations
python3 scripts/generate_annotations.py --wav-dir wav --ann-dir annotations

# 3. Find optimal track order
python3 scripts/analyze_order.py --wav-dir wav --ann-dir annotations

# 4. Mix!
python3 smart_mixer.py --wav-dir wav --ann-dir annotations --output mix.mp3
```

## Analysis tools

```bash
# Analyze mix quality (spikes, RMS jumps, bass muffle, treble dropouts)
python3 scripts/analyze_mix.py mix.mp3

# Investigate a specific time zone
python3 scripts/analyze_zone.py mix.mp3 22:00 23:10
```

## Configuration

Edit constants at top of `smart_mixer.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| SR | 44100 | Sample rate |
| CF_BARS | 16 | Crossfade length in bars |
| RAMP_SEC | 15 | BPM ramp-back duration |
| TARGET_LUFS | -14.0 | Loudness normalization target |
| BPM_DIFF_LIMIT | 0.08 | Max BPM diff ratio for crossfade (8%) |

## System requirements

- Python 3.8+
- ffmpeg
- rubberband-cli (for pyrubberband)
- ~4GB RAM for 6 tracks

## Version history

| Version | Author | Changes |
|---------|--------|---------|
| v5b | ClaudeClaw | HPSS separation, equal-power fades, onset correlation |
| v6 | Hermes | LR4 3-band crossover, bass swap, FFT correlation, fast LUFS |
| v7 | ClaudeClaw+Hermes | Bar-by-bar warp, BPM ramp-back, micro-align +/-50ms |

## License

MIT
