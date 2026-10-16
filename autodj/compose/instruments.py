"""Sound sources: Vital presets, VSCO-2 sampler, drum sample pickers."""
import glob, json, os, re
import numpy as np
from .assets import WA, TDM, VITAL_PRESETS, VITAL_VST3, VSCO
from .core import SR, load_sample, pb

def wa(rel, max_s=None):
    """W.A. Production sample, e.g. wa('Kicks/WATE_Kick_03.wav', .3)"""
    return load_sample(os.path.join(WA, rel), max_s)

def tdm(machine_dir, i=0, max_s=None):
    """drum machine hit, e.g. tdm('LinnDrum/linndrum-sd', 0, .3)"""
    fs = sorted(glob.glob(os.path.join(TDM, machine_dir, "*.wav")))
    return load_sample(fs[i % len(fs)], max_s)

def vital_find(*words):
    return [f for f in glob.glob(f"{VITAL_PRESETS}/**/*.vital", recursive=True) if all(w.lower() in f.lower() for w in words)]

class Vital:
    """Vital VST3 with whole .vital presets swapped into its JUCE state."""
    def __init__(self):
        from pedalboard import load_plugin
        self.p = load_plugin(VITAL_VST3); self.template = self.p.raw_state
    def load(self, path_or_words):
        from autodj.generate.realinst import juce_b64_decode, juce_b64_encode
        path = path_or_words if os.path.exists(str(path_or_words)) else vital_find(*str(path_or_words).split("|"))[0]
        js = open(path, "rb").read()
        xml = self.template[8:].rstrip(b"\x00").decode(); m = re.search(r"<IComponent>([^<]*)</IComponent>", xml)
        inner = juce_b64_decode(m.group(1)); L = int.from_bytes(inner[172:176], "big"); tail = inner[176 + L:]
        head = bytearray(inner[:172]); head[20:24] = (172 + 4 + len(js) - 24).to_bytes(4, "big")
        new = xml.replace(m.group(1), juce_b64_encode(bytes(head) + len(js).to_bytes(4, "big") + js + tail)).encode() + b"\x00"
        self.p.raw_state = b"VC2!" + len(new).to_bytes(4, "little") + new
        self.preset = path
        from .tuning import Cache, pitch_offset, split
        cache = Cache(os.path.join(VITAL_PRESETS, "_tuning3.json"))
        def measure():
            offs = [pitch_offset(self._raw([(0.05, m, 95, 1.3)], 1.6), m) for m in (36, 48, 60)]
            offs = [o for o in offs if o is not None]
            tr, c = split(float(np.median(offs)) if offs else None)
            return [tr, c, round(max(offs) - min(offs), 2) if offs else None]
        self.transpose, self.cents, self.spread = cache.get(os.path.basename(path), measure)
        self.in_tune = self.spread is not None and self.spread < .3 and abs(self.cents) <= 15
        if not self.in_tune: print(f"  ! Vital {os.path.basename(path)}: not in tune (spread {self.spread} st, {self.cents} c) -- pick another preset for tonal parts", flush=True)
        return self
    def render(self, events, total_s, sr=SR, tune=True):
        """events: (t, midi, vel 1-127, dur). tune=True transposes the MIDI by the preset's measured pitch-class error
        (some presets are built a semitone off); octave transpositions inside presets are kept."""
        tr = getattr(self, "transpose", 0) if tune else 0
        return self._raw([(t, m + tr, v, d) for t, m, v, d in events] if tr else events, total_s, sr)
    def _raw(self, events, total_s, sr=SR):
        from mido import Message
        msgs = []
        for t, m, v, d in events:
            msgs += [(max(0.0, t), [0x90, int(m), int(max(1, min(127, v)))]), (max(0.0, t + d), [0x80, int(m), 0])]
        msgs.sort(key=lambda x: x[0])
        mm = [Message.from_bytes(b, time=t) for t, b in msgs]
        out = self.p(mm, duration=total_s, sample_rate=sr, num_channels=2, reset=True).T.astype(np.float32)
        n = int(round(total_s * sr)); return np.pad(out, ((0, max(0, n - len(out))), (0, 0)))[:n]

def sampler(key):
    """VSCO-2 multisample player: violins, violins_spic, violas, violas_spic, cellos, cellos_spic, harp, piano"""
    from .vsampler import Sampler
    return Sampler(key)

def check_notes(events, pcs_allowed, label=""):
    """refuse out-of-key notes before rendering (notes first, groove later)"""
    bad = sorted({e[1] for e in events if e[1] % 12 not in pcs_allowed})
    if bad: raise ValueError(f"{label}: notes out of key {bad}")

def hand_drum(freq=200.0, slap=0.0, decay=.18, sr=SR, seed=0):
    """synthesised conga/bongo-like membrane: two inharmonic modes with a small pitch drop + filtered slap noise.
    freq ~ 180-420 Hz (low conga .. bongo); slap 0..1 for the bright open-slap stroke."""
    from scipy.signal import butter, sosfilt
    r = np.random.default_rng(seed); n = int((decay * 4) * sr); t = np.arange(n) / sr
    f = freq * (1 + .08 * np.exp(-t / .015))
    body = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / decay) + .35 * np.sin(2 * np.pi * np.cumsum(f * 1.58) / sr) * np.exp(-t / (decay * .5))
    nz = sosfilt(butter(2, [freq * 3, min(9000, freq * 20)], "band", fs=sr, output="sos"), r.normal(0, 1, n)) * np.exp(-t / .012)
    y = body + (.25 + slap) * nz; y[:32] *= np.linspace(0, 1, 32); y = y / np.abs(y).max()
    return np.stack([y, y], 1).astype(np.float32)

def keys(preset, events, total_s, sr=SR):
    """sampled Nice-Keys (sf2 via FluidSynth): 'Straight Rhodes', 'Rhodes Bright', pianos, organs... events (t, midi, vel, dur)"""
    from autodj.generate.realinst import render_keys
    y = np.asarray(render_keys(preset, events, total_s, sr), np.float32)
    if y.ndim == 1: y = np.stack([y, y], 1)
    if y.shape[0] == 2 and y.shape[1] != 2: y = y.T
    n = int(round(total_s * sr)); return np.pad(y, ((0, max(0, n - len(y))), (0, 0)))[:n]

def atmosphere(kind, total_s, sr=SR, seed=0, amount=.5):
    """quiet bed of synthesised nature: 'rain', 'wind', 'night' (crickets), 'sand'. Stereo from two seeds."""
    from autodj.generate import nature_synth as ns
    from pedalboard import Pedalboard, HighpassFilter, LowpassFilter
    n = int(total_s * sr)
    f = {"rain": lambda s: ns.rain(n, sr, amount, seed=s), "wind": lambda s: ns.wind_gust(n, sr, amount, seed=s),
         "night": lambda s: ns.crickets(n, sr, seed=s) if "seed" in ns.crickets.__code__.co_varnames else ns.crickets(n, sr),
         "sand": lambda s: ns.sand_on_glass(n, sr, seed=s) if "seed" in ns.sand_on_glass.__code__.co_varnames else ns.sand_on_glass(n, sr)}[kind]
    l, r = np.asarray(f(seed), np.float32).reshape(-1)[:n], np.asarray(f(seed + 1), np.float32).reshape(-1)[:n]
    x = np.stack([l, r], 1); x /= np.abs(x).max() + 1e-9
    return pb(Pedalboard([HighpassFilter(180), LowpassFilter(8000)]), x, sr)
