# Electronic Music Research Log

**Назначение:** Живой документ — накапливаем знания об электронной музыке, BPM, тональностях, жанровых особенностях. Оба агента (Hermes + ClaudeClaw) дополняют по мере работы с autodj-mixer.

**Формат записи:** `[YYYY-MM-DD] [Agent] [Категория] — наблюдение | источник`

**Категории:** BPM, Key/Camelot, Жанр, Транзишены, Анализ, Техника

---

## BPM

### Наблюдения

### Проверенные диапазоны (из треков в папке)

| Трек | BPM | Жанр (оценка) |
|------|-----|----------------|
| Gamgi | 117 | Deep house / downtempo |
| Garden | 122 | Melodic house |
| Lakeside | 124 | Deep house |
| Eleonora | 123 | Melodic house / progressive |
| Fever | 122 | Deep house |
| GetOnMyLevel | 130 | Tech house |

### Заметки по микшеру

- smart_mixer warps BPM в диапазоне ±8% (BPM_DIFF_LIMIT = 0.08)
- За этим пределом — прямой срез (hard cut)
- Рампа BPM: 15с после кроссфейда (RAMP_SEC), замедление/ускорение до native BPM
- fix_ht корректирует half-time/double-time аннотации (медианный интервал)

---

## Key / Camelot

### Наблюдения

### Совместимость (проверено на тестах)

| Переход | Score | Результат |
|---------|-------|-----------|
| Одинаковый key (8A→8A) | 1.0 | Идеально |
| +1 по кругу (8A→9A) | 0.9 | Хорошо, яркий подъём |
| -1 по кругу (8A→7A) | 0.9 | Хорошо, мягкий спуск |
| Major↔Minor (8A→8B) | 0.8 | Смена характера |
| Всё остальное | 0.3 | Плохо |

### Детекция key (librosa chroma CQT + Krumhansl-Schmuckler)

Определяет key на всём треке (среднее по хроме). Точность — умеренная, для клубных треков OK.

---

## Жанры

### Характеристики

| Жанр | BPM | Структура | Особенности |
|------|-----|-----------|-------------|
| Deep house | 118-125 | 4/4, kick on 1-3-5-7 | Длинные intro/outro, мелодия |
| Melodic house / progressive | 120-128 | 4/4 | Build-up/drop структура, 16-32 такта |
| Techno | 128-140 | 4/4, minimal percussion | Длинные сеты, дроун-бас |
| Tech house | 125-130 | 4/4, funky | Коммерческие элементы |
| Hardcore | 160-210 | 4/4, искажённый kick | Требует fix_ht для аннотаций |
| IDM / experimental | 80-140 | Ломаный ритм, не-4/4 | Сложен для warp — неравномерные биты |
| Trance | 130-150 | 4/4, build-up → drop | Энергичный, длинные breakdowns |
| Psy / Goa | 140-160 | 4/4, резкие басы | Быстрый темп, сложные синкопы |
| Psybient / Ambient | 60-100 | Не-4/4 или медленный 4/4 | Атмосферный, текстурный |
| Breakbeat / Jungle | 140-180 | Ломаный ритм (Amen break) | Сложен для beat-matching |
| Downtempo / Chillout | 70-110 | Разная | Часто double-time аннотации от madmom |

### Проблемные жанры для fix_ht

- **Hardcore (210 BPM+):** madmom даёт half-time аннотации (2/4 вместо 4/4). fix_ht med-подход (медиана 0.945s, порог < 0.25 → decimate) не срабатывает — медиана в beat-level диапазоне. Требуется ratio-подход.
- **Downtempo (<80 BPM):** madmom может давать double-time аннотации.

---

## Транзишены

### Наблюдения

### Типы (в smart_mixer)

1. **LR4 3-band + bass swap (hpss):**
   - Мастер бас → слейв бас с плавным замещением
   - Mid/high — power crossfade
   - Коррекция полярности баса (если corr < -0.3)

2. **Power crossfade (no hpss):**
   - Простой gain crossfade
   - Используется при ошибках warp

3. **BPM ramp:** после кроссфейда — потактный warp к native BPM следующего трека

### Проблемы

- **Camelot не влияет на микшер** — key совместимость не зашита в логику выбора переходов, только анализируется постфактум
- **Speed glitch в анализаторе:** ложные срабатывания BPM трекера в зонах ramp-back (нужно подавление 15с после кроссфейда)

---

## Анализ (mix_analyzer)

### 5 фаз

1. **Source analysis:** BPM, key, source artefacts (число)
2. **Transition analysis:** drift (ms), LUFS jump (dB), centroid shift
3. **Mix artefact scan:** stutter, speed glitch, transient spike, HF noise, spectral discontinuity
4. **Source vs mixer cross-reference:** что было в источнике vs что появилось после миксера
5. **Feedback generation:** рекомендации — RAMP_SEC, MAX_SHIFT_SEC, gain_offset, headroom

### Метрики качества

- **Beat drift:** < 10ms = отлично, 10-20ms = OK, > 20ms = плохо
- **LUFS jump:** > 3dB = заметный скачок громкости
- **Speed glitch:** ложные срабатывания в ramp-back (известный баг)

---

## Технические заметки

### Инструменты

| Инструмент | Версия | Путь |
|------------|--------|------|
| Python | 3.11 | /opt/autodj-mixer/.venv/bin/python3 |
| yt-dlp | 2026.03.17 | ~/.local/bin/yt-dlp |
| ffmpeg | 6.1.1 | system |
| madmom | ??? | venv (нужен numpy compat fix) |
| librosa | 0.11.0 | venv |
| rubberband | — | apt / pyrubberband |

### Пайплайн (полный цикл)

1. Поиск треков → треклист (music_tracklist_builder)
2. Скачка: `yt_download.py --url-file urls.txt`
3. Конфиг: скопировать TRACKS в mix_config.py
4. Микс: `smart_mixer.py --config mix_config.py`
5. Анализ: `mix_analyzer.py --mix output.mp3 --config mix_config.py --feedback`
6. Оценка: проверить feedback, если нужно — поправить параметры

### Ограничения

- madmom требует numpy compat хак (`np.float = np.float64` перед import)
- Warp proxy обязателен для YouTube (иначе 429)
- git .git/objects permissions: нужен `git config core.sharedRepository group`