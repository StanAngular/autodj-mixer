"""Pattern knowledge from the Lakh MIDI 'clean_midi' set (Raffel 2016, CC BY 4.0), dance/electronic artists only
(disco, house, eurodance, trance/techno, synth-pop, big beat). Built once:
  python3 -m autodj.compose.lakh build   ->  $AUTODJ_ASSETS/lakh/patterns.json
Per style group it keeps what real arrangements did: bass rhythms on the 16th grid with their scale degrees, 4-bar
chord progressions as roman numerals in the song's key, drum patterns per voice, tempo range and when parts enter.
Use: lib = Lakh("house"); lib.chords(lib.progression(rng, "minor"), key), lib.bass_notes(lib.bass(rng), key),
     lib.drums(rng), lib.form(), lib.tempo().
NOTE: these songs are mostly 1975-2010; use them for harmony/bass/arrangement knowledge, not for 'sound'."""
import collections, glob, json, os, sys
import numpy as np
from .assets import ASSETS

ROOT = os.path.join(ASSETS, "lakh")
GROUPS = {"disco": ["Chic", "Donna Summer", "Bee Gees", "Gloria Gaynor", "Sylvester", "Giorgio Moroder", "Jamiroquai"],
          "house": ["Robin S", "Crystal Waters", "Inner City", "Black Box", "Daft Punk", "Technotronic", "C+C Music Factory", "Snap", "Faithless", "Moby"],
          "eurodance": ["2 Unlimited", "Corona", "Culture Beat", "Haddaway", "La Bouche", "Dr. Alban", "Real McCoy", "Ice MC", "Masterboy", "Mr. President",
                        "E-Type", "DJ BoBo", "Whigfield", "Vengaboys", "2 Brothers on the 4th Floor", "N-Trance", "Eiffel 65"],
          "trance_techno": ["Darude", "Energy 52", "Robert Miles", "Scooter", "SASH!", "Orbital", "Jean Michel Jarre", "Kraftwerk", "Vangelis"],
          "synthpop": ["Depeche Mode", "New Order", "Pet Shop Boys", "Erasure", "Yazoo", "Soft Cell", "Orchestral Manoeuvres in the Dark", "Ultravox", "Visage",
                       "a-ha", "Eurythmics", "Duran Duran", "Tears for Fears", "The Cure", "Kylie Minogue", "Madonna", "Modern Talking", "Bad Boys Blue", "Army of Lovers"],
          "bigbeat": ["Fatboy Slim", "Bomfunk MC's", "Lou Bega"]}
KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]); KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
QUAL = {"": [0, 4, 7], "m": [0, 3, 7], "7": [0, 4, 7, 10], "m7": [0, 3, 7, 10], "maj7": [0, 4, 7, 11], "dim": [0, 3, 6], "sus4": [0, 5, 7]}
ROMAN = ["I", "bII", "II", "bIII", "III", "IV", "#IV", "V", "bVI", "VI", "bVII", "VII"]
DRUM = {"kick": (35, 36), "snare": (38, 40), "clap": (39,), "hh": (42, 44), "oh": (46,), "ride": (51, 59), "tom": (41, 43, 45, 47, 48, 50), "perc": (37, 54, 56, 69, 70, 75)}

def key_of(pm):
    h = np.zeros(12)
    for ins in pm.instruments:
        if ins.is_drum: continue
        for n in ins.notes: h[n.pitch % 12] += n.end - n.start
    best = max(((np.corrcoef(np.roll(KS_MAJ, k), h)[0, 1], k, "major") for k in range(12)), key=lambda x: x[0])
    bm = max(((np.corrcoef(np.roll(KS_MIN, k), h)[0, 1], k, "minor") for k in range(12)), key=lambda x: x[0])
    return (bm if bm[0] > best[0] else best)[1:]

def chord_of(hist):
    if hist.sum() <= 0: return None
    best, bs = None, -1
    for root in range(12):
        for q, iv in QUAL.items():
            s = sum(hist[(root + i) % 12] for i in iv) - .5 * sum(hist[p] for p in range(12) if (p - root) % 12 not in iv) - (.15 * len(iv))
            if s > bs: best, bs = (root, q), s
    return best

def analyse(path):
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(path); db = pm.get_downbeats(); bt = pm.get_beats()
    if len(db) < 16 or len(bt) < 64: return None
    tempo = float(60 / np.median(np.diff(bt))); tonic, mode = key_of(pm)
    s16 = np.interp(np.arange(0, len(bt) - 1, .25), np.arange(len(bt)), bt)            # 16th grid following the beats
    step_of = lambda t: int(np.searchsorted(s16, t - (s16[1] - s16[0]) / 2))
    nb = len(s16) // 16
    melodic = [i for i in pm.instruments if not i.is_drum and i.notes]
    if not melodic: return None
    bass = [i for i in melodic if 32 <= i.program <= 39] or [min(melodic, key=lambda i: np.median([n.pitch for n in i.notes]))]
    bass = bass[0] if np.median([n.pitch for n in bass[0].notes]) < 60 else None
    out = {"tempo": round(tempo, 1), "tonic": int(tonic), "mode": mode, "bars": nb, "bass": [], "chords": [], "drums": [], "active": []}
    for b in range(nb):
        a, e = b * 16, (b + 1) * 16
        if bass is not None:
            hits = sorted((step_of(n.start) - a, n.pitch) for n in bass.notes if a <= step_of(n.start) < e)
            out["bass"].append([[s, (p - tonic) % 12, p] for s, p in hits])
        h = np.zeros(12); t0, t1 = s16[min(a, len(s16) - 1)], s16[min(e, len(s16) - 1)]
        for ins in melodic:
            if ins is bass: continue
            for n in ins.notes:
                ov = min(n.end, t1) - max(n.start, t0)
                if ov > 0: h[n.pitch % 12] += ov
        c = chord_of(h); out["chords"].append(None if c is None else [ROMAN[(c[0] - tonic) % 12], c[1]])
        dr = {}
        for ins in pm.instruments:
            if not ins.is_drum: continue
            for n in ins.notes:
                st = step_of(n.start) - a
                if 0 <= st < 16:
                    for k, ps in DRUM.items():
                        if n.pitch in ps: dr.setdefault(k, set()).add(st)
        out["drums"].append({k: sorted(v) for k, v in dr.items()})
        out["active"].append(sorted({("bass" if ins is bass else "drums" if ins.is_drum else ("lead" if np.median([n.pitch for n in ins.notes]) > 72 else "keys"))
                                     for ins in pm.instruments for n in ins.notes[:: max(1, len(ins.notes) // 400)] if t0 <= n.start < t1}))
    return out

class _Timeout(Exception): pass

def _alarm(*_): raise _Timeout()

def build(per_file_s=8):
    """resumable and hang-proof: each file gets a hard time limit (SIGALRM), every group is saved as soon as it is done,
    and a progress line goes to stdout every 25 files (the heartbeat a watchdog can follow)."""
    import signal, time
    signal.signal(signal.SIGALRM, _alarm)
    part = os.path.join(ROOT, "patterns.partial.json"); lib = json.load(open(part)) if os.path.exists(part) else {}
    for g, artists in GROUPS.items():
        if g in lib: print(g, "already done", flush=True); continue
        songs = []; files = [f for a in artists for f in glob.glob(os.path.join(ROOT, "clean_midi", a, "*.mid"))]; t0 = time.time(); skipped = 0
        for k, f in enumerate(files):
            signal.alarm(per_file_s)
            try:
                s = analyse(f)
                if s: songs.append(s)
            except _Timeout: skipped += 1
            except Exception: pass
            finally: signal.alarm(0)
            if k % 25 == 0: print(f"  {g}: {k}/{len(files)} files, {len(songs)} ok, {skipped} timed out, {time.time() - t0:.0f}s", flush=True)
        bpat, bdeg, prog, drums, forms, tempos = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter(), [], []
        for s in songs:
            tempos.append(s["tempo"])
            for bar in s["bass"]:
                if bar: bpat["".join("x" if any(h[0] == i for h in bar) else "." for i in range(16))] += 1
            for i in range(0, len(s["bass"]) - 4, 4):
                seq = tuple(tuple((h[0], h[1]) for h in bar[:8]) for bar in s["bass"][i:i + 4])
                if all(seq): bdeg[json.dumps(seq)] += 1
            ch = s["chords"]
            for i in range(0, len(ch) - 4, 4):
                q = ch[i:i + 4]
                if all(q) and len({x[0] for x in q}) > 1: prog[(s["mode"], tuple(f"{r}{qq}" for r, qq in q))] += 1
            for d in s["drums"]:
                if "kick" in d: drums[json.dumps({k: d[k] for k in ("kick", "snare", "clap", "hh", "oh") if k in d}, sort_keys=True)] += 1
            act = s["active"]; first = lambda k: next((i for i, x in enumerate(act) if k in x), None)
            forms.append({k: first(k) for k in ("drums", "bass", "keys", "lead")})
        lib[g] = {"songs": len(songs), "tempo": [round(float(np.percentile(tempos, q)), 1) for q in (10, 50, 90)] if tempos else None,
                  "bass_rhythms": bpat.most_common(40), "bass_lines": [[json.loads(k), v] for k, v in bdeg.most_common(60)],
                  "progressions": [[m, list(p), v] for (m, p), v in prog.most_common(60)], "drums": [[json.loads(k), v] for k, v in drums.most_common(40)],
                  "entry_bar_median": {k: (int(np.median([f[k] for f in forms if f[k] is not None])) if any(f[k] is not None for f in forms) else None) for k in ("drums", "bass", "keys", "lead")}}
        print(g, lib[g]["songs"], "songs", lib[g]["tempo"], flush=True)
        json.dump(lib, open(part, "w"))
    json.dump(lib, open(os.path.join(ROOT, "patterns.json"), "w")); print("ALL DONE", flush=True)

_RN = sorted(((r, i) for i, r in enumerate(ROMAN)), key=lambda x: -len(x[0]))
_Q = sorted(QUAL, key=len, reverse=True)

def parse_roman(sym):
    """'bVImaj7' -> (8, 'maj7'): root in semitones above the tonic + chord quality. Raises ValueError on anything else."""
    for r, i in _RN:
        if sym.startswith(r):
            rest = sym[len(r):]
            if rest in QUAL: return i, rest
    raise ValueError(f"not a Lakh chord symbol: {sym!r}")

def drums_aligned(d):
    """a bar whose kick sits only on odd 16ths is a pickup/offset artefact of the grid (e.g. kick on 1,5,9,13), not a groove"""
    return any(s % 2 == 0 for s in d.get("kick", ()))

def plausible_tempo(t, lo=80.0, hi=150.0):
    """beat tracking in MIDI files sometimes doubles or halves the tempo (big beat at 199): fold into a dance range"""
    while t > hi: t /= 2
    while t < lo: t *= 2
    return round(t, 1)

class Lakh:
    """what real dance/electronic arrangements did, per style group. Everything is drawn with the score's rng,
    weighted by how often it occurred, from the top-k entries (k=12) so a seed gives a different but common choice."""
    def __init__(self, group, path=None):
        path = path or os.path.join(ROOT, "patterns.json")
        if not os.path.exists(path): raise FileNotFoundError(f"{path} missing: run python3 -m autodj.compose.lakh build")
        lib = json.load(open(path))
        if group not in lib: raise KeyError(f"unknown Lakh group {group!r}, have: {sorted(lib)}")
        self.group, self.g = group, lib[group]
    @staticmethod
    def groups(path=None):
        return sorted(json.load(open(path or os.path.join(ROOT, "patterns.json"))))
    def _pick(self, items, rng, k=12):
        items = items[:k]
        if not items: raise ValueError(f"Lakh group {self.group!r} has no entries for this")
        w = np.array([it[-1] for it in items], float); return items[int(rng.choice(len(items), p=w / w.sum()))]
    def tempo(self):
        return plausible_tempo(self.g["tempo"][1])
    def bass(self, rng):
        """a real 4-bar bass line: [[(step, semitones-from-tonic), ...] x4]"""
        return [[tuple(h) for h in bar] for bar in self._pick(self.g["bass_lines"], rng)[0]]
    def bass_notes(self, line, key, lo=28, hi=52, length=2):
        """bass line -> [(bar, step, midi, len16)] in `key`, inside [lo, hi]. Out-of-key notes (the source song may
        have been major, the score minor) snap down to the nearest scale tone, in-key notes stay as they are.
        Each note lasts until the next onset, at most `length` 16ths."""
        out = []
        for b, bar in enumerate(line):
            ons = sorted({st for st, _ in bar}) + [16]; seen = set()
            for st, deg in bar:                                             # hits come sorted by (step, real pitch)
                if st in seen: continue                                     # double-stop: keep the lowest note only
                seen.add(st); m = key.snap(lo + (key.tonic + deg - lo) % 12)
                while m < lo: m += 12
                while m > hi: m -= 12
                out.append((b, st, m, max(1, min(length, ons[ons.index(st) + 1] - st))))
        return out
    def bass_rhythm(self, rng):
        return [i for i, c in enumerate(self._pick(self.g["bass_rhythms"], rng)[0]) if c == "x"]
    def progression(self, rng, mode=None):
        items = [p for p in self.g["progressions"] if mode is None or p[0] == mode] or self.g["progressions"]
        return self._pick(items, rng)[1]
    def chords(self, prog, key):
        """roman progression -> pitch-class chords (root first) in `key`, ready for harmony.voicing / lead_chords"""
        out = []
        for sym in prog:
            r, q = parse_roman(sym); out.append([(key.tonic + r + i) % 12 for i in QUAL[q]])
        return out
    def drums(self, rng):
        return self._pick([d for d in self.g["drums"] if drums_aligned(d[0])], rng)[0]
    def form(self):
        return self.g["entry_bar_median"]

if __name__ == "__main__" and sys.argv[1:2] == ["build"]:
    build()
