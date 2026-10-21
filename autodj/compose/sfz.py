"""Headless SFZ player (P108, Стас: «живые мультисэмплы вместо пресетов Vital»). Plays real multisampled instruments
(jRhodes3d, Osiris piano, Karoryfer basses ... in ~/samples/sfz) without sfizz or a GUI.

Supported (what the libraries in use actually need): <control>/<global>/<master>/<group>/<region> inheritance,
#include and #define, default_path, note names (C4 = 60), key/lokey/hikey/pitch_keycenter/pitch_keytrack/
transpose/tune, lovel/hivel + xfin/xfout velocity crossfades, amp_veltrack, volume, amplitude, amplitude_ccN,
locc/hicc conditions against cc defaults (set_ccN, overridable), seq_length/seq_position round robin, lorand/hirand,
offset (+offset_ccN), ampeg_attack/ampeg_release (+ ..._onccN), loop_mode=one_shot, pan, trigger=release (key-off
noise), Skipped on purpose: filters, LFOs, curves (a
`_curveccN=2` flips its cc), sustain pedal (pedal is up), group/off_by (mono modes are switched off by cc)."""
import os, re, glob, numpy as np, soundfile as sf
from fractions import Fraction
from scipy.signal import resample_poly
SR = 44100
SFZ_ROOT = os.environ.get("AUTODJ_SFZ", "/home/cclaw/samples/sfz")
NOTE = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
LIBS = {"rhodes": "jlearman.jRhodes3d-master/jRhodes3d-st.sfz",                          # 1977 Rhodes Mark I Stage 73
        "piano": "Osiris_Piano-main/Programs/02-warm.sfz", "piano_natural": "Osiris_Piano-main/Programs/01-natural.sfz",
        "bass": "karoryfer.big-little-bass-main/Programs/02-big_little_soft_pluck.sfz",
        "bass_pluck": "karoryfer.big-little-bass-main/Programs/01-big_little_pluck.sfz"}

def note_num(v):
    v = str(v).strip()
    if re.fullmatch(r"-?\d+", v): return int(v)
    m = re.fullmatch(r"([a-gA-G])([#b]?)(-?\d+)", v)
    if not m: raise ValueError(f"bad note {v!r}")
    acc = {"#": 1, "b": -1, "": 0}[m.group(2)]
    return NOTE[m.group(1).lower()] + acc + 12 * (int(m.group(3)) + 1)

def _read(path, defines, seen=0):
    """text of an .sfz with #include expanded (relative to the including file) and #define substituted"""
    if seen > 20: raise RuntimeError("#include too deep")
    txt = open(path, encoding="utf-8", errors="replace").read()
    txt = re.sub(r"/\*.*?\*/", " ", txt, flags=re.S); txt = re.sub(r"//[^\n]*", " ", txt)
    for name, val in re.findall(r"#define\s+(\$\w+)\s+(\S+)", txt): defines[name] = val
    txt = re.sub(r"#define\s+\$\w+\s+\S+", " ", txt)
    def inc(m):
        p = os.path.join(os.path.dirname(path), m.group(1).replace("\\", "/"))
        return _read(p, defines, seen + 1) if os.path.exists(p) else " "
    txt = re.sub(r'#include\s+"([^"]+)"', inc, txt)
    for name in sorted(defines, key=len, reverse=True): txt = txt.replace(name, defines[name])
    return txt

def parse(path):
    """-> (control, regions): each region is a dict of opcodes with global/master/group values inherited"""
    txt = _read(path, {}); control, levels, regions = {}, {"global": {}, "master": {}, "group": {}}, []
    cur = None
    for tok in re.split(r"(<\w+>)", txt):
        h = re.fullmatch(r"<(\w+)>", tok)
        if h:
            cur = h.group(1)
            if cur == "global": levels = {"global": {}, "master": {}, "group": {}}
            elif cur == "master": levels["master"] = {}; levels["group"] = {}
            elif cur == "group": levels["group"] = {}
            elif cur == "region": regions.append({**levels["global"], **levels["master"], **levels["group"]})
            continue
        if cur is None: continue
        # opcode values may contain spaces (sample paths): split on the next "name=" token
        for k, v in re.findall(r"(\w+)=(.*?)(?=\s+\w+=|\s*$)", tok.strip(), flags=re.S):
            v = v.strip()
            if cur == "control": control[k] = v
            elif cur == "region": regions[-1][k] = v
            elif cur in levels: levels[cur][k] = v
    return control, regions

class SFZ:
    """SFZ(name_or_path, cc={70: 127}) -> .render(events, total_s) with events (t, midi, vel 1-127, dur_s)"""
    def __init__(self, name, cc=None, sr=SR, tune=True):
        self.path = os.path.join(SFZ_ROOT, LIBS[name]) if name in LIBS else name
        self.control, regs = parse(self.path); self.sr = sr; self.dir = os.path.dirname(self.path)
        self.cc = {int(k[6:]): float(v) for k, v in self.control.items() if re.fullmatch(r"set_cc\d+", k)}
        self.cc.update({int(k[8:]): float(v) * 127 for k, v in self.control.items() if re.fullmatch(r"set_hdcc\d+", k)})
        self.cc.update(cc or {})
        base = self.control.get("default_path", "").replace("\\", "/")
        self.regions = []
        for r in regs:
            if "sample" not in r or r["sample"].startswith("*"): continue
            if not self._cc_ok(r): continue
            r = dict(r); r["_file"] = os.path.normpath(os.path.join(self.dir, base, r["sample"].replace("\\", "/")))
            if not os.path.exists(r["_file"]): continue
            lo = note_num(r.get("lokey", r.get("key", 0))); hi = note_num(r.get("hikey", r.get("key", 127)))
            r["_lo"], r["_hi"] = lo, hi; r["_kc"] = note_num(r.get("pitch_keycenter", r.get("key", lo)))
            self.regions.append(r)
        if not self.regions: raise RuntimeError(f"no playable regions in {self.path}")
        self.seq = {}; self.cache = {}; self.rng = np.random.default_rng(0); self.oct = 0; self.tune = tune
        if tune:                                                            # bass libraries sound an octave below the key
            from .tuning import Cache, pitch_offset                          # (written like bass notation): measure once
            self._tc = Cache(os.path.join(SFZ_ROOT, "_tuning.json"))
            def measure():
                ks = sorted({r["_kc"] for r in self.regions}); probe = [ks[len(ks) // 3], ks[len(ks) // 2], ks[2 * len(ks) // 3]]
                offs = [pitch_offset(self._render([(0.05, k, 90, 1.2)], 1.6), k) for k in probe]
                offs = [o for o in offs if o is not None]
                return int(12 * round(np.median(offs) / 12)) if offs else 0
            self.oct = self._tc.get("oct:" + os.path.relpath(self.path, SFZ_ROOT), measure)

    def _ccval(self, n):
        return self.cc.get(int(n), 0.0)
    def _cc_ok(self, r):
        for k, v in r.items():
            m = re.fullmatch(r"(lo|hi)cc(\d+)", k)
            if m:
                c = self._ccval(m.group(2))
                if (m.group(1) == "lo" and c < float(v)) or (m.group(1) == "hi" and c > float(v)): return False
        return True
    def _cc_sum(self, r, name):
        """value of `name` plus every name_ccN / name_onccN scaled by its cc (curve 2 = inverted)"""
        tot = 0.0
        for k, v in r.items():
            m = re.fullmatch(name + r"_(?:on)?cc(\d+)", k)
            if m:
                x = self._ccval(m.group(1)) / 127
                if r.get(f"{name}_curvecc{m.group(1)}") == "2": x = 1 - x
                tot += float(v) * x
        return tot
    def _load(self, f):
        if f not in self.cache:
            a, s = sf.read(f, dtype="float32", always_2d=True)
            if s != self.sr: a = resample_poly(a, self.sr, s, axis=0).astype(np.float32)
            self.cache[f] = np.repeat(a, 2, 1) if a.shape[1] == 1 else a[:, :2]
        return self.cache[f]

    def pick(self, midi, vel, trigger="attack"):
        """regions sounding for this note (all matching layers/mics, one round-robin step per seq group)"""
        out = []; rnd = self.rng.random()
        for r in self.regions:
            if r.get("trigger", "attack") != trigger or not r["_lo"] <= midi <= r["_hi"]: continue
            if not int(r.get("lovel", 1)) <= vel <= int(r.get("hivel", 127)): continue
            if not float(r.get("lorand", 0)) <= rnd < float(r.get("hirand", 1.0001)): continue
            out.append(r)
        sl = [r for r in out if "seq_length" in r]
        if sl:
            key = (midi, int(sl[0]["seq_length"])); pos = self.seq.get(key, 0) % int(sl[0]["seq_length"]) + 1; self.seq[key] = pos
            out = [r for r in out if "seq_length" not in r or int(r.get("seq_position", 1)) == pos]
        return out

    def _gain(self, r, vel):
        g = 10 ** ((float(r.get("volume", 0)) + self._cc_sum(r, "volume")) / 20) * float(r.get("amplitude", 100)) / 100
        for k, v in r.items():
            m = re.fullmatch(r"amplitude_(?:on)?cc(\d+)", k)
            if m: g *= float(v) / 100 * self._ccval(m.group(1)) / 127
        vt = float(r.get("amp_veltrack", 100)) / 100; x = vel / 127
        g *= (1 - vt) + vt * x * x                                          # SFZ default curve: gain ~ (vel/127)^2
        lo, hi = r.get("xfin_lovel"), r.get("xfin_hivel")
        if lo and hi and vel < int(hi): g *= np.sqrt(np.clip((vel - int(lo)) / max(1, int(hi) - int(lo)), 0, 1))
        lo, hi = r.get("xfout_lovel"), r.get("xfout_hivel")
        if lo and hi and vel > int(lo): g *= np.sqrt(np.clip((int(hi) - vel) / max(1, int(hi) - int(lo)), 0, 1))
        return g

    def _cents(self, r):
        """measured detune of this sample at its key centre (some recordings sit 20-35 c off), cached per file"""
        if not self.tune: return 0.0
        from .tuning import cents_off
        f = r["_file"]; key = "c:" + os.path.relpath(f, SFZ_ROOT)
        return self._tc.get(key, lambda: round(cents_off(self._load(f), r["_kc"] + self.oct, start=.08, dur=.8), 1))
    def voice(self, r, midi, vel, dur):
        a = self._load(r["_file"])
        st = (midi - r["_kc"]) * float(r.get("pitch_keytrack", 100)) / 100 + float(r.get("transpose", 0)) + float(r.get("tune", 0)) / 100
        st -= self._cents(r) / 100
        off = int(float(r.get("offset", 0)) + self._cc_sum(r, "offset"))
        rel = max(.005, float(r.get("ampeg_release", .03)) + self._cc_sum(r, "ampeg_release"))
        one = r.get("loop_mode") == "one_shot"
        need = int(((len(a) / self.sr) if one else dur + rel) * self.sr * 2 ** (st / 12)) + 64
        src = a[off: off + need]
        if abs(st) > 1e-3:
            fr = Fraction(2 ** (-st / 12)).limit_denominator(400)                # polyphase: accurate to < 0.5 cent
            y = resample_poly(src, fr.numerator, fr.denominator, axis=0).astype(np.float32)
        else: y = src.copy()
        att = int(max(.001, float(r.get("ampeg_attack", 0.001))) * self.sr); y[:att] *= np.linspace(0, 1, min(att, len(y)))[:, None]
        if not one:
            k = int(dur * self.sr); n = int(rel * self.sr)
            if len(y) > k:
                e = np.exp(-np.arange(min(n * 4, len(y) - k)) / max(1, n) * 3.0)[:, None]   # exponential release
                y = y[:k + len(e)]; y[k:] *= e
        pan = float(r.get("pan", 0)) / 100 + self._cc_sum(r, "pan") / 100
        if pan: y = y * np.array([np.sqrt(1 - min(1, max(-1, pan))), np.sqrt(1 + min(1, max(-1, pan)))], np.float32) 
        return y * self._gain(r, vel)

    def render(self, events, total_s, release=None):
        """concert pitch: the measured octave of the library is undone, then every sample's own detune"""
        return self._render([(t, m - self.oct, v, d) for t, m, v, d in events], total_s)
    def _render(self, events, total_s):
        n = int(total_s * self.sr); out = np.zeros((n + self.sr * 4, 2), np.float32)
        for t, m, v, d in sorted(events, key=lambda e: e[0]):
            i = int(round(t * self.sr)); m = int(m); v = int(max(1, min(127, v)))
            for r in self.pick(m, v):
                y = self.voice(r, m, v, d); k = min(len(y), len(out) - i)
                if k > 0 and i >= 0: out[i:i + k] += y[:k]
            for r in self.pick(m, max(1, v // 2), "release"):                  # key-off noise (mechanics)
                y = self.voice(r, m, v, .5); j = i + int(d * self.sr); k = min(len(y), len(out) - j)
                if k > 0: out[j:j + k] += y[:k]
        return out[:n]

def available():
    return {k: os.path.exists(os.path.join(SFZ_ROOT, v)) for k, v in LIBS.items()}

def oneshot(wav, keycenter=None, release=.12, lokey=0, hikey=127, cache_dir=None):
    """any one-shot (W.A. bass/pluck/lead shots ...) as a playable SFZ instrument: one region, pitch measured once
    (pyin) if keycenter is None, then the usual per-sample cents calibration of SFZ()."""
    cache_dir = cache_dir or os.path.join(SFZ_ROOT, "_oneshots"); os.makedirs(cache_dir, exist_ok=True)
    name = re.sub(r"\W+", "_", os.path.splitext(os.path.basename(wav))[0]); path = os.path.join(cache_dir, name + ".sfz")
    if keycenter is None:
        import json, librosa
        kc_file = os.path.join(cache_dir, "_keycenters.json"); kcs = json.load(open(kc_file)) if os.path.exists(kc_file) else {}
        if wav not in kcs:
            y, s = sf.read(wav, dtype="float32", always_2d=True); y = librosa.resample(y.mean(1)[:int(s * 1.2)], orig_sr=s, target_sr=22050)
            f0, v, _ = librosa.pyin(y, fmin=30, fmax=1500, sr=22050, frame_length=4096)
            kcs[wav] = int(round(float(librosa.hz_to_midi(np.nanmedian(f0[v]))))) if np.any(v) else 60
            json.dump(kcs, open(kc_file, "w"), indent=0)
        keycenter = kcs[wav]
    open(path, "w").write(f"<region> sample={wav} lokey={lokey} hikey={hikey} pitch_keycenter={keycenter} ampeg_release={release}\n")
    return SFZ(path)
