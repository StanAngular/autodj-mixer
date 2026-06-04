# SKILL: music_tracklist_builder

**Версия:** 2.0  
**Назначение:** Поиск треков → треклист → скачка → микс для autodj-mixer  
**Совместимость:** ClaudeClaw, Hermes Agent (оба агента)

---

## Когда активировать

- Пользователь просит найти треки для микса / плейлиста
- Слова: `микс`, `треклист`, `tracklist`, `скачай треки`, `подбери музыку`
- Запрос содержит упоминание autodj-mixer или папки с треками

## Параметры (уточнить перед стартом)

1. **РЕЖИМ:** underground / commercial / mixed (дефолт: underground)
2. **ЖАНР:** техно / хаус / IDM / эмбиент / экспериментальное / псай / транс / ломаный бит / любой (дефолт: свободный)
3. **ДЛИНА:** 15 треков или хронометраж (дефолт: 15)
4. **BPM-диапазон:** опционально

---

## Фаза 1 — Поиск кандидатов

### Источники

**Underground:** bandcamp.com, ra.co/reviews, boomkat.com, bleep.com, the-quietus.com, nts.live, resident-advisor.net

**Commercial:** beatport.com/top-100, 1001tracklists.com, traxsource.com, soundcloud.com

### Алгоритм

1. 3-5 поисковых запросов (site:bandcamp.com techno experimental 2025)
2. Извлечь: артист + трек + лейбл + BPM + тональность + ссылка
3. Отфильтровать дубли, мусор
4. Собрать 30-40 кандидатов

### Белый список лейблов (underground)

- **Techno:** Avian, Mote-Evolver, Semantica, Hypnus, Blueprint, Perc Trax, Tresor, Downwards, Token, Spazio Disponible
- **IDM:** Warp, Planet Mu, Ninja Tune, CPU, Raster-Media, Editions Mego
- **Avant:** PAN, Hyperdub, SVBKVLT, Nyege Nyege, YEAR0001
- **Ambient:** Room40, 12k, Kranky, Ghostly, Glacial Movements, Erased Tapes
- **House:** Livity Sound, Hessle Audio, Ilian Tape, Giegling, Perlon
- **Industrial / Noise:** Hospital Productions, Dais Records, Sacred Bones, aufnahme + wiedergabe
- **Psy / Neo-Goa:** Zenon Records, Suntrip Records, Parvati Records

---

## Фаза 2 — Треклист

### Энергетическая дуга

```
1-3:   Intro — мягкий вход, –3 dB от пика
4-8:   Разгон — нарастание энергии
9-14:  Пик — максимальная энергия
15-17: Спуск — плавное снижение
18-20: Outro — закрытие
```

### Camelot-совместимость

- Один key: 8A→8A
- +1 по кругу: 8A→9A (подъём)
- -1: 8A→7A (спуск)
- Major↔Minor: 8A→8B
- BPM-дельта: не больше ±4 BPM между соседями

### Формат вывода

```
## ТРЕКЛИСТ: [Название] — [Дата]
| # | Артист | Трек | Лейбл | BPM | Key | Источник | Статус |
```

---

## Фаза 3 — Скачивание

### Warp/Cloudflare прокси (антиблокировка)

VPS использует **Cloudflare WARP** (`socks5://127.0.0.1:40000`). Многие сервисы блокируют Contabo IP — **Warp везде где банит**, не только YouTube:

| Куда | Без Warp | С Warp |
|------|----------|--------|
| YouTube | ❌ блокирован | ✅ (но клиентская детекция) |
| SoundCloud | ⚠️ иногда | ✅ стабильно |
| Discogs | ⚠️ может | ✅ |
| Beatport | ⚠️ может | ✅ |
| Boomkat | ❌ блокирован | ✅ |
| RA | ❌ блокирован | ⚠️ |

**Правило:** если сайт не открывается через curl/wget → добавь `--proxy socks5://127.0.0.1:40000`.

```bash
# Проверка прокси
curl -s --socks5 127.0.0.1:40000 --connect-timeout 5 https://www.google.com -o /dev/null -w "%{http_code}"

# curl на заблокированные сайты
curl -s --proxy socks5://127.0.0.1:40000 "https://api.discogs.com/..."

# yt-dlp (YouTube, SoundCloud)
yt-dlp --proxy socks5://127.0.0.1:40000 "https://..."

# Переподключение Warp (новый IP)
warp-cli disconnect 2>/dev/null; sleep 1; warp-cli connect 2>/dev/null; sleep 3
```

### Cloudflare стратегия — НЕ БЛОКИРУЮТ

**НИКОГДА не качать параллельно** — мгновенный бан. Только последовательно, с Warp reconnect между треками:

```bash
for url in "${URLS[@]}"; do
  warp-cli disconnect 2>/dev/null; sleep 1
  warp-cli connect 2>/dev/null; sleep 3  # новый IP
  
  yt-dlp --proxy socks5://127.0.0.1:40000 \
    -f bestaudio -x --audio-format mp3 --audio-quality 0 \
    -o "%(id)s.%(ext)s" --no-warnings "$url" 2>/dev/null
    
  sleep 2
done
```

**Ожидаемый fail rate:** 10-30% — треки удалены, приватные, регион-лок. Двигаться дальше, не ретраить бесконечно.

**Если ALL fail:** YouTube временно блокирует диапазон Warp IP. Ждать 1ч или переключиться на SoundCloud.

### SoundCloud как альтернатива

Когда YouTube банит, SoundCloud часто работает. Та же команда:

```bash
yt-dlp --proxy socks5://127.0.0.1:40000 \
  -f bestaudio -x --audio-format mp3 --audio-quality 0 \
  -o "%(id)s.%(ext)s" "https://soundcloud.com/.../..."
```

SoundCloud лучше для андеграунд/техно треков.

### yt_download.py

Скрипт в `/opt/autodj-mixer/yt_download.py` — автоматом использует Warp proxy.

```bash
# Одиночный трек
/opt/autodj-mixer/yt_download.py "https://youtube.com/watch?v=..."

# Несколько
/opt/autodj-mixer/yt_download.py "URL1" "URL2"

# Из файла
/opt/autodj-mixer/yt_download.py --url-file urls.txt
```

**Что делает:** MP3 → WAV (44100, PCM_24) → madmom downbeats → TRACKS блок

**ВАЖНО:** yt_download.py сохраняет аннотации в СЕКУНДАХ (float). Если аннотации в сэмплах (int) → BPM=0 → fix: `awk '{$1=$1/44100; print}' ann.txt > ann_fixed.txt`

### Fallback при блокировке

1. Проверить прокси (`curl --proxy ...`)
2. Переподключить Warp (новый IP)
3. Попробовать SoundCloud вместо YouTube
4. Если SoundCloud тоже банит — cookies (экспорт из браузера)
5. Найти трек на другом ресурсе
6. Предложить замену (skip, не зависать)

### Поиск треков (research phase)

**Работают:** Discogs (год+лейбл), Beatport (жанр), SoundCloud (скачка)
**Блокированы:** Boomkat, Resident Advisor (веб-поиск)

**Алгоритм:**
1. Discogs: `site:discogs.com "artist" "track" release` → год, лейбл, каталог
2. SoundCloud: `site:soundcloud.com "artist label"` → скачка
3. YouTube: если не на SoundCloud (30% failrate)

**Red flags:** длительность < 2:30, BPM > 180 или < 80, неизвестный артист без лейбла, плохое качество

### Полный пайплайн (со Strict Gates)

```bash
# Gate 0: проверка исходников
python3 source_check.py --config mix_config.py

# Step 1: пре-анализ + сортировка
python3 track_analyzer.py --config mix_config.py --out .optimized.py

# Step 2: микс
python3 smart_mixer.py --config .optimized.py --style "..." --author "..."

# Step 3: анализ (обязательно перед отправкой!)
python3 mix_analyzer.py --mix Mix.mp3 --config .optimized.py --feedback

# Gate: проверить source artefacts Phase 1 — >50 = трек бит
# Gate: проверить тишину — >2s внутри = exit_bar проблема
# Gate: проверить BPM стабильность в миксе

# Step 4: залить на catbox
curl -s -F "reqtype=fileupload" -F "time=72h" -F "fileToUpload=@Mix.mp3" https://litterbox.catbox.moe/resources/internals/api.php

# Step 5: таблица переходов с реальным временем
```

---

## Фаза 4 — Интеграция с autodj-mixer

### Структура

```
/opt/autodj-mixer/
  tracks/          ← WAV файлы
  ann/             ← downbeat аннотации (.txt)
  mix_config.py    ← конфиг с TRACKS
  CHANGELOG.md     ← лог изменений (оба агента пишут)
  docs/            ← исследования, заметки
```

### Быстрые команды

```bash
python3 smart_mixer.py --yt-urls-file urls.txt --quick-test
python3 smart_mixer.py --yt-urls "URL" --style techno --author Hermes
python3 mix_analyzer.py --mix /tmp/Mix_*.mp3 --config mix_config.py --feedback
```

---

## Ограничения

- Не обходит DRM (Mixcloud, купленный Bandcamp)
- Ссылки устаревают
- Warp может отваливаться — проверять перед скачкой
- BPM/key анализ делает autodj-mixer — не нужно предопределять

## Как читать анализатор (mix_analyzer.py --feedback)

**Phase 1 — Source Analysis:**
- `250 artefacts` в треке = **источник битый** (50+ = стоп). Не вина миксера.
- `BPM=127.9 Key=C# maj conf=0.61` — надёжность детекции

**Phase 2 — Transition Analysis:**
- `drift=-14.5ms` — <50ms = хорошо. >100ms = плохо
- `LUFS=+2.5dB` — скачок громкости >3dB = проблема

**Phase 3 — Mix Artefact Scan:**
- `676 events` — из них сколько mixer-induced (Phase 4)? Если >80% source — треки битые
- `speed_glitch` в зоне рампа (между переходами) — ожидаемо, не баг

**Phase 4 — Source vs Mixer:**
- **КЛЮЧЕВОЙ раздел.** `In source (106)` vs `Mixer-induced (570)` — сравнивать
- Если source artefacts > mixer artefacts → треки плохие, миксер ни при чём
- Если mixer artefacts >> source → искать баг в smart_mixer.py

**Phase 5 — Feedback:**
- Рекомендации по настройке. Не все критичны
- `RAMP_SEC 15→20` — настройка, не баг
