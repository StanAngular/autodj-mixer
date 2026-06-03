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
