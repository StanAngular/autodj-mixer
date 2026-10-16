"""python -m autodj.compose run SCORE.py --seed 7 --name my_track [--title "..."] [--target -14] [--send]

A score is a .py file with  build(seed) -> Track  (and optional META = {"title":..., "target":..., "gates": {...}}).
Pipeline: render slot -> build -> bus wav -> premaster -> warm master -> checks/gates -> ONE automatic master-side fix
(top shelf / low shelf / lower target) -> re-check -> summary JSON (+ registry line, + Telegram if --send)."""
import argparse, datetime, getpass, importlib.util, json, os, sys, time
from .lock import render_slot
from .master import premaster, warm
from .checks import analyze, gates

REGISTRY = os.environ.get("AUTODJ_COMPOSE_REGISTRY", "/opt/autodj-mixer/shared/compose_registry.jsonl")

def load_score(path):
    spec = importlib.util.spec_from_file_location("score", path); mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(os.path.abspath(path))); spec.loader.exec_module(mod); return mod

def send_telegram(path, title):
    import urllib.request, uuid
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("ALLOWED_CHAT_ID")
    if not (tok and chat): return "skipped: no TELEGRAM_BOT_TOKEN/ALLOWED_CHAT_ID"
    b = uuid.uuid4().hex; data = open(path, "rb").read()
    body = b"".join([f"--{b}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat}\r\n".encode(),
                     f"--{b}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{title}\r\n".encode(),
                     f"--{b}\r\nContent-Disposition: form-data; name=\"performer\"\r\n\r\nКлод\r\n".encode(),
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

def main(argv=None):
    ap = argparse.ArgumentParser(prog="autodj.compose run"); ap.add_argument("cmd", choices=["run"]); ap.add_argument("score")
    ap.add_argument("--seed", type=int, default=1); ap.add_argument("--name"); ap.add_argument("--title"); ap.add_argument("--target", type=float)
    ap.add_argument("--outdir"); ap.add_argument("--send", action="store_true"); ap.add_argument("--keep-wav", action="store_true")
    a = ap.parse_args(argv); t0 = time.time()
    mod = load_score(a.score); meta = getattr(mod, "META", {}); name = a.name or os.path.splitext(os.path.basename(a.score))[0]
    outdir = a.outdir or os.path.join(os.path.dirname(os.path.abspath(a.score)), "out"); os.makedirs(outdir, exist_ok=True)
    target = a.target if a.target is not None else meta.get("target", -14.0); title = a.title or meta.get("title", name)
    raw, pre, mp3 = (os.path.join(outdir, f"{name}{s}") for s in ("_raw.wav", "_pre.wav", ".mp3"))
    with render_slot() as slot:
        print(f"render slot {slot}", flush=True); trk = mod.build(a.seed); info = trk.finish(raw, meta={"title": title, "seed": a.seed})
        premaster(raw, pre); ms = warm(pre, mp3, target); met = analyze(mp3, info); bad = gates(met, ms, meta.get("gates"))
        fixed = []; eq_all, dt_all = [], 0.0
        for _ in range(2):                                         # at most two master-side rounds (an EQ cut can raise the limiter)
            eq, dt = fixes_for(bad, met, ms, meta.get("gates"))
            if not (eq or dt): break
            fixed.append({"codes": [c for c, _ in bad if c in FIXABLE], "before": {"high_db": met["high_db"], "sub_mean": met["sub_mean"], "limiter_max_db": ms["limiter_max_db"]}})
            eq_all += eq; dt_all += dt
            premaster(raw, pre, pre_eq=eq_all); ms = warm(pre, mp3, target + dt_all); met = analyze(mp3, info); bad = gates(met, ms, meta.get("gates"))
    if not a.keep_wav:
        for p in (raw, pre): os.path.exists(p) and os.remove(p)
    summ = {"name": name, "title": title, "file": mp3, "dur_s": round(trk.N / trk.sr), "bpm": trk.bpm, "seed": a.seed, "master": ms,
            "high_db": met["high_db"], "sub_mean": met["sub_mean"], "jump_db": met["jump_db"], "break_drop_db": met["break_drop_db"],
            "voice_max_lift": max([v[2] for v in met["voice_lift"]] or [None], key=lambda v: v or -99), "spikes": met["spikes"],
            "sections": [[s["name"], s["rms"], round(s["sub"] * 100)] for s in met["sections"]],
            "auto_fixed": fixed, "problems": [m for _, m in bad], "render_min": round((time.time() - t0) / 60, 1)}
    if a.send: summ["telegram"] = send_telegram(mp3, title)
    json.dump(summ, open(os.path.join(outdir, f"{name}.summary.json"), "w"), ensure_ascii=False, indent=1)
    try:
        with open(REGISTRY, "a") as f:
            f.write(json.dumps({"date": datetime.datetime.now().isoformat(timespec="minutes"), "agent": getpass.getuser(), "score": os.path.abspath(a.score),
                                **{k: summ[k] for k in ("name", "title", "bpm", "seed", "dur_s")}, **{k: meta.get(k) for k in ("key", "story", "fingerprint")}}, ensure_ascii=False) + "\n")
    except OSError as e: summ["registry"] = f"not written: {e}"
    print(json.dumps(summ, ensure_ascii=False))
    return summ
