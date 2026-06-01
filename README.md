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


## Mix Analyzer

`mix_analyzer.py` — comprehensive post-mix quality diagnostics.

```bash
python3 mix_analyzer.py --mix /tmp/mix.mp3 --wav-dir ./wav --ann-dir ./annotations
python3 mix_analyzer.py --mix /tmp/mix.mp3 --config mix_config.py --feedback
```

### 5-phase analysis pipeline

| Phase | What | Details |
|-------|------|---------|
| 1. Source Analysis | Key (Camelot), BPM, source artefacts | Detects pre-existing glitches in originals |
| 2. Transition Analysis | Beat drift, LUFS consistency, centroid shift | Each crossfade zone individually |
| 3. Mix Artefact Scan | Stutter, speed glitch, transients, HF noise, spectral discontinuity | Full-mix sweep |
| 4. Source vs Mixer | Cross-reference | Distinguishes source issues from mixer-induced |
| 5. Feedback | Tuning recommendations | Concrete parameter suggestions |

### Artefact types detected

| Artefact | Detection method | Threshold |
|----------|-----------------|-----------|
| **Stutter** (repeated frame) | Auto-correlation of 50ms windows | corr > 0.999 |
| **Speed glitch** | Local BPM in 4s windows | >15% jump |
| **Transient spike** | Crest factor per 100ms | >5x median |
| **HF noise** (rubberband artifacts) | Energy >16kHz | >8x median |
| **Spectral discontinuity** | Spectral flux (FFT frame diff) | >5x median |
| **Beat drift** | Onset cross-correlation on transition | >5ms flagged |

### Feedback mode

With `--feedback`, the analyzer outputs specific parameter changes:
```
🔴 [warp_to_grid(rate_threshold)] Reduce rate_threshold 0.002→0.001 (12 stutters)
🟡 [ramp_to_native(ramp_sec)] Increase RAMP_SEC 15→20 (7 HF noise events)
🟡 [build_cf_lr4(max_shift_sec)] Increase to 0.073 (drift=5.3ms)
```

## Pipeline

`run_pipeline.py` — mix + analyze in one command.

```bash
# Full pipeline
python3 run_pipeline.py --config mix_config.py

# Analyze only (skip mixing)
python3 run_pipeline.py --config mix_config.py --analyze-only

# With feedback
python3 run_pipeline.py --config mix_config.py --feedback
```

## Scripts

| Script | Purpose |
|--------|---------|
| `smart_mixer.py` | DJ mix engine (bar-by-bar warp, LR4 crossover) |
| `mix_analyzer.py` | Post-mix quality diagnostics |
| `run_pipeline.py` | Mix + analyze in one command |
| `scripts/analyze_order.py` | Optimal track order (BPM, key, energy) |
| `scripts/analyze_zone.py` | Detailed zone inspection (BPM trace, RMS) |
| `scripts/generate_annotations.py` | madmom beat/downbeat annotation |
