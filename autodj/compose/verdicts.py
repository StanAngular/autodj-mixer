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
WORDS = ((r"резк|остр|бьет|бьёт|по мозгам|колюч|sharp|harsh", ("crest", "atk", "cen")), (r"втупую|постоянно|лупит|однообраз|static", ("static",)),
         (r"примитив|банальн|глуп|primitive", ("events",)), (r"ярк|звонк|bright", ("cen",)))
AXES = ("crest", "atk", "cen")                                   # measured sound axes a rule can hold (higher = worse for these words)

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
    m = drumq.features(sample) if sample and os.path.exists(str(sample)) else {}
    row = {"date": date or datetime.date.today().isoformat(), "track": track, "layer": layer, "role": role, "sample": os.path.basename(str(sample or "")),
           "words": words, "good": bool(good), "axes": axes_of(words), "m": {k: m.get(k) for k in AXES if m and not m.get("error")}}
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
        lim = min(bad) * .9
        if good: lim = max(lim, max(good) * 1.05)                    # never refuse what he liked
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
        name = os.path.basename(str(s)); role = ROLE_OF.get(fresh.drum_class(name) or ""); path = s if os.path.isabs(str(s)) else fresh.PATHS.get(name)
        if not role or not path or not os.path.exists(path): continue
        f, w = check(path, role)
        if f: out.append(f"{name}: нарушает подтверждённое правило Стаса для {role}: {'; '.join(f)}")
        elif w: out.append(f"{name}: похож на то, что Стас забраковал для {role} (правило предложено, не подтверждено): {'; '.join(w)}")
    return out
