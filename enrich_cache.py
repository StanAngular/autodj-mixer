#!/usr/bin/env python3
"""
enrich_cache.py — дисковый кэш обогащения (artist+track → BPM/Camelot).

Главный выигрыш по скорости: Tunebat (headed-браузер, ~3-5с/трек) больше не
обрабатывает повторно те же треки между прогонами и сессиями. BPM/Camelot трека
стабильны (свойство самого трека), поэтому кэш не протухает.

Чистый модуль (json + файловый I/O). Ключ согласован с dedup_key из
curate_tracks: f"{artist.lower().strip()}|{track.lower().strip()}".
Кэш — runtime-данные, в репозиторий не коммитится (см. .gitignore).
"""
import json
import os

DEFAULT_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "enrich_cache.json")


def cache_key(artist: str, track: str) -> str:
    """Ключ кэша — зеркало dedup_key (consistency)."""
    return f"{(artist or '').lower().strip()}|{(track or '').lower().strip()}"


def load_cache(path: str = DEFAULT_CACHE_PATH) -> dict:
    """Загрузить кэш с диска. При отсутствии/повреждении — пустой dict."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict, path: str = DEFAULT_CACHE_PATH) -> bool:
    """Сохранить кэш на диск. Возвращает True при успехе."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        return True
    except OSError:
        return False


def cache_get(cache: dict, artist: str, track: str) -> dict | None:
    """Вернуть {bpm, camelot} из кэша или None."""
    return cache.get(cache_key(artist, track))


def cache_put(cache: dict, artist: str, track: str, bpm, camelot) -> bool:
    """
    Положить в кэш ТОЛЬКО полную запись (есть и BPM, и Camelot). Неполные не
    кэшируем — чтобы позже доискать. Возвращает True если записали.
    """
    if bpm and camelot:
        cache[cache_key(artist, track)] = {"bpm": bpm, "camelot": camelot}
        return True
    return False


def split_by_cache(tracks: list[dict], cache: dict):
    """
    Разделить треки на покрытые кэшем и нет. Чистая функция.
    Возвращает (hits, misses):
      hits  — список (track, bpm, camelot) для треков с полной записью в кэше;
      misses — треки, которых в кэше нет (нужен Tunebat).
    """
    hits, misses = [], []
    for t in tracks:
        c = cache.get(cache_key(t.get("artist", ""), t.get("track", "")))
        if c and c.get("bpm") and c.get("camelot"):
            hits.append((t, c["bpm"], c["camelot"]))
        else:
            misses.append(t)
    return hits, misses
