#!/usr/bin/env python3
"""
arrangement.py — Q2: секционная аранжировка вместо кроссфейда слоёв.

Диагноз (спека 008): слои плавно вводились огибающими по всей длине, паттерны между
секциями не менялись, филлов не было, «дроп» = просто громче. Живая электроника
устроена иначе: секции отличаются СОДЕРЖИМЫМ (что играет, а не насколько громко),
а на стыках стоят филлы и сбросы.

Модель: трек = последовательность секций (intro / build / drop / breakdown / outro).
Для барабанов это значит:
  intro      — только кик и редкий хэт, без снейра;
  build      — плотность растёт, хэты дробятся, в последнем такте ФИЛЛ по томам;
  drop       — полный паттерн, акценты сильнее;
  breakdown  — барабаны почти уходят (остаются акценты), возвращаются в дропе;
  outro      — разрежение обратно к кику.
Плюс ghost-удары (тихие) в дропе — «дыхание» грува.

Чистые функции над hit-листом [(время_сек, имя, velocity)] — тестируются офлайн,
на аудио не завязаны.
"""
from __future__ import annotations

import random

# доля событий, которые остаются в секции, по ролям
DENSITY = {
    "intro":     {"kick": 1.0, "snare": 0.0, "closed_hat": 0.35, "open_hat": 0.2,
                  "clap": 0.0, "ride": 0.0, "perc": 0.3},
    "build":     {"kick": 1.0, "snare": 0.7, "closed_hat": 1.0, "open_hat": 0.6,
                  "clap": 0.6, "ride": 0.5, "perc": 0.8},
    "drop":      {"kick": 1.0, "snare": 1.0, "closed_hat": 1.0, "open_hat": 1.0,
                  "clap": 1.0, "ride": 1.0, "perc": 1.0},
    "breakdown": {"kick": 0.0, "snare": 0.15, "closed_hat": 0.2, "open_hat": 0.1,
                  "clap": 0.2, "ride": 0.3, "perc": 0.4},
    "outro":     {"kick": 0.8, "snare": 0.3, "closed_hat": 0.4, "open_hat": 0.2,
                  "clap": 0.2, "ride": 0.2, "perc": 0.3},
}

# множители громкости по секциям (дроп не просто «громче» — он ПЛОТНЕЕ)
VEL_SCALE = {"intro": 0.85, "build": 0.95, "drop": 1.0, "breakdown": 0.7, "outro": 0.8}

FILL_DRUMS = ("tom_high", "tom_mid", "tom_low", "snare")


def default_plan(total_bars: int) -> list[tuple[int, int, str]]:
    """Каркас аранжировки по длине трека: [(бар_от, бар_до, вид)]. Чистая.
    Пропорции — типовые для клубного трека; короткие треки получают меньше секций."""
    if total_bars < 16:
        return [(0, total_bars, "drop")]
    if total_bars < 48:
        i = max(4, total_bars // 8)
        o = max(4, total_bars // 8)
        b = max(4, total_bars // 6)
        return [(0, i, "intro"), (i, i + b, "build"),
                (i + b, total_bars - o, "drop"), (total_bars - o, total_bars, "outro")]
    i = total_bars // 8
    o = total_bars // 8
    b1 = total_bars // 12
    d1 = total_bars // 4
    bd = total_bars // 10
    b2 = total_bars // 16
    marks = [(0, i, "intro"), (i, i + b1, "build"), (i + b1, i + b1 + d1, "drop")]
    cur = i + b1 + d1
    marks.append((cur, cur + bd, "breakdown")); cur += bd
    marks.append((cur, cur + b2, "build")); cur += b2
    marks.append((cur, total_bars - o, "drop"))
    marks.append((total_bars - o, total_bars, "outro"))
    return [(a, b, k) for a, b, k in marks if b > a]


def section_at(plan: list[tuple[int, int, str]], bar: float) -> str:
    for a, b, kind in plan:
        if a <= bar < b:
            return kind
    return plan[-1][2] if plan else "drop"


def make_fill(bar_start_sec: float, bar_sec: float, seed: int = 0,
              steps: int = 8) -> list[tuple[float, str, int]]:
    """Филл на последний такт перед сменой секции: спуск по томам + снейр-раскат.
    Чистая (при фиксированном seed)."""
    rng = random.Random(seed)
    out = []
    for k in range(steps):
        t = bar_start_sec + bar_sec * k / steps
        drum = FILL_DRUMS[min(len(FILL_DRUMS) - 1, k * len(FILL_DRUMS) // steps)]
        vel = int(70 + 50 * (k + 1) / steps + rng.randint(-6, 6))
        out.append((t, drum, max(30, min(127, vel))))
    return out


def apply_sections(hits: list, bar_sec: float, plan: list[tuple[int, int, str]],
                   seed: int = 0, fills: bool = True,
                   ghosts: bool = True) -> list[tuple[float, str, int]]:
    """Главная функция Q2: hit-лист → аранжированный hit-лист. Чистая.
      • прореживание по DENSITY (секции отличаются СОДЕРЖИМЫМ);
      • VEL_SCALE (дроп плотнее, брейкдаун тише);
      • ФИЛЛ в последнем такте перед сменой секции;
      • ghost-снейры в дропе (тихие, между долями) — «дыхание» грува."""
    rng = random.Random(seed)
    out: list[tuple[float, str, int]] = []
    for t, name, vel in hits:
        bar = t / bar_sec if bar_sec else 0
        kind = section_at(plan, bar)
        keep = DENSITY.get(kind, DENSITY["drop"]).get(str(name).lower(), 0.8)
        if keep <= 0.0 or rng.random() > keep:
            continue
        out.append((t, name, int(max(1, min(127, vel * VEL_SCALE.get(kind, 1.0))))))

    if fills:
        for a, b, _kind in plan[:-1]:                       # перед каждой сменой, кроме конца
            fill_bar = b - 1
            if fill_bar <= a:
                continue
            start = fill_bar * bar_sec
            out = [h for h in out if not (start <= h[0] < start + bar_sec
                                          and str(h[1]).lower() in ("closed_hat", "open_hat"))]
            out.extend(make_fill(start, bar_sec, seed + b))

    if ghosts:
        for a, b, kind in plan:
            if kind != "drop":
                continue
            for bar in range(a, b):
                if rng.random() < 0.35:                     # не в каждом такте
                    t = (bar + rng.choice([0.375, 0.875])) * bar_sec
                    out.append((t, "snare", rng.randint(18, 32)))   # тихий ghost

    return sorted(out, key=lambda h: h[0])


def layer_section_gain(role: str, kind: str) -> float:
    """Множитель слоя по секции — чтобы мелодические партии тоже жили по структуре
    (в брейкдауне пад/лид на первый план, в интро лида нет). Чистая."""
    table = {
        "intro":     {"pad": 0.9, "lead": 0.0, "arp": 0.3, "bass": 0.5, "counter": 0.0},
        "build":     {"pad": 0.9, "lead": 0.5, "arp": 0.8, "bass": 0.9, "counter": 0.4},
        "drop":      {"pad": 0.8, "lead": 1.0, "arp": 1.0, "bass": 1.0, "counter": 0.9},
        "breakdown": {"pad": 1.0, "lead": 0.8, "arp": 0.4, "bass": 0.3, "counter": 0.6},
        "outro":     {"pad": 0.9, "lead": 0.3, "arp": 0.4, "bass": 0.6, "counter": 0.2},
    }
    return table.get(kind, table["drop"]).get(role, 1.0)

def section_gain_envelope(role: str, plan: list, bar_sec: float, total: int,
                          sr: int, smooth_ms: float = 150.0):
    """Огибающая слоя ПО СЕКЦИЯМ (Q2 для мелодических партий): лид молчит в интро,
    пад выходит вперёд в брейкдауне, бас проваливается и т.д. Переходы сглажены
    (без щелчков). numpy in → numpy out, чистая.
    Умножается НА существующий rcos_env — тот отвечает за общие вход/выход трека,
    эта — за структуру внутри."""
    import numpy as np
    env = np.ones(total, dtype="float32")
    if not plan or bar_sec <= 0:
        return env
    for a, b, kind in plan:
        i0 = max(0, min(total, int(a * bar_sec * sr)))
        i1 = max(0, min(total, int(b * bar_sec * sr)))
        if i1 > i0:
            env[i0:i1] = layer_section_gain(role, kind)
    n = max(1, int(sr * smooth_ms / 1000))
    if n > 1 and total > n:                       # сглаживание стыков скользящим средним
        k = np.ones(n, dtype="float32") / n
        env = np.convolve(env, k, mode="same").astype("float32")
    return env

# ═══ P92: МАТРИЦА АКТИВАЦИИ — кто играет, кто молчит, кто главный ═══════════
# Диагноз (прослушка Стаса + разбор Claw): одновременно звучали ШЕСТЬ синт-слоёв
# (lead + acid bass + расстроенный pad + arp + counter + accent), каждый со своей
# независимой логикой, все — непрерывно. Отсюда «гудение на фоне», «инструменты
# играют сами по себе», «артхаус». Гейнами это не лечится: нужна ИЕРАРХИЯ и ПАУЗЫ.
#
# Правила живой аранжировки, которые здесь закодированы:
#   1. В каждой секции есть ФОКУС — один ведущий голос, остальные его поддерживают.
#   2. Максимум MAX_VOICES активных мелодических слоёв; лишние выключаются ПОЛНОСТЬЮ
#      (0.0, а не «потише») по приоритету.
#   3. Пад — не фон на весь трек: он ведёт брейкдаун и МОЛЧИТ в дропе.
#   4. Второстепенные линии ЧЕРЕДУЮТСЯ (call-and-response) окнами по 4-8 тактов,
#      а не играют одновременно.
#   5. Не-фокусные слои приглушены относительно фокуса (не спорят за внимание).

MAX_VOICES = 3          # мелодических слоёв одновременно (кроме drums/bass)

# (уровень, приоритет) — приоритет решает, кого выключить при переполнении
ACTIVATION = {
    "intro":     {"drums": (0.85, 9), "bass": (0.70, 8), "pad": (0.45, 5),
                  "arp": (0.0, 2), "lead": (0.0, 1), "counter": (0.0, 1), "accent": (0.25, 3)},
    "build":     {"drums": (0.95, 9), "bass": (0.85, 8), "arp": (0.80, 6),
                  "pad": (0.35, 4), "lead": (0.0, 2), "counter": (0.30, 3), "accent": (0.40, 5)},
    "drop":      {"drums": (1.00, 9), "bass": (1.00, 8), "lead": (0.95, 7),
                  "pad": (0.0, 1), "arp": (0.45, 5), "counter": (0.0, 2), "accent": (0.35, 4)},
    "breakdown": {"pad": (0.95, 8), "lead": (0.55, 6), "counter": (0.45, 5),
                  "drums": (0.0, 1), "bass": (0.25, 4), "arp": (0.0, 2), "accent": (0.30, 3)},
    "outro":     {"drums": (0.70, 9), "bass": (0.55, 8), "pad": (0.60, 6),
                  "arp": (0.25, 4), "lead": (0.0, 2), "counter": (0.0, 1), "accent": (0.20, 3)},
}

FOCUS = {"intro": "drums", "build": "arp", "drop": "lead",
         "breakdown": "pad", "outro": "pad"}

MELODIC = ("lead", "arp", "pad", "counter", "accent")
SECONDARY = ("arp", "counter", "accent")     # чередуются между собой


def active_roles(kind: str, max_voices: int = MAX_VOICES) -> dict:
    """Кто играет в секции и с каким уровнем. Лишние мелодические слои выключаются
    ПОЛНОСТЬЮ по приоритету (не «потише», а молчат). Чистая."""
    table = ACTIVATION.get(kind, ACTIVATION["drop"])
    out = {r: lvl for r, (lvl, _) in table.items()}
    melodic_on = [(r, table[r][1]) for r in MELODIC if out.get(r, 0.0) > 0.0]
    if len(melodic_on) > max_voices:
        melodic_on.sort(key=lambda x: x[1], reverse=True)
        for r, _ in melodic_on[max_voices:]:
            out[r] = 0.0
    return out


def turn_window(role: str, bar: int, rng_seed: int = 0, window: int = 8) -> float:
    """Call-and-response: второстепенные линии ЧЕРЕДУЮТСЯ окнами, а не играют
    одновременно. Возвращает множитель 1.0 (её окно) или 0.0 (молчит). Чистая."""
    if role not in SECONDARY:
        return 1.0
    slot = (bar // max(1, window) + rng_seed) % len(SECONDARY)
    return 1.0 if SECONDARY[slot] == role else 0.0


def activation_envelope(role: str, plan: list, bar_sec: float, total: int, sr: int,
                        max_voices: int = MAX_VOICES, seed: int = 0,
                        smooth_ms: float = 120.0, turn_taking: bool = True):
    """Огибающая слоя по МАТРИЦЕ АКТИВАЦИИ + чередование + приглушение не-фокуса.
    Заменяет мягкий layer_section_gain: здесь есть настоящие ПАУЗЫ. numpy out."""
    import numpy as np
    env = np.zeros(total, dtype="float32")
    if not plan or bar_sec <= 0:
        return env + 1.0
    for a, b, kind in plan:
        lvl = active_roles(kind, max_voices).get(role, 0.0)
        if lvl <= 0.0:
            continue
        if role != FOCUS.get(kind) and role in MELODIC:
            lvl *= 0.75                                   # не спорим с фокусом
        for bar in range(a, b):
            i0 = max(0, min(total, int(bar * bar_sec * sr)))
            i1 = max(0, min(total, int((bar + 1) * bar_sec * sr)))
            if i1 <= i0:
                continue
            g = lvl * (turn_window(role, bar, seed) if turn_taking else 1.0)
            env[i0:i1] = g
    n = max(1, int(sr * smooth_ms / 1000))
    if n > 1 and total > n:                               # мягкие входы/выходы
        k = np.ones(n, dtype="float32") / n
        env = np.convolve(env, k, mode="same").astype("float32")
    return env


# ─── Баланс барабанов: плотный низ, без «звона» ─────────────────────────────
# Запрос Стаса: «низкочастотные плотные биты, даунбит ритмичный, не звенящие ударные».
DRUM_BALANCE = {
    "kick": 1.25, "bd": 1.25,                 # бочка вперёд — даунбит слышен
    "snare": 0.95, "sd": 0.95, "clap": 0.85, "cp": 0.85,
    "closed_hat": 0.55, "hh": 0.55,           # хэты назад — уходит «звон»
    "open_hat": 0.45, "oh": 0.45,
    "ride": 0.40, "rd": 0.40, "crash": 0.45, "cr": 0.45,
    "tom_low": 1.0, "tom_mid": 0.9, "tom_high": 0.8,
}


def balance_drums(hits: list, downbeat_boost: float = 1.15) -> list:
    """Velocity по ролям барабанов: бочка/низ вперёд, тарелки назад; удар НА ДАУНБИТЕ
    дополнительно акцентирован. Чистая."""
    out = []
    for t, name, vel in hits:
        k = str(name).lower()
        g = DRUM_BALANCE.get(k, 1.0)
        v = float(vel) * g
        if k in ("kick", "bd"):
            v *= downbeat_boost
        out.append((t, name, int(max(1, min(127, round(v))))))
    return out

