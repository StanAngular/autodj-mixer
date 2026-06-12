# Jazz / Chill Downtempo

## BPM Range
60-95 BPM (typical: 70-85)

## Mixing Style
Мягкие длинные кроссфейды. Нет ударных акцентов для синхронизации -- сводить по гармонии и атмосфере, не по бочке. Два трека могут звучать одновременно долго без конфликта.

## Recommended Parameters

```python
CF_BARS = 16          # 16 баров = ~45s при 85 BPM. Длинный overlap
MODE = "simple"       # equal-power crossfade. НЕ hpss -- LR4 bass swap ломает джаз
                      # (corr=nan на jazzy basslines -> phase cancellation)
TAIL_FADE_BARS = 0    # не нужен -- simple mode и так плавный
RAMP_SEC = 15         # BPM ramp-back 15s (если BPM разный)
MAX_SHIFT_SEC = 0.05  # micro-align +-50ms
USE_QUIET_EXIT = True # выходить на тихих секциях
TARGET_LUFS = -14.0   # стандарт
```

## Known Issues & Fixes

### 1. warp_to_grid zero-padding (CRITICAL)
**Проблема**: `fix_ht()` расширяет downbeats в beats (x4). `warp_to_grid` получает `s_db[:cf_bars+1]` = 16 BEATS (~11s), а `cf_len` = 16 BARS (~45s). `pt()` zero-pads остаток -> 34s тишины в slave zone.
**Симптом**: "fadeout then sudden new track" на каждом переходе.
**Фикс**: для `mode='simple'` bypass warp -> `s_zone = pt(slave_zone, cf_len)`, `consumed = min(cf_len, len(slave_zone))`.
**Статус**: исправлено в `/tmp/jazz2026/smart_mixer_jazz.py`, НЕ в `/opt/` main.

### 2. BPM mismatch > 8% -> direct cut
**Проблема**: микшер делает hard cut без фейда при BPM разнице > 8%.
**Пример**: Zasypaju (72 BPM) -> Dymka (85 BPM) = 18% -> hard cut -> 4s silence.
**Рекомендация**: ставить трек с отличающимся BPM первым или последним в миксе.

### 3. entry_bar skip
**Проблема**: `first_active()` может пропустить большую часть трека (entry_bar=32 = 90s skip на 2-min track).
**Для джаза**: джаз лупы часто начинаются тихо (BUILD), и `first_active` скипает интро.
**Рекомендация**: если трек < 3 min, ограничить entry_bar до первых 20% длительности.

## Track Selection Tips
- Сортировать по тональности (Camelot), не по BPM (все примерно одинаковые)
- Трек с другим BPM -> в начало или конец
- Для лупов: 2-3 минуты = норма, overlap 45s = почти половина трека
- Minor keys звучат лучше для chill/night атмосферы

## Reference Mix
NIGHT DRIFT v5: 10 tracks, 17:20, 85 BPM, d minor / g minor
