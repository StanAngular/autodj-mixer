# Beatport — спецификация интеграции (источник + резолвер метаданных)

> Полный реестр возможностей Beatport для пайплайна + чек-лист «сделано / TODO».
> Цель: ничего не терять, не возвращаться к обсуждению. Обновлять при каждом патче.

Beatport — DJ-ориентированный источник: чистые **треки** (не сеты) с готовыми
BPM/Key, без Cloudflare (в отличие от Tunebat). Используется в двух ролях:
**(A) источник кандидатов** (чарты/каталоги) и **(B) резолвер метаданных по имени**
(в каскаде `resolve_metadata`, перед Tunebat).

## 1. Поля трека (data fields)

| Поле | Тип | Назначение | Статус |
|---|---|---|---|
| Artist | str | основной артист + ремиксер | ✅ парсится |
| Title | str | название трека | ✅ парсится |
| **Mix Name** | str | Extended / Original / Club / Dub / **Radio Edit** | ✅ парсится + **гейт отсева Radio Edit** |
| BPM | int | точный темп | ✅ парсится |
| Key | str | муз. ключ → Camelot (`beatport_camelot`) | ✅ парсится |
| Genre | str | Tech House, Minimal/Deep Tech, Melodic House & Techno… | ⚠️ частично (на уровне запроса) |
| **Label** | str | лейбл релиза | ✅ парсится (для каталогов лейблов + отчёта) |
| **Release Date** | YYYY-MM-DD | дата выхода | ✅ парсится + **гейт года (напр. 2026)** |

## 2. Каталоги (эндпоинты)

| Эндпоинт | Что даёт | Статус |
|---|---|---|
| `/charts?genre={genre}` | DJ-чарты по жанру | ✅ `fetch_beatport_charts` |
| `/genre/{genre}/tracks` | вся масса треков стиля | ⛔ TODO |
| `/label/{label}/tracks` | релизы целевых лейблов (No Art, Solid Grooves…) | ⛔ TODO |
| `/artist/{artist}/tracks` | дискография по сиду | ⛔ TODO |

## 3. Рейтинги / чарты (источники сидов)

| Чарт | Что даёт | Статус |
|---|---|---|
| Genre Top 100 `/genre/{genre}/top-100` | 100 самых продаваемых в жанре | ⛔ TODO |
| DJ Charts `/artist/{artist}/charts` | топ-10, что артист играет сейчас | ⛔ TODO |
| **Hype Top 100** | инди-лейблы без мейджоров — андеграунд | ⛔ TODO (ценно для «незаезженного») |
| Global Top 100 | общий топ всех жанров — макро-тренды | ⛔ TODO |

## 4. Сортировка / фильтры (параметры запроса)

| Фильтр | Назначение | Статус |
|---|---|---|
| Release Date (Newest) | свежее раньше | ✅ `--sort newest` (клиентская сортировка пула по release_date) |
| Bestsellers (Top Sellers) | популярность | ✅ `--sort bestsellers` (по support_score) |
| Key / BPM в URL | фильтр диапазона на стороне Beatport | ⚠️ частично: год/BPM-гейты есть; URL-фильтр ленты жанра = V4-эндпоинт, проверить вживую |

## Роутинг (как используется в пайплайне)

- **Метаданные:** каскад `resolve_metadata` = каталог → кэш → **Beatport-by-name**
  (`search_beatport_track`) → Tunebat → аудио. **Фоллбэк работает**: нет на Beatport → дальше.
- **Discovery:** `--source youtube | beatport` — взаимоисключающий выбор; `--source auto`
  (`compose_sources.py`) — **композит с фоллбэком**: Beatport → если < target, добор YouTube/last.fm,
  слияние с дедупом по video_id (приоритет Beatport). ✅

## Порядок реализации (предложенный)

1. ~~**Поля + гейты**: Mix Name / Label / Release Date в парсере; гейт «не Radio Edit»; гейт года~~ ✅ **СДЕЛАНО (P39)** — гейты тестируются, парсер проверит Гермес вживую.
2. ~~**Сортировка**: Newest / Bestsellers~~ ✅ **СДЕЛАНО (P43)** — `--sort newest|bestsellers` (клиентская сортировка пула). URL-фильтр ленты жанра (V4) — отдельно, вживую.
3. **Доп. чарты-источники**: Hype Top 100 (андеграунд), Genre Top 100, DJ Charts артиста.
4. **Каталоги**: /label, /artist, /genre/tracks.
5. ~~**Композитный discovery с фоллбэком** (Beatport → YouTube/last.fm)~~ ✅ **СДЕЛАНО (P42)** — `orchestrate --source auto` → `compose_sources.py`.

## Существующий код (точки переиспользования)

- `curate_tracks.fetch_beatport_charts(genre, years)` — чарты → треки.
- `curate_tracks.search_beatport_track(artist, track)` → `(bpm, camelot, style)`, requests, без Cloudflare.
- `curate_tracks.BEATPORT_GENRE_SLUGS` — жанр → слаг.
- `playwright_scraper._parse_beatport_chart_tracks` — парсер `__NEXT_DATA__` (сюда добавлять поля).
- `playwright_scraper.beatport_camelot` / `KEY_NAME_TO_CAMELOT` — ключ → Camelot.
