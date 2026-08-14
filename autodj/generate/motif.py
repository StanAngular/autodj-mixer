#!/usr/bin/env python3
"""
motif.py — P86: мотивная мелодия с развитием + ГАРАНТИЯ НОВИЗНЫ каждого трека.

Две проблемы, которые это закрывает (диагноз Claw + прослушки Стаса):
  1. «Мелодия примитивная»: ноты выбирались случайно из гаммы (`rng.choice`), без
     памяти фраз и развития — получался бессвязный набор, а не тема.
  2. «Треки похожи друг на друга»: 5-7 фиксированных ритм-шаблонов на стиль +
     одинаковые дефолты → узнаваемая шаблонность из трека в трек.

Решение:
  • МОТИВ — короткая тема (4-8 нот: интервалы + ритм), сочиняется заново под трек;
  • РАЗВИТИЕ — классические приёмы: инверсия, ретроград, секвенция (транспозиция),
    аугментация/диминуция (растяжение/сжатие ритма), орнаментация. Секции получают
    РАЗНЫЕ трансформации → есть тема, есть контраст, есть узнаваемость внутри трека;
  • НОВИЗНА — `track_identity()`: на каждый рендер генерируются свои ритм (Евклид со
    случайными параметрами, НЕ из списка шаблонов), контур, регистры, плотности,
    разброс эффектов. Один и тот же seed воспроизводит трек в точности — это режим
    «дорабатываем уже созданный», и он включается ТОЛЬКО явным seed.

Чистые функции (random.Random внутрь передаётся) — тестируются офлайн.
"""
from __future__ import annotations

import hashlib
import random
import time

# ─── Мотив ──────────────────────────────────────────────────────────────────

def new_motif(rng: random.Random, length: int | None = None) -> list[tuple[int, float]]:
    """Свежая тема: [(шаг_по_гамме_относительно_предыдущей, длительность_в_долях)].
    Контур выбирается осмысленно (не белый шум): подъём, арка, спуск, зигзаг.
    Чистая (при заданном rng)."""
    n = length or rng.choice([4, 5, 6, 8])
    shape = rng.choice(["rise", "arch", "fall", "zigzag", "pivot"])
    steps: list[int] = []
    for i in range(n):
        f = i / max(1, n - 1)
        if shape == "rise":
            base = rng.choice([1, 1, 2])
        elif shape == "fall":
            base = rng.choice([-1, -1, -2])
        elif shape == "arch":
            base = rng.choice([1, 2]) if f < 0.5 else rng.choice([-1, -2])
        elif shape == "zigzag":
            base = rng.choice([2, -1]) if i % 2 == 0 else rng.choice([-2, 1])
        else:                                            # pivot — вращение вокруг опоры
            base = rng.choice([0, 1, -1, 2, -2])
        steps.append(base)
    durs = [rng.choice([0.5, 0.5, 1.0, 1.0, 1.5, 2.0]) for _ in range(n)]
    return list(zip(steps, durs))


def invert(motif):
    """Инверсия: интервалы наоборот (вверх→вниз). Чистая."""
    return [(-s, d) for s, d in motif]


def retrograde(motif):
    """Ретроград: тема задом наперёд. Чистая."""
    return list(reversed(motif))


def augment(motif, factor: float = 2.0):
    """Аугментация: длительности растянуты (тема «замедляется»). Чистая."""
    return [(s, d * factor) for s, d in motif]


def diminish(motif, factor: float = 0.5):
    """Диминуция: длительности сжаты (тема «разгоняется»). Чистая."""
    return [(s, max(0.125, d * factor)) for s, d in motif]


def ornament(motif, rng: random.Random, prob: float = 0.35):
    """Орнаментация: между нотами вставляются проходящие. Чистая (при rng)."""
    out = []
    for s, d in motif:
        if d >= 1.0 and rng.random() < prob:
            out.append((s, d / 2))
            out.append((rng.choice([1, -1]), d / 2))
        else:
            out.append((s, d))
    return out


TRANSFORMS = {
    "intro":     ("fragment",),
    "build":     ("sequence", "diminish"),
    "drop":      ("theme", "ornament"),
    "breakdown": ("augment", "invert"),
    "outro":     ("fragment", "augment"),
}


def develop(motif, kind: str, rng: random.Random) -> list[tuple[int, float]]:
    """Трансформация темы под секцию: контраст есть, но узнаваемость сохраняется."""
    ops = TRANSFORMS.get(kind, ("theme",))
    out = list(motif)
    for op in ops:
        if op == "fragment":
            out = out[: max(2, len(out) // 2)]
        elif op == "sequence":
            out = out + [(s + rng.choice([1, 2]), d) for s, d in out]   # секвенция вверх
        elif op == "invert":
            out = invert(out)
        elif op == "retrograde":
            out = retrograde(out)
        elif op == "augment":
            out = augment(out, rng.choice([1.5, 2.0]))
        elif op == "diminish":
            out = diminish(out, rng.choice([0.5, 0.75]))
        elif op == "ornament":
            out = ornament(out, rng)
    return out


# ─── Ритм без шаблонов (Евклид со случайными параметрами) ───────────────────

def euclidean(pulses: int, steps: int) -> list[int]:
    """Равномерное распределение k ударов по n шагам (алгоритм Бьорклунда, упрощённый).
    Чистая. Даёт органичные ритмы вместо списка готовых шаблонов."""
    if steps <= 0 or pulses <= 0:
        return [0] * max(0, steps)
    pattern = []
    bucket = 0
    for _ in range(steps):
        bucket += pulses
        if bucket >= steps:
            bucket -= steps
            pattern.append(1)
        else:
            pattern.append(0)
    return pattern


def random_rhythm(rng: random.Random, steps: int = 16) -> list[int]:
    """Свежий ритм на трек: Евклид со случайной плотностью + случайный поворот.
    НЕ выбор из 5-7 шаблонов — отсюда уходит межтрековая шаблонность."""
    pulses = rng.randint(max(2, steps // 5), max(3, steps // 2))
    pat = euclidean(pulses, steps)
    rot = rng.randrange(steps)
    return pat[rot:] + pat[:rot]


# ─── Личность трека (гарантия новизны) ──────────────────────────────────────

def track_identity(seed: int | None = None) -> dict:
    """Уникальные параметры ЭТОГО трека. seed=None → новый каждый рендер (требование
    Стаса: каждый раз новый трек). Явный seed = точное воспроизведение, режим
    «дорабатываем уже созданный». Возвращает и отпечаток для лога/каталога."""
    if seed is None:
        seed = int.from_bytes(hashlib.blake2b(
            f"{time.time_ns()}{random.random()}".encode(), digest_size=4).digest(), "big")
    rng = random.Random(seed)
    ident = {
        "seed": seed,
        "motif": new_motif(rng),
        "rhythm": random_rhythm(rng),
        "lead_octave": rng.choice([0, 0, 12, -12]),          # регистровое разведение
        "pad_octave": rng.choice([-12, -12, 0]),
        "arp_octave": rng.choice([0, 12]),
        "lead_density": round(rng.uniform(0.3, 0.7), 2),
        "syncopation": round(rng.uniform(0.1, 0.45), 2),
        "reverb_jitter": round(rng.uniform(-0.12, 0.12), 3),  # разное «пространство»
        "gain_jitter": round(rng.uniform(-0.08, 0.08), 3),
        "swing": round(rng.uniform(0.0, 0.12), 3),
    }
    ident["fingerprint"] = hashlib.blake2b(
        repr([ident["motif"], ident["rhythm"], ident["lead_octave"],
              ident["lead_density"], ident["syncopation"]]).encode(),
        digest_size=6).hexdigest()
    return ident


# ─── Мелодия по секциям ─────────────────────────────────────────────────────

def motif_to_notes(motif, scale: list[int], root_midi: int, start_beat: float,
                   beat_sec: float, chord: list[int] | None = None,
                   octave: int = 0) -> list[tuple[float, int, int, float]]:
    """Тема (шаги по гамме) → события [(t, midi, velocity, dur)]. Опорные ноты
    подтягиваются к тонам аккорда — мелодия остаётся в гармонии. Чистая."""
    out = []
    deg = 0
    beat = start_beat
    for i, (step, dur) in enumerate(motif):
        deg += step
        idx = deg % len(scale)
        octs = deg // len(scale)
        midi = root_midi + scale[idx] + 12 * octs + octave
        if chord and i % 4 == 0:                              # опора — тон аккорда
            midi = min(chord, key=lambda c: abs((c % 12) - (midi % 12))) + 12 * octs + octave
        vel = 78 + (18 if i % 4 == 0 else 0) + (6 if dur >= 1.0 else 0)
        out.append((beat * beat_sec, int(midi), int(min(120, vel)), dur * beat_sec * 0.92))
        beat += dur
    return out


def melody_for_sections(plan, chords, scale, root_midi, bpm, ident: dict,
                        rng: random.Random) -> list[tuple[float, int, int, float]]:
    """Мелодия всего трека: одна тема, развитая по секциям. Лид молчит в интро
    (это делает P83), но тема прорастает в build → drop → breakdown."""
    beat_sec = 60.0 / bpm
    bar_beats = 4.0
    events = []
    motif = ident["motif"]
    for a, b, kind in plan:
        if kind == "intro":
            continue
        phrase = develop(motif, kind, rng)
        beat = a * bar_beats
        end_beat = b * bar_beats
        ci = 0
        while beat < end_beat - 1:
            chord = chords[ci % len(chords)] if chords else None
            notes = motif_to_notes(phrase, scale, root_midi, beat, beat_sec,
                                   chord, ident["lead_octave"])
            events.extend([e for e in notes if e[0] < end_beat * beat_sec])
            beat += sum(d for _, d in phrase) + rng.choice([0.0, 1.0, 2.0])  # дыхание
            ci += 1
            if rng.random() < 0.3:                            # вариация внутри секции
                phrase = develop(motif, kind, rng)
    return sorted(events, key=lambda e: e[0])

# ─── P88: гармония и параметры слоёв — тоже уникальные на трек ──────────────
# Диагноз: прогрессия была ЗАШИТА в жанр (`progression="dark_techno"`), поэтому у всех
# треков жанра одна и та же гармония; из 10 параметров track_identity применялись 2.
# Совместимость по настроению: техно не должно вдруг зазвучать как neo-soul.

PROGRESSION_POOLS = {
    "dark_techno":  ("dark_techno", "industrial", "psychedelic", "plagal", "modal_interchange"),
    "industrial":   ("industrial", "dark_techno", "psychedelic", "plagal"),
    "psychedelic":  ("psychedelic", "dark_techno", "trance", "modal_interchange"),
    "trance":       ("trance", "psychedelic", "plagal", "modal_interchange"),
    "deep_house":   ("deep_house", "lounge", "deep_lounge", "neo_soul", "plagal"),
    "lounge":       ("lounge", "deep_lounge", "neo_soul", "deep_house"),
    "deep_lounge":  ("deep_lounge", "lounge", "neo_soul", "ambient"),
    "neo_soul":     ("neo_soul", "deep_lounge", "lounge", "secondary_dom"),
    "ambient":      ("ambient", "deep_lounge", "plagal", "modal_interchange"),
    "indie":        ("indie", "modal_interchange", "plagal", "secondary_dom"),
    "breakbeat":    ("breakbeat", "indie", "dark_techno", "psychedelic"),
}


def pick_progression(base: str, rng: random.Random) -> tuple[str, bool]:
    """Прогрессия ЭТОГО трека из пула, совместимого с жанром + шанс септаккордов.
    Чистая (при rng). Базовая остаётся в пуле — жанр узнаваем, но не повторяется."""
    pool = PROGRESSION_POOLS.get(base, (base, "plagal", "modal_interchange"))
    return rng.choice(pool), rng.random() < 0.35


def apply_octave(events: list, semitones: int) -> list:
    """Сдвиг слоя по регистру (разведение полос). Поддерживает ноты (t, midi, vel, dur)
    и аккорды (t, [midi…], vel, dur). Чистая."""
    if not semitones:
        return events
    out = []
    for ev in events:
        t, notes, vel, dur = ev[0], ev[1], ev[2], ev[3]
        if isinstance(notes, (list, tuple)):
            out.append((t, [int(n) + semitones for n in notes], vel, dur))
        else:
            out.append((t, int(notes) + semitones, vel, dur))
    return out


def apply_swing(events: list, swing: float, beat_sec: float) -> list:
    """Свинг: каждая вторая восьмая сдвигается позже (грув вместо машинной сетки).
    Чистая."""
    if swing <= 0 or beat_sec <= 0:
        return events
    half = beat_sec / 2
    out = []
    for ev in events:
        t = ev[0]
        pos = (t % beat_sec) / beat_sec
        shift = swing * half if 0.4 < pos < 0.6 else 0.0
        out.append((t + shift,) + tuple(ev[1:]))
    return sorted(out, key=lambda e: e[0])


def syncopate(events: list, amount: float, beat_sec: float,
              rng: random.Random) -> list:
    """Синкопа: часть нот смещается с доли на слабую позицию. Чистая (при rng)."""
    if amount <= 0:
        return events
    out = []
    for ev in events:
        t = ev[0]
        on_beat = abs((t % beat_sec)) < beat_sec * 0.08
        if on_beat and rng.random() < amount:
            t = t + beat_sec * rng.choice([0.25, 0.5, 0.75])
        out.append((t,) + tuple(ev[1:]))
    return sorted(out, key=lambda e: e[0])

