---
name: autodj-mixer
category: software-development
description: >-
  AutoDJ Smart Mixer project: shared directory structure, A1F structural
  analysis, Camelot key mixing, bar-by-bar warp, LR4 crossover, and quality
  preservation chain.
triggers:
  - dj mix, audio mixing, crossfade
  - a1f analysis, structural segmentation, vocal intervals
  - Camelot wheel, key detection, tonality
  - enrich metadata, yt-dlp metadata, catalog build
  - shared directory structure, dual-agent paths
  - madmom, beat detection, annotation
  - pyrubberband, bar-by-bar warp, LR4 crossover
  - genre detection, genre profiles
  - AI transition, ACE-Step repaint
  - mix analysis, artefact detection, quality validation
  - catbox upload
  - vps changelog
  - user says "сделай микс", "склей треки", "смиксуй"
tags: [audio, dj, mixing, production, automation, a1f, camelot]
---

# autodj-mixer — Hermes operational guide

**Canonical docs:** `/opt/autodj-mixer/SKILL.md` (GitHub — always up to date)
**GitHub:** https://github.com/StanAngular/autodj-mixer

**Loaded by both Hermes + ClaudeClaw (agent cclaw).**

---

## Shared directory structure (`/opt/autodj-mixer/shared/`)

Group `users` (775) — both agents have rwx access.

| Path | Contents |
|------|----------|
| `shared/tracks/` | WAV files (gitignored via `*.wav`) |
| `shared/ann/` | Madmom beat annotations (`.txt`) |
| `shared/a1f_results/` | A1F analysis JSON + `[ID].meta.json` (yt-dlp metadata) |
| `shared/catalog/` | `catalog_index.json`, `catalog_utils.py`, `update_catalog.py` |

**All code paths** point to `shared/` — no more `tracks/`, `ann/`, or `track_catalog/` in the codebase.

---

## Pipeline (strict order)

1. **Pre-analysis** — BPM + Camelot + optimal track order
2. **A1F enrichment** — `enrich_metadata.py --all` (artist/title/genre/year, key + Camelot, vocal_intervals, youtube_url, is_russian). Mix numbering: `run_pipeline.py` assigns sequential `MIX-#` to each mix.
3. **Preview** — send transition table to user, **wait for confirmation**
4. **Mix** — `smart_mixer.py --wav-dir ./shared/tracks --ann-dir ./shared/ann`
   - **Default:** `--analysis-mode a1f_fast` (fast, ~2-3 min/track, skip-Demucs — sufficient for most mixes; auto-upgrades to full A1F if vocal_density > 0.5)
   - **A1F mode:** full Demucs + structural analysis (triggered automatically for vocal-heavy tracks or via explicit `--analysis-mode a1f`)
5. **Analysis** — `mix_analyzer.py --feedback`
6. **Validate** — `mix_validator.py`
7. **Upload** — catbox; if file > 50MB → re-encode at 96kbps for Telegram: `ffmpeg -i mix.mp3 -b:a 96k mix_tg.mp3`
8. **Article** — DJ AI001 format
9. **Ask to delete** — offer to delete source tracks (WAV + ANN + A1F) via `shared/catalog/delete_tracks.py`

**Token efficiency:** `a1f_fast` saves ~300k input tokens vs `a1f` (no A1F JSON loading, no Demucs wait). Default to `a1f_fast`. Auto-upgrades to full `a1f` when vocal_density > 0.5.

**Automation:** `run_pipeline.py` does steps 3-8 in one call. Step 9 (ask to delete) is manual.
**Never run full mix without preview + confirmation.**

---

## Quick start

```bash
cd /opt/autodj-mixer
.venv/bin/python smart_mixer.py \
  --wav-dir ./shared/tracks \
  --ann-dir ./shared/ann \
  --output mix.mp3 \
  --analysis-mode a1f_fast
```

## Enrich metadata for all tracks

```bash
cd /opt/autodj-mixer
uv run python3 enrich_metadata.py --all
```
Fetches yt-dlp metadata → `shared/a1f_results/[ID].meta.json`
Detects key (librosa) → adds `key` + `camelot` to A1F JSON
Extracts vocal_intervals from A1F segments

## New track workflow

1. Download: `yt_download.py "https://youtube.com/watch?v=ID"` → WAV → `shared/tracks/`, ann → `shared/ann/`
2. A1F analysis: `smart_mixer.py --wav-dir ... --analysis-mode a1f` auto-launches allin1fix in background
3. Enrich: `enrich_metadata.py --ids ID`
4. Register in catalog: `register_new_tracks.py`

## Pitfalls

- **Warp reconnect** between YouTube downloads (`warp-cli disconnect; sleep 1; connect; sleep 3`)
- **Sequential only** for downloads — parallel = YouTube block
- **git pull before mixing** — both agents work on the same repo
- **Commit all related files together** (mixer + analyzer + CHANGELOG + SKILL.md + tools)
- **Never rewrite analyzer** — add on top of v3+v2 hybrid
- **fix_ht is v4** (med-based, commit b851b12) — not v1
- **Shared dir permissions** — must be 775, group `users` for cclaw access
- **WAV files** are gitignored — `.gitkeep` placeholder in `shared/tracks/`

### norm_lufs headroom reverts (−3dB fix)

The `norm_lufs()` function's `if pk > X` check **keeps reverting** from `0.707` (−3dB) back to `0.99` (−0.09dB) after patch sessions.  
**Always verify before mixing:** `grep -n 'if pk >' smart_mixer.py` — must show `0.707`, not `0.99`.  
Reason: a previous session's Fix 4 applied the change, but a later patch or merge overwrote it. This is the single most common regression in DSP fixes.

**Last verified:** v16.3.3 (commit a11fc9c) — currently `0.707`. Check before each mix.

### search_track_genre misclassifies vocal electronics as instrumental (✅ RESOLVED v16.5 — removed keyword guessing)

`search_track_genre()` has an `electronic_keywords` block that sets `vocal_hint='instrumental'` for any title containing 'extended mix', 'remix', 'progressive', 'house', 'techno', etc. (lines 108–118).  

**FIXED in v16.5:** Keyword-based genre detection is REMOVED from fallback. Style is passed via `--style`, fallback uses 24 bars always. `search_track_genre()` is preserved but no longer used for transition length decisions.

### A1F CLI: --skip-separation requires existing Demucs stems

`--skip-separation` skips Demucs **but still expects stems** in `./demix/htdemucs/<id>/bass.wav` etc. If stems don't exist, it crashes with `FileNotFoundError`.

**Two options:**
1. **Full pipeline** (slow): omit `--skip-separation` — runs Demucs + analysis in one step (~20 min/track on CPU)
2. **Two-step** (for speed): manually run Demucs first in background, then A1F with `--skip-separation`

**CRITICAL: Demucs MUST run with full 4-stem output (no --two-stems).**
`--two-stems=vocals` produces only `vocals.wav` + `no_vocals.wav`, but ALL-IN-1-FIX expects all 4 stems: `bass.wav`, `drums.wav`, `other.wav`, `vocals.wav`. Using 2-stem output causes `FileNotFoundError: bass.wav`.

**Correct (full 4-stem):**
```bash
cd /opt/autodj-mixer
demucs "shared/tracks/ID.wav" -o demix
/home/hermes/ai-tools/all-in-one-fix/venv/bin/python -m allin1fix.cli \
  "shared/tracks/ID.wav" -o "shared/a1f_results" --skip-separation
```

**Wrong (2-stem only — DON'T use for A1F):**
```bash
demucs --two-stems=vocals "shared/tracks/ID.wav" -o demix  # ❌ no bass/drums/other
```

**Correct flag:** `-o OUT_DIR` or `--out-dir`, NOT `--output` (that's argparse-internal and won't work).

### Demucs on CPU — performance

On Contabo VPS (no GPU), Demucs htdemucs takes **~20 min per track** (full length). For batch processing of N tracks:
- Start Demucs in background with `notify_on_complete=true`
- Meanwhile, generate the mix with `--analysis-mode no_a1f` (madmom + keyword fallback)
- After Demucs completes all tracks, run A1F (`--skip-separation`) for future mixes with A1F segments

**Note:** The demo/download `demucs` package name collides with `dmucs` (Debian distributed compilation tool) on some VPS installs. Use the full path or `python3 -m demucs` to avoid the wrong binary.

**Practical advice:** `a1f_fast` (skip-Demucs) mode is sufficient for ~80% of mixes (especially instrumental/single-genre). Full A1F is auto-triggered for vocal-heavy tracks (vocal_density > 0.5). Always default to `a1f_fast` for token efficiency and speed; the auto-upgrade mechanism ensures vocal precision without manual intervention.

### Demucs on CPU — performance

On Contabo VPS (no GPU), Demucs htdemucs takes **~20 min per track** (full length). For batch processing of N tracks:
- Start Demucs in background with `notify_on_complete=true`
- Meanwhile, generate the mix with `--analysis-mode no_a1f` (madmom + keyword fallback)
- After Demucs completes all tracks, run A1F (`--skip-separation`) for future mixes with A1F segments

**Note:** The demo/download `demucs` package name collides with `dmucs` (Debian distributed compilation tool) on some VPS installs. Use the full path or `python3 -m demucs` to avoid the wrong binary.

### sections() filtfilt crashes on very short audio

`sections()` applies `scipy.signal.filtfilt` to `mono` audio. If the trimmed segment (`at = audio[s0:e0]`) is near-zero length (e.g., a track classified entirely as QUIET with early downbeats), `filtfilt` raises:
```
ValueError: The length of the input vector x must be greater than padlen, which is 9.
```
**Fix:** Guard the call:
```python
if len(mono) > 20:
    mono_low = signal.filtfilt(b_low, a_low, mono)
else:
    mono_low = np.zeros_like(mono)
```
This is already patched in the codebase. If it reappears, check that the guard is still present.

### Dead code removal must check all callers

When removing unused functions (e.g., during "Чистка мёртвого кода"), `grep -rn` for the function name across `smart_mixer.py` **before deleting**. Deleted functions that are still called at runtime cause a `NameError` crash.

**Known casualties:**
- `first_active()` — used in `mix_tracks()` at line ~1637 to find the first ACTIVE bar
- `first_soft_entry()` — used at line ~1639 to find the first BUILD bar for slave entry
- `best_exit_bar()`, `first_soft_entry()`, `first_active()`, `EXIT_SCORE`, `quiet_exit()` — removed in v16.3.5 cleanup

**Fix when this happens:** replace the call with an inline expression:
```python
# Instead of first_active(st):
fa = next((s for s, e, l in st if l in ('ACTIVE', 'DROP')), 0)

# Instead of first_soft_entry(st):
se = next((s for s, e, l in st if l == 'BUILD'), fa)
```

### Annotation format: sample positions vs time in seconds

`load_dbeats()` (line ~354) does `int(r[0] * sr)` — it expects the first column of `.txt` annotation files to be **time in seconds**, NOT sample positions.

**Correct format (time-based):**
```
0.050000 1
0.510000 2
```
Generated with: `np.savetxt(path, rows, fmt="%.6f %d")`

**Wrong format (sample-based) — causes crash:**
```
88200 1
17090955 4
```
Generated with: `np.savetxt(path, beats_samps, fmt="%d %d")`

**Symptom:** `load_dbeats()` returns enormous values (sample × 44100), then `audio[s0:e0]` produces nearly-empty arrays, causing cascading failures in `filtfilt` and `norm_lufs`.

**Detection:** Check the first value of any annotation file:
```bash
head -1 shared/ann/ID.txt | awk '{print $1}'
```
- Time-based: value contains a decimal point (e.g., `0.05`)
- Sample-based: value is an integer (e.g., `441`, `88200`)

**Fix:** Re-annotate using madmom directly with time output:
```python
act = RNNDownBeatProcessor()(wav)
beats = proc(act)
rows = [[b[0], int(round(b[1]))] for b in beats if int(round(b[1])) in (1,2,3,4)]
np.savetxt(out, rows, fmt="%.6f %d")
```

**Reference:** `references/madmom-annotation-fix-2026-06.md`

### A1F CLI: --skip-separation requires existing Demucs stems

**Reference:** `references/madmom-annotation-fix-2026-06.md`

### A1F energy blindspot — segments don't capture energy (✅ RESOLVED v16.3.5)

A1F segments (intro/verse/chorus/bridge/inst/outro) are **functional labels**, not energy levels. The same `inst` label can mean QUIET (calm breakdown) or DROP (peak energy).

**Resolution:** `HYBRID_SCORE` matrix (v16.3.5) combines A1F label + RMS energy label per bar:
- `inst+QUIET=2` (good exit) vs `inst+DROP=5` (blocked)
- `outro+DROP=3` (ok) vs `verse+QUIET=4` (still better)
- Plus energy-based cf_bars cap: both sides ACTIVE/DROP → max 4b

**Reference:** `references/v1635-hybrid-a1f-rms-scoring.md`

**Verify:**
```bash
grep -n 'HYBRID_SCORE\|bar_energy' smart_mixer.py
```

## Mix from scratch — genre workflow

When creating a mix for a new genre from zero tracks, follow the workflow in `references/mix-from-scratch-genre-workflow.md`:

1. **Track research** — yt-dlp search by genre + year filter + duration filter
2. **Tracklist compilation** — Camelot chain, BPM smoothing, vocal distribution, energy curve
3. **Download** — sequential with Warp reconnect between each
4. **A1F analysis** — `allin1fix --skip-separation` for speed
5. **Preview** — send tracklist + transition table → **wait for confirmation**
6. **Mix** — full a1f mode with auto cf_bars
7. **Analyze + Validate**
8. **Upload** — catbox
9. **Report** — transition table with BPM/Camelot/Drift/RMS + analysis verdict

**Report template:**
```
=== [Genre] Mix [Year] — Отчёт ===
📁 Файл: mix.mp3
⏱ Длительность: MM:SS
🔗 Catbox: https://litterbox.catbox.moe/XXXXX.mp3

Треки: # | Исполнитель — Трек | BPM | Key | Вокал | Год
Переходы: # | Time | Transition | BPM | Camelot | Drift | Entry RMS
Анализ: P-score, артефакты, вердикт PASS/WARN/FAIL
```

### Docstring version drift

`smart_mixer.py` docstring (line 3) — **Check on every commit:** `head -3 smart_mixer.py` — update to match `CHANGELOG.md`. Current: v16.5

---

## v16.5 changes (2026-06-12)

### Style-based fallback (removed keyword guessing)
- **Removed `search_track_genre()` keyword matching from fallback** — больше не ищем 'house'/'techno'/'progressive' в названии трека. Стиль известен из `--style`, fallback использует 24 bars (~45s) всегда
- **Minimum cf_bars raised in A1F mode:** 4→8, 8→12/16 bars — все переходы 20-60s, avg 30-40s, несколько 50-60s
- `resolve_transition_params()` теперь использует style-параметр, не keyword-угадайку

### 24dB/oct HPF→LPF (fix band_cancellation)
- **EQ Sweep filter order: 2→4** (12dB/oct → 24dB/oct)
- Круче срез = меньше фазового перекрытия = меньше band_cancellation артефактов ("эХА" звук на битах)
- `smooth_eq=True` для всех режимов

### Post-mix artifact analysis
- `mix_analyzer.py --feedback` обязателен после каждого микса
- band_cancellation > 300 = WARN, требует диагностики
- **Always create transitions preview** — extract each transition ±1s from mix, concat with 0.5s gaps, upload to catbox

### Extended transitions (20-60s)
- **CF_BARS=24** default, **RAMP_SEC=25**
- `outro→intro/inst` → **32 bars** (~60s @ 128 BPM)
- `outro/break→verse/bridge` → **24 bars** (~45s)
- Default A1F → **24 bars** (~45s)

### A1F Fast default
- `--analysis-mode a1f_fast` is now the **default** (skip-Demucs, ~2-3 min/track)
- Saves ~300k tokens vs full A1F
- Vocal-heavy auto-detection: if `track_vocal_density > 0.5` AND mode is `a1f_fast`, automatically launches full A1F (with Demucs) in background

### Mix numbering
- Each mix gets a sequential number: `MIX-#_Style_Date.mp3`
- Counter stored in `.mix_counter`
- Applied by `run_pipeline.py`

### YouTube URL in catalog
- `enrich_metadata.py` now saves `youtube_url` per track in meta.json
- `catalog_utils.add_to_catalog()` accepts `youtube_url` parameter

### delete_tracks.py
- NEW interactive script to delete tracks by ID
- Auto-recovery: removes from catalog + WAV + ANN + A1F

### Russian track filter
- `enrich_metadata.py` detects Russian tracks (keywords: русский, москва, россия, etc.)
- Flags via `is_russian` field in meta.json

### Report template
- `mix_validator.py` updated with YouTube links section placeholder

### After-mix cleanup
- After each mix, **always ask** if user wants to delete source tracks
- Interactive deletion via `shared/catalog/delete_tracks.py`

---

## 🚨 PIPELINE ENFORCEMENT (v16.7f — mandatory)

**Нарушение любого правила = STOP. Не продолжать.**

### Pre-flight (ОБЯЗАТЕЛЬНО перед каждым миксом)

```bash
# Шаг 0 — Pre-flight скрипт
cd /opt/autodj-mixer && python3 run_preflight.py
# Если ERROR → STOP, не запускать микс!
```

1. `python3 run_preflight.py` — проверка headroom, аннотаций, enrich, git, Demucs
2. `enrich_metadata.py --all` — ВСЕ треки должны иметь meta.json с youtube_url
3. Preview + подтверждение пользователя — **НЕ ПРОПУСКАТЬ**
4. `git pull` — синхронизация с cclaw
5. `git status` — проверить что нет незакоммиченных правок в smart_mixer.py

### Post-mix (автоматически + вручную)

6. **Analyzer запускается АВТОМАТИЧЕСКИ** (post-mix hook в `smart_mixer.py`)
   - Проверить вывод: `band_cancellation > 300` = WARN
7. CHANGELOG.md пишется **ДО** git commit
8. Git: `git add` всех файлов одним коммитом (CHANGELOG + mixer + analyzer + SKILL.md + preflight + tools)
9. Transitions preview: `stamps.npy` → ffmpeg нарезка ±1s → concat с 0.5s паузами (NO beeps)
10. DJ AGENT отчёт: 2 сообщения с YouTube ссылками
11. Спросить: удалить source tracks? Архив вокала?

### Root causes of pipeline failures

| Причина | Симптом | Фикс |
|---------|---------|------|
| Нетерпение агента | Пропуск preview | Pre-flight STOP при ERROR |
| enrich не сделан | Нет youtube_url в отчёте | Шаг 2 обязателен |
| annotation format | Crash в filtfilt | Pre-flight проверяет |
| Demucs stems нет | A1F crash | Pre-flight warns |
| headroom revert | Клиппинг -0.09dB | Pre-flight проверяет