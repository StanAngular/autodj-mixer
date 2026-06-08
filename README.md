# AutoDJ Mixer

AI-powered DJ mix engine. Takes audio tracks, analyzes BPM/structure via madmom, builds a continuous mix with bar-aligned crossfades, LR4 bass swap, BPM normalization, and post-mix quality analysis.

Developed by **Hermes** (signal processing, LR4 math, analyzer) + **ClaudeClaw** (bar-by-bar warp, pipeline, transition reel).

---

## Pipeline

```
Step 0:      Pre-Analyze      → track_analyzer.py (BPM, key, Camelot, sections)
Step 0.5:    Genre Detection   → genre_detector.py (auto-style + bitrate)
Step 0.75:   Preview           → transitions table → user confirms
Step 0.8:    Transitions Reel  → transitions_reel.py (preview clips)
Step 1:      Mix               → smart_mixer.py (bar-by-bar warp + LR4)
Step 2:      Analyze           → mix_analyzer.py (v3 beat grid + v2 detectors)
Step 3:      Upload            → catbox.moe / litterbox (auto)
```

```bash
# Full pipeline
python3 run_pipeline.py --config mix_config.py --feedback

# Preview only (stops for confirmation)
python3 run_pipeline.py --config mix_config.py --preview-only

# Mix + transitions reel + analysis
python3 run_pipeline.py --config mix_config.py --feedback
```

---

## Quick start

```bash
# 1. Download tracks from YouTube (Warp proxy)
python3 yt_download.py "https://youtube.com/watch?v=..."
# → Downloads MP3 → converts to WAV → generates madmom annotations

# 2. Create a config file (mix_config.py):
#    TRACKS = [(name, wav_file, ann_file), ...]
#    WAV_DIR = "tracks"
#    ANN_DIR = "ann"

# 3. Mix!
python3 run_pipeline.py --config mix_config.py --style "Melodic House" --author "Hermes"
```

---

## Key features

### Bar-by-bar warp (pyrubberband)
Each slave bar individually stretched to match master bar length. Eliminates phase drift across 16-bar crossfade zones.

### LR4 3-band crossover (150Hz / 3000Hz)
Mids + highs get equal-power crossfade (cos/sin). Lows get instant bass swap at crossfade center with 1.5-bar smoothing. No "bass mush" from two kicks overlapping.

### Onset micro-alignment (FFT cross-correlation)
±50ms window via scipy fftconvolve. Pre-warp phase alignment on first 2 bars catches large downbeat shifts (up to -99ms).

### Dynamic BPM ramp
| BPM diff | Ramp duration | Effect |
|----------|--------------|--------|
| < 1.0    | skip | No artifacts |
| 1–3      | ×2 (30s) | Imperceptible |
| 3–8      | 15s | Default |
| > 8      | ×0.7 (10.5s) | Fast |

### Structural segmentation (QUIET/BUILD/ACTIVE/DROP)
RMS energy + LR4 bass ratio per bar. `best_exit_bar()` picks quiet section near end. `soft_entry()` picks BUILD section at start.

### Blend→ramp seamless bridge
17th bar of warp saved as `warp_extra`, joined to ramp_result with 20ms crossfade. No endpoint drop, no micro-stutter.

### Bass polarity (5-point weighted consensus)
5 correlation points across crossfade + separate kick band (60-120Hz) check. Prevents phase cancellation.

---

## Mix Analyzer — v3 with v2 detectors

`mix_analyzer.py` — post-mix quality diagnostics.

```bash
# Per-transition beat alignment (madmom)
.venv/bin/python mix_analyzer.py --mix mix.mp3 --config mix_config.py

# Full analysis: beat alignment + artefact detection + recommendations
.venv/bin/python mix_analyzer.py --mix mix.mp3 --config mix_config.py --feedback
```

### Beat grid analysis (v3)
- Uses **pre-computed madmom annotations** (NEVER re-runs madmom on mix)
- Builds beat grid from last 32 beats before CF, extrapolates into CF zone
- Compares expected vs actual onsets → **P-score**, **CMLc**, **Cemgil**
- std 88-110ms (was 400ms in v2), BPM 124-128 (was 496)

### Artefact detection (v2 detectors, restored)
| Detector | Method |
|----------|--------|
| Stutter | diff_ratio < 0.001, 20ms windows, 3+ consecutive → 0 false positives |
| Speed glitch | BPM in 4s windows, 20% threshold, 30s ramp zone |
| Transient spike | Crest factor per 100ms, >5x median |
| HF noise | >16kHz, dual threshold (10x median AND -40dBFS) → 0 false positives |
| Spectral discontinuity | Spectral flux, 12x median (was 5x) |
| Boundary glitch | 1ms RMS envelope at blend→ramp endpoint |
| Band cancellation | 5 bands (20-60 / 60-120 / 120-500 / 500-2000 / 2000-8000Hz) |
| RMS dip | 100ms windows, <40% median, crossfade zones only |
| Onset stability | Onset-envelope correlation within CF |
| Beat irregularity | IOI ratio in onset peaks, >2× local median |

### Zone scanning (NEW)
Only analyzes ±15s around each transition — 90-min mix analysis takes as long as 30-min.

---

## Transitions Reel

`transitions_reel.py` — extract crossfade zones into a short review MP3.

```bash
python3 transitions_reel.py mix.wav --pad-before 15 --pad-after 15 --out reel.mp3
# → 2-3 minute file with all transitions + tone separators
```

Integrated into pipeline — automatically generated after each mix.

---

## AI Transitions (ACE-Step Repaint)

```bash
# Generate AI transition between two tracks
cd ~/ACE-Step-1.5 && uv run python3 /opt/autodj-mixer/repaint_transition.py \
  --track-a track_a.wav --track-b track_b.wav \
  --ann-a ann_a.txt --ann-b ann_b.txt \
  --exit-bar 128 --entry-bar 75 \
  --bpm 122 --style "melodic house" \
  --steps 40 --guidance 7.0 --seed 42 \
  --output /tmp/ai_transitions/tr0_A_to_B.wav

# Use AI transitions in mix
python3 smart_mixer.py --config mix_config.py --transitions-dir /tmp/ai_transitions/
# Hybrid mode: AI if file exists, standard crossfade if not
```

See `/opt/autodj-mixer/SKILL.md` for full documentation.

---

## Key scripts

| Script | Purpose |
|--------|---------|
| `smart_mixer.py` | DJ mix engine (bar-by-bar warp, LR4 crossover) |
| `mix_analyzer.py` | Post-mix quality diagnostics (v3 + v2 detectors) |
| `run_pipeline.py` | Full pipeline: pre-analyze → preview → mix → analyze → reel |
| `track_analyzer.py` | Pre-analysis: BPM, key, Camelot, sections, optimal order |
| `genre_detector.py` | Auto-style detection by BPM + spectral profile |
| `yt_download.py` | YouTube download → WAV → madmom annotations (Warp proxy) |
| `repaint_transition.py` | AI transition generation via ACE-Step 1.5 Repaint |
| `transitions_reel.py` | Extract crossfade zones into short preview MP3 |
| `mix_validator.py` | Threshold-based validation of analysis results |

---

## Quality chain

```
Source WAV (24-bit/44.1kHz)
  → float32 processing (lossless)
  → LUFS normalization (full track, -14 LUFS)
  → Warp + Crossover (float64→float32)
  → WAV PCM_24 master (archival quality)
  → MP3 320kbps (final delivery)
```

---

## Configuration

Edit `mix_config.py`:

```python
WAV_DIR = "/opt/autodj-mixer/tracks"
ANN_DIR = "/opt/autodj-mixer/ann"
TARGET_LUFS = -14.0
MAX_SHIFT_SEC = 0.05
# TRACKS = [(name, wav, ann), ...]
```

CLI flags in `smart_mixer.py`:
| Flag | Default | Effect |
|------|---------|--------|
| `--style` | None | Genre → auto-filename `{Style}_Mix_{date}.mp3` |
| `--author` | None | MP3 artist tag |
| `--bitrate` | 320k | MP3 bitrate |
| `--use-quiet-exit` | False | Exit on QUIET section |
| `--no-stabilizer` | False | Disable RMS stabilizer |
| `--quick-test` | False | 2 tracks, 2-bar CF (2 min) |
| `--transitions-dir` | None | AI transitions directory |

---

## Version history

| Version | Changes |
|---------|---------|
| **v14** | CHANGELOG overhaul. warp thresholds unified (0.002 everywhere). MIN_SOLO_BARS removed. v2 artefact detectors restored (9 types). `--feedback` returned. Zone scanning (±15s transitions only). transitions_reel integrated into pipeline. run_pipeline cleaned up (no --json-out). |
| v13 | Seamless blend→ramp (warp_extra 17th bar). Pre-warp phase alignment. Chunk-0 per-bar fix. CF_BARS+2. ACE-Step Repaint pipeline. Preview step. CMLc/Cemgil/P-score metrics. |
| v12 | Narrow RMS stabilizer + look-ahead gain. |
| v11 | HPSS only, endpoint crossfade → gain-match. |
| v10 | RMS stabilizer, power-law fades, downbeat-weighted alignment, bass polarity check. |
| v7 | Bar-by-bar warp, BPM ramp-back, micro-align ±50ms. |
| v6 | LR4 3-band crossover, bass swap, FFT correlation. |

---

## License

MIT