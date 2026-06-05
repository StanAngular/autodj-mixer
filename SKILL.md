---
name: dj-mixer
title: Automated DJ Mix Engine
description: "DJ mix automation: BPM/structure analysis via madmom, bar-aligned crossfades with LR4 bass swap, BPM normalization, mix_analyzer diagnostics, and upload."
triggers:
  - user asks to mix, create mix, DJ mix, automix
  - user says "сделай микс", "склей треки", "смиксуй", "смикшируй", "запусти микс"
  - user mentions mix_analyzer, smart_mixer, run_pipeline, mix_config
  - task involves fixing, debugging, or analyzing a mix
tags: [audio, dj, mixing, production, automation]
---

# DJ Mixer — общий скилл для Hermes и ClaudeClaw

**Source of truth:** этот SKILL.md лежит в корне репозитория (`/opt/autodj-mixer/SKILL.md`). При изменениях кода — обновляй и его. Оба агента читают одну версию.

GitHub: https://github.com/StanAngular/autodj-mixer

---

## Core files (все в `/opt/autodj-mixer/`)

| Файл | Назначение |
|------|-----------|
| `smart_mixer.py` | Миксер: bar-by-bar warp + LR4 3-band + Camelot + RMS stabilizer |
| `mix_analyzer.py` | Анализатор: 8 детекторов качества (v2) |
| `run_pipeline.py` | Конвейер: pre-analyze → mix → analyze → validate → upload |
| `mix_validator.py` | Валидатор: pass/warn/fail по JSON от анализатора |
| `mix_config.py` | Конфиг: список треков + tunable параметры |
| `source_check.py` | Gate 0: проверка WAV перед миксом |
| `track_analyzer.py` | BPM + Camelot сортировка + оптимальные exit/entry |
| `yt_download.py` | YouTube/SC → MP3 → WAV → аннотации одним скриптом |

---

## Pipeline (`run_pipeline.py`)

```bash
cd /opt/autodj-mixer
.venv/bin/python run_pipeline.py \
  --config mix_config.py \
  --style "Hard Techno" \
  --author "Hermes" \
  --feedback \
  --catbox
```

### Флаги

| Флаг | Назначение |
|------|-----------|
| `--config` | Python файл с TRACKS списком (обязательный) |
| `--style` | Жанр (авто-имя файла: `{style}_{date}.mp3`) |
| `--author` | DJ имя (метаданные MP3) |
| `--output` | Путь к выходному файлу (по умолчанию авто) |
| `--feedback` | Генерировать рекомендации по тюнингу |
| `--catbox` | Загрузить на catbox.moe после микса |
| `--strict` | Строгие пороги валидации |
| `--no-validate` | Пропустить шаг валидации |
| `--skip-preanalyze` | Пропустить pre-analysis |
| `--analyze-only` | Только анализ, без микса |

### Шаги pipeline

```
Step 0: Gate 0 — source_check.py (WAV quality)
Step 1: Pre-analysis — track_analyzer.py (BPM + key + sort + optimal exits)
Step 2: Mix — smart_mixer.py
Step 3: Analysis — mix_analyzer.py --feedback
Step 4: Gate — silence check (>2s → FAIL)
Step 5: Gate — artefact check (>200 mixer → WARN)
Step 6: Validate — mix_validator.py (pass/warn/fail verdict)
Step 7: Upload — catbox (если --catbox)
```

---

## Smart Mixer (`smart_mixer.py`)

```bash
.venv/bin/python smart_mixer.py \
  --wav-dir ./tracks \
  --ann-dir ./ann \
  --style "Hard Techno" \
  --author "Hermes" \
  --use-quiet-exit \
  --bitrate 192k
```

### Флаги

| Флаг | Назначение |
|------|-----------|
| `--wav-dir` | Директория с WAV (обязательный без --config) |
| `--ann-dir` | Директория с аннотациями (обязательный без --config) |
| `--config` | Python конфиг с TRACKS |
| `--style` | Жанр (авто-имя файла) |
| `--author` | DJ имя |
| `--bitrate` | MP3 битрейт (дефолт 320k, для Telegram 192k) |
| `--output` | Переопределить путь выхода |
| `--use-quiet-exit` | Выходить на QUIET/BUILD секции |
| `--no-stabilizer` | Отключить RMS stabilizer |

### Core algorithms

- **LR4 3-band crossover** (150Hz / 3000Hz) — бас своп (никаких двух киков одновременно)
- **Bar-by-bar warp** — pyrubberband, устраняет phase drift на 16 барах
- **Downbeat-weighted onset micro-align** (±50ms, FFT cross-correlation)
- **BPM ramp-back** — 15s линейная интерполяция после кроссфейда
- **Seamless blend-to-ramp** — 20ms crossfade между LR4 и ramp (CF_BARS+2 = 17 баров)
- **Bass polarity** — 5-точечный weighted consensus + kick band (60-120Hz)
- **RMS stabilizer** — компенсация bass cancellation dips на LOW band
- **Camelot** — chroma CQT + Krumhansl-Schmuckler
- **Per-bar re-alignment** — 8×2-bar chunks, cumulative drift correction
- **Pre-warp phase alignment** — ±100ms alignment первого downbeat ДО warp
- **Adaptive sub crossfade** — 5 bars для sub band (вместо 16)

### Configurable params (`mix_config.py`)

```python
WAV_DIR = "/opt/autodj-mixer/tracks"
ANN_DIR = "/opt/autodj-mixer/ann"
TARGET_LUFS = -14.0
MAX_SHIFT_SEC = 0.05
# Optional overrides:
# RAMP_SEC = 15.0
# CF_BARS = 16
# HEADROOM_DB = -1.0

TRACKS = [
    ("TrackName", "filename.wav", "filename.txt"),
]
```

---

## Mix Analyzer v2 (`mix_analyzer.py`)

```bash
.venv/bin/python mix_analyzer.py \
  --mix mix.mp3 \
  --config mix_config.py \
  --feedback
```

### Детекторы

| Детектор | Что ловит | Порог |
|----------|-----------|-------|
| **stutter** | PCM repeat (warp glitch) | diff_ratio < 0.001, 20ms windows, 3+ consecutive |
| **hf_noise** | Rubberband high-freq артефакты | 10×median AND -40dBFS (оба обязательны) |
| **speed_glitch** | BPM jump от warp | 20% jump, BPM clamped ±30% median, 30s ramp zone |
| **spectral_discontinuity** | Резкое изменение спектра | 12× median flux |
| **boundary_glitch** | blend→ramp discontinuity | spike > 1.8×, gradient > 5× |
| **beat_irregularity** | IOI anomaly | 50ms windows, IOI ratio >2.0 or <0.4 |
| **band_cancellation** | Phase cancellation в crossfade | dip_ratio < 0.5 (5 bands: 20-60, 60-120, 120-500, 500-2000, 2000-8000Hz) |
| **source_integrity** | Mix vs source spectrum | spectral_deviation > 0.15 |
| **onset_stability** | Beat drift в crossfade | onset_corr < 0.3 в 500ms windows |
| **rms_dip** | Volume drop в crossfade | RMS < 50% local median |

### Формат вывода — группировка по типам событий

```
╔═══ Phase 2: Beat / Timing Anomalies ═══╗
  beat_irregularity @ 04:23.15 — IOI ratio 2.3x
╔═══ Phase 3: Artefact Scan ═══╗
  hf_noise @ 12:45.30 — HF spikes 14x median
```

Вывод всегда с **таймкодами** (`@ MM:SS.FF`). Stamps (`<mix>_stamps.npy`) обязательны для точных таймкодов.

---

## Mix Validator (`mix_validator.py`)

```bash
.venv/bin/python mix_validator.py --json mix_analysis.json
.venv/bin/python mix_validator.py --json mix_analysis.json --strict
```

Exit codes: 0=PASS, 1=WARN, 2=FAIL

Pass thresholds: mixer_high=0, speed_glitch=0, stutter≤2, drift≤10ms, LUFS jump≤3dB

---

## Upload

```bash
curl -s -F "reqtype=fileupload" -F "time=72h" \
  -F "fileToUpload=@mix.mp3" \
  https://litterbox.catbox.moe/resources/internals/api.php
```

Через pipeline: `--catbox`. Битрейт для Telegram — 192kbps.

---

## Импорт треков (YouTube / SoundCloud)

```bash
# yt_download.py — всё в одном: URL → MP3 → WAV → аннотации
.venv/bin/python yt_download.py "https://youtube.com/watch?v=..."

# Warp proxy (VPS блокирует YouTube)
warp-cli --accept-tos disconnect 2>/dev/null; sleep 1
warp-cli --accept-tos connect 2>/dev/null; sleep 3
yt-dlp --proxy socks5://127.0.0.1:40000 "ytsearch:artist track"
```

- **Только последовательно** — параллельные скачивания = блокировка
- **Warp reconnect** между треками (новый IP)
- 10-30% неудач нормально
- Альтернатива: SoundCloud, Discogs (API)

---

## Синхронизация между агентами

### Для Hermes
Перед каждым миксом загружать этот скилл: `skill_view('dj-mixer')` или читать `/opt/autodj-mixer/SKILL.md`. При правках кода — обновлять этот файл и коммитить.

### Для ClaudeClaw
Перед каждым миксом читать `/opt/autodj-mixer/SKILL.md`. Актуальная версия всегда в GitHub.

### Git дисциплина
```bash
# Перед миксом — проверить обновления
cd /opt/autodj-mixer
git fetch origin
git log HEAD..origin/main --oneline
# Если есть — git pull, проверить diff, протестировать

# После изменений — коммитить все связанные файлы вместе
git add smart_mixer.py mix_analyzer.py run_pipeline.py SKILL.md
git commit -m "feat: описание изменения"
git push origin main
```

---

## fix_ht — важное

Используется ТОЛЬКО v1 (оригинал из 1394cba). Восстановление:
```bash
git checkout 1394cba -- smart_mixer.py
```

v4 (b851b12) **РАЗМНОЖАЕТ downbeats** при med~1.95s → ×4 — ломает exit/entry и shift. Проверка перед миксом:
```python
from smart_mixer import load_dbeats, fix_ht, calc_bpm, SR
db = load_dbeats('ann/file.txt', SR)
dbf, bpm = fix_ht(db.copy(), calc_bpm(db, SR))
print(f'{len(db)} → {len(dbf)}')  # должно быть одинаково
```

---

## Результаты

После микса — **обязательно** таблица переходов:

```
# | Time | Transition | BPM | Camelot | Drift | Entry RMS
1 | 00:00-02:05 | track1→track2 | 122→125 | 1A→3B [POOR] | -2.9ms | 0.173
```

Год указывать после названия трека (например `Gamgi_2023`). Camelot: SAME(1.0), ADJ(0.9), REL(0.8), POOR(<0.6).
