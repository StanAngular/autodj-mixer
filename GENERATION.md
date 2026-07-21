---
name: autodj-generation
category: audio-production
description: >-
  Music generation guide for AutoDJ-Mixer. Standalone synth scripts, JSON-driven
  engine, DSP modules reference, and how generated tracks plug into the mix pipeline.
triggers:
  - "создай трек", "сгенерируй трек", "render", "синтезируй"
  - synth909, synthcore, nature_synth, render_indie_techno
  - "новый трек", "техно", "ambient", "meditation", "breakbeat", "trance"
  - styles/*.json, music_engine, hum2midi
tags: [audio, generation, synthesis, synth909, ambient, techno, render]
---

# AutoDJ — Music Generation Guide

**Canonical copy:** `/opt/autodj-mixer/GENERATION.md`
**Last synced:** 2026-07-20
**Audience:** ClaudeClaw, Hermes, любой агент создающий музыку через autodj-mixer

Пайплайн миксера (SKILL.md) берёт чужие треки и соединяет их.
Этот гайд — про **создание своих треков с нуля** через математический синтезатор.

---

## §1 — АРХИТЕКТУРА ГЕНЕРАЦИИ

Два режима, одна кодовая база:

```
Режим A: render_*.py (standalone)
  └─ python3 render_dark_matter.py → output/dark_matter.mp3
  Плюсы: быстрый старт, жёстко закодированная структура (8 актов и т.д.)
  Минусы: чтоб изменить надо редактировать .py

Режим B: styles/*.json + engine.py (JSON-driven)
  └─ python3 render.py styles/cosmic_techno.json → shared/rework/...mp3
  Плюсы: без кода, Гермес/любой агент пишет JSON → новый трек
  Минусы: ограничен элементами что понимает engine.py
```

**Синтез всегда математический** — никаких sample файлов, только numpy/scipy.

```
autodj/generate/
  synth909.py       TR-909 барабаны (kick, snare, hat, clap, tom, rim)
  synthcore.py      Осцилляторы, фильтры, огибающие, эффекты
  nature_synth.py   Природные текстуры (дождь, сверчки, лягушки, ветер, песок)
  engine.py         Оркестратор для styles/*.json
  hum2midi.py       Голос → MIDI (ещё в разработке)
  backends/
    fluidsynth.py   SoundFont рендер (SPEC 008, не готов)
    dawdreamer.py   VST3 хостинг (SPEC 008, не готов)
```

---

## §2 — СИНТЕЗАТОРНЫЕ МОДУЛИ

### synth909.py — TR-909 барабаны

Все функции возвращают `float32 mono` нормализованный до -6 dBFS.

```python
from autodj.generate.synth909 import (
    kick_909, snare_909, hihat_c_909, hihat_o_909,
    clap_909, tom_909, rim_909,
    drum_hit,     # кэшированный лукап по имени
    render_drums, # список событий → стерео буфер
)

# Имена для drum_hit(): "kick"/"k"/"bd", "snare"/"s"/"sd",
#   "hat_c"/"hc"/"chh", "hat_o"/"ho"/"ohh", "clap"/"cl",
#   "tom"/"t", "rim"/"r"

# kick: синус с свипом частоты 155→50 Hz + сатурация (tanh)
kick_909(sr=44100, decay_ms=550, start_hz=155, end_hz=50,
         sweep_ms=80, click_db=-8, punch=2.2)

# snare: 185 Hz тон + полосовой шум 800-8000 Hz
snare_909(sr=44100, tone_hz=185, tone_decay_ms=250,
          noise_decay_ms=130, tone_mix=0.55)

# hat closed: шум 5.5-17 kHz + металлические тоны
hihat_c_909(sr=44100, decay_ms=60)
hihat_o_909(sr=44100, decay_ms=380)  # открытый = длиннее

# clap: 4 слоя шума + comb reverb
clap_909(sr=44100, layers=4, layer_gap_ms=8, reverb_ms=200)

# render_drums: главная функция для трека
events = [(time_s, "kick", velocity), ...]  # velocity 0-127
buf = render_drums(events, total_samples, sr=44100, stereo=True)
# → (total_samples, 2) float32
# kick → центр, snare → слегка влево, hats → вправо
```

---

### synthcore.py — осцилляторы, фильтры, эффекты

```python
from autodj.generate.synthcore import (
    sawtooth_bl, square_bl, sine_wave, supersaw,
    midi_to_hz, adsr,
    lpf, hpf, lpf_sweep,
    acid_bass_note, pad_note, render_chord,
    apply_reverb, apply_delay, apply_chorus, apply_compressor,
    make_section_envelope, mono_to_stereo, apply_envelope_stereo,
    mix_into, master_chain,
)
```

**Осцилляторы** (все → float32 mono):
```python
# Пилообразная через wavetable (быстро: 0.08s для 10s при 7 голосах)
sawtooth_bl(freq_hz, n_samples, sr=44100)
square_bl(freq_hz, n_samples, sr=44100)   # + 8x LPF anti-alias
sine_wave(freq_hz, n_samples, sr=44100, phase_offset=0)
supersaw(freq_hz, n_samples, sr=44100, detune_cents=12, n_voices=7)
# 7 расстроенных голосов, случайные фазы, суммируются и фильтруются

midi_to_hz(note)  # 69 → 440.0, 57 → 220.0 (A2)
```

**ADSR огибающая**:
```python
env = adsr(attack_ms, decay_ms, sustain_db, release_ms, dur_s, sr)
# sustain_db: -6 = 0.5, -12 = 0.25, -20 = 0.1
# возвращает float32 array длиной int(dur_s * sr)
```

**Фильтры**:
```python
lpf(x, cutoff_hz, q=0.707, sr=44100)   # Butterworth 2nd order
hpf(x, cutoff_hz, sr=44100)
# Временно-переменный LPF: экспоненциальный свип по segments участкам
lpf_sweep(x, start_hz, end_hz, sr=44100, segments=32)
```

**Готовые инструменты**:
```python
# TB-303 стиль: пила + filter envelope + overdrive (tanh)
acid_bass_note(midi_note, dur_s, sr=44100,
               cutoff_start=800, cutoff_end=200,
               resonance_q=4.0, accent=False, slide=False)

# Supersaw пад: медленная атака + LPF + широкое расстройство
pad_note(midi_note, dur_s, sr=44100,
         attack_ms=800, cutoff_hz=2000,
         detune_cents=15.0, n_voices=7)

# Несколько нот вместе (нормализуется по количеству)
render_chord(midi_notes=[45,48,52], dur_s=2.0, osc_fn=pad_note)
```

**Эффекты** (через Pedalboard, работают с mono и stereo):
```python
apply_reverb(x, sr=44100, room_size=0.6, wet=0.3, damping=0.5)
apply_delay(x, sr=44100, delay_ms=375, feedback=0.35, wet=0.25)
apply_chorus(x, sr=44100, rate_hz=0.5, depth=0.25, wet=0.4)
apply_compressor(x, sr=44100, threshold_db=-12.0, ratio=4.0,
                 attack_ms=5.0, release_ms=100.0)
```

**Секции и микширование**:
```python
# Косинусный crossfade между секциями
env = make_section_envelope(
    total_samples,
    [(start_s, end_s, peak_gain), ...],
    sr=44100, crossfade_bars=4, bpm=133.0
)

# Mono → Stereo (constant-power panning, pan: -1 лево, +1 право)
stereo = mono_to_stereo(mono_buf, pan=0.0)

# Применить огибающую к стерео буферу
apply_envelope_stereo(stereo_buf, env)

# Добавить src в dest со сдвигом
mix_into(dest, src, gain=1.0, offset=0)

# Финальная цепь мастеринга
mix = master_chain(mix, sr=44100)
# soft clip (tanh) → compressor(-6dB, ratio=2.5) → normalize(-0.5dB)
```

---

### nature_synth.py — природные текстуры

```python
from autodj.generate.nature_synth import (
    rain, crickets, frogs, wind_gust, sand_on_glass
)

# Дождь: полосовой шум (150-5000 Hz) + капли
rain(n_samples, sr=44100, intensity=0.5, seed=0)
# → (n_samples,) float32 mono

# Сверчки: несколько сверчков, AM модуляция, шумовые ворота
crickets(n_samples, sr=44100, n_crickets=8, seed=0)
# → (n_samples,) float32 mono

# Лягушки: синусоидальные пульсы с паузами
frogs(n_samples, sr=44100, n_frogs=5, seed=0)
# → (n_samples,) float32 mono

# Порыв ветра: полосовой шум + двойной LFO
wind_gust(n_samples, sr=44100, seed=0)
# → (n_samples,) float32 mono

# Песок на стекле: векторизированный, зернистость + стеклянный резонанс
sand_on_glass(n_samples, sr=44100, density=0.5, pan_speed=0.3, seed=0)
# → (left, right) tuple из float32 arrays — уже стерео!
```

**Для длинных треков (>5 мин) рендери кусками по 30-60s**, иначе RAM:
```python
# Пример: 60 минут по 30s кускам
with sf.SoundFile(out_wav, 'w', samplerate=SR, channels=2) as f:
    for ci in range(n_chunks):
        l, r = sand_on_glass(chunk_n, SR, density=0.5, seed=ci)
        f.write(np.column_stack([l, r]))
```

---

## §3 — RENDER СКРИПТЫ (режим A)

Все жёстко закодированы. Запуск: `python3 /opt/autodj-mixer/render_XXXX.py`
Вывод: `/opt/autodj-mixer/output/XXXX.mp3`

| Скрипт | Название | Длина | BPM | Тональность | Описание |
|--------|----------|-------|-----|-------------|----------|
| `render_indie_techno.py` | Midnight Loop | 15:00 | 142 | Am | Minimalist, dry drums, Berlin sequencer, whispers, dub section |
| `render_dark_matter.py` | Dark Matter | 12:00 | 138 | Dm | 8 актов, hard techno→breakbeat hybrid, distorted 808 kick |
| `render_dark_cosmic.py` | Void Protocol | ~8:00 | 134 | Dm | Cosmic atmosphere, acid 303, stereo rotation texture |
| `render_meditation.py` | Starlight Meadow | 60:00 | 72 | Am | Дождь+сверчки+лягушки, 8 мелодических периодов, chunk-рендер |
| `render_tribal_psychedelic.py` | Sand Ritual | 7:00 | 92→128 | Am | Ускоряющийся BPM, африканские барабаны, песок на стекле |
| `render_cosmic_massage.py` | Cosmic Massage | ~7:00 | ~95 | Am | Acid jazz downtempo |
| `render_zaycev_trance.py` | Зайцев Trance | ~10:00 | — | — | Мелодия "Бриллиантовая рука", FluidSynth |
| `render_deep_trance_zaycy.py` | Deep Trance | ~10:00 | — | — | Версия 2 |
| `render_xenolith.py` | Xenolith | — | — | — | Experimental |

**Когда писать новый render_*.py:** жанр требует специфической структуры (акты, своя ритмика, не вписывается в engine.py). Копируй `render_dark_matter.py` как шаблон.

---

## §4 — JSON-DRIVEN ENGINE (режим B)

Новый трек без кода:

```bash
# Редактируй / создай styles/my_style.json
# Запуск:
python3 /opt/autodj-mixer/render.py styles/my_style.json
```

**Формат styles/*.json:**
```json
{
  "meta": {
    "title": "My Track",
    "bpm": 128,
    "key": "Am",
    "duration_s": 360,
    "out": "shared/rework/my_track.mp3",
    "seed": 42
  },
  "elements": {
    "drone":   { "active": true, "freq": 36.71 },
    "texture": { "active": true, "lp_cut": 3000, "hp_cut": 400 },
    "pad": {
      "active": true,
      "chords": [
        [110.0, 130.81, 164.81],
        [87.31, 110.0, 130.81]
      ]
    },
    "acid": {
      "active": true,
      "patterns": [{
        "freqs": [73.42, 73.42, 103.83, 73.42],
        "amp_auto": "acid_amp",
        "cut_scale": 1.0,
        "gain": 0.58
      }]
    },
    "drums": {
      "active": true,
      "kick": true,
      "snare": true,
      "hats": true
    }
  }
}
```

**Существующие стили:**
- `cosmic_techno.json` — 133 BPM, Dm, кислотный техно
- `melodic_house.json` — 124 BPM, Am, мелодик хаус
- `melodic_house_cafe.json` — тише, для фона
- `dark_industrial.json` — тёмный индастриал
- `cyberpunk_breakbeat.json` — брейкбит
- `jazz_lounge.json` — джазовый лаундж
- `cafe_downtempo.json` — даунтемпо

---

## §5 — КАК СОЗДАТЬ ТРЕК: ПОЛНЫЙ ПАЙПЛАЙН

### Быстро (JSON, 5 минут)
```bash
cd /opt/autodj-mixer
# Скопируй ближайший стиль:
cp styles/cosmic_techno.json styles/my_dark_house.json
# Поправь bpm, key, duration_s, freq в pad.chords, acid.freqs
nano styles/my_dark_house.json
python3 render.py styles/my_dark_house.json
# → shared/rework/my_dark_house.mp3
```

### Полноценный (Python, для сложных жанров)
1. Скопируй ближайший render_*.py как шаблон
2. Определи: BPM, тональность, продолжительность
3. Настрой константы вверху (BAR_S, STEP_S, TOTAL, секции)
4. Напиши drum pattern как 16-step velocity массивы
5. Напиши build_* функции для каждого слоя
6. Собери mix_into() в main() с gain-структурой
7. Запусти, слушай, итерируй

### Структура типичного render_*.py
```python
SR = 44100
BPM = 142.0
DUR = 900.0        # секунды
BAR_S = 60/BPM*4
STEP_S = BAR_S/16  # 16th note
TOTAL = int(DUR*SR)

# Секции: всегда пересекаются (cosine crossfade)
S_INTRO   = (0.0, 90.0)
S_GROOVE  = (75.0, 300.0)  # начинается раньше конца INTRO

def build_drums(): ...   # → (TOTAL, 2)
def build_bass(): ...    # → (TOTAL, 2)
def build_pad(): ...     # → (TOTAL, 2)

def main():
    drums = build_drums()
    bass  = build_bass()
    pad   = build_pad()

    mix = np.zeros((TOTAL, 2), dtype=np.float32)
    mix += drums * 0.80
    mix += bass  * 0.60
    mix += pad   * 0.35

    mix = np.clip(mix, -3.0, 3.0)
    mix = master_chain(mix, SR)
    sf.write("output/my_track.wav", mix, SR)
    os.system('ffmpeg -y -i output/my_track.wav -b:a 256k output/my_track.mp3')
```

---

## §6 — GAIN STRUCTURE (референс)

Типичные уровни при сложении 8-10 слоёв:

| Слой | Gain | Примечание |
|------|------|------------|
| Drums (909) | 0.75-0.85 | Главный элемент |
| Sub bass (сайдчейн) | 0.55-0.65 | Ducked на kick |
| Acid/analog bass | 0.45-0.60 | LPF + comp |
| Pad (supersaw) | 0.30-0.45 | Reverb → тихо |
| Synth stabs | 0.35-0.50 | Короткие → могут быть громче |
| Sequencer/arp | 0.35-0.45 | Слегка вправо |
| Whispers/vocals | 0.25-0.35 | Reverb, атмосфера |
| Природные текстуры | 0.10-0.20 | Всегда фон |
| Dub FX | 0.25-0.40 | Только в нужных секциях |

Safety clip перед master_chain: `np.clip(mix, -3.0, 3.0)`
Финальная нормализация: master_chain нормализует до -0.5 dBFS.

---

## §7 — УСКОРЯЮЩИЙСЯ ТЕМП (tribal/psychedelic)

```python
# BPM(t) = BPM_START + rate * t
# Позиция бита = интеграл BPM(tau)/60 dtau
# Квадратное уравнение: a*t^2 + b*t + c = 0
# a = rate/120, b = BPM_START/60, c = -beat_number

def compute_beat_times(bpm_start=92, bpm_end=128, dur=420):
    rate = (bpm_end - bpm_start) / dur
    beat_times = []
    beat = 0
    while True:
        a = rate / 120.0
        b = bpm_start / 60.0
        c = -float(beat)
        disc = b*b - 4*a*c
        if disc < 0:
            break
        t = (-b + np.sqrt(disc)) / (2*a)
        if t > dur:
            break
        beat_times.append(t)
        beat += 1
    return np.array(beat_times)
```

---

## §8 — ИНТЕГРАЦИЯ С MIX PIPELINE

Сгенерированный трек можно подать в mixer как обычный трек:

```bash
# 1. Сгенерируй WAV
python3 render_dark_matter.py
# → output/dark_matter.wav

# 2. Скопируй в shared/tracks/
cp output/dark_matter.wav shared/tracks/dark_matter_LOCAL.wav

# 3. Аннотируй (madmom downbeats)
python3 annotate_tracks.py shared/tracks/dark_matter_LOCAL.wav

# 4. A1F анализ
python3 a1f_analysis.py shared/tracks/dark_matter_LOCAL.wav

# 5. Добавь в tracklist как обычный трек
# Теперь smart_mixer.py увидит его с правильными
# beat/downbeat/structure данными
```

**BPM и Camelot** сгенерированных треков известны точно (в коде), не нужно детектировать.

---

## §11 — MUSIC PRODUCTION MANIFESTO (композиция + DSP правила)

**Полный текст:** `/opt/autodj-mixer/AI_MUSIC_MANIFESTO_v2.1.md` (42 KB, теория + практика).
Ниже — выжимка, обязательная к применению при генерации нового трека.

### 11.1 — Гармония (Модуль 1)
- Никогда случайные ноты. Аккорды — циклами 4/8 тактов из словаря:
  минор `[i–VI–III–VII]`, `[i–v–iv–i]`, `[VI–VII–i–i]`.
  Расширения: вторичная доминанта `[i–V/v–v–i]`, модальный интерчейндж `[i–IV–v–i]`, плагальный каданс `[iv–i]` (медитативные концовки).
- Голосоведение: общие ноты между соседними аккордами держатся на месте, максимальная дельта для пэдов/аккордов — 4 полутона (никаких скачков на октаву).
- Бас — исключение из правила голосоведения: может скакать на кварту/квинту (функция корня), контрапунктически к мелодии (мелодия вверх → бас вниз/тоника).

### 11.2 — Фразировка солистов (Модуль 2)
- Мелодия = period-структура: Фраза 1 (вопрос, 2 такта, восходящая, финиш на 2-й/5-й ступени) → Фраза 2 (ответ, 2 такта, тот же ритм, нисходящая, финиш на тонике долгой нотой).
- На 8 тактов: вторая пара фраз повторяет контур первой со сдвигом (терция/квинта вверх).
- Обязательная тишина: ни один солист не играет 4 такта без пауз — последние 2 доли 4-го такта = тишина ("вдох").
- Евклидовы ритмы для перкуссии/аккомпанемента: (3,8)=тресильо, (5,16)=босса-нова, (7,12)=афро-колокол — параметры (шаги, удары, сдвиг) вместо ручной прописи.
- One-shot/текстурные звуки (Water Drop, Ice Crystal, Wind Chime, Breathing Drone, Binaural Pad) — НЕ мелодические. Call-and-Response к ним неприменим. Генерировать стохастически, 1-2 раза за квадрат, не выстраивать мелодическую линию.

### 11.3 — Частоты и маскирование (Модуль 3)
- MIDI 24-36 (C1-C2): только Sub-Bass. MIDI 36-48 (C2-C3): Mid-Bass/левая рука пиано.
- Плотный Sub-Bass есть → оркестровые инструменты (Cello, Piano) получают LP ниже 150 Гц.
- Комплементарный EQ на конфликтующих парах: усилил одного на частоте X → ослабь второго на X, усиль на соседней.
- Sidechain точечно (кик↔саб/пэд, не на весь микс): −50-80% громкости, release 100-200мс.
- Чек-лист после рендера: баланс → конфликтные пары → HP на всё небасовое → комплементарный EQ → панорама → точечный сайдчейн → проверка в моно.

### 11.4 — Грув и хьюманизация (Модуль 4)
- Velocity никогда constant 100/127. Hi-hat/shaker паттерн по доле: сильная~90 → слабая~40 → средняя~70 → слабая~40, ± 5-15% случайной вариации (не больше — избыточная случайность = неряшливость, не человечность).
- Piano (FluidSynth): Velocity ≤ 70-75 жёстко. Выше — резкий "ударный" тон.
- Kick/Sub-Bass: строго в сетку (0 мс, ритмический якорь).
- Snare/Clap/hats: смещение +3…+10 мс (позже=расслабленно, раньше=энергично).
- Аккорды (Piano/Pads): +5…+15 мс — эффект "ленивого" исполнения.
- Трактовать цифры как диапазоны для рандомизации вокруг паттерна, не константы.

### 11.5 — Пространство (Модуль 5)
- Reverb-матрица: Kick/Sub-Bass = 0.0 (сухие). Lead/Melody = 0.3-0.5+delay. Pads/Strings/Drones = 0.8-1.0.
- Частоты < 150 Гц — строго моно (совместимость с моно-суммированием клубных систем/радио/стриминга).
- Перкуссия/FX — широко разведены (L40%/R40%). Похожие тембры (piano/guitar) — противофазная панорама (L30/R30) как доп. инструмент против маскирования.

### 11.6 — Backend routing (3 яруса, не 2!)

| Бэкенд | Скорость | Тембры | Когда |
|---|---|---|---|
| **FluidSynth** | ~50× realtime | Piano(0), Celesta(8), MusicBox(10), Cello(42), Harp(46) | Всегда для акустики/оркестра |
| **DawDreamer FAUST** | ~10× realtime | supersaw, pluck, organ, bass_sub, fm_bell | Синт-тембры без VST3, предпочтительно перед Surge XT |
| **synthcore** (pure math) | ~5× realtime | Kick, Sub-Bass, Warm Pad, Drone, Binaural, Water Drop, Ice Crystal, Chime | Базис + текстуры (см §2) |
| **DawDreamer VST3 (Surge XT)** | ~0.7× realtime ⚠️ | Сложный Acid/FM | Крайний случай, дорогой рендер, требует явного патча (см `xenolith.py`) |

⚠️ **Ловушка имён:** `synthcore.supersaw()` и FAUST `"supersaw"` preset — два разных объекта с одинаковым названием. В JSON различать явно: `synth: "synthcore.supersaw"` vs `synth: "faust.supersaw"`.

### 11.7 — Gain Staging (полная таблица, дополняет §6)

| Слой | Volume (пик) | Обработка |
|---|---|---|
| Sub-bass | −12 dBFS | моно, центр |
| Kick | −14 dBFS | моно, центр |
| Cello | −14 dBFS | центр |
| Piano | −16 dBFS | стерео |
| Harp | −18 dBFS | стерео |
| Pad | −20 dBFS | стерео |
| Water/Chimes | −22 dBFS | стерео |
| Reverb send | −26 dBFS | aux |

Мастер-шина (Compressor 1.5-2:1 attack40/release500 → Limiter −1.0dBTP → Normalize −0.5dBFS) — в Режиме B применяется **автоматически движком**, агент её НЕ программирует. Не задирать Velocity как суррогат громкости — компрессор всё равно приведёт к финальным цифрам, а задранная velocity сломает внутренний баланс (например, Piano-лимит из §11.4).

### 11.8 — Порядок генерации (снижает противоречия между правилами)

```
1. Форма/структура → тактов, секции, длины циклов
2. Гармония → прогрессия (11.1) → голосоведение → контрапункт баса
3. Ритм-секция → Kick/Sub в сетку → опц. Евклидовы паттерны перкуссии
4. Мелодия/соло → period-структура (11.2) с обязательными паузами
5. Частотное распределение → MIDI-диапазоны по ролям (11.3)
6. Groove → velocity-паттерны + micro-shifting (11.4) — ПОСЛЕ того как ноты расставлены
7. Пространство/микс → reverb-матрица, стерео-ширина, сайдчейн, проверка в моно
```
Шаги 1-4 = композиция (что играть). Шаги 5-7 = продакшн (как звучит). Не смешивать в одном проходе.

### 11.9 — Область действия: Режим A vs Режим B

- **Режим A** (`render_*.py` standalone) — НЕТ allowlist. Любой numpy/scipy-алгоритм, произвольная логика/случайность. Все текущие треки (`cryogenesis.py`, `xenolith.py`, `neo_classical_spa.py` и т.д.) — Режим A.
- **Режим B** (`styles/*.json` + `engine.py`) — жёсткий allowlist из §11.6, gain staging из §11.7 автоматический, мастер-шина не программируется агентом.
- Перед генерацией уточнить у пользователя/себя, какой режим просят. "Напиши скрипт" = A. "Стиль/JSON" = B.

### 11.10 — Strict allowlist (Режим B только)

Запрещено выдумывать инструменты/пресеты вне таблицы 11.6. Нет тембра — сообщить об ограничении явно, предложить добавить пресет в `synthcore.py`/`nature_synth.py`, не имитировать несуществующий тембр экстремальным EQ на похожем пресете (визуально похожий JSON ≠ тот же звук).

---

## §9 — СИНХРОНИЗАЦИЯ СКИЛЛА

Canonical copy: `/opt/autodj-mixer/GENERATION.md`

Обновить из canonical:
```bash
cp /opt/autodj-mixer/GENERATION.md ~/.claude/skills/mixer/GENERATION.md
```

Обновить canonical из скилла:
```bash
cp ~/.claude/skills/mixer/GENERATION.md /opt/autodj-mixer/GENERATION.md
cd /tmp/autodj-push && git pull && cp /opt/autodj-mixer/GENERATION.md . && git add GENERATION.md && git commit -m "docs: sync GENERATION.md" && git push
```

Если Гермес что-то добавил в `/opt/autodj-mixer/` — подтяни оттуда.
Если ClaudeClaw что-то рендерил новое — обнови §3 (таблицу скриптов).

---

## §10 — CHANGELOG

| Дата | Изменение |
|------|-----------|
| 2026-07-20 | Создан GENERATION.md (ClaudeClaw). 9 render скриптов задокументированы. |
| 2026-07-21 | +§11 Music Production Manifesto v2.1 (гармония, фразировка, DSP, backend routing, allowlist) |
