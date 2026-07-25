#!/usr/bin/env python3
"""
mixbus.py -- Q1: микс-шина генератора (диагноз «примитивизм»).

Три причины плоского звука, которые лечит этот модуль:
  1. ГЕЙН-СТЕЙДЖИНГ. Раньше каждый слой отдельно нормализовался до -3 dB
     (backends/fluidsynth.py) -- динамика, насочинённая velocity-логикой, стиралась,
     все слои приезжали одинаково громкими. Здесь баланс ставится по RMS
     относительно ролевых целей, а не по пику.
  2. ЧАСТОТНЫЕ РОЛИ. Раньше слои просто складывались и дрались в одной полосе -> каша.
     Здесь у каждой роли свой диапазон (низ отдан басу/кику, середина расчищена).
  3. САЙДЧЕЙН. Пампинг -- подпись современной электроники; его не было вовсе.
     Тот же приём, что в club_rework (частотные роли + duck), только для генератора.
Плюс ОБЩЕЕ ПРОСТРАНСТВО: один реверб-возврат вместо отдельного реверба на каждом слое --
слои «садятся» в одну комнату.

Чистые функции (numpy/scipy) -- тестируются офлайн, без FluidSynth и pedalboard.
"""
from __future__ import annotations

import numpy as np

# Ролевые цели RMS (относительные, не пики). Бас/кик -- фундамент, лид -- над ним.
ROLE_TARGETS = {
    "drums":   1.00,
    "bass":    0.85,
    "lead":    0.60,
    "arp":     0.45,
    "pad":     0.40,
    "counter": 0.35,
    "accent":  0.30,
}

# Частотные роли: (highpass Гц, lowpass Гц|None). Низ принадлежит басу и кику.
ROLE_BANDS = {
    "drums":   (25.0,  None),
    "bass":    (30.0,  220.0),    # бас не лезет в середину
    "pad":     (180.0, 9000.0),   # пад освобождает низ и самый верх
    "lead":    (220.0, None),
    "arp":     (260.0, None),
    "counter": (300.0, None),
    "accent":  (300.0, None),
}


def _sos(sr: float, fc: float, btype: str):
    from scipy.signal import butter
    return butter(2, fc / (sr / 2.0), btype=btype, output="sos")


def _filt(x: np.ndarray, sr: int, fc: float, btype: str) -> np.ndarray:
    from scipy.signal import sosfilt
    sos = _sos(sr, fc, btype)
    out = np.empty_like(x)
    for ch in range(x.shape[1]):
        out[:, ch] = sosfilt(sos, x[:, ch]).astype(np.float32)
    return out


def eq_carve(buf: np.ndarray, sr: int, role: str) -> np.ndarray:
    """Частотная роль слоя: срезать то, что ему не принадлежит. Чистая."""
    hp, lp = ROLE_BANDS.get(role, (None, None))
    out = buf
    if hp:
        out = _filt(out, sr, hp, "high")
    if lp:
        out = _filt(out, sr, lp, "low")
    return out


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if x.size else 0.0


MAX_BOOST = 4.0      # +12 dB: выше -- вытягиваем шум/хвосты вместо музыки
MIX_CEILING = 0.89   # запас на мастер (tanh+компрессор) -- общий, не пер-слойный


def stage_gain(buf: np.ndarray, role: str, ref_rms: float) -> float:
    """Гейн слоя по РОЛЕВОЙ ЦЕЛИ RMS относительно опорного слоя (обычно drums).
    Буст ограничен MAX_BOOST (иначе тихий слой вытягивается вместе с шумом).
    Тишина -> 0. Чистая."""
    r = rms(buf)
    if r <= 1e-9 or ref_rms <= 1e-9:
        return 0.0
    return float(min(MAX_BOOST, ROLE_TARGETS.get(role, 0.5) * ref_rms / r))


def sidechain_duck(x: np.ndarray, sr: int, period: int, depth_db: float = -4.5,
                   release_ms: float = 120.0) -> np.ndarray:
    """Пампинг: на каждой доле гейн падает до depth и экспоненциально
    восстанавливается. period -- интервал доли в сэмплах. Чистая."""
    if period <= 0 or len(x) == 0:
        return x
    depth = 10 ** (depth_db / 20.0)
    rel = max(1, int(sr * release_ms / 1000.0))
    t = np.arange(rel, dtype=np.float32)
    curve = depth + (1.0 - depth) * (1.0 - np.exp(-4.0 * t / rel))
    env = np.ones(len(x), dtype=np.float32)
    for pos in range(0, len(x), period):
        seg = min(rel, len(x) - pos)
        env[pos:pos + seg] = np.minimum(env[pos:pos + seg], curve[:seg])
    return x * env[:, None]


def reverb_send(layers: dict[str, np.ndarray], sends: dict[str, float]) -> np.ndarray:
    """Сумма посылов в ОДНУ общую комнату (вместо реверба на каждом слое). Чистая."""
    n = max((len(b) for b in layers.values()), default=0)
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32)
    bus = np.zeros((n, 2), dtype=np.float32)
    for name, buf in layers.items():
        s = float(sends.get(name, 0.0))
        if s > 0 and len(buf):
            bus[:len(buf)] += buf * s
    return bus


def mix_layers(layers: dict[str, np.ndarray], sr: int, beat_samples: int,
               duck_roles: tuple = ("pad", "lead", "arp", "counter", "accent"),
               ref_role: str = "drums", duck_db: float = -4.5,
               carve: bool = True) -> tuple[np.ndarray, dict[str, float]]:
    """Собрать слои в микс: частотные роли -> гейн-стейджинг по RMS -> сайдчейн.
    -> (mix, применённые гейны). Чистая (numpy in -> numpy out)."""
    n = max((len(b) for b in layers.values()), default=0)
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32), {}

    proc = {name: (eq_carve(buf, sr, name) if carve and len(buf) else buf)
            for name, buf in layers.items()}
    ref = rms(proc.get(ref_role, np.zeros((1, 2), np.float32)))
    if ref <= 1e-9:                                   # нет опорного слоя -- берём самый громкий
        ref = max((rms(b) for b in proc.values()), default=0.0)

    mix = np.zeros((n, 2), dtype=np.float32)
    gains: dict[str, float] = {}
    for name, buf in proc.items():
        if not len(buf):
            continue
        g = stage_gain(buf, name, ref)
        gains[name] = round(g, 4)
        piece = buf * g
        if name in duck_roles:
            piece = sidechain_duck(piece, sr, beat_samples, duck_db)
        mix[:len(piece)] += piece[:n]

    peak = float(np.abs(mix).max())          # ОДИН общий скейл -- баланс не рушится
    if peak > MIX_CEILING:
        mix *= MIX_CEILING / peak
    return mix, gains
