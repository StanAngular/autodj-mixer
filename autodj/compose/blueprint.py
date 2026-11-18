"""P142 (2026-11-18, Стас: «иногда даю ему другие треки и прошу их воссоздать ... не всегда получается воссоздать, может не хватает
инструментов»).

To recreate a track the score needs the reference's plan as numbers, not a listening impression. learn.py reads drums / bass of
separated stems and reftrack.py builds from that; what was missing is the rest of the plan, read from the MIX itself:

  read(path)           the blueprint: tempo and bar grid, key, a chord per bar (chroma templates, in-key and bass-note aware),
                       sections (where the bar-to-bar picture changes, snapped to 4-bar phrases) with a letter (A, B, ...: which
                       sections are alike) and an energy level, and per bar: loudness, brightness, onset density, the six bands of
                       checks.BANDS, stereo width, the bass note. Plus the FORM in numbers (Q10 of the opus pack): how often
                       something changes (bars between changes), the longest run of identical bars, how many bars bring new
                       material, how much the loudness travels.
  compare(ours, ref)   the same numbers side by side, a similarity score and the differences that matter, as notes in Russian
                       («у эталона в 150-400 Гц на 4 дБ меньше», «эталон что-то меняет каждые 4 такта, у нас каждые 16», ...).
  match_eq(ours, ref)  the tonal balance by octave, ref minus ours, smoothed and limited (+-4 dB): pedalboard peak filters that
                       move our master toward the reference without touching its level. matchering's idea, not its (GPL) code.
  run: META {"reference": "/path/ref.wav"} puts compare() into the summary ("reference", "reference_notes"); with
       "match_eq": 0.5 (0..1) the EQ goes into the premaster as well.
  python -m autodj.compose.blueprint REF.wav [OURS.mp3] [--bpm 124]"""
import json, os, sys
import numpy as np

SR = 22050
BANDS = [(20, 60, "sub"), (60, 150, "bass"), (150, 400, "lowmid"), (400, 2000, "mid"), (2000, 6000, "himid"), (6000, 11000, "air")]
OCT = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000]
QUAL = {"": (0, 4, 7), "m": (0, 3, 7), "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10), "7": (0, 4, 7, 10)}

def _load(path, sr=SR):
    import librosa
    y, _ = librosa.load(path, sr=sr, mono=False)
    y = np.atleast_2d(y); st = np.stack([y[0], y[min(1, len(y) - 1)]], 0)
    return st.mean(0).astype(np.float32), st.astype(np.float32)

def _grid(m, sr, bpm=None):
    """(bpm, bar start times): beat tracking folded into 85-175 bpm, a straight grid fitted to the beats by least squares, moved
    by half a beat when the kick band says the tracker locked onto the off-beats (hats), the downbeat where the music changes
    most (sections and chords start on bar 1)"""
    import librosa
    from scipy.signal import butter, sosfilt
    hop = 256; oenv = librosa.onset.onset_strength(y=m, sr=sr, hop_length=hop); dur = len(m) / sr
    tempo, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, hop_length=hop, start_bpm=bpm or 120.0, units="time", tightness=120)
    bt = np.asarray(beats, float); tempo = float(np.atleast_1d(tempo)[0]) or 120.0
    T = 60.0 / float(bpm) if bpm else (float(np.median(np.diff(bt))) if len(bt) > 8 else 60.0 / tempo)
    while 60 / T < 85: T /= 2
    while 60 / T > 175: T *= 2
    low = librosa.onset.onset_strength(y=sosfilt(butter(4, 150, "low", fs=sr, output="sos"), m).astype(np.float32), sr=sr, hop_length=hop)
    lt = librosa.frames_to_time(np.arange(len(low)), sr=sr, hop_length=hop); at = lambda g: float(np.mean(np.interp(g, lt, low))) if len(g) else 0.0
    ot = librosa.frames_to_time(np.arange(len(oenv)), sr=sr, hop_length=hop); env = oenv / (oenv.max() + 1e-9) + low / (low.max() + 1e-9)
    def comb(Tc, phases):
        k = np.arange(int(dur / Tc)); return max((float(np.mean(np.interp(ph + k * Tc, ot, env))), ph) for ph in phases)
    if not bpm:                                                                          # electronic music sits on a straight grid:
        cands = T * (1 + np.linspace(-.03, .03, 241)); sc = [comb(Tc, np.linspace(0, Tc, 16, endpoint=False))[0] for Tc in cands]   # the
        T = float(cands[int(np.argmax(sc))])                                             # period whose grid catches the most onsets
    t0 = comb(T, np.linspace(0, T, 96, endpoint=False))[1]
    g0 = np.arange(t0, dur, T)
    if at((g0 + T / 2)[g0 + T / 2 < dur]) > 1.3 * at(g0): t0 = (t0 + T / 2) % T                  # the kick is on the beat
    beats = np.arange(t0, dur, T)
    mf = librosa.feature.mfcc(y=m, sr=sr, n_mfcc=13, hop_length=512); fr = librosa.frames_to_time(np.arange(mf.shape[1]), sr=sr, hop_length=512)
    def bar_feats(starts):
        out = []
        for a, b in zip(starts, starts[1:]):
            s = (fr >= a) & (fr < b); out.append(mf[:, s].mean(1) if s.any() else np.zeros(13))
        return np.array(out)
    best, phase = -1.0, 0
    for p in range(4):
        st = beats[p::4]
        if len(st) < 6: continue
        F = bar_feats(st); d = np.linalg.norm(np.diff(F, axis=0), axis=1)          # change between consecutive bars
        sc = float(np.mean(np.sort(d)[-max(2, len(d) // 8):]))                     # the biggest changes fall on bar lines
        if sc > best: best, phase = sc, p
    starts = list(beats[phase::4])
    while starts and starts[0] - 4 * T > -T * .5: starts.insert(0, starts[0] - 4 * T)   # the bars before the first full one
    return round(60.0 / T, 2), np.maximum(np.array(starts), 0.0)

def _chord(ch, bass_pc, key_pcs):
    best = (-9, None, None)
    for r in range(12):
        for q, iv in QUAL.items():
            t = np.zeros(12); t[[(r + i) % 12 for i in iv]] = 1.0
            s = float(ch @ t / (np.linalg.norm(ch) * np.linalg.norm(t) + 1e-9))
            s += .06 * all((r + i) % 12 in key_pcs for i in iv) + (.12 if bass_pc == r else 0) - .02 * (len(iv) - 3)
            if s > best[0]: best = (s, r, q)
    from .tonal import NAMES
    return NAMES[best[1]] + best[2], [(best[1] + i) % 12 for i in QUAL[best[2]]]

def _novelty(S, w=4):
    """Foote novelty on a self-similarity matrix with a checkerboard kernel of half-width w bars"""
    n = len(S); out = np.zeros(n)
    for i in range(w, n - w + 1):
        a, b = S[i - w:i, i - w:i], S[i:i + w, i:i + w]; c = S[i - w:i, i:i + w]
        out[i] = (a.sum() + b.sum() - 2 * c.sum()) / (w * w)
    return out

def read(path, bpm=None, sr=SR, save=True):
    """the blueprint of a recording (see the module doc) -> dict; saved as <path>.blueprint.json when save"""
    import librosa
    from .tonal import best_key, NAMES, MAJOR
    m, st = _load(path, sr); a_ = np.abs(m); snd = np.where(a_ > a_.max() * 1e-3)[0]
    end_s = (snd[-1] + 1) / sr if len(snd) else len(m) / sr                                 # where it stops sounding (tails, padding)
    bpm, starts = _grid(m, sr, bpm); hop = 512
    starts = starts[starts < end_s - min(1.0, .5 * 240 / bpm)]; ends = np.append(starts[1:], min(len(m) / sr, starts[-1] + (starts[1] - starts[0]) if len(starts) > 1 else len(m) / sr))
    S = np.abs(librosa.stft(m, n_fft=4096, hop_length=hop)) ** 2; f = librosa.fft_frequencies(sr=sr, n_fft=4096); fr = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop)
    H = librosa.effects.harmonic(m, margin=2.0)
    chroma = librosa.feature.chroma_cqt(y=H, sr=sr, hop_length=hop, fmin=librosa.note_to_hz("C3"), n_octaves=4)    # chords: above the kick and the sub
    cfr = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr, hop_length=hop)
    lowc = librosa.feature.chroma_cqt(y=H, sr=sr, hop_length=hop, fmin=librosa.note_to_hz("C1"), n_octaves=3)
    mf = librosa.feature.mfcc(S=librosa.power_to_db(librosa.feature.melspectrogram(S=S, sr=sr)), n_mfcc=13)
    on = librosa.onset.onset_detect(y=m, sr=sr, hop_length=256, units="time")
    side = (st[0] - st[1]) / 2; mid = (st[0] + st[1]) / 2
    from scipy.signal import butter, sosfilt
    hp = butter(2, 400, "high", fs=sr, output="sos"); side_h, mid_h = sosfilt(hp, side), sosfilt(hp, mid)
    bars = []; arcv = []
    for a, b in zip(starts, ends):
        s = (fr >= a) & (fr < b); cs = (cfr >= a + .1 * (b - a)) & (cfr < b - .1 * (b - a)); i0, i1 = int(a * sr), int(b * sr)
        P = S[:, s].sum(1) if s.any() else np.zeros(len(f)); tot = P[(f >= 20) & (f < 11000)].sum() + 1e-12
        x = m[i0:i1]; r = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9) if len(x) else -120.0
        ch = chroma[:, cs].mean(1) if cs.any() else np.zeros(12); lc = lowc[:, cs].mean(1) if cs.any() else np.zeros(12)
        bars.append({"t": round(float(a), 3), "db": round(float(r), 1), "centroid": round(float((f * P).sum() / (P.sum() + 1e-12))),
                     "onsets": int(((on >= a) & (on < b)).sum()), "bands": [round(float(P[(f >= lo) & (f < hi)].sum() / tot), 4) for lo, hi, _ in BANDS],
                     "width": round(float(np.sqrt(np.mean(side_h[i0:i1] ** 2)) / (np.sqrt(np.mean(mid_h[i0:i1] ** 2)) + 1e-9)), 3),
                     "_chroma": ch, "_bass": int(np.argmax(lc)) if lc.max() > 0 else None})
        v = np.concatenate([mf[1:, s].mean(1) / 20 if s.any() else np.zeros(12), ch / (np.linalg.norm(ch) + 1e-9)]); arcv.append(v / (np.linalg.norm(v) + 1e-9))
    h = np.sum([b["_chroma"] for b in bars], 0) if bars else np.zeros(12); _, tonic, mode = best_key(h)
    key_pcs = set(((MAJOR + (tonic if mode == "major" else tonic + 3)) % 12).tolist())
    for b in bars:
        b["chord"], _ = _chord(b["_chroma"], b["_bass"], key_pcs) if b["_chroma"].max() > 0 else ("-", [])
        b["bass"] = NAMES[b["_bass"]] if b["_bass"] is not None else None
    # ---- sections: novelty on standardised bar features, snapped to 4-bar phrases --------------------------------------------
    n = len(bars); F = np.array([np.concatenate([v, [b["db"] / 10], np.array(b["bands"]) * 4, [b["onsets"] / 8]]) for v, b in zip(arcv, bars)]) if n else np.zeros((0, 1))
    secs = [(0, n)]
    if n >= 12:
        Z = (F - F.mean(0)) / (F.std(0) + 1e-9); Z /= (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9); SS = Z @ Z.T
        nov = _novelty(SS, 4); thr = nov.mean() + .5 * nov.std(); cand = []
        for i in np.argsort(nov)[::-1]:
            if nov[i] < thr or i < 4 or i > n - 4: continue
            j = int(4 * round(i / 4)) if abs(i - 4 * round(i / 4)) <= 1 else int(i)
            if all(abs(j - c) >= 8 for c in cand): cand.append(j)
        cuts = sorted(cand); secs = [(a, b) for a, b in zip([0] + cuts, cuts + [n]) if b > a]
    means = [F[a:b].mean(0) for a, b in secs]; letters, protos = [], []
    for v in means:
        d = [float(np.dot(v, p) / (np.linalg.norm(v) * np.linalg.norm(p) + 1e-9)) for p in protos]
        if d and max(d) > .97: letters.append(chr(65 + int(np.argmax(d))))
        else: protos.append(v); letters.append(chr(65 + len(protos) - 1))
    dbs = np.array([b["db"] for b in bars]) if bars else np.zeros(1); q1, q2 = np.percentile(dbs, [33, 66]) if n else (0, 0)
    sections = []
    for (a, b), L in zip(secs, letters):
        lv = float(np.mean(dbs[a:b])); sections.append({"bars": [a, b], "letter": L, "level": "low" if lv < q1 else "high" if lv > q2 else "mid", "db": round(lv, 1),
                                                        "chords": " ".join(dict.fromkeys(x["chord"] for x in bars[a:b]))[:80], "onsets_per_bar": round(float(np.mean([x["onsets"] for x in bars[a:b]])), 1)})
    form = form_stats(arcv, dbs)
    for b in bars: b.pop("_chroma"); b.pop("_bass")
    bp = {"file": os.path.abspath(path), "bpm": bpm, "bars": n, "key": f"{NAMES[tonic]} {mode}", "sections": sections, "form": form,
          "chord_changes_per_bar": round(float(np.mean([x["chord"] != y["chord"] for x, y in zip(bars, bars[1:])])) if n > 1 else 0.0, 2),
          "distinct_chords": len({b["chord"] for b in bars}), "bands": {nm: round(float(np.mean([b["bands"][i] for b in bars])), 4) for i, (_, _, nm) in enumerate(BANDS)} if n else {},
          "width": round(float(np.median([b["width"] for b in bars])), 3) if n else 0.0, "per_bar": bars}
    if save:
        try: json.dump(bp, open(path + ".blueprint.json", "w"), ensure_ascii=False)
        except OSError: pass
    return bp

def form_stats(vecs, dbs, same=.985, new=.95):
    """how the music moves: bars between changes, the longest run of identical bars, the share of bars with new material, and
    how far the loudness travels (dB between the quietest and loudest quarter)"""
    V = np.array(vecs); n = len(V)
    if n < 4: return {"bars": n}
    sim1 = np.sum(V[1:] * V[:-1], 1); ch = np.where(sim1 < same)[0] + 1; run = best = 0
    for v in sim1 >= same:
        run = run + 1 if v else 0; best = max(best, run)
    G = V @ V.T; newb = [i for i in range(1, n) if G[i, :i].max() < new]
    return {"bars": n, "change_every_bars": round(float(n / max(1, len(ch))), 1), "longest_same_run_bars": int(best), "new_material_share": round(len(newb) / n, 2),
            "loudness_travel_db": round(float(np.percentile(dbs, 90) - np.percentile(dbs, 10)), 1) if len(dbs) else 0.0}

def _bp(x, bpm=None, cache=False):
    """a blueprint as is, or read from a file (cache: reuse <file>.blueprint.json when it is newer than the file)"""
    if isinstance(x, dict): return x
    j = x + ".blueprint.json"
    if cache and os.path.exists(j) and os.path.getmtime(j) >= os.path.getmtime(x):
        try:
            B = json.load(open(j))
            if bpm is None or abs(B.get("bpm", 0) - bpm) < .5: return B
        except Exception: pass
    return read(x, bpm=bpm, save=cache)

def compare(ours, ref, bpm=None, ref_bpm=None):
    """ours / ref: paths or blueprints -> {"score": 0..1, "ours": summary, "ref": summary, "diff": {...}, "notes": [...]}"""
    A, R = _bp(ours, bpm), _bp(ref, ref_bpm, cache=True); notes = []; diff = {}; sc = []
    def summ(B):
        return {"bpm": B["bpm"], "key": B["key"], "bars": B["bars"], "sections": len(B["sections"]), "form": B["form"], "chord_changes_per_bar": B["chord_changes_per_bar"],
                "distinct_chords": B["distinct_chords"], "bands": B["bands"], "width": B["width"], "letters": "".join(s["letter"] for s in B["sections"])}
    a, r = summ(A), summ(R)
    diff["bpm"] = round(a["bpm"] - r["bpm"], 1)
    if abs(diff["bpm"]) > 1.5: notes.append(f"темп: у нас {a['bpm']}, у эталона {r['bpm']}")
    sc.append(np.exp(-abs(diff["bpm"]) / 6))
    if a["key"] != r["key"]: notes.append(f"тональность: у нас {a['key']}, у эталона {r['key']}")
    sc.append(1.0 if a["key"] == r["key"] else .5)
    bd = {k: round(10 * np.log10((A["bands"].get(k, 0) + 1e-6) / (R["bands"].get(k, 0) + 1e-6)), 1) for k in R["bands"]
          if max(A["bands"].get(k, 0), R["bands"].get(k, 0)) >= .003}; diff["bands_db"] = bd                 # bands that carry something
    hz = {nm: f"{lo}-{hi} Гц" for lo, hi, nm in BANDS}
    for k, v in bd.items():
        if abs(v) >= 2.0: notes.append(f"в {hz[k]} ({k}) у нас на {abs(v)} дБ {'больше' if v > 0 else 'меньше'}, чем у эталона")
    sc.append(np.exp(-np.mean(np.abs(list(bd.values()))) / 4) if bd else 1.0)
    fa, fr_ = A["form"], R["form"]
    if fa.get("change_every_bars") and fr_.get("change_every_bars"):
        diff["change_every_bars"] = [fa["change_every_bars"], fr_["change_every_bars"]]
        if fa["change_every_bars"] > 1.6 * fr_["change_every_bars"]: notes.append(f"эталон что-то меняет каждые {fr_['change_every_bars']} такта, у нас каждые {fa['change_every_bars']}: добавь мелких событий (заполнения, смена рисунка хэтов, фильтр, ответ другим слоем)")
        if fa["longest_same_run_bars"] > max(8, 1.5 * fr_["longest_same_run_bars"]): notes.append(f"у нас {fa['longest_same_run_bars']} тактов подряд одно и то же (у эталона максимум {fr_['longest_same_run_bars']})")
        if fa["new_material_share"] < .6 * fr_["new_material_share"]: notes.append(f"нового материала у нас {fa['new_material_share']:.0%} тактов, у эталона {fr_['new_material_share']:.0%}")
        if fa["loudness_travel_db"] < fr_["loudness_travel_db"] - 3: notes.append(f"громкость у эталона ходит на {fr_['loudness_travel_db']} дБ (ямы и подъёмы), у нас на {fa['loudness_travel_db']}")
        sc.append(np.exp(-abs(np.log((fa["change_every_bars"] + 1) / (fr_["change_every_bars"] + 1)))))
    ra, rr = a["bars"] / max(1, a["sections"]), r["bars"] / max(1, r["sections"])
    if abs(a["sections"] - r["sections"]) >= 2: notes.append(f"разделов у нас {a['sections']} ({a['letters']}), у эталона {r['sections']} ({r['letters']}), в среднем по {rr:.0f} тактов")
    sc.append(np.exp(-abs(np.log((ra + 1) / (rr + 1)))))
    if a["chord_changes_per_bar"] < .5 * r["chord_changes_per_bar"]: notes.append(f"аккорды у эталона меняются в {r['chord_changes_per_bar']:.0%} тактов, у нас в {a['chord_changes_per_bar']:.0%}")
    if abs(a["width"] - r["width"]) > .15: notes.append(f"ширина (side/mid выше 400 Гц): у нас {a['width']}, у эталона {r['width']}")
    da = [s["onsets_per_bar"] for s in A["sections"] if s["level"] == "high"]; dr = [s["onsets_per_bar"] for s in R["sections"] if s["level"] == "high"]
    if da and dr and np.mean(da) < .6 * np.mean(dr): notes.append(f"в громких частях у эталона {np.mean(dr):.1f} ударов на такт, у нас {np.mean(da):.1f}")
    return {"score": round(float(np.mean(sc)), 2), "ours": a, "ref": r, "diff": diff, "notes": notes}

def _audio(path):
    """(n, 2) float32 and its rate from any file ffmpeg reads (wav / mp3 / flac ...), or an array as is (44.1 kHz)"""
    if isinstance(path, np.ndarray): return path, 44100
    if path.lower().endswith(".wav"):
        import soundfile as sf
        return sf.read(path, dtype="float32", always_2d=True)
    from .checks import _read
    return _read(path)

def _ltas(path):
    from scipy.signal import welch
    x, s = _audio(path); x = x if x.ndim == 2 else x[:, None]
    f, P = welch(x.mean(1), fs=s, nperseg=8192); out = []
    for fc in OCT:
        sel = (f >= fc / np.sqrt(2)) & (f < fc * np.sqrt(2)); out.append(float(P[sel].mean()) if sel.any() else 1e-20)
    out = np.array(out); return 10 * np.log10(out / out.sum() + 1e-20)

def match_eq(ours, ref, amount=.5, max_db=4.0):
    """octave bands, ref minus ours (level-free), smoothed over neighbours and limited -> [(fc, gain_db)] (only |gain| >= .5 dB)"""
    d = _ltas(ref) - _ltas(ours); d = np.convolve(np.pad(d, 1, "edge"), [.25, .5, .25], "valid")
    g = np.clip(d * float(amount), -max_db, max_db); return [(fc, round(float(v), 1)) for fc, v in zip(OCT, g) if abs(v) >= .5]

def eq_plugins(curve):
    """match_eq() -> pedalboard filters for premaster(pre_eq=...): an octave-wide peak per band"""
    from pedalboard import PeakFilter
    return [PeakFilter(cutoff_frequency_hz=float(fc), gain_db=float(g), q=1.41) for fc, g in curve]

def notes_for_summary(cmp):
    return [f"эталон: похожесть {cmp['score']:.0%}"] + cmp["notes"]

def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv); bpm = None
    if "--bpm" in a: i = a.index("--bpm"); bpm = float(a[i + 1]); del a[i:i + 2]
    if not a: print("usage: python -m autodj.compose.blueprint REF.wav [OURS.mp3] [--bpm 124]"); return 2
    B = read(a[0], bpm=bpm)
    print(json.dumps({k: v for k, v in B.items() if k != "per_bar"}, ensure_ascii=False, indent=1))
    if len(a) > 1:
        c = compare(a[1], B); print(json.dumps(c, ensure_ascii=False, indent=1))
        print("EQ к эталону:", match_eq(a[1], a[0]))
    return 0

if __name__ == "__main__":
    sys.exit(main())
