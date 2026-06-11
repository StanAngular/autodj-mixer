# AutoDJ Mixer v16.4

**AI-powered DJ mix engine.** Автоматическое сведение треков с использованием нейросетевого структурного анализа (All-in-One Fix), машинного обучения (madmom beat tracking) и профессионального DSP (bar-by-bar warp, LR4 crossover, BPM normalization). Extended transitions 20-60s, A1F Fast default, vocal-heavy auto-switch, mix numbering, YouTube URL catalog, Russian track filter.

Разрабатывается **Hermes** (A1F интеграция, DSP, структурный анализ) + **ClaudeClaw** (warp, pipeline, AI transitions).

---

## Pipeline

Полный конвейер автоматического сведения:

```
Step 0:      A1F Analysis       → all-in-one-fix (Demucs separation + structure)
Step 0.5:    Metadata Enrich    → enrich_metadata.py (yt-dlp + key detection)
Step 1:      Pre-Analyze        → BPM, Camelot, sections, optimal order
Step 1.5:    Preview             → transitions table → user confirms
Step 2:      Mix                → smart_mixer.py (A1F-aware crossfades)
Step 3:      Analyze            → mix_analyzer.py (v3 beat grid + v2 detectors)
Step 4:      Validate           → mix_validator.py (pass/warn/fail)
Step 5:      Upload             → catbox.moe / litterbox (auto)
```

```bash
# Preview only
uv run python3 smart_mixer.py --wav-dir ./shared/tracks --ann-dir ./shared/ann \
  --style "Progressive House" --preview-only

# Full mix with A1F analysis
uv run python3 smart_mixer.py --wav-dir ./shared/tracks --ann-dir ./shared/ann \
  --style "Progressive House" --author "Hermes" --bitrate 320k
```

---

## All-in-One Fix анализ треков (A1F)

**A1F** — это нейросетевой анализ музыкальной структуры через OpenMIRLab All-in-One Fix. Использует Demucs для разделения по стемам + структурный парсер.

### Что собирается о каждом треке

После A1F анализа для каждого трека генерируется **2 файла** в `shared/a1f_results/`:

#### 1. A1F JSON (`[id].json`) — нейросетевой анализ:

| Поле | Тип | Описание |
|------|-----|----------|
| `bpm` | float | Темп в BPM |
| `beats` | float[] | Массив всех долей (в секундах) |
| `downbeats` | float[] | Массив сильных долей (каждый 4-й бит) |
| `beat_positions` | int[] | Позиция каждой доли в такте (1/2/3/4) |
| `segments` | {start, end, label}[] | Сегментная структура: intro, verse, chorus, bridge, inst, outro, break |
| `vocal_intervals` | {start, end, label}[] | Вокальные зоны — verse, chorus, bridge (вычисляются по сегментам) |
| `key` | str | Тональность (librosa chroma CQT + Krumhansl-Schmuckler) |
| `camelot` | str | Camelot код (напр. "6A", "8B") |

#### 2. Meta JSON (`[id].meta.json`) — метаданные:

| Поле | Тип | Описание |
|------|-----|----------|
| `artist` | str | Исполнитель (из yt-dlp) |
| `track_title` | str | Название трека |
| `upload_date` | str | Дата загрузки (YYYYMMDD) |
| `year` | int | Год релиза |
| `tags` | str[] | YouTube-теги |
| `genre` | str | Определённый жанр (House / Techno / Electronic / Melodic / Deep House / Progressive) |
| `description` | str | Описание YouTube (первые 500 символов) |

### Как A1F запускается

```bash
# Полный анализ (Demucs + структура) — для финальных треков
~/ai-tools/all-in-one-fix/venv/bin/python -m allin1fix.cli track.wav \
  -o shared/a1f_results/ --overwrite

# Быстрый анализ (без Demucs) — для черновиков
~/ai-tools/all-in-one-fix/venv/bin/python -m allin1fix.cli track.wav \
  -o shared/a1f_results/ --overwrite --skip-separation
```

- Автоматически запускается `smart_mixer.py` в фоне при первом обнаружении трека без A1F.
- Режим `--analysis-mode a1f_fast` (default): без Demucs, 2-3 мин/трек
- Режим `--analysis-mode a1f`: полный Demucs + full precision, 20-40 мин/трек (авто-включение при vocal_density > 0.5)
- Режим `--analysis-mode no_a1f`: только fallback по тегам

---

## Как собранная информация используется при сведении

### 1. Dynamic CF_BARS — длина кроссфейда по сегментам

Функция `resolve_transition_params()` анализирует сегменты **обоих треков** на стыке:

| Сегмент A (exit) | Сегмент B (entry) | CF_BARS | Smooth EQ | Notch |
|-----------------|-------------------|---------|-----------|-------|
| outro / inst | intro / inst | 16 | да | -3.5 dB |
| outro / inst | любой | 12 | да | -3.5 dB |
| verse / chorus / bridge | intro / inst | 8 | да | -3.0 dB |
| verse / chorus | verse / chorus | 4 | нет (stepped) | -2.0 dB |
| break | chorus / drop | 4 | нет | -2.0 dB |
| любой (no A1F) | fallback | 8 | средне | -3.5 dB |

### 2. Vocal overlap avoidance

Если **оба трека** имеют вокальные зоны рядом со стыком, slave трек сдвигается на безвокальный участок. Используются `vocal_intervals` из A1F JSON.

### 3. Camelot — гармоническое сведение

- Тональность G min (6A) → совместимы 6A, 6B, 5A
- Несовместимые тональности получают longer CF + notch
- Camelot отображается в preview-таблице переходов

### 4. BPM normalization

- A1F BPM — **источник истины** (заменяет madmom BPM)
- BPM Transition: линейный ramp-back 15s после кроссфейда
- Dynamic ramp: <1bpm → skip, 1-3bpm → 30s, 3-8bpm → 15s, >8bpm → 10.5s

### 5. Beat grid синхронизация

- `downbeats` из A1F полностью заменяют madmom downbeats
- Используются для: выбор точек exit/entry, расчёт shift, snap_bar
- Полная сетка `beats` используется для micro-alignment (FFT cross-correlation)

---

## Shared directory structure

Все ресурсы доступны обоим агентам (Hermes + ClaudeClaw) через группу `users`:

```
/opt/autodj-mixer/
├── shared/
│   ├── tracks/          ← WAV-файлы треков (в .gitignore)
│   ├── a1f_results/     ← A1F JSON (анализ) + .meta.json (метаданные)
│   ├── ann/             ← Madmom beat annotations (.txt)
│   └── catalog/         ← catalog_index.json, catalog_utils.py
├── smart_mixer.py       ← Основной миксер
├── enrich_metadata.py   ← Обогащение метаданных (yt-dlp + key)
├── mix_analyzer.py      ← Пост-микс анализ качества
├── SKILL.md             ← Полная документация (canonical source)
└── CHANGELOG.md         ← История изменений
```

---

## Key scripts

| Скрипт | Назначение |
|--------|-----------|
| `smart_mixer.py` | DJ mix engine v16: A1F-aware crossfades, dynamic CF_BARS, EQ Sweep, BPM Transition, Camelot |
| `enrich_metadata.py` | Обогащение: yt-dlp метаданные + тональность + вокальные интервалы |
| `mix_analyzer.py` | Post-mix diagnostics: 10 детекторов качества (v3 madmom + v2 detectors) |
| `mix_validator.py` | Threshold-based validation (pass/warn/fail) |
| `yt_download.py` | YouTube → WAV → madmom annotations (Warp proxy) |
| `batch_annotate.py` | Пакетное аннотирование всех WAV в shared/tracks/ |
| `repaint_transition.py` | AI-переходы через ACE-Step 1.5 Repaint |
| `register_new_tracks.py` | Регистрация новых треков в каталоге |

---

## Quality chain

```
Source WAV (24-bit/44.1kHz PCM)
  → float32 processing (lossless)
  → A1F structural analysis (segments + vocal zones + key)
  → LUFS normalization (-14 LUFS)
  → Bar-by-bar warp + LR4 crossover (float64→float32)
  → EQ Sweep + soft_clipper_tanh
  → -3dB headroom after norm_lufs
  → WAV PCM_24 master (archival quality)
  → MP3 320kbps (final delivery)
```

---

## Configuration

```bash
# CLI flags (smart_mixer.py)
--wav-dir ./shared/tracks    # WAV files
--ann-dir ./shared/ann       # Madmom annotations
--style "Progressive House"  # Genre (auto-filename)
--author "Hermes"            # MP3 artist tag
--bitrate 320k               # MP3 bitrate
--analysis-mode a1f_fast      # a1f_fast (default) / a1f / no_a1f
--cf-bars auto               # Dynamic CF_BARS (default)
--transitions-dir ./transitions  # AI transitions
--preview-only               # Preview mode (no mix)
```

---

## Version history

| Версия | Изменения |
|--------|-----------|
| **v16.4** | Extended transitions (20-60s). A1F Fast default. Vocal-heavy auto-switch to full A1F. Mix numbering (MIX-#). YouTube URL in catalog/metadata. Russian track filter. delete_tracks.py. |
| **v16.3.3** | Shared directory structure (`shared/`) для dual-agent доступа. Все пути → `shared/tracks/`, `shared/a1f_results/`, `shared/ann/`. |
| **v16.3.2** | A1F extended: vocal_intervals, beats, key/camelot. Metadata enrichment: yt-dlp artist, title, year, genre. |
| **v16.3.1** | Camelot integration + vocal overlap avoidance. |
| **v16.3** | Сегментная логика переходов. Dynamic CF_BARS по сегментам A/B. Три режима анализа (a1f/a1f_fast/no_a1f). |
| **v16.2** | Per-track style profiles. A1F bar labels в load_a1f_track_data(). |
| **v15** | DSP overhaul: EQ Sweep HPF/LPF, soft_clipper_tanh, BPM Transition, -3dB headroom, sosfilt. |
| **v14** | CHANGELOG overhaul. 9 artefact detectors. Zone scanning (±15s). fix_ht v4 frozen. |
| **v13** | Seamless blend→ramp. ACE-Step Repaint. Preview step. |
| **v12-v7** | RMS stabilizer, bar-by-bar warp, LR4 crossover. |

---

## License

MIT
