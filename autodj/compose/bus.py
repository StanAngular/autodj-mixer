"""P130 (2026-11-12, audit «глибина у взаємодії елементів»): the mix graph. Until now every layer was summed straight into one
stereo buffer: the «sidechain» was a clock (a dip on every beat whether the kick plays or not), every layer carried its own reverb,
nothing could react to anything else. Here are the four things a mixing desk gives a producer, all opt-in from Track.add():

  key=    keyed ducking: a layer dips when ANOTHER layer really sounds (its measured envelope), optionally only in one band
          trk.add("bass", b, duck=-6, key="kick")                      # follows the real kick, also its drops and fills
          trk.add("pad", p, duck=-4, key="hook", band=(400, 3000))     # the pad makes room for the hook only where the hook lives
  follow  any layer's envelope as a 0..1 curve for ANY parameter of another layer (filter, send, level, synth modulation)
          opening = trk.follow("hats", release_ms=400)                 # e.g. sweep(pad, cuts, opening)
  send=   shared spaces (one room / one echo for the track): layers are sent into them, the return is added once and can
          step back while its senders play (the tail blooms in the gaps): depth instead of «every layer in its own reverb»
          trk.add("hook", h, send={"room": .25, "echo": .15}); trk.space("echo", kind="echo", steps=3, fb=.5)
  depth=  distance as ONE number 0 (front, dry, bright) .. 1 (back, darker, wetter)
  bus=    groups: layers are summed into a bus first; the bus gets its own glue / parallel compression / ducking / sends
          trk.add("hats", h, bus="drums"); trk.bus("drums", fx=[glue()], parallel=(smash(), .15))

Nothing changes for a score that does not use these arguments."""
import numpy as np
from scipy.signal import butter, sosfiltfilt

CTL = 64                                   # control-rate hop in samples (1.45 ms at 44.1 kHz)

def envelope(x, hop=CTL):
    """peak envelope of a buffer at control rate: one value per `hop` samples"""
    m = np.abs(x).max(1) if x.ndim == 2 else np.abs(x)
    k = -(-len(m) // hop); m = np.pad(m, (0, k * hop - len(m)))
    return m.reshape(k, hop).max(1).astype(np.float32)

def follower(e, sr, hop=CTL, attack_ms=1.0, hold_ms=0.0, release_ms=140.0):
    """attack / hold / release follower on a control-rate envelope. release_ms = time to recover ~98 % (as in sidechain_duck)."""
    ca = np.exp(-hop / max(1e-9, attack_ms / 1000 * sr)) if attack_ms > 0 else 0.0
    cr = np.exp(-4.0 * hop / max(1e-9, release_ms / 1000 * sr)); h = int(round(hold_ms / 1000 * sr / hop))
    out = np.empty(len(e), np.float32); y = 0.0; left = 0
    for i, v in enumerate(e.tolist()):
        if v >= y: y = v + (y - v) * ca; left = h
        elif left > 0: left -= 1
        else: y = v + (y - v) * cr
        out[i] = y
    return out

def normalised(e):
    """envelope scaled so that its usual peaks sit at 1 (95th percentile of the sounding part), clipped to 0..1"""
    act = e[e > 1e-4]
    if not len(act): return np.zeros_like(e)
    return np.clip(e / (float(np.percentile(act, 95)) + 1e-12), 0, 1).astype(np.float32)

def upsample(c, n, hop=CTL):
    """control-rate curve -> n samples (linear; control point i sits on sample i * hop)"""
    return np.interp(np.arange(n, dtype=np.float64), np.arange(len(c), dtype=np.float64) * hop, c).astype(np.float32)

def keyed_gain(key_env, n, sr, depth_db=-6.0, attack_ms=1.0, hold_ms=15.0, release_ms=140.0, hop=CTL):
    """gain curve (n,) that dips to depth_db when the key is at its usual peak level and recovers when it goes quiet"""
    f = follower(normalised(key_env), sr, hop, attack_ms, hold_ms, release_ms)
    return upsample(1.0 - (1.0 - 10 ** (depth_db / 20)) * f, n, hop)

def split_band(x, sr, band):
    """(inside, rest): zero-phase band split that sums back to x exactly"""
    lo, hi = band; ny = sr / 2
    if lo <= 20: sos = butter(2, min(hi, ny * .95), "low", fs=sr, output="sos")
    elif hi >= ny * .95: sos = butter(2, lo, "high", fs=sr, output="sos")
    else: sos = butter(2, [lo, hi], "band", fs=sr, output="sos")
    inside = sosfiltfilt(sos, x, axis=0).astype(np.float32)
    return inside, x - inside

def duck(x, sr, key_env, depth_db=-6.0, band=None, **kw):
    """x ducked by a key envelope; with band=(lo, hi) only that band of x gives way (the rest is untouched)"""
    g = keyed_gain(key_env, len(x), sr, depth_db, **kw)[:, None]
    if band is None: return (x * g).astype(np.float32)
    inside, rest = split_band(x, sr, band)
    return (rest + inside * g).astype(np.float32)

def distance(x, depth, sr, top_db=-9.0, level_db=-2.0, corner=3500.0):
    """move a layer back: the further, the less top (air absorption) and a little less level. depth 0 = unchanged."""
    d = float(np.clip(depth, 0, 1))
    if d <= 0: return x
    lp = sosfiltfilt(butter(1, corner, "low", fs=sr, output="sos"), x, axis=0)
    return ((lp + (x - lp) * 10 ** (top_db * d / 20)) * 10 ** (level_db * d / 20)).astype(np.float32)

# ---- shared spaces ---------------------------------------------------------------------------------------------------
KINDS = {"room": dict(decay_s=.7, predelay_ms=8, lo=250, hi=8000), "plate": dict(decay_s=1.6, predelay_ms=15, lo=300, hi=9000),
         "hall": dict(decay_s=3.2, predelay_ms=28, lo=200, hi=5500), "echo": dict(steps=3, fb=.45, lo=300, hi=3500)}

class Space:
    """One shared return for the whole track. kind room / plate / hall: a generated impulse response (alive.room_ir);
    kind echo: a tempo delay of `steps` sixteenths whose every repeat is filtered again (each one darker, the dub echo).
    back_db < 0: the return steps back by that much while its senders sound and blooms when they stop."""
    def __init__(self, trk, kind="room", level=1.0, back_db=-5.0, seed=None, **kw):
        if kind not in KINDS: raise ValueError(f"space kind {kind!r} not in {sorted(KINDS)}")
        self.trk, self.kind, self.level, self.back_db = trk, kind, level, back_db
        self.p = {**KINDS[kind], **kw}; self.seed = int(trk.rng.integers(1 << 30)) if seed is None else seed
        self.buf = None; self.sent = {}
    @property
    def pending(self):
        return self.buf is not None
    def send(self, x, amount, name=None):
        if amount <= 0: return
        if self.buf is None: self.buf = self.trk.buf()
        n = min(len(x), len(self.buf)); self.buf[:n] += x[:n] * amount
        if name: self.sent[name] = round(float(amount), 3)
    def render(self):
        """the wet return of everything sent so far; the send buffer is emptied"""
        if self.buf is None: return self.trk.buf()
        src, self.buf = self.buf, None; sr = self.trk.sr
        if self.kind == "echo": wet = self._echo(src)
        else:
            from scipy.signal import oaconvolve
            from .alive import room_ir
            ir = room_ir(sr, self.p["decay_s"], self.p["predelay_ms"], self.seed, self.p["lo"], self.p["hi"])
            wet = np.stack([oaconvolve(src[:, c], ir[:, c])[:len(src)] for c in range(2)], 1).astype(np.float32)
        if self.back_db: wet = duck(wet, sr, envelope(src), self.back_db, attack_ms=5, hold_ms=30, release_ms=350)
        return (wet * self.level).astype(np.float32)
    def _echo(self, src):
        sr = self.trk.sr; d = int(round(self.p["steps"] * self.trk.S16 * sr)); fb = float(min(.9, self.p["fb"]))
        sos = butter(1, [self.p["lo"], self.p["hi"]], "band", fs=sr, output="sos")
        out = np.zeros_like(src); tap = src
        for k in range(1, 40):
            if k * d >= len(src) or fb ** (k - 1) < 1e-3: break
            tap = sosfiltfilt(sos, tap, axis=0).astype(np.float32)             # every repeat passes the filter again
            out[k * d:] += tap[:len(src) - k * d] * fb ** (k - 1)
        return out

# ---- group buses -----------------------------------------------------------------------------------------------------
class Relative:
    """a compressor whose threshold is set RELATIVE to the level of the bus it sits on (the score's levels are relative to the
    kick, not to full scale, so an absolute threshold would mean something different in every track)"""
    def __init__(self, over_db, ratio, attack_ms, release_ms):
        self.over_db, self.ratio, self.attack_ms, self.release_ms = over_db, ratio, attack_ms, release_ms
    def __call__(self, y, sr):
        from pedalboard import Pedalboard, Compressor
        from .core import pb, rms
        act = np.abs(y).max(1) > 1e-4
        if not act.any(): return y
        thr = 20 * np.log10(rms(y[act]) + 1e-12) + self.over_db
        return pb(Pedalboard([Compressor(threshold_db=float(thr), ratio=self.ratio, attack_ms=self.attack_ms, release_ms=self.release_ms)]), y, sr)

def glue(over_db=4.0, ratio=1.6, attack_ms=10.0, release_ms=120.0):
    """a gentle bus compressor: only what rises more than over_db above the bus's own level is held back, so the layers of a group
    start to move together (1-2 dB of gain reduction on the peaks, not more)"""
    return Relative(over_db, ratio, attack_ms, release_ms)

def smash(over_db=-10.0, ratio=8.0, attack_ms=0.5, release_ms=80.0):
    """the heavy compressor of a parallel («New York») chain: mixed UNDER the dry bus it adds body; its fast attack keeps the
    transients out of the added signal"""
    return Relative(over_db, ratio, attack_ms, release_ms)

def _run(fx, y, sr):
    if fx is None: return y
    if isinstance(fx, (list, tuple)) and any(isinstance(f, Relative) or (callable(f) and not hasattr(f, "process")) for f in fx):
        for f in fx: y = _run(f, y, sr)                                               # a chain that mixes plugins and functions
        return y
    if isinstance(fx, Relative): return np.asarray(fx(y, sr), np.float32)
    if callable(fx) and not hasattr(fx, "process"): return np.asarray(fx(y), np.float32)
    from pedalboard import Pedalboard
    from .core import pb
    return pb(fx if isinstance(fx, Pedalboard) else Pedalboard(list(fx) if isinstance(fx, (list, tuple)) else [fx]), y, sr)

def process(trk, name, y, cfg):
    """a group bus on its way into the mix: fx -> parallel chain -> level kept (makeup) -> keyed duck -> sends"""
    from .core import rms
    act = np.abs(y).max(1) > 1e-4
    if not act.any(): return y
    before = rms(y[act]); sr = trk.sr
    y = _run(cfg.get("fx"), y, sr)
    if cfg.get("parallel"):
        pfx, amt = cfg["parallel"]; y = y + float(amt) * _run(pfx, y, sr)
    if cfg.get("makeup", True): y = y * (before / rms(y[act]))                 # the level plan of the score stays valid
    if cfg.get("duck") and cfg.get("key") is not None:
        y = duck(y, sr, trk.key_env(cfg["key"]), cfg["duck"], band=cfg.get("band"), release_ms=cfg.get("release_ms", 140))
    for sp, amt in (cfg.get("send") or {}).items(): trk.space(sp).send(y, amt, name="bus:" + name)
    return y.astype(np.float32)
