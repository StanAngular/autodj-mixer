# AutoDJ Mixer — Техническая документация (v16.4)

> Подробное описание архитектуры движка микширования, всех модулей и пошаговые примеры работы пайплайна от начала до конца.

**Репозиторий:** https://github.com/StanAngular/autodj-mixer
**Главный движок:** `smart_mixer.py` (~2287 строк)
**Авторы:** Hermes (A1F, DSP, структурный анализ) + ClaudeClaw (warp, pipeline, AI-переходы)

---

## Оглавление

1. [Общая архитектура](#1-общая-архитектура)
2. [Жизненный цикл трека (от WAV до микса)](#2-жизненный-цикл-трека)
3. [Модули и скрипты](#3-модули-и-скрипты)
4. [Анатомия smart_mixer.py](#4-анатомия-smart_mixerpy)
5. [Алгоритм перехода — детально](#5-алгоритм-перехода-детально)
6. [DSP-цепочка качества](#6-dsp-цепочка-качества)
7. [Примеры микширования от начала до конца](#7-примеры-микширования)
8. [Форматы данных](#8-форматы-данных)
9. [Параметры и константы](#9-параметры-и-константы)

---

## 1. Общая архитектура

AutoDJ Mixer — это пайплайн автоматического DJ-сведения, который соединяет несколько независимых треков в один непрерывный микс с бесшовными переходами. Система комбинирует три уровня анализа:

```
┌─────────────────────────────────────────────────────────────┐
│  УРОВЕНЬ 1: Нейросетевой анализ (All-in-One-Fix / A1F)        │
│  Demucs separation + структурная сегментация                  │
│  → intro/verse/chorus/bridge/inst/outro/break                 │
├─────────────────────────────────────────────────────────────┤
│  УРОВЕНЬ 2: Machine Learning (madmom)                          │
│  Beat tracking + downbeat detection                           │
│  → точная ритмическая сетка (downbeats в секундах)            │
├─────────────────────────────────────────────────────────────┤
│  УРОВЕНЬ 3: Классический DSP (scipy / pyrubberband / librosa) │
│  Bar-by-bar warp, LR4 crossover, EQ Sweep, key detection      │
│  → физическое сведение аудио                                  │
└─────────────────────────────────────────────────────────────┘
```

**Ключевая идея:** микс собирается как чередование двух типов фрагментов:
- **body** — «тело» трека, играет как есть (от точки входа до точки выхода);
- **crossfade (CF)** — зона перехода, где конец текущего трека (master) сводится с началом следующего (slave).

```
[body A]──[CF A→B]──[body B]──[CF B→C]──[body C]── ... ──[tail Z]
```

Внутри каждой CF-зоны slave-трек растягивается по времени (warp) до точного совпадения с ритмической сеткой master, затем оба трека смешиваются через 3-полосный LR4-кроссовер с подменой баса.

---

## 2. Жизненный цикл трека

От YouTube-ссылки до готового микса трек проходит следующие этапы:

```
YouTube URL
   │
   ▼
┌──────────────────┐
│ yt_download.py   │  yt-dlp через Cloudflare Warp proxy (socks5://127.0.0.1:40000)
│                  │  → MP3 → WAV (24-bit / 44.1 kHz / стерео)
│                  │  → madmom downbeat annotation (.txt)
└──────────────────┘
   │  shared/tracks/[ID].wav + shared/ann/[ID].txt
   ▼
┌──────────────────┐
│ A1F analysis     │  allin1fix.cli → структурная сегментация
│ (allin1fix.cli)  │  → shared/a1f_results/[ID].json
└──────────────────┘
   │
   ▼
┌──────────────────┐
│ enrich_metadata  │  yt-dlp метаданные (artist/title/year/genre/youtube_url)
│ .py              │  + key detection (librosa) + Camelot
│                  │  + vocal_intervals + is_russian filter
│                  │  → shared/a1f_results/[ID].meta.json
└──────────────────┘
   │
   ▼
┌──────────────────┐
│ register_new_    │  Регистрация в каталоге
│ tracks.py        │  → shared/catalog/catalog_index.json
└──────────────────┘
   │
   ▼
┌──────────────────┐
│ smart_mixer.py   │  Микширование (см. раздел 4-5)
└──────────────────┘
   │
   ▼
┌──────────────────┐
│ mix_analyzer.py  │  Пост-микс диагностика (P-score, артефакты)
│ mix_validator.py │  PASS/WARN/FAIL
└──────────────────┘
   │
   ▼
┌──────────────────┐
│ Upload + Report  │  catbox.moe + отчёт с YouTube-ссылками
│ delete_tracks.py │  Опционально: удалить исходные треки
└──────────────────┘
```

---

## 3. Модули и скрипты

### Основные скрипты

| Скрипт | Назначение | Строк |
|--------|-----------|-------|
| `smart_mixer.py` | Главный движок: warp, crossfade, EQ, сборка | ~2287 |
| `mix_analyzer.py` | Пост-микс анализ: beat grid + 9 детекторов артефактов | ~1037 |
| `run_pipeline.py` | Оркестратор: pre-flight → mix → upload → preview | ~288 |
| `enrich_metadata.py` | Обогащение метаданных: yt-dlp + key + Camelot | ~240 |
| `yt_download.py` | YouTube → WAV → annotations через Warp proxy | ~195 |
| `mix_validator.py` | Threshold-based валидация (PASS/WARN/FAIL) | — |
| `repaint_transition.py` | AI-переходы через ACE-Step Repaint | — |
| `register_new_tracks.py` | Регистрация треков в каталоге | ~35 |
| `batch_annotate.py` | Пакетное аннотирование всех WAV | — |

### Каталог (`shared/catalog/`)

| Файл | Назначение |
|------|-----------|
| `catalog_index.json` | Индекс всех треков: BPM, структура, youtube_url |
| `catalog_utils.py` | `lookup_track()`, `add_to_catalog()`, `list_all()` |
| `update_catalog.py` | Пересборка индекса |
| `delete_tracks.py` | Интерактивное удаление треков (WAV + ANN + A1F + индекс) |

### Структура общих данных (`shared/`)

```
/opt/autodj-mixer/shared/
├── tracks/          # WAV-файлы (24-bit/44.1kHz), в .gitignore
├── ann/             # Madmom downbeat-аннотации (.txt, время в секундах)
├── a1f_results/     # A1F JSON (структура) + .meta.json (метаданные)
└── catalog/         # Индекс + утилиты
```

Группа `users` (права 775) — доступ обоим агентам (Hermes + ClaudeClaw).

---

## 4. Анатомия smart_mixer.py

Движок состоит из ~45 функций, сгруппированных по назначению.

### 4.1. Метаданные и определение жанра

| Функция | Что делает |
|---------|-----------|
| `search_track_genre(artist, title)` | Определяет vocal_hint/density по ключевым словам (fallback без A1F) |
| `load_a1f_track_data(wav_path, sr)` | Загружает A1F JSON: bpm, downbeats, segments, bar_labels, vocal_density |
| `run_a1f_analysis(wav_path, cache_dir)` | Фоновый запуск allin1fix.cli для треков без JSON |

### 4.2. Тональность и гармония (Camelot)

| Функция | Что делает |
|---------|-----------|
| `detect_key(audio_mono, sr)` | Определяет тональность через chroma CQT + Krumhansl-Schmuckler профили |
| `camelot_code(key_str)` | Переводит "G min" → "6A" (Camelot-код) |
| `key_compat(k1, k2)` | Совместимость тональностей: 1.0=SAME, 0.9=ADJ, 0.8=REL, <0.6=POOR |

### 4.3. Загрузка и анализ ритма

| Функция | Что делает |
|---------|-----------|
| `load_stereo(path, sr)` | Загружает WAV в стерео float |
| `load_dbeats(ann_path, sr)` | Загружает downbeat-аннотацию (время в секундах → сэмплы) |
| `calc_bpm(db, sr)` | BPM из интервалов между downbeats (IQR-фильтрация выбросов) |
| `fix_ht(db, bpm)` | **v4** — исправляет half-time/double-time детекцию по ratio |
| `bar_s(bpm)` | Длина одного такта в секундах = 4·60/bpm |

### 4.4. Структурный анализ

| Функция | Что делает |
|---------|-----------|
| `sections(audio, db, sr)` | Классифицирует такты: QUIET/BUILD/ACTIVE/DROP по RMS+bass ratio |
| `quiet_exit(secs)` | Находит тихую секцию для выхода |
| `section_at_bar(secs, bar)` | Возвращает метку секции для такта |
| `snap_bar(bar, grid=4)` | Привязка к фразовой сетке (кратно 4 тактам) |
| `best_exit_bar_v2(...)` | Выбор оптимального такта выхода по A1F + HYBRID_SCORE |
| `resolve_transition_params(...)` | **Резолвер DSP-параметров** перехода по пересечению A1F-сегментов |
| `resolve_cf_bars(...)` | Длина кроссфейда (auto/manual) |

### 4.5. Time-stretching (warp)

| Функция | Что делает |
|---------|-----------|
| `warp_to_grid(slave, s_db, m_db, sr)` | **Bar-by-bar warp** — растягивает каждый такт slave под такт master |
| `ramp_to_native(slave, ...)` | Плавный возврат slave к родному BPM после кроссфейда |
| `dynamic_loop(audio, ...)` | Тайлинг короткого интро до нужной длины |
| `onset_micro_align(...)` | Микро-выравнивание ±50ms по onset cross-correlation |

### 4.6. DSP-фильтры

| Функция | Что делает |
|---------|-----------|
| `find_crossover(audio_m, audio_s)` | Динамический подбор частот раздела полос (kick fundamental + vocal gap) |
| `three_band_split(audio, low, high)` | Разделение на low/mid/high через IIR SOS |
| `eq_sweep(audio, ...)` | Плавный HPF/LPF свип (20→150 Hz) для подмены баса |
| `vocal_notch_sweep(audio, ...)` | Bell-фильтр -3..-6 dB на 1-4 kHz при вокальном конфликте |
| `soft_clipper_tanh(audio, 0.707)` | Мягкий tanh-клиппер (-3 dB headroom) |
| `norm_lufs(audio, -14)` | Нормализация громкости к -14 LUFS |
| `rms_stabilizer_lookahead(...)` | Подавление RMS-провалов в зоне кроссфейда |

### 4.7. Сборка кроссфейда

| Функция | Что делает |
|---------|-----------|
| `build_cf_lr4(...)` | **Главная функция кроссфейда** — warp + micro-align + LR4 bass swap |
| `vocal_per_bar(audio, db, sr)` | Per-bar VAD (детект вокала по ZCR + spectral ratio) |
| `drum_activity(segment, sr)` | Детект барабанов в сегменте (для drum check) |

### 4.8. Главная функция

```python
mix_tracks(tracks, wav_dir, ann_dir, output_mp3, ...,
           cf_bars='auto', analysis_mode='a1f_fast')
```

Это точка входа. Делает: загрузку всех треков → анализ → построение микса по цепочке переходов → экспорт WAV/MP3 → сохранение stamps для анализатора.

---

## 5. Алгоритм перехода — детально

Для каждой пары соседних треков (master → slave) выполняется:

### Шаг 1 — Проверка BPM-разницы
```python
diff = abs(slave_bpm - master_bpm) / master_bpm
if diff > BPM_DIFF_LIMIT (0.08):   # > 8%
    → ЖЁСТКИЙ СРЕЗ (hard cut), без кроссфейда
```

### Шаг 2 — Определение точки выхода (master)
- `best_exit_bar_v2()` ищет такт выхода, учитывая:
  - A1F-метки (предпочтение outro/inst/break)
  - RMS-энергию (`HYBRID_SCORE`: outro+QUIET=хорошо, inst+DROP=плохо)
  - запрет выхода раньше `MIN_PLAY_FRACTION` (70% трека)
- `snap_bar()` привязывает к фразовой сетке (кратно 4)

### Шаг 3 — Резолвинг DSP-параметров
`resolve_transition_params()` по пересечению A1F-сегментов:

| Master (exit) | Slave (entry) | CF_BARS | Smooth EQ | Notch |
|---------------|---------------|---------|-----------|-------|
| outro/end | intro/inst/start | **32** | да | -3.5 dB |
| outro/break | verse/bridge | **24** | да | -5.0 dB |
| любой | chorus/verse/bridge | 4 | нет (срез) | -5.0 dB |
| chorus/verse → intro | — | 4 | нет | -5.0 dB |
| **default (A1F)** | — | **24** | да | -3.0 dB |

> v16.4: расширены до 32/24/24 такта (20-60 секунд).

### Шаг 4 — Energy cap (защита от долгих переходов на пике)
```python
если оба (exit и entry) в ACTIVE/DROP → cf_bars = min(cf_bars, 4)
если один в ACTIVE/DROP            → cf_bars = min(cf_bars, 8)
```

### Шаг 5 — Drum check + auto-loop (slave)
- Проверка наличия барабанов в точке входа slave (`drum_activity`)
- Если барабанов нет (`drum_ratio < 0.15`) → поиск вперёд до 32 тактов
- Если не найдено → **Ambient Blend fallback**: quiet-режим, 16 тактов
- Короткое интро (2-8 тактов) с барабанами → `dynamic_loop()` тайлинг

### Шаг 6 — Vocal clash detection
```python
если у master И slave есть вокал в зоне CF:
    → vocal_clash=True → vocal_notch_sweep дакает мид master (-3..-6 dB)
```

### Шаг 7 — Построение кроссфейда (`build_cf_lr4`)
1. **Warp**: каждый такт slave растягивается под такт master (`warp_to_grid`)
   - если ΔBPM > 5% → **BPM Transition**: наоборот, master варпится к сетке slave
2. **Micro-align**: остаточный сдвиг ±50ms по onset cross-correlation
3. **LR4 3-band split**: динамический кроссовер low/mid/high
4. **Bass swap**: бас переключается, mid/high — equal-power crossfade
5. **Bass polarity check**: проверка фазы по 5 точкам (защита от отмены)

### Шаг 8 — BPM ramp-back
После кроссфейда slave играет на BPM master. `ramp_to_native()` плавно возвращает его к родному BPM за `RAMP_SEC` (25s):
- ΔBPM < 2 → пропуск
- entry_rms < 0.08 → простой volume fade
- иначе → постепенное изменение длины такта

### Шаг 9 — Seamless blend→ramp boundary
20ms микро-кроссфейд между LR4-зоной и ramp-зоной (warp_extra — сохранённый 17-й такт).

---

## 6. DSP-цепочка качества

```
Source WAV (24-bit / 44.1 kHz PCM)
   │
   ▼ float64 processing (без потерь)
   │
   ▼ A1F structural analysis (segments + vocal zones + key)
   │
   ▼ LUFS normalization (-14 LUFS)
   │
   ▼ Hard peak clamp -3 dB (0.707) — запас под переходы
   │
   ▼ Bar-by-bar warp (pyrubberband, rate > 0.002)
   │
   ▼ LR4 crossover (scipy IIR SOS, minimum-phase)
   │
   ▼ EQ Sweep (HPF/LPF) + Vocal Notch Sweep
   │
   ▼ RMS Stabilizer (lookahead)
   │
   ▼ soft_clipper_tanh (threshold 0.707)
   │
   ▼ WAV PCM_24 master (архивное качество)
   │
   ▼ MP3 320 kbps (финальная доставка)
```

**Принципы:**
- Все треки нормализуются к -14 LUFS при загрузке (не per-CF — это вызывало pumping)
- Жёсткий клиппинг на 0.707 (-3 dB) оставляет запас под суммирование в переходах
- IIR SOS вместо filtfilt — нет pre-ringing
- Equal-power кроссфейд сохраняет общую энергию

---

## 7. Примеры микширования

### Пример A — Чистый инструментальный переход (Organic House)

**Дано:** Track1 (118 BPM, 6A, outro) → Track2 (120 BPM, 7A, intro)

```
1. BPM diff = |120-118|/118 = 1.7%  →  OK (< 8%)

2. Exit point (Track1):
   best_exit_bar_v2 находит outro-секцию на такте 96 из 128
   (96 > MIN_PLAY 70% = 90 ✓)
   snap_bar(96) = 96 (уже кратно 4)
   → exit @ bar 96, label='outro'

3. resolve_transition_params('outro', 'intro'):
   → cf_bars=32, smooth_eq=True, notch_db=-3.5
   (~32 такта × 2.0s = 64s... но capped по длине трека → 30 тактов)

4. Energy cap: outro=QUIET, intro=QUIET → нет кэпа

5. Drum check (Track2 intro):
   drum_ratio = 0.08 < 0.15  →  нет барабанов!
   Поиск вперёд: на такте 8 drum_ratio=0.22 ✓
   → s_entry = bar 8 (inst с барабанами)

6. Vocal clash: оба инструментальные → vocal_clash=False

7. build_cf_lr4 (cf_bars=30):
   - warp_to_grid: 30 тактов Track2 растянуты с rate≈0.983 (118/120)
   - micro-align: shift = +12ms
   - find_crossover: low=145Hz, high=2800Hz
   - LR4 split + bass swap (полярность OK по 5 точкам)
   → blended (30 тактов плавного перехода)

8. BPM ramp-back:
   ΔBPM=2.0 → ramp_to_native: 118→120 за 25s (12 тактов)

9. Seamless boundary: warp_extra присутствует → 20ms crossfade
```

**Результат:** длинный плавный 60-секундный переход outro→inst, бас переключается чисто, без вокальных конфликтов. Идеально для organic house.

---

### Пример B — Вокальный трек с авто-переключением A1F (v16.4)

**Дано:** запуск с `--analysis-mode a1f_fast`, Track = Dua Lipa – Levitating

```
1. Загрузка a1f_fast (без Demucs):
   vocal_per_bar() считает vocal_density = 0.88

2. Vocal-heavy auto-detection (v16.4):
   track_vocal_density (0.88) > 0.5 AND mode == 'a1f_fast'
   → 🎤 "Vocal-heavy track detected"
   → Запуск полного A1F (БЕЗ --skip-separation) в фоне
   → Demucs separation для точного определения вокальных зон
   (результат будет доступен на следующем запуске)

3. Текущий микс использует VAD vocal_intervals,
   следующий запуск получит точные A1F-сегменты с Demucs

→ Вокальные зоны определяются точнее, защита от наложения вокала работает
```

**Результат:** система сама понимает, что вокальный трек требует более точного анализа, и догружает полный A1F без вмешательства пользователя.

---

### Пример C — Жёсткий срез при большой разнице BPM

**Дано:** Track1 (103 BPM, downtempo) → Track2 (128 BPM, house)

```
1. BPM diff = |128-103|/103 = 24.3%  →  > 8% !!!

2. → ЖЁСТКИЙ СРЕЗ (hard cut)
   body = Track1[cur_off:]  (весь остаток играет до конца)
   parts.append(body)
   → переход к Track2 без кроссфейда, на фразовой границе

(никакой warp, никакой LR4 — резкая смена)
```

**Результат:** при слишком большой разнице темпа кроссфейд звучал бы неестественно (трек пришлось бы растянуть на 24%, появились бы артефакты). Система делает чистый срез на сильной доле.

---

### Пример D — Полный пайплайн с нуля (run_pipeline.py)

**Команда:**
```bash
cd /opt/autodj-mixer
.venv/bin/python run_pipeline.py \
  --wav-dir shared/tracks \
  --ann-dir shared/ann \
  --config mix_config_organic.py \
  --style "Organic House" \
  --analysis-mode a1f_fast
```

**Что происходит:**
```
═══════════════════════════════════
  AutoDJ Pipeline v1
  Style: Organic House
  Mode: a1f_fast
═══════════════════════════════════

🔍 Pre-flight check...
  - Проверка пар WAV/ann
  - Формат аннотаций (время в секундах, не сэмплы!)
  - BPM sanity (разброс < 15%)
  - A1F: 8 ready, 2 missing
  ✓ All annotations valid

🎯 Mix #7              ← нумерация миксов (v16.4)

🎛 Running mix...
  → smart_mixer.py --analysis-mode a1f_fast
  → Загрузка 8 треков, анализ BPM/key/structure
  → Camelot Wheel Overview
  → Построение 7 переходов
  ✅ Mix done in 142s
  Output: MIX-7_Organic_House_20260611.mp3

📤 Uploading mix...
  📤 Catbox: https://litterbox.catbox.moe/abc123.mp3

🎬 Creating transitions preview...
  → нарезка зон переходов (±5s)
  → preview.mp3 на catbox

═══════════════════════════════════
  ✅ Pipeline complete
═══════════════════════════════════
```

После завершения — отчёт с YouTube-ссылками + вопрос об удалении треков.

---

## 8. Форматы данных

### A1F JSON (`shared/a1f_results/[ID].json`)
```json
{
  "bpm": 120.0,
  "beats": [0.5, 1.0, 1.5, ...],
  "downbeats": [0.5, 2.5, 4.5, ...],
  "beat_positions": [1, 2, 3, 4, 1, ...],
  "segments": [
    {"start": 0.0, "end": 16.0, "label": "intro"},
    {"start": 16.0, "end": 48.0, "label": "verse"},
    ...
  ],
  "vocal_intervals": [{"start": 16.0, "end": 48.0, "label": "verse"}],
  "key": "G min",
  "camelot": "6A"
}
```

### Meta JSON (`shared/a1f_results/[ID].meta.json`)
```json
{
  "artist": "Lane 8",
  "track_title": "Brightest Lights",
  "upload_date": "20250312",
  "year": 2025,
  "tags": ["organic house", "melodic"],
  "genre": "House",
  "youtube_url": "https://www.youtube.com/watch?v=ID",
  "is_russian": false,
  "description": "..."
}
```

### Annotation (`shared/ann/[ID].txt`)
```
0.050000 1      ← время (сек) + позиция в такте (1=downbeat)
0.510000 2
0.970000 3
1.430000 4
1.890000 1
```
> **Важно:** время в СЕКУНДАХ, не сэмплы. Sample-based формат вызывает каскадные ошибки.

### Stamps (`[output]_stamps.npy`)
```python
{'from': 'Lane 8', 'to': 'Yotto',
 'from_key': '6A', 'to_key': '7A', 'key_compat': 0.9,
 't': 154.2, 'dur': 30.0, 'mode': 'hpss',
 'shift': 0.012, 'entry_rms': 0.15}
```

---

## 9. Параметры и константы

### Глобальные константы (smart_mixer.py)
```python
SR = 44100                  # частота дискретизации
CF_BARS = 24                # длина кроссфейда по умолчанию (v16.4)
RAMP_SEC = 25               # BPM ramp-back (v16.4)
RAMP_MIN_RMS = 0.08         # порог для volume fade вместо BPM ramp
TARGET_LUFS = -14.0         # целевая громкость
BPM_DIFF_LIMIT = 0.08       # порог жёсткого среза (8%)
PHRASE_GRID = 4             # фразовая сетка (4 такта)
MIN_PLAY_FRACTION = 0.70    # минимум 70% трека до выхода
DRUM_SEARCH_LIMIT = 32      # макс. поиск барабанов вперёд
```

### CLI-аргументы smart_mixer.py
```bash
--wav-dir DIR           # WAV-файлы (обязательно)
--ann-dir DIR           # Madmom аннотации (обязательно)
--output FILE.mp3       # выходной файл
--style "Genre"         # жанр (в метаданные)
--author "Name"         # автор (в метаданные)
--bitrate 320k          # битрейт MP3
--config FILE.py        # конфиг с TRACKS списком
--cf-bars auto          # длина кроссфейда (auto/int)
--analysis-mode a1f_fast  # a1f / a1f_fast (default) / no_a1f
--use-quiet-exit        # выход на QUIET/BUILD секции
--no-stabilizer         # отключить RMS-стабилизатор
--transitions-dir DIR   # AI-переходы (ACE-Step)
```

### Режимы анализа
| Режим | Demucs | Скорость | Когда |
|-------|--------|----------|-------|
| `a1f` | да | ~20 мин/трек | вокальные/сложные |
| `a1f_fast` | нет (skip-separation) | ~2-3 мин/трек | **default**, ~80% миксов |
| `no_a1f` | нет (только madmom+keyword) | мгновенно | черновики |

> **v16.4:** `a1f_fast` авто-апгрейдится до полного `a1f`, если `vocal_density > 0.5`.

---

## Известные подводные камни

1. **norm_lufs headroom** — `if pk > 0.707` периодически откатывается к `0.99`. Проверять `grep 'if pk >' smart_mixer.py` перед каждым миксом.
2. **Annotation format** — время в секундах, не сэмплы. Проверка: `head -1 ann/ID.txt`.
3. **Demucs 4-stem** — A1F требует все 4 стема (bass/drums/other/vocals). НЕ использовать `--two-stems`.
4. **Warp reconnect** — между YouTube-загрузками обязательно `warp-cli disconnect/connect`.
5. **Sequential downloads** — параллельные загрузки = бан YouTube.
6. **git pull перед миксом** — оба агента работают с одним репозиторием.
7. **Never rewrite analyzer** — только добавлять поверх v3+v2 hybrid.

---

*Документ актуален для v16.4 (2026-06-11). Канонический источник: `/opt/autodj-mixer/SKILL.md`*
