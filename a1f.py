#!/usr/bin/env python3
"""
a1f.py — конфигурация вызова A1F (All-In-One Music Structure Analyzer, форк
all-in-one-fix). Тяжёлый ML-инструмент живёт ВНЕ репо (отдельный venv); здесь —
только версионируемая прослойка: где его питон и как собрать команду.

Портируемость: путь к питону A1F берётся из env A1F_PYTHON, иначе — серверный
дефолт. Раньше путь был захардкожен в smart_mixer.py в трёх местах — на другом
сервере (или у нового агента) это не заводилось без правки кода.

Два режима (это и есть «два режима» A1F — Demucs вкл/выкл):
  fast (--skip-separation) — без Demucs, CPU, 5-10× быстрее; даёт beats/downbeats/
                             segments. Дефолт.
  full (с Demucs)          — нужен ТОЛЬКО для вокал-интервалов; тяжёлый.

activations/embeddings (-a/-e) НЕ используются нигде в пайплайне — не включаем.

Чистый модуль (os). Тестируется офлайн.
"""
import os

DEFAULT_A1F_PYTHON = "~/ai-tools/all-in-one-fix/venv/bin/python"


def a1f_python() -> str:
    """Путь к питону A1F: env A1F_PYTHON или серверный дефолт. expanduser применён."""
    return os.path.expanduser(os.environ.get("A1F_PYTHON", DEFAULT_A1F_PYTHON))


def a1f_command(wav_path: str, out_dir: str, fast: bool = True,
                overwrite: bool = True) -> list[str]:
    """
    Собрать команду запуска allin1fix.cli. Чистая функция.
      fast=True  → --skip-separation (без Demucs, CPU)
      fast=False → полный Demucs (для вокал-интервалов)
    """
    cmd = [a1f_python(), "-m", "allin1fix.cli", wav_path, "-o", out_dir]
    if overwrite:
        cmd.append("--overwrite")
    if fast:
        cmd.append("--skip-separation")
    return cmd
