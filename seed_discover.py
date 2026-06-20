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
import re
import math
import subprocess


def _norm(s: str) -> str:
    """Нормализовать для сравнения: нижний регистр, только буквы/цифры/пробелы. Чистая."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# маркеры «это не тот трек» — НЕ штрафуем remix/edit (в техно/хаусе они легитимны)
_JUNK = ["reaction", "react ", "lyric", "karaoke", "8d audio", "sped up", "slowed",
         "mashup", "megamix", "continuous mix", "full album", "tutorial",
         "how to make", "cover by", "live at", "live @", "(live", "[live"]


# маркеры «это не тот трек» — НЕ штрафуем remix/edit (в техно/хаусе они легитимны)
_JUNK = ["reaction", "react ", "lyric", "karaoke", "8d audio", "sped up", "slowed",
         "mashup", "megamix", "continuous mix", "full album", "tutorial",
         "how to make", "cover by", "live at", "live @", "(live", "[live",
         # DJ-сеты/выступления — не отдельные треки:
         "boiler room", "cercle", "b2b", "dj set", "live set", "full set",
         "essential mix", "radio show", "@ "]

# трек обычно 90с–12мин; короче — тизер/клип, длиннее — сет/микс
TRACK_MIN_SEC = 90
TRACK_MAX_SEC = 720


def is_plausible_track(cand: dict, min_sec: int = TRACK_MIN_SEC,
                       max_sec: int = TRACK_MAX_SEC) -> bool:
    """Длительность похожа на отдельный трек, а не на сет/тизер? Чистая.
    Неизвестная длительность → True (не пере-отсеиваем)."""
    dur = cand.get("duration")
    if dur is None:
        return True
    try:
        d = float(dur)
    except (TypeError, ValueError):
        return True
    return min_sec <= d <= max_sec


def title_penalty(title: str) -> int:
    """Сколько «мусорных» маркеров в заголовке (live/cover/reaction/...). Чистая."""
    t = (title or "").lower()
    return sum(1 for b in _JUNK if b in t)


def identity_ok(title: str, artist: str, track: str = "") -> bool:
    """Уверены, что это нужный артист/трек? Чистая. (Защита от «какой попало».)"""
    nt = _norm(title)
    na = _norm(artist)
    if na and na in nt:
        return True
    if track:
        ntr = _norm(track)
        if ntr and len(ntr) > 3 and ntr in nt:
            return True
    if na:                                    # частичное: ≥половины токенов артиста
        toks = [w for w in na.split() if len(w) > 2]
        if toks and sum(1 for w in toks if w in nt) / len(toks) >= 0.5:
            return True
    return False


def candidate_score(cand: dict, seed_artist: str = "", seed_track: str = "",
                    prefer_remix: bool = False) -> float:
    """Оценка кандидата: популярность (log views) + бонус за личность (+ремикс) − штраф за мусор. Чистая."""
    views = cand.get("views") or 0
    base = math.log10(views + 10)
    idb = 1.5 if identity_ok(cand.get("track", ""), seed_artist, seed_track) else 0.0
    rb = 1.0 if (prefer_remix and is_remix(cand.get("track", ""))) else 0.0
    return base + idb + rb - 1.0 * title_penalty(cand.get("track", ""))


def pick_best(cands: list[dict], seed_artist: str = "", seed_track: str = "",
              require_identity: bool = True, require_remix: bool = False,
              prefer_remix: bool = False) -> dict | None:
    """Лучший уверенный кандидат (по score). None, если уверенного совпадения нет. Чистая.
    Сеты/тизеры (по длительности) отсеиваются до оценки.
    require_remix → оставляем ТОЛЬКО ремиксы (для «не оригиналы, а ремиксы»)."""
    pool = []
    for c in cands:
        if not is_plausible_track(c):
            continue                                  # сет/тизер — не трек
        if require_identity and not identity_ok(c.get("track", ""), seed_artist, seed_track):
            continue
        if require_remix and not is_remix(c.get("track", "")):
            continue                                  # оригинал — мимо (нужен ремикс)
        pool.append((candidate_score(c, seed_artist, seed_track, prefer_remix), c))
    if not pool:
        return None
    pool.sort(key=lambda x: x[0], reverse=True)
    return pool[0][1]


def style_in_tags(tags: list[str], target_style: str) -> bool:
    """Стиль артиста совпадает с целевым? (по тегам last.fm). Чистая.
    Пустой target → True (проверку не требуем)."""
    ts = _norm(target_style)
    if not ts:
        return True
    toks = [w for w in ts.split() if len(w) > 2]
    blob = " ".join(_norm(t) for t in tags)
    if not toks:
        return True
    return any(w in blob for w in toks)


def merge_seed_meta(cand: dict, meta: dict) -> dict:
    """Доклеить метаданные сида (camelot/bpm/source) к найденному кандидату, НЕ затирая
    личность (track/youtube_url/views). Чистая. Для Beatport-сидов с готовыми BPM/Camelot."""
    if not meta:
        return cand
    for k in ("camelot", "key", "bpm", "mix_name", "label", "year",
              "source_url", "support_score", "source_type"):
        v = meta.get(k)
        if v not in (None, "", 0):
            cand[k] = v
    return cand


def build_seed_queries(seeds: list[str], styles: list[str] | None = None,
                       remix: bool = False) -> list[str]:
    """
    Поисковые запросы из сидов. Чистая.
    'Артист - Трек' берём как есть; одиночный артист → '<артист> <стиль>' для контекста.
    remix=True → дописываем 'remix', чтобы поиск выдал танцевальные ремиксы, не оригиналы.
    """
    style = (styles or [""])[0] if styles else ""
    out = []
    for s in (seeds or []):
        s = (s or "").strip()
        if not s:
            continue
        if " - " in s or " — " in s:
            q = s                                  # уже артист-трек
        else:
            q = f"{s} {style}".strip()             # артист + стиль
        if remix:
            q = f"{q} remix"
        out.append(q)
    return out


_REMIX_MARKERS = ("remix", "rework", "bootleg", "flip", " vip", "mashup", "re-edit", "re edit")


def is_remix(title: str) -> bool:
    """Заголовок — ремикс/переработка (не оригинал)? Чистая."""
    t = (title or "").lower()
    return any(m in t for m in _REMIX_MARKERS)


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
                  per_artist: int = 5, countries: dict | None = None,
                  verify: bool = True, verify_style: str = "",
                  seed_meta: dict | None = None, remix: bool = False) -> list[dict]:
    """
    Найти кандидатов по сидам через yt-dlp ytsearch, на каждый сид выбрать ЛУЧШИЙ
    уверенный (личность + просмотры − мусор). Тонкий I/O.
      verify        — требовать совпадение личности (иначе сид пропускается);
      verify_style  — опц.: перепроверить стиль артиста по тегам last.fm перед выбором.
    countries: {seed: 'FR'} — страна трека (для констрейнта уникальности).
    """
    queries = build_seed_queries(seeds, styles, remix=remix)
    countries = countries or {}
    seed_meta = seed_meta or {}
    found: list[dict] = []
    for seed, query in zip(seeds, queries):
        sa = seed.split(" - ")[0]
        st_ = seed.split(" - ", 1)[1] if " - " in seed else ""

        if verify_style:
            try:
                import lastfm
                if not style_in_tags(lastfm.get_artist_top_tags(sa), verify_style):
                    print(f"  ⚠ {seed}: стиль не подтверждён ({verify_style}) — пропуск")
                    continue
            except Exception:
                pass                              # last.fm недоступен — не блокируем

        try:
            res = subprocess.run(
                ["yt-dlp", f"ytsearch{per_artist}:{query}", "-J",
                 "--flat-playlist", "--no-warnings"],
                capture_output=True, text=True, timeout=60)
            if res.returncode != 0 or not res.stdout.strip():
                print(f"  ⚠ ничего по сиду: {seed}")
                continue
            data = json.loads(res.stdout)
            cands = parse_ytdlp_search(data, seed_artist=sa, country=countries.get(seed, ""))
            best = pick_best(cands, sa, st_, require_identity=verify,
                             require_remix=remix, prefer_remix=remix)
            if best:
                merge_seed_meta(best, seed_meta.get(seed, {}))   # приклеить мету (Beatport)
                found.append(best)
                print(f"  ✓ {seed}: лучший из {len(cands)} (views {best.get('views') or '?'})")
            else:
                print(f"  ⚠ {seed}: уверенного совпадения нет из {len(cands)} — пропуск")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            print(f"  ⚠ сид {seed}: {type(e).__name__}")
    return found


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Посев треков по сид-артистам (Path B)")
    ap.add_argument("--artists", default="", help="через запятую; можно 'Артист - Трек'")
    ap.add_argument("--artists-file", default="", help="сид-строки по одной в строке (от build_seedlist)")
    ap.add_argument("--style", default="")
    ap.add_argument("--per", type=int, default=5, help="искать N на сид, выбрать лучший")
    ap.add_argument("--no-verify", action="store_true", help="не требовать совпадение личности")
    ap.add_argument("--verify-style", default="", help="перепроверить стиль артиста по last.fm")
    ap.add_argument("--remix", action="store_true",
                    help="искать танцевальные РЕМИКСЫ, не оригиналы (для 'похожие на X → ремиксы')")
    ap.add_argument("--out", default="seed_candidates.json")
    args = ap.parse_args()

    seeds = [a.strip() for a in args.artists.split(",") if a.strip()]
    if args.artists_file:
        with open(args.artists_file, encoding="utf-8") as f:
            seeds += [ln.strip() for ln in f if ln.strip()]
    seeds = [s for s in seeds if s]
    cands = seed_discover(seeds, [args.style] if args.style else None, args.per,
                          verify=not args.no_verify, verify_style=args.verify_style,
                          remix=args.remix)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    print(f"Посев: {len(cands)} лучших кандидатов (по 1 на сид) → {args.out}. "
          f"Дальше: resolve_metadata → prescreen → скачать.")


if __name__ == "__main__":
    _main()
