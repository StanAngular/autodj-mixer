---
name: autodj-mixer
category: software-development
description: >-
  AutoDJ Smart Mixer — operational guide for ALL agents (Hermes, MimoClaw, any
  future operator). Covers agent rules & restrictions, data-retention policy,
  the full brief→mix pipeline (curation → bridge → download → annotate → A1F →
  mix → analyze → report), and hard-won DSP/annotation lessons.
triggers:
  - dj mix, audio mixing, crossfade, "сделай микс", "склей треки", "смиксуй"
  - curation, brief, tracklist, curate_tracks, curation_bridge
  - a1f analysis, structural segmentation, vocal intervals
  - Camelot wheel, key detection, BPM, harmonic mixing
  - madmom, beat detection, annotation
  - pyrubberband, bar-by-bar warp, LR4 crossover
  - mix analysis, artefact detection, quality validation, catbox upload
tags: [audio, dj, mixing, production, automation, a1f, camelot, agent-rules]
---

# autodj-mixer — operational guide for ALL agents

**Canonical copy:** `/opt/autodj-mixer/SKILL.md` on GitHub (always current).
**GitHub:** https://github.com/StanAngular/autodj-mixer
**Audience:** every agent that operates this pipeline — Hermes, MimoClaw (cclaw), and any future agent.

---

## §0 — ROLE & HARD RULES (read first, non-negotiable)

You are an **OPERATOR of the pipeline, not its developer.** Your job is to *run* mixes and *report*, not to change how the machine works.

1. **Never edit code or generated configs by hand.** Not `smart_mixer.py`, not `curate_tracks.py`, not `mix_config_*.py`, nothing. If something fails or doesn't add up → **report the exact log and STOP.** Code changes come ONLY as reviewed patches from the maintainer.
2. **No background processing.** Run every step in the foreground with visible output. Background jobs get interrupted and hide failures (and hide sloppy work). If a step is slow, say so and wait in the foreground.
3. **No improvisation, no skipping steps, no "creative" workarounds.** Follow the documented commands exactly. If a command doesn't work, that's a report, not a cue to invent another.
4. **Never delete or alter data to "pass" a step.** (Retention cleanup in §1 is the only allowed deletion, and only AFTER delivery.)
5. **Always SHOW the work** (see §6): the approval tracklist (with BPM/Camelot/YouTube links + playlist), the Camelot/BPM build process, the audio preview reel **with beeps**, and the final templated report.
6. **Discipline:** `git pull` before work · `pytest tests/unit -q` before any push · one concern per commit · `git apply --check` before applying a patch · verify the pushed tree with `git log origin/main`, don't trust summaries · never invent commit hashes or specs.

> If you ever find yourself about to edit a `.py` file, run something in the background, or skip the preview — **stop and report instead.**

### Token efficiency & automation (compatible with the rules above)
Goal: the agent issues **few commands** and carries **little in context**, while the user still sees everything that matters.
- **Prefer one orchestrating command** over many manual ones (see §2 — the orchestrator runs the chain foreground).
- **Scripts do the work and emit concise STRUCTURED output** — summary tables, JSON status, and the §6 artifacts — **not raw logs.** Report the structured summary, never paste verbose intermediate output (yt-dlp lines, Tunebat misses, DSP per-bar logs).
- **Foreground and visible ≠ verbose.** Bounded, structured output keeps both control (§0) and low token use. "No background" is about not *hiding* work, not about dumping every log line.
- This is a standing goal until the pipeline is fully hardened; new scripts/patches should default to a quiet structured mode with an opt-in verbose flag for debugging.

---

## §1 — DATA RETENTION POLICY

WAV audio is huge and disposable; metadata is small and precious.

- **WAV tracks (`shared/tracks/*.wav`) and the WAV mix are TEMPORARY.** After the mix is rendered AND delivered to the user, delete the WAVs (≈1 h grace). Keep only the **MP3** mix.
- **Track metadata is PERMANENT** — it lives in the catalog (`shared/catalog/`): BPM, Camelot, A1F structure, `youtube_url`, genre. **Register tracks in the catalog BEFORE deleting their WAVs.** Tracks can always be re-downloaded from their `youtube_url`; their analysis is never repeated.
- Net effect: persist **catalog + final MP3**; ephemeralize **WAVs**. This deletion is intended retention, distinct from the §0.4 prohibition on improvised deletion.

---

## §2 — PIPELINE (current, brief → MP3)

The maintainer gives a **brief in plain text** (e.g. "получасовой melodic techno после полуночи, плавный рост, гармонично"). Turn it into a config, then run the chain. Do **not** ask for JSON — you build it.

```
brief (text)
  → config            (brief_parser.py  OR  emit JSON yourself from --print-config-schema)
  → curate_tracks.py  → cand.json   (+ APPROVAL table shown — §6)
  → curation_bridge.py → urls + mix_config + analysis recommendation
  → yt_download.py --url-file …       (WAV by video_id + downbeats)
  → batch_annotate.py                 (madmom downbeats → shared/ann)
  → [A1F fast] if recommended         (§5)
  → curation_bridge.py --prune-wav-dir shared/tracks   (drop failed downloads)
  → run_pipeline.py --config …        (preflight → smart_mixer → report)
  → analyzer (transitions-only) + preview reel + catbox + report (§6)
  → deliver MP3 → retention cleanup (§1)
```

### Config contract for agents
You don't need to read source to build a config:
```bash
python3 curate_tracks.py --print-config-schema   # JSON schema + valid example, no network
```
Fields, enums (`speed`, `discovery`, `trajectory`), and a self-validating example come straight from this. Emit a config that matches it.

### Canonical commands
```bash
cd /opt/autodj-mixer
git pull

# 1. Curation (APPROVAL MUST BE SHOWN — see §6; do not suppress it)
xvfb-run --auto-servernum python3 curate_tracks.py --config brief.json --out cand.json

# 2. Bridge → urls + mix_config (trajectory order, real names) + A1F recommendation
python3 curation_bridge.py cand.json --name <mixname>

# 3. Download (note: --url-file, NOT a bare filename)
xvfb-run --auto-servernum python3 yt_download.py --url-file urls_<mixname>.txt

# 4. Madmom downbeats
python3 batch_annotate.py

# 5. A1F fast — only if the bridge recommended it (it prints the exact command)

# 6. Reconcile config to what actually downloaded (auto-drops 403/failed)
python3 curation_bridge.py cand.json --name <mixname> --prune-wav-dir shared/tracks

# 7. Mix (foreground; it's slow — A1F+DSP on N tracks can take 15-25 min)
xvfb-run --auto-servernum python3 run_pipeline.py --config mix_config_<mixname>.py
```

> **Approval note:** the curated tracklist (with BPM/Camelot/YouTube links + playlist URL) must be shown to the user. `--no-approve` suppresses it — do **not** use it for real mixes. (A patch is making the table print even in agent/non-interactive mode; until then, surface `cand.json` contents to the user.)

---

## §3 — Shared directory structure (`/opt/autodj-mixer/shared/`)

Group `users` (775) — all agents have rwx.

| Path | Contents |
|------|----------|
| `shared/tracks/` | WAV files (gitignored `*.wav`) — **temporary**, see §1 |
| `shared/ann/` | madmom downbeat annotations (`.txt`, **time-based** — §7) |
| `shared/a1f_results/` | A1F JSON + `[ID].meta.json` (yt-dlp metadata) |
| `shared/catalog/` | `catalog_index.json`, `catalog_utils.py`, `update_catalog.py`, `delete_tracks.py` — **permanent** track data |

All code paths point to `shared/`. Keep perms 775 / group `users`.

---

## §4 — Curation

Deterministic, no LLM in the loop (`curate_tracks.py`). Sources via `playwright_scraper.py` (Playwright + stealth, `headless=False` under `xvfb-run`).

### Sources status
| Source | Status | Gives BPM/Camelot? |
|--------|--------|--------------------|
| **Beatport (beatport-tracks)** | ✅ primary | **Yes** — from `__NEXT_DATA__` (`item.bpm` + `item.key`→Camelot) |
| Discogs API | ✅ | No (release DB; messy "Various"/feat names) |
| Bandcamp | ✅ (via Warp SOCKS5) | No |
| 1001Tracklists | ❌ Cloudflare blocks Warp IP | — (needs resident proxy) |
| Resident Advisor | ❌ DataDome | — |

### How enrichment works now (P15–P16)
- **Beatport tracks already carry BPM + Camelot** — curation uses the `beatport-tracks` source and the conversion preserves them. They do **not** go to Tunebat.
- **Tunebat is demand-driven (P16):** it runs *only* if complete tracks don't cover the segment (Beatport usually over-covers → 0 Tunebat calls). Tunebat is slow (~45 s/track) and matches Discogs's messy names poorly, so we feed it as little as possible. Never raise the curation timeout to "let Tunebat finish" — fix the supply instead (report it).
- Enrichment results cache to `data/enrich_cache.json` (BPM/Camelot are stable, cache never goes stale).

### Bridge (`curation_bridge.py`)
- Builds `mix_config` in **trajectory order with real names**, mapped to `<video_id>.wav/.txt`.
- `recommend_analysis` decides madmom-only vs **A1F fast** by indirect signals (multi-segment / BPM spread >16 / ≥12 tracks).
- `--prune-wav-dir` rebuilds the config from **actually downloaded** WAVs (handles 403/failed downloads without manual edits).

---

## §5 — A1F (All-In-One Music Structure Analyzer)

External heavy ML tool (`all-in-one-fix`, namespace `allin1fix`) in its own venv — **not vendored**. Full setup in `docs/a1f-setup.md`.

- **Path is portable:** resolved via `a1f.a1f_python()` (env **`A1F_PYTHON`**, fallback `~/ai-tools/all-in-one-fix/venv/bin/python`). On a new server just `export A1F_PYTHON=…` — no code edits.
- **Two modes** (= Demucs on/off):
  - **fast** (`--skip-separation`): CPU, 5–10× faster, gives beats/downbeats/segments. **Default.**
  - **full** (Demucs): only for **vocal_intervals**; heavy. Manual choice for vocal-sensitive mixes.
- A1F **downbeats replace madmom** when present; segments → bar labels. `activations`/`embeddings`/`beat_positions` are NOT used (`-a`/`-e` not passed) — don't enable them.
- `--skip-separation` needs existing Demucs stems for full mode; in fast mode it's fine. If you hit `FileNotFoundError: bass.wav`, that's the stems gotcha — report, don't improvise.

---

## §6 — What you MUST show (reporting & delivery)

1. **Approval tracklist** — # · Artist — Track · BPM · Camelot · year/date · **YouTube link**, plus the **YouTube playlist URL** for the whole set. Show it and let the user see it.
2. **Camelot/BPM build** — surface how the set is built: oporni hits (anchors) + harmonic fill, the resulting Camelot chain and BPM curve. The user wants to *see* this, not just the final list.
3. **Transitions preview reel** — `transitions_reel.py` renders the crossfade zones into one short MP3 **with audible beep markers** (440 Hz before each transition, 880 Hz between clips) and silence gaps. **Send the MP3 audio to the user**, not a text table.
4. **Full mix** — final **MP3 @ 320k** uploaded to catbox/litterbox; give the link.
5. **Final report (templated, with legend):**
```
=== [Concept] Mix [Date] — Отчёт ===
📁 MP3: …   ⏱ MM:SS   🔗 catbox: …
Треки:    # | Исполнитель — Трек | BPM | Camelot | Год | YouTube
Переходы: # | Time | A→B | BPM | Camelot | Drift | Качество
Анализ:   бит / LUFS / фаза, средний Cemgil, вердикт PASS/WARN/FAIL
Легенда:  SAME=тот же ключ · ADJ=соседний по Camelot · POOR=большой скачок
```

### Analyzer (`mix_analyzer.py`) — use with care
- **Run it ONLY on transition windows (±5 s around each crossfade), not the whole mix.** librosa on a 40-min WAV hangs/crashes. (Transitions-only mode is a pending patch — until then, analyze the preview reel, not the full WAV.)
- **Don't trust it blindly.** It currently does **not** detect post-mix loudness jumps/spikes — verify by ear / by a loudness-jump check before declaring PASS. Treat its verdict as advisory.

---

## §7 — Critical technical lessons (DO NOT lose)

### Data model — Variant A (CANONICAL, do not drift)
- `db` = **one downbeat per bar** (what `load_dbeats` returns — beat-position 1 only).
- `calc_bpm()` = `240 / bar_seconds` — counts **bars**, not beats.
- `fix_ht()` = half/double correction only (window 85–165 BPM).
- **Invariant:** `db` and `bpm` always consistent. External BPM (A1F) → **rebuild the grid**, don't paint over the old one (warp uses both).

### Annotation format: TIME in seconds, not sample positions
`load_dbeats()` does `int(r[0]*sr)` — first column must be **seconds**.
- Correct: `0.050000 1` … generated `np.savetxt(path, rows, fmt="%.6f %d")`.
- Wrong (crashes filtfilt/norm_lufs): `88200 1` (sample-based).
- Detect: `head -1 shared/ann/ID.txt` — decimal = good, big integer = broken.
- Fix: re-annotate with madmom (`RNNDownBeatProcessor` → `proc` → keep beat-pos 1–4, save time-based).

### norm_lufs headroom revert (the #1 recurring regression)
`norm_lufs()` `if pk > X` keeps reverting from `0.707` (−3 dB) to `0.99` (−0.09 dB) across sessions.
**Verify before every mix:** `grep -n 'if pk >' smart_mixer.py` → must be `0.707`.

### The 5 DSP bugs fixed (Phase 1, do not reintroduce)
1. `fix_ht` ratio was dead (4 bars / 1 beat ≈16) → window 85–165 + `_grid_densify()`.
2. A1F BPM was overwritten by `calc_bpm(db)` → A1F is the reference for grid rescale.
3. "LR4" was `butter(2)` once (−12 dB/oct) → cascade `butter(2)×2` = true LR4 (−24 dB/oct).
4. Bass hole in `build_cf_lr4` (eq_sweep LPF + fades double-attenuated lows) → constant-sum cos²/sin² on raw LR4, no eq_sweep on lows.
5. `eq_sweep`/`_sweep_channel`/`_shelf_coeffs` were dead after #4 → removed.

### Other guards already in place
- `sections()` filtfilt crashes on near-zero-length audio → guard `if len(mono) > 20`.
- Dead-code removal: `grep -rn` callers first. Known live helpers: `first_active()`, `first_soft_entry()`.
- Warp reconnect between YouTube downloads; **sequential only** (parallel = block).
- `demucs` package name can collide with `dmucs` — use full path / `python3 -m demucs`.

### Tests are the spec
- If code and tests disagree → **STOP, ask the maintainer.** Don't silently rewrite either.
- `pytest tests/unit -q` before every push. Verify DSP numerically (RMS, frequency response), not by docstrings.
