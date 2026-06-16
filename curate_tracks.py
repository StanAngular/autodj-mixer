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
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional

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


def get_discogs_styles(genre: str) -> list[str]:
    """
    Получить Discogs-стили для жанра.
    Порядок: статическая таблица → LLM fallback через OpenRouter.
    """
    normalized = genre.lower().strip()

    # 1. Точное совпадение
    if normalized in DISCOGS_STYLE_MAP:
        return DISCOGS_STYLE_MAP[normalized]

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
    if f_let == t_let and abs(f_num - t_num) == 1:
        return "wheel neighbour"
    if f_let == t_let and abs(f_num - t_num) == 11:
        return "wheel neighbour"
    if f_num == t_num and f_let == opposite:
        return "major/minor swap"
    return "diagonal energy boost"


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
    Скрейпить Beatport charts через Playwright + stealth.
    Старые /genre/*/top-100 — 404. Новый эндпоинт: /charts.
    Возвращает DJ charts (плейлисты), не отдельные треки.
    """
    tracks = _run_playwright_scraper("beatport", genre)
    
    # Конвертируем в единый формат
    result = []
    for t in tracks:
        result.append({
            "artist":        t.get("artist", "Various"),
            "track":         t.get("track", ""),
            "bpm":           0,
            "camelot":       "",
            "category":      "Mainstream",
            "source_url":    t.get("source_url", ""),
            "youtube_url":   "",
            "energy_markers": [],
            "support_score": t.get("support_score", 5),
            "reason":        t.get("reason", f"Beatport chart: {genre}"),
        })
    
    print(f"  Beatport: {len(result)} charts (через Playwright)")
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

def main():
    parser = argparse.ArgumentParser(
        description="Детерминированный поиск треков для autodj-mixer"
    )
    parser.add_argument("--genre",    required=True)
    parser.add_argument("--bpm",      type=int, default=0,
                        help="Целевой BPM (или используй --bpm-min/--bpm-max)")
    parser.add_argument("--bpm-min",  type=int, default=0)
    parser.add_argument("--bpm-max",  type=int, default=0)
    parser.add_argument("--camelot",  required=True)
    parser.add_argument("--count",    type=int, required=True)
    parser.add_argument("--region",   default="",
                        help="Регион для тегов (Bandcamp/Discogs)")
    parser.add_argument("--country",  default="",
                        help="Страна Discogs country filter (France, Germany…)")
    parser.add_argument("--years",    default="")
    parser.add_argument("--out",      default="curator_candidates.json")
    parser.add_argument("--urls-out", default="")
    parser.add_argument("--style",    default="")
    parser.add_argument("--bpm-tolerance", type=int, default=4)
    parser.add_argument("--pool-factor",   type=int, default=3,
                        help="Собрать pool_factor×count кандидатов перед фильтром")
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--no-approve", action="store_true",
                        help="Не останавливаться на апруве плейлиста")
    args = parser.parse_args()

    # ── Диапазон BPM ──────────────────────────────────────────────
    if args.bpm_min and args.bpm_max:
        bpm_center = (args.bpm_min + args.bpm_max) // 2
        bpm_tolerance = (args.bpm_max - args.bpm_min) // 2
    elif args.bpm:
        bpm_center    = args.bpm
        bpm_tolerance = args.bpm_tolerance
    else:
        print("ОШИБКА: укажи --bpm или --bpm-min + --bpm-max")
        sys.exit(1)

    # ── Годы ──────────────────────────────────────────────────────
    current_year = datetime.now().year
    years = (
        [int(y.strip()) for y in args.years.split(",")]
        if args.years else [current_year, current_year - 1]
    )

    print(f"\n{'═'*55}")
    print(f" autodj-mixer Curator v4")
    print(f" Жанр:    {args.genre}")
    print(f" BPM:     {bpm_center}±{bpm_tolerance}"
          + (f"  ({args.bpm_min}–{args.bpm_max})" if args.bpm_min else ""))
    print(f" Camelot: {args.camelot}")
    print(f" Нужно:   {args.count} треков  |  пул: {args.pool_factor}×")
    print(f" Годы:    {years}"
          + (f"  |  Страна: {args.country}" if args.country else "")
          + (f"  |  Регион: {args.region}" if args.region else ""))
    print()

    try:
        compatible_keys = get_compatible_keys(args.camelot)
    except ValueError as e:
        print(f"ОШИБКА: {e}"); sys.exit(1)

    print(f" Совместимые ключи: {sorted(compatible_keys)}\n")

    # ════════════════════════════════════════════════════════════
    # ШАГ 1: СБОР ПУЛА (pool_factor × count)
    # ════════════════════════════════════════════════════════════
    print("═══ ШАГ 1: Сбор пула ═══")

    print("─── 1001Tracklists (прокси) ───")
    raw_pool = tag_src(fetch_1001tracklists(args.genre, years), "1001Tracklists")

    print("─── Discogs API ───────────────")
    raw_pool += tag_src(fetch_discogs(
        args.genre, years,
        region=args.region, country=args.country,
        pool_factor=args.pool_factor, target_count=args.count
    ), "Discogs")

    print("─── Beatport Charts ───────────")
    raw_pool += tag_src(fetch_beatport_charts(args.genre, years), "Beatport")

    print("─── Beatport Chart Tracks (BPM/Camelot) ───")
    bp_tracks = _run_playwright_scraper("beatport-tracks", args.genre)
    print(f"  Beatport треки: {len(bp_tracks)} шт (с BPM/Camelot)")
    raw_pool += tag_src(bp_tracks, "Beatport")

    if args.region or args.country:
        print(f"─── Bandcamp [{args.region or args.country}] ───")
        raw_pool += tag_src(fetch_bandcamp_underground(
            args.genre, args.region or args.country
        ), "Bandcamp")

    print(f"\n Пул: {len(raw_pool)} треков до фильтра\n")

    # ════════════════════════════════════════════════════════════
    # ШАГ 2: ОБОГАЩЕНИЕ BPM/Camelot через Tunebat (Playwright)
    # ════════════════════════════════════════════════════════════
    print("═══ ШАГ 2: Обогащение BPM/Camelot (Tunebat Playwright) ═══")

    # Дедупликация пула перед обогащением (со слиянием провенанса)
    seen_dedup: dict[str, dict] = {}
    deduped = []
    for track in raw_pool:
        dk = dedup_key(track["artist"], track["track"])
        if dk not in seen_dedup:
            seen_dedup[dk] = track
            deduped.append(track)
        else:
            merge_provenance(seen_dedup[dk], track)

    # Выделяем треки, которым нужно обогащение
    need_enrich = [t for t in deduped if not t.get("bpm") or not t.get("camelot")]

    if not need_enrich:
        print("  Все треки уже имеют BPM/Camelot — пропуск")
        enriched_pool = deduped
    elif len(deduped) > TUNEBAT_MAX_POOL:
        print(f"  Пул {len(deduped)} > {TUNEBAT_MAX_POOL} → Tunebat пропущен")
        enriched_pool = deduped
    else:
        print(f"  Нуждаются в обогащении: {len(need_enrich)}/{len(deduped)} треков")

        # Batch-обогащение через Playwright (один браузер)
        try:
            from playwright_scraper import enrich_tracks_via_tunebat
            enriched_tracks = enrich_tracks_via_tunebat(need_enrich)

            # Собираем enriched_pool: треки с обогащёнными + те, у кого уже были данные
            enriched_by_key = {}
            for t in enriched_tracks:
                dk = dedup_key(t["artist"], t["track"])
                enriched_by_key[dk] = t

            enriched_pool = []
            for t in deduped:
                dk = dedup_key(t["artist"], t["track"])
                if dk in enriched_by_key:
                    et = enriched_by_key[dk]
                    # Дозаполнить BPM/Camelot из Tunebat, сохранив found_in/страну
                    set_field(t, "bpm",     et.get("bpm"),     "Tunebat")
                    set_field(t, "camelot", et.get("camelot"), "Tunebat")
                enriched_pool.append(t)

        except ImportError as e:
            print(f"  Не удалось импортировать playwright_scraper: {e}")
            print("  → Пропускаю Tunebat обогащение")
            enriched_pool = deduped
        except Exception as e:
            print(f"  Ошибка Tunebat обогащения: {e}")
            print("  → Продолжаю с исходными данными")
            enriched_pool = deduped

    # Считаем, сколько теперь с данными
    has_bpm = sum(1 for t in enriched_pool if t.get("bpm"))
    has_camelot = sum(1 for t in enriched_pool if t.get("camelot"))
    print(f"  После обогащения: BPM у {has_bpm}/{len(enriched_pool)}, Camelot у {has_camelot}/{len(enriched_pool)}")

    # ════════════════════════════════════════════════════════════
    # ШАГ 3: ФИЛЬТР BPM + Camelot
    # ════════════════════════════════════════════════════════════
    print("\n═══ ШАГ 3: Фильтр BPM/Camelot ═══")

    filtered: list[dict] = []
    for track in enriched_pool:
        if track["bpm"] != 0:
            if abs(track["bpm"] - bpm_center) > bpm_tolerance:
                continue
        if track["camelot"] and track["camelot"] not in compatible_keys:
            continue
        filtered.append(track)

    filtered.sort(
        key=lambda t: (
            bool(t["bpm"] and t["camelot"]),
            t["support_score"]
        ),
        reverse=True
    )

    print(f" После фильтра: {len(filtered)} треков")

    if len(filtered) < args.count:
        print(
            f"⚠  Пул после фильтра меньше нужного ({len(filtered)}/{args.count}). "
            f"Попробуй: --bpm-tolerance {bpm_tolerance + 2} или --pool-factor {args.pool_factor + 1}"
        )

    # ════════════════════════════════════════════════════════════
    # ШАГ 4: ВЕРИФИКАЦИЯ через yt-dlp (count + 2 запаса)
    # ════════════════════════════════════════════════════════════
    print("\n═══ ШАГ 4: Верификация yt-dlp ═══")

    target = args.count + 2   # +2 запаса на случай браковки
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

        # Camelot relation в reason
        if track.get("camelot"):
            rel = camelot_relation(args.camelot, track["camelot"])
            if rel not in track.get("reason", ""):
                track["reason"] = track.get("reason", "") + f"; {track['camelot']} = {rel}"

        verified.append(track)
        print(
            f"  [{len(verified)}/{target}] ✓  "
            f"{track['artist']} — {track['track']} "
            f"({track['bpm'] or '?'} BPM, {track['camelot'] or '?'})\n"
        )

    # ════════════════════════════════════════════════════════════
    # ШАГ 5: АПРУВ плейлиста (если не --no-approve)
    # ════════════════════════════════════════════════════════════
    final: list[dict] = []

    if args.no_approve or not sys.stdin.isatty():
        final = verified[:args.count]
    else:
        print("\n═══ ШАГ 5: Апрув плейлиста ═══")
        print(format_approval_table(verified, args.camelot))
        print(f"{'─'*55}")
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
                            if i not in reject_idxs and i >= args.count]
            final = kept[:args.count]

            if len(final) < args.count:
                print(
                    f"⚠  После удаления {rejected} треков — недостаточно. "
                    f"Запусти снова с --pool-factor {args.pool_factor + 1} для большего буфера."
                )
        else:
            final = verified[:args.count]
            print("  ✓ Принято без изменений")

    # ════════════════════════════════════════════════════════════
    # ШАГ 6: СОХРАНЕНИЕ
    # ════════════════════════════════════════════════════════════
    print(f"\n{'═'*55}")
    print(f"Итого: {len(final)} треков из {args.count} запрошенных")

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
