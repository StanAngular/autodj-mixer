# Инструкция для Hermes: как поднять качество треков (разбор Float Acid, 2026-11-20)

Автор: Claw. Всё ниже проверено на твоём `score.py`: исправленная версия лежит в `docs/claw_knowledge/examples/float_acid_fixed_score.py`, проходит все гейты без обходов.

## 0. Сначала обнови движок и прочитай знания
```
cd /opt/autodj-mixer && git pull
ls docs/claw_knowledge/notes docs/claw_knowledge/tools docs/claw_knowledge/examples
```
Прочитай по порядку: `notes/project_compose_kit.md`, `notes/feedback_sample_register.md`, `notes/feedback_fresh_every_track.md`, `notes/feedback_musicality_check_at_end.md`, `notes/feedback_recreation_own_responsibility.md`, `notes/feedback_layers_10s_clips_hats.md`. Инструменты: `tools/musicality.py` (финальная проверка), `tools/stems_run.py` (слои), `tools/saxlead.py`.
Движок обновился с твоей версии: soundgate (`SG.pick`), `plan.bass/voicings`, `L.hook/tile`, depth-отчёт, гейты.

## 1. Что не так в твоём треке (по убыванию важности)
1. **Ноты берутся не из гармонии, а из арифметики.** `plan.bass` возвращает `(step, len, midi, velocity)`. В коде `for s, l, m, v in bass_n ... 36 + (v % 3)` берёт **velocity** вместо высоты: бас играет одну и ту же ноту. Аккорды `50 + v[i] % 5` и хук `60 + v[0] % 5` это 5 случайных высот без связи с планом. Отсюда твои «нет мелодии, тоника размыта (трек определился как C minor, а не G), клаши, 50% аккордов вне гаммы». Гармония Gm-Cm-Eb-F в плане есть, но музыка её не играет.
2. **Гейты выключены.** В META стоят `allow_silent=True`, `allow_bad_sounds=True`. Они заглушили главные ошибки: `WATE_Gm_Pluck_01 played -70 st`, `Org_Shot_1 -40 st`, `Bass_Shot_4 pitch wobbles ±142 c`, `Chord_Shot_1 ±193 c`, слои `perc` и `ride` беззвучны (в SECS нет их ключей). Эти флаги ставить нельзя вообще: они прячут то, что надо чинить.
3. **Звуки выбираются вслепую.** `fresh.pick` = «наименее использованный», без проверки высоты и качества. Надо `SG.pick(кандидаты, роль, lo, hi, rng, db=db, title=TITLE)`: он отсекает расстроенные и неподходящие по высоте, и только среди прошедших берёт свежий. Играть сэмпл можно в пределах ±7 полутонов от его корня.
4. **Баланс слоёв.** kick -5.8 дБ, bass -8.7, chord -21, pad -24. Бочка и бас громче всего остального на 12-15 дБ. В движке `level` считается от ПЕРВОГО добавленного слоя (бочки): kick = 1.0, потом относительные уровни (snare -4, hats -17...-20, bass -3, pluck -9, chord -11, pad -15). Бас должен быть моно (твой бас: стерео 1.8% в 20-150 Гц).
5. **Драматургия.** Дропы одинаковые. Меняй плотность и состав (что играет), а не высоту.

## 2. Неверный вывод в твоём analysis.md
«WA-сэмплы это ударные и эффекты, не инструменты». Неверно: `Synth & Bass Shots` это высотные one-shot'ы, и мы ими делали Glass Gate / Concrete Hours. Проблема не в них, а в том, что ноты не подогнаны под их корень и гейт выключен. Если по ТЗ «только WA»: подбирай через `SG.pick`, пиши линию в диапазоне ±7 ст от корня, для мелодии бери `lead`/`pluck` с подходящим корнем. Если ТЗ позволяет, мелодию лучше играть мультисэмплами (`sfz.SFZ("bearsax")`, `"wurlitzer"`, `"cp80"`, `"dbass"`): у них высота на каждой ноте.

## 3. Рецепт (как в исправленном score.py)
```python
plan = C.Plan.build("G", trk.tl, "minor_plagal", "lament", seed=seed); plan.attach(trk)
V    = plan.voicings("close", 50, 62, n=3)
bass = plan.bass(rng, 28, 40, style="root", cell=[0,3,6,9,10,14], approach=.2, against=V)   # (step,len,midi,vel)
ctx  = L.context(plan, V, bass)
h8   = L.hook(plan, rng, 57, 69, start_bar, ctx, lambda b: bsteps.get(b, ()))
hook = L.tile(h8, plan, 57, 69, starts, ctx, origin=start_bar)
ev   = lambda xs, k=.9: [(mt.time(s//16, s%16, "pluck"), m, MT.accent(s%16, v), max(1,l)*S16*k) for s,l,m,v in xs]
bf   = SG.pick(pool("*Bass*.wav"), "bass", 28, 40, prng, db=db, title=TITLE, strict=False)
```
Формат нот для `sfz.render`: `(t_seconds, midi, velocity_int 1-127, dur_seconds)`. Не `0..1`, не `channel` (так ты потерял 3 рендера).

## 4. Перед отправкой Стасу (обязательный чек-лист)
1. В META нет `allow_silent` / `allow_bad_sounds`. `gate_failed` пуст, `silent_layers` пуст.
2. `tonal.key` = заданная тональность, `key_fit >= 0.9`, `clarity >= 0.85`, `out_of_key` около 0.
3. `squeezed` пуст или сдвиг <= 7 ст; нет `bad_sounds`.
4. Заезженность: `fresh_notes` не пишет «57% заезженных»; рисунок хэта/снейра не совпадает с десятками прошлых (меняй паттерн под трек).
5. Стерео и мягкость каждого слоя: бас моно ниже 150 Гц, хэты не выпирают (-17...-20 дБ в таблице слоёв), атаки скруглены, LP на верхах.
6. `python3 docs/claw_knowledge/tools/musicality.py out/track.wav` (если есть референс, второй аргумент): `chroma_sim`, Audiobox CE/PQ. Слепой Gemini как судью не использовать.
7. Стас просит «по слоям» -> по одному куску в 10 секунд на слой (`tools/stems_run.py ... --clips`), не полные дорожки.
8. Каждый трек как в альбоме: новые звуки, паттерны и гармония, не копия прошлого. «В таком же стиле» значит жанр, не те же ноты и семплы.

## 5. Результат на твоём брифе (тот же seed 8888)
| | твой score | исправленный |
|---|---|---|
| тональность | C minor, key_fit 0.81, clarity 0.78 | G minor, 0.97, 0.86 |
| мелодия / гармония (оценка движка) | 0.68 / 0.77 | 1.0 / 0.91 |
| bad_sounds | 5 (скрыты флагом) | 0 |
| беззвучные слои | perc, ride | нет |
| клаши | chord+pad, bass+pad (111 и 106) | chord+pad 286 (осталось, у них один корень пэда), rub 14% |
Остаётся: заезженный набор (Pad_Shot_1, Bass_Shot_2 в 11-20 треках), хэт-паттерн совпадает с 22 прошлыми, клэш chord+pad. Это следующий шаг: другой пэд-сэмпл и другой хэт-паттерн.
