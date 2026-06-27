#!/usr/bin/env python3
"""
a1f.py — конфигурация вызова A1F (All-In-One Music Structure Analyzer, форк
all-in-one-fix, openmirlab). Тяжёлый ML-инструмент живёт ВНЕ репо (отдельный venv);
здесь — версионируемая прослойка: где его питон и как собрать КОРРЕКТНУЮ команду.

ВАЖНО — почему «fast без стемов» НЕВОЗМОЖЕН (и почему прежний код падал):
  Модель harmonix-all анализирует СПЕКТРОГРАММЫ, которые извлекаются из 4 demucs-стемов
  (bass/drums/other/vocals). Без стемов входа у модели нет — анализа нет.
    • `--skip-separation` НЕ значит «без стемов». Значит «стемы УЖЕ готовы в --demix-dir,
      не пересчитывай demucs». Если стемов там нет — allin1fix падает на bass.wav.
      Прежний код звал --skip-separation БЕЗ стемов → это и был баг (BPM=None, beats=0).
    • `--no-demucs` тоже «requires pre-computed stems» (и в analyze() даже не передаётся).

Поэтому реальный «fast» = посчитать стемы ОДИН раз, СОХРАНИТЬ (-k, --demix-dir) и
ПЕРЕИСПОЛЬЗОВАТЬ на следующих прогонах (--skip-separation уже корректно, т.к. стемы есть).
Стемы — переиспользуемые данные: лежат в demix_dir, годятся для будущих миксов/анализа.

Чистый модуль (os). Тестируется офлайн.
"""
import os

DEFAULT_A1F_PYTHON = "~/ai-tools/all-in-one-fix/venv/bin/python"
_STEMS = ("bass", "drums", "other", "vocals")


def a1f_python() -> str:
    """Путь к питону A1F: env A1F_PYTHON или серверный дефолт. expanduser применён."""
    return os.path.expanduser(os.environ.get("A1F_PYTHON", DEFAULT_A1F_PYTHON))


def stems_ready(wav_path: str, demix_dir: str) -> bool:
    """Готовы ли 4 demucs-стема для трека в <demix_dir>/htdemucs/<name>/. Если да — сепарацию
    можно пропустить (--skip-separation корректно). Чистая (только проверка файлов)."""
    name = os.path.splitext(os.path.basename(wav_path))[0]
    d = os.path.join(demix_dir, "htdemucs", name)
    return all(os.path.exists(os.path.join(d, s + ".wav")) for s in _STEMS)


def a1f_command(wav_path: str, out_dir: str, demix_dir: str | None = None,
                overwrite: bool = True) -> list[str]:
    """Собрать КОРРЕКТНУЮ команду allin1fix.cli. Чистая функция.

    Модель работает на стемах, поэтому:
      • стемы уже в demix_dir → добавляем --skip-separation (быстро, переиспользуем),
      • иначе → demucs RUN, и СОХРАНЯЕМ стемы (-k) в demix_dir для будущих прогонов.
    demix_dir по умолчанию <out_dir>/demix. «Fast без стемов» режима НЕТ by design."""
    demix_dir = demix_dir or os.path.join(out_dir, "demix")
    cmd = [a1f_python(), "-m", "allin1fix.cli", wav_path,
           "-o", out_dir, "--demix-dir", demix_dir, "-k"]   # -k: сохранить стемы для reuse
    if overwrite:
        cmd.append("--overwrite")
    if stems_ready(wav_path, demix_dir):
        cmd.append("--skip-separation")                     # корректно: стемы есть
    return cmd
