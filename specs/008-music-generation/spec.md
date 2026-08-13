# SPEC 008: Music Generation — от синтеза к настоящему звучанию

## Цель
Генерация треков ПРОФЕССИОНАЛЬНОГО звучания (классика/попса/андеграунд-электроника),
включая: напев голосом → та же мелодия в электронном треке. Уйти от примитивизма
базовых волн music_engine.

## Требования
1. **Бэкенд A — FluidSynth+SoundFonts** (первый): pyfluidsynth+mido, банки sf2
   (Sonatina оркестр, GeneralUser GS); headless на VPS; рендер MIDI→WAV.
2. **Бэкенд B — Dawdreamer VST3** (второй слой): бесплатные Vital/Surge XT/Dexed;
   профессиональная электроника; graceful fallback на A, если VST недоступен.
3. **hum2midi**: запись голоса → basic-pitch (или librosa.pyin) → MIDI → квантование
   к сетке/тональности (Camelot-стек уже есть) → рендер любым бэкендом.
4. **styles/*.json = партитура**: instrument_mapping per-channel
   {type: soundfont|vst_instrument, path, params} (формат из гайда) — расширение
   существующих styles без слома.
5. Полочка `autodj/generate/` (по REFACTORING_PLAN): engine.py (диспетчер бэкендов),
   backends/{fluidsynth,dawdreamer}.py, hum2midi.py; music_engine остаётся бэкендом
   «synth» (fallback). studio_resynth_v1-3 → одна версия, остальное в archive/.
6. Изоляция сохраняется: генерация НЕ вмешивается в микс-пайплайн; выход-WAV может
   входить в него как обычный трек (annotate→A1F→mix) — вот и интеграция.

## Acceptance (прослушка Стаса)
- [ ] Оркестровый стиль НЕ звучит «midi-пищалкой» (реальные сэмплы).
- [ ] Электронный стиль: жирный бас/пады уровня VST, не голая пила.
- [ ] Напев (30-60с) → узнаваемая та же мелодия в рендере, в сетке и тональности.
- [ ] doctor показывает: fluidsynth, sf2-банки, dawdreamer, basic-pitch.
- [ ] 543+ тестов зелёные; пайплайн микса не тронут.

## Edge cases
Нет sf2/VST → честный отказ с подсказкой установки; шумный напев → доверительный
порог pitch-трекинга, отчёт «не распознал»; полифонический напев → берём верхний голос.


## S — уроки live-coding (Strudel/TidalCycles, dj_dave), P80
Разбор её кода: `s("~ oh").bank("akailinn, alesissr16")`, `.bank("RolandTR808")`,
`.struct("x - - x - - x - - - x - x - x -")`, `<d#3 g#2>`, `!4`, `.fast(4)`,
`.begin(0.1).end(0.3)`, `.chop(4)`, `.room(sine.range(0.2,0.75))`, `supersaw.detune(1)
.distort(1)`. Почему у неё «нормальный звук», а у нас примитив:
1. **Сэмплы вместо математики.** У неё барабаны — записи живых драм-машин (TR-808,
   AkaiLinn, AlesisSR16, DMX). У нас `synth909.py` прямо пишет: «All sounds synthesized
   from first principles (no samples needed)». 808-ю формулами не заменить. → S1.
2. **Вариативность встроена в ЗАПИСЬ паттерна**: `<a b>` меняет звук по циклам, `?` —
   вероятность, `!n`/`*n` — повторы/дробление. Музыка «дышит» без ручной аранжировки
   каждой секции — это лечит наше «статичные паттерны, сочиняет средне». → S2.
3. **Обработка на уровне события**: begin/end/chop/speed/clip + модуляция параметров
   (`sine.range`), а не один эффект на весь слой. → S3.

- [x] **S1 сэмплер** (P80): `autodj/generate/sampler.py` — банки драм-машин
      (`git clone ritchse/tidal-drum-machines` или `tidalcycles/Dirt-Samples`, путь в
      env SAMPLE_BANKS), псевдонимы Strudel (bd/sd/hh/oh/cp…), round-robin вариаций
      (два одинаковых удара подряд не звучат), begin/end/speed/gain/pan.
- [x] **S2 мини-нотация** (P80): `autodj/generate/mininotation.py` — `"bd*2 <sd cp> hh?"`,
      `!n`, `[a b]`, struct-строки; развёртка на циклы даёт РАЗНЫЙ результат каждый цикл.
- [ ] **S3 событийная обработка**: chop/clip + модуляция параметров (sine.range) на
      уровне события, не слоя.
- [x] **S4 барабаны сэмплами** (P81): `instrument.render_drums()` — ЕДИНАЯ точка, через
      которую идут все барабаны — теперь играет сэмплы живых драм-машин, если банки стоят
      (env SAMPLE_BANKS), а GM-кит FluidSynth остаётся fallback'ом (это он давал «midi»-
      призвук). velocity→gain нелинейно (gamma 1.2, как у железа), round-robin вариаций.
      Банк выбирается: `GenreConfig.drum_bank` → env DRUM_BANK → RolandTR909.
      В логе видно, каким путём пошло: «drums: сэмплы банка RolandTR909».

## Tasks (после Approve)
- [x] **Q2 секционная аранжировка** (P82): `autodj/generate/arrangement.py` — трек =
      последовательность секций (intro→build→drop→breakdown→build→drop→outro,
      `default_plan` по длине трека). Секции отличаются СОДЕРЖИМЫМ, не громкостью:
      в интро нет снейра, в брейкдауне УХОДИТ КИК, в дропе полная плотность + ghost-удары
      (тихие снейры между долями); ФИЛЛ по томам в последнем такте перед каждой сменой.
      Врезано в `render_track` одной точкой — аранжируется hit-лист ДО озвучки; в логе
      печатается план. `GenreConfig.arrange=False` отключает.
- [x] **Q2b структура для мелодических слоёв** (P83): `section_gain_envelope` —
      лид молчит в интро, пад ведёт брейкдаун, бас там же проваливается; стыки сглажены
      (без щелчков). Умножается на существующий `rcos_env` (тот отвечает за общие
      вход/выход трека, новая — за структуру ВНУТРИ). Раньше слои жили одним фейдом на
      весь трек — это и было «кроссфейд вместо аранжировки».
- [ ] G1: autodj/generate/ каркас + fluidsynth-бэкенд + 1 sf2 + рендер style.json
- [ ] G2: uborka resynth_v* → archive; styles-формат v2 (instrument_mapping)
- [ ] G3: hum2midi (basic-pitch) + квантование + e2e напев→трек
- [ ] G4: dawdreamer-бэкенд + Vital/Surge пресеты
- [ ] G5: doctor-проверки + доки установки банков/VST
