# Changelog — autodj-mixer

Формат: `[YYYY-MM-DD HH:MM] [Agent] [Категория] описание | причина`

Категории:
- `[fix_ht]` — изменения логики исправления half-time аннотаций
- `[warp]` — изменения в bar-by-bar warping / временном растяжении
- `[mixer]` — изменения в основном процессе сведения
- `[analyzer]` — изменения в mix_analyzer
- `[pipeline]` — run_pipeline, config, scripts
- `[infra]` — структура репозитория, пути, permissions

## v16.5 — 2026-06-12 [Hermes] Style-based Fallback + 24dB/oct HPF + Artifact Analysis Pipeline

### [mixer] — Removed keyword-based genre guessing, proper 20-60s transitions
  • **Removed keyword-based genre detection from fallback** — больше не ищем 'house'/'techno' в названии трека. Стиль известен из --style, fallback использует 24 bars (~45s) всегда.
  • **Minimum cf_bars raised:** 4→8, 8→12/16 bars — все переходы теперь 20-60s, avg 30-40s, несколько 50-60s
  • **24dB/oct HPF→LPF на EQ Sweep** — замена 12dB/oct на 24dB/oct. Круче срез = меньше фазового перекрытия = меньше band_cancellation артефактов ("эХА" звук)
  • **smooth_eq=True для всех режимов** — убран False в коротких переходах для плавности

### [pipeline] — Post-mix artifact analysis step added
  • **mix_analyzer --feedback** обязателен после каждого микса
  • **band_cancellation check** — если > 300 ивентов → WARN, диагностика

### [pipeline] — New DJ AGENT report template (per user specs)
  • DJ AGENT format: трек-лист + сетка сведения + техстэк + диггерский лог + sound prompt
  • Переходы с ⏱ таймкодами и техникой сведения
  • YouTube ссылки к каждому треку

### [mixer] — A1F fast default, vocal-heavy auto-switch, extended transitions
  • **Default analysis-mode changed to `a1f_fast`** — skip-Demucs mode for speed (~2-3 min/track), saves ~300k tokens vs full a1f
  • **Vocal-heavy auto-detection** — if track_vocal_density > 0.5 AND mode is a1f_fast, automatically launches full A1F (with Demucs) in background for vocal precision
  • **Extended transitions 20-60s** — CF_BARS=24 default, RAMP_SEC=25, transition rules increased:
    - `outro→intro/inst` → **32 bars** (~60s @ 128 BPM)
    - `outro/break→verse/bridge` → **24 bars** (~45s)
    - Default A1F → **24 bars** (~45s)

### [pipeline] — Mix numbering, YouTube URL in catalog, Russian filter
  • **Mix numbering** — each mix gets a sequential number (`MIX-#_Style_Date.mp3`), stored in `.mix_counter`
  • **YouTube URL in metadata** — `enrich_metadata.py` now saves `youtube_url` per track in meta.json
  • **YouTube URL in catalog** — `catalog_utils.add_to_catalog()` accepts `youtube_url` parameter
  • **delete_tracks.py** — NEW interactive script to delete tracks by ID with auto-recovery (catalog + WAV + ANN + A1F)
  • **Russian track filter** — `enrich_metadata.py` detects Russian tracks (keywords: русский, москва, россия, etc.) and flags them via `is_russian` field
  • **Report template** — `mix_validator.py` updated with YouTube links section placeholder

## v16.3.3 — 2026-06-09 [Hermes] [infra] Shared directory structure

  • **`/opt/autodj-mixer/shared/`** — создана единая shared-папка с группой `users` для доступа обоих агентов (Hermes + ClaudeClaw)
  • **`shared/tracks/`** — 11 WAV треков перенесены из `tracks/` сюда
  • **`shared/a1f_results/`** — 22 A1F JSON + meta.json перенесены из `track_catalog/a1f_results/` сюда
  • **`shared/ann/`** — 34 madmom-аннотации скопированы из `ann/` сюда
  • **`shared/catalog/`** — catalog_index.json, catalog_utils.py, update_catalog.py перенесены из `track_catalog/` сюда
  • **Все скрипты обновлены:** smart_mixer.py, enrich_metadata.py, yt_download.py, batch_annotate.py, register_new_tracks.py, repaint_transition.py, mix_config*.py — пути заменены на `shared/`
  • **SKILL.md** — обновлён: секция `shared/`, все примеры команд

---

## 2026-06-03

### [fix_ht] Hermes
**commit 6b6bb04** — fix_ht: beat-level thresholds + фильтр шума

Проблема: версия Claw (99691b3) использовала медианный интервал с порогами для **bar-level** (1–4s). На треках где downbeat-аннотации идут каждый бит (med=0.5s) это приводило к decimate — выбрасывался каждый второй downbeat.

Решение: заменить пороги на beat-level (0.25–1.0s). med < 0.25 → quarter-beat (×4), 0.25–0.65 → half-beat (×2), 0.65–1.0 → correct (не трогать), >1.3 → insert midpoint.

Также починил noise filter в calc_bpm: `iv > 0.1` вместо `iv > 0.3` — чтобы 210 BPM hardcore (0.286s) не фильтровался.

---

### [fix_ht] Hermes
**commit 4563223** — fix_ht: ratio approach

Проблема: beat-level пороги всё ещё не работали для некоторых треков из-за способа расчёта ratio.

Решение: считать ratio как len(db) / (db[-1]-db[0]) / 4 * sr, сравнивать с ожидаемым 1-бит-интервалом. Если ratio ≈ 0.5 → double-time (decimate). Если ratio ≈ 2 → half-time (insert midpoints).

Для pop (100 BPM, med=0.6) ratio ≈ 1.0 → correct.

---

### [fix_ht] → [warp] Hermes
**commit 3df33a2** — три фикса:

**1. micro-align shift slice bug [bug]**
Проблема: `s_zone[:-int(shift)]` при отрицательном shift (ускорение, сэмплы нужно убрать в начале) превращался в `s_zone[:896]` — брал первые 0.02с кроссфейда вместо «все сэмплы кроме последних 896». Из-за этого 3-полосный LR4 crossfader вставлял шум/щелчок на каждом переходе с растяжением >1x.
Фикс: `s_zone[:s_len - pad]` вместо `s_zone[:-int(shift)]`.

**2. fix_ht: return musical BPM [fix_ht]**
Проблема: fix_ht возвращал beat-level BPM (508 вместо 127) для half-time аннотаций. Это ломало bar_s(), который считал 1 бит = 1 бар → кроссфейд длиной 4 сэмпла.
Фикс: делить BPM на 4 при срабатывании half-time детекции.

**3. librosa key detection вместо essentia [mixer]**
Проблема: essentia KeyExtractor не устанавливался, API не совпадал.
Решение: встроить chroma CQT + Krumhansl-Schmuckler прямо в smart_mixer.py.

---

### [analyzer] Hermes
**mix_analyzer.py** — создан и закоммичен. Анализирует 5 фаз: source, transition, artefact scan, source vs mixer cross-reference, feedback generation.

Известный баг: local BPM tracker в detect_mix_artefacts() выдаёт ложные speed_glitch в зонах BPM ramp-back (намеренное замедление, не глюк). Нужно подавлять 15s после кроссфейда.

---

## 2026-06-02

### [infra] ClaudeClaw
Установлены CI, pytest, тесты (34 unit + integration). rubberband-cli, Cython, madmom build deps. mix_validator.py — auto-validation pipeline.

### [fix_ht] ClaudeClaw
**commit 99691b3** — fix_ht: median-based absolute timing.
Первая попытка заменить хардкод `db[4:8]` на универсальное решение. Не учтено, что аннотации могут быть beat-level — вызвало регрессию.

### [fix_ht] ClaudeClaw
**commit 859dd98** — старая fix_ht с db[4:8].
Работала для 6 треков Stas (pop/house, 117-130 BPM). Ломалась для коротких треков (<4 downbeats → ratio≈0 → full decimate) и для hardcore 210 BPM.

### [infra] Hermes — 2026-06-03 13:32: создан CHANGELOG.md + log_change.sh | причина: оба агента пишут изменения в одном месте

### [infra] Hermes — 2026-06-03 14:07: коммит 3df33a2 запушен на GitHub | причина: новый токен

### [mixer] Hermes — 2026-06-03 19:26: config-driven params + --quick-test флаг | причина: сокращение токенов: правки через config вместо чтения 900 строк кода

### [pipeline] ClaudeClaw — 2026-06-03: mix_config.py -- документированы tunable params | причина: TARGET_LUFS/MAX_SHIFT_SEC уже читаются из config (коммит d19c6c6) но не были явно в файле -- добавил с дефолтными значениями + закомментированные RAMP_SEC/CF_BARS/HEADROOM_DB

### [infra] ClaudeClaw — 2026-06-03: smart_mixer.py синхронизирован в ~/.claude/skills/mixer/ | причина: скилл теперь использует /opt/autodj-mixer/ код (коммит d19c6c6 Hermes)

### [infra] ClaudeClaw — 2026-06-03: /opt/autodj-mixer permissions fixed | причина: root выполнил chown -R root:users + chmod -R g+w на весь каталог. Оба агента (cclaw + hermes) теперь могут git push напрямую из /opt/. Workaround через /tmp/autodj-push больше не нужен

### [skill] ClaudeClaw — 2026-06-03: music_tracklist_builder v1.2 | причина: додав стратегії пошуку як у діджеїв (1001tracklists, Shazam у сетах, Bandcamp fans also bought, критерії якості), розширив лейбли (Afterlife, Innervisions, Prologue і ін.), топ DJ-референси по жанрах, changelog скіла
### [analyzer] Hermes — 2026-06-04 08:59
mix_analyzer.py v2 — полная переработка:
  • Стуттер: разностный метод (diff_ratio < 0.001) вместо корр. 20ms окна — 0 ложных
  • HF noise: двойной порог (10x median AND -40dBFS abs) — 0 ложных (было 372)
  • Speed glitch: BPM clamped к ±30% медианы, зона рампа 30с — 4 события (было 30)
  • Spectral discontinuity: 12x median (было 5x)
  • Beat drift: замер IOI на master-only секции до перехода, нормализация ритм. уровня
  • Band cancellation: по-полосный анализ dips в зоне кроссфейда (5 bands: 20-60..2000-8000Hz)
  • Source integrity: сравнение спектра mix vs source на соло-секциях до/после перехода
  • Группировка вывода по типам событий вместо списка всех подряд

### [mixer] Hermes — 2026-06-04 10:34
smart_mixer.py — fixes from v2 analyzer findings:
  • blend→ramp boundary: 10ms crossfade между warp_extra и ramp_result
    (раньше был np.concatenate — жёсткая склейка давала 5 микрозапинов)
  • Bass polarity: 5-точечный weighted consensus (была 1 точка в центре)
  • Kick band (60-120Hz) отдельная проверка polarity

### [analyzer] Hermes — 2026-06-04 10:34
  • boundary_glitch: spike > 1.8x, gradient > 5x (было 1.5 и 3)
  • stutter: diff_ratio < 0.001, 20ms windows, 3+ consecutive
  • threshold tweaks for v2 stability

### [warp] Hermes — 2026-06-04 12:42
smart_mixer.py:
  • Per-bar re-align: 8×2-bar chunks (было 4×4-bar), порог 0.2ms (был 0.5ms)
    — ловит постепенный cumulative drift (~35-64ms на 16-bar кроссфейде)
  • warp_to_grid: сглаживание master bar lengths (clamp ±25% от median)
    — защита от выбросов в madmom аннотациях

### [mixer] Hermes — 2026-06-04 13:42
smart_mixer.py — fixes from v2 analyzer findings:
  • blend→ramp boundary: 10ms crossfade между warp_extra и ramp_result
    (раньше был np.concatenate — жёсткая склейка давала 5 микрозапинов)
  • Bass polarity: 5-точечный weighted consensus (была 1 точка в центре)
  • Kick band (60-120Hz) отдельная проверка polarity

### [analyzer] Hermes — 2026-06-04 13:42
  • boundary_glitch: spike > 1.8x, gradient > 5x (было 1.5 и 3)
  • stutter: diff_ratio < 0.001, 20ms windows, 3+ consecutive
  • threshold tweaks for v2 stability


### [mixer] Hermes — 2026-06-04 14:00 — alignment fix: 3 бага в build_cf_lr4()
  1. Pre-warp phase alignment (новый):
     onset_micro_align на первые 2 бара ДО warp с окном 100ms
     — ловит большие смещения первого даунбита (переход 1: -98.7ms!)
  2. Chunk 0 в per-bar re-alignment:
     range(1, n_chunks) пропускал первые 2 бара — баг
     range(0, n_chunks) — теперь все 8 чанков корректируются
  3. Warp_extra bridge всегда был None:
     CF_BARS+1 downbeats = CF_BARS bars = cf_len → warp_extra пуст
     Fix: CF_BARS+2 → 17 bars → реальный 1-bar bridge
  Результат: blend→ramp seamless True на всех переходах, начало сведений фазово выровнено

## 2026-06-06..08

### [analyzer] Hermes
**mix_analyzer v3** — полный рефакторинг (d05b76b)
  • Вместо детекции onset на mix-аудио — использует **pre-computed madmom аннотации**
  • Beat-level grid (все 4 доли, не только downbeats) из последних 32 битов до CF
  • Экстраполяция grid в зону кроссфейда, сравнение с реальными onsets
  • std 88-110ms (было 400ms), BPM 124-128 (было 496)
  • Beat alignment: 5/7 pass (было 3/7)
  • CMLc, Cemgil, P-score метрики добавлены (1627410)

### [pipeline] Hermes
  • **track_analyzer.py** — пре-анализ треков (BPM, key, Camelot, секции), сортировка, вывод optimized_config.py (8a111fc)
  • **genre_detector.py** + genre profiles (hard_techno, afro_house, jazz_downtempo) — авто-стиль по BPM + спектру (ab54939, f9e1a71)
  • **run_pipeline.py** — preview step перед финальным миксом (fdf82d9)
  • **mix_validator.py** — auto-validation с порогами качества (859dd98)
  • **batch_annotate.py** — массовая генерация аннотаций (8a111fc)

### [dl] Hermes
  • **yt_download.py** — скачивание с ютуба через Warp proxy, конверт MP3→WAV, madmom downbeat-аннотации (57c107c)
  • `--yt-urls` — интеграция Warp-скачки прямо в mixer (88c1757)
  *В CHANGELOG до этого момента не было ни слова!*

### [repaint] Hermes
  • **repaint_transition.py** — ACE-Step Repaint pipeline: закрашивание середины склейки хвост+голова, бесшовные стыки (751a8eb)
  • **mix_config_house.py** — конфиг для house-сета с AI-переходами (751a8eb)
  • `--transitions-dir` — гибридный режим: AI если файл есть, crossfade если нет

### [mixer] Hermes — fixes & cleanup
  • **Vocal overlap avoidance** — has_vocals(), сдвиг slave entry на ±8/16 бар при вокальной конфликтной зоне (9d9c78e)
  • **lufs_gain удалён** — треки уже нормализованы под -14 LUFS, per-section gain избыточен (f9f822f, 3a25ceb)
  • **Same-BPM ramp** — динамический ramp duration: <1% diff → skip ramp, <3% → ×2 duration (f589392)
  • **RAMP_MIN_RMS** — если entry RMS < порога, volume-only fade вместо BPM ramp
  • **best_exit_bar + soft_entry восстановлены** — revert отключения, которое сделало хуже (5d68cda)
  • **warp thresholds унифицированы** — 0.002 (0.2%) во всех 3 функциях (было 0.005 в warp_to_grid vs 0.002 в ramp/build_cf_lr4)
  • **MIN_SOLO_BARS удалён** — не нужен, best_exit_bar уже решает выбор тихого экзита
  • **Анализатор: v2 детекторы восстановлены** (9 штук), `--feedback` возвращён
  • **Анализатор: зонное сканирование** — только ±15с вокруг переходов, не весь микс
  • **run_pipeline**: transitions_reel после микса, убран --json-out (v3 не поддерживает)
  • **transitions_reel.py** — интеграция в пайплайн (ClaudeClaw написал, Hermes встроил)

### [skill] Hermes
  • ACE-Step Repaint, madmom/docs, preview workflow — расширение SKILL.md
  • CLAUDE_SYNC.md — инструкция для ClaudeClaw по синхронизации SKILL.md (bc7df61)
  • mixer tuning doc — references по всем исправлениям

---

## v15 (uncommitted)

### [mixer] Hermes — DSP refactor + A1F integration + structural fixes
  • **A1F BPM source of truth** — madmom BPM заменяется на A1F BPM, если найден JSON; downbeats пересчитываются под новый BPM
  • **A1F section labels** — `load_a1f_bar_labels()`, `A1F_PRIORITY`, `A1F_CF`, `A1F_DROP` — выход/вход и длина кроссфейда выбираются по A1F-меткам
  • **Per-bar VAD** — `vocal_per_bar()` — по ZCR + spectral ratio (1-4kHz); clash detection → vocal_notch_sweep вместо сдвига entry
  • **Dynamic CF_BARS** — `resolve_cf_bars()` + `--cf-bars auto|int`; A1F_CF словарь управляет длиной (16/8/4 bars)
  • **Downbeat snapping** — `snap_bar()` — exit/snap к 4-bar phrase grid
  • **EQ Sweep bass swap** — `eq_sweep()` с HPF 20→150Hz / LPF 150→20Hz вместо бинарного 2-bar bass swap; плавный, без ступеньки
  • **Dynamic crossover** — `find_crossover()` — спектральный анализ kick fundamental + vocal gap → индивидуальные low_cut/high_cut
  • **Vocal Notch Sweep** — `vocal_notch_sweep()` — -12dB bell sweep 1-4kHz на master mid band при вокальном конфликте
  • **BPM Transition path** — при ΔBPM > 5% мастер варпится к сетке слейва (вместо слейва к мастеру); ramp пропускается
  • **Ambient Blend fallback** — `DRUM_SEARCH_LIMIT=32`; если у слейва нет драм, ищет до 32 бар вперёд; не нашёл → quiet blend 16 bars
  • **Auto-looping** — `dynamic_loop()` — короткое интро (2-8 bars) растягивается тайлингом + crossfade до нужной длины
  • **soft_clipper_tanh()** — стандартный tanh-клиппер, заменяет `np.clip(mix, -1.0, 1.0)` на финальном выходе; threshold=0.707 (-3dB)
  • **filtfilt → sosfilt** — `three_band_split()` мигрирован на IIR SOS (minimum-phase, zero pre-ringing)
  • **-3dB headroom** — жёсткий пиковый клиппинг после norm_lufs (0.707 threshold) — запас под переходы

### [analyzer] Hermes — indentation fix
  • **`_scan_zone()` indentation** — все 9 детекторов (stutter, speed_glitch, transient_spike, hf_noise, spectral_discontinuity, onset_stability, rms_dip, harsh_endpoint, boundary_glitch, beat_irregularity, band_cancellation) были на уровне модуля, а не внутри функции. Теперь работают корректно

### [pipeline] Hermes — catalog integration
  • **yt_download.py** — после загрузки трек автоматически регистрируется в track_catalog через `register_in_catalog()`

---

## v16: Adaptive Style Engine

### [mixer] Hermes — STYLE_PROFILES + Auto-Detection + Per-sample EQ
  • **STYLE_PROFILES dict** — 4 профиля: downtempo (24/12-32, notch=-2dB, smooth_eq), house_tech (16/8-16, notch=-3.5dB, smooth_eq), hard_techno (8/4-12, notch=-1dB, stepped), pop_vocal (6/4-8, notch=-5dB, stepped)
  • **get_style_profile()** — автоопределение стиля по BPM + vocal_ratio: <110 BPM → downtempo, >135 BPM → hard_techno, vocal_ratio>0.55 → pop_vocal, иначе house_tech
  • **--cf-bars ручной приоритет** — если пользователь передал число (--cf-bars 16), профиль НЕ может его переопределить. Автоматика работает только в режиме 'auto'
  • **resolve_cf_bars профильная** — в auto режиме использует default_cf/min_cf/max_cf из профиля для LONG/MEDIUM/DROP
  • **Smooth EQ interpolation** — при smooth_eq=True: num_sweep_steps = max(256, len(audio)//128) (~3ms разрешение). При smooth_eq=False: классические 8-32 steps
  • **notch_db из профиля** — vocal_notch_sweep использует gain_db из профиля вместо жёсткого -12dB. Для pop_vocal -5dB (сохраняет плотность), для downtempo -2dB, для hard_techno -1dB
  • **Vocal Notch Smooth** — при smooth_eq=True: notch_steps = max(256, len//128) для бесшовной интерполяции

### Валидация (sanity test, --cf-bars 16, 128 BPM set)
  • Оба перехода: cf_bars=16 (ручной приоритет соблюдён) ✅
  • Профили: pop vocal (vocal_ratio 0.83, 0.96) ✅
  • noth_db: -5.0dB вместо -12dB ✅
  • P-score: 100% | CMLc: 100% | Cemgil: 0.885 ✅

---

## v16.2: Per-Track Profiles + Catalog + Web Genre

### [mixer] Hermes — Catalog & Per-Track Style Engine
  • **Каталог A1F** — `load_a1f_bar_labels()` теперь проверяет `track_catalog/a1f_results/` приоритетно
  • **Per-track style_profile** — каждый трек в TD получает свой `style_profile` (A1F + BPM + vocal_ratio)
  • **A1F instrumental override** — >40% instr. секций + vocal_ratio<0.4 → house_tech
  • **Динамический DSP при переходе** — cf_bars по longer default_cf, notch_db по min, smooth_eq=OR
  • **search_track_genre()** — веб-поиск жанра по ключевым словам в названии трека
  • **All-in-One Fix** — `/home/hermes/ai-tools/all-in-one-fix/venv/bin/python -m allin1fix.cli` для ML-анализа

---

## v16.3: A1F Segment-Based Transitions (Universal DSP)

### [mixer] Hermes — Full A1F Integration + Static Profile Removal
  • **`load_a1f_track_data()`** — полное извлечение A1F: bpm, downbeats (sample positions), segments (start/end/label), bar_labels, vocal_density. Заменяет `load_a1f_bar_labels()`
  • **A1F master grid** — downbeats из A1F JSON заменяют madmom DB как мастер-сетку (точность ML-модели)
  • **`resolve_transition_params()`** — универсальный DSP-резолвер на основе пересечения A1F-сегментов:
    - `outro→intro/inst` → 16 bars, smooth_eq, notch=-3.5
    - `outro/break→verse/bridge` → 8 bars, smooth_eq, notch=-5.0
    - `break→intro/inst` → 8 bars, smooth_eq, notch=-3.0
    - `chorus/verse→intro/inst` → 4 bars, stepped, notch=-5.0
    - `anything→chorus/verse` → 4 bars, stepped, notch=-5.0
    - Default → 8 bars, smooth_eq, notch=-3.0
    - Vocal density >0.5 → notch_db -1dB (max -6.0)
  • **Удалён STYLE_PROFILES** — больше нет жёстко закодированных жанров (pop_vocal, house_tech, hard_techno, downtempo)
  • **Удалён pop_vocal fallback** (строка 1492) — больше никакой автоматической классификации треков по стилям
  • **Удалены A1F_CF/A1F_DROP** — заменены единым `resolve_transition_params()`
  • **`run_a1f_analysis()`** — неблокирующий фоновый запуск allin1fix.cli с `--skip-separation` (без Demucs, 5-10x быстрее) для треков без JSON
  • **`search_track_genre()`** — переписана: читает yt-dlp `.info.json` метаданные (теги, genre, description) для определения vocal_hint/density. Фолбек на keyword matching в названии
  • **`--yt-metadata-dir`** — новый CLI-аргумент

### Валидация (5 треков с A1F JSON, --cf-bars auto)
  • A1F данные загружены для 5/5 треков ✅
  • Переходы по сегментам: chorus→verse (4 bars, notch=-6.0), inst→verse (4 bars, notch=-6.0) ✅
  • Нет pop_vocal/house_tech в логах ✅
  • BPM hard cuts при >8% расхождении (103→128, 127→103) ✅
  • Время сборки: 50.6с для 5 треков ✅

---

## v16.3.1: --analysis-mode + Strict Fallback

### [mixer] Hermes — CLI & Fallback Fix
  • **`--analysis-mode`** — 3 режима: `a1f` (полный Demucs, по умолчанию), `a1f_fast` (--skip-separation, без стем), `no_a1f` (без нейросети)
  • **Строгий fallback в `resolve_transition_params()`** — при `has_a1f=False` проверяет `search_track_genre()` hints. Если трек электронный/инструментальный → 🎯 **16b, smooth_eq, notch=-3.5**
  • **`search_track_genre()`** — расширена электронными ключевыми словами (progressive, house, techno, melodic, extended mix, original mix, remix)
  • **genre_hint в TD** — каждый трек хранит fallback-метаданные; `has_a1f` bool для переключения режима резолвера
  • **resolve_cf_bars()** — пробрасывает genre_hint и has_a1f в resolve_transition_params()
  • **`--yt-metadata-dir` удалён** — заменён на `--analysis-mode`
  • **Удалён старый `run_a1f_analysis()`** — заменён на встроенный Popen с учётом analysis_mode

### Валидация (8 треков с A1F, --cf-bars auto, --analysis-mode a1f)
  • Микс: 29:43, 71.3 MB, 320 кбит/с ✅
  • A1F-переходы: bridge→verse (4b, -6.0dB), inst→bridge (4b, -6.0dB) ✅
  • Fallback mode (no_a1f): корректный VAD-дефолт 8b ✅
  • Время сборки: 73.8с для 8 треков ✅

## v16.6 — 2026-06-12

### Новые правила переходов (Stas req)
- **Запрещены переходы < 22с** — минимальный `cf_bars` поднят с 4→12 bar (~23с при 128 BPM)
- **70% переходов ≥ 28с** — one-side energy cap повышен с 8→16 bar (~30с)
- **Переходы 40-60с** — нормальные (без cap) остаются 24-32 bar (45-60с)
- Vocal entry (chorus/verse/bridge): минимум **12 bar** (было 8 bar)
- Energy cap both-high: **12 bar** (было 4 bar)
- Energy cap one-high: **16 bar** (было 8 bar)
- Документация: `smart_mixer.py` docstring v16.6

### A1F pre-analysis pipeline
- Все 21 трек MIX-2 проанализированы `allin1fix --skip-separation` перед сведением
- 20/21 треков имеют полные A1F JSON (bpm, segments, beats, downbeats)
- 1 трек (Korolova - My Mind) использует style-based fallback (24 bar)
- Строгая последовательность: `a1f_fast` → mix → analyze → report

### Исправление эхо на ударных (band_cancellation)
- Увеличенная длина переходов уменьшает фазовую интерференцию баса
- 24dB/oct HPF→LPF сохраняется (v16.5)
- band_cancellation ожидается < 300 против 558 в MIX-2

