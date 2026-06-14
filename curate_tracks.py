#!/usr/bin/env python3
"""
curate_tracks.py — детерминированный поиск треков для autodj-mixer.
Без LLM. Каждый трек верифицирован через yt-dlp перед выдачей.

Использование:
  python3 curate_tracks.py --genre "melodic techno" --bpm 132 --camelot 8A --count 12
  python3 curate_tracks.py --genre "melodic techno" --bpm 132 --camelot 8A --count 12 \
    --region France --years 2025,2026 --out curator_candidates.json --urls-out urls.txt
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional

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

DURATION_MIN = 180   # 3 мин — отсекает тизеры
DURATION_MAX = 660   # 11 мин — отсекает DJ-сеты и час-миксы

# Платформы для пошуку (в порядку пріоритету)
SEARCH_PLATFORMS = [
    {"prefix": "ytsearch", "name": "YouTube"},
    {"prefix": "scsearch", "name": "SoundCloud"},
]


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
                    "--print", "%(url)s\t%(title)s\t%(uploader)s\t%(duration)s",
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

            # Для SoundCloud duration може бути 0 — пропускаємо перевірку
            if duration and not (DURATION_MIN <= duration <= DURATION_MAX):
                continue

            if title_matches(artist, track, title, uploader):
                return {"url": url, "title": title, "uploader": uploader, "source": name}

        # Якщо на YouTube не знайшли — пробуємо SoundCloud
        print(f"  {name}: не знайдено, пробую іншу платформу...")

    return None


# ─── Источник 1: Beatport Charts ─────────────────────────────────────────────

def fetch_beatport_charts(genre: str, years: list[int]) -> list[dict]:
    """Скрейпить Beatport top-100 для жанра."""
    slug = BEATPORT_GENRE_SLUGS.get(genre.lower(), genre.lower().replace(" ", "-"))
    url = f"https://www.beatport.com/genre/{slug}/top-100"
    tracks = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Beatport хранит данные в JSON внутри <script id="__NEXT_DATA__">
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script_tag:
            print(f"  Beatport: не найден __NEXT_DATA__ для {slug}")
            return []

        data = json.loads(script_tag.string)
        # путь к трекам в Beatport Next.js payload
        track_list = (
            data.get("props", {})
                .get("pageProps", {})
                .get("dehydratedState", {})
                .get("queries", [{}])[0]
                .get("state", {})
                .get("data", {})
                .get("results", [])
        )

        for item in track_list:
            try:
                release_year = int(
                    item.get("release_date", "0000")[:4]
                )
                if years and release_year not in years:
                    continue

                raw_key = item.get("key", {})
                key_str = (
                    f"{raw_key.get('letter', '')} "
                    f"{'maj' if raw_key.get('chord') == 'major' else 'min'}"
                ).strip()
                camelot = KEY_TO_CAMELOT.get(key_str, "")

                bpm = item.get("bpm") or 0
                artists = ", ".join(
                    a.get("name", "") for a in item.get("artists", [])
                )
                track_name = item.get("name", "")
                source_url = f"https://www.beatport.com/track/{item.get('slug', '')}/{item.get('id', '')}"

                if artists and track_name and bpm and camelot:
                    tracks.append({
                        "artist": artists,
                        "track": track_name,
                        "bpm": int(bpm),
                        "camelot": camelot,
                        "category": "Mainstream",
                        "source_url": source_url,
                        "youtube_url": "",
                        "energy_markers": [],
                        "support_score": 10,  # базовый балл за попадание в top-100
                        "reason": f"Beatport top-100 {genre} {release_year}",
                    })
            except (KeyError, TypeError, ValueError):
                continue

        time.sleep(SCRAPE_DELAY)

    except requests.RequestException as e:
        print(f"  Beatport scrape error: {e}")

    return tracks


# ─── Источник 2: 1001Tracklists ──────────────────────────────────────────────

def fetch_1001tracklists(genre: str, years: list[int]) -> list[dict]:
    """
    Поиск треков с высоким DJ-саппортом через 1001tracklists.
    Использует search endpoint.
    """
    tracks = []
    year_str = " OR ".join(str(y) for y in years) if years else str(datetime.now().year)
    query = f"{genre} {year_str}"
    url = f"https://www.1001tracklists.com/search/track/?q={requests.utils.quote(query)}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        rows = soup.select("div.tlpItem, div.trk-item, tr.search-result")
        for row in rows[:30]:  # первые 30 результатов
            try:
                # Извлечь artist/track из типичных селекторов 1001TL
                artist_el = row.select_one(".artist, .artistName, td.artist")
                track_el = row.select_one(".trackName, .title, td.trackname")
                count_el = row.select_one(".playedByCount, .support-count, .tlCount")

                if not artist_el or not track_el:
                    continue

                artist = artist_el.get_text(strip=True)
                track = track_el.get_text(strip=True)
                support_score = 0
                if count_el:
                    nums = re.findall(r'\d+', count_el.get_text())
                    if nums:
                        support_score = int(nums[0])

                if artist and track:
                    tracks.append({
                        "artist": artist,
                        "track": track,
                        "bpm": 0,       # нет BPM на 1001TL — заполним после верификации
                        "camelot": "",  # нет Key на 1001TL
                        "category": "Mainstream",
                        "source_url": url,
                        "youtube_url": "",
                        "energy_markers": [],
                        "support_score": support_score,
                        "reason": f"1001TL: {support_score} played by; {genre}",
                    })
            except (AttributeError, ValueError):
                continue

        time.sleep(SCRAPE_DELAY)

    except requests.RequestException as e:
        print(f"  1001TL scrape error: {e}")

    # Треки без BPM/Key нельзя фильтровать — они будут пропущены фильтром.
    # Возвращаем только те у кого support_score > 0 (реальный саппорт)
    return [t for t in tracks if t["support_score"] > 0]


# ─── Источник 3: Resident Advisor Charts ─────────────────────────────────────

def fetch_ra_charts(genre: str) -> list[dict]:
    """Скрейпить RA genre charts — треки с редакционным весом."""
    tracks = []
    # RA использует slug типа "melodic-techno" или "techno"
    slug = genre.lower().replace(" ", "-")
    url = f"https://ra.co/charts/genre/{slug}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # RA хранит данные в Next.js __NEXT_DATA__
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script_tag:
            return []

        data = json.loads(script_tag.string)
        chart_tracks = (
            data.get("props", {})
                .get("pageProps", {})
                .get("data", {})
                .get("chartTracks", [])
        )

        for item in chart_tracks:
            try:
                artist = item.get("artist", {}).get("name", "")
                track = item.get("title", "")
                if artist and track:
                    tracks.append({
                        "artist": artist,
                        "track": track,
                        "bpm": 0,
                        "camelot": "",
                        "category": "Mainstream",
                        "source_url": f"https://ra.co{item.get('slug', '')}",
                        "youtube_url": "",
                        "energy_markers": [],
                        "support_score": 8,  # базовый балл за RA chart
                        "reason": f"RA chart: {genre}",
                    })
            except (KeyError, TypeError):
                continue

        time.sleep(SCRAPE_DELAY)

    except requests.RequestException as e:
        print(f"  RA scrape error: {e}")

    return tracks


# ─── Источник 4: Bandcamp Underground ────────────────────────────────────────

def fetch_bandcamp_underground(genre: str, region: str) -> list[dict]:
    """Скрейпить Bandcamp tag page для локального андеграунда."""
    tracks = []
    tag = genre.lower().replace(" ", "-")
    url = f"https://bandcamp.com/tag/{tag}?tab=all_releases&s=pop&p=0"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        items = soup.select("li.music-grid-item, div.discover-item")
        for item in items[:40]:
            try:
                title_el = item.select_one("p.title, .track-title, .itemTitle")
                artist_el = item.select_one("p.artistName, .artist-name, .itemArtist")
                link_el = item.select_one("a")

                if not title_el or not artist_el:
                    continue

                track = title_el.get_text(strip=True)
                artist = artist_el.get_text(strip=True)
                source_url = link_el["href"] if link_el and link_el.get("href") else ""

                # Проверить регион в URL или тексте (мягко)
                region_match = region.lower() in (artist + track + source_url).lower()

                tracks.append({
                    "artist": artist,
                    "track": track,
                    "bpm": 0,
                    "camelot": "",
                    "category": "Local Underground",
                    "source_url": source_url,
                    "youtube_url": "",
                    "energy_markers": [],
                    "support_score": 0,
                    "reason": (
                        f"Bandcamp {genre} tag"
                        + (f"; {region} scene" if region_match else "")
                        + "; Hidden Gem"
                    ),
                })
            except (AttributeError, KeyError):
                continue

        time.sleep(SCRAPE_DELAY)

    except requests.RequestException as e:
        print(f"  Bandcamp scrape error: {e}")

    return tracks


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
    parser.add_argument("--genre", required=True, help='Жанр: "melodic techno"')
    parser.add_argument("--bpm", type=int, required=True, help="Целевой BPM: 132")
    parser.add_argument("--camelot", required=True, help="Целевой ключ: 8A")
    parser.add_argument("--count", type=int, required=True, help="Сколько треков нужно")
    parser.add_argument("--region", default="", help="Регион андеграунда: France, Ukraine")
    parser.add_argument(
        "--years", default="",
        help="Годы через запятую: 2025,2026 (дефолт: текущий + прошлый)"
    )
    parser.add_argument("--out", default="curator_candidates.json")
    parser.add_argument("--bpm-tolerance", type=int, default=4)
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Пропустить yt-dlp верификацию (для дебага)"
    )
    parser.add_argument(
        "--style", default="",
        help='Стиль музыки: "French Touch", "melodic techno" (добавляется в каждый трек)'
    )
    parser.add_argument(
        "--urls-out", default="",
        help='Сохранить список YouTube URL в текстовый файл для yt_download.py --url-file'
    )
    args = parser.parse_args()

    # Парсинг лет
    current_year = datetime.now().year
    if args.years:
        years = [int(y.strip()) for y in args.years.split(",")]
    else:
        years = [current_year, current_year - 1]

    print(f"\n{'─'*50}")
    print(f" autodj-mixer Curator")
    print(f" Жанр: {args.genre} | BPM: {args.bpm}±{args.bpm_tolerance} | "
          f"Camelot: {args.camelot} | Стиль: {args.style or '(не указан)'} | Нужно: {args.count} треков")
    print(f" Годы: {years}" + (f" | Регион: {args.region}" if args.region else ""))
    print()

    try:
        compatible_keys = get_compatible_keys(args.camelot)
    except ValueError as e:
        print(f"ОШИБКА: {e}")
        sys.exit(1)

    print(f" Совместимые ключи: {sorted(compatible_keys)}\n")

    found = []
    seen = set()

    # Источники в порядке приоритета
    print("─── Источник 1: Beatport Charts ───")
    sources = [fetch_beatport_charts(args.genre, years)]

    print("─── Источник 2: 1001Tracklists ────")
    sources.append(fetch_1001tracklists(args.genre, years))

    print("─── Источник 3: Resident Advisor ──")
    sources.append(fetch_ra_charts(args.genre))

    if args.region:
        print(f"─── Источник 4: Bandcamp [{args.region}] ──")
        sources.append(fetch_bandcamp_underground(args.genre, args.region))

    print()

    for source_tracks in sources:
        for track in source_tracks:
            if len(found) >= args.count:
                break

            dedup_key = f"{track['artist'].lower().strip()}|{track['track'].lower().strip()}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # ── BPM фильтр ──────────────────────────────────────────────────
            if track["bpm"] != 0:
                if abs(track["bpm"] - args.bpm) > args.bpm_tolerance:
                    continue

            # ── Camelot фильтр ───────────────────────────────────────────────
            if track["camelot"] and track["camelot"] not in compatible_keys:
                continue

            # ── yt-dlp верификация ───────────────────────────────────────────
            print(f"Проверяю: {track['artist']} - {track['track']}")

            if args.no_verify:
                track["youtube_url"] = f"ytsearch1:{track['artist']} - {track['track']}"
            else:
                yt = verify_and_resolve_url(track["artist"], track["track"])
                if yt is None:
                    print(f"  ✗ не верифицирован — пропуск")
                    continue
                track["youtube_url"] = yt["url"]
                print(f"  ✓ {yt.get('source', 'YouTube')}: {yt['title'][:60]}")

                # Если BPM/Key/стиль неизвестны — поиск через Beatport search
                if track["bpm"] == 0 or not track["camelot"] or (args.style and not track.get("style")):
                    enriched_bpm, enriched_key, enriched_style = search_beatport_track(
                        track["artist"], track["track"]
                    )
                    if track["bpm"] == 0 and enriched_bpm:
                        track["bpm"] = enriched_bpm
                        print(f"  ℹ Beatport BPM: {enriched_bpm}")
                    if not track["camelot"] and enriched_key:
                        track["camelot"] = enriched_key
                        print(f"  ℹ Beatport Key: {enriched_key}")
                    if enriched_style and (not track.get("style") or args.style):
                        track["style"] = enriched_style
                        print(f"  ℹ Beatport стиль: {enriched_style}")

                # BPM/Key — nice to have, визначаються пізніше A1F аналізатором
                if track["bpm"] == 0 or not track["camelot"]:
                    yt_bpm, yt_key = enrich_from_youtube_description(track["youtube_url"])
                    if track["bpm"] == 0 and yt_bpm:
                        track["bpm"] = yt_bpm
                        print(f"  ℹ YouTube BPM: {yt_bpm}")
                    if not track["camelot"] and yt_key:
                        track["camelot"] = yt_key
                        print(f"  ℹ YouTube Key: {yt_key}")

            # ── Додати style ────────────────────────────────────────────
            if args.style and not track.get("style"):
                track["style"] = args.style

            # ── Додати гармонічне відношення в reason (якщо є camelot) ──
            if track.get("camelot"):
                relation = camelot_relation(args.camelot, track["camelot"])
                if relation not in track.get("reason", ""):
                    track["reason"] = track.get("reason", "") + f"; {track['camelot']} = {relation}"

            found.append(track)
            print(
                f"  [{len(found)}/{args.count}] ✓ "
                f"{track['artist']} — {track['track']} "
                f"({track['bpm'] or '?'} BPM, {track['camelot'] or '?'})"
            )
            print()

        if len(found) >= args.count:
            break

    # ── Итог ────────────────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"Готово: {len(found)} треков из {args.count} запрошенных")

    if len(found) < args.count:
        print(
            f"⚠  Набрано меньше чем нужно. "
            f"Попробуй: --bpm-tolerance 6 или другой --camelot"
        )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False, indent=2)

    print(f"Сохранено → {args.out}")

    # ── Сохранить URL-файл для yt_download.py ──
    if args.urls_out:
        with open(args.urls_out, "w", encoding="utf-8") as f:
            for t in found:
                f.write(t["youtube_url"] + "\n")
        print(f"URLs → {args.urls_out}")

    print(f"\nСледующий шаг:")
    if args.urls_out:
        print(f"  python3 yt_download.py --url-file {args.urls_out}")
    else:
        for t in found:
            print(f"  python3 yt_download.py \"{t['youtube_url']}\"")


if __name__ == "__main__":
    main()
