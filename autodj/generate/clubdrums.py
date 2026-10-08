"""P99: КЛУБНЫЕ УДАРНЫЕ (прогрессив/хаус) — плотно, по секциям, на живых сэмплах.

Запрос Стаса 2026-10-08: «клубный энергичный прогрессив-хаус с хорошими плотными
ударными». Старый путь: винтажные драм-машины + round-robin по РАЗНЫМ сэмплам банка
(«баскетбольный мяч»: бочка AkaiLinn 0.12 с / 1.8 кГц, каждая бочка — другой звук).

Здесь:
  * кит трека: ОДИН сэмпл на каждый звук (бочка выбирается по низу и короткому хвосту);
  * свои удары по сетке: бочка 4/4, клэп+снейр на 2 и 4, хэты 16-ми с акцентами,
    открытый хэт на офбит, райд в дропах, крэш на старте фраз, снейр-ролл с крещендо
    перед дропом, бочка молчит в брейкдауне;
  * поверх — профессиональные лупы MusicRadar House со срезанным низом («топы»):
    плотность и движение, которые сеткой не нарисовать;
  * всё выбирается на трек по seed (кит, лупы, срез, райд/шейкер, фактура хэтов).
Сэмплы: ~/samples/musicradar (royalty-free MusicRadar SampleRadar) + tidal-drum-machines.
"""
from __future__ import annotations

import glob
import os
import random

import numpy as np

MR = os.path.expanduser(os.environ.get("MUSICRADAR_DIR", "~/samples/musicradar"))
TIDAL = os.path.expanduser("~/samples/tidal-drum-machines/machines")
KITS = f"{MR}/drums/musicradar-drum-samples/Drum Kits"
LOOPS = f"{MR}/house/musicradar-house-samples"


def available() -> bool:
    return os.path.isdir(KITS) and os.path.isdir(LOOPS)


# ─── загрузка ───────────────────────────────────────────────────────────────

_CACHE: dict = {}


def load(path: str, sr: int = 44100) -> np.ndarray:
    """wav → стерео float32 (n, 2) с нужной частотой. Кэш на процесс."""
    key = (path, sr)
    if key not in _CACHE:
        import soundfile as sf
        a, s = sf.read(path, dtype="float32", always_2d=True)
        if a.shape[1] == 1:
            a = np.repeat(a, 2, axis=1)
        a = a[:, :2]
        if s != sr:
            a = resample(a, sr / s)
        _CACHE[key] = a
    return _CACHE[key]


def resample(a: np.ndarray, factor: float) -> np.ndarray:
    """Растянуть по времени в factor раз (линейная интерполяция). Чистая."""
    n = max(1, int(round(len(a) * factor)))
    x = np.linspace(0, len(a) - 1, n)
    return np.stack([np.interp(x, np.arange(len(a)), a[:, c]) for c in range(a.shape[1])],
                    axis=1).astype(np.float32)


def kick_score(a: np.ndarray, sr: int = 44100) -> float:
    """Клубная бочка: много низа (<150 Гц), короткий хвост, без звона. Больше = лучше."""
    m = a.mean(axis=1)
    if len(m) < sr // 50:
        return -1.0
    X = np.abs(np.fft.rfft(m[: int(0.25 * sr)]))
    f = np.fft.rfftfreq(min(len(m), int(0.25 * sr)), 1 / sr)
    low = X[f < 150].sum() / (X.sum() + 1e-9)
    env = np.abs(m)
    tail = float(env[int(0.35 * sr):].mean()) / (float(env[: int(0.05 * sr)].mean()) + 1e-9) \
        if len(env) > int(0.35 * sr) else 0.0
    Xl = np.abs(np.fft.rfft(m[: int(0.2 * sr)], 32768))
    fl = np.fft.rfftfreq(32768, 1 / sr)
    band = (fl > 25) & (fl < 300)
    f0 = float(fl[band][np.argmax(Xl[band])])
    punch = 0.15 if 52 <= f0 <= 85 else 0.0                 # удар, а не гул/щелчок
    long_pen = 0.3 * max(0.0, len(m) / sr - 0.7)            # длинный хвост мажет бас
    return float(low - 0.5 * tail + punch - long_pen)


# ─── кит трека ──────────────────────────────────────────────────────────────

def _g(pattern: str) -> list[str]:
    return sorted(glob.glob(pattern))


def pick_kit(rng: random.Random, sr: int = 44100) -> dict:
    """Один сэмпл на звук. Возвращает {роль: путь}. Детерминирован при rng."""
    electro = [d for d in _g(f"{KITS}/*") if "Electro" in d or "Kurzweil" in d]
    kicks = [p for d in electro for p in _g(f"{d}/*Kick*.wav")]
    kicks += _g(f"{TIDAL}/RolandTR909/rolandtr909-bd/*.wav")[:6]
    kicks += _g(f"{TIDAL}/RolandTR808/rolandtr808-bd/*.wav")[:4]
    scored = sorted(kicks, key=lambda p: kick_score(load(p, sr), sr), reverse=True)
    top = scored[: max(3, len(scored) // 4)]
    kit_dir = rng.choice(electro)
    pick = lambda pats, fb: rng.choice([p for pat in pats for p in _g(pat)] or fb)
    tidal = lambda m, k: _g(f"{TIDAL}/{m}/{m.lower()}-{k}/*.wav")
    return {
        "kick": rng.choice(top),
        "kick_layer": rng.choice(tidal("RolandTR909", "bd")[:4]) if rng.random() < 0.5 else None,
        "clap": pick([f"{kit_dir}/*Clap*.wav", f"{KITS}/*Electro*/*Clap*.wav"],
                     tidal("RolandTR909", "cp")),
        "snare": pick([f"{kit_dir}/*Snr*.wav"], tidal("RolandTR909", "sd")),
        "hat": pick([f"{kit_dir}/*ClHat*.wav", f"{kit_dir}/*-Hat*.wav"], tidal("RolandTR909", "hh")),
        "open": pick([f"{kit_dir}/*OpHat*.wav"], tidal("RolandTR909", "oh")),
        "ride": rng.choice(tidal("RolandTR909", "rd") or tidal("RolandTR909", "hh")),
        "crash": pick([f"{MR}/drums/musicradar-drum-samples/Assorted Hits/Cymbals/*Crash-0*.wav",
                       f"{KITS}/Kurzweil*/*Crash*.wav"], tidal("RolandTR909", "cr")),
        "perc": rng.choice(tidal("RolandTR909", "rim") + tidal("RolandTR808", "cb")
                           + tidal("RolandTR808", "lc") or tidal("RolandTR909", "hh")),
        "shaker": rng.choice(tidal("LinnDrum", "sh") + tidal("RolandTR808", "ma")
                             or tidal("RolandTR909", "hh")),
        "kit": os.path.basename(kit_dir),
    }


def pick_loops(rng: random.Random) -> dict:
    """Топ-лупы трека: основной, вариация для второго дропа, ролл для подводок."""
    kits = _g(f"{LOOPS}/LoopKit *")
    k1, k2 = rng.choice(kits), rng.choice(kits)
    beats = lambda k: [p for p in _g(f"{k}/Beats/*Beat*.wav")       # без LPF-версий:
                       if "LPF" not in os.path.basename(p) and "Roll" not in p]  # после среза низа пусто
    fx = lambda k: _g(f"{k}/Beats/*BeatFx*.wav") or beats(k)
    rolls = _g(f"{LOOPS}/*/Beats/*RollSnare*.wav")
    bpm_of = lambda p: 127.0 if "127" in os.path.basename(os.path.dirname(os.path.dirname(p))) else 128.0
    a, b = rng.choice(beats(k1)), rng.choice(beats(k2))   # P100: без Fx-лупов (свипы/шум)
    return {"top_a": a, "top_b": b, "roll": rng.choice(rolls) if rolls else None,
            "bpm_a": bpm_of(a), "bpm_b": bpm_of(b), "hpf_hz": rng.randint(280, 650)}


# ─── сетка ──────────────────────────────────────────────────────────────────

def _place(buf, smp, t, sr, gain, pan=0.0):
    i = int(round(t * sr))
    if i >= len(buf) or i < 0:
        return
    n = min(len(smp), len(buf) - i)
    l = np.sqrt((1 - pan) / 2) * np.sqrt(2)
    r = np.sqrt((1 + pan) / 2) * np.sqrt(2)
    buf[i:i + n, 0] += smp[:n, 0] * gain * l
    buf[i:i + n, 1] += smp[:n, 1] * gain * r


def _vel(v: float) -> float:
    return (max(1.0, min(127.0, v)) / 127.0) ** 1.3


def _hpf(a: np.ndarray, sr: int, hz: float) -> np.ndarray:
    from scipy.signal import butter, sosfilt
    sos = butter(4, hz / (sr / 2), btype="high", output="sos")
    return sosfilt(sos, a, axis=0).astype(np.float32)


def sample_groove(rng: random.Random) -> dict:
    """Фактура ударных трека (без однотипности)."""
    return {
        "hat16": rng.random() < 0.7,           # 16-е хэты в дропе (иначе 8-е)
        "ride": rng.random() < 0.55,
        "open_offbeat": rng.random() < 0.85,
        "clap_flam_ms": rng.uniform(4, 14),
        "snare_layer": rng.uniform(0.25, 0.6),
        "top_gain": rng.uniform(0.45, 0.7),
        "roll_bars": rng.choice([1, 2, 2, 4]),
        "kick_gap_before_drop": rng.random() < 0.6,
        "hat_push_ms": rng.uniform(-4, 0),
        "perc": rng.random() < 0.5,            # P100: перкуссия (рим/конги/шейкер)
        "perc_pattern": rng.choice([[3, 7, 10, 14], [3, 6, 11, 14], [2, 7, 10, 15], [3, 10, 13]]),
        "shaker16": rng.random() < 0.6,
    }


def bar_events(kind: str, bar_in: int, sec_len: int, gr: dict, rng: random.Random,
               next_kind: str | None) -> list[tuple[float, str, float]]:
    """События одного такта: [(шаг 16-й, звук, velocity)]. Чистая при rng."""
    ev = []
    last_bars = sec_len - bar_in
    pre_drop = next_kind == "drop" and kind in ("build", "breakdown", "intro")
    rolling = pre_drop and last_bars <= gr["roll_bars"]
    kick_on = kind in ("intro", "build", "drop", "outro")
    if kind == "outro" and last_bars <= 4:
        kick_on = True
    if pre_drop and gr["kick_gap_before_drop"] and last_bars == 1:
        kick_on = False                                     # вдох перед дропом
    if kick_on:
        for s in (0, 4, 8, 12):
            ev.append((s, "kick", 118 if s == 0 else 110))
    if kind in ("build", "drop") or (kind == "outro" and last_bars > 4):
        for s in (4, 12):
            ev.append((s, "clap", 108))
            ev.append((s, "snare", 100))
    hats = kind in ("build", "drop", "outro") or (kind == "intro" and bar_in >= sec_len // 2)
    if hats:
        steps = range(16) if (kind == "drop" and gr["hat16"]) or kind == "build" else range(2, 16, 4)
        for s in steps:
            acc = 92 if s % 4 == 2 else (70 if s % 2 == 0 else 52)
            ev.append((s, "hat", acc + rng.uniform(-6, 6)))
    if kind == "drop" and gr["open_offbeat"]:
        for s in (2, 6, 10, 14):
            ev.append((s, "open", 84 + rng.uniform(-5, 5)))
    if kind == "drop" and gr["ride"]:
        for s in (0, 4, 8, 12):
            ev.append((s, "ride", 70 + rng.uniform(-6, 6)))
    if bar_in == 0 and kind in ("drop", "breakdown") or (kind == "drop" and bar_in % 16 == 0):
        ev.append((0, "crash", 105))
    if rolling:                                             # снейр-ролл с крещендо
        div = {1: 1, 2: 2}.get(last_bars, 4)               # четверти → восьмые → 16-е
        k = gr["roll_bars"] - last_bars + 1                 # 1..roll_bars
        base = 60 + 50 * k / gr["roll_bars"]
        for s in range(0, 16, div):
            ev.append((s, "snare", base * (0.75 + 0.25 * s / 15)))
    if gr.get("perc") and kind in ("build", "drop"):        # P100: перкуссия тек-хауса
        for st in gr["perc_pattern"]:
            ev.append((st, "perc", 88 + rng.uniform(-10, 8)))
        if gr.get("shaker16") and kind == "drop":
            for st in range(16):
                ev.append((st, "shaker", (70 if st % 2 else 50) + rng.uniform(-6, 6)))
    if kind == "drop" and bar_in % 8 == 7 and not rolling:  # мини-сбивка в конце фразы
        ev += [(13, "snare", 70), (14, "snare", 82), (15, "snare", 95)]
    return ev


# ─── рендер ─────────────────────────────────────────────────────────────────

def render(plan, bpm: float, dur: float, sr: int, rng: random.Random,
           swing: float = 0.0, log=print, overrides: dict | None = None) -> np.ndarray:
    """План секций → стерео буфер ударных (n, 2)."""
    total = int(dur * sr)
    bar = 240.0 / bpm
    step = bar / 16
    kit = pick_kit(rng, sr)
    loops = pick_loops(rng)
    gr = sample_groove(rng)
    gr.update(overrides or {})                              # стиль может зафиксировать фактуру
    log(f"    клубные ударные: кит {kit['kit']}, бочка {os.path.basename(kit['kick'])}"
        f"{' +909' if kit['kick_layer'] else ''}, топы {os.path.basename(loops['top_a'])} / "
        f"{os.path.basename(loops['top_b'])}, срез {loops['hpf_hz']} Гц, "
        f"хэты {'16-е' if gr['hat16'] else '8-е'}, райд {'да' if gr['ride'] else 'нет'}")
    S = {k: load(v, sr) for k, v in kit.items() if v and k != "kit"}
    hits = np.zeros((total + sr, 2), np.float32)
    pans = {"perc": -0.35, "shaker": 0.4, "hat": 0.25, "open": -0.2, "ride": 0.35, "crash": -0.15, "snare": 0.05, "clap": -0.05}
    gains = {"kick": 1.0, "kick_layer": 0.45, "clap": 0.62, "snare": 0.62 * gr["snare_layer"],
             "hat": 0.30, "open": 0.26, "ride": 0.20, "crash": 0.32,
             "perc": 0.34, "shaker": 0.16}
    kinds = [k for _, _, k in plan]
    for si, (a, b, kind) in enumerate(plan):
        nxt = kinds[si + 1] if si + 1 < len(kinds) else None
        for bi, br in enumerate(range(a, b)):
            for st, snd, v in bar_events(kind, bi, b - a, gr, rng, nxt):
                t = br * bar + st * step
                if st % 2 == 1:
                    t += swing * step
                if snd in ("hat", "open", "ride", "shaker"):
                    t += gr["hat_push_ms"] / 1000 + rng.uniform(-0.002, 0.002)
                elif snd == "clap":
                    t += gr["clap_flam_ms"] / 1000
                elif snd == "snare" and v < 100:
                    t += rng.uniform(0.0, 0.004)
                g = gains[snd] * _vel(v)
                _place(hits, S[snd], t, sr, g, pans.get(snd, 0.0))
                if snd == "kick" and "kick_layer" in S:
                    _place(hits, S["kick_layer"], t, sr, gains["kick_layer"] * _vel(v))
    # топы-лупы: со срезом низа, только где есть грув
    tops = np.zeros_like(hits)
    for key, bkey in (("top_a", "bpm_a"), ("top_b", "bpm_b")):
        lp = _hpf(resample(load(loops[key], sr), loops[bkey] / bpm), sr, loops["hpf_hz"])
        L = len(lp)
        bars_in_loop = max(1, int(round(L / sr / bar)))
        drops = [i for i, (_, _, k) in enumerate(plan) if k == "drop"]
        for si, (a, b, kind) in enumerate(plan):
            use_b = key == "top_b"
            second_half = drops and si >= drops[len(drops) // 2] if len(drops) > 1 else False
            if kind == "drop" and use_b != second_half:
                continue
            if kind != "drop" and use_b:
                continue
            lvl = {"intro": 0.35, "build": 0.7, "drop": 1.0, "outro": 0.55}.get(kind, 0.0)
            if lvl <= 0:
                continue
            for br in range(a, b, bars_in_loop):
                if kind == "intro" and br - a < (b - a) // 2:
                    continue
                _place(tops, lp, br * bar, sr, gr["top_gain"] * lvl)
    if loops["roll"]:
        roll = _hpf(resample(load(loops["roll"], sr), 127.0 / bpm), sr, 150)
        for si, (a, b, kind) in enumerate(plan):
            if si + 1 < len(plan) and plan[si + 1][2] == "drop" and kind != "drop":
                _place(tops, roll, (b - 2) * bar, sr, 0.35)
    out = hits + tops
    out = np.tanh(out * 1.4) / np.tanh(1.4)                 # склейка шины, плотность
    return out[:total].astype(np.float32)


def carve_bass(bass: np.ndarray, sr: int, hz: float = 40.0) -> np.ndarray:
    """Освободить место бочке: срез инфра-гула баса ниже hz (4-й порядок)."""
    from scipy.signal import butter, sosfilt
    sos = butter(4, hz / (sr / 2), btype="high", output="sos")
    return sosfilt(sos, bass, axis=0).astype(np.float32)
