"""P98: НАСТОЯЩИЕ ИНСТРУМЕНТЫ вместо самодельных numpy-синтов и GM-саундфонта.

Ресерч 2026-10-08: потолок качества задают тембры. Голая пила + ADSR и GM-банк звучат
«демо 90-х». Здесь два источника:
  * keys:<пресет>  — сэмплированный Nice-Keys Ultimate (Rhodes, рояли, Hammond, маримба,
                     гитары) через FluidSynth;
  * surge:<путь>   — Surge XT (VST3, ~1700 пресетов) headless через pedalboard.
Селекторы «@роль» (keys:@ep, surge:@pad …) выбирают КОНКРЕТНЫЙ пресет на трек по seed —
у каждого трека свой набор звуков. Пул surge-пресетов по ролям строит прослушивание
(audition_surge): плохие/шумные/расстроенные пресеты отсеиваются один раз, результат
кэшируется в shared/catalog/surge_patch_index.json.

Формат пресетов Surge: .fxp = 60 байт заголовка + чанк 'sub3'. VST3-состояние JUCE —
"VC2!" + XML с <IComponent> в JUCE-base64: внутри тот же чанк + JUCEPrivateData.
"""
from __future__ import annotations

import glob
import json
import os
import random
import re

import numpy as np

ROOT = "/opt/autodj-mixer"
NICE_KEYS = os.environ.get("NICE_KEYS_SF2", f"{ROOT}/shared/Nice-Keys-Ultimate-V2.3.sf2")
SURGE_VST3 = os.environ.get("SURGE_VST3", f"{ROOT}/plugins/vst3/Surge XT.vst3")
SURGE_DATA = os.environ.get("SURGE_DATA", f"{ROOT}/plugins/surge-xt-data")
SURGE_INDEX = f"{ROOT}/shared/catalog/surge_patch_index.json"

KEYS_POOLS = {
    "ep": ["Straight Rhodes", "Rhodes Bright", "Slow, Light,Tremolo", "SLT Bright",
           "Fast, Light,Tremolo", "Slow, Heavy,Tremolo", "HS DX7 Rhodes"],
    "piano": ["Dark Grand", "Mellow Grand", "Upright Piano", "Yamaha C5 Grand"],
    "organ": ["B3 Fast Leslie", "Rotary Org.S", "Hammond Org.F"],
    "mallet": ["Marimba"],
    "guitar": ["Jazz Guitar 1", "Nylon Guitar Fret", "Single Coil Dry", "Muted Guitar 1"],
    "strings": ["Slow Strings", "Chamber Strings SSO", "Synth Strings"],
}

SURGE_ROLE_CATEGORIES = {
    "pad": ("Pads", "Polysynths", "Chords", "Atmospheres"),
    "pluck": ("Plucks", "Mallets", "Keys"),
    "lead": ("Leads",),
    "bass": ("Basses",),
    "keys": ("Keys", "Polysynths"),
}


# ─── разбор строки инструмента ──────────────────────────────────────────────

def is_real(inst) -> bool:
    return isinstance(inst, str) and (inst.startswith("keys:") or inst.startswith("surge:"))


def resolve(inst: str, rng: random.Random, index: dict | None = None) -> str:
    """Селектор → конкретный пресет трека. keys:@ep → keys:Rhodes Bright;
    surge:@pad → surge:patches_factory/Pads/xxx.fxp. Конкретные строки — как есть."""
    if not is_real(inst):
        return inst
    kind, _, name = inst.partition(":")
    if not name.startswith("@"):
        return inst
    sel = name[1:]
    if kind == "keys":
        pool = KEYS_POOLS.get(sel) or KEYS_POOLS["ep"]
        return "keys:" + rng.choice(pool)
    idx = index if index is not None else load_index()
    pool = sorted(idx.get(sel, []))
    if not pool:
        raise RuntimeError(f"нет прослушанных surge-пресетов для роли {sel!r}: "
                           f"запусти python3 -m autodj.generate.realinst --audition")
    return "surge:" + rng.choice(pool)


def label(inst: str) -> str:
    if inst.startswith("surge:"):
        p = inst[6:]
        return "Surge " + "/".join(p.replace(".fxp", "").split("/")[-2:])
    return "Nice-Keys " + inst[5:]


# ─── Nice-Keys (сэмплы) ─────────────────────────────────────────────────────

_PRESETS = None


def sf2_presets(path: str = NICE_KEYS) -> dict:
    """Имя пресета → (bank, program), из заголовка phdr. Кэш на процесс."""
    global _PRESETS
    if _PRESETS is None:
        with open(path, "rb") as f:
            head = f.read(64 * 1024 * 1024) if os.path.getsize(path) < 64 * 1024 * 1024 else None
        if head is None:                                  # phdr в конце большого файла
            with open(path, "rb") as f:
                f.seek(max(0, os.path.getsize(path) - 8 * 1024 * 1024))
                head = f.read()
        i = head.rfind(b"phdr")
        n = int.from_bytes(head[i + 4:i + 8], "little") // 38
        out = {}
        for k in range(n - 1):
            r = head[i + 8 + k * 38: i + 8 + (k + 1) * 38]
            name = r[:20].split(b"\0")[0].decode("latin1").strip()
            out.setdefault(name, (int.from_bytes(r[22:24], "little"),
                                  int.from_bytes(r[20:22], "little")))
        _PRESETS = out
    return _PRESETS


def _flat(notes):
    for ev in notes:
        t, n, v, d = ev[0], ev[1], ev[2], ev[3]
        for m in (n if isinstance(n, (list, tuple)) else [n]):
            yield float(t), int(m), int(max(1, min(127, v))), float(d)


def render_keys(preset: str, notes: list, duration: float, sr: int = 44100,
                release_s: float = 0.0) -> np.ndarray:
    from .backends.fluidsynth import FluidSynthBackend
    bank, prog = sf2_presets()[preset]
    ch = 0
    ev = [(0.0, "program", ch, bank, prog), (0.0, "control", ch, 91, 20)]
    for t, m, v, d in _flat(notes):
        ev.append((t, "note_on", ch, m, v))
        ev.append((t + d + release_s, "note_off", ch, m, 0))
    ev.sort(key=lambda e: e[0])
    with FluidSynthBackend(NICE_KEYS, sr) as b:
        return b.render(ev, duration)


# ─── Surge XT (VST3) ────────────────────────────────────────────────────────

_T = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def juce_b64_decode(s: str) -> bytes:
    size, _, data = s.partition(".")
    size = int(size)
    bits = 0
    nbits = 0
    out = bytearray()
    for ch in data:
        bits |= _T.index(ch) << nbits
        nbits += 6
        while nbits >= 8 and len(out) < size:
            out.append(bits & 0xFF)
            bits >>= 8
            nbits -= 8
    return bytes(out[:size]) + bytes(max(0, size - len(out)))


def juce_b64_encode(b: bytes) -> str:
    chars, bits, nbits = [], 0, 0
    for byte in b:
        bits |= byte << nbits
        nbits += 8
        while nbits >= 6:
            chars.append(_T[bits & 63])
            bits >>= 6
            nbits -= 6
    if nbits:
        chars.append(_T[bits & 63])
    return f"{len(b)}." + "".join(chars)


def fxp_chunk(path: str) -> bytes:
    raw = open(path, "rb").read()
    if raw[:4] != b"CcnK" or raw[56:60] == b"" or b"sub3" not in raw[:80]:
        raise ValueError(f"не Surge .fxp: {path}")
    return raw[60:]


def wrap_state(template: bytes, chunk: bytes) -> bytes:
    """Подменить патч в VST3-состоянии JUCE, сохранив JUCEPrivateData."""
    xml = template[8:].rstrip(b"\x00").decode()
    m = re.search(r"<IComponent>([^<]*)</IComponent>", xml)
    inner = juce_b64_decode(m.group(1))
    n = int.from_bytes(inner[4:8], "little")
    tail = inner[8 + n:] if inner[:4] == b"sub3" else b""
    new = xml.replace(m.group(1), juce_b64_encode(chunk + tail)).encode() + b"\x00"
    return b"VC2!" + len(new).to_bytes(4, "little") + new


class Surge:
    """Один экземпляр плагина на процесс; патч меняется подменой состояния."""
    _inst = None

    def __init__(self):
        from pedalboard import load_plugin
        self.plugin = load_plugin(SURGE_VST3)
        self.template = self.plugin.raw_state

    @classmethod
    def get(cls) -> "Surge":
        if cls._inst is None:
            cls._inst = Surge()
        return cls._inst

    def load(self, rel: str):
        path = rel if os.path.isabs(rel) else os.path.join(SURGE_DATA, rel)
        self.plugin.raw_state = wrap_state(self.template, fxp_chunk(path))

    def render(self, rel: str, notes: list, duration: float, sr: int = 44100,
               release_s: float = 0.0) -> np.ndarray:
        import mido
        self.load(rel)
        self.plugin([], duration=0.3, sample_rate=sr, num_channels=2, reset=False)  # патч применяется
        msgs = []
        for t, m, v, d in _flat(notes):
            msgs.append(mido.Message("note_on", note=m, velocity=v, time=t))
            msgs.append(mido.Message("note_off", note=m, velocity=0, time=t + d + release_s))
        msgs.sort(key=lambda x: x.time)
        a = self.plugin(msgs, duration=duration, sample_rate=sr, num_channels=2, reset=False)
        out = np.asarray(a, dtype=np.float32).T
        peak = float(np.abs(out).max()) if out.size else 0.0
        if peak > 0.99:
            out *= 0.99 / peak
        return out


def surge_available() -> bool:
    return os.path.isdir(SURGE_VST3) and os.path.isdir(SURGE_DATA)


def keys_available() -> bool:
    return os.path.isfile(NICE_KEYS)


def render_real(inst: str, notes: list, duration: float, sr: int = 44100,
                release_s: float = 0.0) -> np.ndarray:
    """Конкретный пресет (после resolve) → стерео (n, 2)."""
    total = int(duration * sr)
    if not notes:
        return np.zeros((total, 2), np.float32)
    kind, _, name = inst.partition(":")
    if kind == "keys":
        buf = render_keys(name, notes, duration, sr, release_s)
    else:
        buf = Surge.get().render(name, notes, duration, sr, release_s)
    if len(buf) < total:
        buf = np.pad(buf, ((0, total - len(buf)), (0, 0)))
    return level_match(buf[:total].astype(np.float32))


def level_match(buf: np.ndarray, target_rms: float = 0.08) -> np.ndarray:
    """Пресеты и сэмплы сильно разной громкости (Nice-Keys ~0.01, Surge ~0.2): приводим
    звучащие участки к одному уровню, чтобы миксшина не упиралась в потолок +12 дБ.
    Тишина не поднимается; пик не выше 0.99. Чистая."""
    mag = np.abs(buf).max(axis=1)
    live = mag > 1e-4
    if not live.any():
        return buf
    rms = float(np.sqrt(np.mean(buf[live] ** 2)))
    g = target_rms / max(rms, 1e-6)
    peak = float(mag.max()) * g
    if peak > 0.99:
        g *= 0.99 / peak
    return (buf * g).astype(np.float32)


# ─── прослушивание пресетов Surge (один раз) ────────────────────────────────

def _metrics(a: np.ndarray, sr: int, f0: float) -> dict:
    m = a.mean(axis=1)
    n = len(m)
    seg = lambda t0, t1: m[int(t0 * sr):int(t1 * sr)]
    rms = lambda x: float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    body = seg(0.05, 1.2)
    X = np.abs(np.fft.rfft(body * np.hanning(len(body)))) + 1e-12
    f = np.fft.rfftfreq(len(body), 1 / sr)
    def _harm(base):                                  # доля энергии в гармониках base
        h = 0.0
        for k in range(1, 24):
            h += X[(f > base * k * 0.97 - 1.5) & (f < base * k * 1.03 + 1.5)].sum()
        return h
    harm = max(_harm(f0), _harm(f0 / 2), _harm(f0 * 2) + X[(f > f0 * 0.97) & (f < f0 * 1.03)].sum())
    return {
        "rms": rms(body),
        "early": rms(seg(0.05, 0.3)), "late": rms(seg(1.0, 1.4)),
        "tail": rms(seg(1.9, 2.4)),
        "centroid": float((X * f).sum() / X.sum()),
        "flatness": float(np.exp(np.mean(np.log(X))) / np.mean(X)),
        "harmonicity": float(harm / X.sum()),
        "low_ratio": float(X[f < 200].sum() / X.sum()),
        "width": float(np.std(a[:, 0] - a[:, 1]) / (np.std(m) + 1e-9)) if n else 0.0,
    }


def classify(cat: str, name: str, mt: dict) -> list[str]:
    """Метрики прослушивания → подходящие роли. Чистая."""
    bad = re.search(r"(?i)\b(fx|noise|riser|sweep|vocoder|sequence|seq|arp|drone|glitch|"
                    r"init|template|tutorial|split|mpe|perc|drum|kick|snare|hat)\b", name)
    if bad or mt["rms"] < 0.01 or mt["flatness"] > 0.22 or mt["harmonicity"] < 0.35:
        return []
    roles = []
    sustained = mt["late"] > 0.5 * mt["early"]
    decaying = mt["late"] < 0.45 * mt["early"]
    c = mt["centroid"]
    if cat in SURGE_ROLE_CATEGORIES["bass"] and mt["low_ratio"] > 0.35 and c < 1500:
        roles.append("bass")
    if cat in SURGE_ROLE_CATEGORIES["pad"] and sustained and 300 < c < 4500:
        roles.append("pad")
    if cat in SURGE_ROLE_CATEGORIES["pluck"] and decaying and 500 < c < 5500:
        roles.append("pluck")
    if cat in SURGE_ROLE_CATEGORIES["lead"] and sustained and 600 < c < 5500:
        roles.append("lead")
    if cat in SURGE_ROLE_CATEGORIES["keys"] and 300 < c < 4000 and not sustained:
        roles.append("keys")
    return roles


def audition_surge(paths: list[str] | None = None, sr: int = 44100) -> dict:
    """Каждый пресет играет тестовую ноту/аккорд → метрики → роли. ~0.4 с на пресет."""
    cats = {c for v in SURGE_ROLE_CATEGORIES.values() for c in v}
    if paths is None:
        paths = []
        for c in cats:
            paths += glob.glob(f"{SURGE_DATA}/patches_factory/{c}/*.fxp")
            paths += glob.glob(f"{SURGE_DATA}/patches_3rdparty/*/{c}/*.fxp")
    s = Surge.get()
    result = {"_meta": {}}
    for p in sorted(paths):
        rel = os.path.relpath(p, SURGE_DATA)
        cat = os.path.basename(os.path.dirname(p))
        name = os.path.basename(p)[:-4]
        note = 40 if cat == "Basses" else 60
        try:
            a = s.render(rel, [(0.05, note, 96, 1.4)], 2.5, sr).astype(np.float64)
            mt = _metrics(a, sr, 440.0 * 2 ** ((note - 69) / 12))
        except Exception as e:                            # битый пресет — мимо
            result["_meta"][rel] = {"error": type(e).__name__}
            continue
        roles = classify(cat, name, mt)
        result["_meta"][rel] = {k: round(v, 4) for k, v in mt.items()} | {"roles": roles}
        for r in roles:
            result.setdefault(r, []).append(rel)
    return result


def load_index() -> dict:
    try:
        with open(SURGE_INDEX) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


if __name__ == "__main__":
    import sys
    if "--audition" in sys.argv:
        idx = audition_surge()
        os.makedirs(os.path.dirname(SURGE_INDEX), exist_ok=True)
        with open(SURGE_INDEX, "w") as f:
            json.dump(idx, f, ensure_ascii=False, indent=1)
        print({k: len(v) for k, v in idx.items() if k != "_meta"},
              "из", len(idx["_meta"]))
