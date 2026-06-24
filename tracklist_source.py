"""tracklist_source.py — явный треклист (из веб-поиска/LLM) → кандидаты с метаданными.

Принимает JSON `[{artist, track, bpm?, camelot?, key?, year?}]` ИЛИ текст `Artist - Title`.
BPM/Camelot (если LLM их дал — из Beatport/Tunebat-листинга в индексе) ЕДУТ с сидами через
seed_meta, ровно как у Beatport. Тогда resolve/prescreen их НЕ перепроверяют (smart-bypass),
и Cloudflare не нужен. Чего нет — добьёт каскад/local_enrich после скачивания.

Это «звено-приёмник» для discovery через поиск/LLM: тот собирает список (любой жанр/год,
минуя Cloudflare), а тут он входит в обычный пайплайн. Reuse seed_meta + KEY_TO_CAMELOT,
ничего не реинвентим. Чистые функции тестируются офлайн; tracklist_candidates — тонкий I/O.
"""
import json

import seed_discover as sd
from curate_tracks import KEY_TO_CAMELOT


def key_to_camelot(key: str) -> str:
    """Музыкальный ключ ('E Major' / 'F Minor' / 'Ab maj') → Camelot ('12B'). Чистая.
    '' если не распознан. Понимает полное Major/Minor и сокращённое maj/min."""
    k = (key or "").strip()
    if not k:
        return ""
    parts = k.replace("-", " ").split()
    if len(parts) < 2:
        return ""
    note = parts[0][0].upper() + parts[0][1:]            # Ab, Bb, F# — регистр ноты
    mode = parts[1].lower()
    mode = "maj" if mode.startswith("maj") else ("min" if mode.startswith("min") else mode)
    return KEY_TO_CAMELOT.get(f"{note} {mode}", "")


def load_tracklist(path: str) -> list[dict]:
    """Файл → [{artist, track, bpm?, camelot?, key?, year?}]. JSON-массив ИЛИ текст 'Artist - Title'."""
    raw = open(path, encoding="utf-8").read().strip()
    if raw.startswith("["):
        return json.loads(raw)
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if " - " in line:
            a, t = line.split(" - ", 1)
            out.append({"artist": a.strip(), "track": t.strip()})
    return out


def tracklist_to_seeds_with_meta(entries: list[dict]) -> tuple[list[str], dict]:
    """[{artist,track,bpm?,camelot?,key?}] → (seeds, {seed: meta}). Чистая. Мета едет как у Beatport.
    camelot берём напрямую, иначе конвертим из key. bpm/year — как есть."""
    seeds: list[str] = []
    meta: dict = {}
    seen: set = set()
    for e in entries:
        a = (e.get("artist") or "").strip()
        t = (e.get("track") or "").strip()
        if not a or not t:
            continue
        seed = f"{a} - {t}"
        if seed.lower() in seen:
            continue
        seen.add(seed.lower())
        seeds.append(seed)
        m = {"source_type": "tracklist"}
        cam = (e.get("camelot") or "").strip() or key_to_camelot(e.get("key", ""))
        if cam:
            m["camelot"] = cam
        if e.get("bpm"):
            m["bpm"] = e["bpm"]
        if e.get("year"):
            m["year"] = e["year"]
        meta[seed] = m
    return seeds, meta


def tracklist_candidates(path: str, per: int = 1, verify: bool = True) -> list[dict]:
    """Треклист → кандидаты: discover находит аудио, метаданные едут с сидами. Тонкий I/O."""
    seeds, meta = tracklist_to_seeds_with_meta(load_tracklist(path))
    return sd.seed_discover(seeds, per_artist=per, verify=verify, seed_meta=meta)


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Явный треклист (поиск/LLM) → кандидаты с метаданными")
    ap.add_argument("--tracklist", required=True, help="JSON [{artist,track,bpm?,camelot?,key?}] или текст 'Artist - Title'")
    ap.add_argument("--per", type=int, default=1)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", default="tracklist_candidates.json")
    args = ap.parse_args()
    cands = tracklist_candidates(args.tracklist, per=args.per, verify=not args.no_verify)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    with_cam = sum(1 for c in cands if (c.get("camelot") or "").strip())
    print(f"Треклист: {len(cands)} кандидатов ({with_cam} с готовым Camelot) → {args.out}")


if __name__ == "__main__":
    _main()
