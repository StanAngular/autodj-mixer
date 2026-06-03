# SKILL: music_tracklist_builder

**Версия:** 1.2
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

## Как диджеи находят музыку (стратегии)

Диджей ищет треки не через поисковик общего назначения. Есть три основных канала:

### 1. Обратный инжиниринг сетов

Живые сеты топовых диджеев -- самый прямой источник актуального материала.

- **1001tracklists.com** -- база треклистов радиошоу и живых выступлений. Ищи сеты конкретного DJ или по жанру.
  - Поиск: `site:1001tracklists.com [DJ name] 2025` или топ-чарты по жанру
  - Дает: артист, трек, лейбл, временная метка в сете
- **Shazam в записях:** поставь кусок сета из Boiler Room / RA Podcast -- Shazam или ACRCloud определит трек
  - Boiler Room: boilerroom.tv (видео с таймкодами)
  - RA Podcast: ra.co/podcast
- **Mixcloud + ACRCloud:** ACRCloud (acrcloud.com) идентифицирует треки из аудио автоматически

### 2. Лейблы как фильтр качества

Диджей подписывается на лейблы, которым доверяет -- не на артистов. Лейбл = курация.

- Bandcamp: подписка на лейбл → уведомления о новых релизах
- RA: ra.co/labels/[label-id] -- дискография + новые релизы
- Spotify: "Это [лейбл]" плейлисты автоматически обновляются

### 3. Рекомендательные цепочки

- Bandcamp: "fans also bought" на странице трека -- точнее Spotify
- SoundCloud: "Suggested tracks" в очереди у диджеев которых слушаешь
- Discogs: купленные пластинки конкретного диджея (у многих открытые коллекции)
- RA Charts: ra.co/charts -- ежемесячные чарты от конкретных диджеев

### Критерии качества (не скачивать если)

- Трек не получил рецензий ни на одном из: RA, Boomkat, XLR8R, The Quietus
- Лейбл не в белом списке ниже
- SoundCloud plays < 5000 (если не эксклюзив для Bandcamp)
- Дата релиза > 3 лет -- если это не классика (проверить, есть ли в чартах)

---

## Фаза 1 — Поиск кандидатов

### Источники

**Underground:** bandcamp.com, ra.co/reviews, boomkat.com, bleep.com, the-quietus.com, nts.live, resident-advisor.net, xlr8r.com

**Commercial:** beatport.com/top-100, 1001tracklists.com, traxsource.com, soundcloud.com

**Блоги / рассылки (актуальное):** xlr8r.com/tag/reviews, juno.co.uk/articles/, thewire.co.uk

### Алгоритм

1. Старт: взять 2-3 топовых диджея нужного жанра → их последние сеты на 1001tracklists
2. Выбрать 10-15 треков которые встречаются у нескольких диджеев сразу (пересечение = качество)
3. Дополнить: site:bandcamp.com [genre] 2025 new releases
4. Извлечь: артист + трек + лейбл + BPM + тональность + ссылка
5. Отфильтровать: убрать всё не из белого списка лейблов (если underground режим)
6. Собрать 30-40 кандидатов

### Белый список лейблов (underground)

- **Techno:** Avian, Mote-Evolver, Semantica, Hypnus, Blueprint, Perc Trax, Tresor, Downwards, Token, Spazio Disponible, Prologue, Stroboscopic Artefacts
- **IDM:** Warp, Planet Mu, Ninja Tune, CPU, Raster-Media, Editions Mego
- **Avant:** PAN, Hyperdub, SVBKVLT, Nyege Nyege, YEAR0001
- **Ambient:** Room40, 12k, Kranky, Ghostly, Glacial Movements, Erased Tapes
- **House:** Livity Sound, Hessle Audio, Ilian Tape, Giegling, Perlon, L.I.E.S., Shall Not Fade
- **Melodic / Progressive:** Afterlife, Innervisions, Watergate, Kompakt
- **Industrial / Noise:** Hospital Productions, Dais Records, Sacred Bones, aufnahme + wiedergabe
- **Psy / Neo-Goa:** Zenon Records, Suntrip Records, Parvati Records

### Топ диджеи по жанру (для 1001tracklists и RA Podcast)

- **Techno:** Surgeon, Phase, Blawan, Ancient Methods, Paula Temple, Alignment
- **Melodic house/techno:** Innellea, Ben Böhm, Stephan Bodzin, Tale Of Us, Bicep
- **Deep/minimal house:** Move D, Lawrence, Recondite, Mathew Jonson
- **IDM/experimental:** Objekt, Shackleton, Actress, Burial, Kuedo
- **Psy/Goa:** Skazi, Astrix, Liquid Soul (Zenon-направление более underground)

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

VPS использует **Cloudflare WARP** (`socks5://127.0.0.1:40000`). YouTube без прокси блокирует yt-dlp (429, региональные ограничения).

```bash
# Проверка прокси
curl -s --socks5 127.0.0.1:40000 --connect-timeout 5 https://www.google.com -o /dev/null -w "%{http_code}"

# Переподключение Warp
warp-cli disconnect && warp-cli connect
```

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

### Fallback при блокировке

1. Проверить прокси
2. Переподключить Warp
3. Попробовать без прокси
4. Найти трек на другом ресурсе
5. Предложить замену

### Полный пайплайн

```
1. Собрать URLs из треклиста
2. Сохранить в /tmp/urls_{date}.txt
3. Запустить yt_download.py --url-file /tmp/urls_{date}.txt
4. Скопировать TRACKS в mix_config.py
5. python3 smart_mixer.py --config mix_config.py
6. python3 mix_analyzer.py --mix output.mp3 --config mix_config.py --feedback
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
- Warp может отваливаться -- проверять перед скачкой
- BPM/key анализ делает autodj-mixer -- не нужно предопределять
- 1001tracklists иногда даёт неполные треклисты (ID треки без названий) -- оставить на потом

## Changelog

- v1.1 (Hermes, 2026-06-03): создан, фазы 1-4, белый список лейблов, Camelot, пайплайн скачки
- v1.2 (ClaudeClaw, 2026-06-03): добавлены стратегии поиска как у диджеев (1001tracklists, Shazam в сетах, Bandcamp fans also bought, критерии качества), расширены лейблы (Afterlife, Innervisions, Prologue и др.), топ DJ-референсы по жанрам
