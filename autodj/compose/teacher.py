"""Gemini as TEACHER, not as composer (P107 stage 6). The loop for every new track:
 (a) critique(): a TEXT draft of the score (sections, chords, hook, bass) is reviewed before any rendering;
 (b) ab_pick(): blind A/B between two sound candidates, asked twice with the order swapped (Gemini is noisy:
     disagreement = tie, not a random winner);
 (c) the 8-bar loop / full-track review (review.py) gets the same guide in its prompt;
 (d) every rule from Gemini and every verdict from Стас lands in style_guide.json and is prepended to all prompts.
Стас's rules and verdicts outrank Gemini's: they are listed first and are never replaced by a Gemini rule."""
import datetime, json, os, re, time, urllib.request

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

def add_rule(text, source="gemini", genre="*", path=None):
    """dedupe by normalised text; returns True if new"""
    g = load(path); n = _norm(text)
    if not n or any(_norm(r["text"]) == n for r in g["rules"]): return False
    g["rules"].append({"text": text.strip(), "source": source, "genre": genre, "added": datetime.date.today().isoformat()}); save(g, path)
    return True

def add_verdict(track, verdict, note="", who="stas", path=None):
    g = load(path); g["verdicts"].append({"track": track, "who": who, "verdict": verdict, "note": note,
                                          "date": datetime.date.today().isoformat()}); save(g, path)

def guide_text(genre=None, path=None, max_rules=40, max_verdicts=8):
    """rules for the prompt: Стас first, then Gemini; genre-specific + general"""
    g = load(path); ok = lambda r: r.get("genre", "*") in ("*", genre) or genre is None
    rs = sorted([r for r in g["rules"] if ok(r)], key=lambda r: r["source"] != "stas")[:max_rules]
    out = ["ПРАВИЛА (сначала от слушателя-заказчика, они главнее):"] + [f"- [{'Стас' if r['source'] == 'stas' else 'учитель'}] {r['text']}" for r in rs]
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
