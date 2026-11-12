"""P135 (2026-11-12, Стас: «накладывает звуки, которые уже использовал в прошлых треках… ударные подобраны явно по шаблону»).
Claw measured it: in 433 scripts the same kicks, bass shots, Rhodes and kit sit in 9-17 project folders each. The cause is not one
track: the helper files carry fixed paths (wk.py: W.A. shots, Kit 15, jRhodes, Karoryfer), the agent's memory says «prefer WART_Kick
2/5/9» and «keep this recipe as the base», the same Cm(add9) | Abmaj7 | Fm7 | G7sus4 is typed into every score, and NOTHING in the
engine knows what the previous tracks used. This module is that memory, kept in the repository instead of in the agent:

  used(path)         called by load_sample / sfz.oneshot / SFZ(): every sound source of a render is noted (by file name)
  rhythms(trk)       the drum layers' bar patterns as strings ("x...x...x...x..."), from what each layer really played
  ledger             shared/fresh_ledger.json: per track title its sources, drum patterns, harmony fingerprint (chords.Plan)
  review(info, t)    this render against all EARLIER tracks: which sources / drum patterns / progression were already used and
                     how often -> numbers and plain-word notes in the summary (`fresh`, `fresh_notes`); gates are opt-in:
                     META["gates"] = {"fresh_reuse_max": .3, "fresh_rhythm_max": 1, "fresh_harmony_new": True}
  pick(candidates)   choose the LEAST used of several files (ties at random): `kick = load_sample(fresh.pick(glob(KICKS)))`
  scan(root)         bootstrap the ledger from old score files (which sample names each project folder mentions)

    python -m autodj.compose.fresh scan /home/cclaw/claudeclaw-build/workspace/music      # once: history of the old tracks
    python -m autodj.compose.fresh top                                                       # the most worn sounds
A re-render of the same title replaces its own entry and is never counted against itself."""
import datetime, glob, json, os, re
import numpy as np

LEDGER = "/opt/autodj-mixer/shared/fresh_ledger.json"          # override: env AUTODJ_FRESH_LEDGER (read at call time)
def ledger_path(path=None):
    return path or os.environ.get("AUTODJ_FRESH_LEDGER") or LEDGER
USED = {}                                        # sources of the render in this process: key -> count
WORN = 3                                         # a source / pattern found in this many earlier tracks is «worn»
CLASS = (("kick", ("kick", "bd")), ("hat", ("hat", "hh", "ride", "cymbal")), ("backbeat", ("clap", "snare", "rim", "snr")), ("shaker", ("shk", "shaker", "tamb")),
         ("perc", ("perc", "conga", "tom", "clave", "bongo", "tumba", "click")))

def key_of(path):
    """a portable name for a source: the file name (sample packs keep unique names), or "sfz:NAME" for a library instrument"""
    p = str(path); return p if p.startswith(("sfz:", "lab:", "synth:")) else os.path.basename(p)

def used(path, kind=None):
    """note that this render loaded a sound source (never raises)"""
    try: k = key_of(path); USED[k] = USED.get(k, 0) + 1
    except Exception: pass
    return path

def reset():
    USED.clear()

def drum_class(name):
    n = name.lower()
    return next((c for c, keys in CLASS if any(k in n for k in keys)), None)

def rhythms(trk):
    """{drum class: the layer's most frequent bar pattern "x...x..." (16 steps)} from the step x band maps of the layers"""
    from .depth import onsets
    out = {}
    for name, E in getattr(trk, "act", {}).items():
        c = drum_class(name)
        if c is None or E is None: continue
        pats = {}
        for st in onsets(E, trk.bars):
            if st: p = "".join("x" if i in st else "." for i in range(16)); pats[p] = pats.get(p, 0) + 1
        if pats:
            best = max(pats, key=pats.get)
            if c not in out or pats[best] > out[c][1]: out[c] = (best, pats[best])
    return {c: p for c, (p, _) in out.items()}

def load(path=None):
    path = ledger_path(path)
    try: return json.load(open(path))
    except (OSError, ValueError): return {"version": 1, "tracks": {}}

def save(db, path=None):
    path = ledger_path(path); os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True); tmp = path + ".tmp"
    json.dump(db, open(tmp, "w"), ensure_ascii=False, indent=0); os.replace(tmp, path)

def usage(db, title=None):
    """{source: [titles of OTHER tracks that used it]}"""
    out = {}
    for t, e in db["tracks"].items():
        if t == title: continue
        for s in e.get("sources", []): out.setdefault(s, []).append(t)
    return out

def review(info, title, db=None):
    """compare one render (the dict Track.finish returns) with the ledger -> {"sources", "reused", "worn", "reuse_share", "rhythm_repeats",
    "harmony_seen", "notes"}"""
    db = db if db is not None else load(); use = usage(db, title); src = sorted(info.get("sources") or [])
    reused = {s: len(use[s]) for s in src if s in use}; worn = {s: n for s, n in reused.items() if n >= WORN}
    others = {t: e for t, e in db["tracks"].items() if t != title}; rep = {}
    for c, p in (info.get("rhythms") or {}).items():
        n = sum(1 for e in others.values() if (e.get("rhythms") or {}).get(c) == p)
        if n: rep[c] = [p, n]
    fp = (info.get("harmony") or {}).get("fingerprint"); seen = [t for t, e in others.items() if fp and e.get("harmony") == fp]
    loops = [t for t, e in others.items() if e.get("harmony")]
    notes = []
    for s, n in sorted(worn.items(), key=lambda x: -x[1]):
        notes.append(f"звук «{s}» уже в {n} прошлых треках ({', '.join(use[s][-3:])}…): возьми другой — fresh.pick(кандидаты) выбирает наименее заезженный")
    for c, (p, n) in rep.items():
        if n >= WORN: notes.append(f"рисунок «{c}» {p} совпадает с {n} прошлыми треками: ударные по шаблону — измени рисунок под этот трек")
    if seen: notes.append(f"та же последовательность аккордов уже была в: {', '.join(seen[-3:])}. Возьми другой оборот (chords.idioms) или его вариант")
    if src and not info.get("harmony") and info.get("notes_logged"): notes.append("гармония вписана вручную, без плана (chords.Plan): её нельзя сравнить с прошлыми треками")
    share = round(len(worn) / len(src), 2) if src else 0.0
    if share > .5 and len(src) >= 4: notes.append(f"{share:.0%} звуков этого трека — заезженные (в {WORN}+ прошлых треках): это тот же набор, что и раньше")
    return {"sources": src, "reused": reused, "worn": worn, "reuse_share": share, "rhythm_repeats": rep, "harmony_seen": seen, "tracks_known": len(others), "notes": notes,
            "harmony_tracks": len(loops)}

def gates(rev, g):
    g = g or {}; out = []
    if "fresh_reuse_max" in g and rev["reuse_share"] > g["fresh_reuse_max"]: out.append(f"заезженных звуков {rev['reuse_share']:.0%} > {g['fresh_reuse_max']:.0%}: {sorted(rev['worn'])}")
    nr = sum(1 for p, n in rev["rhythm_repeats"].values() if n >= WORN)
    if "fresh_rhythm_max" in g and nr > g["fresh_rhythm_max"]: out.append(f"рисунков ударных, повторяющих прошлые треки: {nr} > {g['fresh_rhythm_max']}")
    if g.get("fresh_harmony_new") and rev["harmony_seen"]: out.append(f"последовательность аккордов уже была в {rev['harmony_seen'][-3:]}")
    return out

def record(info, title, db=None, path=None):
    """store this render under its title (a re-render replaces the entry)"""
    db = db if db is not None else load(path)
    db["tracks"][title] = {"date": datetime.date.today().isoformat(), "sources": sorted(info.get("sources") or []), "rhythms": info.get("rhythms") or {},
                           "harmony": (info.get("harmony") or {}).get("fingerprint")}
    save(db, path); return db

def pick(candidates, rng=None, k=None, db=None, title=None):
    """the least used of the candidate files (ties broken at random by rng). k=None -> one path; k=N -> a list of N different ones."""
    c = sorted(set(candidates))
    if not c: raise ValueError("fresh.pick: no candidates (check the glob pattern)")
    use = usage(db if db is not None else load(), title); rng = rng or np.random.default_rng()
    order = sorted(c, key=lambda p: (len(use.get(key_of(p), [])), rng.random()))
    return order[0] if k is None else order[:k]

PAT = re.compile(r"""[\w \-&()+.]+\.(?:wav|flac|aiff?|sfz)\b""", re.I); SFZ_CALL = re.compile(r"""SFZ\(\s*["'](\w+)["']""")
def scan(root, db=None, path=None):
    """bootstrap: every project folder under `root` becomes a track "legacy:<folder>" with the sample names its *.py files mention
    (literal file names and SFZ("name") calls; names built from pieces at run time are not seen). Returns {folder: n_sources}."""
    db = db if db is not None else load(path); found = {}
    for f in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        rel = os.path.relpath(f, root); proj = rel.split(os.sep)[0] if os.sep in rel else os.path.splitext(rel)[0]
        try: txt = open(f, errors="ignore").read()
        except OSError: continue
        s = found.setdefault(proj, set()); s.update(os.path.basename(m.group(0).strip()) for m in PAT.finditer(txt)); s.update("sfz:" + m.group(1) for m in SFZ_CALL.finditer(txt))
    for proj, s in found.items():
        if s: db["tracks"]["legacy:" + proj] = {"date": None, "sources": sorted(s), "rhythms": {}, "harmony": None}
    save(db, path); return {p: len(s) for p, s in found.items() if s}

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="autodj.compose.fresh"); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("root"); s.add_argument("--ledger")
    t = sub.add_parser("top"); t.add_argument("--n", type=int, default=25); t.add_argument("--ledger")
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        r = scan(a.root, path=a.ledger); print(json.dumps({"projects": len(r), "sources": sum(r.values())}, ensure_ascii=False)); return r
    use = usage(load(a.ledger)); rows = sorted(use.items(), key=lambda x: -len(x[1]))[:a.n]
    for s_, ts in rows: print(f"{len(ts):4d}  {s_}")
    return rows

if __name__ == "__main__":
    main()
