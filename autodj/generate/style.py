#!/usr/bin/env python3
"""
style.py — P90: ПРОСТРАНСТВО СТИЛЕЙ вместо фиксированного списка жанров.

Проблема, которую это снимает (вопрос Стаса): `GENRES` — жёсткий словарь из 15 записей
в коде. Жанров бесконечно много, они смешиваются, каждый трек должен быть своим, а
добавление стиля требовало правки Python-файла. Плюс из-за ручных конфигов 78 из 90
слоёв остались на GM-пресетах («пиликалки»): каждый жанр правился руками и про них
забыли.

Модель: стиль — не запись в реестре, а ТОЧКА (точнее, ОБЛАСТЬ) в пространстве
параметров. Отсюда бесплатно получаем:
  • новый стиль — JSON-файл или dict от агента, БЕЗ правки кода;
  • смешение жанров — `blend(a, b, t)` (afro × dnb = валидный стиль);
  • уникальность каждого трека — параметры СЭМПЛИРУЮТСЯ из диапазонов, а не берутся
    фиксированными;
  • тембры назначаются ПОЛИТИКОЙ по характеру и роли (`character`), поэтому любой
    новый стиль сразу получает синт-голоса, а не GM-пресеты из чужого шаблона.

Формат (JSON-сериализуемый) — см. StyleSpec. Загрузка: styles/<имя>.json.
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import asdict, dataclass, field

STYLES_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "styles")

# Характер стиля → политика тембров по РОЛЯМ. Электронные роли идут на свой синт
# (P84/P85), акустические — на сэмплированные GM-инструменты, где это уместно.
TIMBRE_POLICY = {
    "electronic": {
        "lead": "synth:supersaw", "bass": "synth:acid?drive=0.45",
        "pad": "synth:pad?spread=1&detune=6", "arp": "synth:pluck",
        "counter": "synth:pluck", "accent": "synth:pluck?cutoff=1600",
    },
    "hybrid": {
        "lead": "synth:supersaw?detune=10", "bass": "synth:sub",
        "pad": "synth:pad?spread=1&detune=5", "arp": "synth:pluck",
        "counter": "electric_piano", "accent": "vibraphone",
    },
    "organic": {
        "lead": "synth:pluck?cutoff=1400", "bass": "synth:sub",
        "pad": "synth:pad?spread=1&detune=7", "arp": "kalimba",
        "counter": "electric_piano", "accent": "vibraphone",
    },
    "acoustic": {
        "lead": "flute", "bass": "acoustic_bass", "pad": "slow_strings",
        "arp": "harp", "counter": "electric_piano", "accent": "celesta",
    },
}

DRUM_BANK_BY_CHARACTER = {
    "electronic": ("RolandTR909", "RolandTR808", "RolandTR707"),
    "hybrid": ("RolandTR808", "AkaiLinn", "AlesisSR16"),
    "organic": ("AkaiLinn", "AlesisSR16", "RolandCompurhythm8000"),
    "acoustic": ("AkaiLinn", "AlesisSR16"),
}


@dataclass
class StyleSpec:
    """Описание стиля как ОБЛАСТИ параметров (не одной точки)."""
    name: str
    character: str = "electronic"              # electronic | hybrid | organic | acoustic
    bpm_range: tuple = (120, 128)
    keys: tuple = ("Am", "Dm", "Fm", "Gm", "Cm")
    modes: tuple = ("minor", "dorian", "phrygian")
    progressions: tuple = ("dark_techno", "plagal", "modal_interchange")
    energy: float = 0.6                        # 0..1 — плотность/напор
    swing_range: tuple = (0.0, 0.12)
    drum_patterns: tuple = ("four_on_floor",)   # P91: список — выбор на трек
    chord_bars_options: tuple = (2, 4)          # P91: гармонический ритм
    drum_pattern: str = "four_on_floor"         # legacy (одиночный)
    dur_range: tuple = (240, 420)
    melodic_style: str = "default"
    role_overrides: dict = field(default_factory=dict)   # точечные замены тембров
    gain_bias: dict = field(default_factory=dict)        # смещения баланса ролей
    notes: str = ""                                       # человеческое описание

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "StyleSpec":
        """Из JSON/ответа агента. Неизвестные ключи игнорируются, диапазоны чинятся."""
        allowed = StyleSpec.__dataclass_fields__.keys()
        clean = {k: v for k, v in (d or {}).items() if k in allowed}
        clean.setdefault("name", "unnamed")
        for k in ("bpm_range", "swing_range", "dur_range"):
            v = clean.get(k)
            if isinstance(v, (list, tuple)) and len(v) == 2:
                clean[k] = (min(v), max(v))
        for k in ("keys", "modes", "progressions"):
            if isinstance(clean.get(k), list):
                clean[k] = tuple(clean[k])
        spec = StyleSpec(**clean)
        return validate(spec)


def validate(spec: StyleSpec) -> StyleSpec:
    """Музыкальные предохранители: агент может прислать что угодно. Чистая."""
    lo, hi = spec.bpm_range
    spec.bpm_range = (max(50, min(200, int(lo))), max(50, min(200, int(hi))))
    if spec.bpm_range[0] > spec.bpm_range[1]:
        spec.bpm_range = (spec.bpm_range[1], spec.bpm_range[0])
    s_lo, s_hi = spec.swing_range
    spec.swing_range = (max(0.0, min(0.3, s_lo)), max(0.0, min(0.3, s_hi)))
    d_lo, d_hi = spec.dur_range
    spec.dur_range = (max(30, int(d_lo)), max(60, int(d_hi)))
    spec.energy = max(0.0, min(1.0, float(spec.energy)))
    if spec.character not in TIMBRE_POLICY:
        spec.character = "electronic"
    if not spec.keys:
        spec.keys = ("Am",)
    if not spec.modes:
        spec.modes = ("minor",)
    if not spec.progressions:
        spec.progressions = ("plagal",)
    return spec


def blend(a: StyleSpec, b: StyleSpec, t: float = 0.5, name: str | None = None) -> StyleSpec:
    """СМЕШЕНИЕ жанров: afro × dnb. Числа интерполируются, наборы объединяются.
    Чистая. t=0 → a, t=1 → b."""
    t = max(0.0, min(1.0, t))

    def mix(x, y):
        return tuple(round(x[i] + (y[i] - x[i]) * t) for i in range(2))

    return validate(StyleSpec(
        name=name or f"{a.name}x{b.name}",
        character=b.character if t > 0.5 else a.character,
        bpm_range=mix(a.bpm_range, b.bpm_range),
        keys=tuple(dict.fromkeys(a.keys + b.keys)),
        modes=tuple(dict.fromkeys(a.modes + b.modes)),
        progressions=tuple(dict.fromkeys(a.progressions + b.progressions)),
        energy=a.energy + (b.energy - a.energy) * t,
        swing_range=(a.swing_range[0] + (b.swing_range[0] - a.swing_range[0]) * t,
                     a.swing_range[1] + (b.swing_range[1] - a.swing_range[1]) * t),
        drum_pattern=b.drum_pattern if t > 0.5 else a.drum_pattern,
        dur_range=mix(a.dur_range, b.dur_range),
        melodic_style=b.melodic_style if t > 0.5 else a.melodic_style,
        role_overrides={**a.role_overrides, **b.role_overrides},
        gain_bias={**a.gain_bias, **b.gain_bias},
        notes=f"blend {a.name}↔{b.name} t={t:.2f}",
    ))


def resolve_timbres(spec: StyleSpec) -> dict:
    """Роль → инструмент по ПОЛИТИКЕ характера + точечные замены стиля. Чистая.
    Любой новый стиль сразу получает синт-голоса, а не GM-пресеты по недосмотру."""
    base = dict(TIMBRE_POLICY.get(spec.character, TIMBRE_POLICY["electronic"]))
    base.update({k: v for k, v in (spec.role_overrides or {}).items() if v})
    return base


def sample_style(spec: StyleSpec, rng: random.Random | None = None) -> dict:
    """Стиль → КОНКРЕТНЫЕ параметры трека (каждый рендер свои). Чистая при rng.
    Возвращает словарь под поля GenreConfig — движок не меняется."""
    rng = rng or random.Random()
    timbres = resolve_timbres(spec)
    bpm = rng.randint(*spec.bpm_range)
    dur = rng.randint(*spec.dur_range)
    e = spec.energy
    gains = {
        "gain_drums": round(0.42 + 0.16 * e + spec.gain_bias.get("drums", 0.0), 3),
        "gain_bass": round(0.48 + 0.14 * e + spec.gain_bias.get("bass", 0.0), 3),
        "gain_lead": round(0.44 + 0.12 * e + spec.gain_bias.get("lead", 0.0), 3),
        "gain_pad": round(0.52 - 0.08 * e + spec.gain_bias.get("pad", 0.0), 3),
        "gain_arp": round(0.44 + 0.10 * e + spec.gain_bias.get("arp", 0.0), 3),
        "gain_accent": round(0.40 + 0.06 * e + spec.gain_bias.get("accent", 0.0), 3),
        "gain_counter": round(0.38 + 0.06 * e + spec.gain_bias.get("counter", 0.0), 3),
    }
    banks = DRUM_BANK_BY_CHARACTER.get(spec.character, ("RolandTR909",))
    return {
        "name": spec.name,
        "bpm": bpm,
        "key": rng.choice(spec.keys),
        "scale_mode": rng.choice(spec.modes),
        "progression": rng.choice(spec.progressions),
        "dur": dur,
        "swing": round(rng.uniform(*spec.swing_range), 3),
        "melodic_style": spec.melodic_style,
        "drum_pattern": rng.choice(spec.drum_patterns or (spec.drum_pattern,)),
        "chord_bars": rng.choice(spec.chord_bars_options or (2,)),
        "drum_bank": rng.choice(banks),
        "duck_db": round(-3.0 - 3.0 * e, 2),
        "inst_lead": timbres.get("lead"),
        "inst_bass": timbres.get("bass"),
        "inst_pad": timbres.get("pad"),
        "inst_arp": timbres.get("arp"),
        "inst_counter": timbres.get("counter"),
        "inst_accent": timbres.get("accent"),
        **gains,
    }


# ─── Хранение стилей: файлы, а не код ───────────────────────────────────────

def load_style(name_or_path: str) -> StyleSpec:
    """`styles/afro_dub.json` или имя стиля из styles/. Новый стиль = новый файл."""
    path = name_or_path
    if not os.path.exists(path):
        path = os.path.join(STYLES_DIR, f"{name_or_path}.json")
    with open(path, encoding="utf-8") as f:
        return StyleSpec.from_dict(json.load(f))


def save_style(spec: StyleSpec, path: str | None = None) -> str:
    os.makedirs(STYLES_DIR, exist_ok=True)
    path = path or os.path.join(STYLES_DIR, f"{spec.name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec.to_dict(), f, ensure_ascii=False, indent=2)
    return path


def list_styles() -> list[str]:
    if not os.path.isdir(STYLES_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(STYLES_DIR) if f.endswith(".json"))


def style_from_brief(brief: dict) -> StyleSpec:
    """Свободное описание от агента (LLM понял запрос «пыльный пустынный брейкбит
    с даб-аккордами») → валидный стиль. Никакого кода править не нужно."""
    return StyleSpec.from_dict(brief)
