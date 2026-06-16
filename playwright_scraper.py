#!/usr/bin/env python3
"""
Playwright Scraper для autodj-mixer.
Обёртка над Playwright + stealth для обхода Cloudflare/антибот систем.

Статус источников (июнь 2026):
  ✅ Beatport /charts — работает (DJ charts, фильтр по жанру)
  ✅ Tunebat /search — работает (BPM/Camelot из pageModel)
  ⚠️ 1001tracklists — client-side поиск, нужен ввод в поле
  ❌ RA — DataDome, нужен резидентский прокси
  ✅ Bandcamp — data-blob парсинг (если не заблокирован)

Использование:
  export RESIDENTIAL_PROXY="http://user:pass@host:port"  # для RA и сложных блоков
  export SOCKS5_PROXY="socks5://127.0.0.1:40000"         # Cloudflare Warp

  xvfb-run --auto-servernum uv run python3 playwright_scraper.py beatport --genre techno
  xvfb-run --auto-servernum uv run python3 playwright_scraper.py tunebat --artist "Martyn" --track "Broken"
"""

import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

# ─── Конфигурация ─────────────────────────────────────────────────────────────

HUMAN_DELAY_MIN = 800
HUMAN_DELAY_MAX = 2500
PAGE_LOAD_TIMEOUT = 45000
NAVIGATION_WAIT = "domcontentloaded"
MAX_RETRIES = int(os.environ.get("SCRAPER_MAX_RETRIES", "3"))  # свежий браузер + ротация IP на каждую попытку
RETRY_BASE_DELAY = 2.0
XVFB_AVAILABLE = os.system("which xvfb-run >/dev/null 2>&1") == 0


@dataclass
class ScraperResult:
    """Результат скрейпинга."""
    success: bool = False
    data: list[dict] = field(default_factory=list)
    source: str = ""
    page_url: str = ""
    page_title: str = ""
    error: str = ""


# ─── Camelot mapping ──────────────────────────────────────────────────────────

KEY_TO_CAMELOT = {
    "C maj": "8B", "C min": "5A",
    "C# maj": "7B", "C# min": "12A",
    "D maj": "10B", "D min": "7A",
    "D# maj": "3B", "D# min": "2A",
    "E maj": "12B", "E min": "9A",
    "F maj": "7B", "F min": "4A",
    "F# maj": "2B", "F# min": "11A",
    "G maj": "9B", "G min": "6A",
    "G# maj": "4B", "G# min": "1A",
    "A maj": "11B", "A min": "8A",
    "A# maj": "6B", "A# min": "3A",
    "B maj": "1B", "B min": "10A",
}

# Beatport genre slugs для /charts (не /genre/*/top-100 — они 404)
BEATPORT_GENRE_SLUGS = {
    "melodic techno": "melodic-house-techno",
    "melodic house": "melodic-house-techno",
    "techno": "techno-peak-time-driving",
    "tech house": "tech-house",
    "deep house": "deep-house",
    "progressive house": "progressive-house",
    "afro house": "afro-house",
    "organic house": "organic-house-downtempo",
    "house": "house",
    "minimal": "minimal",
    "trance": "trance",
    "drum and bass": "drum-and-bass",
    "hard techno": "hard-techno-schranz",
    "electro": "electro",
}

# ═══════════════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ═══════════════════════════════════════════════════════════════════════════════


def log(msg: str) -> None:
    print(f"  [Playwright] {msg}", flush=True)


def human_delay() -> None:
    ms = random.randint(HUMAN_DELAY_MIN, HUMAN_DELAY_MAX)
    time.sleep(ms / 1000.0)


def get_proxy_config() -> Optional[dict]:
    """
    Приоритет: RESIDENTIAL_PROXY > SOCKS5_PROXY > None
    """
    proxy_str = os.environ.get("RESIDENTIAL_PROXY", "")
    if proxy_str:
        log(f"Резидентский прокси: {proxy_str[:30]}...")
        return {"server": proxy_str}
    proxy_str = os.environ.get("SOCKS5_PROXY", "")
    if proxy_str:
        log(f"SOCKS5 прокси: {proxy_str}")
        return {"server": proxy_str}
    return None


def launch_browser(headless: bool = False):
    """Запуск Chromium с stealth."""    
    from playwright.sync_api import sync_playwright
    import playwright_stealth

    pw = sync_playwright().start()
    
    launch_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-blink-features=AutomationControlled",
    ]
    
    if not headless and "DISPLAY" not in os.environ and XVFB_AVAILABLE:
        log("DISPLAY не найден — используйте xvfb-run")
    
    proxy = get_proxy_config()
    browser_kwargs = {"headless": headless, "args": launch_args}
    if proxy:
        browser_kwargs["proxy"] = proxy
    
    browser = pw.chromium.launch(**browser_kwargs)
    
    page = browser.new_page(
        viewport={
            "width": random.randint(1280, 1440),
            "height": random.randint(800, 900),
        },
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="en",
    )
    
    # Stealth
    try:
        stealth = playwright_stealth.Stealth()
        stealth.apply_stealth_sync(page)
        log("Stealth активирован")
    except Exception as e:
        log(f"Stealth error: {e}")
    
    return pw, browser, page


def close_browser(pw, browser) -> None:
    try:
        browser.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass


def safe_goto(page, url: str) -> bool:
    try:
        resp = page.goto(url, wait_until=NAVIGATION_WAIT, timeout=PAGE_LOAD_TIMEOUT)
        status = resp.status if resp else 0
        if status and status >= 400:
            log(f"HTTP {status} для {url}")
            return False
        human_delay()
        return True
    except Exception as e:
        log(f"Ошибка перехода: {e}")
        return False


_BLOCK_SIGNATURES = [
    ("just a moment",            "cloudflare"),
    ("checking your browser",    "cloudflare"),
    ("cf-browser-verification",  "cloudflare_verify"),
    ("verify you are human",     "cloudflare_challenge"),
    ("geo.captcha-delivery.com", "datadome"),
    ("unusual traffic",          "google_ratelimit"),
    ("/recaptcha/",              "recaptcha"),
    ("hcaptcha.com",             "hcaptcha"),
    ("access denied",            "access_denied"),
]


def detect_block(html: str, title: str = "") -> Optional[str]:
    """
    Определить тип антибот-блокировки по HTML/заголовку. Чистая функция (тестируема).
    Возвращает строку-тип или None если блокировки не обнаружено.
    """
    h = (html or "").lower()
    t = (title or "").lower()
    for sig, kind in _BLOCK_SIGNATURES:
        if sig in h or sig in t:
            return kind
    if "403" in t:
        return "http_403"
    if "404" in t and "error" in t:
        return "http_404"
    return None


def page_is_blocked(page) -> Optional[str]:
    return detect_block(page.content()[:4000], page.title())


def rotate_ip() -> bool:
    """
    Сменить IP перед повторной попыткой после блокировки.
    Residential-прокси с ротацией меняет IP сам на новом соединении (новый
    браузер) — тогда просто пауза. Иначе пробуем Cloudflare Warp reconnect.
    Defensive: при отсутствии warp-cli просто ждёт. Возвращает True, если смена
    IP реально предпринята.
    """
    import subprocess
    if os.environ.get("RESIDENTIAL_PROXY"):
        log("Ротация IP: residential proxy сменит IP на новом соединении")
        time.sleep(RETRY_BASE_DELAY)
        return True
    try:
        subprocess.run(["warp-cli", "disconnect"], capture_output=True, timeout=10)
        time.sleep(1.5)
        subprocess.run(["warp-cli", "connect"], capture_output=True, timeout=10)
        time.sleep(2.0)
        log("Ротация IP: Warp переподключён")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log("Ротация IP недоступна (нет warp-cli) — пауза")
        time.sleep(RETRY_BASE_DELAY)
        return False


def retry_scrape(url: str, scrape_fn, max_retries: int = MAX_RETRIES) -> ScraperResult:
    """Выполнить скрейпинг с retry (каждая попытка в отдельном процессе)."""
    for attempt in range(max_retries):
        pw, browser, page = None, None, None
        try:
            pw, browser, page = launch_browser(headless=False)
            log(f"Попытка {attempt + 1}/{max_retries}: {url}")

            if not safe_goto(page, url):
                close_browser(pw, browser)
                if attempt < max_retries - 1:
                    rotate_ip()
                    time.sleep(RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1))
                continue

            block = page_is_blocked(page)
            if block:
                log(f"БЛОКИРОВКА: {block}")
                close_browser(pw, browser)
                if attempt < max_retries - 1:
                    rotate_ip()
                    time.sleep(RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1))
                continue

            result = scrape_fn(page, url)
            result.success = True
            result.page_url = page.url
            result.page_title = page.title()

            close_browser(pw, browser)
            return result

        except Exception as e:
            log(f"Ошибка: {e}")
            close_browser(pw, browser)
            if attempt < max_retries - 1:
                rotate_ip()
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1))

    return ScraperResult(error=f"Все {max_retries} попыток исчерпаны")


# ═══════════════════════════════════════════════════════════════════════════════
# Источник 0: Tunebat (BPM/Camelot поиск)
# ═══════════════════════════════════════════════════════════════════════════════


def _extract_tunebat_page_model(page) -> Optional[dict]:
    """
    Извлекает pageModel из ReactDOM.hydrate().
    pageModel — JSON-строка внутри JS-строки, \\u0022 вместо кавычек.
    Использует page.content() (raw HTML) и Python regex/json.
    """
    import json as _json
    
    html = page.content()
    
    # pageModel:"{...}" — захватываем всё между кавычками
    match = re.search(r'pageModel"\s*:\s*"([^"]+)"', html)
    if not match:
        return None
    
    raw = match.group(1)
    # raw = {\\u0022searchResult\\u0022:...}
    # json.loads(f'"{raw}"') декодирует \\u0022 → "
    try:
        decoded = _json.loads(f'"{raw}"')
        return _json.loads(decoded)
    except (json.JSONDecodeError, ValueError) as e:
        log(f"pageModel parse error: {e}")
        log(f"Raw (first 200): {raw[:200]}")
        return None


def scrape_tunebat(page, url: str) -> ScraperResult:
    """
    Парсит Tunebat search results.
    URL: https://www.tunebat.com/search?q=ARTIST+TRACK
    Извлекает BPM, Camelot, Key из pageModel JSON.
    """
    result = ScraperResult(source="tunebat")
    
    # Ждём React render
    time.sleep(5)
    human_delay()
    
    # Проверка блокировки
    block = page_is_blocked(page)
    if block:
        result.error = f"Blocked: {block}"
        return result
    
    # Извлекаем pageModel
    page_model = _extract_tunebat_page_model(page)
    if not page_model:
        log("pageModel не найден")
        result.error = "pageModel not found"
        return result
    
    search_result = page_model.get("searchResult", {})
    items = search_result.get("items", [])
    
    log(f"Найдено {len(items)} результатов на Tunebat")
    
    for item in items:
        if not isinstance(item, dict):
            continue
        
        name = item.get("n", "")
        artists = item.get("as", [])
        if isinstance(artists, list):
            artist_str = ", ".join(artists)
        else:
            artist_str = str(artists) if artists else ""
        
        bpm = item.get("b", 0) or 0
        camelot = item.get("c", "") or ""
        key_name = item.get("k", "") or ""
        popularity = item.get("p", 0) or 0
        
        if name and bpm:
            result.data.append({
                "artist": artist_str,
                "track": name,
                "bpm": int(round(bpm)),
                "camelot": camelot,
                "key": key_name,
                "popularity": popularity,
            })
    
    if result.data:
        result.success = True
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Источник 1: Beatport Charts
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_beatport(page, url: str) -> ScraperResult:
    # ... (unchanged, omitted for brevity in this test)
    """
    Парсит Beatport /charts.
    Beatport переехал на V4 API. Старые /genre/*/top-100 — 404.
    /charts показывает DJ charts, фильтр по жанру через genre slug.
    """
    result = ScraperResult(source="beatport")
    
    if "/charts" in url:
        data_str = page.evaluate("() => { const el = document.querySelector('script#__NEXT_DATA__'); return el ? el.textContent : null; }")
        if not data_str:
            log("__NEXT_DATA__ не найден на странице charts")
            return result
        
        try:
            data = json.loads(data_str)
            queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
            
            if len(queries) < 2:
                log("Queries меньше 2")
                return result
            
            modules = queries[1].get("state", {}).get("data", {}).get("modules", [])
            if not modules:
                log("Модули не найдены")
                return result
            
            chart_items = modules[0].get("module_items", [])
            log(f"Найдено {len(chart_items)} charts")
            
            from urllib.parse import parse_qs, urlparse
            parsed_url = urlparse(url)
            genre = parse_qs(parsed_url.query).get("genre", ["all"])[0]
            
            log(f"Фильтр по жанру: '{genre}'")
            
            for item in chart_items:
                if not isinstance(item, dict):
                    continue
                chart = item.get("item")
                if not isinstance(chart, dict):
                    continue
                    
                genres = [g.get("name", "").lower() for g in chart.get("genres", []) if isinstance(g, dict)]
                
                if genre and genre.lower() != "all":
                    genre_lower = genre.lower()
                    genre_match = False
                    for g in genres:
                        if genre_lower in g or g in genre_lower:
                            genre_match = True
                            break
                        genre_words = genre_lower.replace("/", " ").replace("-", " ").split()
                        if all(w in g for w in genre_words):
                            genre_match = True
                            break
                    if not genre_match:
                        continue
                
                name = chart.get("name", "")
                track_count = chart.get("track_count", 0)
                chart_url = chart.get("url", "")
                chart_id = chart.get("id", "")
                artist_name = chart.get("artist", {})
                if isinstance(artist_name, dict):
                    artist_name = artist_name.get("name", "")
                
                if name and track_count > 0:
                    result.data.append({
                        "artist": artist_name or "Various",
                        "track": name,
                        "bpm": 0,
                        "camelot": "",
                        "category": "Mainstream",
                        "source_url": f"https://www.beatport.com/chart/{chart.get('slug', '')}/{chart_id}",
                        "youtube_url": "",
                        "energy_markers": [],
                        "support_score": track_count,
                        "reason": f"Beatport chart: {name} ({track_count} tracks)",
                        "track_count": track_count,
                        "chart_id": chart_id,
                        "genres": genres,
                    })
            
            log(f"Отфильтровано: {len(result.data)} charts для жанра '{genre}'")
            
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            log(f"Ошибка парсинга Beatport __NEXT_DATA__: {e}")
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Источник 2: 1001Tracklists
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_1001tl(page, url: str) -> ScraperResult:
    # ... (unchanged)
    result = ScraperResult(source="1001tracklists")
    
    log("Выполняю поиск на 1001TL...")
    search_performed = page.evaluate("""() => {
        const selectors = [
            'input[type="text"]', 'input[name="q"]', 'input.search',
            '.search input', 'input[placeholder*="search" i]',
            'input[placeholder*="track" i]', '#q', '#search'
        ];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el && el.offsetParent !== null) {
                return {found: true, selector: sel, placeholder: el.placeholder || ''};
            }
        }
        return {found: false};
    }""")
    
    if not search_performed.get("found"):
        log("Поле поиска не найдено")
        return result
    
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(url)
    query = parse_qs(parsed.query).get("q", ["techno"])[0]
    
    page.fill(search_performed["selector"], query)
    human_delay()
    page.press(search_performed["selector"], "Enter")
    time.sleep(3)
    human_delay()
    
    tracklist_urls = page.evaluate("""() => {
        const links = document.querySelectorAll('a[href*="/tracklist/"]');
        return Array.from(links).slice(0, 20).map(a => a.href);
    }""")
    
    log(f"Найдено {len(tracklist_urls)} tracklist'ов")
    
    if not tracklist_urls:
        return result
    
    all_tracks = []
    for i, tl_url in enumerate(tracklist_urls):
        log(f"Парсю tracklist {i+1}/{len(tracklist_urls)}: {tl_url[:60]}...")
        try:
            page.goto(tl_url, wait_until=NAVIGATION_WAIT, timeout=PAGE_LOAD_TIMEOUT)
            human_delay()
            
            tracks = _parse_1001tl_tracklist(page)
            log(f"  → {len(tracks)} треков")
            all_tracks.extend(tracks)
        except Exception as e:
            log(f"  → ошибка: {e}")
    
    result.data = all_tracks
    log(f"Всего: {len(all_tracks)} треков из {len(tracklist_urls)} tracklist'ов")
    return result


def _parse_1001tl_tracklist(page) -> list[dict]:
    return page.evaluate("""() => {
        const trackSpans = document.querySelectorAll(
            '.trackValue, span.notranslate.redTxt, [id^="tr_"], ' +
            '.bCont .fontL span[translate="no"]'
        );
        const results = [];
        const seen = new Set();
        
        trackSpans.forEach(span => {
            const text = span.textContent.trim();
            if (!text || text === '-' || seen.has(text)) return;
            seen.add(text);
            
            if (text === 'ID - ID') return;
            
            const parts = text.split(' - ');
            if (parts.length >= 2) {
                results.push({
                    artist: parts[0].trim(),
                    track: parts.slice(1).join(' - ').trim(),
                    bpm: 0,
                    camelot: '',
                    category: 'Mainstream',
                    source_url: window.location.href,
                    youtube_url: '',
                    energy_markers: [],
                    support_score: 5,
                    reason: '1001TL tracklist',
                });
            }
        });
        
        return results;
    }""")


# ═══════════════════════════════════════════════════════════════════════════════
# Источник 3: RA (Resident Advisor)
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_ra(page, url: str) -> ScraperResult:
    result = ScraperResult(source="resident_advisor")
    
    if "geo.captcha-delivery.com" in page.content()[:2000]:
        log("DataDome captcha — нужен резидентский прокси! Установи RESIDENTIAL_PROXY")
        result.error = "DataDome captcha requires residential proxy"
        return result
    
    data_str = page.evaluate("() => { const el = document.querySelector('script#__NEXT_DATA__'); return el ? el.textContent : null; }")
    if data_str:
        try:
            data = json.loads(data_str)
            for path in [
                ["props", "pageProps", "data", "chartTracks"],
                ["props", "pageProps", "tracks"],
                ["props", "pageProps", "chart", "tracks"],
            ]:
                tracks_data = data
                for key in path:
                    tracks_data = tracks_data.get(key, {}) if isinstance(tracks_data, dict) else {}
                if isinstance(tracks_data, list) and tracks_data:
                    for item in tracks_data:
                        artist = item.get("artist", {}).get("name", item.get("artist_name", ""))
                        track = item.get("title", item.get("track_name", ""))
                        if artist and track:
                            result.data.append({
                                "artist": artist,
                                "track": track,
                                "bpm": 0,
                                "camelot": "",
                                "category": "Mainstream",
                                "source_url": url,
                                "youtube_url": "",
                                "energy_markers": [],
                                "support_score": 8,
                                "reason": "RA chart",
                            })
                    if result.data:
                        log(f"RA: {len(result.data)} треков из __NEXT_DATA__")
                        return result
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log(f"RA parse error: {e}")
    
    log("RA: данные не найдены (возможно, структура изменилась)")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Источник 4: Bandcamp
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_bandcamp(page, url: str) -> ScraperResult:
    result = ScraperResult(source="bandcamp")
    
    title = page.title()
    if "Client Challenge" in title or "just a moment" in title.lower():
        log("Bandcamp: Cloudflare challenge — нужен SOCKS5 прокси")
        result.error = "Cloudflare challenge"
        return result
    
    albums = page.evaluate("""() => {
        const links = document.querySelectorAll('a[href*="/album/"]');
        return Array.from(links).slice(0, 40).map(a => {
            const text = a.innerText.trim();
            const lines = text.split(String.fromCharCode(10)).map(l => l.trim()).filter(l => l);
            let title = lines[0] || '';
            let artist = '';
            for (const line of lines) {
                if (line.startsWith('by ')) {
                    artist = line.slice(3).trim();
                    break;
                }
            }
            if (!artist && lines.length > 1) artist = lines[1];
            return { title: title, artist: artist, url: a.href };
        }).filter(a => a.title);
    }""")
    
    for a in albums:
        result.data.append({
            "artist": a["artist"],
            "track": a["title"],
            "bpm": 0,
            "camelot": "",
            "category": "Underground",
            "source_url": a["url"],
            "youtube_url": "",
            "energy_markers": [],
            "support_score": 5,
            "reason": "Bandcamp discover",
        })
    
    log(f"Bandcamp: {len(result.data)} альбомов")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Источник 1b: Beatport Chart Tracks (парсинг треков внутри chart'ов)
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_beatport_tracks(page, url: str) -> ScraperResult:
    result = ScraperResult(source="beatport_tracks")
    
    data_str = page.evaluate("() => { const el = document.querySelector('script#__NEXT_DATA__'); return el ? el.textContent : null; }")
    if not data_str:
        log("__NEXT_DATA__ не найден")
        return result
    
    try:
        data = json.loads(data_str)
        queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        if len(queries) < 2:
            return result
        
        modules = queries[1].get("state", {}).get("data", {}).get("modules", [])
        if not modules:
            return result
        
        chart_items = modules[0].get("module_items", [])
        
        from urllib.parse import parse_qs, urlparse
        parsed_url = urlparse(url)
        genre = parse_qs(parsed_url.query).get("genre", ["all"])[0]
        
        chart_urls = []
        for item in chart_items:
            if not isinstance(item, dict):
                continue
            chart = item.get("item")
            if not isinstance(chart, dict):
                continue
            
            genres = [g.get("name", "").lower() for g in chart.get("genres", []) if isinstance(g, dict)]
            
            if genre and genre.lower() != "all":
                genre_lower = genre.lower()
                genre_match = False
                for g in genres:
                    if genre_lower in g or g in genre_lower:
                        genre_match = True
                        break
                    genre_words = genre_lower.replace("/", " ").replace("-", " ").split()
                    if all(w in g for w in genre_words):
                        genre_match = True
                        break
                if not genre_match:
                    continue
            
            chart_id = chart.get("id", "")
            chart_slug = chart.get("slug", "")
            if chart_id:
                chart_urls.append(f"https://www.beatport.com/chart/{chart_slug}/{chart_id}")
        
        log(f"Найдено {len(chart_urls)} chart'ов для парсинга треков")
        
        all_tracks = []
        for i, chart_url in enumerate(chart_urls[:10]):
            log(f"Парсю chart {i+1}/{min(len(chart_urls), 10)}: {chart_url[:60]}...")
            try:
                page.goto(chart_url, wait_until=NAVIGATION_WAIT, timeout=PAGE_LOAD_TIMEOUT)
                human_delay()
                
                tracks = _parse_beatport_chart_tracks(page, genre)
                log(f"  → {len(tracks)} треков")
                all_tracks.extend(tracks)
            except Exception as e:
                log(f"  → ошибка: {e}")
        
        result.data = all_tracks
        log(f"Всего: {len(all_tracks)} треков из {len(chart_urls[:10])} chart'ов")
        
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        log(f"Ошибка: {e}")
    
    return result


def _parse_beatport_chart_tracks(page, genre: str) -> list[dict]:
    data_str = page.evaluate("() => { const el = document.querySelector('script#__NEXT_DATA__'); return el ? el.textContent : null; }")
    if not data_str:
        return []
    
    try:
        data = json.loads(data_str)
        queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        
        for q in queries:
            qdata = q.get("state", {}).get("data", {})
            if isinstance(qdata, dict):
                results = qdata.get("results", [])
                if results and isinstance(results, list) and len(results) > 0:
                    tracks = []
                    for item in results:
                        try:
                            artists = ", ".join(
                                a.get("name", "") for a in item.get("artists", [])
                            )
                            track_name = item.get("name", "")
                            bpm = item.get("bpm") or 0
                            
                            raw_key = item.get("key", {})
                            key_str = ""
                            if raw_key:
                                key_str = (
                                    f"{raw_key.get('letter', '')} "
                                    f"{'maj' if raw_key.get('chord') == 'major' else 'min'}"
                                ).strip()
                            camelot = KEY_TO_CAMELOT.get(key_str, "")
                            
                            if artists and track_name:
                                tracks.append({
                                    "artist": artists,
                                    "track": track_name,
                                    "bpm": int(bpm),
                                    "camelot": camelot,
                                    "category": "Mainstream",
                                    "source_url": page.url,
                                    "youtube_url": "",
                                    "energy_markers": [],
                                    "support_score": 10,
                                    "reason": f"Beatport chart track: {genre}",
                                })
                        except (KeyError, TypeError, ValueError):
                            continue
                    return tracks
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# Batch Tunebat Enrichment (для curate_tracks)
# ═══════════════════════════════════════════════════════════════════════════════


def enrich_tracks_via_tunebat(tracks: list[dict]) -> list[dict]:
    """
    Batch-обогащение треков через Tunebat в одном браузере.
    Каждый трек — отдельная страница (вкладка), чтобы SPA инициализировалась свежей.
    """
    pw, browser = None, None
    try:
        pw, browser, _ = launch_browser(headless=False)
        
        enriched = 0
        skipped = 0
        
        for track in tracks:
            if track.get("bpm") and track.get("camelot"):
                skipped += 1
                continue
            
            artist = track.get("artist", "")
            track_name = track.get("track", "")
            if not artist or not track_name:
                skipped += 1
                continue
            
            query = f"{artist} {track_name}"
            search_url = f"https://www.tunebat.com/search?q={quote(query)}"
            
            log(f"Tunebat: {artist} — {track_name}")
            
            # Создаём новую страницу (fresh React instance)
            page = browser.new_page(
                viewport={"width": random.randint(1280, 1440), "height": random.randint(800, 900)},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                locale="en",
            )
            
            try:
                resp = page.goto(search_url, wait_until="load", timeout=PAGE_LOAD_TIMEOUT)
                status = resp.status if resp else 0
                if status and status >= 400:
                    log(f"HTTP {status} — пропуск")
                    page.close()
                    continue
            except Exception as e:
                log(f"Ошибка перехода: {e}")
                page.close()
                continue
            
            # Ждём React render
            time.sleep(4)
            human_delay()
            
            # Парсим pageModel
            pm = _extract_tunebat_page_model(page)
            
            # Retry
            if not pm:
                time.sleep(3)
                pm = _extract_tunebat_page_model(page)
            
            if not pm:
                log(f"  pageModel не найден")
                page.close()
                continue
            
            items = pm.get("searchResult", {}).get("items", [])
            if not items:
                log(f"  Нет результатов")
                page.close()
                continue
            
            # Matching logic (same as before)
            import unicodedata
            def _norm(s):
                nfkd = unicodedata.normalize('NFKD', s.lower().strip())
                return ''.join(c for c in nfkd if not unicodedata.combining(c))
            
            artist_norm = _norm(artist)
            track_norm = _norm(track_name)
            found = False
            
            for item in items:
                item_name = _norm(item.get("n", "") or "")
                item_artists = [_norm(a) for a in (item.get("as", []) or [])]
                
                name_match = track_norm in item_name or item_name in track_norm
                artist_match = any(
                    artist_norm in ia or ia in artist_norm
                    for ia in item_artists
                )
                
                if name_match and artist_match:
                    bpm_val = item.get("b", 0) or 0
                    camelot_val = item.get("c", "") or ""
                    key_val = item.get("k", "") or ""
                    
                    if bpm_val:
                        track["bpm"] = int(round(bpm_val))
                        log(f"  → {int(round(bpm_val))} BPM")
                    if camelot_val:
                        track["camelot"] = camelot_val
                        log(f"  → Camelot {camelot_val}")
                    if key_val:
                        track["key"] = key_val
                    
                    found = True
                    enriched += 1
                    break
            
            if not found:
                log(f"  → совпадений не найдено среди {len(items)} результатов")
            
            page.close()
            
            # Случайная задержка между треками
            time.sleep(random.uniform(1.0, 2.5))
        
        log(f"Tunebat enrichment: {enriched} enriched, {skipped} skipped")
        
    except Exception as e:
        log(f"Tunebat enrichment error: {e}")
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
    
    return tracks


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

SCRAPE_FUNCTIONS = {
    "tunebat": (scrape_tunebat, lambda q: f"https://www.tunebat.com/search?q={quote(q)}"),
    "beatport": (scrape_beatport, lambda genre: f"https://www.beatport.com/charts?genre={quote(genre)}"),
    "beatport-tracks": (scrape_beatport_tracks, lambda genre: f"https://www.beatport.com/charts?genre={quote(genre)}"),
    "1001tl": (scrape_1001tl, lambda genre: f"https://www.1001tracklists.com/search/track/?q={quote(genre + ' 2026')}"),
    "ra": (scrape_ra, lambda genre: f"https://ra.co/charts/genre/{genre.lower().replace(' ', '-')}"),
    "bandcamp": (scrape_bandcamp, lambda genre: f"https://bandcamp.com/tag/{genre.lower().replace(' ', '-')}"),
}


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Playwright scraper for Beatport, RA, 1001TL, Bandcamp, Tunebat")
    parser.add_argument("source", nargs="?", choices=list(SCRAPE_FUNCTIONS.keys()) + ["all"],
                       help="Источник для скрейпинга")
    parser.add_argument("--genre", default="techno",
                       help="Жанр (для beatport и ra использует slug из BEATPORT_GENRE_SLUGS)")
    parser.add_argument("--artist", help="Артист для поиска (Tunebat)")
    parser.add_argument("--track", help="Трек для поиска (Tunebat)")
    parser.add_argument("--url", help="URL для скрейпинга (если не указан, строится из --genre)")
    parser.add_argument("--output", "-o", help="Сохранить в JSON")
    parser.add_argument("--headless", action="store_true", help="Headless режим")
    parser.add_argument("--proxy", help="Прокси (protocol://user:pass@host:port)")
    parser.add_argument("--list-slugs", action="store_true", help="Показать slug'ы для Beatport")
    parser.add_argument("--enrich", help="JSON файл с треками для batch обогащения через Tunebat")
    
    args = parser.parse_args()
    
    if args.list_slugs:
        print("Beatport genre slugs:")
        for genre, slug in sorted(BEATPORT_GENRE_SLUGS.items()):
            print(f"  {genre:30s} -> {slug}")
        print()
        print("Использование: xvfb-run --auto-servernum uv run python3 playwright_scraper.py beatport --genre techno")
        sys.exit(0)
    
    if args.proxy:
        os.environ["RESIDENTIAL_PROXY"] = args.proxy
    
    # Batch enrichment mode (не требует source)
    if args.enrich:
        print(f"\n[Playwright Scraper] Batch Tunebat enrichment: {args.enrich}")
        with open(args.enrich) as f:
            tracks = json.load(f)
        print(f"  Загружено {len(tracks)} треков")
        
        enriched = enrich_tracks_via_tunebat(tracks)
        
        output_path = args.output or args.enrich.replace(".json", "_enriched.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(enriched, f, indent=2, ensure_ascii=False)
        print(f"  Сохранено в {output_path}")
        sys.exit(0)
    
    # Без source — ошибка
    if not args.source:
        parser.print_help()
        print("\nОШИБКА: укажи источник (tunebat, beatport, ...) или --enrich для batch обогащения")
        sys.exit(1)
    
    proxy_info = get_proxy_config()
    print(f"\n[Playwright Scraper] Источник: {args.source}, жанр: {args.genre}")
    print(f"[Playwright Scraper] headless={args.headless}, proxy={'Y' if proxy_info else 'N'}")
    print()
    
    # Для Tunebat — строим URL из artist/track
    if args.source == "tunebat":
        if args.artist and args.track:
            query = f"{args.artist} {args.track}"
            args.url = f"https://www.tunebat.com/search?q={quote(query)}"
        elif args.url:
            pass
        else:
            print("ОШИБКА: для tunebat нужен --artist + --track или --url")
            sys.exit(1)
    
    sources = list(SCRAPE_FUNCTIONS.keys()) if args.source == "all" else [args.source]
    
    all_results = {}
    
    for src in sources:
        scrape_fn, url_builder = SCRAPE_FUNCTIONS[src]
        
        if args.url:
            url = args.url
        elif callable(url_builder):
            url = url_builder(args.genre)
        else:
            url = url_builder
        
        print(f"\n{'='*60}")
        print(f"  {src.upper()}: {url}")
        print(f"{'='*60}")
        
        result = retry_scrape(url, scrape_fn)
        
        all_results[src] = {
            "success": result.success,
            "count": len(result.data),
            "error": result.error,
            "page_url": result.page_url,
            "page_title": result.page_title,
        }
        
        if result.success:
            print(f"  ✅ Найдено {len(result.data)} результатов")
            if result.page_title:
                print(f"     Title: {result.page_title}")
            
            if result.data:
                print(f"\n  Результаты:")
                for i, t in enumerate(result.data[:5], 1):
                    info = f"{t.get('artist', '')} — {t.get('track', '')}"
                    if t.get('bpm'):
                        info += f" ({t['bpm']} BPM)"
                    if t.get('camelot'):
                        info += f" {t['camelot']}"
                    print(f"    {i}. {info}")
            
            if args.output:
                fname = args.output
                if len(sources) > 1:
                    fname = fname.replace(".json", f"_{src}.json")
                with open(fname, "w") as f:
                    json.dump(result.data, f, indent=2, ensure_ascii=False)
                print(f"\n  Сохранено в {fname}")
        else:
            print(f"  ❌ {result.error}")
    
    # Итоговый отчёт
    print(f"\n{'='*60}")
    print(f"  ИТОГ:")
    print(f"{'='*60}")
    for src, info in all_results.items():
        status = "✅" if info["success"] else "❌"
        print(f"  {status} {src}: {info['count']} результатов  |  {info.get('error', 'OK')}")