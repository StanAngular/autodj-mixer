# autodj.compose: как сочинять трек из сэмплов (для Hermes)

Версия 2026-11-18, движок `/opt/autodj-mixer` на коммите `64b5aa0` (origin/main).
Пишет Claw. Ниже то, что реально работает сейчас, с путями и вызовами.

## 0. Последний апдейт (что поменялось, какие ТВОИ файлы затронуты)

Коммиты 2026-11-17..18 (все запушены):

| Коммит | Что |
|---|---|
| `afe8c03` P137 | консонантная гармония по умолчанию в `chords.Plan.build`, отчёт `tonal.py` (`tonal_notes` в сводке) |
| `656c294` P139 | `soundgate.py`: замер звука до использования (расстройка, плавание высоты, шум, нота/аккорд, регистр), гейт `bad_sounds` |
| `81c9bfd` | `fresh.pick` снова строго «наименее использованный» (гибкую свежесть убрали по слову Стаса) |
| `0a6f024` | 8 новых мультисэмплов в `sfz.LIBS` (см. п. 3) |
| `f37e979` P140 | щелчок: дак «по часам» опускается за 0.5 мс, края сэмплов сглаживаются, `clicks.py` показывает, где рвётся волна |
| `51128ef` P141 | `evolve.py`: запись играется как инструмент (держание, легато, ансамбль, зёрна) |
| `48642f5` P142 | `blueprint.py`: план референса в числах, `compare`, `match_eq` |
| `64b5aa0` P143 | `docs/COMPOSE_VECTOR.md`: план развития и ответы на 11 вопросов |

**Твои файлы, которые изменил P140** (правка одна и та же, смысл не меняется):
- `club_rework.py` → `sidechain_duck(..., attack_ms=0.5)`
- `club_underlay.py` → `sidechain_duck(..., attack_ms=0.5)`
- `autodj/generate/mixbus.py` → `sidechain_duck(..., attack_ms=0.5)` + новая `duck_attack()`

Раньше громкость падала за один сэмпл на каждой доле и давала щелчок в верхах. Теперь падение длится 0.5 мс и заканчивается ровно на доле, качание то же. Старое поведение: `attack_ms=0`. Тесты: 1123 passed, 0 failed.

## 1. Запуск

Трек = один файл `score.py` с функцией `build(seed) -> Track` и словарём `META`.

```sh
cd <папка трека>
PYTHONPATH=/opt/autodj-mixer python3 -m autodj.compose run score.py --name my_track --title "Название (стиль)" [--seed 7] [--send]
```

- Без `--seed` зерно берётся из `--name` (crc32). Тот же seed = та же музыка (для вариаций одного трека).
- Выход: `out/<name>.mp3`, `out/<name>.summary.json` (все замеры), `out/<name>_raw.json`.
- Код выхода 3 = провален жёсткий гейт (беззвучный слой, плохой звук); mp3 всё равно пишется, `--send` блокируется.
- `META`: `title`, `genre`, `key`, `target` (LUFS, обычно -14), `master` ("warm"), `lead` (имя слоя мелодии), `story`; опции `allow_silent`, `allow_bad_sounds`, `gates`.

## 2. Скелет партитуры

```python
import os, glob, numpy as np
from autodj.compose import Track, pb, load_sample, fresh, chords as C, lines as L, microtiming as MT, sfz, soundgate as SG
from autodj.compose.sfz import SFZ
from autodj.compose.bus import glue
from pedalboard import Pedalboard, HighpassFilter, LadderFilter
LP24 = lambda f: LadderFilter(mode=LadderFilter.Mode.LPF24, cutoff_hz=f, resonance=0.0)

META = {"title": "Name (style)", "genre": "deep house", "key": "Am", "target": -14.0, "master": "warm", "lead": "hook"}
SECS = [(0, 8, "intro", dict(pad=1, hats=.5)), (8, 24, "home1", dict(kick=1, bass=1, pad=.7, hook=1)),
        (24, 32, "break", dict(pad=1.3, hook=1)), (32, 48, "home2", dict(kick=1, bass=1, pad=.7, hook=1)), (48, 56, "outro", dict(kick=1, pad=1))]
# имена частей определяют роль в гармонии: intro*, home*, journey*, break*, build*, outro*

def build(seed):
    trk = Track(122, 56, seed=seed, tail_s=4).sections(SECS); trk.step_env = True
    S16, T = trk.S16, trk.N / trk.sr; mt = MT.Ensemble(trk, seed); db = fresh.load(); title = META["title"]
    plan = C.Plan.build("A", trk.tl, "minor_plagal", "lament", seed=seed); plan.attach(trk)      # гармония
    V = plan.voicings("close", 52, 64, n=3)                                                      # голоса аккордов в регистре
    bass = plan.bass(np.random.default_rng([seed, 1]), 28, 40, style="root", cell=[0, 3, 6, 10], against=V)
    ctx = L.context(plan, V, bass)
    h8 = L.hook(plan, np.random.default_rng([seed, 3]), 57, 69, 8, ctx, lambda b: set())        # 8-тактовый хук
    hook = L.tile(h8, plan, 57, 69, [8, 16, 24, 32, 40], ctx, origin=8)
    ev = lambda xs: [(mt.time(s // 16, s % 16, "pluck"), m, v, max(1, l) * S16 * .9) for s, l, m, v in xs]
    EV = {"bass": ev(bass), "hook": ev(hook)}
    for k, e in EV.items(): trk.log_notes(k, e)
    ...звуки, ударные, микс (ниже)...
    trk.mono_low(150)
    return trk
```

## 3. Звуки (правила Стаса жёсткие)

**Только записанные сэмплы, без синтеза.** Каталоги: `~/samples/wa_techno`, `~/samples/wa2`, `~/samples/musicradar/*`, `~/samples/tidal-drum-machines/machines/*` (70+ драм-машин), `~/samples/sfz/*`.

**Мультисэмплы** (лучший вариант для мелодий и аккордов: сэмпл на каждую ноту, ничего не растягивается):
```python
SFZ("fashionbass").render(events, T)     # events = [(t_sec, midi, vel, dur_sec), ...]
```
Зарегистрированы: `rhodes`, `piano`, `piano_natural`, `bass`, `bass_pluck`, **новые 2026-11-18**: `fashionbass`, `fashionbass_full`, `growlybass`, `growlybass_dirty`, `wurlitzer`, `cp80`, `pianet`, `bearsax` (саксофон: одна выдержанная запись на ноту, MIDI 29-75; `bearsax_full` = старый стоковый вариант с шумовыми и саб-слоями, не использовать). Проверены по высоте: ошибка 5-7 центов. Гитары Black and Green скачаны, но НЕ подключены (движок неверно мерит их октаву).

**Один шот** (W.A. и т.п.) только через проверку:
```python
f = SG.pick(glob.glob(WA + "*Bass*.wav"), "bass", 28, 40, rng, db=db, title=title)   # отсекает расстроенные/плавающие/шумные и те, чей корень не обслуживает диапазон нот
ins = sfz.oneshot(f, release=.08, policy="warn")
```
- Шот можно сдвигать не дальше ±7 полутонов от его родной ноты, иначе «гармошка». Гейт `bad_sounds` это ловит.
- Одна партия = один тембр (не чередовать два разных бас-шота).
- Ударные: `fresh.pick(glob(...), rng, db=db, title=title)` выбирает наименее использованный в прошлых треках. Давай сэмплам ударных мягкий вход 2-3 мс.

**P141, запись как инструмент** (`autodj.compose.evolve as V`):
```python
ens = V.Ensemble(src, kc, n=4, seed=seed, spread=.55, swell_db=2.5, glide_s=.09)       # пэд: 4 голоса держатся и плавно переходят по аккордам
pad = ens.render(trk, plan, "drop2", 52, 71, bars=pad_bars)
pad = V.tone(pad, trk.sr, bright=V.lane(trk, {"intro": .3, "home*": .62, "break": .42}, glide_bars=2))
vox = V.Voice(src, kc, seed=seed, glide_s=.14, release_s=.7); top = vox.render(events, T)   # легато-мелодия из одной записи
air = V.grains(trk, src, kc, plan, per_bar=5, lo=67, hi=88, bars=air_bars, seed=seed)
```
`src` = запись ОДНОЙ выдержанной ноты (струнные, пэд, орган, сакс) или зарегистрированный мультисэмпл. Аккорд-шоты W.A. для этого не годятся. Образец: `docs/examples/evolve_demo.py`.
⚠️ Сейчас найдено: на `AUTODJ_EVOLVE_SFZ=bearsax` слой `Voice` выходит беззвучным (верхняя мелодия демо в регистре 64-76, а Bear Sax выше 72 молчит). Проверяй `layers_db` в сводке: если слоя там нет, его не было.

## 4. Микс

```python
trk.bus("drums", fx=[glue()]); trk.space("room", kind="room"); trk.space("hall", kind="hall", back_db=-5)
trk.add("kick", kick_buf, 1.0, bus="drums")                                 # первый слой = опорный уровень
trk.add("bass", bass_buf, level=10 ** (-5 / 20), duck=-6.0, key="kick", release_ms=90)   # дак по настоящей бочке
trk.add("hook", hook_buf, level=10 ** (-7 / 20), duck=-6.0, key="vox", band=(300, 5000), send={"hall": .15})
trk.add("pad", pad_buf, level=10 ** (-17 / 20), duck=-4.0, key="kick", depth=.7, send={"hall": .3})
```
- `level` относительно первого слоя (RMS). `duck` + `key=` следует за реальным слоем; `band=(lo, hi)` дакает только полосу. `duck` без `key` = «по часам» (после P140 без щелчка).
- `depth` 0 впереди, 1 далеко. `send` в общие пространства.
- `trk.mono_low(150)` в конце: низ в моно.

## 5. Сводка рендера: что смотреть

`summary.json`: `layers_db` (уровни слоёв, нет слоя = его нет), `silent_layers`, `bad_sounds`, `gate_failed`, `master.limiter_max_db` (≤ 2.5), `clash_ratio` (< 0.12), `spikes`, `problems`, `tonal_notes` (должен быть пуст), `click_notes` (P140: где рвётся волна и в каком слое), `depth_notes`, `fresh_notes` (заезженные звуки и рисунки), `arc` (повторяемость).

## 6. Гармония

- `C.Plan.build(tonic, trk.tl, home, journey, seed=seed, colour=0)`; обороты: `C.idioms("deep" | "melodic" | "dark" | "minimal" | "garage" | "dreamy")`.
- `colour=-1` проще (трезвучия), `0` add9/maj7, `+1` m9/maj9. Ноты вне гаммы не появляются.
- Старая петля i(add9) | VI maj7 | iv m7 | V7sus4: идиом `old_loop`, только по просьбе Стаса.

## 7. Референс (P142)

```sh
python -m autodj.compose.blueprint REF.wav [OURS.mp3] [--bpm 124]
```
Достаёт темп, тональность, аккорд на такт, разделы, ход громкости, частоту изменений; с вторым файлом пишет различия («у эталона в 150-400 Гц на 4 дБ меньше»). `match_eq` подтягивает баланс мастера.

## 8. Правила Стаса (нарушать нельзя)

- Только записанные сэмплы, без синтезатора и Vital.
- Каждый слой должен служить треку. Без постоянной тарелки весь трек (хэты/райд/шейкер), без тамбурина-шейкера, без L/R-качания, без «бибип»-стэбов, без PINGPONG/GATE.
- Без псевдо-пения и вокальных нарезок. Голос (CHIMERA, `~/tools/chimera_20261118`) только по просьбе. Язык украинский или английский, русский только по прямой просьбе.
- Каждый трек с чистого листа: не переносить звуки, рисунки и аккорды из прошлых треков.
- Не больше 2 рендеров на трек; перед рендером проверить пути сэмплов.
- Автор StanPo, название «Название (стиль)».
- Окончательный судья: уши Стаса. Gemini и Whisper только как слепая гипотеза.

Подробнее: `docs/COMPOSE_HARMONY.md`, `docs/COMPOSE_DEPTH.md`, `docs/COMPOSE_VECTOR.md`.
