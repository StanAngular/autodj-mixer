# Hard Techno

## BPM Range
145-165 BPM (typical: 150-160)

## Mixing Style
Агрессивный, точный. Бочка -- главный элемент. Сведение СТРОГО по бочке, downbeat-to-downbeat. Два кика одновременно = грязь. Bass swap обязателен. Короткие-средние переходы.

## Recommended Parameters

```python
CF_BARS = 16          # 16 баров = ~25s при 155 BPM
MODE = "hpss"         # LR4 3-band bass swap -- ОБЯЗАТЕЛЕН для hard techno
TAIL_FADE_BARS = 2    # короткий tail
RAMP_SEC = 15         # BPM ramp стандартный
MAX_SHIFT_SEC = 0.03  # micro-align +-30ms (точнее чем джаз)
USE_QUIET_EXIT = True # выходить на breakdowns
TARGET_LUFS = -14.0
```

## Known Issues & Fixes

### 1. librosa vs madmom BPM detection
**Проблема**: librosa часто определяет BPM как половину (77.5 вместо 155). Это ломает весь микс -- warp stretch x2, артефакты, непопадание.
**Фикс**: ТОЛЬКО madmom для hard techno. `madmom.features.downbeats.RNNDownBeatProcessor` + `DBNDownBeatTrackingProcessor`.
**Проверка**: если BPM < 100 для hard techno трека -- это ошибка, умножить x2.

### 2. Bass polarity на distorted kicks
**Проблема**: hard techno kicks с сильным distortion дают нестабильную корреляцию.
**Фикс**: 5-point weighted consensus + kick band (60-120Hz) -- уже реализовано в smart_mixer v13+.

### 3. Speed glitch при BPM ramp
**Проблема**: BPM jump 164->108 в зоне Wintersong->Euphoria. Аварийное восстановление темпа.
**Фикс**: clamp BPM +-30% от медианы сета. Не допускать jumps > 20%.

### 4. Band cancellation (202 events в первом миксе)
**Проблема**: sub/mid фаза противопоставляется в crossfade -> провалы баса.
**Фикс**: adaptive sub crossfade (5 bars вместо 16), bass polarity inversion check.

### 5. Beat drift (100-1133ms в первом миксе)
**Проблема**: librosa annotations drift. Каждый переход 100-1000ms мимо.
**Фикс**: madmom RNN annotations. Drift должен быть < 20ms.

## Track Selection Tips
- BPM range 150-162 хорошо миксуется (8% threshold)
- Если трек 145 BPM а остальные 160 -- ставить первым или последним
- Camelot: SAME и ADJ дают лучший результат. POOR слышно сразу
- Energy: build-up tracks перед drops, не два drop трека подряд
- Distorted kicks + clean kicks = проблема при overlap. Группировать по стилю кика

## Reference Mixes
- EASTERN BLOC: 9 tracks, 36 min, Denis Dekay / Kagoriii / Klofama, 155-162 BPM
- v2 (original order): max drift 185ms, Camelot 1/8
- v3 (Camelot order): max drift 403ms, Camelot 4/8 (Euphoria disrupted flow)
