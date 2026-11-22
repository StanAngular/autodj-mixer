"""python -m autodj.compose run SCORE.py --seed 7 --name my_track [--title "..."] [--target -14] [--send]

A score is a .py file with  build(seed) -> Track  (and optional META = {"title":..., "target":..., "gates": {...}}).
Pipeline: render slot -> build -> bus wav -> premaster -> warm master -> checks/gates -> ONE automatic master-side fix
(top shelf / low shelf / lower target) -> re-check -> summary JSON (+ registry line, + Telegram if --send)."""
import argparse, datetime, getpass, importlib.util, json, os, re, sys, time
from .lock import render_slot
from . import sfz
from .master import premaster, warm
from .checks import analyze, gates

REGISTRY = os.environ.get("AUTODJ_COMPOSE_REGISTRY", "/opt/autodj-mixer/shared/compose_registry.jsonl")

def load_score(path):
    spec = importlib.util.spec_from_file_location("score", path); mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(os.path.abspath(path))); spec.loader.exec_module(mod); return mod

ARTIST = os.environ.get("AUTODJ_ARTIST", "StanPo")                     # P111, Стас 2026-10-23: «автор StanPo у всех»

def clean_title(title):
    """P111: titles are «Name (style)», the artist goes to the performer field / ID3 tag, never into the title"""
    t = re.sub(r"^\s*StanPo\s*[-–—:]\s*", "", title or "", flags=re.I).strip()
    return t or (title or "")

def tag_mp3(path, title, genre=""):
    """write ID3 artist/title/genre in place (stream copy, no re-encode)"""
    import subprocess, tempfile
    tmp = tempfile.mktemp(suffix=".mp3", dir=os.path.dirname(os.path.abspath(path)))
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-c", "copy", "-map_metadata", "-1", "-metadata", f"title={title}",
                        "-metadata", f"artist={ARTIST}", "-metadata", f"genre={genre}", tmp], capture_output=True)
    if r.returncode == 0: os.replace(tmp, path); return True
    if os.path.exists(tmp): os.remove(tmp)
    return False

def send_telegram(path, title):
    import urllib.request, uuid
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("ALLOWED_CHAT_ID")
    if not (tok and chat): return "skipped: no TELEGRAM_BOT_TOKEN/ALLOWED_CHAT_ID"
    b = uuid.uuid4().hex; data = open(path, "rb").read()
    body = b"".join([f"--{b}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat}\r\n".encode(),
                     f"--{b}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{title}\r\n".encode(),
                     f"--{b}\r\nContent-Disposition: form-data; name=\"performer\"\r\n\r\n{ARTIST}\r\n".encode(),
                     f"--{b}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{os.path.basename(path)}\"\r\nContent-Type: audio/mpeg\r\n\r\n".encode(),
                     data, f"\r\n--{b}--\r\n".encode()])
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendAudio", data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    return "sent" if json.load(urllib.request.urlopen(req, timeout=300)).get("ok") else "failed"

FIXABLE = ("high", "sub", "limiter")
def fixes_for(bad, met, ms, g):
    """master-side fixes that need no re-render, sized by how far the value is over the gate"""
    from pedalboard import HighShelfFilter, LowShelfFilter
    from .checks import GATES
    g = {**GATES, **(g or {})}; eq, dt = [], 0.0
    for code, _ in bad:
        if code == "high": eq.append(HighShelfFilter(3500, -min(6.0, met["high_db"] - g["high_db"] + 1.5)))
        if code == "sub": eq.append(LowShelfFilter(75, -min(5.0, 2.0 + 20 * max(met["sub_mean"] - g["sub_mean"], met["sub_max"] - g["sub_max"], 0))))
        if code == "limiter": dt -= ms["limiter_max_db"] - g["limiter_max_db"] + .5
    return eq, dt

def _verdict_lines(sources):
    """P159: sources that break (confirmed) or resemble (proposed) Стас's layer verdicts"""
    try:
        from . import verdicts
        return verdicts.report(sources)
    except Exception: return []

def _drum_static(trk, summ):
    """P156: the drums the score logged (arrange.log_drums): runs of identical bars"""
    try:
        from . import arrange
        summ["drum_static"] = arrange.drum_static(trk) or None; return arrange.drum_static_problems(trk)
    except Exception: return []

def main(argv=None):
    ap = argparse.ArgumentParser(prog="autodj.compose run"); ap.add_argument("cmd", choices=["run"]); ap.add_argument("score")
    ap.add_argument("--seed", type=int, default=None); ap.add_argument("--name"); ap.add_argument("--title"); ap.add_argument("--target", type=float)
    ap.add_argument("--outdir"); ap.add_argument("--send", action="store_true"); ap.add_argument("--keep-wav", action="store_true"); ap.add_argument("--review", action="store_true", help="Gemini second ear on the final mp3"); ap.add_argument("--ears", action="store_true", help="P125: Audiobox Aesthetics on 3 clips (also META[\"ears\"])")
    a = ap.parse_args(argv); t0 = time.time()
    from . import fresh
    fresh.reset()                                                                             # P135: sources are counted per render, from the score's import on
    mod = load_score(a.score); meta = getattr(mod, "META", {})
    from . import drumq, rhythm; drumq.set_task(**(meta.get("task") or {}))                          ; rhythm.set_task(**{k: v for k, v in (meta.get("task") or {}).items() if k in ("mood", "style", "profile")})            # P161: sharpness limits of THIS task (mood / references / explicit numbers)
    name = a.name or os.path.splitext(os.path.basename(a.score))[0]
    outdir = a.outdir or os.path.join(os.path.dirname(os.path.abspath(a.score)), "out"); os.makedirs(outdir, exist_ok=True)
    try:                                                                                      # P176: the genre card supplies defaults the score did not set (explicit META wins)
        from . import genres as _G; _g = (meta.get("task") or {}).get("genre")
        if _g:
            _d = _G.meta_defaults(_G.card(_g)); meta = {**{k: v for k, v in _d.items() if k != "gates"}, **meta, "gates": {**(_d.get("gates") or {}), **(meta.get("gates") or {})}}
    except Exception: pass
    target = a.target if a.target is not None else meta.get("target", -14.0); title = clean_title(a.title or meta.get("title", name)); fresh.TITLE = title                # P147: from here chords.Plan.build refuses a progression the latest tracks opened with
    raw, pre, mp3 = (os.path.join(outdir, f"{name}{s}") for s in ("_raw.wav", "_pre.wav", ".mp3"))
    with render_slot() as slot:
        if a.seed is None:                                                   # Стас 2026-10-22: the same seed only for variations of
            import zlib                                                       # ONE track; a new track gets its own seed (from its name)
            a.seed = zlib.crc32((a.name or os.path.basename(a.score)).encode()) % 100000
        print(f"render slot {slot}", flush=True); sfz.SQUEEZE_LOG.clear(); trk = mod.build(a.seed); info = trk.finish(raw, meta={"title": title, "seed": a.seed, "lead": meta.get("lead")}); info["squeezed"] = sfz.squeezed_report()
        drv = meta.get("premaster_drive", 3.0); pm = meta.get("premaster", "clip" if meta.get("master") == "studio" else "sat")   # P130
        ref_eq, ref_curve = [], None                                                        # P142: META "reference" + "match_eq": the
        if meta.get("reference") and meta.get("match_eq"):                                   # tonal balance moves toward the reference
            try:
                from .blueprint import match_eq, eq_plugins
                ref_curve = match_eq(raw, meta["reference"], amount=float(meta["match_eq"])); ref_eq = eq_plugins(ref_curve)
            except Exception as ex: ref_curve = {"error": f"{type(ex).__name__}: {str(ex)[:120]}"}
        premaster(raw, pre, drive_db=drv, mode=pm, pre_eq=list(ref_eq), knee_db=meta.get("premaster_knee", -5.0)); ms = warm(pre, mp3, target, mode=meta.get("master", "warm")); met = analyze(mp3, info); bad = gates(met, ms, meta.get("gates"))
        fixed = []; eq_all, dt_all = list(ref_eq), 0.0
        for _ in range(2):                                         # at most two master-side rounds (an EQ cut can raise the limiter)
            eq, dt = fixes_for(bad, met, ms, meta.get("gates"))
            if not (eq or dt): break
            fixed.append({"codes": [c for c, _ in bad if c in FIXABLE], "before": {"high_db": met["high_db"], "sub_mean": met["sub_mean"], "limiter_max_db": ms["limiter_max_db"]}})
            eq_all += eq; dt_all += dt
            premaster(raw, pre, drive_db=drv, pre_eq=eq_all, mode=pm, knee_db=meta.get("premaster_knee", -5.0)); ms = warm(pre, mp3, target + dt_all, mode=meta.get("master", "warm")); met = analyze(mp3, info); bad = gates(met, ms, meta.get("gates"))
    if not a.keep_wav:
        for p in (raw, pre): os.path.exists(p) and os.remove(p)
    summ = {"name": name, "title": title, "file": mp3, "dur_s": round(trk.N / trk.sr), "bpm": trk.bpm, "seed": a.seed, "master": ms,
            "high_db": met["high_db"], "sub_mean": met["sub_mean"], "jump_db": met["jump_db"], "break_drop_db": met["break_drop_db"],
            "voice_max_lift": max([v[2] for v in met["voice_lift"]] or [None], key=lambda v: v or -99), "spikes": met["spikes"],
            "sections": [[s["name"], s["rms"], round(s["sub"] * 100)] for s in met["sections"]], "mono_low": met.get("mono_low"), "mono_fold_db": met.get("mono_fold_db"), "rhythm": met.get("rhythm"),
            "auto_fixed": fixed, "problems": [m for _, m in bad], "render_min": round((time.time() - t0) / 60, 1)}
    summ["squeezed"] = info.get("squeezed", []); summ.update({k: met.get(k) for k in ("width_high", "lr_balance_std", "hf_step_dbfs", "true_peak_db")}); summ["clash_ratio"] = info.get("clash_ratio"); summ["clash_pairs"] = info.get("clash_pairs")
    from . import clicks                                                                      # P140: where the wave jumps and which layer made it (always reported)
    summ["clicks"] = info.get("clicks"); summ["click_notes"] = clicks.explain(info.get("clicks")); summ["hf_step_t"] = met.get("hf_step_t")
    if summ["click_notes"] and any(c == "click" for c, _ in bad):
        why = next((n for n in summ["click_notes"] if n.startswith("самый резкий")), summ["click_notes"][0])
        if clicks.only_attacks(info.get("clicks")) and not (meta.get("gates") or {}).get("click_strict"):
            summ["problems"] = [m for m in summ["problems"] if not m.startswith("резкий щелчок")]          # P140: the click gate is about the wave
            summ["click_notes"].insert(0, f"гейт щелчка снят: верх {met.get('hf_step_dbfs')} дБFS — это атаки, разрывов волны нет (gates click_strict=True вернёт старый гейт)")
        else: summ["problems"] = [f"{m}: {why}" if m.startswith("резкий щелчок") else m for m in summ["problems"]]
    summ["tagged"] = tag_mp3(mp3, title, meta.get("genre", ""))
    from . import ears                                                                        # P125: silent layers (always), arrangement arc (always), Audiobox (opt-in), optional gates
    summ["silent_layers"] = ears.silent_layers(info.get("layers_db")); summ["layers_db"] = info.get("layers_db")
    try: summ["literal"] = ears.literal_runs(trk.notes, trk.BAR, trk.S16)                  # P149: layers that loop the same bars (step + pitch) for a long time
    except Exception as e: summ["literal"] = {}; summ["problems"].append(f"literal_runs: {type(e).__name__}: {e}")
    summ["bands"] = ears.band_owners(trk)                                                      # P155: who owns which band + level to the ear
    summ["top"] = ears.top_balance(trk)                                                        # P151: do the hats own the top of the spectrum
    try:
        from . import rhythm; summ["rhythm_drive"], summ["rhythm_notes"] = rhythm.report(trk, info.get("sources"))                          # P162: report only
    except Exception as e: summ["rhythm_drive"], summ["rhythm_notes"] = None, [f"rhythm.report: {type(e).__name__}: {e}"]
    try:                                                                                        # P175: how much the mix sounds like its genre card's genre (CLAP, a report)
        g = (meta.get("task") or {}).get("genre")
        if g:
            from . import genres; c = genres.card(g); summ["genre_similarity"] = genres.similarity(mp3, c["labels"]); summ["problems"] += genres.palette_problems(info.get("sources"), c)
    except Exception as e: summ["genre_similarity"] = {"error": f"{type(e).__name__}: {e}"}
    summ["kick_bass"] = ears.kick_bass(trk)
    try:
        from . import rhythm; cl = rhythm.checklist(trk, summ, summ.get("rhythm_drive")); summ["rhythm_checklist"] = [list(x) for x in cl]                       # P164: six questions, every render
    except Exception as e: summ["rhythm_checklist"] = [["checklist", "unknown", f"{type(e).__name__}: {e}"]]                                                   # P150: share of bass notes on kick hits (None = unknown)
    try: summ["arc"] = ears.arc(mp3, trk.bpm)
    except Exception as e: summ["arc"] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    if a.ears or meta.get("ears"): summ["ears"] = ears.abx(mp3)
    summ["problems"] += [f"слой {n} беззвучен (layers_db пуст): проверь env/секции" for n in summ["silent_layers"]] + ears.ears_gates(summ, meta.get("gates")) + ears.top_problems(summ["top"], meta) + ears.band_problems(summ["bands"]) + ears.lead_problems(summ["bands"], meta.get("lead")) + _drum_static(trk, summ) + ears.kick_tuning_problems(info.get("sources"), info.get("harmony")) + ears.drum_sharp_problems(info.get("sources")) + _verdict_lines(info.get("sources")) + [f"бас и бочка: {x}; строй бас от бочки: Plan.bass(kick=...)" for x in ears.kick_bass_failures(summ, meta)] + [f"слой {x} играет те же такты подряд, это петля, а не развитие: lines.evolve / develop" for x in ears.literal_failures(summ, meta)]
    from . import depth                                                                       # P133: where the track is flat (always reported; gates opt-in)
    summ["depth"] = info.get("depth"); summ["depth_notes"] = (info.get("depth") or {}).get("notes", []); summ["problems"] += depth.gates(info.get("depth"), meta.get("gates"))
    from . import tonal                                                                       # P137: is it harmonious (always reported; gates opt-in)
    summ["tonal"] = info.get("tonal"); summ["tonal_notes"] = (info.get("tonal") or {}).get("notes", []); summ["problems"] += tonal.gates(info.get("tonal"), meta.get("gates"))
    try:                                                                                      # P135: this track against all earlier ones (always reported; gates opt-in)
        fdb = fresh.load(); rev = fresh.review(info, title, fdb); summ["fresh"] = {k: rev[k] for k in ("reuse_share", "worn", "rhythm_repeats", "harmony_seen", "tracks_known")}
        summ["fresh_notes"] = rev["notes"]; summ["problems"] += fresh.gates(rev, meta.get("gates")); summ["harmony"] = {k: v for k, v in (info.get("harmony") or {}).items() if k != "tension"} or None; summ["line_fit"] = info.get("line_fit")
        if not meta.get("fresh_skip"): fresh.record(info, title, fdb)
    except Exception as e: summ["fresh"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if meta.get("reference"):                                                                 # P142: this render against the reference
        try:
            from . import blueprint
            cmp = blueprint.compare(mp3, meta["reference"], bpm=trk.bpm, ref_bpm=meta.get("reference_bpm"))
            summ["reference"] = {k: cmp[k] for k in ("score", "diff", "ours", "ref")}; summ["reference_notes"] = blueprint.notes_for_summary(cmp)
        except Exception as ex: summ["reference"] = {"error": f"{type(ex).__name__}: {str(ex)[:120]}"}; summ["reference_notes"] = []
        if ref_curve is not None: summ["match_eq"] = ref_curve
    if a.review:
        from .review import review
        summ["review"] = review(mp3, summ, info, meta, os.path.join(outdir, f"{name}.review.txt"))
    try:
        from . import soundgate
        bad = soundgate.report(info.get("sources")); bad.update({q["sample"]: [f"played {q['mean_shift']:+.0f} st from its note on {q['share']:.0%} of notes"] for q in summ.get("squeezed", []) if q.get("share", 0) > .3 and abs(q.get("mean_shift", 0)) > 7 and q.get("policy") != "fold"})
        summ["bad_sounds"] = bad
    except Exception as ex: summ["bad_sounds"] = {}; print("soundgate:", ex)
    summ["gate_failed"] = ears.gate_failures(summ, meta)                                      # hard stop: silent layer = muted part (2026-11-16)
    _flags = [k for k in ("allow_silent", "allow_bad_sounds") if meta.get(k)]                  # P146: the flags alone do not open the gates
    if _flags and ears.gate_override(meta): summ["gate_override_reason"] = str(meta.get("allow_reason")); summ["problems"].append("ГЕЙТ ОБХОД по просьбе Стаса: " + str(meta.get("allow_reason")))
    elif _flags: summ["ignored_allow_flags"] = _flags; summ["problems"].append("флаги META " + ", ".join(_flags) + " игнорируются: гейты включены (обход только по просьбе Стаса: env AUTODJ_GATE_OVERRIDE=1 + allow_reason)")
    if summ["gate_failed"]: print("ГЕЙТ: " + ", ".join(summ["gate_failed"]) + ": отправка заблокирована. Исправь звуки или слои: флаги allow_* не помогают", flush=True)
    if a.send and not summ["gate_failed"]: summ["telegram"] = send_telegram(mp3, title)
    json.dump(summ, open(os.path.join(outdir, f"{name}.summary.json"), "w"), ensure_ascii=False, indent=1)
    try:
        with open(REGISTRY, "a") as f:
            f.write(json.dumps({"date": datetime.datetime.now().isoformat(timespec="minutes"), "agent": getpass.getuser(), "score": os.path.abspath(a.score),
                                **{k: summ[k] for k in ("name", "title", "bpm", "seed", "dur_s")}, **{k: meta.get(k) for k in ("key", "story", "fingerprint")}}, ensure_ascii=False) + "\n")
    except OSError as e: summ["registry"] = f"not written: {e}"
    print(json.dumps(summ, ensure_ascii=False))
    return summ
