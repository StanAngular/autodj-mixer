#!/usr/bin/env python3
"""
Playwright Scraper для autodj-mixer.
Обёртка над Playwright + stealth для обхода Cloudflare/антибот систем.

Статус источников (июнь 2026):
  ✅ Beatport /charts — работает (DJ charts, фильтр по жанру)
  ⚠️ 1001tracklists — client-side поиск, нужен ввод в поле
  ❌ RA — DataDome, нужен резидентский прокси
  ✅ Bandcamp — data-blob парсинг (если не заблокирован)

Использование:
  export RESIDENTIAL_PROXY="http://user:pass@host:port"  # для RA и сложных блоков
  export SOCKS5_PROXY="socks5://127.0.0.1:40000"         # Cloudflare Warp

  xvfb-run --auto-servernum uv run python3 playwright_scraper.py beatport --genre techno
  xvfb-run --auto-servernum uv run python3 playwright_scraper.py 1001tl --genre techno
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
MAX_RETRIES = 1  # >1 вызывает Playwright async error при пересоздании браузера
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


# ─── Camlot mapping ──────────────────────────────────────────────────────────

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
        locale="en-US",
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


def page_is_blocked(page) -> Optional[str]:
    html = page.content()[:2000].lower()
    title = page.title().lower()
    if "just a moment" in html:
        return "cloudflare"
    if "cf-browser-verification" in html:
        return "cloudflare_verify"
    if "access denied" in html or "access denied" in title:
        return "access_denied"
    if "geo.captcha-delivery.com" in html:
        return "datadome"
    if "403" in title:
        return "http_403"
    if "404" in title and "error" in title:
        return "http_404"
    return None


def retry_scrape(url: str, scrape_fn, max_retries: int = MAX_RETRIES) -> ScraperResult:
    """Выполнить скрейпинг с retry (каждая попытка в отдельном процессе)."""
    for attempt in range(max_retries):
        pw, browser, page = None, None, None
        try:
            pw, browser, page = launch_browser(headless=False)
            log(f"Попытка {attempt + 1}/{max_retries}: {url}")
            
            if not safe_goto(page, url):
                close_browser(pw, browser)
                continue
            
            block = page_is_blocked(page)
            if block:
                log(f"БЛОКИРОВКА: {block}")
                close_browser(pw, browser)
                delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
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
                delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
    
    return ScraperResult(error=f"Все {max_retries} попыток исчерпаны")


# ═══════════════════════════════════════════════════════════════════════════════
# Источник 1: Beatport Charts
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_beatport(page, url: str) -> ScraperResult:
    """
    Парсит Beatport /charts.
    Beatport переехал на V4 API. Старые /genre/*/top-100 — 404.
    /charts показывает DJ charts, фильтр по жанру через genre slug.
    """
    result = ScraperResult(source="beatport")
    
    if "/charts" in url:
        # Режим/страница charts — парсим __NEXT_DATA__
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
            
            # Module 0 = featured charts
            modules = queries[1].get("state", {}).get("data", {}).get("modules", [])
            if not modules:
                log("Модули не найдены")
                return result
            
            chart_items = modules[0].get("module_items", [])
            log(f"Найдено {len(chart_items)} charts")
            
            # Определяем жанр из URL query параметра
            from urllib.parse import parse_qs, urlparse
            parsed_url = urlparse(url)
            genre = parse_qs(parsed_url.query).get("genre", ["all"])[0]
            
            log(f"Фильтр по жанру: '{genre}'")
            
            # Фильтруем по жанру (если задан)
            for item in chart_items:
                if not isinstance(item, dict):
                    continue
                chart = item.get("item")
                if not isinstance(chart, dict):
                    continue
                    
                genres = [g.get("name", "").lower() for g in chart.get("genres", []) if isinstance(g, dict)]
                
                # Если жанр указан — фильтруем (частичное совпадение)
                if genre and genre.lower() != "all":
                    genre_lower = genre.lower()
                    genre_match = False
                    for g in genres:
                        # Проверяем частичное совпадение: "melodic techno" in "melodic house/techno"
                        if genre_lower in g or g in genre_lower:
                            genre_match = True
                            break
                        # Проверяем по словам: "techno" in "Melodic House/Techno"
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
    """
    Парсит 1001tracklists.
    Поиск — client-side JS. После поиска получает tracklist'ы,
    заходит в каждый и парсит отдельные треки.
    """
    result = ScraperResult(source="1001tracklists")
    
    # Шаг 1: Выполняем поиск
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
    
    # Шаг 2: Получаем ссылки на tracklist'ы из результатов поиска
    tracklist_urls = page.evaluate("""() => {
        const links = document.querySelectorAll('a[href*="/tracklist/"]');
        return Array.from(links).slice(0, 5).map(a => a.href);
    }""")
    
    log(f"Найдено {len(tracklist_urls)} tracklist'ов")
    
    if not tracklist_urls:
        return result
    
    # Шаг 3: Заходим в каждый tracklist и парсим треки
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
    """Парсит треки внутри tracklist на 1001TL."""
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
            
            if (text === 'ID - ID') return;  // placeholder
            
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
    """
    Парсит RA charts.
    Внимание: RA под DataDome (очень агрессивная защита).
    Нужен резидентский прокси для обхода.
    """
    result = ScraperResult(source="resident_advisor")
    
    # Проверка на DataDome
    if "geo.captcha-delivery.com" in page.content()[:2000]:
        log("DataDome captcha — нужен резидентский прокси! Установи RESIDENTIAL_PROXY")
        result.error = "DataDome captcha requires residential proxy"
        return result
    
    # Пробуем __NEXT_DATA__
    data_str = page.evaluate("() => { const el = document.querySelector('script#__NEXT_DATA__'); return el ? el.textContent : null; }")
    if data_str:
        try:
            data = json.loads(data_str)
            # RA может быть в разных структурах
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
    """
    Парсит Bandcamp discover page.
    Bandcamp — React SPA. Альбомы рендерятся как <a> ссылки.
    Нужен SOCKS5 прокси (Cloudflare Warp) для обхода.
    """
    result = ScraperResult(source="bandcamp")
    
    # Проверка на блокировку
    title = page.title()
    if "Client Challenge" in title or "just a moment" in title.lower():
        log("Bandcamp: Cloudflare challenge — нужен SOCKS5 прокси")
        result.error = "Cloudflare challenge"
        return result
    
    # Парсим альбомы из DOM
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
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

SCRAPE_FUNCTIONS = {
    "beatport": (scrape_beatport, lambda genre: f"https://www.beatport.com/charts?genre={quote(genre)}"),
    "1001tl": (scrape_1001tl, lambda genre: f"https://www.1001tracklists.com/search/track/?q={quote(genre + ' 2026')}"),
    "ra": (scrape_ra, lambda genre: f"https://ra.co/charts/genre/{genre.lower().replace(' ', '-')}"),
    "bandcamp": (scrape_bandcamp, lambda genre: f"https://bandcamp.com/tag/{genre.lower().replace(' ', '-')}"),
}


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Playwright scraper for Beatport, RA, 1001TL, Bandcamp")
    parser.add_argument("source", choices=list(SCRAPE_FUNCTIONS.keys()) + ["all"],
                       help="Источник для скрейпинга")
    parser.add_argument("--genre", default="techno",
                       help="Жанр (для beatport и ra использует slug из BEATPORT_GENRE_SLUGS)")
    parser.add_argument("--url", help="URL для скрейпинга (если не указан, строится из --genre)")
    parser.add_argument("--output", "-o", help="Сохранить в JSON")
    parser.add_argument("--headless", action="store_true", help="Headless режим")
    parser.add_argument("--proxy", help="Прокси (protocol://user:pass@host:port)")
    parser.add_argument("--list-slugs", action="store_true", help="Показать slug'ы для Beatport")
    
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
    
    proxy_info = get_proxy_config()
    print(f"\n[Playwright Scraper] Источник: {args.source}, жанр: {args.genre}")
    print(f"[Playwright Scraper] headless={args.headless}, proxy={'Y' if proxy_info else 'N'}")
    print()
    
    # Определяем источники для скрейпинга
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
        
        print(f"{'='*60}")
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
            print(f"  ✅ Найдено {len(result.data)} треков/charts")
            if result.page_title:
                print(f"     Title: {result.page_title}")
            
            if result.data:
                print(f"\n  Первые 5:")
                for i, t in enumerate(result.data[:5], 1):
                    info = f"{t['artist']} — {t['track']}"
                    if t.get('bpm'):
                        info += f" ({t['bpm']} BPM)"
                    if t.get('camelot'):
                        info += f" {t['camelot']}"
                    if t.get('support_score'):
                        info += f" [score: {t['support_score']}]"
                    print(f"    {i}. {info}")
            
            if args.output:
                fname = f"{args.output}"
                if len(sources) > 1:
                    fname = fname.replace(".json", f"_{src}.json")
                with open(fname, "w") as f:
                    json.dump(result.data, f, indent=2, ensure_ascii=False)
                print(f"\n  Сохранено в {fname}")
        else:
            print(f"  ❌ {result.error}")
        
        print()
    
    # Итоговый отчёт
    print(f"{'='*60}")
    print(f"  ИТОГ:")
    print(f"{'='*60}")
    for src, info in all_results.items():
        status = "✅" if info["success"] else "❌"
        print(f"  {status} {src}: {info['count']} результатов  |  {info.get('error', 'OK')}")