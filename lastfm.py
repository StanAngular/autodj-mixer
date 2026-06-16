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


def _main():
    ap = argparse.ArgumentParser(description="Last.fm similar artists")
    ap.add_argument("artist")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = ap.parse_args()
    if not _api_key():
        print("LASTFM_API_KEY не задан в окружении (.env)")
        return
    res = get_similar_artists(args.artist, args.limit)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
