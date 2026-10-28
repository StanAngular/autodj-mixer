"""P121 (2026-10-28): STATIC wide stereo. Стас banned ear-to-ear motion (autopan, ping-pong, alternating pan = «мерцание») and asked for
«расширенное стерео». Width here never moves in time: side boost above a split frequency, allpass decorrelation, Haas delay, L/R split
of detuned copies, fixed binaural-style positions. The low end stays mono. balance_stats() measures motion so a gate can tell the two apart."""
import numpy as np
from scipy.signal import butter, sosfilt, lfilter

SR = 44100

def ms_widen(x, amt=1.7, hp=400, sr=SR):
    """side signal above hp gets amt x gain (1.0 = unchanged); everything below hp is untouched, so the low end keeps its width (mono)"""
    M = (x[:, 0] + x[:, 1]) / 2; S = (x[:, 0] - x[:, 1]) / 2; Sh = sosfilt(butter(2, hp, "high", fs=sr, output="sos"), S)
    S2 = S + (amt - 1) * Sh; return np.stack([M + S2, M - S2], 1).astype(np.float32)

def decorr(m, sr=SR, seed=0, g=.55, wet=.8):
    """mono -> stereo with DIFFERENT Schroeder allpass chains per channel (fixed, no modulation); wet mixes with the mono original.
    Bug fixed 2026-10-28 (found by the width test): two draws from the same delay list can give the same set, and allpass chains commute, so both channels
    came out identical (width 0). The right chain now uses its own delays, 15-60 % longer, so the two chains can never coincide."""
    r = np.random.default_rng(seed); base = r.uniform(2.0, 11.0, 5); delays = [base, base * r.uniform(1.15, 1.6, 5) + .7]; out = []
    for ds in delays:
        y = np.asarray(m, np.float64).copy()
        for d_ms in ds:
            d = int(d_ms / 1000 * sr); b = np.zeros(d + 1); b[0] = -g; b[d] = 1; a = np.zeros(d + 1); a[0] = 1; a[d] = -g; y = lfilter(b, a, y)
        out.append(y)
    st = np.stack(out, 1); return (st * wet + np.asarray(m)[:, None] * (1 - wet)).astype(np.float32)

def haas(x, ms=14.0, sr=SR):
    """right channel delayed by ms (static width cue)"""
    d = max(1, int(ms / 1000 * sr)); y = x.copy(); y[d:, 1] = x[:-d, 1]; y[:d, 1] = 0; return y

def place(m, az, sr=SR):
    """mono source at a FIXED position az in [-1, 1]: level difference + up to 0.6 ms interaural delay + far-ear shadow (LPF 5 kHz)"""
    m = np.asarray(m, np.float32); th = (az + 1) * np.pi / 4; gl, gr = np.cos(th), np.sin(th); d = int(abs(az) * .0006 * sr)
    far = sosfilt(butter(1, 5000, "low", fs=sr, output="sos"), m); far = np.concatenate([np.zeros(d, np.float32), far[:len(m) - d]]) if d else far
    L, R = m * gl, m * gr
    if az > 0: L = far * gl
    elif az < 0: R = far * gr
    return np.stack([L, R], 1).astype(np.float32)

def width_ratio(x, hp=400, sr=SR):
    """side/mid RMS ratio above hp (0 = mono, ~1 = very wide)"""
    h = sosfilt(butter(4, hp, "high", fs=sr, output="sos"), x, axis=0); M = (h[:, 0] + h[:, 1]) / 2; S = (h[:, 0] - h[:, 1]) / 2
    return float(np.sqrt((S ** 2).mean() / ((M ** 2).mean() + 1e-12)))

def balance_stats(x, sr=SR, hp=400, win_s=1.0):
    """L/R level balance (dB) per 1 s window above hp: std and range. A static wide image has std < 1 dB; autopan / ping-pong / hopping nodes swing it.
    Windows quieter than -60 dB below the loudest are ignored (silence has no balance)."""
    h = sosfilt(butter(4, hp, "high", fs=sr, output="sos"), x, axis=0); n = int(win_s * sr); step = n // 2; bal = []
    ref = float(np.sqrt((h ** 2).mean()) + 1e-12)
    for i in range(0, len(h) - n, step):
        l, r = float((h[i:i + n, 0] ** 2).mean()), float((h[i:i + n, 1] ** 2).mean())
        if (l + r) / 2 < (ref * 10 ** (-60 / 20)) ** 2: continue
        bal.append(10 * np.log10((l + 1e-12) / (r + 1e-12)))
    return {"std_db": round(float(np.std(bal)), 2) if bal else 0.0, "min_db": round(float(min(bal)), 1) if bal else 0.0, "max_db": round(float(max(bal)), 1) if bal else 0.0}

def width_high(a, sr=SR, hp=400):
    """alias used by checks.stereo_metrics"""
    return width_ratio(a, hp, sr)

def balance_std(a, sr=SR, hp=400):
    """alias used by checks.stereo_metrics: std (dB) of the per-second L/R balance above hp"""
    return balance_stats(a, sr, hp)["std_db"]
