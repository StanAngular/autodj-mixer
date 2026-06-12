# Afro House

## BPM Range
118-128 BPM (typical: 120-125)

## Mixing Style
Ритмически сложный жанр. Перкуссия многослойная (congas, shakers, djembe поверх kick+hat). Сведение по бочке + перкуссии. Longer transitions work well -- tracks are groovy and layer naturally.

## Recommended Parameters

```python
CF_BARS = 16          # 16 баров = ~32s при 122 BPM
MODE = "hpss"         # LR4 3-band bass swap -- работает хорошо на четких kicks
TAIL_FADE_BARS = 2    # небольшой tail fade
RAMP_SEC = 15         # BPM ramp стандартный
MAX_SHIFT_SEC = 0.05  # micro-align +-50ms
USE_QUIET_EXIT = True # выходить на breakdowns
TARGET_LUFS = -14.0
```

## Known Issues & Fixes

### 1. Polyrhythmic confusion
**Проблема**: madmom может путать downbeats из-за conga/djembe patterns. Аннотация на перкуссии вместо kick.
**Фикс**: проверять аннотации вручную. Если BPM определяется как 60-65 вместо 120-125 -- madmom посчитал каждый второй удар.
**Рекомендация**: использовать madmom RNN (не librosa), он лучше на сложных ритмах.

### 2. Bass swap на sub-bass
**Проблема**: afro house часто имеет deep sub-bass lines. LR4 bass swap на 150Hz может резать нижние частоты.
**Рекомендация**: crossover frequency 120Hz вместо 150Hz для afro.

### 3. Percussion overlap
**Проблема**: два набора перкуссий одновременно = каша.
**Рекомендация**: сводить в breakdowns (когда перкуссия уходит), не в busy секциях.

## Track Selection Tips
- BPM разброс обычно маленький (120-125), все хорошо миксуются
- Camelot важен -- гармонические конфликты слышны на длинных bass lines
- Energy flow: начать с percussion-heavy, двигаться к melodic, вернуться к percussion
- African vocal samples не конфликтуют -- можно оставлять overlap

## Reference Mix
Afro house mix: madmom annotations через external service (бесплатный). Результат лучше librosa.
