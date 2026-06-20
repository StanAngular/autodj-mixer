#!/usr/bin/env python3
"""
compose_sources.py — единый подбор: источники по УБЫВАНИЮ богатства данных.

Сначала источник с БОЛЬШИМ объёмом данных, спускаемся к бедным только если не добрали
target. Порядок (по данным, НЕ «Path A/B»):
  [1] Beatport   — богатейший: BPM+Camelot+год+лейбл, чистые треки (+ чарты, by-name,
                   гейты Radio-Edit/год, сортировки).
  [2] Bandcamp   — жанровый андеграунд: треки в стиле (аудио добираем поиском).
  [3] last.fm/YT — беднейший: одни ИМЕНА, стиль дрейфит → жёсткий ГЕЙТ стиля (+remix).

Discogs (релизы→треки) — следующим шагом (адаптер альбом→треклист: ТРЕКИ, не альбомы).
merge_candidates — чистая (тестируется). compose — тонкий I/O.
"""
import json

from local_enrich import video_id


def merge_candidates(pools: list[list[dict]], target: int | None = None) -> list[dict]:
    """Слить пулы по приоритету (первый — главный), дедуп по video_id, кап до target.
    Чистая. Ключ дедупа — video_id из youtube_url (или 'artist|track' как запасной)."""
    seen, out = set(), []
    for pool in pools:
        for c in pool:
            vid = video_id(c.get("youtube_url", ""))
            key = vid or f"{(c.get('artist') or '').lower()}|{(c.get('track') or '').lower()}"
            if not key.strip("|") or key in seen:
                continue
            seen.add(key)
            out.append(c)
            if target and len(out) >= target:
                return out
    return out


def _enough(pools: list[list[dict]], target: int) -> int:
    """Сколько уникальных набрали (через дедуп)."""
    return len(merge_candidates(pools, target))


def compose(style: str = "", artists: str = "", tag: str = "", target: int = 16,
            year_lo: int | None = None, year_hi: int | None = None,
            per: int = 5, verify: bool = True, sort: str = "", country: str = "",
            remix: bool = False) -> list[dict]:
    """Источники по убыванию данных: Beatport → Bandcamp → last.fm/YouTube.
    Каждый следующий — только если не добрали target. Тонкий I/O."""
    import seed_discover as sd
    pools: list[list[dict]] = []
    genre = style or tag

    # [1] Beatport — богатейший источник (главный)
    if genre:
        try:
            import beatport_source as bps
            bp = bps.beatport_candidates(genre, per=per, verify=verify,
                                         year_lo=year_lo, year_hi=year_hi, sort=sort)
            pools.append(bp)
            print(f"  [1] Beatport: {len(bp)} (BPM/Camelot готовы)")
        except Exception as e:
            print(f"  [1] Beatport пропущен: {type(e).__name__}")

    # [2] Bandcamp — жанровый андеграунд (треки в стиле, аудио добираем)
    if genre and _enough(pools, target) < target:
        try:
            from curate_tracks import fetch_bandcamp_underground
            bc_tracks = fetch_bandcamp_underground(genre, country)
            seeds = [f"{t['artist']} - {t['track']}" for t in bc_tracks
                     if t.get("artist") and t.get("track")]
            bc = sd.seed_discover(seeds, per_artist=1, verify=verify, verify_style=genre)
            pools.append(bc)
            print(f"  [2] Bandcamp: +{len(bc)} (из {len(seeds)} треков жанра)")
        except Exception as e:
            print(f"  [2] Bandcamp пропущен: {type(e).__name__}")

    # [3] last.fm/YouTube — беднейший (имена) → ГЕЙТ стиля (+ремиксы при remix)
    if _enough(pools, target) < target:
        try:
            import build_seedlist as bsl
            seed_artists = [a.strip() for a in artists.split(",") if a.strip()]
            res = bsl.build_seedlist(style=style, seed_artists=seed_artists, tag=tag,
                                     limit=max(target * 2, 24))
            yt = sd.seed_discover(res["seeds"], per_artist=1, verify=verify,
                                  verify_style=(style or tag), remix=remix)
            pools.append(yt)
            print(f"  [3] last.fm/YouTube: +{len(yt)} (добор, гейт стиля)")
        except Exception as e:
            print(f"  [3] last.fm/YouTube пропущен: {type(e).__name__}")
    else:
        print("  Богатые источники покрыли target — last.fm/YouTube не нужен")

    return merge_candidates(pools, target)


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Композитный поиск: Beatport → YouTube/last.fm")
    ap.add_argument("--style", default="")
    ap.add_argument("--artists", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--target", type=int, default=16)
    ap.add_argument("--year-min", type=int, default=None)
    ap.add_argument("--year-max", type=int, default=None)
    ap.add_argument("--per", type=int, default=5)
    ap.add_argument("--sort", default="", choices=["", "newest", "bestsellers"])
    ap.add_argument("--country", default="", help="страна для Bandcamp")
    ap.add_argument("--remix", action="store_true", help="ремиксы в Path B-доборе")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", default="composite_candidates.json")
    args = ap.parse_args()

    cands = compose(args.style, args.artists, args.tag, args.target,
                    args.year_min, args.year_max, args.per, verify=not args.no_verify,
                    sort=args.sort, country=args.country, remix=args.remix)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    with_meta = sum(1 for c in cands if (c.get("camelot") or "").strip())
    print(f"Композит: {len(cands)} кандидатов ({with_meta} с Camelot) → {args.out}")


if __name__ == "__main__":
    _main()
