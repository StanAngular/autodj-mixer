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
    """{"before": [sections whose previous bar has fewer than half of the kick's usual hits], "peak_without": True when the last home has none}"""
    L = _layers(trk, ("kick",))
    if not L: return None
    by = {}
    for br, st, d in _onset_db(next(iter(L.values())), trk.bars): by[br] = by.get(br, 0) + 1
    usual = float(np.median([v for v in by.values()] or [0])); out = []; homes = []
    from .chords import role_of
    for a, b, name, *_ in trk.tl:
        if role_of(name) == "home" and int(a) > 0:
            homes.append(name)
            if by.get(int(a) - 1, 0) < .5 * usual: out.append(name)
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
TASK = {"mood": "neutral", "limits": {}}
MOOD = {"soft": .6, "calm": .6, "ambient": .4, "neutral": 1.0, "club": 1.0, "hard": 1.2, "aggressive": 1.3}     # how much change / accent a task is expected to have
def set_task(mood=None, limits=None): TASK["mood"] = mood or "neutral"; TASK["limits"] = dict(limits or {})
def limit(name): return TASK["limits"].get(name, DEFAULT[name] * MOOD.get(TASK["mood"], 1.0))

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
