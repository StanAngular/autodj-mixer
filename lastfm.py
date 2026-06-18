#!/usr/bin/env python3
"""
lastfm.py — похожие исполнители через Last.fm API (artist.getSimilar).

Закрывает требование ТЗ «исполнитель + похожие». Last.fm — единственный из наших
источников, кто отдаёт similarity по реальным данным прослушиваний.

API key берётся из окружения LASTFM_API_KEY (НЕ хардкодить, .env в .gitignore).
Для artist.getSimilar нужен только api_key — shared secret не требуется.

ВАЖНО (honest): similarity-эндпоинты Last.fm бывают нестабильны (были репорты по
track.getSimilar в 2025). Поэтому get_similar_artists() defensive: при любой ошибке
или пустом ответе возвращает [], а вызывающий код откатывается на seed-исполнителей
из PulseRoots (style_resolver.seed_artists).

Чистые функции (_build_url / _parse_similar) тестируются офлайн на фикстурах;
сетевая обёртка тонкая и не падает.

CLI:  LASTFM_API_KEY=... python3 lastfm.py "Daft Punk"
"""
import argparse
import json
import os
from urllib.parse import urlencode

API_ROOT = "https://ws.audioscrobbler.com/2.0/"
DEFAULT_LIMIT = 20
REQUEST_TIMEOUT = 12


def _api_key() -> str:
    return os.environ.get("LASTFM_API_KEY", "")


def _build_url(method: str, params: dict, api_key: str) -> str:
    """Собрать URL запроса к Last.fm. Чистая функция."""
    q = {"method": method, "api_key": api_key, "format": "json", **params}
    return f"{API_ROOT}?{urlencode(q)}"


def _as_list(value):
    """Last.fm возвращает один объект как dict, несколько — как list. Нормализуем."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _parse_similar(data: dict) -> list[dict]:
    """
    Распарсить ответ artist.getSimilar → список {name, match, mbid}.
    Возвращает [] при ошибке Last.fm или пустом ответе. Чистая функция.
    match приводится к float (0..1), сортировка по убыванию похожести.
    """
    if not isinstance(data, dict) or "error" in data:
        return []
    artists = _as_list((data.get("similarartists") or {}).get("artist"))
    out: list[dict] = []
    for a in artists:
        name = (a.get("name") or "").strip()
        if not name:
            continue
        try:
            match = float(a.get("match", 0) or 0)
        except (TypeError, ValueError):
            match = 0.0
        out.append({"name": name, "match": round(match, 4),
                    "mbid": a.get("mbid", "")})
    out.sort(key=lambda x: x["match"], reverse=True)
    return out


def get_similar_artists(artist: str, limit: int = DEFAULT_LIMIT,
                        api_key: str = "") -> list[dict]:
    """
    Похожие исполнители для artist. Defensive: [] при отсутствии ключа, сетевой
    ошибке, ошибке API или пустом ответе (вызывающий откатывается на seed-артистов).
    """
    key = api_key or _api_key()
    if not key or not artist.strip():
        return []
    url = _build_url("artist.getsimilar",
                     {"artist": artist, "limit": limit, "autocorrect": 1}, key)
    try:
        import requests
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return _parse_similar(resp.json())[:limit]
    except Exception:
        return []


# ── Расширение (P27): top-tracks / geo (страна) / tag (жанр) ──────────────────

def _request(method: str, params: dict, api_key: str = "") -> dict:
    """Тонкая сетевая обёртка: {} при отсутствии ключа или любой ошибке."""
    key = api_key or _api_key()
    if not key:
        return {}
    try:
        import requests
        resp = requests.get(_build_url(method, params, key), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def _parse_artists(data: dict, root_key: str) -> list[dict]:
    """Распарсить *.getTopArtists / similar → [{name, mbid}]. Чистая."""
    if not isinstance(data, dict) or "error" in data:
        return []
    arts = _as_list((data.get(root_key) or {}).get("artist"))
    out = []
    for a in arts:
        if not isinstance(a, dict):
            continue
        name = (a.get("name") or "").strip()
        if name:
            out.append({"name": name, "mbid": a.get("mbid", "")})
    return out


def _parse_tracks(data: dict, root_key: str) -> list[dict]:
    """Распарсить *.getTopTracks → [{artist, track, playcount}]. Чистая."""
    if not isinstance(data, dict) or "error" in data:
        return []
    tracks = _as_list((data.get(root_key) or {}).get("track"))
    out = []
    for t in tracks:
        if not isinstance(t, dict):
            continue
        name = (t.get("name") or "").strip()
        if not name:
            continue
        art = t.get("artist") or {}
        artist = art.get("name", "") if isinstance(art, dict) else str(art)
        try:
            pc = int(t.get("playcount", 0) or 0)
        except (TypeError, ValueError):
            pc = 0
        out.append({"artist": artist.strip(), "track": name, "playcount": pc})
    return out


def get_artist_top_tracks(artist: str, limit: int = DEFAULT_LIMIT, api_key: str = "") -> list[dict]:
    """Топ-треки артиста → конкретные названия для посева (Path B). Defensive."""
    if not artist.strip():
        return []
    data = _request("artist.gettoptracks",
                    {"artist": artist, "limit": limit, "autocorrect": 1}, api_key)
    return _parse_tracks(data, "toptracks")[:limit]


def get_tag_top_artists(tag: str, limit: int = DEFAULT_LIMIT, api_key: str = "") -> list[dict]:
    """Топ-артисты по тегу/жанру (напр. 'tech house'). Defensive."""
    if not tag.strip():
        return []
    return _parse_artists(_request("tag.gettopartists", {"tag": tag, "limit": limit}, api_key),
                          "topartists")[:limit]


def get_geo_top_artists(country: str, limit: int = DEFAULT_LIMIT, api_key: str = "") -> list[dict]:
    """Топ-артисты по СТРАНЕ (ISO-название, напр. 'France'). Та ось, которой нет в Beatport."""
    if not country.strip():
        return []
    return _parse_artists(_request("geo.gettopartists", {"country": country, "limit": limit}, api_key),
                          "topartists")[:limit]


def get_geo_top_tracks(country: str, limit: int = DEFAULT_LIMIT, api_key: str = "") -> list[dict]:
    """Топ-треки по СТРАНЕ → готовые кандидаты «по одному с каждой страны». Defensive."""
    if not country.strip():
        return []
    return _parse_tracks(_request("geo.gettoptracks", {"country": country, "limit": limit}, api_key),
                         "tracks")[:limit]


def _main():
    ap = argparse.ArgumentParser(description="Last.fm: similar / top-tracks / geo / tag")
    ap.add_argument("artist", nargs="?", default="")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--check", action="store_true",
                    help="живая проверка API по всем методам (микротест)")
    ap.add_argument("--geo", default="", help="топ-треки по стране (напр. France)")
    ap.add_argument("--tag", default="", help="топ-артисты по жанру (напр. 'tech house')")
    args = ap.parse_args()

    if not _api_key():
        print("LASTFM_API_KEY не задан в окружении (.env)")
        return

    if args.check:
        print("Живая проверка Last.fm API (ключ найден):")
        checks = [
            ("artist.getSimilar(Daft Punk)",      lambda: get_similar_artists("Daft Punk", 5)),
            ("artist.getTopTracks(Daft Punk)",    lambda: get_artist_top_tracks("Daft Punk", 5)),
            ("tag.getTopArtists(tech house)",     lambda: get_tag_top_artists("tech house", 5)),
            ("geo.getTopArtists(France)",         lambda: get_geo_top_artists("France", 5)),
            ("geo.getTopTracks(France)",          lambda: get_geo_top_tracks("France", 5)),
        ]
        ok = True
        for label, fn in checks:
            res = fn()
            mark = "✓" if res else "✗ (пусто/ошибка)"
            ok = ok and bool(res)
            print(f"  {mark} {label}: {len(res)}")
            if res:
                print(f"      пример: {res[0]}")
        print("ИТОГ:", "API рабочий по всем методам ✓" if ok else
              "часть методов пуста — проверь ключ/доступность Last.fm ⚠")
        return

    if args.geo:
        print(json.dumps(get_geo_top_tracks(args.geo, args.limit), ensure_ascii=False, indent=2))
        return
    if args.tag:
        print(json.dumps(get_tag_top_artists(args.tag, args.limit), ensure_ascii=False, indent=2))
        return
    if args.artist:
        print(json.dumps(get_similar_artists(args.artist, args.limit), ensure_ascii=False, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
