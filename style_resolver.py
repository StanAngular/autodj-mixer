#!/usr/bin/env python3
"""
style_resolver.py — офлайн-резолвер музыкальных стилей на дереве PulseRoots.

Первый (локальный, детерминированный) тир интеллекта стилей. Загружает
вендоренный data/pulseroots.genres.json (дерево электронных жанров, MIT,
github.com/Mendiak/pulse.roots) и отвечает на:

  • resolve(query)        → лучший канонический стиль + score уверенности
  • similar_styles(query) → смежные стили (родитель / соседи / подстили)
  • seed_artists(query)   → ключевые исполнители стиля (сид для «похожих»)

Если score ниже порога — вызывающий код эскалирует на следующие тиры
(Wikidata / MusicBrainz / LLM, Фаза B2). Без сети и тяжёлых зависимостей.

CLI:  python3 style_resolver.py "french touch"
"""
import argparse
import difflib
import json
import os
import re
from functools import lru_cache

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "pulseroots.genres.json")

# Порог уверенности: ниже него resolve() считает, что стиль не найден локально
DEFAULT_THRESHOLD = 0.6


def _node_name(node: dict) -> str:
    """Имя узла. Верхний уровень использует 'style', подстили — 'name'."""
    return node.get("style") or node.get("name") or ""


def _normalize(s: str) -> str:
    """Нормализация для сравнения: lower-case, без пунктуации, схлопнутые пробелы."""
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def _index(path: str = DATA_PATH):
    """
    Построить плоский индекс дерева. Возвращает список записей:
    {name, norm, node, parent, children:[names], depth}.
    Кэшируется (дерево неизменно в рамках процесса).
    """
    with open(path, encoding="utf-8") as f:
        tree = json.load(f)

    entries: list[dict] = []

    def walk(node: dict, parent: str, depth: int):
        name = _node_name(node)
        kids = [_node_name(s) for s in (node.get("substyles") or [])]
        entries.append({
            "name": name,
            "norm": _normalize(name),
            "node": node,
            "parent": parent,
            "children": kids,
            "depth": depth,
        })
        for s in (node.get("substyles") or []):
            walk(s, name, depth + 1)

    for top in tree:
        walk(top, "", 0)
    return entries


def _best_entry(query: str, path: str = DATA_PATH):
    """Найти лучшую запись индекса для запроса. Возвращает (entry, score)."""
    nq = _normalize(query)
    if not nq:
        return None, 0.0

    entries = _index(path)
    best, best_score = None, 0.0

    for e in entries:
        ne = e["norm"]
        if ne == nq:
            return e, 1.0                      # точное совпадение — сразу
        if nq in ne or ne in nq:
            score = 0.85                       # подстрока
        else:
            score = difflib.SequenceMatcher(None, nq, ne).ratio()
        if score > best_score:
            best, best_score = e, score

    return best, round(best_score, 3)


def resolve(query: str, threshold: float = DEFAULT_THRESHOLD,
            path: str = DATA_PATH) -> dict:
    """
    Разрешить свободный запрос стиля в канонический узел PulseRoots.

    Возвращает dict:
      matched: bool         — превышен ли порог уверенности
      style:   str          — канонический стиль (или исходный запрос если нет)
      score:   float        — уверенность 0..1
      parent:  str
      siblings: list[str]   — другие подстили того же родителя
      children: list[str]
      seed_artists: list[str]
      wikipedia: str
    """
    entry, score = _best_entry(query, path)
    if entry is None or score < threshold:
        return {
            "matched": False, "style": query, "score": score,
            "parent": "", "siblings": [], "children": [],
            "seed_artists": [], "wikipedia": "",
        }

    node = entry["node"]
    siblings: list[str] = []
    if entry["parent"]:
        for e in _index(path):
            if e["parent"] == entry["parent"] and e["name"] != entry["name"]:
                siblings.append(e["name"])

    artists = [a.get("name", "") for a in (node.get("key_artists") or []) if a.get("name")]

    return {
        "matched": True,
        "style": entry["name"],
        "score": score,
        "parent": entry["parent"],
        "siblings": siblings,
        "children": entry["children"],
        "seed_artists": artists,
        "wikipedia": node.get("wikipedia_url", ""),
    }


def similar_styles(query: str, path: str = DATA_PATH) -> list[str]:
    """Смежные стили: родитель + соседи + подстили (без самого запроса). Дедуп."""
    r = resolve(query, path=path)
    if not r["matched"]:
        return []
    out: list[str] = []
    if r["parent"]:
        out.append(r["parent"])
    out.extend(r["siblings"])
    out.extend(r["children"])
    seen, uniq = set(), []
    for s in out:
        if s and s != r["style"] and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def seed_artists(query: str, path: str = DATA_PATH) -> list[str]:
    """Ключевые исполнители найденного стиля (сид для поиска похожих)."""
    return resolve(query, path=path)["seed_artists"]


def _main():
    ap = argparse.ArgumentParser(description="PulseRoots style resolver")
    ap.add_argument("query", help="название стиля в свободной форме")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()

    r = resolve(args.query, threshold=args.threshold)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r["matched"]:
        print(f"\nСмежные стили: {', '.join(similar_styles(args.query)) or '—'}")


if __name__ == "__main__":
    _main()
