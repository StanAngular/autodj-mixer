#!/usr/bin/env python3
"""
curation_config.py — модель конфигурации курации (сегменты + траектория).

ВАЖНО: это конфиг ПОИСКА треков (для curate_tracks.py), НЕ путать с mix_config.py,
который держит трек-лист уже скачанных файлов для микшера (smart_mixer.py).

Микс = упорядоченный список сегментов. Каждый сегмент — самостоятельный запрос
курации (стили / страны / BPM / discovery / сид-исполнители / count). Сверху —
траектория, описывающая, как сегменты собираются в путешествие (BPM-ramp,
гармонический проход, рост энергии).

Этот модуль ЧИСТЫЙ (без сети и тяжёлых зависимостей): нормализация, валидация и
мост из старого одиночного CLI в 1-сегментный конфиг (обратная совместимость).
Сама курация по сегментам — отдельный шаг (P6b).

Контракт конфига (JSON), который заполняет LLM из свободного ТЗ:

    {
      "title": "...",
      "years": [2025, 2026],
      "duration_minutes": [60, 80],
      "trajectory": {"bpm": "ramp", "key": "harmonic_walk", "energy": "rising"},
      "segments": [
        {"name": "intro", "styles": ["Ambient"], "similar_styles": true,
         "countries": ["RU","KZ"], "bpm_range": [70,90],
         "discovery": "underground", "seed_artists": [], "count": 3}
      ]
    }
"""
import json
import re

DISCOVERY_MODES = ("popular", "newest", "underground")
SPEED_MODES = ("thorough", "fast")
DEFAULT_SPEED = "thorough"
TRAJECTORY_BPM = ("ramp", "constant")
TRAJECTORY_KEY = ("harmonic_walk", "per_segment", "none")
TRAJECTORY_ENERGY = ("rising", "flat")

DEFAULT_TRAJECTORY = {"bpm": "constant", "key": "per_segment", "energy": "flat"}

_CAMELOT_RE = re.compile(r"^(?:[1-9]|1[0-2])[AB]$")


class CurationConfigError(ValueError):
    """Некорректный конфиг курации."""


def _as_str_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return [x.strip() for x in value if x.strip()]
    raise CurationConfigError(f"Поле '{field}' должно быть строкой или списком строк")


def _as_range(value, field: str) -> list[int]:
    """[] (любой) или [lo, hi] с lo <= hi."""
    if not value:
        return []
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(x, (int, float)) for x in value)):
        lo, hi = int(value[0]), int(value[1])
        return [min(lo, hi), max(lo, hi)]
    raise CurationConfigError(f"Поле '{field}' должно быть [min, max]")


def normalize_segment(seg: dict, index: int = 0) -> dict:
    """Нормализовать и провалидировать один сегмент. Возвращает чистый dict."""
    if not isinstance(seg, dict):
        raise CurationConfigError(f"Сегмент #{index} должен быть объектом")

    styles = _as_str_list(seg.get("styles"), "styles")
    seed_artists = _as_str_list(seg.get("seed_artists"), "seed_artists")
    if not styles and not seed_artists:
        raise CurationConfigError(
            f"Сегмент #{index}: нужен хотя бы один 'styles' или 'seed_artists'")

    count = seg.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise CurationConfigError(f"Сегмент #{index}: 'count' должен быть целым > 0")

    discovery = seg.get("discovery", "popular")
    if discovery not in DISCOVERY_MODES:
        raise CurationConfigError(
            f"Сегмент #{index}: 'discovery' должен быть из {DISCOVERY_MODES}")

    target_key = (seg.get("target_key") or "").strip()
    if target_key and not _CAMELOT_RE.match(target_key):
        raise CurationConfigError(
            f"Сегмент #{index}: 'target_key' '{target_key}' не в формате Camelot (напр. 8A)")

    return {
        "name":           (seg.get("name") or f"segment-{index + 1}").strip(),
        "styles":         styles,
        "similar_styles": bool(seg.get("similar_styles", False)),
        "countries":      _as_str_list(seg.get("countries"), "countries"),
        "bpm_range":      _as_range(seg.get("bpm_range"), "bpm_range"),
        "target_key":     target_key,
        "discovery":      discovery,
        "seed_artists":   seed_artists,
        "count":          count,
    }


def _normalize_trajectory(traj) -> dict:
    t = dict(DEFAULT_TRAJECTORY)
    if traj:
        if not isinstance(traj, dict):
            raise CurationConfigError("'trajectory' должен быть объектом")
        t.update({k: v for k, v in traj.items() if k in t})
    if t["bpm"] not in TRAJECTORY_BPM:
        raise CurationConfigError(f"trajectory.bpm должен быть из {TRAJECTORY_BPM}")
    if t["key"] not in TRAJECTORY_KEY:
        raise CurationConfigError(f"trajectory.key должен быть из {TRAJECTORY_KEY}")
    if t["energy"] not in TRAJECTORY_ENERGY:
        raise CurationConfigError(f"trajectory.energy должен быть из {TRAJECTORY_ENERGY}")
    return t


def load_config(data: dict) -> dict:
    """
    Нормализовать и провалидировать полный конфиг (уже распарсенный dict).
    Возвращает чистый конфиг с нормализованными сегментами. Бросает CurationConfigError.
    """
    if not isinstance(data, dict):
        raise CurationConfigError("Конфиг должен быть объектом JSON")

    segments_raw = data.get("segments")
    if not isinstance(segments_raw, list) or not segments_raw:
        raise CurationConfigError("Конфиг должен содержать непустой список 'segments'")

    years = data.get("years") or []
    if years and not all(isinstance(y, int) and not isinstance(y, bool) for y in years):
        raise CurationConfigError("'years' должен быть списком целых")

    speed = data.get("speed", DEFAULT_SPEED)
    if speed not in SPEED_MODES:
        raise CurationConfigError(f"'speed' должен быть из {SPEED_MODES}")

    return {
        "title":            (data.get("title") or "").strip(),
        "years":            list(years),
        "speed":            speed,
        "duration_minutes": _as_range(data.get("duration_minutes"), "duration_minutes"),
        "trajectory":       _normalize_trajectory(data.get("trajectory")),
        "segments":         [normalize_segment(s, i) for i, s in enumerate(segments_raw)],
    }


def load_config_file(path: str) -> dict:
    """Загрузить и нормализовать конфиг из JSON-файла."""
    with open(path, encoding="utf-8") as f:
        return load_config(json.load(f))


def config_from_cli(args) -> dict:
    """
    Построить 1-сегментный конфиг из аргументов старого CLI (обратная
    совместимость). Старый путь курации = частный случай одного сегмента.
    """
    if getattr(args, "bpm_min", 0) and getattr(args, "bpm_max", 0):
        bpm_range = [args.bpm_min, args.bpm_max]
    elif getattr(args, "bpm", 0):
        tol = getattr(args, "bpm_tolerance", 4)
        bpm_range = [args.bpm - tol, args.bpm + tol]
    else:
        bpm_range = []

    country = getattr(args, "country", "") or getattr(args, "region", "")
    years = ([int(y.strip()) for y in args.years.split(",")]
             if getattr(args, "years", "") else [])

    segment = {
        "name":       "main",
        "styles":     [args.genre],
        "countries":  [country] if country else [],
        "bpm_range":  bpm_range,
        "target_key": getattr(args, "camelot", ""),
        "discovery":  getattr(args, "discovery", "popular"),
        "count":      args.count,
    }
    return load_config({
        "title": args.genre,
        "years": years,
        "speed": "fast" if getattr(args, "fast", False) else DEFAULT_SPEED,
        "trajectory": {"bpm": "constant", "key": "per_segment", "energy": "flat"},
        "segments": [segment],
    })


def schema() -> dict:
    """
    Машиночитаемый контракт конфига курации (единый источник правды — enum'ы берутся
    из тех же констант модуля). Для агентов/интеграций: получить схему, сгенерировать
    валидный конфиг, не читая исходники. Пример внутри сам проходит load_config().
    """
    return {
        "description": "Конфиг курации: упорядоченный список сегментов + траектория. "
                       "НЕ путать с mix_config.py (трек-лист для микшера).",
        "fields": {
            "title":            {"type": "string", "required": False, "default": ""},
            "years":            {"type": "list[int]", "required": False, "default": []},
            "duration_minutes": {"type": "[min,max]", "required": False, "default": []},
            "speed":            {"type": "enum", "allowed": list(SPEED_MODES),
                                 "required": False, "default": DEFAULT_SPEED},
            "trajectory": {
                "bpm":    {"allowed": list(TRAJECTORY_BPM),    "default": DEFAULT_TRAJECTORY["bpm"]},
                "key":    {"allowed": list(TRAJECTORY_KEY),    "default": DEFAULT_TRAJECTORY["key"]},
                "energy": {"allowed": list(TRAJECTORY_ENERGY), "default": DEFAULT_TRAJECTORY["energy"]},
            },
            "segments": {
                "type": "list", "required": True, "note": "непустой список",
                "item": {
                    "name":           {"type": "string", "default": "segment-N"},
                    "styles":         {"type": "list[str]",
                                       "note": "обязателен styles ИЛИ seed_artists"},
                    "similar_styles": {"type": "bool", "default": False},
                    "countries":      {"type": "list[str ISO]", "default": [],
                                       "example": ["RU", "US"]},
                    "bpm_range":      {"type": "[min,max]", "default": []},
                    "target_key":     {"type": "string Camelot, напр. 8A", "default": ""},
                    "discovery":      {"allowed": list(DISCOVERY_MODES), "default": "popular"},
                    "seed_artists":   {"type": "list[str]", "default": []},
                    "count":          {"type": "int>0", "required": True},
                },
            },
        },
        "example": {
            "title": "Eurasia → America",
            "years": [2025, 2026],
            "duration_minutes": [60, 80],
            "speed": "thorough",
            "trajectory": {"bpm": "ramp", "key": "harmonic_walk", "energy": "rising"},
            "segments": [
                {"name": "intro", "styles": ["Ambient"], "similar_styles": True,
                 "countries": ["RU", "KZ"], "bpm_range": [70, 90],
                 "discovery": "underground", "count": 3},
                {"name": "peak", "styles": ["Hard Trance"], "countries": ["US"],
                 "bpm_range": [150, 170], "discovery": "newest", "count": 4},
            ],
        },
    }


def describe(config: dict) -> str:
    """Человекочитаемый план конфига (для печати на апруве плана)."""
    lines = [f"Микс: {config['title'] or '—'}"]
    if config["years"]:
        lines.append(f"Годы: {config['years']}")
    if config["duration_minutes"]:
        lo, hi = config["duration_minutes"]
        lines.append(f"Длительность: {lo}–{hi} мин")
    t = config["trajectory"]
    lines.append(f"Траектория: BPM={t['bpm']}, ключ={t['key']}, энергия={t['energy']}")
    lines.append(f"Режим: {config.get('speed', DEFAULT_SPEED)}")
    lines.append(f"Сегментов: {len(config['segments'])}")
    for s in config["segments"]:
        rng = f"{s['bpm_range'][0]}–{s['bpm_range'][1]}" if s["bpm_range"] else "любой"
        src = f", сид: {s['seed_artists']}" if s["seed_artists"] else ""
        lines.append(
            f"  • {s['name']}: {s['styles'] or '—'}"
            f"{' (+смежные)' if s['similar_styles'] else ''}"
            f" · {s['countries'] or 'любая страна'} · BPM {rng}"
            f" · {s['discovery']} · {s['count']} тр.{src}")
    return "\n".join(lines)
