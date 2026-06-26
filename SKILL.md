---
name: autodj-mixer
category: software-development
description: >-
  AutoDJ Smart Mixer — operational guide for ALL agents (Hermes, MimoClaw, any
  future operator). Agent rules & restrictions, data retention, the two curation
  paths (A=charts, B=knowledge/seed), the full brief→mix pipeline, the
  orchestrator, and hard-won DSP/annotation lessons. Single source of truth.
triggers:
  - dj mix, audio mixing, crossfade, "сделай микс", "склей треки", "смиксуй"
  - curation, brief, tracklist, curate_tracks, curation_bridge, seed_discover
  - path b, seed-based, build_seedlist, prescreen, local_enrich, lastfm
  - a1f analysis, structural segmentation, vocal intervals
  - Camelot wheel, key detection, BPM, harmonic mixing
  - madmom, beat detection, annotation, pyrubberband, LR4 crossover
  - mix analysis, artefact detection, quality validation, catbox upload
  - catalog, retention, cleanup wav, orchestrate, report
tags: [audio, dj, mixing, production, automation, a1f, camelot, path-b, agent-rules]
---

# autodj-mixer — operational guide for ALL agents

**Canonical copy:** `/opt/autodj-mixer/SKILL.md` on GitHub — the SINGLE source of truth.
**GitHub:** https://github.com/StanAngular/autodj-mixer
**Audience:** every agent operating this pipeline — Hermes, MimoClaw (cclaw), future agents.
**State:** code + this doc current through P30. Knowledge lives HERE (committed), not in
local-only skill edits — a daily cron mirrors the local skill FROM this canonical file,
so anything not committed here is lost. Improvements go in via reviewed patches + commit.

---

## §0 — ROLE & HARD RULES (read first, non-negotiable)

You are an **OPERATOR of the pipeline, not its developer.** Run mixes and report; do not change how the machine works.

1. **Never edit code or generated configs by hand** (`smart_mixer.py`, `curate_tracks.py`, `mix_config_*.py`, …). On failure → **report the exact log and STOP.** Code changes come ONLY as reviewed patches from the maintainer.
2. **No background processing.** Every step foreground, visible. Background hides failures and gets interrupted.
3. **No improvisation, no skipping steps, no workarounds.** A failing command is a report, not a cue to invent another (no truncating IDs, no hand-patched paths, no fake stub files).
4. **Never delete or alter data to "pass" a step.** (Retention cleanup §1 is the only allowed deletion, AFTER delivery, via `cleanup_wavs.py`.)
5. **Always SHOW the work** (§6): approval tracklist (BPM/Camelot/YouTube + playlist), the harmonic chain, the preview reel **with beeps**, the final templated report.
6. **Discipline:** `git pull` before work · `pytest tests/unit -q` before any push · one concern per commit · `git apply --check` before applying · verify pushed tree via `git log origin/main` (don't trust summaries) · never invent commit hashes.

> About to edit a `.py`, run something in the background, fake a file, or skip the preview — **stop and report instead.**

### Token efficiency & automation
- **Prefer one orchestrating command** (§2, `orchestrate.py`) over many manual ones.
- **Scripts emit concise STRUCTURED output** (summary lines, JSON) — **not raw logs.** Report the summary; never paste yt-dlp/Tunebat/DSP log floods.
- **Foreground ≠ verbose.** Bounded structured output keeps both control and low token use.
- **The orchestrator is NOT autopilot.** Run it in segments with checkpoints — above all, review candidate count + the harmonic chain **before** the expensive download/mix. Approving between phases is required while quality is still being hardened.
- **HARD LIMITS are in code, not just docs** (P32): `seed_limit=24`, `max_probe=30`, `target=16`. Agent *cannot* exceed them even if it "prioritises downloading more."

---

## §1 — DATA RETENTION POLICY

WAV audio is huge and disposable; metadata is small and precious.

- **WAV tracks (`shared/tracks/*.wav`) and the WAV mix are TEMPORARY.** After the mix is delivered, delete WAVs via **`cleanup_wavs.py`** (dry-run default; `--apply` to delete). Keep only the **MP3** mix.
- **Metadata is PERMANENT** — catalog (`shared/catalog/`) + **`shared/a1f_results/*` (full A1F json + .meta.json)** + **`shared/ann/*` (madmom)**. `cleanup_wavs.py` touches ONLY `tracks/*.wav` — it never deletes a1f_results, ann, or MP3.
- **Register tracks in the catalog BEFORE deleting WAVs** (`catalog_register.py`). Guard: `cleanup_wavs.py` deletes a WAV only if its video_id is confirmed in the catalog; unregistered WAVs are kept + warned.
- Tracks re-download from `youtube_url`; analysis is never repeated.

---

## §2 — PIPELINE: two curation paths + common tail

A brief is given in **plain text**. You turn it into seeds/config. There are TWO curation paths feeding one common mix tail.

### Path A — from charts (mainstream / charted)
`curate_tracks.py --config brief.json --out NAME_cand.json` → BPM/Camelot from Beatport-tracks (+ Tunebat gap-fill). A coarse **year/BPM gate** drops clearly out-of-range tracks (known year/bpm only; unknown kept).

### Path B — from knowledge (country / underground / rare / new — NOT in DBs)
```
build_seedlist.py  --style S --artists "A,B" --tag T  → NAME_seeds.txt   (PulseRoots + last.fm, --limit 24)
seed_discover.py   --artists-file NAME_seeds.txt --per 1 --out NAME_cand.json   (yt-dlp search)
resolve_metadata.py  NAME_cand.json                   (каскад: каталог→кэш→Beatport(by-name)→tunebat, без скачивания)
prescreen.py       NAME_cand.json --bpm-min .. --bpm-max ..  → keepers + url-file   (MP3 probe, --max-probe 30 --target 16)
yt_download.py     --url-file NAME_urls.txt          (WAV — ONLY keepers, ≤16)
local_enrich.py    NAME_cand.json --tracks-dir shared/tracks   (Camelot/BPM from WAV)
```
**Country = your knowledge** (seed artists by nationality), NOT a scrape. last.fm `geo.*` is "popular IN country" (global pop), not "from country" — weak signal only.

### Common tail (both paths)
```
batch_annotate.py                                   (madmom downbeats → shared/ann)
[A1F fast — for structure / transition placement; see §5]
curation_bridge.py NAME_cand.json --name NAME --prune-wav-dir shared/tracks → mix_config_NAME.py
run_pipeline.py --wav-dir shared/tracks --ann-dir shared/ann --config mix_config_NAME.py
                --analysis-mode a1f_fast|no_a1f          (does mix + report + preview + upload)

- **A1F длинных миксов**: `batch_a1f.py <wav_dir> [a1f_dir]` — A1F ПАЧКОЙ по одному треку (свой таймаут/резюм/скип) в `a1f_results` (оттуда микс читает и catalog_register кладёт в каталог). В фоне (`nohup … &`) ДО микса; затем микс с `--a1f-dir`. `--depth full`(дефолт: +вокал Demucs, собираем всё для переиспользования)/`fast`(--skip-separation, без вокала, 5-10× быстрее). `--mode auto`(дефолт): A1F ТОЧЕЧНО — короткие/нерегулярные треки (длительность + CV madmom-даунбитов, `--ann-dir`), регулярным madmom достаточно; по-трековое дополнение к пул-уровневой curation_bridge.recommend_analysis. Что не посчиталось — микс берёт no_a1f, не падает.
catalog_register.py NAME_cand.json --a1f-dir shared/a1f_results
cleanup_wavs.py --tracks-dir shared/tracks [--apply]      (after delivery)
```

### Orchestrator (one command, staged)
`orchestrate.py NAME --path b --artists "…" --tag "…" --bpm-min .. --bpm-max .. [--a1f] [--cleanup]`
Dry-run by default (prints the exact plan). Add `--run` to execute foreground: full output → `logs/<stage>.log`, only each stage's final summary line to context, **stop on first error**. **Not autopilot** — review the dry-run plan and the mid-pipeline harmonic chain before committing to download/mix.

### Tools reference
| Script | Path | Purpose |
|---|---|---|
| `curate_tracks.py` | A | charts → candidates (BPM/Camelot), year/BPM gate, approval table, harmonic order |
| `build_seedlist.py` | B | style/artists → concrete seed-strings (PulseRoots + last.fm similar/top-tracks/tag) |
| `seed_discover.py` | B | seeds → YouTube: ищет 5 на сид, проверяет личность/стиль, выбирает лучший по просмотрам (P34) |
| `resolve_metadata.py` | both | каскад: каталог→кэш→**Beatport(by-name)**→tunebat (без скачивания) |
| `prescreen.py` | B | cheap MP3 probe → Camelot/BPM → keep only fitting (--max-probe 30 --target 16) |
| `local_enrich.py` | B | compute Camelot/BPM from downloaded WAV (no DB needed) |
| `lastfm.py` | B | similar / top-tracks / tag / geo (`--check` = live API test) |
| `curation_bridge.py` | both | candidates → `mix_config_NAME.py` + urls; `--prune-wav-dir` drops failed downloads |
| `run_pipeline.py` | both | preflight → smart_mixer → report → preview → upload |
| `catalog_register.py` | both | register tracks (camelot/youtube_url + full A1F + meta + madmom method) |
| `cleanup_wavs.py` | both | catalog-guarded WAV deletion, dry-run default |
| `orchestrate.py` | both | chain the stages, compact summaries, dry-run default |
| `report.py` | both | DJ AGENT 001 report (deterministic fields + creative slots) |
| `mix_analyzer.py` | both | transition-zone analysis (`--pad 5`), volume-jump detector |

---

## §3 — Shared directory structure (`/opt/autodj-mixer/shared/`, group `users` 775)

| Path | Contents | Retention |
|---|---|---|
| `shared/tracks/` | WAV (`*.wav` gitignored) | TEMPORARY |
| `shared/probe_mp3/` | MP3 probes for prescreen | temporary |
| `shared/ann/` | madmom downbeats (`.txt`, **time-based** — §7) | PERMANENT |
| `shared/a1f_results/` | A1F json + `<id>.meta.json` (yt-dlp meta) | PERMANENT |
| `shared/catalog/` | `catalog_index.json`, `catalog_utils.py` | PERMANENT |

---

## §4 — Curation detail

### Harmonic order (curation side)
- `camelot_distance(a,b)` (0 exact · 1 neighbour/relative · 2 diagonal · ≥3 clash) drives `_harmonic_order` (greedy min-distance). `camelot_relation` labels a far pair as **"clash"**, NOT a fake "diagonal energy boost".

- **Camelot alignment (P54)**: микшер берёт КУРИРОВАННЫЙ Camelot primary (`CAMELOTS` в mix_config из curation_bridge), `detect_key` из аудио — fallback (`resolve_camelot`). Гармоническая цепочка курации/треклиста теперь совпадает с тем, что реально сводит микшер (раньше микшер детектил свой и мог разойтись). Лог: `Camelot: 8A [curated] (detect=5A)`.
- `harmonic_chain_trace` prints the chain (smooth / energy / jump) — shown ALWAYS.
- Approval table (artist/track/BPM/Camelot+relation/country/views/YouTube + playlist URL) prints in agent mode too. Don't use `--no-approve` for real mixes.
- Year/BPM gate (`passes_sanity`): drops a track only if its year/BPM are **known and out of range**; unknown metadata is kept (Path B fills it later).

### Sources
- **Beatport** (`beatport_source.py` + `curate_tracks.py`): чистые ТРЕКИ (не сеты) с готовыми BPM/Camelot, обход = Playwright stealth + Warp SOCKS5 + xvfb (как раньше). Две роли:
  (1) **источник** — `orchestrate --source beatport --style <genre>` (чарты жанра → сиды с метаданными → поиск аудио). Поля: Mix Name/Label/Release Date/Genre. Гейты: **отсев Radio Edit** + **год** (`--year-min/--year-max`).
  (2) **резолвер по имени** — `search_beatport_track` в каскаде resolve (requests, БЕЗ Cloudflare → стоит ПЕРЕД Tunebat). Has **no reliable artist country.** Полная спека и чек-лист: `docs/beatport.md`.
- **Маршрутизация источников:** метаданные — фоллбэк-каскад (есть). Жанры: `BEATPORT_GENRE_SLUGS` покрывает все основные жанры Beatport V4 (+алиасы); `beatport_slug()` нормализует фразу через PulseRoots (вспомогательно), неизвестный жанр пропускает как есть. `--tracklist <файл>`: явный список `Artist - Title` (из веб-поиска/LLM — ЛЮБОЙ жанр/год, минует Cloudflare) → метаданные BPM/Camelot (если LLM их дал из Beatport/Tunebat-листинга) ЕДУТ с сидами (как Beatport) → smart-bypass не перепроверяет; чего нет — каскад/local_enrich. discover находит аудио → микс. Так берём 2025+ свежак (прямой скрейп Beatport за Cloudflare). Discovery — ДЕФОЛТ `--source auto`: по УБЫВАНИЮ данных **Beatport→Bandcamp→last.fm/YouTube** (следующий только если не добрали target; дедуп). last.fm/YouTube беднейший (имена/дрейф) → ГЕЙТ стиля (+remix). `youtube`/`beatport` — оверрайд. Discogs (релизы→треки) — TODO. См. docs/beatport.md.
- **Tunebat**: slow, demand-driven gap-fill only. With Path B local_enrich it's largely unneeded for Camelot/BPM.
- **last.fm** (`lastfm.py`): `getSimilar`, `getTopTracks` (concrete tracks!), `tag.getTopArtists` (genre-accurate) — solid. `geo.*` = popular IN country (NOT from) — weak.
- **PulseRoots** (`style_resolver.py` + `data/pulseroots.SOURCE.txt`): style → Beatport slug + seed_artists + similar styles + wikipedia.
- Blocked: 1001Tracklists (Cloudflare), Resident Advisor (DataDome) on Warp IP.

---

## §5 — A1F (structure) — and why it matters

A1F (`all-in-one-fix`, env `A1F_PYTHON`; see `docs/a1f-setup.md`) gives beats/downbeats/**segments**. Segments = **where to place transitions**. madmom alone gives beats but NO section boundaries, so **without A1F the mixer places transitions blind** (wrong spots). For anything beyond trivial, A1F structure is needed for good placement.

- **fast** (`--skip-separation`): CPU, no Demucs — beats/downbeats/segments. Default.
- **full** (Demucs): only for vocal_intervals; heavy.

⚠ **KNOWN BREAKAGE (open):** `--skip-separation` still tries to read `demix/htdemucs/*/bass.wav` and crashes on missing stems; faking empty stub stems yields silence → `BPM=None, beats=0`. Do **not** fake stems. Until A1F fast is fixed on the server, structure is unreliable — this is a maintainer patch, not an agent workaround.

---

## §6 — What you MUST show (reporting & delivery)

1. **Approval tracklist + YouTube playlist + harmonic chain** (§4).
2. **Transitions preview reel** — `transitions_reel.py`: crossfade zones as one MP3 **with beep markers** (440 Hz before each transition, 880 Hz between clips). Send the **audio**, not a text table.
3. **Final MP3 @ 320k** → catbox/litterbox link.
4. **Report** (`report.py`, DJ AGENT 001 template): header = **invented mix TITLE** (creative slot the agent fills — NOT the genre); subtitle = **genre/style from the brief**. Deterministic fields filled (time, artist/track, BPM, Camelot+marker, totals, playlist); creative slots ([ИНТРО], per-track comment) filled by the agent journalist-style with internet. Legend of Camelot markers included.

**Analyzer (`mix_analyzer.py`):** run with `--pad 5` (transition zones ±5 s only) — never on the whole 40-min WAV (it hangs). Reports beat/LUFS/phase + **volume-jump** detection. Verdict is advisory.

---

## §7 — Critical lessons (DO NOT lose)

### Open quality issues surfaced by live runs (Euro Tech House Tour, Mix #7/#8)
- **Mixer detects its OWN Camelot from audio (madmom/A1F) and mixes by that — NOT our curated metadata.** So the harmonic order we curate (P20) can be overridden, and "smooth by our Camelot" becomes "POOR by the mixer's detection." Curated chain ≠ mixer chain until these are aligned. **Top quality issue.** → **ИСПРАВЛЕНО P54**: микшер берёт курированный Camelot primary (`CAMELOTS`/`resolve_camelot`), detect_key — fallback.
- **prescreen on ALL candidates = mass downloads** (a 206-seed run pulled ~200 MP3s, ~2 h). Run prescreen on a SHORTLIST; cap `build_seedlist` expansion. Don't probe hundreds.
- **prescreen BPM stored as 0/falsy** in one run → report showed a flat 126 for everyone. Probe BPM must be validated before trusting.
- **seed_discover track names = YouTube video titles** (messy), not clean artist/track. Names need cleanup before the report.

### Workflow: контрольный прогон перед полным миксом
Новый/сомнительный поток гоняй СЕГМЕНТАМИ с чекпойнтом: ранние стадии (seedlist→discover→resolve→prescreen) → СТОП → отчёт числами (сколько проб/keeper'ов, имена+BPM+Camelot, сколько из каталога/кэша/Beatport vs остаток) → ждать «ок» → только потом download/WAV/микс. Оркестратор НЕ автопилот.

### Поиск ремиксов: --remix
Для запросов «похожие на X → танцевальные РЕМИКСЫ, не оригиналы»: `seed_discover --remix`
(или `orchestrate --remix`). Дописывает 'remix' к запросу, отсеивает оригиналы (require_remix),
даёт бонус ремиксу в скоринге. Сиды — обычно last.fm getSimilar(X) → их топ-треки.

### Gotcha: seed_discover --no-verify
`seed_discover` по умолчанию требует совпадение личности (identity_ok) и отсев сетов (длительность). `--no-verify` снимает проверку личности — использовать ТОЛЬКО осознанно (иначе вернутся «какие попало»/сеты). Beatport-сиды чистые → проверка проходит штатно.

### Data model — Variant A (CANONICAL)
`db` = one downbeat/bar; `calc_bpm()` = 240 / bar_seconds (counts bars); `fix_ht()` = half/double only (85–165). External BPM (A1F) → **rebuild the grid**, don't paint over it.

### Annotation format: TIME in seconds, not samples
`load_dbeats` does `int(r[0]*sr)` → first column must be seconds (`0.050000 1`). Sample-based (`88200 1`) crashes filtfilt/norm_lufs. Check: `head -1 shared/ann/ID.txt` (decimal = good).

### norm_lufs headroom (recurring regression)
`grep -n 'if pk >' smart_mixer.py` must be `0.707` (−3 dB), not `0.99`. Verify before every mix.

### 5 DSP bugs (do not reintroduce)
fix_ht dead ratio → window 85–165 + grid densify · A1F BPM overwritten by calc_bpm → A1F is reference · "LR4" was butter(2) once → cascade ×2 (−24 dB/oct) · bass hole in build_cf_lr4 → constant-sum cos²/sin² on raw LR4, no eq_sweep on lows · removed dead eq_sweep/_sweep_channel/_shelf_coeffs.

### Other guards
`sections()` filtfilt guard `len(mono) > 20` · check callers (`grep -rn`) before deleting helpers · Warp reconnect, sequential downloads only · `python3 -m demucs` (name collision).

### Tests are the spec
Code vs tests disagree → STOP, ask maintainer. `pytest tests/unit -q` before every push.

---

## §8 — Path B quick recipe (country / underground / rare)

For "one track per country", "French organic house", underground, new releases:
1. **Seed by knowledge** — you know which artists are from where / are underground. Feed them to `build_seedlist` / `seed_discover` (set `country` per seed for uniqueness constraints). Keep the seed list SMALL and targeted (a handful per slot), not hundreds.
2. **Probe cheap** — `prescreen` a shortlist (MP3) to get Camelot/BPM before any WAV.
3. **Download only keepers** (WAV), `local_enrich` fills Camelot/BPM from audio.
4. Common tail (bridge → run_pipeline → catalog → cleanup).

Reliable last.fm for this: `getTopTracks(artist)` (concrete tracks), `getSimilar` (expand), `tag.getTopArtists` (genre). Avoid leaning on `geo.*` for "from country".
