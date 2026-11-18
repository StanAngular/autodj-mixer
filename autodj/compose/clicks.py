"""P140 (2026-11-18, opus_pack: «резкий щелчок в верху» in every render, -10.8..-22 dBFS, and no edit made it go away).

The cause found first: the clock sidechain (autodj.generate.mixbus.sidechain_duck, every `trk.add(..., duck=-6)` without a key)
dropped the gain in ONE sample on every beat. A bass with no top at all (-142 dB above 6 kHz) came out of it with a -16 dBFS
step in the 6+ kHz band: a tick on every beat, under the kick, in every track that ducks its bass / hook / pad by the clock.
It now ramps over 0.5 ms (raised cosine, ending exactly on the beat): the step drops to -51 dB, the pump is the same.

The old number (checks.stereo_metrics hf_step_dbfs) is the biggest sample-to-sample step of the 6+ kHz band of the mastered mp3.
It cannot tell a click (the wave JUMPS: a cut, a gain step) from a hat or a snare (a fast but real attack), and it says
neither when nor which layer. The tools here:

  edges(x)        how hard a recording starts / ends: the first / last sounding sample against its peak. A one-shot cut on its
                  transient (many drum packs) jumps from silence to 30 % of full scale in one sample: a click on every hit.
  declick(x)      ramps only such edges (0.5 ms in, 3 ms out); a recording that starts and ends at zero comes back unchanged
                  (the same array). Track.place() and the sampler voices use it; Track.declick = False turns it off.
  steps(x, sr)    the isolated discontinuities of a buffer: the 6+ kHz step against the 6+ kHz energy around it. A hat's
                  attack sits in its own noise (10-16 dB above it), a click stands alone (20-70 dB).
  report(trk, m)  Track.finish(): the bus's steps, each attributed to the layer that made it (Track.add keeps every layer's
                  steps) -> info["clicks"]; explain() turns it into the notes of the run summary. When there is no step at all
                  (only_attacks) the run drops the «резкий щелчок» gate: what it measured were hats / snares / kick clicks
                  (the loud top has its own gate, high_db). META gates {"click_strict": True} keeps the old gate.
  python -m autodj.compose.clicks scan DIR     the recordings of a pack with hard edges, worst first."""
import os, sys
import numpy as np
from scipy.signal import butter, sosfilt

SR = 44100
EDGE = .02                       # a first / last sounding sample above 2 % of the peak is a cut, not a start from silence
SILENT = 1e-4                    # below this (re the peak) the recording is silent (pre-roll / tail)
ISO_DB = 18.0                    # a step that stands this far above the 6+ kHz energy around it is a discontinuity (hats: <= 16)
HEAD = 4096                      # how far into a recording the first sounding sample is looked for

def _peak(x):
    return float(max(x.max(), -x.min())) if len(x) else 0.0                          # no |x| copy of a 5-minute buffer

def edges(x):
    """(start, end): the first / last sounding sample of a recording relative to its peak (0 = starts / ends from silence)"""
    x = np.asarray(x); pk = _peak(x)
    if pk <= 0: return 0.0, 0.0
    a = np.abs(x).max(1) if x.ndim == 2 else np.abs(x); thr = pk * SILENT
    h = a[:HEAD]; i0 = int(np.argmax(h > thr)) if np.any(h > thr) else 0
    t = a[-HEAD:]; i1 = len(t) - 1 - int(np.argmax(t[::-1] > thr)) if np.any(t > thr) else len(t) - 1
    return float(h[i0] / pk), float(t[i1] / pk)

def declick(x, sr=SR, in_ms=.5, out_ms=3.0, edge=EDGE):
    """ramp a hard start / end (only those): returns the SAME array when both edges are already soft"""
    x = np.asarray(x)
    if x.ndim not in (1, 2) or len(x) < 4: return x
    pk = _peak(x)
    if pk <= 0: return x
    a = np.abs(x).max(1) if x.ndim == 2 else np.abs(x); thr = pk * SILENT
    h = a[:HEAD]; i0 = int(np.argmax(h > thr)) if np.any(h > thr) else 0
    t = a[-HEAD:]; i1 = len(x) - len(t) + len(t) - 1 - int(np.argmax(t[::-1] > thr)) if np.any(t > thr) else len(x) - 1
    hard_in, hard_out = in_ms > 0 and a[i0] > edge * pk, out_ms > 0 and a[i1] > edge * pk
    if not (hard_in or hard_out): return x
    y = np.array(x, np.float32, copy=True)
    if hard_in:
        k = max(2, min(int(sr * in_ms / 1000), (len(y) - i0) // 2)); r = _rise(k)
        y[i0:i0 + k] *= r[:, None] if y.ndim == 2 else r
    if hard_out:
        k = max(2, min(int(sr * out_ms / 1000), (i1 + 1) // 2)); r = _rise(k)[::-1]
        y[i1 + 1 - k:i1 + 1] *= r[:, None] if y.ndim == 2 else r
    return y

def _rise(k):
    """raised cosine 0 -> 1 over k samples (a linear ramp of a full-scale edge still jumps 1/k in its first sample)"""
    return (.5 - .5 * np.cos(np.pi * np.arange(k) / (k - 1))).astype(np.float32)

def _dstep(x, sr, band):
    """|sample-to-sample step| of the band above `band` Hz, the larger of the channels. float32 and one channel at a time (a 5-minute
    layer would need ~0.6 GB in float64 at once). The 1e-12 offset keeps the filter out of denormal numbers in long silences (a layer
    silent for minutes made sosfilt 50x slower); the high-pass removes the offset itself."""
    a = np.asarray(x, np.float32); a = a[:, None] if a.ndim == 1 else a
    sos = butter(4, band, "high", fs=sr, output="sos").astype(np.float32); d = None
    for c in range(a.shape[1]):
        h = sosfilt(sos, a[:, c] + np.float32(1e-12)); dc = np.diff(h); del h; np.abs(dc, out=dc)
        d = dc if d is None else np.maximum(d, dc, out=d)
    return d

def steps(x, sr=SR, band=6000.0, floor=None, iso_db=ISO_DB, gap_s=.002, keep=4000):
    """isolated discontinuities of a buffer. Returns {"max": (i, value, iso_db) of the biggest 6+ kHz step whatever it is,
    "idx", "val", "iso": arrays of the isolated ones (value = |step| of the 6+ kHz band, iso = dB above its surroundings)}.
    floor: ignore steps below this value (default: 40 dB under the buffer's peak: quieter ones drown in the layer itself)."""
    x = np.asarray(x)
    if len(x) < 64 or _peak(x) <= 0: return {"max": None, "idx": np.zeros(0, np.int64), "val": np.zeros(0, np.float32), "iso": np.zeros(0, np.float32)}
    d = _dstep(x, sr, band)
    floor = _peak(x) * 1e-2 if floor is None else floor
    i_max = int(np.argmax(d)); W, C = max(4, int(.003 * sr)), max(2, int(.0004 * sr))
    cs = np.square(d, dtype=np.float64); np.cumsum(cs, out=cs)                       # running energy, in place
    S = lambda i: np.where(i > 0, cs[np.maximum(i - 1, 0)], 0.0)                         # sum of d^2 before sample i
    def iso_at(p):
        p = np.asarray(p, np.int64); n = len(d)
        lo, hi = np.clip(p - W, 0, n), np.clip(p + W + 1, 0, n); clo, chi = np.clip(p - C, 0, n), np.clip(p + C + 1, 0, n)
        e = (S(hi) - S(lo)) - (S(chi) - S(clo)); cnt = np.maximum((hi - lo) - (chi - clo), 1)
        return 20 * np.log10(d[p] / (np.sqrt(np.maximum(e, 0) / cnt) + 1e-12))
    B = max(1, int(gap_s * sr)); nb = len(d) // B                                     # the strongest point of every 2 ms: a click 15 ms
    blk = d[:nb * B].reshape(nb, B); j = blk.argmax(1); pk = np.arange(nb) * B + j         # before a hat is still a candidate (iso sorts them)
    pk = pk[blk[np.arange(nb), j] >= floor]
    iso = iso_at(pk) if len(pk) else np.zeros(0); ok = iso >= iso_db; pk, iso = pk[ok], iso[ok]
    if len(pk) > 1:                                                                   # one click split over two blocks counts once
        a_ = np.where(np.diff(pk) < B)[0]; first = d[pk[a_]] < d[pk[a_ + 1]]; drop = np.zeros(len(pk), bool)
        drop[a_[first]] = True; drop[a_[~first] + 1] = True; pk, iso = pk[~drop], iso[~drop]
    if len(pk) > keep: o = np.argsort(d[pk])[::-1][:keep]; pk, iso = pk[o], iso[o]
    o = np.argsort(pk); pk, iso = pk[o], iso[o]
    return {"max": (i_max + 1, float(d[i_max]), float(iso_at([i_max])[0])), "idx": (pk + 1).astype(np.int64), "val": d[pk].astype(np.float32), "iso": iso.astype(np.float32)}

def _db(v):
    return round(float(20 * np.log10(max(float(v), 1e-12))), 1)

def _mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"

def report(trk, m, scale=1.0, top=8, near_ms=1.0):
    """the bus `m` (as written, scale = what the bus was multiplied by) -> {"bus": ..., "layers": ..., "declicked": n}"""
    sr = trk.sr; st = steps(m, sr); lay = getattr(trk, "steps", {}) or {}; near = int(near_ms / 1000 * sr)
    def who(i):
        best, bv = None, 0.0
        for name, s in lay.items():
            idx = s["idx"]
            if not len(idx): continue
            j = np.searchsorted(idx, i); cand = [k for k in (j - 1, j) if 0 <= k < len(idx) and abs(int(idx[k]) - i) <= near]
            for k in cand:
                if s["val"][k] > bv: best, bv = name, float(s["val"][k])
        return best
    out = {"bus": {"n_steps": int(len(st["idx"])), "steps": []}, "layers": {}, "declicked": int(getattr(trk, "declicked", 0)),
           "where": "bus before the master (dBFS of the _raw.wav, the master raises it)"}
    if st["max"] is not None:
        i, v, iso = st["max"]; out["bus"]["max"] = {"t": round(i / sr, 3), "dbfs": _db(v), "iso_db": round(iso, 1),
                                                    "kind": "step" if iso >= ISO_DB else "attack", "layer": who(i)}
    order = np.argsort(st["val"])[::-1][:top]
    for k in order:
        i = int(st["idx"][k]); out["bus"]["steps"].append({"t": round(i / sr, 3), "dbfs": _db(st["val"][k]), "iso_db": round(float(st["iso"][k]), 1), "layer": who(i)})
    for name, s in lay.items():
        if not len(s["idx"]): continue
        w = int(np.argmax(s["val"])); out["layers"][name] = {"n_steps": int(len(s["idx"])), "worst_dbfs": _db(s["val"][w] * scale), "worst_t": round(int(s["idx"][w]) / sr, 3)}
    return out

def only_attacks(c):
    """True when the render has no discontinuity at all: the biggest 6+ kHz jump is an attack, no layer and no bus step"""
    if not c or "bus" not in c or c.get("error"): return False
    mx = c["bus"].get("max") or {}
    return mx.get("kind") == "attack" and not c["bus"].get("n_steps") and not c.get("layers")

def explain(c):
    """Russian notes for the run summary (empty when there is nothing to say)"""
    if not c or "bus" not in c: return []
    notes = []; L = c.get("layers") or {}
    if L:
        worst = sorted(L.items(), key=lambda kv: -kv[1]["worst_dbfs"])[:4]
        notes.append("разрывы волны (щелчки) в слоях: " + ", ".join(f"{n} {v['n_steps']} шт., худший {v['worst_dbfs']} дБFS на {_mmss(v['worst_t'])}" for n, v in worst))
    mx = c["bus"].get("max")
    if mx:
        if mx["kind"] == "attack": notes.append(f"самый резкий перепад верха ({_mmss(mx['t'])}) — атака (хэт/перкуссия/щёлк бочки), не разрыв волны: метрика hf_step его и видит")
        else: notes.append(f"самый резкий перепад верха ({_mmss(mx['t'])}) — разрыв волны" + (f" в слое {mx['layer']}" if mx.get("layer") else " в шине (эффект на всём миксе, пространство или шина группы)"))
    orphan = [s for s in c["bus"].get("steps", []) if not s.get("layer")]
    if orphan: notes.append("разрывы без слоя (fx на всём миксе / шины / пространства): " + ", ".join(_mmss(s["t"]) for s in orphan[:5]))
    if c.get("declicked"): notes.append(f"сглажено краёв семплов при раскладке: {c['declicked']} (семпл начинался/кончался не с нуля)")
    return notes

def scan(root, limit=60, edge=EDGE):
    """recordings under root whose first / last sounding sample is above `edge` of their peak, worst first"""
    import soundfile as sf
    out = []
    for dp, _, fs in os.walk(root):
        for f in fs:
            if not f.lower().endswith((".wav", ".aif", ".aiff", ".flac")): continue
            p = os.path.join(dp, f)
            try: x, _ = sf.read(p, dtype="float32", always_2d=True)
            except Exception: continue
            s, e = edges(x)
            if max(s, e) > edge: out.append((max(s, e), s, e, p))
    out.sort(key=lambda r: -r[0]); return out[:limit]

def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 2 or a[0] != "scan": print("usage: python -m autodj.compose.clicks scan DIR [LIMIT]"); return 2
    rows = scan(a[1], int(a[2]) if len(a) > 2 else 60)
    for w, s, e, p in rows: print(f"start {s:5.1%}  end {e:5.1%}  {p}")
    print(f"{len(rows)} recording(s) with a hard edge (declick() ramps them when they are placed)"); return 0

if __name__ == "__main__":
    sys.exit(main())
