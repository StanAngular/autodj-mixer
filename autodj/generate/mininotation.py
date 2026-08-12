#!/usr/bin/env python3
"""
mininotation.py — S2: паттерн-язык в стиле Strudel/TidalCycles.

Зачем (диагноз «сочиняет средне»): у нас паттерны статичны — заданы списком и
повторяются без изменений, аккорды меняются раз в 8 тактов. В live-coding языках
вариативность встроена В САМУ ЗАПИСЬ паттерна, поэтому музыка «дышит» без ручной
аранжировки каждой секции.

Поддержано (подмножество мини-нотации):
    "bd sd bd sd"       — 4 события на цикл, равномерно
    "bd ~ sd ~"         — ~ или - это пауза
    "bd*2 sd"           — *n: событие дробится на n быстрых повторов
    "bd!3 sd"           — !n: событие повторяется n раз (занимает n слотов)
    "<bd sd> hh"        — <a b>: чередование ПО ЦИКЛАМ (цикл 0 → bd, цикл 1 → sd)
    "[bd sd] hh"        — [..]: подгруппа в один слот
    "bd? sd"            — ?: событие играет с вероятностью 50% (сид детерминирован)
    "x - - x - - x -"   — struct-строка: x = удар, - = пауза

Выход — список событий на ОДИН цикл: [{"value": str, "start": 0..1, "dur": 0..1}].
Чистые функции, без numpy/аудио — тестируются офлайн.
"""
from __future__ import annotations

import random
import re

REST = {"~", "-", "_", "."}


def _split_top(s: str) -> list[str]:
    """Разбить строку по пробелам верхнего уровня (учитывая [] и <>). Чистая."""
    out, depth, cur = [], 0, ""
    for ch in s.strip():
        if ch in "[<":
            depth += 1
        elif ch in "]>":
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _expand_repeats(tokens: list[str]) -> list[str]:
    """`x!3` → три слота. Чистая."""
    out = []
    for t in tokens:
        m = re.fullmatch(r"(.+?)!(\d+)", t)
        if m:
            out.extend([m.group(1)] * int(m.group(2)))
        else:
            out.append(t)
    return out


def parse_pattern(pattern: str, cycle: int = 0, seed: int = 0) -> list[dict]:
    """Мини-нотация → события одного цикла. cycle управляет <a b>-чередованием,
    seed — детерминизм для `?`. Чистая (при фиксированных cycle/seed)."""
    tokens = _expand_repeats(_split_top(pattern))
    if not tokens:
        return []
    rng = random.Random((seed << 8) ^ cycle)
    step = 1.0 / len(tokens)
    events: list[dict] = []

    for i, tok in enumerate(tokens):
        start = i * step
        # <a b c> — выбор по номеру цикла
        if tok.startswith("<") and tok.endswith(">"):
            alts = _split_top(tok[1:-1])
            tok = alts[cycle % len(alts)] if alts else "~"
        # x? — вероятностное событие
        if tok.endswith("?"):
            tok = tok[:-1]
            if rng.random() < 0.5:
                continue
        # x*n — дробление слота
        mul = 1
        m = re.fullmatch(r"(.+?)\*(\d+)", tok)
        if m:
            tok, mul = m.group(1), int(m.group(2))
        # [a b] — подгруппа внутри слота
        if tok.startswith("[") and tok.endswith("]"):
            sub = parse_pattern(tok[1:-1], cycle, seed)
            for e in sub:
                events.append({"value": e["value"],
                               "start": start + e["start"] * step,
                               "dur": e["dur"] * step})
            continue
        if tok in REST or not tok:
            continue
        for k in range(mul):
            events.append({"value": tok,
                           "start": start + k * step / mul,
                           "dur": step / mul})
    return events


def struct_events(struct: str, cycle: int = 0, seed: int = 0) -> list[float]:
    """`"x - - x - x - -"` → позиции ударов в долях цикла (0..1). Чистая."""
    return [e["start"] for e in parse_pattern(struct, cycle, seed) if e["value"] == "x"]


def pattern_to_times(pattern: str, cycles: int, cycle_sec: float,
                     seed: int = 0) -> list[tuple[float, str, float]]:
    """Развернуть паттерн на N циклов → [(время_сек, значение, длительность_сек)].
    Чередование <a b> и `?` дают РАЗНЫЙ результат в разных циклах — та самая
    встроенная вариативность. Чистая."""
    out = []
    for c in range(cycles):
        base = c * cycle_sec
        for e in parse_pattern(pattern, cycle=c, seed=seed):
            out.append((base + e["start"] * cycle_sec, e["value"], e["dur"] * cycle_sec))
    return out
