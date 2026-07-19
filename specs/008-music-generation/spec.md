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

## Tasks (после Approve)
- [ ] G1: autodj/generate/ каркас + fluidsynth-бэкенд + 1 sf2 + рендер style.json
- [ ] G2: uborka resynth_v* → archive; styles-формат v2 (instrument_mapping)
- [ ] G3: hum2midi (basic-pitch) + квантование + e2e напев→трек
- [ ] G4: dawdreamer-бэкенд + Vital/Surge пресеты
- [ ] G5: doctor-проверки + доки установки банков/VST
