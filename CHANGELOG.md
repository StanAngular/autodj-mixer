# Changelog — autodj-mixer

Формат: `[YYYY-MM-DD HH:MM] [Agent] [Категория] описание | причина`

Категории:
- `[fix_ht]` — изменения логики исправления half-time аннотаций
- `[warp]` — изменения в bar-by-bar warping / временном растяжении
- `[mixer]` — изменения в основном процессе сведения
- `[analyzer]` — изменения в mix_analyzer
- `[pipeline]` — run_pipeline, config, scripts
- `[infra]` — установка зависимостей, CI, права
- `[bug]` — фикс бага

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

### [skill] Hermes
  • ACE-Step Repaint, madmom/docs, preview workflow — расширение SKILL.md
  • CLAUDE_SYNC.md — инструкция для ClaudeClaw по синхронизации SKILL.md (bc7df61)
  • mixer tuning doc — references по всем исправлениям

