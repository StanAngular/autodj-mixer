# 📊 Контрольный прогон Path B — отчёт (с P35)

**Параметры:** ANOTR, Adriatique, Chris Stussy, WADE · tech house · BPM 122-128 · seed-limit 16 · max-probe 20 · target 12

---

## 1️⃣ build_seedlist — сиды

| Метрика | Значение |
|---|---|
| Входные артисты | 4 |
| После расширения last.fm | 21 артиста |
| Пул до лимита | 42 сид-строки |
| **После --limit 16** | **16** ✅ |

## 2️⃣ seed_discover — кандидаты

| Метрика | Значение |
|---|---|
| Искал на сид (--per) | 5 |
| **Кандидатов** | **16** (по 1 лучшему на сид) |
| Cercle/Boiler Room сеты | ❌ **отсеяны** (P35: is_plausible_track) ✅ |
| Пропущено по стилю | 0 |

## 3️⃣ resolve_metadata — каскад

| Источник | Попаданий |
|---|---|
| Каталог | 0 |
| Кэш | 0 |
| **Остаток на аудио** | **16** |

## 4️⃣ prescreen — MP3-проба

| Параметр | Значение |
|---|---|
| max-probe (потолок) | 20 |
| target (порог) | 12 |
| **Фактически пощупано MP3** | **9** ✅ (≤20) |
| **Keeper'ов** | **5** ✅ (≤12) |
| Отклонено | 11 (6 — Camelot не определён, 4 — BPM вне 122-128, 1 — Camelot fail) |

## 5️⃣ Keeper'ы

| # | Артист — Трек | BPM | Camelot | Источник |
|---|---|---|---|---|
| 1 | ANOTR — Talk To You | **129** | 6B | probe-mp3 |
| 2 | Adriatique — Miracle | **123** | 8B | probe-mp3 |
| 3 | Jamie Jones — Lose My Mind | **123** | 6A | probe-mp3 |
| 4 | Jamie Jones — My Paradise | **129** | 3A | probe-mp3 |
| 5 | Franky Rizardo — Shinjuku | **129** | 1A | probe-mp3 |

**BPM реальный** ✅ — ни одного `None`

## 6️⃣ Сводка проблем / остатки

| Что | Статус |
|---|---|
| Cercle/Boiler Room сеты | ❌ **ИСПРАВЛЕНО** P35 ✅ |
| BPM = None | ❌ **ИСПРАВЛЕНО** P35 ✅ |
| Имена чистые (без live/reaction/lyrics/set) | ✅ |
| Wade x2 — Camelot не определён у обоих | ⚠ остаётся (видимо MP3-проба не смогла определить) |
| Alan Fitzpatrick x2 — Camelot не определён | ⚠ остаётся |
| Gesaffelstein — вне BPM-диапазона (99 BPM) | норм (не тот жанр) |
| Chris Stussy — Desire 89 BPM / All Night Long 136 BPM | не tech house темп |
| Гармония keepers: 6B→8B→6A→3A→1A | смешанная (нужна пересборка) |

## Итог

| Этап | Было (P30) | Стало (P35) |
|---|---|---|
| Сид-строк | 118 | 16 ✅ |
| MP3-проб | 115 → OOM | **9** ✅ |
| WAV к скачиванию | 62 → OOM | **5** ✅ |
| BPM | все None | **реальные 123–129** ✅ |
| Сеты вместо треков | Adriatique @ Cercle | **Adriatique — Miracle** ✅ |