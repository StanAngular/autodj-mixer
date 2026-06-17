# A1F (All-In-One Music Structure Analyzer) — установка и интеграция

A1F даёт микшеру **структуру трека** (intro/verse/chorus/bridge/outro + даунбиты),
чего madmom не умеет. Это тяжёлый ML-инструмент (PyTorch + NATTEN + Demucs), поэтому
он **не вендорится** в этот репозиторий — живёт во внешнем venv, а здесь только
версионируемая прослойка (`a1f.py`) и этот рецепт.

Используется форк **`all-in-one-fix`** (namespace `allin1fix`) — он чинит совместимость
оригинала с PyTorch 2.x (NATTEN), использует `demucs-infer` для сепарации и добавляет
кэш моделей.

## Установка (воспроизводимо)

```bash
mkdir -p ~/ai-tools && cd ~/ai-tools
python3.11 -m venv all-in-one-fix/venv
source all-in-one-fix/venv/bin/activate
# PyTorch под вашу систему — см. pytorch.org
pip install torch
# NATTEN (соседское внимание) — Linux: см. natten.org; гибко 0.17.5+
pip install "natten>=0.17.5"
pip install git+https://github.com/CPJKU/madmom        # свежий madmom
pip install all-in-one-fix                              # сам форк
sudo apt install -y ffmpeg
deactivate
```

Проверка: `~/ai-tools/all-in-one-fix/venv/bin/python -m allin1fix.cli --help`

## Где путь задаётся (портируемость)

Питон A1F берётся из `a1f.py` → `a1f_python()`:
- по умолчанию `~/ai-tools/all-in-one-fix/venv/bin/python`;
- переопределяется переменной окружения **`A1F_PYTHON`** (для другого сервера / агента):

```bash
export A1F_PYTHON=/path/to/allin1fix/venv/bin/python
```

Раньше путь был захардкожен в `smart_mixer.py` в трёх местах — теперь все вызовы идут
через `a1f.a1f_python()`, так что перенос на другой сервер не требует правки кода.

## Два режима (Demucs вкл/выкл)

| Режим | Флаг | Demucs | Скорость | Когда |
|-------|------|--------|----------|-------|
| fast  | `--skip-separation` | нет | CPU, 5-10× быстрее | по умолчанию (нужны структура+даунбиты) |
| full  | (без флага) | да | медленно, GPU желателен | только для **вокал-интервалов** |

Сборка команды — `a1f.a1f_command(wav, out_dir, fast=True/False)`.

`recommend_analysis` (в `curation_bridge.py`) подсказывает режим по косвенным признакам:
`none` (хватит madmom) / `fast` (структурный анализ нужен). Полный Demucs — ручной
выбор для вокал-чувствительных миксов.

## Что A1F отдаёт и что из этого используется

Результат — JSON на трек (~11 КБ) в `shared/a1f_results/`:
`bpm`, `beats`, `downbeats`, `beat_positions`, `segments` ({start, end, label}).

Микшер потребляет: `bpm` (кросс-валидация с madmom), `beats`, `downbeats`
(→ мастер-сетка, **заменяют madmom**), `segments` (→ bar_labels), а также
`vocal_intervals` и ключ/Camelot из `.meta.json` (полный режим).

**НЕ используются** и потому **не запрашиваются** (`-a`/`-e` не передаются):
`activations`, `embeddings`, demix-стемы, `beat_positions`. Лишних данных нет.

## Перенос на GitHub

Тяжёлый инструмент остаётся внешним (pip/venv). В репозитории версионируется:
`a1f.py` (путь + сборка команды), этот `docs/a1f-setup.md` (рецепт), и вызовы из
`smart_mixer.py`/`curation_bridge.py`. Этого достаточно, чтобы на чистом сервере
поднять A1F по рецепту и указать `A1F_PYTHON`.
