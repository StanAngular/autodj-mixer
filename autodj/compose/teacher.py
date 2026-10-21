"""Gemini as TEACHER, not as composer (P107 stage 6). The loop for every new track:
 (a) critique(): a TEXT draft of the score (sections, chords, hook, bass) is reviewed before any rendering;
 (b) ab_pick(): blind A/B between two sound candidates, asked twice with the order swapped (Gemini is noisy:
     disagreement = tie, not a random winner);
 (c) the 8-bar loop / full-track review (review.py) gets the same guide in its prompt;
 (d) every rule from Gemini and every verdict from Стас lands in style_guide.json and is prepended to all prompts.
Стас's rules and verdicts outrank Gemini's: they are listed first and are never replaced by a Gemini rule."""
import datetime, json, os, re, time, urllib.request
import numpy as np

GUIDE = os.environ.get("AUTODJ_STYLE_GUIDE", os.path.join(os.path.dirname(__file__), "style_guide.json"))
MODELS = ("gemini-3-flash-preview", "gemini-2.5-flash")

def _norm(s):
    return re.sub(r"[^\wа-яё]+", " ", s.lower()).strip()

def load(path=None):
    p = path or GUIDE
    return json.load(open(p)) if os.path.exists(p) else {"rules": [], "verdicts": []}

def save(g, path=None):
    p = path or GUIDE; tmp = p + ".tmp"
    json.dump(g, open(tmp, "w"), ensure_ascii=False, indent=1); os.replace(tmp, p)

def add_rule(text, source="gemini", genre="*", path=None, status=None):
    """dedupe by normalised text; returns True if new. A rule Gemini invents in a critique starts as "proposed"
    (the 2026-10-21 critique also invented rules like «each layer's release twice shorter»); "confirmed" after a
    check or a listening test; "rejected" rules stay in the file (so they are not re-added) but never reach a prompt."""
    g = load(path); n = _norm(text)
    if not n or any(_norm(r["text"]) == n for r in g["rules"]): return False
    g["rules"].append({"text": text.strip(), "source": source, "genre": genre, "added": datetime.date.today().isoformat(),
                       "status": status or ("confirmed" if source == "stas" else "proposed")}); save(g, path)
    return True

def set_status(substr, status, path=None):
    g = load(path); n = 0
    for r in g["rules"]:
        if _norm(substr) in _norm(r["text"]): r["status"] = status; n += 1
    save(g, path); return n

def add_verdict(track, verdict, note="", who="stas", path=None):
    g = load(path); g["verdicts"].append({"track": track, "who": who, "verdict": verdict, "note": note,
                                          "date": datetime.date.today().isoformat()}); save(g, path)

def guide_text(genre=None, path=None, max_rules=40, max_verdicts=8):
    """rules for the prompt: Стас first, then Gemini; genre-specific + general"""
    g = load(path); ok = lambda r: r.get("genre", "*") in ("*", genre) or genre is None
    st = lambda r: r.get("status", "confirmed")
    rs = sorted([r for r in g["rules"] if ok(r) and st(r) != "rejected"], key=lambda r: (r["source"] != "stas", st(r) == "proposed"))[:max_rules]
    tag = lambda r: "Стас" if r["source"] == "stas" else "учитель" if st(r) == "confirmed" else "учитель, не проверено"
    out = ["ПРАВИЛА (сначала от слушателя-заказчика, они главнее):"] + [f"- [{tag(r)}] {r['text']}" for r in rs]
    vs = [v for v in g["verdicts"] if v["who"] == "stas"][-max_verdicts:]
    if vs: out += ["ОТЗЫВЫ ЗАКАЗЧИКА на прошлые треки:"] + [f"- {v['track']}: {v['verdict']}{' — ' + v['note'] if v['note'] else ''}" for v in vs]
    return "\n".join(out)

def parse_rules(text):
    """lines 'ПРАВИЛО: ...' from a Gemini answer"""
    return [m.strip(" .") for m in re.findall(r"^\s*[-*]?\s*ПРАВИЛО:\s*(.+)$", text, re.M) if len(m.strip()) > 8]

# ---------------------------------------------------------------- Gemini calls
def _call(parts, key=None, models=MODELS, timeout=300):
    key = key or os.environ.get("GOOGLE_API_KEY"); err = "no GOOGLE_API_KEY"
    if not key: raise RuntimeError(err)
    body = json.dumps({"contents": [{"parts": parts}]}).encode()
    for m in models:
        for _ in range(2):
            try:
                req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}",
                                             data=body, headers={"Content-Type": "application/json"})
                return m, json.load(urllib.request.urlopen(req, timeout=timeout))["candidates"][0]["content"]["parts"][-1]["text"]
            except Exception as e:
                err = str(e); time.sleep(5)
    raise RuntimeError(err)

def describe_draft(title, bpm, key_name, sections, chords, hook=None, bass=None, extra=""):
    """compact text score. sections [(a, b, name, [layers])]; chords [str per bar or per 4 bars]; hook/bass
    [(step_abs, len16, midi[, vel])] over the first 8 bars"""
    nm = lambda m: ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][m % 12] + str(m // 12 - 1)
    def ev(xs):
        return " ".join(f"{x[0] // 16 + 1}.{x[0] % 16 + 1}:{nm(x[2])}/{x[1]}" + (f"@{x[3]}" if len(x) > 3 else "") for x in xs)
    lines = [f"Трек «{title}», {bpm} BPM, {key_name}.", "Части: " + "; ".join(f"такты {a + 1}-{b}: {n} ({', '.join(l)})" for a, b, n, l in sections),
             "Аккорды: " + " | ".join(chords)]
    if hook: lines.append("Хук (такт.шестнадцатая:нота/длина в 16-х): " + ev(hook))
    if bass: lines.append("Бас (такт.16-я:нота/длина@сила): " + ev(bass))
    if extra: lines.append(extra)
    return "\n".join(lines)

CRITIQUE = """Ты строгий учитель композиции электронной музыки. Звука ещё нет: перед тобой текстовая партитура черновика.
{guide}

ЧЕРНОВИК:
{draft}

Ответь по-русски:
1. Топ-5 проблем ИМЕННО сочинения (хук, гармония, бас, ритм, развитие), с тактами, и как исправить конкретно (какие ноты/шаги).
2. Что оставить как есть.
3. До 3 ОБЩИХ правил, которые пригодятся и для следующих треков (не про этот трек), каждое отдельной строкой в формате
ПРАВИЛО: <правило с числами>
Не повторяй правила, которые уже есть выше."""

def critique(draft, genre=None, path=None, learn=True, **kw):
    m, t = _call([{"text": CRITIQUE.format(guide=guide_text(genre, path), draft=draft)}], **kw)
    new = [r for r in parse_rules(t) if learn and add_rule(r, "gemini", genre or "*", path)]
    return {"model": m, "text": t, "new_rules": new}

AB = """Слепое сравнение двух звуков для трека. Вопрос: {question}
{guide}
Звук X первый, звук Y второй. Ответь двумя строками: причина (коротко), затем строго «ВЫБОР: X» или «ВЫБОР: Y»."""

def _audio_part(path, key=None):
    from .review import _upload
    mime = "audio/mpeg" if path.endswith(".mp3") else "audio/wav"
    return {"file_data": {"mime_type": mime, "file_uri": _upload(path, key or os.environ.get("GOOGLE_API_KEY"))}}

def ab_pick(a, b, question, genre=None, path=None, ask=None):
    """'a' | 'b' | 'tie'. Asked in both orders; only a consistent answer counts. `ask(first, second, prompt)->text`
    is injectable for tests; by default it uploads both files to Gemini."""
    p = AB.format(question=question, guide=guide_text(genre, path))
    ask = ask or (lambda x, y, pr: _call([_audio_part(x), _audio_part(y), {"text": pr}])[1])
    pick = lambda t: (re.findall(r"ВЫБОР:\s*([XYХ])", t) or ["?"])[-1].replace("Х", "X")
    r1 = pick(ask(a, b, p)); r2 = pick(ask(b, a, p))
    w1 = {"X": "a", "Y": "b"}.get(r1); w2 = {"X": "b", "Y": "a"}.get(r2)
    return w1 if w1 and w1 == w2 else "tie"

# ---------------------------------------------------------------- P108: short-clip ratings with order swap
RATE = """Оцени короткие звуковые отрывки (каждый 4-8 секунд) для трека. Задача: {question}
{guide}
Порядок отрывков случайный, номер ничего не значит. Оцени КАЖДЫЙ отрывок отдельно по шкалам от 1 до 10:
{scales}
Ответь строго, по одной строке на отрывок, в порядке прослушивания:
ОТРЫВОК 1: {fmt}
ОТРЫВОК 2: ...
Потом одну строку: что именно в лучшем отрывке звучит лучше."""
SCALES = {"живость": "звучит как сыгранный/записанный инструмент, а не как пресет (1 = пластик, 10 = живая запись)",
          "теплота": "мягкость, приятная сатурация, без резкого верха",
          "современность": "звучит как звук 2020-х в этом жанре, а не как 90-е/2010-е",
          "сочетание": "сочетается с остальными звуками отрывка (одна комната, не выпирает)"}

def _parse_rates(text, n, scales):
    out = {}
    for k, body in re.findall(r"ОТРЫВОК\s*(\d+)\s*:\s*([^\n]+)", text):
        k = int(k) - 1
        if 0 <= k < n: out[k] = {s: int(v) for s, v in re.findall(r"([а-яё]+)\s*=\s*(\d+)", body.lower()) if s in scales}
    return out

def rate_clips(clips, question, scales=("живость", "теплота", "современность", "сочетание"), genre=None, path=None, ask=None, seed=None, tol=2):
    """clips: list of audio paths (4-8 s). Asked twice: a random order, then the REVERSED order. A score counts only if
    both rounds agree within `tol` (Gemini prefers positions in A/B; rotation cancels that). Returns
    {"scores": [{scale: mean or None}], "total": [mean of reliable scales or None], "best": index or None, "agree": share}."""
    rng = np.random.default_rng(seed); n = len(clips); perm = [int(i) for i in rng.permutation(n)]
    p = RATE.format(question=question, guide=guide_text(genre, path), scales="\n".join(f"- {s}: {SCALES.get(s, '')}" for s in scales),
                    fmt="; ".join(f"{s}=N" for s in scales))
    ask = ask or (lambda files, pr: _call([_audio_part(f) for f in files] + [{"text": pr}])[1])
    rounds = []
    sh = max(1, n // 2); second = perm[sh:] + perm[:sh]                      # every clip moves to ANOTHER position
    for order in (perm, second):                                            # (plain reversal keeps the middle one put)
        got = _parse_rates(ask([clips[i] for i in order], p), n, scales)
        rounds.append({order[k]: v for k, v in got.items()})
    scores, agree, total_pairs = [], 0, 0
    for i in range(n):
        row = {}
        for s in scales:
            a, b = rounds[0].get(i, {}).get(s), rounds[1].get(i, {}).get(s)
            if a is None or b is None: row[s] = None; continue
            total_pairs += 1
            if abs(a - b) <= tol: row[s] = (a + b) / 2; agree += 1
            else: row[s] = None
        scores.append(row)
    total = [float(np.mean([v for v in r.values() if v is not None])) if any(v is not None for v in r.values()) else None for r in scores]
    ok = [(t, i) for i, t in enumerate(total) if t is not None]
    best = max(ok)[1] if ok and (len(ok) == 1 or sorted(ok)[-1][0] - sorted(ok)[-2][0] >= 1.0) else None   # a real margin
    return {"scores": scores, "total": total, "best": best, "agree": agree / total_pairs if total_pairs else 0.0, "order": perm}
