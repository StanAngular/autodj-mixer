#!/usr/bin/env python3
"""
compose_sources.py — композитный поиск с фоллбэком источников (Beatport → YouTube/last.fm).

Бриф → пробуем приоритетный источник (Beatport: чистые треки + готовые BPM/Camelot),
и ЕСЛИ набрали меньше target — добираем Path B (build_seedlist + seed_discover по
YouTube/last.fm). Пулы сливаются с дедупом по video_id, приоритет — у Beatport.

Это и есть «нет на Beatport → идём дальше по списку» для DISCOVERY (для метаданных
фоллбэк уже есть в resolve_metadata). Доп. источники (SoundCloud/Bandcamp) добавляются
в список pools по мере подключения.

merge_candidates — чистая (тестируется офлайн). compose — тонкий I/O.
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


def compose(style: str = "", artists: str = "", tag: str = "", target: int = 16,
            year_lo: int | None = None, year_hi: int | None = None,
            per: int = 5, verify: bool = True, sort: str = "") -> list[dict]:
    """Beatport → (если мало) YouTube/last.fm. Тонкий I/O. Возвращает слитый пул."""
    pools: list[list[dict]] = []
    genre = style or tag

    # 1) приоритетный источник — Beatport
    if genre:
        try:
            import beatport_source as bps
            bp = bps.beatport_candidates(genre, per=per, verify=verify,
                                         year_lo=year_lo, year_hi=year_hi, sort=sort)
            pools.append(bp)
            print(f"  [1] Beatport: {len(bp)} кандидатов")
        except Exception as e:
            print(f"  [1] Beatport пропущен: {type(e).__name__}")

    have = len(merge_candidates(pools, target))

    # 2) фоллбэк — Path B (YouTube/last.fm), только если не добрали
    if have < target:
        try:
            import build_seedlist as bsl
            import seed_discover as sd
            seed_artists = [a.strip() for a in artists.split(",") if a.strip()]
            res = bsl.build_seedlist(style=style, seed_artists=seed_artists, tag=tag,
                                     limit=max(target * 2, 24))
            yt = sd.seed_discover(res["seeds"], per_artist=1, verify=verify,
                                  verify_style=(style or tag))
            pools.append(yt)
            print(f"  [2] Фоллбэк YouTube/last.fm: +{len(yt)} "
                  f"(Beatport дал {have} < target {target})")
        except Exception as e:
            print(f"  [2] Фоллбэк пропущен: {type(e).__name__}")
    else:
        print(f"  Beatport покрыл target ({have} ≥ {target}) — фоллбэк не нужен")

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
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", default="composite_candidates.json")
    args = ap.parse_args()

    cands = compose(args.style, args.artists, args.tag, args.target,
                    args.year_min, args.year_max, args.per, verify=not args.no_verify,
                    sort=args.sort)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    with_meta = sum(1 for c in cands if (c.get("camelot") or "").strip())
    print(f"Композит: {len(cands)} кандидатов ({with_meta} с Camelot) → {args.out}")


if __name__ == "__main__":
    _main()
