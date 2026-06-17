#!/usr/bin/env python3
"""
curation_bridge.py — мостик курация → микшер.

Берёт результат курации (curator_candidates.json — список треков в порядке
траектории, с youtube_url/artist/track/bpm/camelot/segment) и готовит вход для
микшера:
  • список URL для yt_download (скачивание → WAV + даунбиты),
  • готовый mix_config (TRACKS в ПОРЯДКЕ траектории, с реальными названиями,
    замапленные на video_id-файлы, которые создаёт yt_download),
  • рекомендацию по анализу: madmom (база, всегда) и нужен ли A1F (тяжёлый,
    опциональный) — по косвенным признакам пула.

Тяжёлые шаги (скачивание/аннотации/A1F/микс) — серверные; мостик их НЕ запускает
сам, а генерит файлы и печатает рекомендованные команды (как с xvfb — никаких
неявных тяжёлых/сетевых операций).

Чистый модуль (json/re). CLI:
  python3 curation_bridge.py curator_candidates.json --name mymix
"""
import json
import re

# Пороги рекомендации A1F (косвенные признаки) — прозрачны и настраиваемы
A1F_BPM_SPREAD = 16     # большой разброс BPM в миксе → сложные переходы
A1F_MIN_TRACKS = 12     # длинный микс → много переходов, структура важна


def extract_video_id(url: str) -> str:
    """11-символьный YouTube video_id из URL (зеркало curate_tracks). '' если нет."""
    if not url or "soundcloud.com" in url:
        return ""
    m = re.search(r'[?&]v=([0-9A-Za-z_-]{11})', url)
    if m:
        return m.group(1)
    m = re.search(r'(?:youtu\.be/|/embed/|/shorts/|/v/)([0-9A-Za-z_-]{11})', url)
    if m:
        return m.group(1)
    if re.fullmatch(r'[0-9A-Za-z_-]{11}', url.strip()):
        return url.strip()
    return ""


def _label(track: dict, fallback: str) -> str:
    """Короткое читаемое имя для TRACKS: track title (или artist - track). Без кавычек."""
    title = (track.get("track") or "").strip()
    artist = (track.get("artist") or "").strip()
    name = title if title else (artist or fallback)
    return re.sub(r'["\\]', "", name)[:48]


def extract_urls(candidates: list[dict]) -> list[str]:
    """URL для yt_download, в порядке траектории, только YouTube, без дублей."""
    seen, out = set(), []
    for t in candidates:
        url = t.get("youtube_url", "")
        vid = extract_video_id(url)
        if vid and vid not in seen:
            seen.add(vid)
            out.append(url)
    return out


def mix_config_entries(candidates: list[dict]) -> list[tuple]:
    """
    TRACKS-записи (label, '<vid>.wav', '<vid>.txt') в ПОРЯДКЕ траектории.
    Только треки с валидным video_id (их и скачает yt_download под этим именем).
    """
    entries, seen = [], set()
    for t in candidates:
        vid = extract_video_id(t.get("youtube_url", ""))
        if not vid or vid in seen:
            continue
        seen.add(vid)
        entries.append((_label(t, vid), f"{vid}.wav", f"{vid}.txt"))
    return entries


def render_mix_config(candidates: list[dict], wav_dir: str, ann_dir: str,
                      target_lufs: float = -14.0) -> str:
    """Сгенерировать содержимое mix_config_*.py из результата курации. Чистая функция."""
    lines = [
        "#!/usr/bin/env python3",
        '"""Авто-сгенерирован curation_bridge из результата курации (порядок траектории)."""',
        f'WAV_DIR = "{wav_dir}"',
        f'ANN_DIR = "{ann_dir}"',
        f"TARGET_LUFS = {target_lufs}",
        "",
        "TRACKS = [",
    ]
    for label, wav, txt in mix_config_entries(candidates):
        lines.append(f'    ({label!r}, {wav!r}, {txt!r}),')
    lines.append("]")
    return "\n".join(lines) + "\n"


def recommend_analysis(candidates: list[dict]) -> dict:
    """
    По косвенным признакам пула рекомендовать глубину анализа. Чистая функция.
    madmom (даунбиты) — всегда (база для warp/beatmatch микшера).
    A1F (структурный анализ) — тяжёлый; рекомендуем, если переходы нетривиальны:
      • многосегментный микс (journey), ИЛИ
      • большой разброс BPM (> A1F_BPM_SPREAD), ИЛИ
      • длинный микс (>= A1F_MIN_TRACKS треков).
    Иначе (короткий однородный набор) — madmom достаточно.
    Возвращает {madmom, a1f, reason}. Это РЕКОМЕНДАЦИЯ — финальное слово за оператором.
    """
    bpms = [t["bpm"] for t in candidates if t.get("bpm")]
    spread = (max(bpms) - min(bpms)) if len(bpms) >= 2 else 0
    segments = {t.get("segment", "") for t in candidates if t.get("segment")}
    n = len(candidates)

    reasons = []
    if len(segments) > 1:
        reasons.append(f"многосегментный микс ({len(segments)} сегм.)")
    if spread > A1F_BPM_SPREAD:
        reasons.append(f"разброс BPM {spread}")
    if n >= A1F_MIN_TRACKS:
        reasons.append(f"длинный микс ({n} тр.)")

    a1f = bool(reasons)
    if a1f:
        reason = "A1F рекомендуется: " + ", ".join(reasons)
    else:
        reason = f"A1F не нужен: короткий однородный набор ({n} тр., разброс BPM {spread})"
    # Режим A1F: fast (--skip-separation, CPU) когда A1F нужен. Полный Demucs —
    # только для вокал-интервалов, по metadata курации не определить → ручной выбор.
    a1f_mode = "fast" if a1f else "none"
    return {
        "madmom": True,
        "a1f": a1f,
        "a1f_mode": a1f_mode,
        "reason": reason,
        "note": "Полный Demucs (без --skip-separation) — вручную, для вокал-чувствительных миксов",
    }


def _main():
    import argparse
    import os
    ap = argparse.ArgumentParser(description="Мостик курация → микшер")
    ap.add_argument("candidates", help="curator_candidates.json")
    ap.add_argument("--name", default="mymix", help="имя микса (для файлов конфига)")
    ap.add_argument("--wav-dir", default="/opt/autodj-mixer/shared/tracks")
    ap.add_argument("--ann-dir", default="/opt/autodj-mixer/shared/ann")
    args = ap.parse_args()

    with open(args.candidates, encoding="utf-8") as f:
        candidates = json.load(f)
    if not isinstance(candidates, list) or not candidates:
        print("ОШИБКА: пустой или неверный curator_candidates.json")
        return

    urls = extract_urls(candidates)
    cfg_path = f"mix_config_{args.name}.py"
    urls_path = f"urls_{args.name}.txt"

    with open(urls_path, "w", encoding="utf-8") as f:
        f.write("\n".join(urls) + "\n")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(render_mix_config(candidates, args.wav_dir, args.ann_dir))

    rec = recommend_analysis(candidates)

    print(f"Треков: {len(candidates)}  |  URL: {len(urls)} → {urls_path}")
    print(f"mix_config → {cfg_path} (в порядке траектории, реальные названия)")
    print(f"\nАнализ: madmom — обязательно. {rec['reason']}")
    print("\nСледующие шаги (на сервере, под xvfb для headed-частей):")
    print(f"  python3 yt_download.py {urls_path}")
    print(f"  python3 batch_annotate.py            # madmom даунбиты → {args.ann_dir}")
    if rec["a1f"]:
        import a1f
        a1f_cmd = " ".join(a1f.a1f_command("<wav>", args.ann_dir, fast=True))
        print(f"  # A1F рекомендован (режим {rec['a1f_mode']}). Пример вызова на трек:")
        print(f"  {a1f_cmd}")
        print(f"  # {rec['note']}")
    print(f"  python3 run_pipeline.py --wav-dir {args.wav_dir} --ann-dir {args.ann_dir} --config {cfg_path}")


if __name__ == "__main__":
    _main()
