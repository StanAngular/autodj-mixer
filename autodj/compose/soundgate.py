"""P139 (2026-11-17, Стас про indie dance A: «мотив и гармония интересные, но звуки, тональность, громкость подобраны плохо»).
Claw measured it: the track picked every sound with fresh.pick (= least used, no quality), the bass alternated two different one-shots
(one noisy detuned unison, one wobbling ±35 cents), the pad was played 10 st away from its own note. Of 17 W.A. bass shots only 3 are pitch-clean.
This module is the missing step «judge the sound before it is used», cheap (lazy, one ~1 s measure per file, cached) and role-aware:

  measure(path)            cents (median pitch vs the nearest semitone), wobble (pitch spread in cents), noise (flatness), kind note/dyad/chord, root (MIDI)
  quality(m, role)         0..1 (1 = clean single stable note); hard-bad if wobble > 20 c or noise > .1 (a detuned unison / a noise burst), soft penalties for the rest
  pick(candidates, role, lo, hi, rng, db, title, k)   cleanest-first among files whose root fits the note range (window), FRESHNESS INSIDE that:
                           fresh.pick(..., quality=...) so a great sound unused for long may come back, a mediocre new one does not win by being new
  window(kc) / fits(kc, lo, hi) / needs_multisample(kc, lo, hi)   the register a one-shot may serve (±7 st): give it to plan.voicings / plan.bass; wider -> multisample
  report(sources)          the gate: which sources of a render are hard-bad (used by ears.gate_failures via run.py)
Cache: shared/sound_quality.json (override AUTODJ_SOUND_QUALITY)."""
import json, os, glob
import numpy as np

CACHE = os.environ.get("AUTODJ_SOUND_QUALITY", "/opt/autodj-mixer/shared/sound_quality.json")
MAX_SHIFT = 7
WOBBLE_BAD, NOISE_BAD, CENTS_SOFT = 20.0, 0.10, 15.0
_MEM = {}

def _load():
    if "db" not in _MEM:
        try: _MEM["db"] = json.load(open(os.environ.get("AUTODJ_SOUND_QUALITY", CACHE)))
        except (OSError, ValueError): _MEM["db"] = {}
    return _MEM["db"]

def _save():
    p = os.environ.get("AUTODJ_SOUND_QUALITY", CACHE); tmp = p + ".tmp"
    json.dump(_MEM.get("db", {}), open(tmp, "w"), ensure_ascii=False, indent=0); os.replace(tmp, p)

def measure_signal(y, sr):
    """-> measures of one mono signal (see module doc); None if too short / silent"""
    import librosa
    seg = y[int(.08 * sr):int(.7 * sr)]
    if len(seg) < sr * .2: seg = y
    if len(seg) < 2048 or np.abs(seg).max() < 1e-4: return None
    C = librosa.feature.chroma_cqt(y=seg, sr=sr, bins_per_octave=36).mean(1); C = C / (C.max() + 1e-9); top = np.argsort(C)[::-1]
    root = int(top[0]); extra = [int(i) for i in top if C[i] > .45 and i not in (root, (root + 7) % 12)]
    f0, _, vp = librosa.pyin(seg, fmin=30, fmax=1500, sr=sr, frame_length=2048); ok = f0[~np.isnan(f0)]
    if len(ok) > 5:
        midi = float(np.median(librosa.hz_to_midi(ok))); wob = float(np.std(1200 * np.log2(ok / np.median(ok))))
    else: midi = wob = None
    flat = float(librosa.feature.spectral_flatness(y=seg).mean())
    return {"root": None if midi is None else round(midi, 2), "cents": None if midi is None else round((midi - round(midi)) * 100, 1), "wobble": None if wob is None else round(wob, 1),
            "noise": round(flat, 4), "kind": "chord" if len(extra) >= 2 else ("dyad" if extra else "note"), "pcs": len(extra) + 1}

def measure(path):
    db = _load(); k = os.path.basename(path)
    if k not in db:
        import librosa
        try:
            y, sr = librosa.load(path, sr=22050, mono=True); m = measure_signal(y, sr)
        except Exception as e: m = None
        db[k] = m or {"error": True}; _save()
    return db[k]

def quality(m, role=None):
    """-> (q 0..1, hard_bad reasons list). Hard-bad = wobble > 20 c or noise > .1: a detuned stack / noise burst cannot be tuned by the engine."""
    if not m or m.get("error") or m.get("root") is None: return 0.0, ["no clear pitch"]
    bad = []; q = 1.0
    if m["wobble"] is not None and m["wobble"] > WOBBLE_BAD: bad.append(f"pitch wobbles ±{m['wobble']:.0f} c")
    if m["noise"] > NOISE_BAD: bad.append(f"noisy/detuned stack (flatness {m['noise']:.2f})")
    q -= min(.5, max(0.0, (m["wobble"] or 0) - 8) / 40) + min(.4, m["noise"] * 4) + min(.2, max(0.0, abs(m["cents"] or 0) - CENTS_SOFT) / 50)
    if m["kind"] == "chord" and role not in ("pad", "chord", "keys"): q -= .25
    elif m["kind"] == "dyad" and role in ("bass", "lead"): q -= .08
    return round(max(0.0, q), 2), bad

def window(kc): return (kc - MAX_SHIFT, kc + MAX_SHIFT)
def fits(kc, lo, hi, slack=5): return kc is not None and abs(kc - (lo + hi) / 2) + (hi - lo) / 2 <= MAX_SHIFT + slack
def needs_multisample(kc, lo, hi): return not fits(kc, lo, hi, slack=0)

def pick(candidates, role=None, lo=None, hi=None, rng=None, db=None, title=None, k=None, strict=True):
    """cleanest sounds first (hard-bad out; with lo/hi only those whose root serves the range), then the flexible freshness of fresh.pick.
    strict=False: if everything is hard-bad / out of range fall back to the best quality instead of raising. Returns a path (k=None) or a list."""
    from . import fresh
    rows = []
    for p in sorted(set(candidates)):
        m = measure(p); q, bad = quality(m, role)
        if bad: continue
        if lo is not None and not fits(round(m["root"]), lo, hi): continue
        rows.append((p, q))
    if not rows:
        if strict: raise ValueError(f"soundgate.pick: no clean candidate for {role} {lo}-{hi} among {len(set(candidates))} files")
        rows = [(p, quality(measure(p), role)[0]) for p in sorted(set(candidates))]
    best = max(q for _, q in rows); rows = [(p, q) for p, q in rows if q >= best - .35]               # keep the top band; freshness decides inside it
    return fresh.pick([p for p, _ in rows], rng, k=k, db=db, title=title, quality={p: q for p, q in rows})

def report(sources, root_dirs=("/home/cclaw/samples",)):
    """gate input: {source name: [reasons]} for the sources of a render that were measured and are hard-bad (never raises; unmeasured = unknown = fine)"""
    db = _load(); out = {}
    for s in sources or []:
        m = db.get(os.path.basename(s))
        if m and not m.get("error"):
            _, bad = quality(m)
            if bad: out[s] = bad
    return out

def scan(globs, procs=4):
    from multiprocessing import Pool
    files = sorted({p for g in globs for p in glob.glob(g, recursive=True)}); db = _load(); todo = [p for p in files if os.path.basename(p) not in db]
    with Pool(procs) as pool:
        for k, m in pool.imap_unordered(_m_top, todo, chunksize=2): db[k] = m
    _save(); return len(todo), len(files)

def _m_top(p):
    import librosa
    try: y, sr = librosa.load(p, sr=22050, mono=True); return os.path.basename(p), measure_signal(y, sr) or {"error": True}
    except Exception: return os.path.basename(p), {"error": True}

if __name__ == "__main__":
    import sys
    print(scan(sys.argv[1:] or ["/home/cclaw/samples/wa_techno/WAV MIDI Presets/Synth & Bass Shots/*.wav"]))
