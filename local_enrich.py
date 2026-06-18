#!/usr/bin/env python3
"""
local_enrich.py — посчитать Camelot/BPM из аудио для треков без метаданных БД.

Зачем: Path B (посев по знанию — страна / андеграунд / редкое / новые релизы).
Такие треки не лежат в Beatport/Tunebat, поэтому Camelot берём НЕ из базы, а
считаем сами из скачанного WAV (`enrich_metadata.compute_key`, librosa-хрома +
Krumhansl). BPM добираем из A1F-json, если он есть. Это «самому смотреть камелот/
битрейт» из обсуждения — без зависимости от покрытия БД.

Встаёт в поток ПОСЛЕ скачивания: seed_discover → yt_download → local_enrich → bridge.
needs_local_key — чистая (тестируется офлайн); enrich_candidates — тонкий I/O,
переиспользует существующий compute_key.
"""
import json
import os
import re


def video_id(url: str) -> str:
    """11-символьный YouTube id из URL. '' если нет."""
    if not url:
        return ""
    m = re.search(r'[?&]v=([0-9A-Za-z_-]{11})', url) \
        or re.search(r'(?:youtu\.be/|/embed/|/shorts/|/v/)([0-9A-Za-z_-]{11})', url)
    if m:
        return m.group(1)
    if re.fullmatch(r'[0-9A-Za-z_-]{11}', url.strip()):
        return url.strip()
    return ""


def needs_local_key(track: dict) -> bool:
    """Нужно ли считать Camelot локально (его нет в метаданных). Чистая."""
    return not (track.get("camelot") or "").strip()


def enrich_candidates(candidates: list[dict], tracks_dir: str,
                      a1f_dir: str | None = None) -> tuple[list[dict], dict]:
    """
    Для кандидатов без Camelot — посчитать ключ из WAV (и BPM из A1F, если пусто).
    Меняет записи на месте, ставит camelot_source='local'. Тонкий I/O.
    """
    from enrich_metadata import compute_key      # переиспользуем существующий детектор
    stats = {"computed": 0, "skipped_has_key": 0, "no_wav": 0, "failed": 0}
    for t in candidates:
        if not needs_local_key(t):
            stats["skipped_has_key"] += 1
            continue
        vid = video_id(t.get("youtube_url", "")) or t.get("video_id", "")
        wav = os.path.join(tracks_dir, f"{vid}.wav") if vid else ""
        if not wav or not os.path.exists(wav):
            stats["no_wav"] += 1
            continue
        key, cam = compute_key(wav)
        if cam and cam != "?":
            t["key"] = key
            t["camelot"] = cam
            t["camelot_source"] = "local"
            stats["computed"] += 1
        else:
            stats["failed"] += 1
        # BPM из A1F, если пусто
        if not t.get("bpm") and a1f_dir and vid:
            ap = os.path.join(a1f_dir, f"{vid}.json")
            if os.path.exists(ap):
                try:
                    with open(ap, encoding="utf-8") as f:
                        bpm = json.load(f).get("bpm")
                    if bpm:
                        t["bpm"] = round(bpm)
                except (OSError, ValueError):
                    pass
    return candidates, stats


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Локальный расчёт Camelot/BPM из WAV")
    ap.add_argument("candidates", help="cand.json")
    ap.add_argument("--tracks-dir", default="shared/tracks")
    ap.add_argument("--a1f-dir", default="shared/a1f_results")
    ap.add_argument("--out", default=None, help="по умолчанию перезаписать вход")
    args = ap.parse_args()

    cands = json.load(open(args.candidates, encoding="utf-8"))
    cands, stats = enrich_candidates(cands, args.tracks_dir, args.a1f_dir)
    out = args.out or args.candidates
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    print(f"Локальный анализ: посчитан Camelot у {stats['computed']} "
          f"(уже был у {stats['skipped_has_key']}, нет WAV {stats['no_wav']}, "
          f"не определился {stats['failed']}). → {out}")


if __name__ == "__main__":
    _main()
