#!/usr/bin/env python3
"""
resolve_metadata.py — каскад разрешения BPM/Camelot БЕЗ скачивания.

Принцип (SKILL §2/§7): метаданные сначала, закачка — последней. Для каждого трека
без Camelot пробуем по убыванию дешевизны:
  1. каталог  (catalog_utils) — ранее зарегистрированный трек, бесплатно, база растёт;
  2. кэш      (enrich_cache)  — прошлые Tunebat-результаты по имени;
  3. Tunebat  (опц., аккуратно) — ТОЛЬКО остаток, медленно, обходя блок;
  → остаток (нигде не нашли) уходит на MP3-пробу/аудио (prescreen/local_enrich).

Так закачка ради анализа становится редким последним резервом, а не дефолтом.

needs_resolution / from_catalog / from_cache — чистые (тестируются офлайн).
resolve_candidates — тонкий I/O (каталог/кэш/опц. Tunebat).
"""
import json
import os

from local_enrich import video_id           # переиспользуем извлечение id
import enrich_cache as ec


def needs_resolution(track: dict) -> bool:
    """Нужно ли разрешать (нет Camelot). Чистая."""
    return not (track.get("camelot") or "").strip()


def from_catalog(track: dict, index: dict) -> bool:
    """Заполнить из каталога по video_id. Меняет track на месте. Чистая. → нашли?"""
    vid = video_id(track.get("youtube_url", "")) or track.get("video_id", "")
    if not vid:
        return False
    entry = (index.get("tracks") or {}).get(vid)
    if not entry:
        return False
    cam = (entry.get("camelot") or "").strip()
    if not cam:
        return False
    track["camelot"] = cam
    if entry.get("bpm") and not track.get("bpm"):
        track["bpm"] = entry["bpm"]
    track["camelot_source"] = "catalog"
    return True


def from_cache(track: dict, cache: dict) -> bool:
    """Заполнить из enrich_cache по 'артист|трек'. Чистая. → нашли?"""
    hit = ec.cache_get(cache, track.get("artist", ""), track.get("track", ""))
    if not hit:
        return False
    cam = (hit.get("camelot") or "").strip()
    if not cam:
        return False
    track["camelot"] = cam
    if hit.get("bpm") and not track.get("bpm"):
        track["bpm"] = hit["bpm"]
    track["camelot_source"] = "cache"
    return True


def resolve_candidates(candidates: list[dict], catalog_dir: str, cache_path: str,
                       use_tunebat: bool = False) -> tuple[list[dict], dict]:
    """Каскад каталог→кэш→(опц. Tunebat остаток). Тонкий I/O. Возвращает (cands, stats)."""
    import sys
    sys.path.insert(0, catalog_dir)
    import catalog_utils as cu
    index = cu.load_index()
    cache = ec.load_cache(cache_path)
    stats = {"already": 0, "catalog": 0, "cache": 0, "tunebat": 0, "residual": 0}

    residual = []
    for t in candidates:
        if not needs_resolution(t):
            stats["already"] += 1
            continue
        if from_catalog(t, index):
            stats["catalog"] += 1
            continue
        if from_cache(t, cache):
            stats["cache"] += 1
            continue
        residual.append(t)

    # Tunebat — аккуратно и ТОЛЬКО по остатку (медленно, со своими таймаутами)
    if use_tunebat and residual:
        try:
            from playwright_scraper import enrich_tracks_via_tunebat
            enrich_tracks_via_tunebat(residual)          # заполняет на месте
            for t in residual:
                if (t.get("camelot") or "").strip():
                    t["camelot_source"] = "tunebat"
                    ec.cache_put(cache, t.get("artist", ""), t.get("track", ""),
                                 t.get("bpm"), t.get("camelot"))
                    stats["tunebat"] += 1
            ec.save_cache(cache, cache_path)
        except Exception as e:
            print(f"  ⚠ Tunebat-шаг пропущен: {type(e).__name__}")

    stats["residual"] = sum(1 for t in candidates if needs_resolution(t))
    return candidates, stats


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Каскад разрешения BPM/Camelot без скачивания")
    ap.add_argument("candidates")
    ap.add_argument("--catalog-dir",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "shared", "catalog"))
    ap.add_argument("--cache", default="data/enrich_cache.json")
    ap.add_argument("--tunebat", action="store_true", help="добить остаток через Tunebat (медленно)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cands = json.load(open(args.candidates, encoding="utf-8"))
    cands, st = resolve_candidates(cands, args.catalog_dir, args.cache, args.tunebat)
    out = args.out or args.candidates
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    print(f"Каскад: каталог {st['catalog']}, кэш {st['cache']}, tunebat {st['tunebat']}, "
          f"уже было {st['already']}. Остаток на аудио-пробу: {st['residual']}. → {out}")


if __name__ == "__main__":
    _main()
