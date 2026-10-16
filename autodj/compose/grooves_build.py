"""Build the groove library from the Groove MIDI Dataset (Magenta, CC BY 4.0: Gillick et al. 2019, 13.6 h of
professional drummers on a Roland TD-11, played to a click). Run once:
  python3 -m autodj.compose.grooves_build  ->  $AUTODJ_ASSETS/grooves/grooves.json
For every 4/4 performance: notes -> 16th grid step + micro-offset (fraction of a 16th) + velocity, per drum class.
The drummer's constant latency is removed per file (median offset on quarter notes)."""
import csv, json, os, collections
import numpy as np, mido
from .assets import ASSETS

ROOT = os.path.join(ASSETS, "grooves", "groove")
CLASS = {36: "kick", 38: "snare", 40: "snare", 37: "rim", 42: "hh", 22: "hh", 44: "hh", 46: "oh", 26: "oh",
         43: "tom", 58: "tom", 47: "tom", 45: "tom", 50: "tom", 48: "tom", 49: "crash", 55: "crash", 57: "crash", 52: "crash",
         51: "ride", 59: "ride", 53: "ride"}

def notes(path):
    mf = mido.MidiFile(path); tpb = mf.ticks_per_beat; t = 0; out = []
    for msg in mido.merge_tracks(mf.tracks):
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.note in CLASS: out.append((t / tpb * 4, CLASS[msg.note], msg.velocity / 127))
    return out                                        # (position in 16ths, class, vel)

def bars_of(ns):
    pos = np.array([p for p, _, _ in ns]); st = np.round(pos)
    q = (st % 4 == 0); lat = np.median((pos - st)[q]) if q.any() else 0.0
    bars = collections.defaultdict(lambda: collections.defaultdict(list))
    for (p, c, v) in ns:
        s = int(round(p - lat)); off = float(p - lat - s)
        bars[s // 16][c].append([s % 16, round(v, 3), round(off, 3)])
    return [dict(b) for _, b in sorted(bars.items())]

def main():
    rows = [r for r in csv.DictReader(open(os.path.join(ROOT, "info.csv"))) if r["time_signature"] == "4-4"]
    lib = {}
    for r in rows:
        style = r["style"].split("/")[0]; kind = "fills" if r["beat_type"] == "fill" else "bars"
        bars = bars_of(notes(os.path.join(ROOT, r["midi_filename"])))
        bars = [b for b in bars if sum(len(v) for v in b.values()) >= 4]
        d = lib.setdefault(style, {"bars": [], "fills": [], "phrases": []}); d[kind] += bars
        if kind == "bars" and len(bars) >= 4: d["phrases"].append(bars[:8])
    for style, d in lib.items():                     # micro-timing / velocity template per class x step
        acc = collections.defaultdict(list)
        for b in d["bars"]:
            for c, hits in b.items():
                for s, v, o in hits: acc[(c, s)].append((o, v))
        n_bars = max(1, len(d["bars"]))
        d["template"] = {f"{c}:{s}": [round(float(np.mean([o for o, _ in x])), 3), round(float(np.std([o for o, _ in x])), 3),
                                      round(float(np.mean([v for _, v in x])), 3), round(float(np.std([v for _, v in x])), 3), round(len(x) / n_bars, 3)]
                         for (c, s), x in acc.items() if len(x) >= 3}
        d["bars"] = d["bars"][:600]; d["fills"] = d["fills"][:300]; d["phrases"] = d["phrases"][:80]
    out = os.path.join(ASSETS, "grooves", "grooves.json"); json.dump(lib, open(out, "w"))
    print(out, {s: (len(d["bars"]), len(d["fills"]), len(d["phrases"])) for s, d in lib.items()})

if __name__ == "__main__":
    main()
