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
  - compose, score, original track creation, создать трек, придумай трек
tags: [audio, dj, mixing, production, automation, a1f, camelot, path-b, agent-rules, compose]
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
7. **Before every new compose track (P146, 2026-11-20):** read `docs/claw_knowledge/guides/HERMES_INSTRUCTION_FLOAT_ACID.md` and the notes it lists (`docs/claw_knowledge/notes/`). Notes come from `plan` / `L.hook` (never `% n` arithmetic), sounds through `SG.pick` and inside +-7 st of their root, levels as in the compose kit, bass mono, hats quiet. **`allow_silent` / `allow_bad_sounds` in META are ignored by the engine** (a gate failure means fix the sounds/layers); an exception exists only on Стас's explicit request (env `AUTODJ_GATE_OVERRIDE=1` + `allow_reason` in META). Before sending run `docs/claw_knowledge/tools/musicality.py`.

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

- **A1F длинных миксов**: `batch_a1f.py <wav_dir> [a1f_dir]` — A1F ПАЧКОЙ по одному треку (свой таймаут/резюм/скип) в `a1f_results` (оттуда микс читает и catalog_register кладёт в каталог). В фоне (`nohup … &`) ДО микса; затем микс с `--a1f-dir`. Стемы demucs обязательны (модель на них работает) — «fast без стемов» НЕ существует (прежний `--skip-separation` без стемов и был багом). Ускоритель — КЭШ стемов: `--demix-dir` (дефолт `<wav_dir>/demix`), первый прогон считает+сохраняет, следующие переиспользуют (`--skip-separation` корректно). `--mode auto`(дефолт): A1F ТОЧЕЧНО — короткие/нерегулярные треки (длительность + CV madmom-даунбитов, `--ann-dir`), регулярным madmom достаточно; по-трековое дополнение к пул-уровневой curation_bridge.recommend_analysis. Что не посчиталось — микс берёт no_a1f, не падает.

- **A1F в мастере (авто)**: `run_pipeline` по умолчанию ДО микса точечно досчитывает A1F (`a1f_precompute_cmd`→`batch_a1f --mode auto`): только короткие/нерегулярные/вокальные треки, остальным madmom достаточно. Решение — ПОСЛЕ скачки (по аудио: длительность + CV madmom), это точнее метадаты. Пишет в `a1f_results` (микс читает оттуда). `--no-a1f-precompute` отключает; при `--analysis-mode no_a1f` шаг пропускается. Стемы кэшируются (P55) → повторные миксы быстрые.
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
- **Discovery fallback (когда источников не хватило):** если `compose`/`seed_discover` дали **< target** (мало кандидатов, как 7 на deep-tech) — это ТРИГГЕР запустить **`skills/music_tracklist_builder.md` Фазу 1** (веб-ресёрч: 3-5 запросов по чартам/лейблам → артист+трек+BPM+тональность → 30-40 кандидатов → фильтр). Делает **любой агент через свой `web_search`-инструмент** (Claude в чате, ClaudeClaw, Hermes — у всех он есть). КЛЮЧЕВОЕ: использовать именно search-ИНСТРУМЕНТ (API-канал), а НЕ сырой скрейп с IP VPS (curl/Playwright по Beatport/RA или по выдаче Google/DuckDuckGo — вот это ловит Cloudflare/CAPTCHA; сниппеты search-инструмента до листингов Beatport с BPM/key доходят свободно). Выход → `--tracklist` JSON `[{artist,track,bpm,camelot,year}]` → `orchestrate --tracklist` (P52: мета едет с сидами, минует Cloudflare). Не «нет такого шага» — шаг есть (Фаза 1 скилла), и доступен всем агентам.

- **DSP-сетка ядра (M1, P64)**: физ-тесты `three_band_split` (LR4-реконструкция+разделение полос), `eq_pow` (equal-power), `vocal_notch_sweep`, `norm_lufs` (попадание в target LUFS), `warp_to_grid` (длина по мастер-сетке; skip без rubberband CLI). conftest мокает тяжёлые аудио-пакеты ТОЛЬКО при их отсутствии — со стеком тесты гоняют реальную физику. Это сетка безопасности Фазы M (layered blend / stem-мэшап / pop→club rework) перед правками движка.

- **Stem-мэшап (M3, P65)**: `stem_mixer.py --vocal A.wav --instrumental B.wav --demix-dir <кэш> --vocal-camelot --inst-camelot --vocal-bpm --inst-bpm --out mashup.wav` — НАЛОЖЕНИЕ: вокал A поверх инструментала B (bass+drums+other из demucs-кэша P55). Тональность: минимальный сдвиг до ГАРМОНИЧЕСКОЙ совместимости по Camelot (соседи → 0 st, колесо!); темп: pyrubberband. Честный гейт: |shift|≤3 st, stretch 0.92–1.08 — иначе отказ с подсказкой. Отдельный opt-in модуль, smart_mixer не тронут. База для pop→club rework (M4).

- **Pop→Club rework (M4 v2, P66-67)**: `club_rework.py --pop pop.wav --drums-donor club.wav --demix-dir <кэш> [--target-bpm 124] --out club_edit.wav` — СЕКЦИОННАЯ клубная аранжировка (v1-сумматор провалил прослушку): groove-интро → verse → build (sweep + drum-lift) → DROP=припев → breakdown (без грува) → build → DROP2=припев ПОВТОРНО → outro (fade). DJ-принципы в рендере: частотные РОЛИ (вся попса под HPF 150Гц, поп-drums выброшены — низ у клубного грува; в breakdown попсе возвращают тело), sidechain-duck по четвертям, лупы донора по ЕГО A1F (peak после интро, sparse из интро — не «середина»). Гейт стретча 0.85–1.25. Требует A1F+стемы обоих (batch_a1f). Opt-in, отдельная команда — обычный микс-пайплайн НЕ роутится сюда и не тронут.

- **Rework: анализ попсы ПЕРВЫМ (P68)**: `club_rework.py --pop pop.wav --demix-dir D --analyze` → профиль (BPM/Camelot/структура/вокал-карта) + СПЕКА донора (BPM-диапазон из гейта, Camelot-совместимые, инструментальность, ≥16 peak-бар, стиль-подсказка); с `--drums-donor X` — вердикты check-donor по кандидату. Порядок правильный: попса диктует донора, не наоборот. `--pop-layers vocals` = «чистый плюс» (только вокал попсы, без её музыки). `--donor-bass` = взять и бас донора (низ в дропе; требует Camelot-совместимости — drums атональны, бас нет).

- **Фразы вокала + хук (P69)**: `vocal_phrases.py --wav pop.wav --demix-dir D [--asr-cmd 'whisper-cli {wav}'] --out phrases.json` — резка vocals-стема на ФРАЗЫ (паузы >400мс), ХУК-детекция («что прёт» = самая повторяющаяся фраза, спектральные отпечатки+косинус, чистый numpy), слова через плагинный ASR (любой CLI, '{wav}'-шаблон; без ASR — безымянные). club_rework автоматически: hook-STUTTER (×2 повтора фразы) в хвосте build перед дропом + ТИЗЕР (фраза в середине интро, сухой HPF×2). `--no-hook-stutter` отключает. Оперируем не только куплетом — фразами.

- **Фразы ПО ТЕКСТУ + word-ASR (P70)**: `club_rework --phrase 'Я приходжу я іду до тебе знову' --phrase '…' --asr groq` — word-level Whisper (Groq API, env GROQ_API_KEY; или CLI-шаблон '{wav}'→JSON) даёт КАЖДОЕ СЛОВО с таймингом; `find_text_span` находит цитату (fuzzy, терпит неточность) → вырезка точно по границам слов. Первая фраза → статтер, последняя → тизер. Фиксы по прослушке: статтер только ЦЕЛЫМИ фразами (обрубок = отказ), гигантские «фразы» дробятся по тишайшей точке (max 12s), sweep больше НЕ режет клубный грув, тизер без лишнего среза. Разделение вокал/музыка — это demucs (нейронка, класс ИИ-сервисов), НЕ эквалайзер; HPF — микс-приём ролей. Канонический текст песни для сверки ASR — бэклог (--lyrics).

- **Лирика-сверка + исполняемый план фраз (P71)**: `--lyrics-file lyrics.txt` — канонический текст (агент ищет в вебе) выравнивается к ASR-словам (тайминги ASR остаются, написание каноническое, лог покрытия) → точнее поиск цитат. `--vocal-plan plan.json` — [{phrase, at_bar, repeat, gain_db}]: АГЕНТ решает «что куда» (LLM = аранжировщик), скрипт — руки: кладёт фразы ЦЕЛИКОМ по барам поверх арки (HPF-роль + duck), не влезло — пропуск с логом.

- **Вставки как у людей (P72)**: по прослушке P71 — (1) `edge_fade` 20мс на КАЖДОЙ вставке (статтер/тизер/план): края не слышны; (2) КОНТРОЛЬ ПЕРЕСЕЧЕНИЙ в плане — вторая фраза поверх первой = «каша», пропуск с логом; (3) слово-юниты: `{word:'я', occurrence:2, repeat:3, spacing_beats:1}` = «я, я, я» по долям — универсально для любого трека; (4) fx: `reverse` и `scratch` (baby-скретч: синусоидальная скорость чтения); (5) `vocal_phrases --transcript` — полный текст СТРОКАМИ с барами: агент сначала ЧИТАЕТ и понимает смысл, потом строит план.

- **Приёмы как у диджеев (P73)**: по проф. источникам (stutter edits/DJ transitions) — (1) `lead_repeats` в плане: «я, я, я приходжу» = первое слово фразы повторяется по долям ПЕРЕД её даунбитом с НАРАСТАНИЕМ громкости, затем фраза целиком; (2) `roll:[1,0.5,0.5,0.25]` = loop-roll с уменьшением длины (machine-gun билдап); (3) КАТАЛОГ ПРИЁМОВ в club_rework.py (комментарий-гайд: какой приём в какой секции) — агент читает транскрипт + каталог и САМ решает, где lead_in/roll/scratch/reverse/spacing. Всё квантовано к долям, края fade, пересечения контролируются.

- **Discogs официальный API (Фаза 1а, P62)**: `discogs_source.py --style <Discogs-стиль> --year-min --year-max` — легальный поиск жанр+год ПРЯМО с VPS (не блокируется, токен DISCOGS_TOKEN в .env). АДАПТЕР release→tracklist разворачивает EP в реальные треки (старый fetch_discogs терял их, беря имя релиза). BPM/Camelot не даёт → pending_local (из аудио). `orchestrate --source discogs --year-min 2025 --year-max 2026` — год-констрейнт брифа теперь первоклассный фильтр (Фаза 1б). Rate-limit 60/мин соблюдён (пауза 1.1s).

- **Верификация сущности артиста (Фаза 1в, P63)**: Discogs-стиль вешается на РЕЛИЗ — в «Disco» попадает мейнстрим-поп (живой кейс: Carly Rae Jepsen). `discogs_source` теперь по умолчанию гоняет `verify_style` (last.fm-теги АРТИСТА против целевого стиля) — не-сценовые отсекаются ДО поиска аудио. `--verify-style ''` выключает; без LASTFM_API_KEY — мягкий пропуск. `styles` из Discogs теперь едут с кандидатом (merge_seed_meta) — видны в отчётах/фильтрах.

- **Discovery: YouTube + SoundCloud (P59)**: `seed_discover` ищет аудио на YouTube, а если уверенного совпадения нет — фоллбэк на **SoundCloud** (`scsearch`). Покрывает треки, которые есть ТОЛЬКО на SC и ни в каких чартах. Система track-agnostic: `--tracklist` берёт любой `Artist - Title` (мета опциональна — нет в чарте → BPM/Camelot считаются из аудио после скачки), точечный поиск по имени = штатный `seed_discover`. `soundcloud=False` отключает фоллбэк.
- **Tunebat**: slow, demand-driven gap-fill only. With Path B local_enrich it's largely unneeded for Camelot/BPM.
- **last.fm** (`lastfm.py`): `getSimilar`, `getTopTracks` (concrete tracks!), `tag.getTopArtists` (genre-accurate) — solid. `geo.*` = popular IN country (NOT from) — weak.
- **PulseRoots** (`style_resolver.py` + `data/pulseroots.SOURCE.txt`): style → Beatport slug + seed_artists + similar styles + wikipedia.
- Blocked: 1001Tracklists (Cloudflare), Resident Advisor (DataDome) on Warp IP.

---

## §5 — A1F (structure) — and why it matters

A1F (`all-in-one-fix`, env `A1F_PYTHON`; see `docs/a1f-setup.md`) gives beats/downbeats/**segments**. Segments = **where to place transitions**. madmom alone gives beats but NO section boundaries, so **without A1F the mixer places transitions blind** (wrong spots). For anything beyond trivial, A1F structure is needed for good placement.

Модель harmonix работает на 4 demucs-стемах — анализ всегда ПОЛНЫЙ (beats/downbeats/segments + vocal_intervals); «fast без стемов» НЕ существует. Разница не в данных, а в вычислено-vs-кэшировано:
- **первый прогон трека**: demucs считает стемы (медленно), `-k --demix-dir` их сохраняет.
- **последующие**: `--skip-separation` переиспользует кэш (быстро), те же данные.

✅ **ИСПРАВЛЕНО P55:** прежний `--skip-separation` без стемов падал на `bass.wav` — это была НАША ошибка вызова (флаг значит «бери готовые стемы», а не «без стемов»). Теперь `a1f.a1f_command` сам делает demucs-run+сохранение, а `--skip-separation` добавляет только когда стемы реально готовы. Стемы не подделывать.

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

- **A1F структура → вход/выход (P57)**: микшер примагничивает энергетическую точку выхода к ближайшему `outro/break/inst` и входа к `intro/inst` (`a1f_snap_bar`), bounded ±4 бара — энергия остаётся якорем, off при `no_a1f`. Перевод обрезанной сетки в полную через смещение `eb`. Лог: `A1F exit snap: bar12→bar14 (outro)`. **Требует live-сверки** (аудио в песочнице не прогнать): сравнить микс `a1f` vs `no_a1f`, если переход хуже — это локально и обратимо. Vocal-aware бленды — следующий шаг.

---

## §9 — COMPOSE ENGINE: original track creation (`autodj/compose/`)

**Location:** `/opt/autodj-mixer/autodj/compose/`
**Activation:** `source /opt/autodj-mixer/.venv/bin/activate`
**Run command:**
```sh
cd /opt/autodj-mixer
PYTHONPATH=/opt/autodj-mixer python3 -m autodj.compose run scores/<track_name>/score.py --title "Name (style)" [--seed <N>]
```
**Docs ref:** `/opt/autodj-mixer/scores/<track>/score.py` (example), `docs/COMPOSE_HARMONY.md`, `docs/COMPOSE_DEPTH.md`, `docs/COMPOSE_VECTOR.md`

Each track = one `scores/<track_name>/score.py` with `build(seed) -> Track` and `META` dict (`title`, `genre`, `key`, `target`, `master`, `lead`).

### Modern API (docs 2026-11-18, commit 64b5aa0)

**Harmony (chords.py):**
```python
plan = C.Plan.build("A", trk.tl, "minor_plagal", "lament", seed=seed)
plan.attach(trk)                              # registers harmony_notes in summary
V = plan.voicings("drop2", 50, 74, 4)         # [(step, len, [midi ...])]
bass = plan.bass(rng, 29, 45, style="root", against=V)
ctx = L.context(plan, V, bass)
```
Idioms for moods: `chords.idioms("deep")` lists home idioms, `"deep"`→ `minor_plagal`, `"melodic"`→ `lament`, etc.

**Melody (lines.py):**
```python
h8 = L.hook(plan, rng, 62, 79, 4, ctx)        # 8-bar hook A A' A B
hook = L.tile(h8, plan, 62, 79, [bars], ctx, origin=4)
top, topline = L.topline(plan, rng, 66, 76)    # slow colour notes, one per chord
```

**Microtiming (microtiming.py):**
```python
mt = MT.Ensemble(trk, seed)
t_sec = mt.time(bar, step, "pluck")            # → float seconds
```

**Sections:**
```python
PL = [("intro", 4), ("home1", 16), ("journey", 12), ...]
secs = [(b, b+n, name, {kick:1, bass:1, hook:1, ...}) for name, n in PL]
trk = Track(122, 68, seed=seed).sections(secs)
```
Section names determine harmonic role: `intro*`, `home*`, `journey*`, `break*`, `build*`, `outro*`.

### Sample handling (rules: only recorded samples, NO Vital/synth)

**SFZ multisamples** (best for keys/bass/pad — each note = native recording):
```python
SFZ("wurlitzer").render(events, T)      # events = [(t_sec, midi, vel, dur_sec), ...]
```
Library at `/home/cclaw/samples/sfz/` (readable by hermes). Registered: rhodes, wurlitzer, cp80, pianet, piano, bass, fashionbass, growlybass, bearsax.

**One-shot samples** (bass shots, lead shots — `sfz.py`):
```python
sfz.oneshot(file, release=.06, cache_dir="/home/hermes/.hermes/cache/scratch/sfz/_oneshots")
```
**cache_dir must be writable** — the default `SFZ_ROOT/_oneshots/` is under `/home/cclaw/samples/sfz/` (not writable by hermes).

**Soundgate** (quality check before use — `soundgate.py`):
```python
SG.pick(candidates, "bass", lo, hi, rng, db=db, title=title)   # returns path
```
Filters: wobble > 20¢, noise > 0.1, root outside note range. Strict mode raises if no clean candidate.

**Drums** (least used — `fresh.py`):
```python
fresh.pick(glob.glob(WA + "Kicks/*.wav"), rng, db=db, title=title)
```

**Sample paths (assets.py):**
| Var | Path |
|---|---|
| `WA` | `/home/cclaw/samples/wa_techno/WAV MIDI Presets/` (Kicks, Claps, Cymbals, Synth & Bass Shots, Percussion) |
| `WA2` | `/home/cclaw/samples/wa2/WAV MIDI Loops/` |
| `AUTODJ_SFZ` (env) | `/home/cclaw/samples/sfz/` (multisample libraries) |

### Mixing

```python
trk.bus("drums", fx=[glue()], parallel=(smash(), .12))
trk.space("room", kind="room")
trk.space("hall", kind="hall", back_db=-5)

trk.add("kick", buf, 1.0, bus="drums")                              # FIRST → duck reference
trk.add("bass", buf, level=10**(-3/20), duck=-6.0, key="kick", release_ms=90)
trk.add("hook", buf, level=10**(-7/20), duck=-3.0, key="kick", send={"room": .12})
trk.add("keys", buf, level=10**(-10/20), duck=-3.0, key="kick", depth=.3, send={"room": .15})
trk.add("pad",  buf, level=10**(-14/20), duck=-4.0, key="kick", depth=.7, send={"hall": .18})
trk.mono_low(150)
```
- `level` relative to the first layer (1.0 = 0 dB).
- `key="kick"` ducking: the kick layer must be added FIRST (raises KeyError otherwise).
- `send=` routes into `trk.space()` verbusses.
- `depth` 0 = front, 1 = back.

### Pitfalls

- **Lock files**: `/tmp/autodj-render-{k}.lock` owned by cclaw with /tmp sticky bit → hermes cannot delete or O_CREAT. **Fix**: set `TMPDIR=/home/hermes/.hermes/cache/scratch` env var (the wrapper reads it); the hardcoded /tmp path in lock.py cannot be patched due to perms.
- **SFZ oneshot writes**: always pass explicit `cache_dir` to `sfz.oneshot()` — don't rely on SFZ_ROOT default.
- **Add order**: the layer that ducks to `"kick"` must be trk.add'd AFTER the `"kick"` layer.
- **Glob misses**: open-hat patterns may not match → guard `if K["ohat"] is not None` and `if len(Bf["ohat"])`. HiHat files live in `WA/Cymbals/*HiHat*.wav` — NOT WA/Hihats/. Always verify drum sample globs match reality before rendering.
- **fresh.pick() returns None when worn**: `fresh.pick()` returns `None` when ALL candidates in a folder have been used 10+ times. `load_sample(None, .*)` returns `None` → the layer is silent. Guard hat/ride/perc with `if sample is not None and len(sample)`. Use a fallback: re-call `fresh.pick(candidates, rng, db=None)` to bypass the worn check.
- **Numpy truthiness**: use `len(buf)` not bare `if buf:` for numpy buffer arrays.
- **Gate failures (P146)**: gate fails on silent layers AND on bad sounds (wobble, noise, pitch outside ±7 st). The `allow_silent` / `allow_bad_sounds` META flags are **ignored by the engine** — fix the sounds/layers instead. Exception only with env `AUTODJ_GATE_OVERRIDE=1` + `allow_reason` in META on explicit request. Worn samples (13+ tracks) and repeated drum patterns are warnings, not gate failures.
- **plan.bass() 4-tuples**: `plan.bass()` returns `(step, length, midi, velocity)` — unpack with `for s, l, m, v in bass`. Using 3 vars raises ValueError.
- **SG.pick range or note octave mismatch**: SG.pick validates the sample's `native_midi` against its `lo-hi` range AND against the eventual render MIDI (±7 st). If pad notes are generated at `m-12` (MIDI 38-50) but SG.pick is called with range 50-62, the sample root (~55) is within SG.pick's check but the ACTUAL render happens 5-17 st below it → bad_sounds gate failure. Match the SG.pick lo-hi to the MIDI values you actually pass to `.render()`, not the voicing octave you plan to shift from.
- **Pad depth without `key=` ducks by the clock, not the kick**: `trk.add("pad", ..., depth=.7)` without `key="kick"` makes the duck timing follow a steady clock instead of the actual kick envelope. The engine warns `duck по часам (а не по реальной бочке)`. Add `key="kick"` to pad layers with `depth=` so the sidechain ducking follows kick gaps and breaks. Only layers where clock ducking is intentional (e.g., constant hats) should omit `key`.
- **NumPy seed types**: `np.random.default_rng([seed, val])` requires both `seed` and `val` to be ints. Passing a float (e.g., `mt.time()` return) raises `TypeError: seed must be integer`. Pre-seed one rng at the start and reuse it, or `int()` wrap.
- **Distortion API**: `pedalboard.Distortion(drive_db=float)` is the only parameter. No `hard_clip_db` or other kwargs.
- **Render output**: `out/score.mp3` + `out/score.summary.json`. Exit code 3 = hard gate (silent layers); MP3 still written, `--send` blocked.
- **Max 2 renders per track** (Стас rule). Verify sample paths before rendering.

### User preferences (from docs, Стас rules — violations are regressions)
- Only recorded samples. No synthesizer, no Vital.
- Every layer serves the track. No constant hi-hat/ride/shaker the whole track. No tambourine, no L/R-panning, no "beep" stabs, no PINGPONG/GATE.
- No vocal chops, no vocal samples. Vocals (CHIMERA) only on explicit request. Language: Ukrainian or English. Russian only on request.
- Each track from a clean slate: don't reuse sounds, patterns, or chord progressions from past tracks.
- Author: **StanPo**. Title format: `"Name (style)"`.
- Final judge: Стас's ears. Gemini and Whisper are blind hypotheses.
