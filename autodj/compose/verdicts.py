"""P159 (2026-11-21, audit 2): a listener's verdict on a LAYER becomes a rule the engine applies by itself. Until now Стас's words («kick острый,
резкий, лупит втупую», «clap примитивный», «piano самое ужасное») lived in the agent's memory only; preference_profile had 0 rules, the 44 timbre
verdicts had none about drums, and no generator read any of it.

  add(track, layer, role, sample, words, good)   store the verdict (shared/layer_verdicts.jsonl) WITH the measured sound (drumq features) and the axes
                                                 its words point to (WORDS: «резкий/острый» = crest, attack, centroid; «втупую/постоянно» = static;
                                                 «примитивный/банальный» = few events; «мягкий/лучше» = the good side)
  rules(role)                                    per role and sound axis: the limit learnt from the bad verdicts (just under the mildest bad value, never
                                                 below the good ones); status "proposed" (one verdict) or "confirmed" (two or more, or confirm())
  check(path, role)                              (fails, warnings): confirmed rules fail, proposed ones only warn
  confirm(role, axis)                            Стас says the rule is right -> confirmed
  report(sources)                                problem lines for the sources of a render
CI.pick drops candidates that fail a confirmed rule; a proposed rule never blocks (one word is not a law)."""
import datetime, json, os, re
import numpy as np

LOG = "/opt/autodj-mixer/shared/layer_verdicts.jsonl"
def log_path(): return os.environ.get("AUTODJ_LAYER_VERDICTS") or LOG
WORDS = ((r"бренч|брынч|дребезж|ржав|пластиков|линейк|ненастро|фальш|струн|twang|buzz|out of tune", ("hf", "err")), (r"резк|остр|бьет|бьёт|по мозгам|колюч|sharp|harsh", ("crest", "atk", "cen")), (r"втупую|постоянно|лупит|однообраз|static", ("static",)),
         (r"примитив|банальн|глуп|primitive", ("events",)), (r"ярк|звонк|bright", ("cen",)))
AXES = ("crest", "atk", "cen", "hf", "err")                      # measured sound axes a rule can hold (higher = worse for these words); hf / err belong to instruments (measure_instrument)
INSTRUMENT_ROLES = ("bass", "keys", "lead", "pad", "pluck")

def measure_instrument(name):
    """a library instrument measured on a standard phrase (notes 33-46 at two velocities, 0.9 s): {"hf": dB of the power above 1.5 kHz (the plastic-ruler twang),
    "err": the 90th percentile of the pitch error in cents (the string that plucks out of tune)}; cached per name in shared/instrument_quality.json"""
    import json
    p = os.path.join(os.path.dirname(log_path()), "instrument_quality.json")
    try: db = json.load(open(p))
    except (OSError, ValueError): db = {}
    k = str(name).replace("sfz:", "")
    if k not in db:
        import librosa
        from . import sfz
        inst = sfz.SFZ(k); errs, hfs = [], []
        for note in range(33, 47):
            for vel in (60, 100):
                y = inst.render([(0, note, vel, .9)], 1.4).mean(1)[:int(1.2 * 44100)]
                if np.abs(y).max() < 1e-4: continue
                seg = y[int(.05 * 44100):int(.8 * 44100)]; f0 = librosa.yin(seg, fmin=25, fmax=400, sr=44100, frame_length=8192); errs.append(abs(float(np.median(librosa.hz_to_midi(f0))) - note) * 100)
                S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2; f = np.fft.rfftfreq(len(seg), 1 / 44100); hfs.append(10 * np.log10(S[f > 1500].sum() / S.sum() + 1e-12))
        db[k] = {"hf": round(float(np.median(hfs)), 1), "err": round(float(np.percentile(errs, 90)), 1)} if hfs else {"error": "silent"}
        try: json.dump(db, open(p, "w"))
        except OSError: pass
    return db[k]

def check_instrument(name, role):
    """(fails, warns) of a library instrument against the learnt rules of the role (the same proposed / confirmed logic as check())"""
    m = measure_instrument(name); fails, warns = [], []
    if not m or m.get("error"): return fails, warns
    for ax, r in rules(role).items():
        if ax in ("hf", "err") and m.get(ax) is not None and m[ax] > r["max"]: (fails if r["status"] == "confirmed" else warns).append(f"{ax} {m[ax]} > {r['max']} ({r['status']}, вердиктов: {r['n']})")
    return fails, warns

def _load():
    try: return [json.loads(l) for l in open(log_path()) if l.strip()]
    except OSError: return []

def axes_of(words):
    w = (words or "").lower(); out = []
    for rx, ax in WORDS:
        if re.search(rx, w): out += [a for a in ax if a not in out]
    return out

def add(track, layer, role, sample, words, good, date=None):
    from . import drumq
    if sample and str(sample).startswith("sfz:") and role in INSTRUMENT_ROLES: m = measure_instrument(sample)
    else: m = drumq.features(sample) if sample and os.path.exists(str(sample)) else {}
    row = {"date": date or datetime.date.today().isoformat(), "track": track, "layer": layer, "role": role, "sample": os.path.basename(str(sample or "")),
           "words": words, "good": bool(good), "axes": axes_of(words), "m": {k: m.get(k) for k in AXES if m and not m.get("error") and m.get(k) is not None}}
    p = log_path(); os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row

def confirm(role, axis):
    p = log_path(); os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "a") as f: f.write(json.dumps({"kind": "confirm", "role": role, "axis": axis, "date": datetime.date.today().isoformat()}) + "\n")

def rules(role):
    """{axis: {"max": limit, "status": proposed|confirmed, "n": bad verdicts}} learnt for the role"""
    rows = _load(); out = {}
    conf = {r["axis"] for r in rows if r.get("kind") == "confirm" and r.get("role") == role}
    vs = [r for r in rows if r.get("kind") != "confirm" and r.get("role") == role]
    for ax in AXES:
        bad = [r["m"][ax] for r in vs if not r["good"] and ax in r.get("axes", []) and r.get("m", {}).get(ax) is not None]
        if not bad: continue
        good = [r["m"][ax] for r in vs if r["good"] and r.get("m", {}).get(ax) is not None]
        lim = min(bad) - .1 * abs(min(bad))                            # just under the mildest bad value (also right for negative dB axes)
        if good: lim = max(lim, max(good) + .05 * abs(max(good)))      # never refuse what he liked
        if good and lim >= min(bad): continue                         # the words do not separate good from bad on this axis: no rule
        out[ax] = {"max": round(float(lim), 3), "status": "confirmed" if (len(bad) >= 2 or ax in conf) else "proposed", "n": len(bad)}
    return out

def check(path, role):
    from . import drumq
    m = drumq.features(path); fails, warns = [], []
    if not m or m.get("error"): return fails, warns
    for ax, r in rules(role).items():
        if m.get(ax) is not None and m[ax] > r["max"]: (fails if r["status"] == "confirmed" else warns).append(f"{ax} {m[ax]} > {r['max']} ({r['status']}, вердиктов: {r['n']})")
    return fails, warns

def report(sources):
    from . import fresh
    from .drumq import ROLE_OF
    out = []
    for s in sources or []:
        if str(s).startswith("sfz:"):
            for role in INSTRUMENT_ROLES:
                try: f, w = check_instrument(s, role)
                except Exception: continue
                if f: out.append(f"{s}: нарушает подтверждённое правило Стаса для {role}: {'; '.join(f)}")
                elif w: out.append(f"{s}: похож на то, что Стас забраковал для {role} (правило предложено): {'; '.join(w)}")
            continue
        name = os.path.basename(str(s)); role = ROLE_OF.get(fresh.drum_class(name) or ""); path = s if os.path.isabs(str(s)) else fresh.PATHS.get(name)
        if not role or not path or not os.path.exists(path): continue
        f, w = check(path, role)
        if f: out.append(f"{name}: нарушает подтверждённое правило Стаса для {role}: {'; '.join(f)}")
        elif w: out.append(f"{name}: похож на то, что Стас забраковал для {role} (правило предложено, не подтверждено): {'; '.join(w)}")
    return out
