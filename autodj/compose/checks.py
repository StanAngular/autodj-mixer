"""Objective checks of a finished render and the gates that encode Стас's ear notes:
хрип (limiter crush), «шик-шик» (loud top), гул (sub), parts jumping in level, voice sticking out, sudden spikes."""
import io, subprocess
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt

# high_db = 3-14 kHz band vs whole mix: Sieben v1 (-15.8, «шик-шик») failed by ear, Sieben v2 (-23.1) passed.
GATES = dict(clash_ratio=.12, limiter_max_db=3.0, high_db=-19.0, sub_mean=.35, sub_max=.50, jump_db=4.0, break_drop_db=8.0, voice_lift_db=6.0, spikes=0)
BANDS = [(20, 60, "sub"), (60, 150, "bass"), (150, 400, "lowmid"), (400, 2000, "mid"), (2000, 6000, "himid"), (6000, 16000, "air")]

def _read(path):
    w = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "wav", "-ac", "2", "-ar", "44100", "-"], capture_output=True).stdout
    return sf.read(io.BytesIO(w), dtype="float32")

def _db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12)

def _shares(x, sr):
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2; f = np.fft.rfftfreq(len(x), 1 / sr); tot = X[(f > 20) & (f < 16000)].sum() + 1e-12
    return [X[(f >= lo) & (f < hi)].sum() / tot for lo, hi, _ in BANDS]

def analyze(path, info):
    a, sr = _read(path); m = a.mean(1); bar = 240 / info["bpm"]; out = {"sections": []}
    for s0, s1, name, brk in info["plan"]:
        x = m[int(s0 * bar * sr):int(s1 * bar * sr)]
        if len(x) < 2 * sr: continue
        sh = np.mean([_shares(x[i:i + 2 * sr], sr) for i in range(0, len(x) - 2 * sr, 4 * sr)] or [_shares(x[:2 * sr], sr)], 0)
        out["sections"].append({"name": name, "brk": brk, "rms": round(_db(x), 1), **{n: round(float(v), 3) for (_, _, n), v in zip(BANDS, sh)}})
    hb = sosfilt(butter(4, [3000, 14000], "band", fs=sr, output="sos"), m); out["high_db"] = round(_db(hb) - _db(m), 1)
    main = [s for s in out["sections"] if not s["brk"]]; med = np.median([s["rms"] for s in main]) if main else 0
    out["jump_db"] = round(max([abs(s["rms"] - med) for s in main] or [0]), 1)
    out["break_drop_db"] = round(max([med - s["rms"] for s in out["sections"] if s["brk"]] or [0]), 1)
    out["sub_mean"] = round(float(np.mean([s["sub"] for s in main])) if main else 0, 3)
    out["sub_max"] = round(max([s["sub"] for s in main] or [0]), 3)
    bp = sosfilt(butter(4, [300, 3000], "band", fs=sr, output="sos"), m); r = lambda t0, t1: _db(bp[int(t0 * sr):int(t1 * sr)])
    out["voice_lift"] = [[t, lab, round(r(t + .1, t + 2) - r(t - 4, t - .3), 1)] for t, lab in info.get("voice", []) if t > 4.5]
    st = 3 * sr; k = len(m) // st; L = 20 * np.log10(np.sqrt((m[:k * st].reshape(k, st) ** 2).mean(1)) + 1e-9)
    med3 = np.array([np.median(L[max(0, i - 5):i + 5]) for i in range(k)]); out["spikes"] = [round(float(i) * 3 / 60, 1) for i in np.where(L - med3 > 2.5)[0]]
    out["clash_ratio"] = info.get("clash_ratio", 0.0)
    return out

def gates(metrics, master, g=None):
    """list of (code, message). Empty list = passed."""
    g = {**GATES, **(g or {})}; bad = []
    if metrics.get("clash_ratio", 0) > g["clash_ratio"]: bad.append(("clash", f"ноты разных слоёв трутся (м2/м9) в {metrics['clash_ratio']:.0%} тактовых долей"))
    if master["limiter_max_db"] > g["limiter_max_db"]: bad.append(("limiter", f"лимитер давит {master['limiter_max_db']} дБ (хрип)"))
    if metrics["high_db"] > g["high_db"]: bad.append(("high", f"верх {metrics['high_db']} дБ к общему (шик)"))
    if metrics["sub_mean"] > g["sub_mean"] or metrics["sub_max"] > g["sub_max"]: bad.append(("sub", f"саб {metrics['sub_mean']:.0%} в среднем, {metrics['sub_max']:.0%} макс"))
    if metrics["jump_db"] > g["jump_db"]: bad.append(("jump", f"части скачут на {metrics['jump_db']} дБ"))
    if metrics["break_drop_db"] > g["break_drop_db"]: bad.append(("break", f"яма тише на {metrics['break_drop_db']} дБ"))
    loud = [v for v in metrics["voice_lift"] if v[2] > g["voice_lift_db"]]
    if loud: bad.append(("voice", "голос выпирает: " + ", ".join(f"{lab}@{t:.0f}s +{d}" for t, lab, d in loud[:5])))
    if len(metrics["spikes"]) > g["spikes"]: bad.append(("spikes", f"всплески громкости на {metrics['spikes'][:6]} мин"))
    return bad
