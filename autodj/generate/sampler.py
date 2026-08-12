#!/usr/bin/env python3
"""
sampler.py — S1: РЕАЛЬНЫЕ сэмплы вместо математического синтеза барабанов.

Диагноз: наш synth909 честно пишет о себе «All sounds synthesized from first
principles (no samples needed)» — то есть кик/снейр/хэт считаются формулами.
Живые live-coding сеты (Strudel/Tidal) звучат «нормально» ровно потому, что
играют СЭМПЛЫ настоящих драм-машин: .bank("RolandTR808"), .bank("akailinn"),
.bank("dmx"). Никакая математика 808-й не заменит.

Банки (бесплатные, ставятся один раз):
    git clone --depth 1 https://github.com/ritchse/tidal-drum-machines
    git clone --depth 1 https://github.com/tidalcycles/Dirt-Samples
Путь к банкам — env SAMPLE_BANKS или аргумент banks_dir.

Возможности сэмпла (как в Strudel): begin/end (обрезка), speed (скорость/питч),
gain, pan, chop (нарезка на куски). Всё — numpy, без внешних зависимостей кроме
soundfile для чтения.
"""
from __future__ import annotations

import os
import random

import numpy as np

# Псевдонимы Strudel → типичные имена папок в банках
ALIASES = {
    "bd": ("bd", "kick", "bassdrum"), "sd": ("sd", "snare", "sn"),
    "hh": ("hh", "hat", "hihat", "ch"), "oh": ("oh", "openhat", "ohh"),
    "cp": ("cp", "clap", "handclap"), "rim": ("rim", "rimshot"),
    "cr": ("cr", "crash", "cymbal"), "rd": ("rd", "ride"),
    "lt": ("lt", "tom", "lowtom"), "mt": ("mt", "midtom"), "ht": ("ht", "hightom"),
    "perc": ("perc", "percussion"), "cb": ("cb", "cowbell"),
}


def banks_root(banks_dir: str | None = None) -> str:
    return os.path.expanduser(banks_dir or os.environ.get("SAMPLE_BANKS", "~/samples"))


def find_bank(bank: str, banks_dir: str | None = None) -> str | None:
    """Папка банка (RolandTR808, AkaiLinn…) — регистронезависимо, на любой глубине."""
    root = banks_root(banks_dir)
    if not os.path.isdir(root):
        return None
    target = bank.lower().replace(" ", "").replace("-", "")
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames:
            if d.lower().replace(" ", "").replace("-", "") == target:
                return os.path.join(dirpath, d)
    return None


def canonical(name: str) -> str:
    """Любое имя («kick», «bassdrum», «bd») → канон («bd»). Чистая."""
    n = name.lower()
    if n in ALIASES:
        return n
    for canon, keys in ALIASES.items():
        if n in keys:
            return canon
    return n


def find_samples(bank_path: str, name: str) -> list[str]:
    """Все wav для инструмента (bd/sd/hh…) — round-robin по вариациям. Чистая по данным."""
    if not bank_path or not os.path.isdir(bank_path):
        return []
    keys = ALIASES.get(canonical(name), (canonical(name),))
    hits: list[str] = []
    for dirpath, dirnames, files in os.walk(bank_path):
        base = os.path.basename(dirpath).lower()
        for f in sorted(files):
            if not f.lower().endswith((".wav", ".flac", ".aiff", ".aif")):
                continue
            stem = os.path.splitext(f)[0].lower()
            if base in keys or any(stem.startswith(k) for k in keys):
                hits.append(os.path.join(dirpath, f))
    return hits


class SampleBank:
    """Загруженный банк: имя инструмента → список вариаций (стерео float32)."""

    def __init__(self, bank: str, sr: int = 44100, banks_dir: str | None = None):
        self.bank, self.sr = bank, sr
        self.path = find_bank(bank, banks_dir)
        self._cache: dict[str, list[np.ndarray]] = {}
        if not self.path:
            raise FileNotFoundError(
                f"банк «{bank}» не найден в {banks_root(banks_dir)}. Поставь один раз:\n"
                f"  git clone --depth 1 https://github.com/ritchse/tidal-drum-machines "
                f"{banks_root(banks_dir)}/tidal-drum-machines")

    def get(self, name: str) -> list[np.ndarray]:
        name = canonical(name)
        if name in self._cache:
            return self._cache[name]
        import soundfile as sf
        out = []
        for p in find_samples(self.path, name)[:16]:
            try:
                a, sr0 = sf.read(p, dtype="float32", always_2d=True)
                if a.shape[1] == 1:
                    a = np.repeat(a, 2, axis=1)
                if sr0 != self.sr:                        # простая ресемплинг-интерполяция
                    n = int(len(a) * self.sr / sr0)
                    idx = np.linspace(0, len(a) - 1, n)
                    a = np.stack([np.interp(idx, np.arange(len(a)), a[:, c])
                                  for c in range(2)], 1).astype("float32")
                out.append(a)
            except Exception:
                continue
        self._cache[name] = out
        return out


def shape_sample(x: np.ndarray, begin: float = 0.0, end: float = 1.0,
                 speed: float = 1.0, gain: float = 1.0, pan: float = 0.0) -> np.ndarray:
    """Обработка сэмпла как в Strudel: begin/end/speed/gain/pan. Чистая."""
    if len(x) == 0:
        return x
    a, b = int(max(0.0, begin) * len(x)), int(min(1.0, end) * len(x))
    y = x[a:max(a + 1, b)]
    if abs(speed - 1.0) > 1e-3 and speed > 0:
        n = max(1, int(len(y) / speed))
        idx = np.linspace(0, len(y) - 1, n)
        y = np.stack([np.interp(idx, np.arange(len(y)), y[:, c]) for c in range(2)], 1)
    y = y.astype("float32") * gain
    if abs(pan) > 1e-3:                                   # -1 левее, +1 правее
        l = np.sqrt(max(0.0, (1 - pan) / 2)) * np.sqrt(2)
        r = np.sqrt(max(0.0, (1 + pan) / 2)) * np.sqrt(2)
        y = y * np.array([l, r], dtype="float32")
    return y


def render_pattern(bank: SampleBank, pattern: str, cycles: int, cycle_sec: float,
                   sr: int = 44100, gain: float = 1.0, speed: float = 1.0,
                   begin: float = 0.0, end: float = 1.0, seed: int = 0,
                   round_robin: bool = True) -> np.ndarray:
    """Мини-нотация + банк сэмплов → аудио. Вариации сэмпла берутся по кругу
    (round-robin) — живые драм-машины не звучат двумя одинаковыми ударами подряд."""
    from .mininotation import pattern_to_times
    total = int(cycles * cycle_sec * sr) + sr
    out = np.zeros((total, 2), dtype="float32")
    rng = random.Random(seed)
    counters: dict[str, int] = {}
    for t, name, _dur in pattern_to_times(pattern, cycles, cycle_sec, seed):
        variants = bank.get(name)
        if not variants:
            continue
        if round_robin:
            i = counters.get(name, 0) % len(variants)
            counters[name] = i + 1
        else:
            i = rng.randrange(len(variants))
        seg = shape_sample(variants[i], begin, end, speed, gain)
        pos = int(t * sr)
        n = min(len(seg), total - pos)
        if n > 0:
            out[pos:pos + n] += seg[:n]
    return out
