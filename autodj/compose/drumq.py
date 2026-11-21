"""P154 (2026-11-21, audit 2): drum hits are MEASURED before they are chosen. Slate Harbor's kick (Kurzweil Kit 07 Kick03) «бьёт по мозгам, острый,
резкий»: CLAP ranked it 6th of 7, fresh.pick took it because it was the least used, and nothing measured a drum hit (soundgate judges pitch only).

  features(path)     amplitude centroid (Hz), hf (dB of the power above 2 kHz), sub (power share < 120 Hz), crest (peak / rms, dB),
                     atk (share of the first 10 ms above 3 kHz), tail (s to -40 dB); cached in shared/drum_quality.json
  problems(m, role)  why a hit is too sharp for its role (LIMITS); [] = fine
  ok(path, role)     no problems
  report(sources)    {file: reasons} for the kick / clap / snare sources of a render (problem lines in the summary, not a hard gate yet)

Calibration (2026-11-21): kicks WART_Kick_5/9, WATE_Kick_05/07, WAFTH_Kick_04/07, WATS_Kick_03/04, Roland System100 BD-08: crest 6.5-12.2 dB;
Kurz07-Kick03 (rejected by ear) 21.0, Kurz08-Kick01 16.0. Claps: LM-2 clap (accepted) atk 0.011, centroid 2904; K04DHit-02 (rejected: «очень острый») atk 0.71,
centroid 4840. One listener and ten files: the limits are a start, P161 will set them from references."""
import json, os
import numpy as np

LIMITS = {"kick": {"crest": 14.0}, "clap": {"crest": 24.0, "atk": .4, "cen": 4200.0}, "snare": {"crest": 24.0, "atk": .45, "cen": 4500.0}}
ROLE_OF = {"kick": "kick", "backbeat": "clap"}                 # fresh.drum_class -> LIMITS key
CACHE = "/opt/autodj-mixer/shared/drum_quality.json"
def cache_path(): return os.environ.get("AUTODJ_DRUM_QUALITY") or CACHE
_MEM = {}

def _db():
    p = cache_path()
    if p not in _MEM:
        try: _MEM[p] = json.load(open(p))
        except (OSError, ValueError): _MEM[p] = {}
    return _MEM[p]

def measure_signal(x, sr):
    x = np.asarray(x, np.float32); x = x.mean(1) if x.ndim == 2 else x
    if sr != 44100:
        from scipy.signal import resample_poly
        x = resample_poly(x, 44100, sr).astype(np.float32); sr = 44100
    a = np.abs(x)
    if not len(x) or a.max() < 1e-5: return {"error": "silent"}
    i0 = int(np.argmax(a > a.max() * .05)); x = x[i0:i0 + sr]
    nf = 1 << 16; S = np.abs(np.fft.rfft(x * np.hanning(len(x)), nf)) ** 2; f = np.fft.rfftfreq(nf, 1 / sr); M = np.sqrt(S)
    n = max(64, int(.01 * sr)); A = np.abs(np.fft.rfft(x[:n] * np.hanning(min(n, len(x))) if len(x) >= n else x, 4096)) ** 2; fa = np.fft.rfftfreq(4096, 1 / sr)
    env = 20 * np.log10(np.abs(x) / (np.abs(x).max() + 1e-12) + 1e-9); rms = float(np.sqrt((x ** 2).mean()))
    return {"cen": round(float((M * f).sum() / (M.sum() + 1e-12))), "hf": round(float(10 * np.log10(S[f > 2000].sum() / (S.sum() + 1e-12) + 1e-12)), 1),
            "sub": round(float(S[f < 120].sum() / (S.sum() + 1e-12)), 2), "crest": round(float(20 * np.log10(np.abs(x).max() / (rms + 1e-12))), 1),
            "atk": round(float(A[fa > 3000].sum() / (A.sum() + 1e-12)), 3), "tail": round(float(np.max(np.where(env > -40)[0]) / sr), 3)}

def features(path):
    import soundfile as sf
    k = os.path.basename(str(path)); db = _db()
    if k not in db:
        try: x, sr = sf.read(str(path), dtype="float32", always_2d=True); db[k] = measure_signal(x, sr)
        except Exception as e: db[k] = {"error": type(e).__name__}
        try:
            p = cache_path(); os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True); json.dump(db, open(p + ".tmp", "w"), indent=0); os.replace(p + ".tmp", p)
        except OSError: pass
    return db[k]

# ---- P161 (Стас: «пороги не только из референсов, гибко исходя из задачи»): the limits are resolved PER TASK -----------------------------------
MOOD_SCALE = {"soft": .8, "calm": .8, "ambient": .7, "neutral": 1.0, "club": 1.0, "hard": 1.35, "aggressive": 1.5}
TASK = {"mood": "neutral", "refs": {}, "limits": {}}
def set_task(mood=None, refs=None, limits=None, style=None, profile=None):
    """the task of this render: mood (MOOD_SCALE: soft / calm / ambient stricter, hard / aggressive looser), refs = {role: [reference hit files or feature dicts]}
    (the limit becomes what the references do + REF_HEADROOM: a task that wants a sharp hit is allowed one), limits = {role: {axis: value}} explicit
    numbers for this task; all optional. style / profile belong to rhythm.set_task and are accepted (META["task"] is shared) and ignored here.
    Called by run.py from META["task"]; set_task() resets to the defaults."""
    TASK["mood"] = mood or "neutral"; TASK["limits"] = {r: dict(v) for r, v in (limits or {}).items()}; TASK["refs"] = {}
    for role, xs in (refs or {}).items():
        ms = [x if isinstance(x, dict) else features(x) for x in (xs if isinstance(xs, (list, tuple)) else [xs])]; TASK["refs"][role] = [m for m in ms if m and not m.get("error")]

REF_HEADROOM = 1.15
def limits(role, task=None):
    """{axis: max} for the role under the task: defaults x mood, then what the references of the task do (+15 %), then explicit limits"""
    t = task or TASK; base = LIMITS.get(role)
    if not base: return {}
    k = MOOD_SCALE.get(t.get("mood") or "neutral", 1.0); out = {ax: v * k for ax, v in base.items()}
    for ax in out:
        vals = [m[ax] for m in (t.get("refs") or {}).get(role, []) if m.get(ax) is not None]
        if vals: out[ax] = max(vals) * REF_HEADROOM
    out.update((t.get("limits") or {}).get(role, {})); return out

def problems(m, role, task=None):
    """reasons a hit is too sharp for the role (kick / clap / snare) under the task (limits()); unknown role or unmeasured -> []"""
    lim = limits(role, task)
    if not lim or not m or m.get("error"): return []
    out = []
    if "crest" in lim and m["crest"] > lim["crest"]: out.append(f"острый пик: crest {m['crest']} дБ > {lim['crest']}")
    if "atk" in lim and m["atk"] > lim["atk"]: out.append(f"резкая атака: {m['atk']:.0%} энергии первых 10 мс выше 3 кГц > {lim['atk']:.0%}")
    if "cen" in lim and m["cen"] > lim["cen"]: out.append(f"слишком ярко: центроид {m['cen']} Гц > {lim['cen']:.0f}")
    return out

def ok(path, role, task=None): return not problems(features(path), role, task)

def report(sources):
    """{file: reasons} for kick / clap / snare sources (by file name class, fresh.PATHS gives the file) that are too sharp"""
    from . import fresh
    out = {}
    for s in sources or []:
        name = os.path.basename(str(s)); role = ROLE_OF.get(fresh.drum_class(name) or "")
        if role == "clap" and "snare" in name.lower(): role = "snare"
        path = s if os.path.isabs(str(s)) else fresh.PATHS.get(name)
        if not role or not path or not os.path.exists(path): continue
        r = problems(features(path), role)
        if r: out[name] = r
    return out
