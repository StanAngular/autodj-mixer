"""P93/P96: ЖИВОЕ ИСПОЛНЕНИЕ мелодических партий. Чистые функции (numpy/scipy).

Отзыв Стаса (2026-10-08, psy_triphop): «слишком механически, нет грува».
Диагноз: у барабанов свинг из стиля, у мелодии свой случайный — сетки не связаны;
«человечность» = белый шум ±5-12 мс вокруг сетки; velocity без учёта доли;
плаки сыпят нотами без хвостов; пад обрывается за 0.6 с.

Что здесь:
  * sample_performance — диапазоны стиля → КОНКРЕТНЫЙ профиль ЭТОГО трека (каждый
    рендер свой; seed трека = точное воспроизведение, режим «дорабатываем трек»).
  * apply_groove — общий с барабанами свинг 16-х + оттяжка за сетку по ролям +
    velocity по метрической карте с медленным «дыханием».
  * thin_events — плаки реже: сильные доли остаются, слабые выпадают.
  * echo — длинный delay: фильтр в петле (каждый повтор темнее), пинг-понг,
    приглушение эха под сухим сигналом.

Бас и барабаны сюда НЕ попадают (Стас: «работают хорошо») — apply_groove/thin_events
возвращают их события без изменений.
"""
from __future__ import annotations

import random

import numpy as np

GROOVE_ROLES = ("lead", "counter", "arp", "accent", "pad")
UNTOUCHED_ROLES = ("bass", "drums")

# Метрический вес позиции в такте 4/4 (16 шагов): 1-я доля > 3-я > 2/4 > восьмые > 16-е.
METRIC_WEIGHT = [1.00, 0.30, 0.50, 0.35, 0.72, 0.30, 0.52, 0.35,
                 0.86, 0.30, 0.50, 0.35, 0.72, 0.30, 0.55, 0.40]

# Диапазоны по умолчанию: стиль может переопределить любой ключ в "performance".
DEFAULT_RANGES = {
    # оттяжка за сетку, мс [мин, макс] — выбирается на трек
    "lag_ms": {"lead": [2, 12], "counter": [8, 25], "arp": [0, 10],
               "accent": [6, 20], "pad": [0, 0]},
    # разброс тайминга (сигма, мс) — микродрожь поверх оттяжки
    "jitter_ms": {"lead": [3, 6], "counter": [4, 8], "arp": [2, 4],
                  "accent": [4, 9], "pad": [0, 0]},
    # окно velocity: [тихая слабая доля, громкая сильная]
    "vel_window": {"lead": [52, 104], "counter": [36, 94], "arp": [34, 92],
                   "accent": [40, 96], "pad": [48, 70]},
    "vel_span_scale": [0.8, 1.2],      # насколько контрастны доли у этого трека
    "breath_depth": [0.06, 0.14],      # глубина медленного «дыхания» velocity
    "pad_release_ms": [1500, 4000],    # P96: аккорды наплывают друг на друга
    "pluck_release_ms": [250, 700],
    "arp_keep": [0.40, 0.60],          # P96: доля нот арпа, которая остаётся
    "lead_keep": [0.75, 0.90],         # у темы выпадают только слабые доли
    "echo_times": [1.0, 0.75, 1.5],    # в долях: 1/4, 3/16 (точечная 1/8), 3/8
    "echo_feedback": [0.45, 0.65],
    "echo_wet": [0.25, 0.40],
    "echo_lp_hz": [2200, 4500],
    "echo_pingpong": [True, True, False],
}


def _u(rng: random.Random, r) -> float:
    lo, hi = float(r[0]), float(r[1])
    return round(rng.uniform(min(lo, hi), max(lo, hi)), 3)


def sample_performance(ranges: dict | None, rng: random.Random) -> dict | None:
    """Диапазоны стиля → профиль исполнения трека. ranges=None/{} или enabled=False
    → None (движок ведёт себя как до P93). Чистая при rng."""
    if not ranges or not ranges.get("enabled", True):
        return None
    R = {**DEFAULT_RANGES, **{k: v for k, v in ranges.items() if k != "enabled"}}
    for k in ("lag_ms", "jitter_ms", "vel_window"):        # роли можно задать частично
        R[k] = {**DEFAULT_RANGES[k], **(ranges.get(k) or {})}
    span = _u(rng, R["vel_span_scale"])
    vel = {}
    for role, (lo, hi) in R["vel_window"].items():
        mid, half = (lo + hi) / 2, (hi - lo) / 2 * span
        shift = rng.uniform(-6, 6)
        vel[role] = (int(max(20, mid - half + shift)), int(min(124, mid + half + shift)))
    return {
        "lag_ms": {r: _u(rng, v) for r, v in R["lag_ms"].items()},
        "jitter_ms": {r: _u(rng, v) for r, v in R["jitter_ms"].items()},
        "vel": vel,
        "breath": _u(rng, R["breath_depth"]),
        "pad_release_ms": _u(rng, R["pad_release_ms"]),
        "pluck_release_ms": _u(rng, R["pluck_release_ms"]),
        "arp_keep": _u(rng, R["arp_keep"]),
        "lead_keep": _u(rng, R["lead_keep"]),
        "echo_beats": float(rng.choice(list(R["echo_times"]))),
        "echo_feedback": _u(rng, R["echo_feedback"]),
        "echo_wet": _u(rng, R["echo_wet"]),
        "echo_lp_hz": _u(rng, R["echo_lp_hz"]),
        "echo_pingpong": bool(rng.choice(list(R["echo_pingpong"]))),
    }


def grid_position(t: float, beat_sec: float) -> tuple[int, float]:
    """Время → (шаг 0..15 в такте, отклонение от ближайшей 16-й в секундах). Чистая."""
    step_sec = beat_sec / 4
    k = int(round(t / step_sec))
    return k % 16, t - k * step_sec


def _breath_curve(n: int, depth: float, rng: random.Random) -> list[float]:
    """Медленное блуждание громкости (AR(1)): партия «дышит», а не скачет. Чистая."""
    x, out = 0.0, []
    for _ in range(n):
        x = 0.92 * x + rng.gauss(0.0, depth * 0.4)
        x = max(-depth, min(depth, x))
        out.append(x)
    return out


def apply_groove(events: list, role: str, perf: dict | None, swing: float,
                 beat_sec: float, rng: random.Random) -> list:
    """Мелодические события [(t, midi|[midi], vel, dur)] → сыгранные «руками».
      тайминг: позиция на сетке + свинг 16-х КАК У БАРАБАНОВ (_swt) + оттяжка роли
               + малая дрожь. Ноты вне сетки (свободные) сохраняют своё место + оттяжка.
      velocity: окно роли × метрический вес доли × дыхание (+ немного исходной фразы у лида).
    Бас/барабаны и perf=None → без изменений. Чистая при rng."""
    if not perf or role not in GROOVE_ROLES or not events or beat_sec <= 0:
        return events
    step_sec = beat_sec / 4
    lag = perf["lag_ms"].get(role, 0.0) / 1000.0
    jit = perf["jitter_ms"].get(role, 0.0) / 1000.0
    lo, hi = perf["vel"].get(role, (40, 100))
    breath = _breath_curve(len(events), perf["breath"], rng)
    keep_orig = 0.35 if role == "lead" else 0.0          # у темы своя дуга фразы
    out = []
    for i, ev in enumerate(sorted(events, key=lambda e: e[0])):
        t, note, vel, dur = ev[0], ev[1], ev[2], ev[3]
        step, dev = grid_position(t, beat_sec)
        on_grid = abs(dev) <= min(0.03, step_sec * 0.3)
        w = METRIC_WEIGHT[step] if on_grid else 0.45
        if role == "pad":                    # пад: только дыхание громкости, страм не трогаем
            w, t_new = 0.5, t
        elif on_grid:
            t_new = t - dev + (step_sec * swing if step % 2 == 1 else 0.0)
        else:
            t_new = t
        t_new += lag + (rng.gauss(0.0, jit) if jit > 0 else 0.0)
        v = (lo + (hi - lo) * w) * (1.0 + breath[i]) + rng.gauss(0.0, 2.5)
        v = keep_orig * float(vel) + (1.0 - keep_orig) * v
        out.append((max(0.0, t_new), note, int(np.clip(round(v), 1, 127)), dur) + tuple(ev[4:]))
    return sorted(out, key=lambda e: e[0])


def thin_events(events: list, keep: float, beat_sec: float, rng: random.Random,
                protect_strong: bool = False) -> list:
    """Реже, но осмысленнее: вероятность остаться растёт с весом доли. keep≥1 → как
    было; keep≤0 → пусто. protect_strong: сильные доли (вес ≥0.7) не трогаются. Чистая."""
    if keep >= 1.0 or not events:
        return list(events)
    if keep <= 0.0:
        return []
    out = []
    for ev in events:
        step, _ = grid_position(ev[0], beat_sec)
        w = METRIC_WEIGHT[step]
        if protect_strong and w >= 0.7:
            out.append(ev)
            continue
        p = min(1.0, keep * (0.55 + 0.9 * w))
        if rng.random() < p:
            out.append(ev)
    return out


def _onepole_lp(x: np.ndarray, sr: int, hz: float) -> np.ndarray:
    from scipy.signal import lfilter
    a = float(np.exp(-2.0 * np.pi * hz / sr))
    return lfilter([1.0 - a], [1.0, -a], x).astype(np.float32)


def _onepole_hp(x: np.ndarray, sr: int, hz: float) -> np.ndarray:
    return (x - _onepole_lp(x, sr, hz)).astype(np.float32)


def echo(buf: np.ndarray, sr: int, time_s: float, feedback: float, wet: float,
         lp_hz: float = 3500.0, hp_hz: float = 250.0, pingpong: bool = True,
         duck: float = 0.6, max_repeats: int = 24) -> np.ndarray:
    """Длинный delay для плаков: эхо заполняет пространство вместо лишних нот.
    Каждый повтор темнее (LPF в петле), низ срезан (не мутит бас), пинг-понг L/R,
    эхо приглушается, пока звучит сухая нота (не маскирует атаку). (n,2) → (n,2)."""
    if buf.ndim != 2 or wet <= 0 or feedback <= 0 or time_s <= 0:
        return buf
    n = len(buf)
    mono = buf.mean(axis=1).astype(np.float32)
    tap = _onepole_hp(mono, sr, hp_hz)
    wet_buf = np.zeros_like(buf, dtype=np.float32)
    g, k = 1.0, 1
    while k <= max_repeats:
        g *= feedback
        if g < 0.015:
            break
        shift = int(round(k * time_s * sr))
        if shift >= n:
            break
        tap = _onepole_lp(tap, sr, lp_hz)
        seg = g * tap[:n - shift]
        if pingpong:
            ch = (k - 1) % 2
            wet_buf[shift:, ch] += seg
            wet_buf[shift:, 1 - ch] += seg * 0.25
        else:
            wet_buf[shift:, 0] += seg
            wet_buf[shift:, 1] += seg
        k += 1
    if duck > 0:
        env = _onepole_lp(np.abs(mono), sr, 4.0)               # ~40 мс сглаживание
        ref = float(np.percentile(env, 95)) or 1.0
        gain = 1.0 - duck * np.clip(env / ref, 0.0, 1.0)
        wet_buf *= gain[:, None]
    return (buf + wet * wet_buf).astype(np.float32)
