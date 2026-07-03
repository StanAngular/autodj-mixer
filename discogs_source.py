#!/usr/bin/env python3
"""
discogs_source.py — источник кандидатов через ОФИЦИАЛЬНЫЙ Discogs API (Фаза 1а).

Зачем: единственный легальный поиск «жанр+год» прямо с VPS — не блокируется
Cloudflare (в отличие от скрейпа Beatport/поисковиков). Токен бесплатный:
discogs.com → Settings → Developers → Generate Token → DISCOGS_TOKEN в .env.

Ключевое отличие от старого fetch_discogs (curate_tracks, Path A): тот брал
ИМЯ РЕЛИЗА за имя трека (EP из 4 треков давал 1 псевдотрек). Здесь — адаптер
release→tracklist: GET /releases/{id} → все реальные треки релиза.

Паттерн — как beatport_source: поиск → сиды+мета (year едет с кандидатом) →
seed_discover (YouTube→SoundCloud) находит аудио. BPM/Camelot Discogs не даёт →
pending_local (посчитаются из аудио после скачки — штатно после P52/P59).

Rate limit: 60 req/min с токеном → пауза RATE_SLEEP между вызовами.
"""
import json
import os
import sys
import time

import requests

API = "https://api.discogs.com"
RATE_SLEEP = 1.1                       # 60 req/min с токеном
UA = "autodj-mixer/1.0 +https://github.com/StanAngular/autodj-mixer"


def _token() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    except Exception:
        pass
    return os.environ.get("DISCOGS_TOKEN", "").strip()


def _headers() -> dict:
    return {"User-Agent": UA, "Authorization": f"Discogs token={_token()}"}


# ─── Чистые парсеры (тестируются офлайн) ────────────────────────────────────

def parse_search_releases(data: dict) -> list[dict]:
    """JSON /database/search → [{release_id, title, year, styles, country}]. Чистая.
    Альбомы/компиляции отсеиваются (нужны синглы/EP — там треки танцевальные)."""
    out = []
    for it in (data.get("results") or []):
        rid = it.get("id")
        if not rid:
            continue
        formats = " ".join(it.get("format") or []).lower()
        if any(w in formats for w in ("album", "lp", "compilation")):
            continue
        out.append({
            "release_id": rid,
            "title":      it.get("title", ""),
            "year":       int(it.get("year", 0) or 0),
            "styles":     it.get("style") or [],
            "country":    it.get("country", ""),
        })
    return out


def parse_release_tracklist(release: dict) -> list[dict]:
    """JSON /releases/{id} → реальные треки. АДАПТЕР release→tracks (закрывает бэклог:
    старый путь терял треки EP). Чистая.
    Артист: у трека свой artists[] (VA-релизы) или общий у релиза."""
    year = int(release.get("year", 0) or 0)
    styles = release.get("styles") or []
    rel_artists = ", ".join(a.get("name", "").strip() for a in (release.get("artists") or [])) or ""
    out = []
    for tr in (release.get("tracklist") or []):
        if (tr.get("type_", "track") or "track") != "track":
            continue                                   # heading/index — не треки
        title = (tr.get("title") or "").strip()
        if not title:
            continue
        t_artists = ", ".join(a.get("name", "").strip() for a in (tr.get("artists") or []))
        artist = _clean_artist(t_artists or rel_artists)
        if not artist:
            continue
        out.append({"artist": artist, "track": title, "year": year,
                    "styles": styles, "duration": tr.get("duration", "")})
    return out


def _clean_artist(name: str) -> str:
    """Discogs дописывает '(2)'/'(3)' к тёзкам — убираем. Чистая."""
    import re
    return re.sub(r"\s*\(\d+\)\s*$", "", (name or "").strip())


def tracks_to_seeds_with_meta(tracks: list[dict], year_lo: int | None = None,
                              year_hi: int | None = None) -> tuple[list[str], dict]:
    """Discogs-треки → (сиды, {сид: мета}). Чистая. Год — ПЕРВОКЛАССНЫЙ фильтр
    (Фаза 1б): вне диапазона — мимо; год всегда едет в мете (проверяем бриф)."""
    seeds, meta, seen = [], {}, set()
    for t in tracks:
        artist, track = (t.get("artist") or "").strip(), (t.get("track") or "").strip()
        if not artist or not track:
            continue
        yr = int(t.get("year", 0) or 0)
        if yr:
            if year_lo and yr < year_lo:
                continue
            if year_hi and yr > year_hi:
                continue
        seed = f"{artist} - {track}"
        if seed.lower() in seen:
            continue
        seen.add(seed.lower())
        seeds.append(seed)
        m = {"source_type": "discogs"}
        if yr:
            m["year"] = yr
        if t.get("styles"):
            m["styles"] = t["styles"]
        meta[seed] = m
    return seeds, meta


# ─── Тонкий I/O ──────────────────────────────────────────────────────────────

def _api_get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(f"{API}{path}", headers=_headers(), params=params or {}, timeout=20)
    resp.raise_for_status()
    time.sleep(RATE_SLEEP)
    return resp.json()


def search_releases(style: str, year: int, country: str = "", page: int = 1,
                    per_page: int = 50) -> list[dict]:
    """Поиск релизов style+year (официальный API). Сортировка want — «народный спрос»."""
    params = {"style": style, "year": year, "type": "release",
              "sort": "want", "sort_order": "desc", "per_page": per_page, "page": page}
    if country:
        params["country"] = country
    return parse_search_releases(_api_get("/database/search", params))


def fetch_release_tracks(release_id: int) -> list[dict]:
    """GET /releases/{id} → треки (адаптер)."""
    return parse_release_tracklist(_api_get(f"/releases/{release_id}"))


def discogs_candidates(style: str, year_lo: int, year_hi: int, target: int = 16,
                       country: str = "", per: int = 5, verify: bool = True) -> list[dict]:
    """style+годы → релизы → АДАПТЕР → треки → сиды с метой → seed_discover (YT→SC).
    Останавливается, когда сидов хватает (~2×target на отсев discover'ом)."""
    import seed_discover as sd
    all_tracks: list[dict] = []
    for year in range(year_hi, year_lo - 1, -1):       # свежие сперва
        for rel in search_releases(style, year, country):
            try:
                all_tracks.extend(fetch_release_tracks(rel["release_id"]))
            except requests.RequestException as e:
                print(f"  ⚠ релиз {rel['release_id']}: {type(e).__name__}")
            if len(all_tracks) >= 2 * target:
                break
        if len(all_tracks) >= 2 * target:
            break
    seeds, meta = tracks_to_seeds_with_meta(all_tracks, year_lo, year_hi)
    print(f"  Discogs: {len(all_tracks)} треков из релизов → {len(seeds)} сидов "
          f"({year_lo}-{year_hi}, style={style!r})")
    return sd.seed_discover(seeds[: 2 * target], per_artist=per, verify=verify, seed_meta=meta)


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Discogs API: жанр+год → треки (адаптер) → аудио")
    ap.add_argument("--style", required=True, help="стиль Discogs-таксономии (Deep House, Disco, Techno…)")
    ap.add_argument("--year-min", type=int, required=True)
    ap.add_argument("--year-max", type=int, required=True)
    ap.add_argument("--target", type=int, default=16)
    ap.add_argument("--country", default="")
    ap.add_argument("--per", type=int, default=5)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", default="discogs_candidates.json")
    args = ap.parse_args()
    if not _token():
        print("Нет DISCOGS_TOKEN в env (.env). discogs.com → Settings → Developers → token")
        sys.exit(2)
    cands = discogs_candidates(args.style, args.year_min, args.year_max, args.target,
                               args.country, args.per, verify=not args.no_verify)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    print(f"Discogs: {len(cands)} кандидатов → {args.out}")


if __name__ == "__main__":
    _main()
