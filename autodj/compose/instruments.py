"""Sound sources: Vital presets, VSCO-2 sampler, drum sample pickers."""
import glob, json, os, re
import numpy as np
from .assets import WA, TDM, VITAL_PRESETS, VITAL_VST3, VSCO
from .core import SR, load_sample

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
        return self
    def render(self, events, total_s, sr=SR):
        """events: (t, midi, vel 1-127, dur)"""
        from mido import Message
        msgs = []
        for t, m, v, d in events:
            msgs += [(max(0.0, t), [0x90, int(m), int(max(1, min(127, v)))]), (max(0.0, t + d), [0x80, int(m), 0])]
        msgs.sort(key=lambda x: x[0])
        out = self.p([Message.from_bytes(b, time=t) for t, b in msgs], duration=total_s, sample_rate=sr, num_channels=2, reset=True).T.astype(np.float32)
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
