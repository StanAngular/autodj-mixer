"""P162 + P163 (2026-11-21, audit 3 «Rhythm & Drive»): the rhythm of a render is MEASURED, and a recording is placed by its attack.

  onset_samples(x)        samples of silence before the attack (first |x| above ONSET_FRAC of the peak); Track.place(align="onset") uses it
  onset_latency(path)     the same in seconds for a file, cached by (path, size, mtime) in shared/onset_cache.json (env AUTODJ_ONSET_CACHE), never recomputed
  latency_report(...)     drum sources whose attack lies > LATENCY_MS after the start of the file and that the track did not align
  section_density(trk)    onsets per bar of the drum layers per section + the range (a track whose density never changes has no felt change of speed)
  accent_contrast(trk)    spread (dB, 10th..90th percentile) of the hat layers' hits: ~0 dB = every hit the same, the sound of a drum machine
  kick_spread(trk)        standard deviation (dB) of the kick hits
  dropouts(trk)           bars before a home / peak where the kick breathes out (fewer than half its hits)
  timing(trk)             from the Ensemble log: mean offset per role (ms) and the measured swing (odd - even, as a share of a 16th), sd of the anchor
  report(trk, sources)    all of it -> summary["rhythm_drive"] and notes["rhythm_notes"] (Russian, REPORT ONLY: no gate until Стас has heard the thresholds)
Thresholds are first guesses from one track and ~14 references; flexible per task (rhythm.set_task(mood=, limits=) like drumq.set_task)."""
import hashlib, json, os
import numpy as np

ONSET_FRAC = .05; LATENCY_MS = 5.0
CACHE = "/opt/autodj-mixer/shared/onset_cache.json"
def cache_path(): return os.environ.get("AUTODJ_ONSET_CACHE") or CACHE
_MEM = {}

def onset_samples(x, frac=ONSET_FRAC):
    """samples before the first |x| >= frac * peak (0 for silence or an attack at the very start)"""
    a = np.abs(np.asarray(x)); a = a.max(1) if a.ndim == 2 else a
    return 0 if not len(a) or a.max() <= 1e-6 else int(np.argmax(a >= a.max() * frac))

def _key(path):
    """path + size + mtime + a hash of the first 64 KB (a file rewritten within the timestamp resolution is still seen as another file)"""
    st = os.stat(path)
    with open(path, "rb") as f: head = hashlib.sha1(f.read(65536)).hexdigest()
    return hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}|{head}".encode()).hexdigest()[:20]

def _db():
    p = cache_path()
    if p not in _MEM:
        try: _MEM[p] = json.load(open(p))
        except (OSError, ValueError): _MEM[p] = {}
    return _MEM[p]

def onset_latency(path):
    """seconds from the start of the file to its attack; cached by the file's path + size + mtime (a changed file is measured again)"""
    import soundfile as sf
    try: k = _key(path)
    except OSError: return None
    db = _db()
    if k not in db:
        x, sr = sf.read(str(path), dtype="float32", always_2d=True); db[k] = round(onset_samples(x) / sr, 5)
        try:
            p = cache_path(); os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True); json.dump(db, open(p + ".tmp", "w")); os.replace(p + ".tmp", p)
        except OSError: pass
    return db[k]

def latency_report(sources, aligned=False):
    """[(file, ms)] of kick / backbeat / hat sources whose attack is later than LATENCY_MS after the file start (empty when the track aligns by attack)"""
    from . import fresh
    if aligned: return []
    out = []
    for s in sources or []:
        name = os.path.basename(str(s)); path = s if os.path.isabs(str(s)) else fresh.PATHS.get(name)
        if fresh.drum_class(name) not in ("kick", "backbeat", "hat", "shaker", "perc") or not path or not os.path.exists(path): continue
        l = onset_latency(path)
        if l is not None and l * 1000 > LATENCY_MS: out.append((name, round(l * 1000, 1)))
    return out

# ---- measures from what the layers played (trk.act: step x band energy) ------------------------------------------------------------------------
def _onset_db(E, bars):
    """per layer: (bar, step, dB) of every onset (depth.onsets rule: a rise of >= 6 dB to within 20 dB of the layer's loudest step)"""
    e = 10 * np.log10(np.asarray(E, float)[:bars * 16].sum(1) + 1e-20); pk = e.max(); prev = np.concatenate([[-99.0], e[:-1]]); on = np.where((e - pk > -20) & (e - prev > 6))[0]
    return [(int(i) // 16, int(i) % 16, float(e[i])) for i in on]

def _layers(trk, classes):
    from .fresh import drum_class
    return {n: E for n, E in (getattr(trk, "act", {}) or {}).items() if E is not None and drum_class(n) in classes}

def section_density(trk):
    """{"per_bar": {section: drum onsets per bar}, "range": max - min, "mean": mean}"""
    L = _layers(trk, ("kick", "backbeat", "hat", "shaker", "perc"))
    if not L: return None
    ons = [x for E in L.values() for x in _onset_db(E, trk.bars)]; out = {}
    for a, b, name, *_ in trk.tl:
        n = int(b) - int(a)
        if n > 0: out[name] = round(sum(1 for br, st, d in ons if a <= br < b) / n, 2)
    v = list(out.values())
    return {"per_bar": out, "range": round(max(v) - min(v), 2), "mean": round(float(np.mean(v)), 2)} if v else None

def accent_contrast(trk):
    """{layer: dB between the 10th and 90th percentile of its hits} for the hat / shaker layers"""
    out = {}
    for n, E in _layers(trk, ("hat", "shaker")).items():
        d = [x[2] for x in _onset_db(E, trk.bars)]
        if len(d) >= 16: out[n] = round(float(np.percentile(d, 90) - np.percentile(d, 10)), 1)
    return out

def kick_spread(trk):
    for n, E in _layers(trk, ("kick",)).items():
        d = [x[2] for x in _onset_db(E, trk.bars)]
        if len(d) >= 16: return round(float(np.std(d)), 2)
    return None

def dropouts(trk):
    """{"before": [sections whose previous bar has its kick hits in the second half (steps 8-14) cut to half or less of the usual count], "peak_without": True when the last home has none}"""
    L = _layers(trk, ("kick",))
    if not L: return None
    by = {}
    for br, st, d in _onset_db(next(iter(L.values())), trk.bars):
        if 8 <= st <= 14: by[br] = by.get(br, 0) + 1                                     # the soft pickup on step 15 does not count as the beat
    usual = float(np.median([by.get(b, 0) for b in range(trk.bars)] or [0])); out = []; homes = []
    from .chords import role_of
    for a, b, name, *_ in trk.tl:
        if role_of(name) == "home" and int(a) > 0:
            homes.append(name)
            if usual > 0 and by.get(int(a) - 1, 0) <= .5 * usual: out.append(name)
    return {"before": out, "peak_without": bool(homes) and homes[-1] not in out, "usual_hits_per_bar": round(usual, 1)}

def timing(trk):
    """from Ensemble.log: {role: mean offset ms} and {role: measured swing = (mean odd - mean even offset) / 16th} and the standard deviation of the kick"""
    mt = getattr(trk, "microtiming", None); log = getattr(mt, "log", None)
    if not log: return None
    s16 = trk.S16 * 1000; by = {}
    for role, br, st, ms in log: by.setdefault(role, {"e": [], "o": []})["o" if st % 2 else "e"].append(ms)
    mean = {r: round(float(np.mean(v["e"] + v["o"])), 1) for r, v in by.items()}
    sw = {r: round(float((np.mean(v["o"]) - np.mean(v["e"])) / s16), 3) for r, v in by.items() if v["o"] and v["e"]}
    k = by.get("kick"); return {"mean_ms": mean, "swing": sw, "kick_sd_ms": round(float(np.std(k["e"] + k["o"])), 2) if k else None, "version": getattr(mt, "version", 1)}

# ---- the task (flexible thresholds) -----------------------------------------------------------------------------------------------------------
DEFAULT = {"density_range_min": .12, "hat_contrast_min_db": 1.5, "kick_spread_min_db": .8}
TASK = {"mood": "neutral", "limits": {}, "profile": None}
MOOD = {"soft": .6, "calm": .6, "ambient": .4, "neutral": 1.0, "club": 1.0, "hard": 1.2, "aggressive": 1.3}     # how much change / accent a task is expected to have
PROFILE_KEYS = {"density_range_min": "density_range_min", "hat_contrast_min_db": "hat_contrast_min_db", "kick_spread_min_db": "kick_spread_db"}
def set_task(mood=None, limits=None, style=None, profile=None):
    """P167: style (rhythm_profiles) makes the thresholds those of that style (mood scales them), profile = overrides of its keys, limits = explicit numbers (win)"""
    TASK["mood"] = mood or "neutral"; TASK["limits"] = dict(limits or {}); TASK["profile"] = None
    if style:
        from .rhythm_profiles import profile as _p; TASK["profile"] = _p(style, mood, **(profile or {}))
def limit(name):
    if name in TASK["limits"]: return TASK["limits"][name]
    pr = TASK.get("profile")
    if pr and name in PROFILE_KEYS: return pr[PROFILE_KEYS[name]] * (.8 if name == "kick_spread_min_db" else 1.0)     # the report warns below 80 % of the style's expected kick spread
    return DEFAULT[name] * MOOD.get(TASK["mood"], 1.0)

def report(trk, sources=None):
    """-> (dict for summary["rhythm_drive"], [Russian notes])"""
    d = {"density": section_density(trk), "hat_contrast_db": accent_contrast(trk), "kick_spread_db": kick_spread(trk), "dropouts": dropouts(trk), "timing": timing(trk),
         "latency_ms": latency_report(sources, aligned=bool(getattr(trk, "align", None) == "onset" or getattr(trk, "aligned", 0)))}
    notes = []
    de = d["density"]
    if de and len(de["per_bar"]) >= 4 and de["mean"] > 0 and de["range"] / de["mean"] < limit("density_range_min"): notes.append(f"плотность ударных почти не меняется между секциями (разброс {de['range']} при среднем {de['mean']} онсета на такт): нет ощущения смены скорости, меняй плотность перкуссии и хэтов по энергии")
    for n, c in d["hat_contrast_db"].items():
        if c < limit("hat_contrast_min_db"): notes.append(f"хэты «{n}»: все удары одной силы (контраст {c} дБ): звук драм-машины, нужны акценты и разная длина")
    if d["kick_spread_db"] is not None and d["kick_spread_db"] < limit("kick_spread_min_db"): notes.append(f"бочка ровная: разброс громкости ударов {d['kick_spread_db']} дБ")
    dr = d["dropouts"]
    if dr and dr["peak_without"]: notes.append("перед пиком нет провала бочки: вдох на 2-4 доли даёт входу больше энергии, чем новый слой")
    for n, ms in d["latency_ms"]: notes.append(f"{n}: атака в файле на {ms} мс позже начала, партитура не выровняла по атаке (Track.align = \"onset\"): удар опаздывает")
    t = d["timing"]
    if t and t["version"] >= 2 and t["kick_sd_ms"] not in (None, 0.0): notes.append(f"бочка не на сетке: sd {t['kick_sd_ms']} мс")
    return d, notes

# ---- P164: the checklist of the six questions of the «Rhythm & Drive» block, answered for every render -----------------------------------------
def checklist(trk, summ=None, rep=None):
    """[(question, status, text)] status ok / warn / unknown: the six questions of the audit block (felt tempo, spring, parts together, dynamics, plastic drums, style accuracy).
    summ: the render summary (kick_bass, top); rep: the dict of report(trk). Only reports: no gate until Стас has heard the thresholds."""
    summ = summ or {}; rep = rep or report(trk, None)[0]; out = []; de = rep.get("density"); pr = TASK.get("profile")
    if de and len(de["per_bar"]) >= 2 and de["mean"] > 0:
        r = de["range"] / de["mean"]; lo = min(de["per_bar"], key=de["per_bar"].get); hi = max(de["per_bar"], key=de["per_bar"].get)
        out.append(("1 Ощущаемый темп и пульс", "ok" if r >= limit("density_range_min") else "warn", f"плотность ударных от {de['per_bar'][lo]} ({lo}) до {de['per_bar'][hi]} ({hi}) онсета на такт, разброс {r:.0%} при ожидании от {limit('density_range_min'):.0%}"))
    else: out.append(("1 Ощущаемый темп и пульс", "unknown", "нет данных по ударным слоям"))
    t = rep.get("timing")
    if t and t["swing"]:
        sw = t["swing"].get("hats") if t["swing"].get("hats") is not None else max(t["swing"].values()); want = pr["swing"] if pr else None
        ok = sw >= .02 if want is None else abs(sw - want) <= .05
        out.append(("2 Пружина, свинг, микротайминг", "ok" if ok else "warn", f"измеренный свинг хэтов {sw:.0%} 16-й" + (f", профиль стиля {want:.0%}" if want is not None else "") + f", микротайминг версии {t['version']}" + (f", sd бочки {t['kick_sd_ms']} мс" if t["kick_sd_ms"] is not None else "")))
    else: out.append(("2 Пружина, свинг, микротайминг", "unknown" if not t else "warn", "партитура не пишет тайминг через Ensemble: свинг и сдвиги не измеримы" if not t else "свинг не обнаружен: сетка ровная"))
    kb = summ.get("kick_bass")
    out.append(("3 Kick, bass, клэп, перкуссия вместе", "unknown" if kb is None else ("ok" if kb <= .5 else "warn"), "доля нот баса на ударах бочки: " + ("нет данных" if kb is None else f"{kb:.0%}")))
    ks = rep.get("kick_spread_db"); dr = rep.get("dropouts"); bad = []
    if ks is not None and ks < limit("kick_spread_min_db"): bad.append(f"бочка ровная ({ks} дБ)")
    if dr and dr["peak_without"]: bad.append("нет вдоха перед пиком")
    out.append(("4 Динамика ритм-секции", "warn" if bad else ("unknown" if ks is None and not dr else "ok"), "; ".join(bad) if bad else f"разброс бочки {ks} дБ, вдох перед пиком есть" if ks is not None else "нет данных"))
    hc = rep.get("hat_contrast_db") or {}; top = summ.get("top") or {}; bad = [f"хэты «{n}»: контраст {c} дБ" for n, c in hc.items() if c < limit("hat_contrast_min_db")]
    if top and top.get("hat_share_of_top", 0) > .4 and top.get("top_vs_body_db", -99) > -10: bad.append("хэты занимают верх")
    out.append(("5 Однообразные / пластиковые ударные", "warn" if bad else ("ok" if hc else "unknown"), "; ".join(bad) if bad else "акценты хэтов есть" if hc else "хэтов в данных нет"))
    fam = pr["kick_family"] if pr else None
    if fam and trk is not None and getattr(trk, "act", None):
        from .chords import role_of
        L = _layers(trk, ("kick",)); by = {}
        for E in L.values():
            for br, st, d in _onset_db(E, trk.bars): by[br] = by.get(br, 0) + 1
        homes = [b for a, e_, n_, *_ in trk.tl if role_of(n_) == "home" for b in range(int(a), int(e_))]; per = float(np.mean([by.get(b, 0) for b in homes])) if homes else None
        if per is not None:
            ok = per >= 3.4 if fam == "four" else (per <= 3.2 if fam in ("two_step", "half", "broken") else per <= 1.5)
            out.append(("6 Ритм соответствует стилю", "ok" if ok else "warn", f"стиль {pr['style']}: семейство бочки «{fam}», в home {per:.1f} ударов на такт"))
        else: out.append(("6 Ритм соответствует стилю", "unknown", "нет секций home"))
    else: out.append(("6 Ритм соответствует стилю", "unknown", "стиль не задан (META[\"task\"][\"style\"])"))
    return out

def checklist_text(cl):
    mark = {"ok": "✓", "warn": "⚠", "unknown": "?"}; return "\n".join(f"{mark[s]} {q}: {t}" for q, s, t in cl)
