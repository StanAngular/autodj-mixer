"""P94/P95: ФАКТУРА и МАКРО-ДИНАМИКА. Чистые функции.

Отзыв Стаса (2026-10-08): «мелодичности ноль, как будто кто-то бренчит без навыков».
Старая мелодия = случайные шаги по гамме, без фразы, без повтора, без каденции;
Rhodes 68 нот за 7 минут; вибрафон — случайные ноты гаммы; фильтр открывается
один раз на интро; каркас трека у всех одинаковый.

Здесь:
  * phrase_melody — мелодия ФРАЗАМИ: ритм-мотив на 2 такта, вопрос (A, конец на 3/5)
    → ответ (A', конец на тонике), середина B, повтор; на сильных долях тоны аккорда,
    на слабых — поступенное движение. Тема узнаваема и развивается по секциям.
  * comp_events — Rhodes компингом: синкопы и предъёмы, бескорневые расположения
    (3-5-7-9), плавное голосоведение.
  * answer_events — вибрафон/плаки отвечают в паузах лида фрагментом его фразы.
  * plan_variant — несколько каркасов аранжировки, выбор на трек.
  * filter_macro — LPF раскрывается к кульминациям и закрывается в ямах.
Каждый трек получает свои параметры (sample_texture) — однотипности нет.
"""
from __future__ import annotations

import random

import numpy as np

# ─── профиль фактуры трека ───────────────────────────────────────────────────

COMP_PATTERNS = [            # (шаг 16-й, длительность в 16-х) на такт; синкопы/предъёмы
    [(0, 3), (6, 2), (10, 4)],
    [(3, 2), (8, 3), (14, 2)],
    [(2, 2), (7, 3), (12, 2), (15, 1)],
    [(0, 2), (3, 3), (10, 2), (14, 2)],
    [(6, 4), (14, 2)],
    [(0, 6), (11, 3)],
    [(4, 2), (7, 2), (12, 4)],
]

PLAN_TEMPLATES = {
    # доли трека по секциям (сумма 1.0)
    "classic":      [("intro", .125), ("build", .083), ("drop", .25), ("breakdown", .1),
                     ("build", .0625), ("drop", .2545), ("outro", .125)],
    "slow_burn":    [("intro", .15), ("build", .15), ("drop", .25), ("breakdown", .12),
                     ("drop", .23), ("outro", .10)],
    "two_valleys":  [("intro", .10), ("build", .08), ("drop", .20), ("breakdown", .10),
                     ("build", .06), ("drop", .20), ("breakdown", .10), ("drop", .08),
                     ("outro", .08)],
    "open_sky":     [("intro", .12), ("breakdown", .14), ("build", .10), ("drop", .30),
                     ("breakdown", .10), ("drop", .14), ("outro", .10)],
}


def sample_texture(rng: random.Random) -> dict:
    """Параметры фактуры ЭТОГО трека. Чистая при rng."""
    return {
        "plan": rng.choice(sorted(PLAN_TEMPLATES)),
        "melody_density": rng.choice([4, 5, 5, 6, 7]),      # нот на 2-тактовый мотив
        "melody_low": rng.randint(62, 69),                   # нижняя граница регистра лида
        "leap_prob": round(rng.uniform(0.12, 0.3), 2),
        "comp_main": rng.randrange(len(COMP_PATTERNS)),
        "comp_alt": rng.randrange(len(COMP_PATTERNS)),
        "comp_ninth": rng.random() < 0.6,
        "answer_prob": round(rng.uniform(0.55, 0.85), 2),
        "answer_op": rng.choice(["retrograde", "echo", "sequence"]),
        "pluck_mode": rng.choice(["arp", "answer"]),
        "filter_lo": rng.randint(260, 700),
        "filter_hi": rng.randint(4500, 12000),
        "filter_curve": round(rng.uniform(0.6, 1.8), 2),
        "filter_peak": round(rng.uniform(0.55, 0.95), 2),     # где в дропе пик раскрытия
    }


# ─── каркас аранжировки ─────────────────────────────────────────────────────

def plan_variant(total_bars: int, name: str) -> list[tuple[int, int, str]]:
    """Шаблон → [(бар_от, бар_до, вид)], границы по 4 такта. Чистая."""
    tpl = PLAN_TEMPLATES.get(name) or PLAN_TEMPLATES["classic"]
    if total_bars < 32:
        return [(0, total_bars, "drop")]
    out, cur, acc = [], 0, 0.0
    for i, (kind, frac) in enumerate(tpl):
        acc += frac
        end = total_bars if i == len(tpl) - 1 else max(cur + 4, int(round(acc * total_bars / 4)) * 4)
        end = min(end, total_bars)
        if end > cur:
            out.append((cur, end, kind))
        cur = end
    return out


def section_at(plan, bar: float) -> str:
    for a, b, k in plan:
        if a <= bar < b:
            return k
    return plan[-1][2] if plan else "drop"


def chord_at(chords, t: float, bar_sec: float, chord_bars: int):
    return chords[int(t // (bar_sec * max(1, chord_bars))) % len(chords)]


# ─── мелодия фразами ────────────────────────────────────────────────────────

def _motif_rhythm(rng: random.Random, n: int) -> list[tuple[float, float]]:
    """Ритм мотива на 2 такта (8 долей): n нот, первая на сильной доле или предъём,
    последняя длинная, в конце воздух. [(старт_доля, длит_долей)]."""
    grid = [x * 0.5 for x in range(0, 13)]                   # 0..6 долей с шагом 1/8
    starts = sorted(set([0.0] + rng.sample(grid[1:], k=min(n - 1, len(grid) - 1))))
    out = []
    for i, s in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else min(8.0, s + rng.choice([1.5, 2.0]))
        out.append((s, max(0.5, nxt - s)))
    return out


def _contour(rng: random.Random, n: int, leap_prob: float) -> list[int]:
    """Шаги по гамме: в основном секунды, скачок компенсируется шагом назад."""
    steps, prev = [0], 0
    for _ in range(n - 1):
        if abs(prev) >= 3:
            s = -int(np.sign(prev)) * rng.choice([1, 1, 2])
        elif rng.random() < leap_prob:
            s = rng.choice([3, 4, -3, 4])
        else:
            s = rng.choice([1, 1, -1, -1, 2, -2, 0])
        steps.append(s)
        prev = s
    return steps


def _realize(rhythm, contour, start_beat, beat_sec, bar_sec, chords, chord_bars,
             pool, idx0, cadence: str | None):
    """Ступени → ноты: сильные доли и длинные ноты тянутся к тону аккорда."""
    out, idx = [], idx0
    for i, ((s, d), step) in enumerate(zip(rhythm, contour)):
        idx = max(0, min(len(pool) - 1, idx + step))
        t = (start_beat + s) * beat_sec
        ch = chord_at(chords, t + 0.01, bar_sec, chord_bars)
        pcs = {c % 12 for c in ch}
        strong = (s % 2 == 0) or d >= 1.5
        last = i == len(rhythm) - 1
        if last and cadence:
            root = ch[0] % 12
            target = {root} if cadence == "root" else ({c % 12 for c in ch[1:3]} or pcs)
            cand = [j for j, m in enumerate(pool) if m % 12 in target]
            if cand:
                idx = min(cand, key=lambda j: abs(j - idx))
        elif strong:
            cand = [j for j, m in enumerate(pool) if m % 12 in pcs]
            if cand:
                idx = min(cand, key=lambda j: abs(j - idx))
        vel = 92 if s % 4 == 0 else (80 if strong else 66)
        out.append((t, int(pool[idx]), vel, d * beat_sec * (0.95 if d >= 1 else 0.85)))
    return out, idx


def phrase_melody(plan, chords, scale_abs, bpm, chord_bars, tex, rng: random.Random):
    """Мелодия всего трека: мотив A (вопрос) / A' (ответ) / B / A' по 8 тактов,
    в секциях — фрагмент, полная форма, растянутая версия. Ноты [(t, midi, vel, dur)]."""
    beat_sec = 60.0 / bpm
    bar_sec = beat_sec * 4
    lo = tex["melody_low"]
    pool = [n for n in scale_abs if lo <= n <= lo + 19] or list(scale_abs)
    n = tex["melody_density"]
    rhy_a = _motif_rhythm(rng, n)
    con_a = _contour(rng, len(rhy_a), tex["leap_prob"])
    con_a2 = con_a[:-2] + _contour(rng, 2, tex["leap_prob"]) if len(con_a) > 3 else con_a
    rhy_b = _motif_rhythm(rng, max(3, n - 1))
    con_b = _contour(rng, len(rhy_b), tex["leap_prob"])
    home = len(pool) // 3
    form = [(rhy_a, con_a, "third"), (rhy_a, con_a2, "root"),
            (rhy_b, con_b, "third"), (rhy_a, con_a2, "root")]
    events = []
    for a, b, kind in plan:
        if kind == "intro":
            continue
        bar = a
        k = 0
        while bar + 2 <= b:
            rhy, con, cad = form[k % 4]
            if kind in ("build", "outro"):
                rhy = rhy[: max(2, len(rhy) // 2)]
                con = con[: len(rhy)]
                cad = None
            elif kind == "breakdown":
                rhy = [(s * 2, d * 2) for s, d in rhy if s * 2 < 8][:max(2, len(rhy) // 2)]
                con = con[: len(rhy)]
            span = 2 if kind != "breakdown" else 2
            notes, _ = _realize(rhy, con, bar * 4, beat_sec, bar_sec, chords, chord_bars,
                                pool, home, cad)
            events.extend(e for e in notes if e[0] < b * bar_sec)
            bar += span
            k += 1
            if kind in ("build", "outro") and k % 2 == 1:
                bar += 2                                  # во фрагментах больше воздуха
    return sorted(events, key=lambda e: e[0])


# ─── Rhodes: компинг ────────────────────────────────────────────────────────

def _rootless(chord, ninth: bool, lo=55, hi=74) -> list[int]:
    pcs = [c % 12 for c in chord]
    root = pcs[0]
    tones = pcs[1:] + ([(root + 2) % 12] if ninth else [])
    if not ninth and len(tones) < 3:
        tones = pcs
    out, base = [], lo
    for pc in tones:
        n = base + ((pc - base) % 12)
        while n > hi:
            n -= 12
        out.append(n)
    return sorted(set(out))


def _fold(notes, lo, hi):
    """Ноты в регистр [lo, hi] октавными переносами (звуки аккорда те же)."""
    out = []
    for n in notes:
        while n < lo:
            n += 12
        while n > hi:
            n -= 12
        out.append(n)
    return sorted(out)


def comp_events(plan, chords, chord_bars, bpm, tex, rng: random.Random,
                active=("build", "drop", "breakdown")):
    """Rhodes: синкопированные аккорды; на предъёме (шаг ≥14) уже следующий аккорд."""
    from .music_theory import voice_lead
    beat_sec = 60.0 / bpm
    bar_sec = beat_sec * 4
    step = bar_sec / 16
    main, alt = COMP_PATTERNS[tex["comp_main"]], COMP_PATTERNS[tex["comp_alt"]]
    events, prev = [], None
    for a, b, kind in plan:
        if kind not in active:
            continue
        for bar in range(a, b):
            pat = alt if bar % 4 == 3 else main
            if kind == "breakdown":
                pat = pat[:1]
            for st, ln in pat:
                t = bar * bar_sec + st * step
                ch = chord_at(chords, t + (step * 2 if st >= 14 else 0.0), bar_sec, chord_bars)
                voic = _rootless(ch, tex["comp_ninth"])
                if prev and len(prev) == len(voic):
                    voic = voice_lead(prev, voic)
                voic = _fold(voic, 55, 74)                # не сползать по октавам
                prev = voic
                for i, m in enumerate(voic):
                    events.append((t + i * rng.uniform(0.004, 0.012), int(m),
                                   72 if st % 4 == 0 else 62,
                                   (min(ln, 1.5) * step * 0.7) if tex.get("comp_staccato")
                                   else ln * step * 0.9))
    return sorted(events, key=lambda e: e[0])


# ─── ответы в паузах лида ───────────────────────────────────────────────────

def answer_events(lead, chords, chord_bars, bpm, tex, rng: random.Random,
                  lo=67, hi=86, prob=None):
    """В паузу лида (≥1.5 доли) — ответ фрагментом его последней фразы."""
    if not lead:
        return []
    beat_sec = 60.0 / bpm
    bar_sec = beat_sec * 4
    prob = tex["answer_prob"] if prob is None else prob
    lead = sorted(lead, key=lambda e: e[0])
    out = []
    for i in range(len(lead) - 1):
        end = lead[i][0] + lead[i][3]
        gap = lead[i + 1][0] - end
        if gap < 1.5 * beat_sec or rng.random() > prob:
            continue
        frag = lead[max(0, i - 2): i + 1]
        if tex["answer_op"] == "retrograde":
            frag = list(reversed(frag))
        t = end + 0.5 * beat_sec
        for j, f in enumerate(frag):
            if t > lead[i + 1][0] - 0.25 * beat_sec:
                break
            ch = chord_at(chords, t, bar_sec, chord_bars)
            pcs = {c % 12 for c in ch}
            target = f[1] + (12 if tex["answer_op"] == "echo" else 0) - (2 if tex["answer_op"] == "sequence" else 0)
            cands = [m for m in range(lo, hi + 1) if m % 12 in pcs]
            m = min(cands, key=lambda x: abs(x - target)) if cands else f[1]
            d = min(beat_sec, max(0.5 * beat_sec, f[3]))
            out.append((t, int(m), 70 - 6 * j, d))
            t += d
    return out


# ─── фильтр по секциям ──────────────────────────────────────────────────────

def cutoff_curve(plan, bar_sec, total, sr, tex, block: int, scale: float = 1.0) -> np.ndarray:
    """Кривая cutoff по блокам: интро глухо, build раскрывает, пик в дропе, яма закрыта."""
    lo, hi = tex["filter_lo"] * scale, tex["filter_hi"] * scale
    curve, peak = tex["filter_curve"], tex["filter_peak"]
    nb = total // block + 1
    out = np.empty(nb, dtype=np.float64)
    for i in range(nb):
        bar = i * block / sr / bar_sec
        kind, pos = "drop", 0.5
        for a, b, k in plan:
            if a <= bar < b:
                kind, pos = k, (bar - a) / max(1, b - a)
                break
        if kind == "intro":
            x = 0.15 * pos
        elif kind == "build":
            x = 0.2 + 0.7 * pos ** curve
        elif kind == "drop":
            x = 0.85 + 0.15 * (1 - abs(pos - peak) / max(peak, 1 - peak))
        elif kind == "breakdown":
            x = 0.05 + 0.35 * pos ** 2
        else:                                            # outro
            x = 0.7 * (1 - pos) ** curve
        out[i] = lo * (hi / lo) ** max(0.0, min(1.0, x))
    k = max(1, int(2 * bar_sec * sr / block))           # сглаживание ~2 такта
    out = np.convolve(np.pad(out, (k, k), mode="edge"), np.ones(k) / k, mode="same")[k:-k]
    return out


def filter_macro(buf: np.ndarray, sr: int, plan, bar_sec: float, tex: dict,
                 scale: float = 1.0, block: int = 2048) -> np.ndarray:
    """Плавный LPF по кривой секций (блоки + перенос состояния фильтра, без щелчков)."""
    from scipy.signal import butter, sosfilt, sosfilt_zi
    if buf.ndim != 2 or not plan:
        return buf
    total = len(buf)
    cut = cutoff_curve(plan, bar_sec, total, sr, tex, block, scale)
    out = np.empty_like(buf)
    zi = None
    for i in range(0, total, block):
        c = float(min(cut[i // block], sr / 2 - 200))
        sos = butter(2, c / (sr / 2), btype="low", output="sos")
        if zi is None:
            zi = np.stack([sosfilt_zi(sos) * 0.0 for _ in range(buf.shape[1])], axis=-1)
        seg, zi = sosfilt(sos, buf[i:i + block], axis=0, zi=zi)
        out[i:i + block] = seg
    return out.astype(np.float32)


# ─── P100: катящийся бас тек-хауса ──────────────────────────────────────────

ROLLING_BASS = [            # шаги 16-х без сильных долей (место бочке) — офбитный грув
    [2, 3, 6, 7, 10, 11, 14, 15],
    [2, 6, 10, 14],
    [2, 3, 6, 10, 11, 14],
    [3, 6, 7, 10, 14, 15],
    [2, 5, 6, 10, 13, 14],
]


def rolling_bass(plan, chords, chord_bars, bpm, rng: random.Random,
                 active=("build", "drop", "outro")):
    """Бас тек-хауса: офбитные 16-е на корне, октава/квинта как акценты, короткие ноты.
    Паттерн и вариация свои у каждого трека. [(t, midi, vel, dur)]."""
    beat_sec = 60.0 / bpm
    bar_sec = beat_sec * 4
    step = bar_sec / 16
    main = rng.choice(ROLLING_BASS)
    alt = rng.choice(ROLLING_BASS)
    oct_prob = rng.uniform(0.1, 0.3)
    gate = rng.uniform(0.45, 0.7)
    out = []
    for a, b, kind in plan:
        if kind not in active:
            continue
        for bar in range(a, b):
            pat = alt if bar % 8 == 7 else main
            for st in pat:
                t = bar * bar_sec + st * step
                ch = chord_at(chords, t + 0.01, bar_sec, chord_bars)
                root = ch[0] % 12
                n = 36 + root if 36 + root <= 47 else 24 + root
                r = rng.random()
                if r < oct_prob:
                    n += 12
                elif r < oct_prob + 0.08:
                    n += 7
                vel = 104 if st % 4 == 2 else 88
                out.append((t, int(n), vel, step * gate))
    return out
