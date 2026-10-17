"""Pre-master (body level + clean soft clip of transients) and the warm master with a lookahead limiter."""
import io, subprocess
import numpy as np, soundfile as sf
from .core import sat, rms

def premaster(src, dst, body_db=-16.0, drive_db=3.0, pre_eq=()):
    """pre_eq: pedalboard plugins applied first (used by the auto-fixes: high shelf / low shelf)"""
    from pedalboard import Pedalboard
    x, sr = sf.read(src, dtype="float32")
    if pre_eq: x = Pedalboard(list(pre_eq))(x.T.copy(), sr).T
    r = rms(x[sr * 10:-sr * 10] if len(x) > sr * 30 else x); x = x * (10 ** (body_db / 20) / r)
    p = np.abs(x).max(); y = sat(x * (.5 / p) / .5, drive_db) * .5; y *= rms(x) / rms(y)
    sf.write(dst, y.astype(np.float32), sr, subtype="FLOAT")

def warm(src, dst, target=-14.0, ceil_db=-1.5, mode="warm"):
    """tame 2.5-5 kHz edge and the top, a little low warmth, slow glue, lookahead brickwall. Returns limiter stats."""
    from pedalboard import (Pedalboard, HighpassFilter, LowShelfFilter, HighShelfFilter, PeakFilter, LowpassFilter, Compressor)
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    a, sr = sf.read(src, dtype="float32")
    if mode == "club":      # club/remix: no presence or top cuts (the warm chain made remixes dull, Стас 2026-10-17), clean air, less box
        chain = [HighpassFilter(28), LowShelfFilter(110, 0.6), PeakFilter(380, -1.5, 1.0), PeakFilter(3300, -0.8, 1.0), HighShelfFilter(11000, 1.5), LowpassFilter(19000),
                 Compressor(threshold_db=-18, ratio=1.5, attack_ms=30, release_ms=250)]
    else:
        chain = [HighpassFilter(28), LowShelfFilter(140, 1.2), PeakFilter(320, -0.8, 1.0), PeakFilter(3300, -3.0, 0.8),
                 PeakFilter(6500, -2.0, 1.0), HighShelfFilter(4500, -1.4), HighShelfFilter(10000, -2.5), LowpassFilter(17500),
                 Compressor(threshold_db=-18, ratio=1.5, attack_ms=40, release_ms=300)]
    x = Pedalboard(chain)(a.T.copy(), sr)
    body = lambda z: 20 * np.log10(np.sqrt((z[:, int(.1 * z.shape[1]):int(.9 * z.shape[1])].astype(np.float64) ** 2).mean()) + 1e-12)
    ceil = 10 ** (ceil_db / 20); L = int(sr * .04)
    def limit(z):
        need = np.minimum(1.0, ceil / (np.abs(z).max(0) + 1e-9)).astype(np.float32)
        gg = uniform_filter1d(minimum_filter1d(need, 2 * L + 1), 2 * L + 1); return z * np.minimum(gg, need)[None], gg
    g = target - body(x)
    for _ in range(8):
        y, gg = limit(x * 10 ** (g / 20)); r = body(y)
        if abs(r - target) < 0.2: break
        g += target - r
    buf = io.BytesIO(); sf.write(buf, y.T, sr, format="WAV", subtype="PCM_24")
    ext = ["-c:a", "aac", "-b:a", "192k"] if dst.endswith(".m4a") else ["-b:a", "320k"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "-", *ext, dst], input=buf.getvalue(), check=True)
    return {"body_db": round(r, 1), "limiter_max_db": round(float(-20 * np.log10(gg.min() + 1e-9)), 1),
            "limiter_avg_db": round(float(-20 * np.log10(np.mean(gg[int(.1 * len(gg)):int(.9 * len(gg))]))), 2),
            "peak_db": round(float(20 * np.log10(np.abs(y).max())), 1)}
