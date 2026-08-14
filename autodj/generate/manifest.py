#!/usr/bin/env python3
"""
manifest.py — P87: паспорт каждого сгенерированного трека.

Проблема, которую закрывает: рендер запускает агент, у которого своя сессия, своя
память переписки и свои НЕзакоммиченные файлы. Снаружи не видно, каким именно кодом
и с какими параметрами сделан конкретный трек — а значит, нельзя ни воспроизвести,
ни отличить «плохо звучит из-за алгоритма» от «плохо звучит из-за локального форка».
Живой случай: music_theory.py существовал только на машине агента, и рендеры шли
кодом, которого в репозитории не было.

Манифест пишется рядом с треком и фиксирует:
  • git-коммит + ФЛАГ ГРЯЗНОГО ДЕРЕВА (незакоммиченные правки = рендер невоспроизводим);
  • список untracked .py в autodj/ (тот самый класс «работает только у меня»);
  • отпечаток трека и seed (воспроизведение), параметры GenreConfig;
  • банк сэмплов, версии ключевых пакетов, окружение.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                           text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def git_state() -> dict:
    """Коммит, ветка, грязное дерево, untracked-модули пакета. I/O-тонкое."""
    status = _git("status", "--porcelain")
    modified = [l[3:] for l in status.splitlines() if l[:2].strip() and l.endswith(".py")]
    untracked_pkg = [l[3:] for l in status.splitlines()
                     if l.startswith("??") and l[3:].startswith("autodj/") and l.endswith(".py")]
    return {
        "commit": _git("rev-parse", "HEAD")[:12],
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status.strip()),
        "modified_py": modified[:20],
        "untracked_package_py": untracked_pkg,     # ← «работает только у меня»
    }


def package_versions(names=("numpy", "scipy", "soundfile", "pyrubberband",
                            "pyloudnorm", "pedalboard")) -> dict:
    out = {}
    for n in names:
        try:
            mod = __import__(n)
            out[n] = getattr(mod, "__version__", "?")
        except Exception:
            out[n] = None
    return out


def build_manifest(cfg=None, ident: dict | None = None, extra: dict | None = None) -> dict:
    """Собрать паспорт рендера. Чистая по структуре (I/O только чтение окружения)."""
    cfg_dump = {}
    if cfg is not None:
        for k in dir(cfg):
            if k.startswith("_"):
                continue
            v = getattr(cfg, k, None)
            if isinstance(v, (str, int, float, bool)) or v is None:
                cfg_dump[k] = v
    man = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git": git_state(),
        "track": {
            "seed": (ident or {}).get("seed"),
            "fingerprint": (ident or {}).get("fingerprint"),
            "motif_len": len(((ident or {}).get("motif") or [])),
            "lead_octave": (ident or {}).get("lead_octave"),
            "rhythm": "".join(map(str, (ident or {}).get("rhythm") or [])),
        },
        "config": cfg_dump,
        "env": {
            "python": platform.python_version(),
            "sample_banks": os.environ.get("SAMPLE_BANKS", ""),
            "drum_bank": os.environ.get("DRUM_BANK", ""),
            "a1f_python": os.environ.get("A1F_PYTHON", ""),
        },
        "packages": package_versions(),
    }
    if extra:
        man.update(extra)
    return man


def write_manifest(out_wav: str, cfg=None, ident: dict | None = None,
                   extra: dict | None = None) -> str:
    """Записать <трек>.manifest.json рядом с аудио. Возврат — путь."""
    man = build_manifest(cfg, ident, extra)
    path = os.path.splitext(out_wav)[0] + ".manifest.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"    манифест не записан: {type(e).__name__}")
        return ""
    g = man["git"]
    warn = ""
    if g["untracked_package_py"]:
        warn = (f"  ⚠ НЕЗАКОММИЧЕННЫЕ модули: {', '.join(g['untracked_package_py'][:3])}"
                f" — трек сделан кодом, которого нет в репозитории!")
    elif g["dirty"]:
        warn = "  ⚠ рабочее дерево грязное — точное воспроизведение не гарантировано"
    print(f"    манифест: {os.path.basename(path)} (commit {g['commit']}, "
          f"отпечаток {man['track']['fingerprint']}){warn}")
    return path
