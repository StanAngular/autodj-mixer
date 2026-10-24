"""Objective checks of a finished render and the gates that encode Стас's ear notes:
хрип (limiter crush), «шик-шик» (loud top), гул (sub), parts jumping in level, voice sticking out, sudden spikes."""
import io, subprocess
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt

# high_db = 3-14 kHz band vs whole mix: Sieben v1 (-15.8, «шик-шик») failed by ear, Sieben v2 (-23.1) passed.
GATES = dict(mono_low=.01, mono_fold_db=1.5, clash_ratio=.12, limiter_max_db=3.0, high_db=-19.0, sub_mean=.35, sub_max=.50, jump_db=4.0, break_drop_db=8.0, voice_lift_db=6.0, spikes=0)
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
    out.update(mono_metrics(a, sr)); out["rhythm"] = rhythm_metrics(m, sr, info["bpm"])
    return out

def mono_metrics(a, sr):
    """P117: low end in mono (side energy 20-150 Hz < 1 %) and loss when folded to mono (< 1.5 dB)"""
    if a.ndim != 2 or a.shape[1] < 2: return {"mono_low": 0.0, "mono_fold_db": 0.0}
    L, R = a[:, 0].astype(np.float64), a[:, 1].astype(np.float64); sos = butter(4, [20, 150], "band", fs=sr, output="sos")
    lm, ls = sosfilt(sos, (L + R) / 2), sosfilt(sos, (L - R) / 2); em, es = float(np.mean(lm ** 2)), float(np.mean(ls ** 2))
    low = es / (em + es) if em + es > 1e-12 else None
    est = (float(np.mean(L ** 2)) + float(np.mean(R ** 2))) / 2; emo = float(np.mean(((L + R) / 2) ** 2))
    fold = 10 * np.log10(est / emo) if emo > 1e-12 and est > 1e-12 else None
    return {"mono_low": None if low is None else round(low, 4), "mono_fold_db": None if fold is None else round(float(fold), 2)}

def rhythm_metrics(m, sr, bpm, block_bars=8):
    """P117: per 8 bars, onset density (onsets per bar) and the share of onset strength on weak 16ths (a syncopation proxy)"""
    import librosa
    y = librosa.resample(m.astype(np.float32), orig_sr=sr, target_sr=11025) if sr != 11025 else m; sr2 = 11025
    env = librosa.onset.onset_strength(y=y, sr=sr2, hop_length=128); fr = 128 / sr2; s16 = 15 / bpm; out = {"density": [], "offbeat": []}
    nb = int(len(env) * fr / (16 * s16))
    for b0 in range(0, nb, block_bars):
        steps = np.zeros(16)
        for br in range(b0, min(nb, b0 + block_bars)):
            for st in range(16):
                i = int((br * 16 + st) * s16 / fr); steps[st] += env[i:i + 2].max() if i + 2 <= len(env) else 0
        on = librosa.onset.onset_detect(onset_envelope=env[int(b0 * 16 * s16 / fr):int((b0 + block_bars) * 16 * s16 / fr)], sr=sr2, hop_length=128)
        out["density"].append(round(len(on) / block_bars, 1)); tot = steps.sum()
        out["offbeat"].append(round(float(steps[[1, 3, 5, 7, 9, 11, 13, 15]].sum() / tot), 2) if tot > 0 else 0.0)
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
    if metrics.get("mono_low") is not None and metrics["mono_low"] > g["mono_low"]: bad.append(("mono_low", f"бас не в моно: стерео в 20-150 Гц {metrics['mono_low']:.1%}"))
    if metrics.get("mono_fold_db") is not None and metrics["mono_fold_db"] > g["mono_fold_db"]: bad.append(("mono_fold", f"в моно теряется {metrics['mono_fold_db']} дБ"))
    return bad
