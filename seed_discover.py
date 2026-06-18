#!/usr/bin/env python3
"""
seed_discover.py — посев треков по знанию: сид-артисты/треки → кандидаты с YouTube.

Зачем: Path B. Когда нужно «по одному треку с каждой страны», «французский органик-
хаус», андеграунд или редкое — это знание агента, а не скрейп Beatport (там страны
нет). Агент задаёт seed_artists (или 'Артист - Трек'), здесь они превращаются в
кандидатов через yt-dlp ytsearch. Camelot/BPM у них пока нет — их посчитает
local_enrich ПОСЛЕ скачивания (compute_key из аудио).

Поток: seed_discover → (слить с cand.json) → yt_download → local_enrich → bridge.

build_seed_queries и parse_ytdlp_search — чистые (тестируются офлайн).
seed_discover — тонкий I/O (вызывает yt-dlp).
"""
import json
import subprocess


def build_seed_queries(seeds: list[str], styles: list[str] | None = None) -> list[str]:
    """
    Поисковые запросы из сидов. Чистая.
    'Артист - Трек' берём как есть; одиночный артист → '<артист> <стиль>' для контекста.
    """
    style = (styles or [""])[0] if styles else ""
    out = []
    for s in (seeds or []):
        s = (s or "").strip()
        if not s:
            continue
        if " - " in s or " — " in s:
            out.append(s)                          # уже артист-трек
        else:
            out.append(f"{s} {style}".strip())     # артист + стиль
    return out


def parse_ytdlp_search(data: dict, seed_artist: str = "", country: str = "") -> list[dict]:
    """
    yt-dlp -J (dict с 'entries') → кандидаты Path B. Чистая.
    Camelot пуст (camelot_source='pending_local') — посчитается локально после скачивания.
    """
    out = []
    for e in (data.get("entries") or []):
        if not e:
            continue
        vid = e.get("id", "")
        if not vid:
            continue
        out.append({
            "artist":         seed_artist or e.get("uploader", ""),
            "track":          e.get("title", ""),
            "video_id":       vid,
            "youtube_url":    e.get("url") or e.get("webpage_url") or f"https://youtu.be/{vid}",
            "duration":       e.get("duration"),
            "views":          e.get("view_count"),
            "country":        country,
            "bpm":            None,
            "camelot":        "",
            "source":         "seed",
            "camelot_source": "pending_local",
        })
    return out


def seed_discover(seeds: list[str], styles: list[str] | None = None,
                  per_artist: int = 3, countries: dict | None = None) -> list[dict]:
    """
    Найти кандидатов по сидам через yt-dlp ytsearch. Тонкий I/O.
    countries: {seed: 'FR'} — проставить страну треку (для констрейнта уникальности).
    """
    queries = build_seed_queries(seeds, styles)
    countries = countries or {}
    found: list[dict] = []
    for seed, query in zip(seeds, queries):
        try:
            res = subprocess.run(
                ["yt-dlp", f"ytsearch{per_artist}:{query}", "-J",
                 "--flat-playlist", "--no-warnings"],
                capture_output=True, text=True, timeout=60)
            if res.returncode != 0 or not res.stdout.strip():
                print(f"  ⚠ ничего по сиду: {seed}")
                continue
            data = json.loads(res.stdout)
            cands = parse_ytdlp_search(data, seed_artist=seed.split(" - ")[0],
                                       country=countries.get(seed, ""))
            found.extend(cands)
            print(f"  ✓ {seed}: {len(cands)} кандидатов")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            print(f"  ⚠ сид {seed}: {type(e).__name__}")
    return found


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Посев треков по сид-артистам (Path B)")
    ap.add_argument("--artists", required=True, help="через запятую; можно 'Артист - Трек'")
    ap.add_argument("--style", default="")
    ap.add_argument("--per", type=int, default=3, help="кандидатов на сид")
    ap.add_argument("--out", default="seed_candidates.json")
    args = ap.parse_args()

    seeds = [a.strip() for a in args.artists.split(",") if a.strip()]
    cands = seed_discover(seeds, [args.style] if args.style else None, args.per)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    print(f"Посев: {len(cands)} кандидатов → {args.out}. "
          f"Дальше: скачать (yt_download) и посчитать Camelot (local_enrich).")


if __name__ == "__main__":
    _main()
