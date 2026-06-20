#!/usr/bin/env python3
"""
curate_tracks.py — детерминированный поиск треков для autodj-mixer.
Без LLM. Каждый трек верифицирован через yt-dlp перед выдачей.
Авто-загрузка .env через python-dotenv.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional

import curation_config
import enrich_cache

# Auto-load .env если есть
try:
    from dotenv import load_dotenv
    dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
except ImportError:
    pass

import requests
from bs4 import BeautifulSoup

# ─── Константы ───────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 15
SCRAPE_DELAY = 1.5  # секунд между запросами (вежливый скрейпинг)
YTDLP_PROXY = "socks5://127.0.0.1:40000"  # Cloudflare Warp для YouTube
PROXY_HOST  = "127.0.0.1:40000"
PROXIES     = {
    "http":  f"socks5h://{PROXY_HOST}",
    "https": f"socks5h://{PROXY_HOST}",
}
DISCOGS_TOKEN = os.environ.get("DISCOGS_TOKEN", "")
GOOGLE_DELAY  = 3.0
TUNEBAT_MAX_POOL = 100  # макс размер пула для Playwright Tunebat обогащения
ENRICH_FACTOR = 4       # thorough: обогащаем через Tunebat count×ENRICH_FACTOR кандидатов
ENRICH_MIN = 12         # thorough: но не меньше этого (буфер на отсев при фильтре)
ENRICH_FACTOR_FAST = 2  # fast: вдвое меньше кандидатов на обогащение
ENRICH_MIN_FAST = 6     # fast: меньший пол
ENRICH_DEMAND_BUFFER = 3  # запас полных треков сверх count сегмента (на отсев/верификацию/дедуп)


def resolve_speed(config_speed: str, fast_flag: bool) -> str:
    """
    Финальный режим скорости: флаг --fast включает fast; без флага сохраняется
    speed из конфига (чтобы "speed":"fast" в JSON тоже работал). Однонаправленно —
    флаг только ускоряет, никогда не возвращает в thorough. Чистая функция.
    """
    return "fast" if fast_flag else config_speed


def enrich_gap(n_complete: int, seg_count: int,
               buffer: int = ENRICH_DEMAND_BUFFER) -> int:
    """
    Сколько неполных треков реально нужно обогатить = нехватка ПОЛНЫХ под сегмент
    (+буфер на отсев). 0, если полных уже достаточно. Чистая функция.
    Суть: если Beatport дал достаточно треков с BPM/Camelot, Tunebat не нужен.
    """
    if seg_count <= 0:
        return 0
    return max(0, seg_count + buffer - n_complete)


def enrich_budget(count: int, speed: str = "thorough") -> int:
    """Сколько кандидатов гнать через Tunebat на сегмент в зависимости от режима.
    thorough (по умолчанию) — щедро для хорошего отбора; fast — быстрее. Чистая функция."""
    if speed == "fast":
        return max(count * ENRICH_FACTOR_FAST, ENRICH_MIN_FAST)
    return max(count * ENRICH_FACTOR, ENRICH_MIN)

KEY_TO_CAMELOT = {
    "C maj": "8B",  "C min": "5A",
    "Db maj": "3B", "Db min": "12A",
    "D maj": "10B", "D min": "7A",
    "Eb maj": "5B", "Eb min": "2A",
    "E maj": "12B", "E min": "9A",
    "F maj": "7B",  "F min": "4A",
    "F# maj": "2B", "F# min": "11A",
    "G maj": "9B",  "G min": "6A",
    "Ab maj": "4B", "Ab min": "1A",
    "A maj": "11B", "A min": "8A",
    "Bb maj": "6B", "Bb min": "3A",
    "B maj": "1B",  "B min": "10A",
    # алиасы
    "C# maj": "3B", "C# min": "12A",
    "D# maj": "5B", "D# min": "2A",
    "G# maj": "4B", "G# min": "1A",
    "A# maj": "6B", "A# min": "3A",
}

BEATPORT_GENRE_SLUGS = {
    "melodic techno": "melodic-house-techno",
    "melodic house": "melodic-house-techno",
    "melodic house techno": "melodic-house-techno",
    "techno": "techno-peak-time-driving",
    "tech house": "tech-house",
    "deep house": "deep-house",
    "progressive house": "progressive-house",
    "afro house": "afro-house",
    "organic house": "organic-house-downtempo",
}

# Маппинг жанров → Discogs стили
DISCOGS_STYLE_MAP = {
    "house":                ["House", "Deep House", "Chicago House"],
    "deep house":           ["Deep House", "House", "Soulful House"],
    "tech house":           ["Tech House", "House", "Minimal"],
    "progressive house":    ["Progressive House", "House", "Trance"],
    "funky house":          ["Funky", "House", "Disco"],
    "afro house":           ["Afro House", "Afrobeat", "House"],
    "organic house":        ["Organic House", "Downtempo", "Deep House"],
    "soulful house":        ["Soulful House", "Deep House", "Gospel"],
    "vocal house":          ["Vocal", "House", "Soulful House"],
    "jackin house":         ["Jackin House", "House", "Funky"],
    "electro house":        ["Electro House", "House", "Electro"],
    "big room":             ["Big Room", "Progressive House", "EDM"],
    "future house":         ["Future House", "House", "Tropical House"],
    "tropical house":       ["Tropical House", "House", "Chill-out"],
    "bass house":           ["Bass House", "House", "UK Bass"],
    "slap house":           ["Slap House", "House", "Future House"],
    "techno":               ["Techno", "Industrial", "EBM"],
    "melodic techno":       ["Melodic Techno", "Techno", "Minimal Techno"],
    "melodic house":        ["Melodic House", "Deep House", "Melodic Techno"],
    "raw techno":           ["Techno", "Industrial", "Hard Techno"],
    "hard techno":          ["Hard Techno", "Techno", "Industrial"],
    "industrial techno":    ["Industrial", "Techno", "EBM"],
    "peak time techno":     ["Techno", "Hard Techno"],
    "minimal techno":       ["Minimal Techno", "Minimal", "Techno"],
    "detroit techno":       ["Detroit Techno", "Techno", "Electro"],
    "nu-disco":             ["Nu-Disco", "Disco", "Indie Dance"],
    "nu disco":             ["Nu-Disco", "Disco", "Indie Dance"],
    "french touch":         ["French House", "Nu-Disco", "Disco", "Funky"],
    "french groovy house":  ["French House", "Nu-Disco", "Funky", "Disco"],
    "french house":         ["French House", "House", "Nu-Disco"],
    "indie dance":          ["Indie Dance", "Nu-Disco", "Alternative Dance"],
    "disco":                ["Disco", "Nu-Disco", "Funk"],
    "italo disco":          ["Italo-Disco", "Disco", "Synth-pop"],
    "trance":               ["Trance", "Progressive Trance", "Uplifting Trance"],
    "progressive trance":   ["Progressive Trance", "Trance", "Progressive House"],
    "uplifting trance":     ["Uplifting Trance", "Trance", "Euphoric Trance"],
    "psytrance":            ["Psychedelic Trance", "Psy-Trance", "Goa Trance"],
    "hardtrance":           ["Hard Trance", "Trance", "Hardstyle"],
    "hard trance":          ["Hard Trance", "Trance", "Hardstyle"],
    "vocal trance":         ["Vocal", "Trance", "Uplifting Trance"],
    "tech trance":          ["Tech Trance", "Trance", "Techno"],
    "dark psy":             ["Dark Psytrance", "Psychedelic Trance"],
    "drum and bass":        ["Drum n Bass", "Jungle", "Neurofunk"],
    "dnb":                  ["Drum n Bass", "Jungle"],
    "liquid dnb":           ["Liquid Funk", "Drum n Bass", "Jazz-Funk"],
    "neurofunk":            ["Neurofunk", "Drum n Bass", "Industrial"],
    "jungle":               ["Jungle", "Drum n Bass", "Ragga Jungle"],
    "breakbeat":            ["Breakbeat", "Breaks", "Big Beat"],
    "ambient":              ["Ambient", "Drone", "New Age"],
    "downtempo":            ["Downtempo", "Trip Hop", "Chillout"],
    "chillout":             ["Chillout", "Downtempo", "Ambient"],
    "lo-fi":                ["Lo-Fi", "Downtempo", "Chillout"],
    "trip hop":             ["Trip Hop", "Downtempo", "Hip Hop"],
    "dark ambient":         ["Dark Ambient", "Ambient", "Industrial"],
    "electro":              ["Electro", "Electro House", "Detroit Techno"],
    "electroclash":         ["Electroclash", "Electro", "New Wave"],
    "synthwave":            ["Synthwave", "Electro", "Darksynth"],
    "darksynth":            ["Darksynth", "Synthwave", "Industrial"],
    "vaporwave":            ["Vaporwave", "Chillwave", "Synthwave"],
    "hardstyle":            ["Hardstyle", "Hardcore", "Rawstyle"],
    "hardcore":             ["Hardcore", "Hardstyle", "Industrial Hardcore"],
    "rawstyle":             ["Rawstyle", "Hardstyle"],
    "uk garage":            ["UK Garage", "Speed Garage", "Grime"],
    "garage":               ["UK Garage", "Speed Garage"],
    "grime":                ["Grime", "UK Garage", "Hip Hop"],
    "uk bass":              ["UK Bass", "Dubstep", "UK Garage"],
    "dubstep":              ["Dubstep", "Brostep", "Grime"],
    "future garage":        ["Future Garage", "UK Garage", "Ambient"],
    "funk":                 ["Funk", "Soul", "Disco"],
    "soul":                 ["Soul", "R&B", "Funk"],
    "hip hop":              ["Hip Hop", "Rap", "Boom Bap"],
    "afrobeat":             ["Afrobeat", "Funk", "Soul"],
    "minimal":              ["Minimal", "Minimal Techno", "Microhouse"],
    "experimental":         ["Experimental", "Noise", "Avant-garde"],
    "jazz":                 ["Jazz", "Nu Jazz", "Jazz-Funk"],
    "classical":            ["Classical", "Contemporary Classical"],
}

DURATION_MIN = 180   # 3 мин — отсекает тизеры
DURATION_MAX = 660   # 11 мин — отсекает DJ-сеты и час-миксы

# Платформы для пошуку (в порядку пріоритету)
SEARCH_PLATFORMS = [
    {"prefix": "ytsearch", "name": "YouTube"},
    {"prefix": "scsearch", "name": "SoundCloud"},
]


# ─── Провенанс источников (P1) ───────────────────────────────────────────────
# Каждое обогащаемое поле (bpm/camelot/country) несёт спутник {field}_src с
# именем источника. set_field уважает приоритет: данные из более авторитетного
# источника могут перезаписать менее авторитетные, но не наоборот. Это позволяет
# таблице апрува (P3) и итоговому JSON честно показывать «откуда инфа».

SOURCE_PRIORITY = {
    "user":           100,   # ручная правка — высший приоритет
    "Beatport":        50,
    "Tunebat":         50,
    "MusicBrainz":     40,
    "Discogs":         40,
    "1001Tracklists":  30,
    "Bandcamp":        30,
    "YouTube-desc":    20,
    "":                 0,   # нет источника
}

# Поля, для которых ведётся провенанс {field} + {field}_src
PROV_FIELDS = ("bpm", "camelot", "country")


def _src_priority(src: str) -> int:
    """Приоритет источника; неизвестный источник получает средний вес 10."""
    return SOURCE_PRIORITY.get(src, 10)


def _is_empty(value) -> bool:
    """0 / '' / None трактуются как «нет значения»."""
    return value is None or value == "" or value == 0


def set_field(track: dict, field: str, value, src: str) -> None:
    """
    Записать track[field]=value и track[field+'_src']=src с учётом приоритета.
    Пустые значения (0/''/None) игнорируются. Перезапись только если новый
    источник строго авторитетнее текущего (при равенстве — побеждает первый).
    """
    if _is_empty(value):
        return
    cur     = track.get(field)
    cur_src = track.get(f"{field}_src", "")
    if _is_empty(cur) or _src_priority(src) > _src_priority(cur_src):
        track[field] = value
        track[f"{field}_src"] = src


def tag_src(tracks: list[dict], src: str) -> list[dict]:
    """
    Проштамповать провенанс для полей, которые уже заполнил фетчер источника, и
    записать источник в found_in («каждый источник, где трек обнаружен»).
    Возвращает тот же список — удобно для цепочек: raw_pool += tag_src(fetch(), "X").
    """
    for t in tracks:
        fi = t.setdefault("found_in", [])
        if src not in fi:
            fi.append(src)
        for f in PROV_FIELDS:
            if not _is_empty(t.get(f)) and not t.get(f"{f}_src"):
                t[f"{f}_src"] = src
    return tracks


def dedup_key(artist: str, track: str) -> str:
    """Ключ дедупликации. P1: сырой lower-case (P2 заменит на normalize_text)."""
    return f"{artist.lower().strip()}|{track.lower().strip()}"


def merge_provenance(kept: dict, dup: dict) -> None:
    """
    Слить дубликат в оставшийся трек: объединить found_in и дозаполнить
    провенанс-поля (с уважением приоритета источников).
    """
    for s in dup.get("found_in", []):
        if s not in kept.setdefault("found_in", []):
            kept["found_in"].append(s)
    for f in PROV_FIELDS:
        if not _is_empty(dup.get(f)):
            set_field(kept, f, dup[f], dup.get(f"{f}_src", ""))


# ─── Форматирование таблицы апрува (P3) ──────────────────────────────────────

def fmt_duration(sec: int) -> str:
    """Секунды → 'M:SS', или '?' если неизвестно."""
    if not sec:
        return "?"
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_views(n: int) -> str:
    """Просмотры → компактно (1.2M / 12K / 850), или '—' если неизвестно."""
    if not n:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_field(track: dict, field: str, suffix: str = "") -> str:
    """'value+suffix (src)' или '?' если поле пустое."""
    val = track.get(field)
    if _is_empty(val):
        return "?"
    src = track.get(f"{field}_src", "")
    s = f"{val}{suffix}"
    return f"{s} ({src})" if src else s


def extract_video_id(url: str) -> str:
    """
    Извлечь 11-символьный YouTube video_id из URL или строки.
    Возвращает '' если это не YouTube (например SoundCloud) или ID не найден.
    """
    if not url:
        return ""
    if "soundcloud.com" in url:
        return ""
    m = re.search(r'[?&]v=([0-9A-Za-z_-]{11})', url)
    if m:
        return m.group(1)
    m = re.search(r'(?:youtu\.be/|/embed/|/shorts/|/v/)([0-9A-Za-z_-]{11})', url)
    if m:
        return m.group(1)
    if re.fullmatch(r'[0-9A-Za-z_-]{11}', url.strip()):
        return url.strip()
    return ""


def build_youtube_playlist_url(tracks: list[dict], limit: int = 50) -> str:
    """
    Собрать ссылку на временный YouTube-плейлист из video_id треков.
    YouTube создаёт временный (несохраняемый) плейлист по такому URL.
    Лимит ~50 видео. SoundCloud и треки без YouTube-ссылки пропускаются.
    Возвращает '' если ни одного YouTube-ID не найдено. Чистая функция.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for t in tracks:
        vid = extract_video_id(t.get("youtube_url", ""))
        if vid and vid not in seen:
            seen.add(vid)
            ids.append(vid)
        if len(ids) >= limit:
            break
    if not ids:
        return ""
    return "https://www.youtube.com/watch_videos?video_ids=" + ",".join(ids)


def format_approval_table(tracks: list[dict], target_camelot: str = "") -> str:
    """
    Читаемая таблица для апрува. Чистая функция (без сети) — тестируема.
    На каждый трек: №, артист — трек, длительность, стиль, BPM(src),
    Key(src)▸отношение, страна(src), просмотры, ссылка, статус.
    Группирует по полю 'segment', если оно присутствует (готовность к P6).
    """
    lines: list[str] = []

    segments: dict[str, list[tuple[int, dict]]] = {}
    for i, t in enumerate(tracks, 1):
        segments.setdefault(t.get("segment", ""), []).append((i, t))

    rel_short = {
        "exact match": "=", "wheel neighbour": "▸±1",
        "major/minor swap": "▸maj/min", "diagonal energy boost": "▸energy",
        "clash": "▸⚠скачок",
    }

    for seg, items in segments.items():
        if seg:
            lines.append(f"\nСЕГМЕНТ: {seg}")
        for i, t in items:
            key_str = fmt_field(t, "camelot")
            cam = t.get("camelot")
            if cam and target_camelot:
                try:
                    key_str += rel_short.get(camelot_relation(target_camelot, cam), "")
                except Exception:
                    pass

            status = t.get("youtube_status", "")
            lines.append(f"{i:3}. {t['artist']} — {t['track']}")
            lines.append(
                f"      {fmt_duration(t.get('duration_sec', 0))} · "
                f"{t.get('style') or '?'} · "
                f"{fmt_field(t, 'bpm', ' BPM')} · {key_str} · "
                f"{fmt_field(t, 'country')} · ▶{fmt_views(t.get('youtube_views', 0))}"
                + (f" · {status}" if status else "")
            )
            if t.get("youtube_url"):
                lines.append(f"      {t['youtube_url']}")

    total_sec = sum(t.get("duration_sec", 0) for t in tracks)
    bpms = [t["bpm"] for t in tracks if t.get("bpm")]
    keys = sorted({t["camelot"] for t in tracks if t.get("camelot")})
    summary = f"\nΣ {len(tracks)} треков"
    if total_sec:
        summary += f" · ~{total_sec // 60} мин"
    if bpms:
        summary += f" · BPM {min(bpms)}–{max(bpms)}"
    if keys:
        summary += f" · ключи: {', '.join(keys)}"
    lines.append(summary)

    playlist = build_youtube_playlist_url(tracks)
    if playlist:
        n = playlist.count(",") + 1
        lines.append(f"\n▶ Превью-плейлист ({n} видео, временный): {playlist}")

    return "\n".join(lines)


# ─── Режимы discovery: ранжирование пула (B4) ────────────────────────────────

def _meta_known(t: dict) -> int:
    """1 если у трека известны и BPM, и Camelot — такие всегда ранжируются выше."""
    return 1 if (t.get("bpm") and t.get("camelot")) else 0


def discovery_rank(tracks: list[dict], mode: str = "popular") -> list[dict]:
    """
    Отсортировать пул под режим запроса. Чистая функция (тестируема офлайн).
      popular     — популярное/чартовое сверху (support_score, затем просмотры)
      newest      — свежие релизы сверху (year), затем популярность
      underground — наименее популярное / Bandcamp сверху (низкий support/просмотры)
    Во всех режимах треки с полными метаданными (BPM+Camelot) идут выше прочих.
    """
    def is_bandcamp(t):
        return 1 if "Bandcamp" in (t.get("found_in") or []) else 0

    if mode == "newest":
        key = lambda t: (_meta_known(t), t.get("year", 0), t.get("support_score", 0))
    elif mode == "underground":
        key = lambda t: (_meta_known(t), is_bandcamp(t),
                         -t.get("support_score", 0), -t.get("youtube_views", 0))
    else:  # popular (по умолчанию)
        key = lambda t: (_meta_known(t), t.get("support_score", 0),
                         t.get("youtube_views", 0))

    return sorted(tracks, key=key, reverse=True)


# ─── Сборка/траектория (P6c) ─────────────────────────────────────────────────

def _harmonic_order(tracks: list[dict]) -> list[dict]:
    """
    Жадный гармонический проход: каждый следующий трек МИНИМАЛЬНО далёк по Camelot
    от предыдущего (camelot_distance: 0 exact → 1 сосед/relative → 2 диагональ →
    ≥3 клэш). Так далёкие скачки (8A→3B) выбираются только когда ближе нет ничего.
    Треки без Camelot — в конец в исходном порядке. Чистая, детерминированная.
    """
    with_key = [t for t in tracks if t.get("camelot")]
    no_key   = [t for t in tracks if not t.get("camelot")]
    if not with_key:
        return list(tracks)

    remaining = with_key[:]
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1]["camelot"]
        # стабильная сортировка по возрастанию расстояния: при равенстве — исходный порядок
        remaining.sort(key=lambda t: camelot_distance(last, t["camelot"]))
        ordered.append(remaining.pop(0))
    return ordered + no_key


def assemble_mix(tracks: list[dict], trajectory: dict) -> list[dict]:
    """
    Упорядочить треки по траектории, СОХРАНЯЯ порядок сегментов (intro→…→peak).
    Внутри сегмента:
      key='harmonic_walk' → гармонический проход по Camelot;
      иначе bpm='ramp'    → сортировка по возрастанию BPM;
      иначе               → как есть (discovery-ранжирование).
    Чистая функция.
    """
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for t in tracks:
        seg = t.get("segment", "")
        if seg not in groups:
            groups[seg] = []
            order.append(seg)
        groups[seg].append(t)

    bpm_mode = trajectory.get("bpm", "constant")
    key_mode = trajectory.get("key", "per_segment")

    out: list[dict] = []
    for seg in order:
        g = groups[seg]
        if key_mode == "harmonic_walk":
            g = _harmonic_order(g)
        elif bpm_mode == "ramp":
            g = sorted(g, key=lambda t: (t.get("bpm") or 99999))
        out.extend(g)
    return out


def trajectory_summary(tracks: list[dict]) -> str:
    """Человекочитаемая кривая: BPM по сегментам + проход по ключам."""
    segs: list[tuple[str, list[dict]]] = []
    cur = object()
    for t in tracks:
        s = t.get("segment", "")
        if not segs or s != cur:
            segs.append((s, []))
            cur = s
        segs[-1][1].append(t)

    bpm_parts = []
    for _, ts in segs:
        bpms = [t["bpm"] for t in ts if t.get("bpm")]
        if bpms:
            bpm_parts.append(f"{bpms[0]}▸{bpms[-1]}" if len(bpms) > 1 else str(bpms[0]))

    keys = [t["camelot"] for t in tracks if t.get("camelot")]
    line = ""
    if bpm_parts:
        line = "Кривая BPM: " + " ┊ ".join(bpm_parts)
    if keys:
        shown = "▸".join(keys[:12]) + ("…" if len(keys) > 12 else "")
        line += ("  |  " if line else "") + f"ключи: {shown}"
    return line


def harmonic_chain_trace(tracks: list[dict]) -> str:
    """
    Компактный трейс гармонической цепочки: Camelot-отношение между соседними
    треками + счёт плавных/скачков + BPM. Чистая функция — видно, как собран
    микс по ключам и где большие скачки Camelot (POOR-переходы).
    """
    if not tracks:
        return ""
    smooth_rel = {"exact match": "=", "wheel neighbour": "±1", "major/minor swap": "maj↔min"}
    lines = ["Гармоническая цепочка (как собрано по Camelot/BPM):"]
    smooth = energy = jumps = 0
    prev = ""
    for i, t in enumerate(tracks, 1):
        cam = t.get("camelot") or "?"
        bpm = t.get("bpm") or "?"
        mark = ""
        if prev and cam != "?" and prev != "?":
            try:
                rel = camelot_relation(prev, cam)
            except Exception:
                rel = ""
            if rel in smooth_rel:
                mark = f"   {prev}→{cam} {smooth_rel[rel]}"
                smooth += 1
            elif rel == "diagonal energy boost":
                mark = f"   {prev}→{cam} ↑energy"     # агрессивно — микшер часто рейтит POOR
                energy += 1
            else:
                mark = f"   {prev}→{cam} ⚠скачок"
                jumps += 1
        name = (t.get("track") or t.get("artist") or "?")[:26]
        lines.append(f"  {i:2}. {str(cam):>3} {str(bpm):>3}bpm  {name}{mark}")
        prev = cam
    total = smooth + energy + jumps
    if total:
        lines.append(f"  → плавных {smooth}/{total} · энергетич. {energy}/{total} · скачков {jumps}/{total}")
    return "\n".join(lines)


# ─── Умный селектор: count лучших на сегмент (якоря + гармония) ───────────────

def select_segment_tracks(candidates: list[dict], count: int,
                          speed: str = "thorough") -> list[dict]:
    """
    Выбрать count лучших треков сегмента. Чистая, детерминированная функция.
      fast     — просто топ-count по текущему ранжированию (discovery).
      thorough — топ-якоря по популярности (≈половина слотов) + остальное
                 добираем по гармонической совместимости с уже выбранными.
    Прозрачно и без глобального оптимизатора: якоря фиксированы, добор жадный.
    """
    if count <= 0:
        return []
    if len(candidates) <= count:
        return list(candidates)
    if speed == "fast":
        return candidates[:count]

    n_anchor = max(1, (count + 1) // 2)        # ceil(count/2) под якоря
    selected = candidates[:n_anchor]
    pool = candidates[n_anchor:]

    rel_score = {"exact match": 3, "wheel neighbour": 2,
                 "major/minor swap": 2, "diagonal energy boost": 1}

    while len(selected) < count and pool:
        last = next((t["camelot"] for t in reversed(selected) if t.get("camelot")), "")

        def score(t):
            if last and t.get("camelot"):
                try:
                    return rel_score.get(camelot_relation(last, t["camelot"]), 0)
                except Exception:
                    return 0
            return 0

        pool.sort(key=score, reverse=True)     # стабильно: при равенстве — по рангу
        selected.append(pool.pop(0))

    return selected


def passes_sanity(track: dict, year_lo: int | None = None, year_hi: int | None = None,
                  bpm_lo: float | None = None, bpm_hi: float | None = None,
                  bpm_tol: float = 2.0) -> bool:
    """
    Грубый гейт пула. Режем трек, ТОЛЬКО если его год/BPM известны и явно вне рамок.
    Неизвестные (None/0) пропускаем — их добьёт enrich/local_enrich (Path B). Чистая.
    Применяется ко ВСЕМ источникам (раньше год проверялся только у Discogs → Beatport
    пропускал Gorillaz 2001; BPM-фильтр обходился при bpm=0 → пролезал 150 BPM).
    """
    try:
        y = int(track.get("year") or 0)
    except (ValueError, TypeError):
        y = 0
    if y and year_lo and year_hi and not (year_lo <= y <= year_hi):
        return False
    try:
        b = float(track.get("bpm") or 0)
    except (ValueError, TypeError):
        b = 0.0
    if b and bpm_lo and bpm_hi and not (bpm_lo - bpm_tol <= b <= bpm_hi + bpm_tol):
        return False
    return True


def global_bpm_bounds(config: dict) -> tuple[float | None, float | None]:
    """Общие границы BPM по всем сегментам (объединение bpm_range). Чистая."""
    los, his = [], []
    for s in config.get("segments", []):
        rng = s.get("bpm_range") or []
        if len(rng) == 2:
            los.append(rng[0]); his.append(rng[1])
    return (min(los), max(his)) if los else (None, None)


def select_mix(verified: list[dict], config: dict,
               speed: str = "thorough") -> list[dict]:
    """Отобрать по seg['count'] на каждый сегмент, сохраняя порядок сегментов.
    Чистая функция."""
    counts = {s["name"]: s["count"] for s in config["segments"]}
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for t in verified:
        seg = t.get("segment", "")
        if seg not in groups:
            groups[seg] = []
            order.append(seg)
        groups[seg].append(t)

    out: list[dict] = []
    for seg in order:
        c = counts.get(seg, len(groups[seg]))
        out.extend(select_segment_tracks(groups[seg], c, speed))
    return out


def get_discogs_styles(genre: str) -> list[str]:
    """
    Получить Discogs-стили для жанра.
    Порядок: точная таблица → PulseRoots-резолвер (офлайн) → частичная таблица
    → LLM fallback (OpenRouter) → жанр как есть.
    """
    normalized = genre.lower().strip()

    # 1. Точное совпадение со статической таблицей (ручная — побеждает всё)
    if normalized in DISCOGS_STYLE_MAP:
        return DISCOGS_STYLE_MAP[normalized]

    # 1.5. PulseRoots-резолвер (офлайн, детерминированный): уверенный матч (≥0.8)
    #      даёт канонический стиль + смежные — точнее грубого substring ниже и
    #      без сети. Слабый матч пропускаем дальше по цепочке.
    try:
        import style_resolver
        r = style_resolver.resolve(genre, threshold=0.8)
        if r["matched"]:
            styles = [r["style"]] + style_resolver.similar_styles(genre)[:3]
            print(f"  Жанр '{genre}' → PulseRoots: {styles} (score={r['score']})")
            return styles
    except Exception as e:
        print(f"  PulseRoots resolver недоступен: {e}")

    # 2. Частичное совпадение
    for key, styles in DISCOGS_STYLE_MAP.items():
        if key in normalized or normalized in key:
            print(f"  Жанр '{genre}' → маппинг на '{key}' (частичное совпадение)")
            return styles

    # 3. LLM fallback — спрашиваем OpenRouter
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if openrouter_key:
        print(f"  Жанр '{genre}' не найден в таблице → спрашиваю LLM...")
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-flash-1.5",
                    "max_tokens": 100,
                    "messages": [{
                        "role": "user",
                        "content": (
                            f"List 3-5 Discogs style tags most closely related to the music genre '{genre}'. "
                            f"Return only a JSON array of strings, no explanation. "
                            f"Example: [\"Nu-Disco\", \"Indie Dance\", \"House\"]"
                        )
                    }]
                },
                timeout=15,
            )
            content = resp.json()["choices"][0]["message"]["content"]
            match = re.search(r'\[.*?\]', content, re.DOTALL)
            if match:
                styles = json.loads(match.group(0))
                print(f"  LLM стили для '{genre}': {styles}")
                return styles
        except Exception as e:
            print(f"  LLM fallback error: {e}")

    # 4. Последний резерв — передать жанр как есть
    print(f"  Жанр '{genre}' → используем как есть (нет LLM ключа)")
    return [genre.title()]


def warp_reconnect():
    """Переподключить Cloudflare Warp для смены IP. После Google-запросов."""
    try:
        subprocess.run(["warp-cli", "disconnect"], capture_output=True, timeout=10)
        time.sleep(1.5)
        subprocess.run(["warp-cli", "connect"], capture_output=True, timeout=10)
        time.sleep(2.0)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        time.sleep(GOOGLE_DELAY)


def get_tunebat_bpm_key(artist: str, track: str) -> tuple[int, str]:
    """
    BPM + Camelot из Tunebat через Playwright + stealth.
    Вызывается в batch через enrich_tracks_via_tunebat() из playwright_scraper.py.
    
    Этот отдельный вызов — fallback для единичного трека.
    Для batch-обогащения используй: playwright_scraper.py --enrich <json>
    
    Устарел: вместо этого используй batch enrich_tracks_via_tunebat().
    """
    # Импортируем и запускаем через временный JSON
    import tempfile, subprocess, shlex
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump([{"artist": artist, "track": track, "bpm": 0, "camelot": ""}], tmp)
    tmp.close()
    
    try:
        cmd = f"xvfb-run --auto-servernum uv run python3 {PLAYWRIGHT_SCRAPER} --enrich {shlex.quote(tmp.name)} -o {shlex.quote(tmp.name + '_out.json')}"
        subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90,
                       env={**os.environ, "SOCKS5_PROXY": os.environ.get("SOCKS5_PROXY", "socks5://127.0.0.1:40000")})
        if os.path.exists(tmp.name + '_out.json'):
            with open(tmp.name + '_out.json') as f:
                data = json.load(f)
            if data and data[0].get("bpm"):
                return data[0]["bpm"], data[0].get("camelot", "")
    except Exception:
        pass
    finally:
        try: os.unlink(tmp.name)
        except OSError: pass
        try: os.unlink(tmp.name + '_out.json')
        except OSError: pass
    
    return 0, ""


def fetch_discogs(
    genre: str,
    years: list[int],
    region: str = "",
    country: str = "",
    pool_factor: int = 3,
    target_count: int = 12,
) -> list[dict]:
    """
    Discogs Database Search API.
    Собирает пул в pool_factor × target_count треков.
    Токен: discogs.com → Settings → Developers → Generate Token → DISCOGS_TOKEN в .env
    """
    if not DISCOGS_TOKEN:
        print("  Discogs: нет DISCOGS_TOKEN → пропуск")
        return []

    target_pool = pool_factor * target_count
    styles = get_discogs_styles(genre)
    print(f"  Discogs стили: {styles}")

    discogs_headers = {
        **HEADERS,
        "Authorization": f"Discogs token={DISCOGS_TOKEN}",
        "User-Agent": "autodj-mixer/1.0 +https://github.com/StanAngular/autodj-mixer",
    }

    all_tracks: list[dict] = []
    seen: set[str] = set()

    for style in styles:
        if len(all_tracks) >= target_pool:
            break
        for year in (years or [datetime.now().year, datetime.now().year - 1]):
            if len(all_tracks) >= target_pool:
                break

            params: dict = {
                "style":      style,
                "year":       year,
                "type":       "release",
                "sort":       "want",
                "sort_order": "desc",
                "per_page":   50,
                "page":       1,
            }
            if country:
                params["country"] = country
            elif region:
                params["country"] = region

            try:
                resp = requests.get(
                    "https://api.discogs.com/database/search",
                    headers=discogs_headers,
                    params=params,
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("results", []):
                    title = item.get("title", "")
                    if " - " not in title:
                        continue
                    parts  = title.split(" - ", 1)
                    artist = parts[0].strip()
                    track  = parts[1].strip()

                    # Фильтр альбомов — пропускать LP/compilations
                    formats = item.get("format", []) or []
                    if any(w in " ".join(formats).lower() for w in ["album","lp","compilation"]):
                        continue

                    dedup = f"{artist.lower()}|{track.lower()}"
                    if dedup in seen:
                        continue
                    seen.add(dedup)

                    item_year = int(item.get("year", 0) or 0)
                    if years and item_year and item_year not in years:
                        continue

                    community    = item.get("community", {}) or {}
                    want         = community.get("want", 0)
                    have         = community.get("have", 0)
                    styles_raw   = item.get("style", []) or []
                    source_url   = item.get("uri", "")
                    if source_url and not source_url.startswith("http"):
                        source_url = f"https://www.discogs.com{source_url}"

                    cat = "Local Underground" if (country or region) else "Mainstream"
                    rel_country = item.get("country", "") or country or region or ""

                    all_tracks.append({
                        "artist":        artist,
                        "track":         track,
                        "bpm":           0,
                        "camelot":       "",
                        "country":       rel_country,
                        "category":      cat,
                        "source_url":    source_url,
                        "youtube_url":   "",
                        "energy_markers": styles_raw[:3],
                        "support_score": min(want, 999),
                        "year":          item_year,
                        "reason": (
                            f"Discogs {style} {item_year}; "
                            f"want={want} have={have}"
                            + (f"; {country or region}" if (country or region) else "")
                        ),
                    })

                time.sleep(1.0)   # Discogs rate limit

            except requests.RequestException as e:
                print(f"  Discogs error (style={style} year={year}): {e}")
                time.sleep(2.0)

    # Сортировать по want (popularity) убыв.
    all_tracks.sort(key=lambda t: t["support_score"], reverse=True)
    print(f"  Discogs: собрано {len(all_tracks)} треков в пул")
    return all_tracks


# ─── Camelot-совместимость ───────────────────────────────────────────────────

def get_compatible_keys(target: str) -> set[str]:
    """Вычислить множество совместимых ключей для целевого Camelot."""
    match = re.match(r'^(\d{1,2})([AB])$', target.upper())
    if not match:
        raise ValueError(f"Неверный формат Camelot: {target}. Ожидается например 8A, 12B.")
    num = int(match.group(1))
    letter = match.group(2)
    opposite = "B" if letter == "A" else "A"

    def camelot(n: int, l: str) -> str:
        n = ((n - 1) % 12) + 1
        return f"{n}{l}"

    return {
        camelot(num, letter),       # унисон
        camelot(num - 1, letter),   # -1 сосед
        camelot(num + 1, letter),   # +1 сосед
        camelot(num, opposite),     # мажор/минор
        camelot(num - 1, opposite), # диагональ (energy boost)
    }


def camelot_relation(target: str, found: str) -> str:
    """Описание гармонического отношения для поля reason."""
    t_num = int(re.match(r'(\d+)', target).group(1))
    t_let = target[-1]
    f_num = int(re.match(r'(\d+)', found).group(1))
    f_let = found[-1]
    opposite = "B" if t_let == "A" else "A"

    if found == target:
        return "exact match"
    if f_let == t_let and abs(f_num - t_num) in (1, 11):
        return "wheel neighbour"
    if f_num == t_num and f_let == opposite:
        return "major/minor swap"
    # Настоящий diagonal energy boost: смена лада + СОСЕДНИЙ номер (±1). Далёкие
    # пары (напр. 8A→3B) — это клэш, НЕ «буст» (раньше попадали сюда catch-all'ом).
    if f_let == opposite and abs(f_num - t_num) in (1, 11):
        return "diagonal energy boost"
    return "clash"


def camelot_distance(a: str, b: str) -> int:
    """
    Расстояние на колесе Camelot (0 = тот же ключ). Чистая функция.
    0 exact · 1 сосед/relative · 2 диагональ · ≥3 клэш. Нет ключа → большое (99).
    Используется для гармонического порядка (минимизировать скачки).
    """
    try:
        na = int(re.match(r'(\d+)', a).group(1)); la = a[-1]
        nb = int(re.match(r'(\d+)', b).group(1)); lb = b[-1]
    except (AttributeError, ValueError, TypeError):
        return 99
    ring = min((na - nb) % 12, (nb - na) % 12)      # 0..6 шагов по колесу
    if la == lb:
        return ring                                  # тот же лад
    if na == nb:
        return 1                                     # relative major/minor
    return ring + 1                                  # смена лада + ход по колесу


# ─── Верификация через yt-dlp ─────────────────────────────────────────────────

def normalize_text(s: str) -> str:
    noise = [
        "official", "video", "audio", "hd", "4k", "lyrics",
        "official music video", "official audio", "mv", "visualizer",
        "extended mix", "original mix", "feat", "ft", "presents",
        "premiere", "exclusive",
    ]
    s = s.lower()
    for n in noise:
        s = s.replace(n, " ")
    s = re.sub(r'[^\w\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def title_matches(artist: str, track: str, yt_title: str, yt_uploader: str) -> bool:
    """
    Мягкое сравнение: проверить что YouTube-видео действительно этот трек.
    Требует совпадения 60%+ ключевых слов из artist + track.
    """
    combined_yt = normalize_text(f"{yt_title} {yt_uploader}")
    keywords = [
        w for w in normalize_text(f"{artist} {track}").split()
        if len(w) > 2
    ]
    if not keywords:
        return False
    matches = sum(1 for kw in keywords if kw in combined_yt)
    return matches >= max(2, len(keywords) * 0.6)


def verify_and_resolve_url(
    artist: str,
    track: str,
    max_candidates: int = 5
) -> Optional[dict]:
    """
    Шукає трек спочатку на YouTube, потім на SoundCloud (якщо не знайдено).
    Повертає {'url': ..., 'title': ..., 'uploader': ..., 'source': ...} або None.
    """
    for platform in SEARCH_PLATFORMS:
        prefix = platform["prefix"]
        name = platform["name"]
        query = f"{prefix}{max_candidates}:{artist} - {track}"

        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--proxy", YTDLP_PROXY,
                    "--flat-playlist",
                    "--print", "%(url)s\t%(title)s\t%(uploader)s\t%(duration)s\t%(view_count)s",
                    "--no-warnings",
                    "--quiet",
                    query,
                ],
                capture_output=True,
                text=True,
                timeout=45,
            )
        except subprocess.TimeoutExpired:
            print(f"  {name} timeout: {artist} - {track}")
            continue
        except FileNotFoundError:
            print("  ОШИБКА: yt-dlp не найден. Установи: pip install yt-dlp")
            sys.exit(1)

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            url, title, uploader = parts[0], parts[1], parts[2]
            duration = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            views    = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0

            # Для SoundCloud duration може бути 0 — пропускаємо перевірку
            if duration and not (DURATION_MIN <= duration <= DURATION_MAX):
                continue

            if title_matches(artist, track, title, uploader):
                return {"url": url, "title": title, "uploader": uploader,
                        "source": name, "duration": duration, "views": views}

        # Якщо на YouTube не знайшли — пробуємо SoundCloud
        print(f"  {name}: не знайдено, пробую іншу платформу...")

    return None


# ─── Playwright Scraper Helper ────────────────────────────────────────────────

PLAYWRIGHT_SCRAPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playwright_scraper.py")
XVFB_RUN = "xvfb-run --auto-servernum" if os.system("which xvfb-run >/dev/null 2>&1") == 0 else ""


def _run_playwright_scraper(source: str, genre: str, timeout: int = 180) -> list[dict]:
    """
    Запускает playwright_scraper.py через subprocess и возвращает список треков.
    Использует SOCKS5_PROXY из окружения (Cloudflare Warp).
    
    Args:
        source: beatport, 1001tl, bandcamp, beatport-tracks
        genre: жанр для поиска
        timeout: таймаут в секундах (180 для beatport-tracks, 120 для остальных)
    """
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    
    cmd = (
        f"{XVFB_RUN} uv run python3 {PLAYWRIGHT_SCRAPER} "
        f"{source} --genre {shlex.quote(genre)} --output {shlex.quote(tmp_path)}"
    )
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "SOCKS5_PROXY": os.environ.get("SOCKS5_PROXY", "socks5://127.0.0.1:40000")}
        )
        if result.returncode != 0:
            print(f"  Playwright {source} error (exit {result.returncode})")
            if result.stderr:
                for line in result.stderr.split("\n")[-3:]:
                    print(f"    {line.strip()}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return []
        
        # Читаем из временного файла
        if os.path.exists(tmp_path):
            with open(tmp_path) as f:
                data = json.load(f)
            os.unlink(tmp_path)
            return data if isinstance(data, list) else []
        
        return []
    except subprocess.TimeoutExpired:
        print(f"  Playwright {source} timeout ({timeout}s)")
        return []
    except Exception as e:
        print(f"  Playwright {source} error: {e}")
        return []
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ─── Источник 1: Beatport Charts (через Playwright) ──────────────────────────

def fetch_beatport_charts(genre: str, years: list[int]) -> list[dict]:
    """
    Скрейпить Beatport через Playwright + stealth.
    Источник beatport-tracks: заходит в чарты и достаёт ОТДЕЛЬНЫЕ ТРЕКИ с их
    BPM и Camelot (item.bpm + item.key → Camelot). Раньше использовался источник
    'beatport' (возвращал чарты-плейлисты с bpm:0/camelot:"" → все треки выглядели
    неполными и зря летели в Tunebat → таймаут). 180s таймаут (нужно зайти в чарты).
    """
    tracks = _run_playwright_scraper("beatport-tracks", genre, timeout=180)
    
    # Конвертируем в единый формат (СОХРАНЯЯ bpm/camelot от beatport-tracks)
    result = []
    for t in tracks:
        result.append({
            "artist":        t.get("artist", "Various"),
            "track":         t.get("track", ""),
            "bpm":           t.get("bpm", 0),
            "camelot":       t.get("camelot", ""),
            "mix_name":      t.get("mix_name", ""),
            "label":         t.get("label", ""),
            "release_date":  t.get("release_date", ""),
            "genre":         t.get("genre", ""),
            "category":      "Mainstream",
            "source_url":    t.get("source_url", ""),
            "youtube_url":   "",
            "energy_markers": [],
            "support_score": t.get("support_score", 5),
            "reason":        t.get("reason", f"Beatport: {genre}"),
        })

    with_meta = sum(1 for r in result if r["bpm"] and r["camelot"])
    print(f"  Beatport: {len(result)} треков ({with_meta} с BPM/Camelot, через Playwright)")
    return result


# ─── Источник 2: 1001Tracklists (через Playwright + SOCKS5) ───────────────────

def fetch_1001tracklists(genre: str, years: list[int]) -> list[dict]:
    """
    1001tracklists — DJ саппорт. Playwright + SOCKS5 прокси.
    ВНИМАНИЕ: Cloudflare заблокировал Warp IP (unblock_ip.html).
    Нужен резидентский прокси для работы.
    """
    print("  1001TL: пропущен — Cloudflare заблокировал Warp IP (нужен resident proxy)")
    return []


# ─── Источник 3: Resident Advisor Charts ─────────────────────────────────────

def fetch_ra_charts(genre: str) -> list[dict]:
    """
    Скрейпить RA genre charts.
    ВНИМАНИЕ: RA под DataDome. Нужен резидентский прокси (RESIDENTIAL_PROXY).
    Без него не работает. Пропускаем.
    """
    print(f"  RA: пропущен — нужен резидентский прокси (DataDome)")
    return []


# ─── Источник 4: Bandcamp (через Playwright + SOCKS5) ─────────────────────────

def fetch_bandcamp_underground(genre: str, region: str) -> list[dict]:
    """
    Bandcamp discover page. Playwright + SOCKS5 прокси.
    Парсит альбомы из DOM.
    """
    tracks = _run_playwright_scraper("bandcamp", genre)
    
    result = []
    for t in tracks:
        artist = t.get("artist", "")
        track = t.get("track", "")
        source_url = t.get("source_url", "")
        
        if not artist or not track:
            continue
        
        region_match = (
            region.lower() in source_url.lower()
            or region.lower() in artist.lower()
        ) if region else False
        
        result.append({
            "artist":        artist,
            "track":         track,
            "bpm":           0,
            "camelot":       "",
            "category":      "Local Underground" if region_match else "Underground",
            "source_url":    source_url,
            "youtube_url":   "",
            "energy_markers": [],
            "support_score": 0,
            "reason": (
                f"Bandcamp {genre}"
                + (f"; {region} scene" if region_match else "")
                + "; Hidden Gem"
            ),
        })
    
    print(f"  Bandcamp: {len(result)} альбомов (через Playwright)")
    return result


# ─── Получить BPM/Key/стиль через Beatport search ──────────────────────────

# Маппінг ключів Beatport → Camelot (для key_name типу "Db Minor")
KEY_NAME_TO_CAMELOT = {
    "C Major": "8B", "C Minor": "5A",
    "C# Major": "3B", "C# Minor": "12A",
    "Db Major": "3B", "Db Minor": "12A",
    "D Major": "10B", "D Minor": "7A",
    "D# Major": "5B", "D# Minor": "2A",
    "Eb Major": "5B", "Eb Minor": "2A",
    "E Major": "12B", "E Minor": "9A",
    "F Major": "7B", "F Minor": "4A",
    "F# Major": "2B", "F# Minor": "11A",
    "Gb Major": "2B", "Gb Minor": "11A",
    "G Major": "9B", "G Minor": "6A",
    "G# Major": "4B", "G# Minor": "1A",
    "Ab Major": "4B", "Ab Minor": "1A",
    "A Major": "11B", "A Minor": "8A",
    "A# Major": "6B", "A# Minor": "3A",
    "Bb Major": "6B", "Bb Minor": "3A",
    "B Major": "1B", "B Minor": "10A",
}


def search_beatport_track(artist: str, track: str) -> tuple[int, str, str]:
    """
    Шукає трек на Beatport за іменем, повертає BPM, Camelot, стиль.
    Beatport НЕ використовує Cloudflare (на відміну від Tunebat).
    Повертає (bpm, camelot, style) або (0, "", "").
    """
    query = f"{artist} {track}"
    url = f"https://www.beatport.com/search?q={requests.utils.quote(query)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script_tag:
            return 0, "", ""

        data = json.loads(script_tag.string)
        queries = (
            data.get("props", {})
                .get("pageProps", {})
                .get("dehydratedState", {})
                .get("queries", [])
        )

        for q in queries:
            tracks_data = q.get("state", {}).get("data", {}).get("tracks", {})
            if not isinstance(tracks_data, dict):
                continue
            items = tracks_data.get("data", [])
            if not items:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                # Перевірити збіг назви треку
                name = (item.get("track_name", "") or "").lower()
                if track.lower() not in name:
                    continue

                # Перевірити збіг артиста
                artist_list = [a.get("artist_name", "") for a in item.get("artists", [])]
                artist_names = " ".join(artist_list).lower()
                if artist.lower() not in artist_names:
                    continue

                # BPM
                bpm = item.get("bpm") or 0

                # Key → Camelot через key_name ("Db Minor" → "12A")
                key_name = item.get("key_name", "") or ""
                camelot = KEY_NAME_TO_CAMELOT.get(key_name.strip(), "")

                # Стиль/жанр — genre це список [{"genre_id": X, "genre_name": "..."}]
                style_str = ""
                genre_list = item.get("genre", [])
                if isinstance(genre_list, list) and len(genre_list) > 0:
                    style_str = genre_list[0].get("genre_name", "") or ""
                elif isinstance(genre_list, dict):
                    style_str = genre_list.get("name", "") or ""

                return int(bpm) if bpm else 0, camelot, style_str

        time.sleep(SCRAPE_DELAY)

    except (requests.RequestException, json.JSONDecodeError, AttributeError, TypeError) as e:
        print(f"  Beatport search error: {e}")

    return 0, "", ""


# ─── Fallback: BPM/Key з YouTube description ──────────────────────────────

def enrich_from_youtube_description(yt_url: str) -> tuple[int, str]:
    """
    Запасний варіант: витягнути BPM і Key з description YouTube-відео.
    Спрацьовує для треків на лейблах (Afterlife, Ed Banger та ін.)
    які публікують метадані в описі.
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "--proxy", YTDLP_PROXY, "--print", "%(description)s",
             "--no-warnings", "--quiet", yt_url],
            capture_output=True, text=True, timeout=20,
        )
        desc = result.stdout

        # BPM: "132 BPM" або "BPM: 132"
        bpm_match = re.search(r'\b(\d{2,3})\s*[Bb][Pp][Mm]|\b[Bb][Pp][Mm]\s*:?\s*(\d{2,3})', desc)
        bpm = int(bpm_match.group(1) or bpm_match.group(2)) if bpm_match else 0

        # Key: "Key: Am" або "8A" напряму
        camelot_match = re.search(r'\b([1-9]|1[0-2])[AB]\b', desc)
        camelot = camelot_match.group(0) if camelot_match else ""

        if not camelot:
            key_match = re.search(
                r'\b(Key|Tonality)\s*:?\s*([A-G][b#]?\s*(?:maj(?:or)?|min(?:or)?))\b',
                desc, re.IGNORECASE
            )
            if key_match:
                camelot = KEY_TO_CAMELOT.get(key_match.group(2).strip(), "")

        return bpm, camelot
    except Exception:
        return 0, ""


# ─── Главный цикл ─────────────────────────────────────────────────────────────

def xvfb_preflight(display: str, xvfb_run_path: str) -> tuple[bool, str]:
    """
    Проверка окружения для headed-скрейпинга (Tunebat/Beatport идут через
    видимый Chromium для обхода анти-бота, а ему нужен X-дисплей).
    Чистая функция — тестируема.

      display       — значение $DISPLAY ('' если нет)
      xvfb_run_path — путь к xvfb-run ('' если не найден)

    Возвращает (ok, сообщение). ok=False → headed-браузер не стартует, обогащение
    Tunebat/Beatport будет пропущено (BPM/Camelot доберутся из других источников).
    """
    if display:
        return True, ""
    if xvfb_run_path:
        return False, (
            "⚠ DISPLAY не задан, но xvfb-run найден. Запусти curate ПОД xvfb:\n"
            "    xvfb-run --auto-servernum python3 curate_tracks.py ...\n"
            "  Иначе Tunebat/Beatport (headed-скрейпинг) будут пропущены."
        )
    return False, (
        "⚠ Нет ни DISPLAY, ни xvfb-run — headed-скрейпинг (Tunebat/Beatport) будет\n"
        "  пропущен. Установи Xvfb (один раз) и запускай под ним:\n"
        "    bash scripts/setup_xvfb.sh\n"
        "    xvfb-run --auto-servernum python3 curate_tracks.py ..."
    )


def _dedup_pool(raw_pool: list[dict]) -> list[dict]:
    """Дедуп пула со слиянием провенанса (found_in/поля)."""
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for t in raw_pool:
        dk = dedup_key(t["artist"], t["track"])
        if dk not in seen:
            seen[dk] = t
            out.append(t)
        else:
            merge_provenance(seen[dk], t)
    return out


def select_enrich_candidates(deduped: list[dict], discovery: str = "popular",
                             limit: int | None = None) -> list[dict]:
    """
    Кого гнать через Tunebat: только треки без полных метаданных (нет BPM или
    Camelot), ранжированные под discovery и обрезанные до limit. Это и есть
    оптимизация — обогащаем самых перспективных кандидатов, а не весь пул, иначе
    headed-браузер упирается в таймаут на больших пулах. Чистая функция.
    """
    need = [t for t in deduped if not t.get("bpm") or not t.get("camelot")]
    if limit is not None and len(need) > limit:
        need = discovery_rank(need, discovery)[:limit]
    return need


def enrich_pool(deduped: list[dict], seg: dict | None = None,
                limit: int | None = None) -> list[dict]:
    """
    Шаг 2: обогащение BPM/Camelot. Сначала дисковый кэш (мгновенно), затем Tunebat
    только для остатка (топ-`limit` под discovery). Новые результаты кэшируются.
    """
    discovery = (seg or {}).get("discovery", "popular")
    incomplete = [t for t in deduped if not t.get("bpm") or not t.get("camelot")]
    if not incomplete:
        print("  Все треки уже имеют BPM/Camelot — пропуск")
        return deduped

    # 1. Кэш обогащения — дозаполняем без Tunebat
    cache = enrich_cache.load_cache()
    hits, misses = enrich_cache.split_by_cache(incomplete, cache)
    for t, bpm, cam in hits:
        set_field(t, "bpm",     bpm, "cache")
        set_field(t, "camelot", cam, "cache")
    if hits:
        print(f"  Кэш: {len(hits)} попаданий (без Tunebat)")

    # 2.5 Обогащение ПО НЕОБХОДИМОСТИ: если полных треков (Beatport + кэш) уже
    # хватает на сегмент — Tunebat не нужен. Иначе тянем только нехватку.
    seg_count = (seg or {}).get("count", 0)
    if seg_count > 0:
        n_complete = sum(1 for t in deduped if t.get("bpm") and t.get("camelot"))
        gap = enrich_gap(n_complete, seg_count)
        if gap <= 0:
            print(f"  Полных треков {n_complete} ≥ нужно сегменту ({seg_count}+буфер) — Tunebat не требуется")
            return deduped
        limit = gap if limit is None else min(limit, gap)
        print(f"  Нехватка полных: {gap} (полных {n_complete}, нужно {seg_count}) → Tunebat только на нехватку")

    # 3. Остаток без метаданных → ранжируем под discovery и берём топ-limit
    need = select_enrich_candidates(misses, discovery, limit)

    if not need:
        print("  Остаток покрыт кэшем — Tunebat пропущен")
        return deduped
    if limit is None and len(deduped) > TUNEBAT_MAX_POOL:
        print(f"  Пул {len(deduped)} > {TUNEBAT_MAX_POOL} → Tunebat пропущен")
        return deduped

    if len(need) < len(misses):
        print(f"  Обогащаю топ-{len(need)} из {len(misses)} (после кэша, discovery={discovery})")
    else:
        print(f"  Обогащаю {len(need)} (после кэша)")

    try:
        from playwright_scraper import enrich_tracks_via_tunebat
        enriched = enrich_tracks_via_tunebat(need)
        by_key = {dedup_key(t["artist"], t["track"]): t for t in enriched}
        for t in deduped:
            et = by_key.get(dedup_key(t["artist"], t["track"]))
            if et:
                set_field(t, "bpm",     et.get("bpm"),     "Tunebat")
                set_field(t, "camelot", et.get("camelot"), "Tunebat")
        # 3. Новые полные результаты → в кэш
        stored = 0
        for t in deduped:
            if enrich_cache.cache_put(cache, t["artist"], t["track"],
                                      t.get("bpm"), t.get("camelot")):
                stored += 1
        if enrich_cache.save_cache(cache):
            print(f"  Кэш обновлён: {stored} записей всего")
    except ImportError as e:
        print(f"  playwright_scraper недоступен: {e} → пропуск Tunebat")
    except Exception as e:
        print(f"  Ошибка Tunebat: {e} → продолжаю с исходными данными")
    return deduped


def filter_rank_tag(pool: list[dict], seg: dict) -> list[dict]:
    """
    Шаг 3 для сегмента: фильтр по bpm_range/target_key + ранжирование discovery +
    проставление поля 'segment'. ЧИСТАЯ функция (без сети) — тестируема.
    """
    compatible = None
    if seg.get("target_key"):
        try:
            compatible = get_compatible_keys(seg["target_key"])
        except ValueError:
            compatible = None

    rng = seg.get("bpm_range") or []
    lo, hi = (rng[0], rng[1]) if rng else (0, 0)

    out: list[dict] = []
    for t in pool:
        bpm = t.get("bpm") or 0
        if rng and bpm and not (lo <= bpm <= hi):
            continue
        if compatible and t.get("camelot") and t["camelot"] not in compatible:
            continue
        t["segment"] = seg["name"]
        out.append(t)

    return discovery_rank(out, seg.get("discovery", "popular"))


def collect_segment(seg: dict, years: list[int], pool_factor: int,
                    speed: str = "thorough") -> list[dict]:
    """
    Шаги 1-3 для одного сегмента: сбор пула по styles × countries → дедуп →
    обогащение → фильтр/ранжирование/тег. Возвращает отфильтрованные треки.
    Сетевая функция (вызывает фетчеры/скрейперы).
    """
    styles = seg["styles"] or [""]
    countries = seg["countries"] or [""]
    raw: list[dict] = []

    for genre in styles:
        if not genre:
            continue
        print(f"─── [{seg['name']}] стиль '{genre}' ───")
        raw += tag_src(fetch_1001tracklists(genre, years), "1001Tracklists")
        for country in countries:
            raw += tag_src(fetch_discogs(
                genre, years, country=country,
                pool_factor=pool_factor, target_count=seg["count"]
            ), "Discogs")
        raw += tag_src(fetch_beatport_charts(genre, years), "Beatport")
        raw += tag_src(_run_playwright_scraper("beatport-tracks", genre), "Beatport")
        for country in countries:
            if country:
                raw += tag_src(fetch_bandcamp_underground(genre, country), "Bandcamp")

    print(f"  [{seg['name']}] пул: {len(raw)} до фильтра")
    deduped = _dedup_pool(raw)
    enrich_budget_n = enrich_budget(seg["count"], speed)
    enriched = enrich_pool(deduped, seg, enrich_budget_n)
    filtered = filter_rank_tag(enriched, seg)
    print(f"  [{seg['name']}] после фильтра: {len(filtered)}")
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Детерминированный поиск треков для autodj-mixer"
    )
    parser.add_argument("--genre",    default="")
    parser.add_argument("--bpm",      type=int, default=0,
                        help="Целевой BPM (или используй --bpm-min/--bpm-max)")
    parser.add_argument("--bpm-min",  type=int, default=0)
    parser.add_argument("--bpm-max",  type=int, default=0)
    parser.add_argument("--camelot",  default="")
    parser.add_argument("--count",    type=int, default=0)
    parser.add_argument("--region",   default="",
                        help="Регион для тегов (Bandcamp/Discogs)")
    parser.add_argument("--country",  default="",
                        help="Страна Discogs country filter (France, Germany…)")
    parser.add_argument("--years",    default="")
    parser.add_argument("--out",      default="curator_candidates.json")
    parser.add_argument("--urls-out", default="")
    parser.add_argument("--style",    default="")
    parser.add_argument("--bpm-tolerance", type=int, default=4)
    parser.add_argument("--discovery", choices=["popular", "newest", "underground"],
                        default="popular",
                        help="режим отбора: популярное / новинки / андеграунд")
    parser.add_argument("--pool-factor",   type=int, default=3,
                        help="Собрать pool_factor×count кандидатов перед фильтром")
    parser.add_argument("--config", default="",
                        help="JSON-конфиг курации (сегменты+траектория). "
                             "Если задан — переопределяет --genre/--bpm/--camelot/--country")
    parser.add_argument("--fast", action="store_true",
                        help="Быстрый режим: меньше кандидатов на обогащение Tunebat")
    parser.add_argument("--print-config-schema", action="store_true",
                        help="Вывести JSON-схему конфига курации и выйти "
                             "(для агентов/интеграций — не запускает курацию)")
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--no-approve", action="store_true",
                        help="Не останавливаться на апруве плейлиста")
    args = parser.parse_args()

    # Ранний выход: вывести схему конфига и завершиться (для агентов/интеграций)
    if args.print_config_schema:
        print(json.dumps(curation_config.schema(), ensure_ascii=False, indent=2))
        sys.exit(0)

    current_year = datetime.now().year

    # ── Конфиг: --config (многосегментный) или старый CLI (1 сегмент) ──
    try:
        if args.config:
            config = curation_config.load_config_file(args.config)
        else:
            if not (args.genre and args.camelot and args.count):
                print("ОШИБКА: без --config нужны --genre, --camelot и --count")
                sys.exit(1)
            if not (args.bpm or (args.bpm_min and args.bpm_max)):
                print("ОШИБКА: укажи --bpm или --bpm-min + --bpm-max")
                sys.exit(1)
            config = curation_config.config_from_cli(args)
    except curation_config.CurationConfigError as e:
        print(f"ОШИБКА конфига: {e}")
        sys.exit(1)
    except (OSError, ValueError) as e:
        print(f"ОШИБКА чтения --config: {e}")
        sys.exit(1)

    # --fast применяется к ОБОИМ путям (и --config, и старый CLI)
    config["speed"] = resolve_speed(config["speed"], args.fast)

    years = config["years"] or [current_year, current_year - 1]
    total_count = sum(s["count"] for s in config["segments"])

    # Ключ для колонки отношения в апруве: единый для 1 сегмента, иначе пусто
    approval_key = (config["segments"][0]["target_key"]
                    if len(config["segments"]) == 1 else "")

    print(f"\n{'═'*55}")
    print(" autodj-mixer Curator v5 (сегменты)")
    print(curation_config.describe(config))
    print(f"{'═'*55}\n")

    # Префлайт: headed-скрейпинг (Tunebat/Beatport) требует X-дисплея (xvfb)
    ok_xvfb, xvfb_msg = xvfb_preflight(
        os.environ.get("DISPLAY", ""), shutil.which("xvfb-run") or "")
    if not ok_xvfb:
        print(xvfb_msg + "\n")

    # ════════════════════════════════════════════════════════════
    # ШАГИ 1-3: СБОР + ОБОГАЩЕНИЕ + ФИЛЬТР по каждому сегменту
    # ════════════════════════════════════════════════════════════
    filtered: list[dict] = []
    for seg in config["segments"]:
        print(f"\n═══ Сегмент '{seg['name']}' ═══")
        seg_tracks = collect_segment(seg, years, args.pool_factor, config["speed"])
        filtered.extend(seg_tracks[: seg["count"] + 2])   # +2 буфер на сегмент

    print(f"\n Всего после фильтра по сегментам: {len(filtered)}/{total_count}")

    if len(filtered) < total_count:
        print(f"⚠  Пул меньше нужного ({len(filtered)}/{total_count}). "
              f"Попробуй --pool-factor {args.pool_factor + 1} или ослабь bpm_range.")

    # ════════════════════════════════════════════════════════════
    # ШАГ 4: ВЕРИФИКАЦИЯ через yt-dlp (count + 2 запаса)
    # ════════════════════════════════════════════════════════════
    print("\n═══ ШАГ 4: Верификация yt-dlp ═══")

    target = total_count + 2   # +2 запаса на случай браковки
    verified: list[dict] = []

    for track in filtered:
        if len(verified) >= target:
            break

        print(f"Проверяю: {track['artist']} — {track['track']}")

        if args.no_verify:
            track["youtube_url"] = (
                f"ytsearch1:{track['artist']} - {track['track']}"
            )
        else:
            yt = verify_and_resolve_url(track["artist"], track["track"])
            if yt is None:
                print(f"  ✗ не найдено — пропуск")
                continue
            track["youtube_url"] = yt["url"]
            track["youtube_status"] = "verified"
            track["youtube_src"] = yt.get("source", "YouTube")
            track["duration_sec"] = yt.get("duration", 0)
            track["youtube_views"] = yt.get("views", 0)
            print(f"  ✓ {yt.get('source', 'YouTube')}: {yt['title'][:55]}")

            # Beatport search если BPM/Key всё ещё неизвестны
            if track["bpm"] == 0 or not track["camelot"]:
                eb, ek, es = search_beatport_track(track["artist"], track["track"])
                if eb: set_field(track, "bpm", eb, "Beatport"); print(f"  ℹ Beatport BPM: {eb}")
                if ek: set_field(track, "camelot", ek, "Beatport"); print(f"  ℹ Beatport Key: {ek}")
                if es and not track.get("style"): track["style"] = es

            # YouTube description как последний fallback
            if track["bpm"] == 0 or not track["camelot"]:
                yb, yk = enrich_from_youtube_description(track["youtube_url"])
                if yb: set_field(track, "bpm", yb, "YouTube-desc"); print(f"  ℹ YT desc BPM: {yb}")
                if yk: set_field(track, "camelot", yk, "YouTube-desc"); print(f"  ℹ YT desc Key: {yk}")

        # style fallback
        if args.style and not track.get("style"):
            track["style"] = args.style

        # Camelot relation в reason (только при едином ключе сегмента)
        if track.get("camelot") and approval_key:
            rel = camelot_relation(approval_key, track["camelot"])
            if rel not in track.get("reason", ""):
                track["reason"] = track.get("reason", "") + f"; {track['camelot']} = {rel}"

        verified.append(track)
        print(
            f"  [{len(verified)}/{target}] ✓  "
            f"{track['artist']} — {track['track']} "
            f"({track['bpm'] or '?'} BPM, {track['camelot'] or '?'})\n"
        )

    # ════════════════════════════════════════════════════════════
    # ШАГ 4.35: грубый гейт года/BPM — режем явно лишнее (Gorillaz 2001, 150 BPM)
    # по ВСЕМ источникам; неизвестные метаданные не трогаем (добьёт enrich/local).
    # ════════════════════════════════════════════════════════════
    _ylo, _yhi = (min(years), max(years)) if years else (None, None)
    _blo, _bhi = global_bpm_bounds(config)
    _before = len(verified)
    verified = [t for t in verified if passes_sanity(t, _ylo, _yhi, _blo, _bhi)]
    _dropped = _before - len(verified)
    if _dropped:
        print(f"Гейт года/BPM: отброшено {_dropped} вне рамок "
              f"(год {_ylo}–{_yhi}, BPM {_blo}–{_bhi}); неизвестные оставлены.")

    # ════════════════════════════════════════════════════════════
    # ШАГ 4.5: СБОРКА по траектории (порядок сегментов + BPM-ramp/harmonic)
    # ════════════════════════════════════════════════════════════
    # ШАГ 4.4: умный отбор — count лучших на сегмент (якоря + гармония)
    _pre: dict[str, int] = {}
    for t in verified:
        _pre[t.get("segment", "")] = _pre.get(t.get("segment", ""), 0) + 1
    verified = select_mix(verified, config, config["speed"])
    _post: dict[str, int] = {}
    for t in verified:
        _post[t.get("segment", "")] = _post.get(t.get("segment", ""), 0) + 1
    _sel = " · ".join(f"{s or 'mix'}: {_pre.get(s, 0)}→{n}" for s, n in _post.items())
    print(f"\nОтбор (из пула с запасом → выбрано на сегмент): {_sel}")

    verified = assemble_mix(verified, config["trajectory"])
    _curve = trajectory_summary(verified)
    if _curve:
        print(f"\n{_curve}")

    # ════════════════════════════════════════════════════════════
    # ШАГ 5: АПРУВ плейлиста (если не --no-approve)
    # ════════════════════════════════════════════════════════════
    final: list[dict] = []

    # Таблица плейлиста печатается ВСЕГДА — видимость и в агентском режиме
    print("\n═══ ШАГ 5: Плейлист ═══")
    print(format_approval_table(verified, approval_key))
    _playlist = build_youtube_playlist_url(verified)
    if _playlist:
        print(f"\n▶ YouTube-плейлист (превью всего сета): {_playlist}")
    print("\n" + harmonic_chain_trace(verified))

    if args.no_approve or not sys.stdin.isatty():
        final = verified[:total_count]
        print(f"\n(неинтерактивный режим — принято {len(final)} треков без правок)")
    else:
        print(f"\n{'─'*55}")
        print("Введи номера треков для УДАЛЕНИЯ через пробел (или Enter для принятия всего):")

        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            user_input = ""

        if user_input:
            reject_idxs = set()
            for token in user_input.split():
                if token.isdigit():
                    idx = int(token) - 1
                    if 0 <= idx < len(verified):
                        reject_idxs.add(idx)
                        print(f"  ✗ Удалён: {verified[idx]['artist']} — {verified[idx]['track']}")

            kept     = [t for i, t in enumerate(verified) if i not in reject_idxs]
            rejected = len(reject_idxs)

            replacements = [t for i, t in enumerate(verified)
                            if i not in reject_idxs and i >= total_count]
            final = kept[:total_count]

            if len(final) < total_count:
                print(
                    f"⚠  После удаления {rejected} треков — недостаточно. "
                    f"Запусти снова с --pool-factor {args.pool_factor + 1} для большего буфера."
                )
        else:
            final = verified[:total_count]
            print("  ✓ Принято без изменений")

    # ════════════════════════════════════════════════════════════
    # ШАГ 6: СОХРАНЕНИЕ
    # ════════════════════════════════════════════════════════════
    print(f"\n{'═'*55}")
    print(f"Итого: {len(final)} треков из {total_count} запрошенных")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    print(f"JSON → {args.out}")

    if args.urls_out:
        with open(args.urls_out, "w", encoding="utf-8") as f:
            for t in final:
                if t.get("youtube_url"):
                    f.write(t["youtube_url"] + "\n")
        print(f"URLs → {args.urls_out}")

    playlist = build_youtube_playlist_url(final)
    if playlist:
        n = playlist.count(",") + 1
        print(f"\n▶ Превью-плейлист ({n} видео, временный):\n  {playlist}")

    print(f"\nСледующий шаг:")
    if args.urls_out:
        print(f"  python3 yt_download.py --url-file {args.urls_out}")
    else:
        print(f"  python3 yt_download.py --candidates {args.out}")


if __name__ == "__main__":
    main()
