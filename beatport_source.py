#!/usr/bin/env python3
"""
beatport_source.py — Beatport как источник в ОБЩЕЙ воронке (Path A в Path B).

Beatport отдаёт чистые ТРЕКИ (не сеты) с готовыми BPM/Camelot, но без youtube_url —
аудио надо найти. Поэтому Beatport-треки превращаются в сид-строки 'Artist - Track'
С ПРИКЛЕЕННЫМИ метаданными, идут в seed_discover (поиск аудио + проверка личности),
а метаданные едут с найденным кандидатом. Дальше resolve/prescreen их ПРОПУСКАЮТ
(Camelot уже есть) — умный bypass, никаких лишних MP3-проб.

tracks_to_seeds_with_meta — чистая (тестируется). beatport_candidates — тонкий I/O.
"""
import json


def mix_name_ok(mix_name: str) -> bool:
    """Версия трека годится для микса? Чистая. Radio Edit — отсев (диджею не нужен);
    пустое/Extended/Original/Club/Dub — ок."""
    mn = (mix_name or "").strip().lower()
    if not mn:
        return True
    return "radio edit" not in mn and "radio mix" not in mn


def release_year(release_date: str) -> int:
    """'YYYY-MM-DD' → год (int) или 0. Чистая."""
    s = (release_date or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return 0


def sort_beatport_tracks(tracks: list[dict], sort: str = "") -> list[dict]:
    """Сортировка пула Beatport по намерению брифа. Чистая.
      newest      → свежее раньше (по release_date);
      bestsellers → популярнее раньше (по support_score);
      ""          → как пришло.
    Это «клиентская» сортировка того, что Beatport уже отдал (URL-фильтры Newest/
    Bestsellers на ленте треков жанра — отдельный V4-эндпоинт, см. docs/beatport.md)."""
    s = (sort or "").strip().lower()
    if s in ("newest", "new", "release", "date"):
        return sorted(tracks, key=lambda t: (t.get("release_date") or ""), reverse=True)
    if s in ("bestsellers", "popular", "top", "sales"):
        return sorted(tracks, key=lambda t: (t.get("support_score") or 0), reverse=True)
    return list(tracks)


def tracks_to_seeds_with_meta(tracks: list[dict], year_lo: int | None = None,
                              year_hi: int | None = None) -> tuple[list[str], dict]:
    """Beatport-треки → (сид-строки, {сид: метаданные}). Чистая.
    Отсев Radio Edit и треков вне диапазона года (когда год известен).
    Метаданные (camelot/bpm/mix_name/label/year/source) поедут с кандидатом."""
    seeds, meta, seen = [], {}, set()
    for t in tracks:
        artist = (t.get("artist") or "").strip()
        track = (t.get("track") or "").strip()
        if not artist or not track:
            continue
        if not mix_name_ok(t.get("mix_name", "")):
            continue                                  # Radio Edit — мимо
        yr = release_year(t.get("release_date", ""))
        if yr:                                        # год известен → проверяем диапазон
            if year_lo and yr < year_lo:
                continue
            if year_hi and yr > year_hi:
                continue
        seed = f"{artist} - {track}"
        if seed.lower() in seen:
            continue
        seen.add(seed.lower())
        seeds.append(seed)
        m = {"source_type": "beatport"}
        for src, dst in (("camelot", "camelot"), ("bpm", "bpm"), ("mix_name", "mix_name"),
                         ("label", "label"), ("source_url", "source_url"),
                         ("support_score", "support_score")):
            v = t.get(src)
            if v not in (None, "", 0):
                m[dst] = v
        if yr:
            m["year"] = yr
        meta[seed] = m
    return seeds, meta


def beatport_candidates(genre: str, per: int = 5, verify: bool = True,
                        year_lo: int | None = None, year_hi: int | None = None,
                        sort: str = "") -> list[dict]:
    """Beatport чарты жанра → кандидаты с аудио (через seed_discover) + метаданными.
    Тонкий I/O. Жанр маппится через BEATPORT_GENRE_SLUGS; отсев Radio Edit + год; sort."""
    from curate_tracks import fetch_beatport_charts, BEATPORT_GENRE_SLUGS
    import seed_discover as sd
    slug = BEATPORT_GENRE_SLUGS.get(genre.strip().lower(), genre)
    tracks = fetch_beatport_charts(slug, [])
    tracks = sort_beatport_tracks(tracks, sort)
    seeds, meta = tracks_to_seeds_with_meta(tracks, year_lo, year_hi)
    suffix = f", сортировка: {sort}" if sort else ""
    print(f"  Beatport ({slug}): {len(seeds)} треков (после отсева Radio Edit/года{suffix}) → поиск аудио")
    return sd.seed_discover(seeds, per_artist=per, verify=verify, seed_meta=meta)


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Beatport как источник кандидатов (с метаданными)")
    ap.add_argument("--genre", required=True, help="жанр Beatport (напр. 'deep trance')")
    ap.add_argument("--per", type=int, default=5)
    ap.add_argument("--year-min", type=int, default=None)
    ap.add_argument("--year-max", type=int, default=None)
    ap.add_argument("--sort", default="", choices=["", "newest", "bestsellers"],
                    help="newest: свежее раньше; bestsellers: популярнее раньше")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", default="beatport_candidates.json")
    args = ap.parse_args()

    cands = beatport_candidates(args.genre, args.per, verify=not args.no_verify,
                                year_lo=args.year_min, year_hi=args.year_max, sort=args.sort)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    with_meta = sum(1 for c in cands if (c.get("camelot") or "").strip())
    print(f"Beatport-источник: {len(cands)} кандидатов ({with_meta} с Camelot — пройдут "
          f"resolve/prescreen без скачки) → {args.out}")


if __name__ == "__main__":
    _main()
