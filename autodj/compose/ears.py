"""P125 «Уши» (applied 2026-11-11, Стас: «Давай p125»): a second listener by measurements + the silent-layer check.
 - silent_layers(layers_db): a layer that was added but is silent (None / <= -90 dB). 2026-11-11: an empty `sections` dict made every layer without an explicit env silent in 15 sent tracks and no gate noticed.
 - arc(path, bpm): arrangement arc without listening (loudness range, rises/falls, repetition vs 8/16 bars ago, longest unchanged run); always on, ~2 s.
 - abx(path): Meta Audiobox Aesthetics (PQ production quality, PC complexity, CE enjoyment, CU usefulness) on 3 clips of 20 s at 25/55/85 % of the track; opt-in (--ears or META["ears"]), CPU ~40 s, model 416 MB in ~/.local/lib/abx;
   a hint where it is weak, not a verdict (it under-rates voice chops and pure percussion).
 - ears_gates(summary, gates): optional gates: gates["ears_ce_min"], gates["arc_same8_max"], gates["arc_run_max"]; no key = no gate."""
import os, sys, tempfile
import numpy as np
ABX_PATH = "/home/cclaw/.local/lib/abx"

def silent_layers(layers_db, floor_db=-90.0):
    return sorted(n for n, v in (layers_db or {}).items() if v is None or v <= floor_db)

def gate_override(meta=None):
    """P146 (2026-11-20): `allow_silent` / `allow_bad_sounds` in META do NOTHING by themselves (Hermes hid 5 bad sounds and 2 silent layers with them in Float Acid).
    An intentional exception needs BOTH the environment variable AUTODJ_GATE_OVERRIDE=1 (set only when Стас explicitly asked for it, e.g. a deliberate pseudo-voice) AND a
    non-empty `allow_reason` in META; the reason is written into the summary."""
    import os
    return os.environ.get("AUTODJ_GATE_OVERRIDE") == "1" and bool(str((meta or {}).get("allow_reason", "")).strip())

LITERAL_RUN_MAX = 32          # P149: a layer that plays the very same bars (same steps, same pitches) for more than this many bars is a loop, not music

def literal_runs(notes, bar_s, s16_s, min_notes=2):
    """P149: {layer: (bars, period)} the longest stretch of consecutive bars in which a pitched layer repeats the bar `period` (1..4) bars earlier
    note for note (16th step + midi). notes: {layer: [(t_seconds, midi, vel, dur)]} (Track.notes). Layers with fewer than min_notes notes per bar
    (held pads, single hits) are skipped. A stretch of L equal bars with period p covers L + p bars."""
    out = {}
    for name, ev in (notes or {}).items():
        by = {}
        for e in ev: by.setdefault(int(e[0] / bar_s + 1e-6), []).append((int(round((e[0] % bar_s) / s16_s)) % 16, int(e[1])))
        if not by: continue
        n = max(by) + 1; sig = [tuple(sorted(by.get(b, ()))) for b in range(n)]; best = (0, 0)
        for p in range(1, 5):
            run = 0
            for b in range(p, n):
                run = run + 1 if (sig[b] and sig[b] == sig[b - p] and len(sig[b]) >= min_notes) else 0
                if run and run + p > best[0]: best = (run + p, p)
        if best[0]: out[name] = best
    return out

KICK_BASS_MAX = .5            # P150: more than this share of the bass notes on kick hits = bass and kick play the same rhythm (the unison has no «кач»)

def kick_bass(trk):
    """P150: share of the bass notes that land on a kick hit, from what the layers really played (trk.act["kick"], trk.notes of the bass layers); None when unknown"""
    from .depth import onsets
    try:
        E = (getattr(trk, "act", {}) or {}).get("kick")
        if E is None: return None
        ks = {b: s for b, s in enumerate(onsets(E, trk.bars)) if s}; steps = []
        for name, ev in (trk.notes or {}).items():
            if "bass" in name.lower() or name.lower() == "sub":
                steps += [(int(e[0] / trk.BAR + 1e-6), int(round((e[0] % trk.BAR) / trk.S16)) % 16) for e in ev]
        from .chords import kick_bass_overlap
        r = kick_bass_overlap(steps, ks); return None if r is None else round(r, 2)
    except Exception: return None

def kick_bass_failures(summ, meta=None, override=None):
    """["kick_bass ..."] when the bass sits on the kick (> KICK_BASS_MAX). META["gates"]["kick_bass_max"] moves the limit only under gate_override (P146)."""
    meta = meta or {}; ov = gate_override(meta) if override is None else override
    lim = ((meta.get("gates") or {}).get("kick_bass_max") if ov else None) or KICK_BASS_MAX; r = (summ or {}).get("kick_bass")
    return [f"{r:.0%} нот баса совпадает с бочкой (> {lim:.0%})"] if isinstance(r, (int, float)) and r > lim else []

def literal_failures(summ, meta=None, override=None):
    """names of the layers that loop literally for more than LITERAL_RUN_MAX bars. META["gates"]["literal_run_max"] moves the limit only under
    gate_override(meta) (P146: Стас asked for it + reason); otherwise it is ignored."""
    meta = meta or {}; ov = gate_override(meta) if override is None else override
    lim = ((meta.get("gates") or {}).get("literal_run_max") if ov else None) or LITERAL_RUN_MAX
    return [f"{n} ({r} тактов, период {p})" for n, (r, p) in ((summ or {}).get("literal") or {}).items() if r > lim]

def gate_failures(summ, meta=None, override=None):
    """2026-11-16 (friction top-3): HARD stops. A silent layer means a muted part of the arrangement (15 tracks went out without drums on 2026-11-11);
    reporting it as a problem was not enough. P146: the opt-out flags only count under gate_override(meta) (env + reason), otherwise they are ignored. Returns the list of failed gate names."""
    meta = meta or {}; ov = gate_override(meta) if override is None else override
    out = []
    if (summ or {}).get("silent_layers") and not (ov and meta.get("allow_silent")): out.append("silent_layers")
    if kick_bass_failures(summ, meta, ov): out.append("kick_bass")                       # P150
    if literal_failures(summ, meta, ov): out.append("literal_repeat")                     # P149: a layer that loops the same bars for > 32 bars
    if ov and meta.get("allow_bad_sounds"): return out
    if summ.get("bad_sounds"): out.append("bad_sounds")                       # P139: a detuned/wobbling/noisy one-shot, or a sample played > 7 st from its note on > 30 % of notes
    return out

def arc(path, bpm):
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True); bar = 240 / bpm; n = int(len(y) / sr / bar); feats, rms, cen = [], [], []
    for b in range(n):
        s = y[int(b * bar * sr):int((b + 1) * bar * sr)]
        if len(s) < sr: break
        mf = librosa.feature.mfcc(y=s, sr=sr, n_mfcc=13).mean(1)[1:]; ch = librosa.feature.chroma_stft(y=s, sr=sr).mean(1)
        feats.append(np.concatenate([mf / 20, ch])); rms.append(20 * np.log10(np.sqrt(np.mean(s ** 2)) + 1e-9)); cen.append(float(librosa.feature.spectral_centroid(y=s, sr=sr).mean()))
    if len(feats) < 4: return {"bars": len(feats)}
    F = np.array(feats); F = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9); r = np.array(rms); k = len(F)
    def share(lag):
        s = [float(F[i] @ F[i - lag]) for i in range(lag, k)]; return float(np.mean(np.array(s) > .985)) if s else 0.0
    sim1 = np.array([float(F[i] @ F[i - 1]) for i in range(1, k)]); run = best = 0
    for v in sim1 > .985:
        run = run + 1 if v else 0; best = max(best, run)
    sm = np.convolve(r, np.ones(8) / 8, "valid"); d = np.diff(sm[::4])
    return {"bars": k, "loudness_range_db": round(float(np.percentile(r, 95) - np.percentile(r, 5)), 1), "rises": int((d > 1.0).sum()), "falls": int((d < -1.0).sum()),
            "bar_change": round(float(1 - sim1.mean()), 4), "same_as_8_bars_ago": round(share(8), 2), "same_as_16_bars_ago": round(share(16), 2),
            "longest_unchanged_run_bars": best, "centroid_range_hz": round(float(np.percentile(cen, 95) - np.percentile(cen, 5)))}

def abx(path, clip_s=20.0, at=(.25, .55, .85)):
    """mean Audiobox scores over three clips; None if the model is not installed (never raises)"""
    try:
        import soundfile as sf
        sys.path.insert(0, ABX_PATH)
        import torch, torchaudio
        torchaudio.load = lambda p, *a, **k: (lambda d, sr: (torch.from_numpy(d.T.copy()).float(), sr))(*sf.read(p, dtype="float32", always_2d=True))
        from audiobox_aesthetics.infer import initialize_predictor
        x, sr = sf.read(path, dtype="float32", always_2d=True); n = int(clip_s * sr); paths = []
        with tempfile.TemporaryDirectory() as td:
            for i, f in enumerate(at):
                a = int(max(0, min(len(x) - n, f * len(x) - n / 2))); p = os.path.join(td, f"c{i}.wav"); sf.write(p, x[a:a + n], sr); paths.append(p)
            res = initialize_predictor().forward([{"path": p} for p in paths])
        return {k: round(float(np.mean([r[k] for r in res])), 2) for k in ("CE", "CU", "PC", "PQ")}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}

def ears_gates(summ, gates):
    """optional gates -> list of problem strings (empty when the key is absent or the value is fine)"""
    g = gates or {}; out = []; ar = summ.get("arc") or {}; ea = summ.get("ears") or {}
    if "ears_ce_min" in g and isinstance(ea.get("CE"), (int, float)) and ea["CE"] < g["ears_ce_min"]: out.append(f"скучно по Audiobox: CE {ea['CE']} < {g['ears_ce_min']}")
    if "arc_same8_max" in g and isinstance(ar.get("same_as_8_bars_ago"), (int, float)) and ar["same_as_8_bars_ago"] > g["arc_same8_max"]: out.append(f"повтор: {ar['same_as_8_bars_ago']} тактов совпадает с тактом 8 назад > {g['arc_same8_max']}")
    if "arc_run_max" in g and isinstance(ar.get("longest_unchanged_run_bars"), (int, float)) and ar["longest_unchanged_run_bars"] > g["arc_run_max"]: out.append(f"{ar['longest_unchanged_run_bars']} тактов без изменений > {g['arc_run_max']}")
    return out
