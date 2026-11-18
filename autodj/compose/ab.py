"""P144 (2026-11-18, Стас: «итеративное A/B-тестирование и активное обучение вкусу ... единый файл для Claude и других агентов»).
Concept: workspace/music/AB_LEARNING.md in the Claw workspace. One shared, append-only log for every agent (Claw, Hermes, ...):

  shared/preference_log.jsonl      one JSON object per line, never rewritten (group "users", mode 664: both agents write)
     kind "pair"    an A/B fork: ONE factor differs, same seed, loudness matched, blind letters
     kind "vote"    Стас's answer to a pair ("A" / "B" / "=" no difference / "0" both bad / "!" both good, + his word)
     kind "single"  a generation without A/B (a full track, a sketch): his verdict and word, if any
     kind "pick"    N variants, he picked one (the old experiment.py way)
  shared/preference_profile.json   recomputed from the log: per factor and value wins / losses / ties, a smoothed score,
                                   the contexts (genres) it was tested in, and rule suggestions

  make_pair(score, factor, a, b, ...)   render the score twice (env AB_FACTOR / AB_VALUE pick the value), match loudness, assign
                                        blind letters at random, refuse a pair with a failed gate, log it
  vote(round_id, "1B 2A 3= ...")        parse his one-line answer, log the votes, return what each meant
  log_single(...), log_pick(...)        the other generation paths (no A/B) go to the same log
  profile()                             recompute and save the profile; rules = a value that won 3+ times in 2+ contexts, never lost
  hypothesis_score()                    share of votes my hypothesis predicted (calibration of my guesses about his taste)

    python -m autodj.compose.ab vote R1 "1B 2A 3="
    python -m autodj.compose.ab profile
    python -m autodj.compose.ab show [R1]
"""
import datetime, fcntl, grp, json, os, random, re, shutil, subprocess, sys

SHARED = "/opt/autodj-mixer/shared"
def log_path(): return os.environ.get("AUTODJ_PREF_LOG") or os.path.join(SHARED, "preference_log.jsonl")
def profile_path(): return os.environ.get("AUTODJ_PREF_PROFILE") or os.path.join(SHARED, "preference_profile.json")
VOTES = {"A": "A", "B": "B", "=": "=", "0": "0", "!": "!"}

def _shareable(path):
    """the file exists, group users, rw for owner and group (Claw and Hermes both write it)"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if not os.path.exists(path): open(path, "a").close()
    try:
        os.chmod(path, 0o664)
        os.chown(path, -1, grp.getgrnam("users").gr_gid)
    except (OSError, KeyError): pass
    return path

def append(entry, path=None):
    """append one entry (locked, so two agents writing at once do not interleave)"""
    p = _shareable(path or log_path()); entry = dict(entry); entry.setdefault("at", datetime.datetime.now().isoformat(timespec="seconds"))
    with open(p, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps(entry, ensure_ascii=False) + "\n"); f.flush(); fcntl.flock(f, fcntl.LOCK_UN)
    return entry

def read(path=None):
    p = path or log_path()
    if not os.path.exists(p): return []
    out = []
    for line in open(p):
        line = line.strip()
        if line:
            try: out.append(json.loads(line))
            except ValueError: pass
    return out

# ---- the pair -----------------------------------------------------------------------------------------------------------------
def _render(score, name, seed, title, env_extra, cwd):
    env = dict(os.environ, **{k: str(v) for k, v in env_extra.items()}); env["PYTHONPATH"] = "/opt/autodj-mixer" + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    r = subprocess.run([sys.executable, "-m", "autodj.compose", "run", score, "--seed", str(seed), "--name", name, "--title", title], cwd=cwd, env=env, capture_output=True, text=True)
    summ = os.path.join(cwd, "out", name + ".summary.json")
    if not os.path.exists(summ): raise RuntimeError(f"render {name} failed: {r.stderr[-600:]}")
    return json.load(open(summ))

def _lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr); return float(m[-1]) if m else None

def _gain(src, dst, db):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-af", f"volume={db:.2f}dB", "-b:a", "256k", dst], check=True)

def check_pair(sa, sb):
    """refuse a pair that would teach nothing: a failed gate on either side, different seed or tempo"""
    bad = []
    for k, s in (("A", sa), ("B", sb)):
        if s.get("gate_failed"): bad.append(f"{k}: gate {s['gate_failed']}")
        if s.get("silent_layers"): bad.append(f"{k}: silent layers {s['silent_layers']}")
    if sa.get("seed") != sb.get("seed"): bad.append("different seeds")
    if sa.get("bpm") != sb.get("bpm"): bad.append("different tempo")
    return bad

def make_pair(score, factor, a, b, round_id, n, seed, genre, hypothesis="", p_expected=None, expected=None, who="claw", mood=None, title=None, outdir=None, rng=None, dry=False):
    """render value a and value b of `factor` (the score reads env AB_FACTOR / AB_VALUE), match loudness, assign blind letters,
    log the pair. Returns the entry ({"id", "letters": {"A": value, "B": value}, "files": {...}}) or raises when check_pair fails."""
    cwd = os.path.dirname(os.path.abspath(score)); outdir = outdir or os.path.join(cwd, "ab"); os.makedirs(outdir, exist_ok=True)
    pid = f"{round_id}-p{n}"; title = title or f"AB {pid}"; summ = {}
    for v in (a, b):
        summ[v] = None if dry else _render(score, f"{pid}_{v}", seed, f"{title} {v}", {"AB_FACTOR": factor, "AB_VALUE": v}, cwd)
    if not dry:
        bad = check_pair(summ[a], summ[b])
        if bad: raise ValueError(f"pair {pid} refused: {bad}")
    rng = rng or random.Random(); order = [a, b]; rng.shuffle(order); letters = {"A": order[0], "B": order[1]}; files = {}; lufs = {}
    if not dry:
        src = {v: summ[v]["file"] for v in (a, b)}; lufs = {v: _lufs(src[v]) for v in (a, b)}; target = min(x for x in lufs.values() if x is not None)
        for L, v in letters.items():
            dst = os.path.join(outdir, f"{pid}-{L}.mp3"); _gain(src[v], dst, target - lufs[v]); files[L] = dst
    e = {"kind": "pair", "id": pid, "round": round_id, "n": n, "who": who, "date": datetime.date.today().isoformat(), "genre": genre, "mood": mood,
         "factor": factor, "values": [a, b], "letters": letters, "files": files, "seed": seed, "score": os.path.abspath(score),
         "lufs_before": lufs, "hypothesis": hypothesis, "expected": expected, "p_expected": p_expected,
         "metrics": {v: {k: (summ[v] or {}).get(k) for k in ("hf_step_dbfs", "clash_ratio", "jump_db")} | {"limiter": ((summ[v] or {}).get("master") or {}).get("limiter_max_db")} for v in (a, b)}}
    return append(e)

# ---- votes ----------------------------------------------------------------------------------------------------------------------
def parse(text):
    """'1B 2A мягче 3=' -> [(1, 'B', ''), (2, 'A', 'мягче'), (3, '=', '')]"""
    out = []
    for m in re.finditer(r"(\d+)\s*([ABАВ=0!])\s*([^\d]*?)(?=\s*\d+\s*[ABАВ=0!]|\s*$)", text.strip(), re.I):
        L = m.group(2).upper().replace("А", "A").replace("В", "B"); out.append((int(m.group(1)), VOTES[L], m.group(3).strip(" ,.;")))
    return out

def vote(round_id, text, who="stas", recorded_by="claw", path=None):
    pairs = {e["n"]: e for e in read(path) if e.get("kind") == "pair" and e.get("round") == round_id}; res = []
    for n, L, word in parse(text):
        p = pairs.get(n)
        if not p: res.append({"n": n, "error": "no such pair"}); continue
        won = p["letters"].get(L) if L in ("A", "B") else None
        v = append({"kind": "vote", "pair": p["id"], "round": round_id, "n": n, "vote": L, "won": won, "word": word, "who": who, "recorded_by": recorded_by,
                    "hypothesis_ok": (won == p.get("expected")) if p.get("expected") and won else None}, path)
        res.append(v)
    return res

def log_single(title, file, genre, verdict=None, word="", who="claw", notes=None, path=None):
    return append({"kind": "single", "title": title, "file": file, "genre": genre, "verdict": verdict, "word": word, "who": who, "notes": notes or {}}, path)

def log_pick(round_id, options, picked, genre, word="", who="claw", path=None):
    return append({"kind": "pick", "round": round_id, "options": options, "picked": picked, "genre": genre, "word": word, "who": who}, path)

# ---- the profile ----------------------------------------------------------------------------------------------------------------
def profile(path=None, save=True):
    log = read(path); pairs = {e["id"]: e for e in log if e.get("kind") == "pair"}; F = {}; hyp = [0, 0]
    for v in (e for e in log if e.get("kind") == "vote"):
        p = pairs.get(v["pair"])
        if not p: continue
        f = F.setdefault(p["factor"], {}); a, b = p["values"]
        for x in (a, b): f.setdefault(x, {"wins": 0, "losses": 0, "ties": 0, "both_bad": 0, "both_good": 0, "contexts": [], "words": []})
        if v["vote"] in ("A", "B"):
            w = v["won"]; l = b if w == a else a; f[w]["wins"] += 1; f[l]["losses"] += 1
            ctx = p.get("genre") or "?"
            if ctx not in f[w]["contexts"]: f[w]["contexts"].append(ctx)
            if v.get("word"): f[w]["words"].append(v["word"])
            exp = p.get("expected")
            if exp: hyp[0] += exp == w; hyp[1] += 1
        else:
            key = {"=": "ties", "0": "both_bad", "!": "both_good"}[v["vote"]]
            for x in (a, b): f[x][key] += 1
    rules, unimportant = [], []
    for fac, vals in F.items():
        for x, s in vals.items():
            s["score"] = round((s["wins"] + 1) / (s["wins"] + s["losses"] + 2), 2)
            if s["wins"] >= 3 and s["losses"] == 0 and len(s["contexts"]) >= 2: rules.append({"factor": fac, "value": x, "wins": s["wins"], "contexts": s["contexts"]})
        if max((s["ties"] for s in vals.values()), default=0) >= 3: unimportant.append(fac)
    prof = {"updated": datetime.datetime.now().isoformat(timespec="seconds"), "factors": F, "rules": rules, "unimportant": unimportant,
            "hypotheses": {"right": hyp[0], "total": hyp[1], "share": round(hyp[0] / hyp[1], 2) if hyp[1] else None},
            "counts": {k: sum(1 for e in log if e.get("kind") == k) for k in ("pair", "vote", "single", "pick")}}
    if save:
        p = _shareable(profile_path()); tmp = p + ".tmp"; json.dump(prof, open(tmp, "w"), ensure_ascii=False, indent=1); os.replace(tmp, p); _shareable(p)
    return prof

def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a: print(__doc__); return 2
    if a[0] == "vote" and len(a) >= 3:
        for r in vote(a[1], " ".join(a[2:])): print(r)
        print(json.dumps(profile()["factors"], ensure_ascii=False)[:1500]); return 0
    if a[0] == "profile": print(json.dumps(profile(), ensure_ascii=False, indent=1)[:4000]); return 0
    if a[0] == "show":
        for e in read():
            if len(a) < 2 or e.get("round") == a[1]: print(json.dumps(e, ensure_ascii=False)[:400])
        return 0
    print(__doc__); return 2

if __name__ == "__main__":
    sys.exit(main())
