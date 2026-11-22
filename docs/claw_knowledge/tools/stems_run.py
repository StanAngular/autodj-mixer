"""Re-render a score and save every layer (dry, post-duck, no shared reverb) on one common scale: python3 stems_run.py score.py --seed N --outdir DIR.
Wraps Track.add, takes the layer as the change of the mix/bus sums. Layers sum back to the mix minus shared spaces. Output DIR/layers/<name>.wav + .mp3 (192k)."""
import sys, os, numpy as np, soundfile as sf, subprocess
sys.path.insert(0, "/opt/autodj-mixer")
from autodj.compose import core
LAY = {}; _add = core.Track.add
def add(self, name, x, *a, **k):
    m0 = self._mix.copy(); b0 = {n: v.copy() for n, v in self.buses.items()}
    _add(self, name, x, *a, **k)
    d = self._mix - m0
    for n, v in self.buses.items(): d = d + (v - b0[n] if n in b0 else v)
    if np.abs(d).max() > 1e-6: LAY[name] = d.astype(np.float32)
core.Track.add = add
from autodj.compose import run
args = sys.argv[1:]; outdir = args[args.index("--outdir") + 1]; run.main(["run"] + [a for a in args if a != "--clips"])
ld = os.path.join(outdir, "layers"); os.makedirs(ld, exist_ok=True); peak = max(np.abs(v).max() for v in LAY.values()); g = 10 ** (-3 / 20) / peak
for n, v in LAY.items():
    p = os.path.join(ld, n + ".wav"); sf.write(p, v * g, 44100); subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", p, "-b:a", "192k", p[:-4] + ".mp3"], check=True); os.remove(p)
if "--clips" in args:                                                        # Стас 2026-11-20: one ~10 s clip per layer where it is clearly audible (loudest window of its own RMS, with the layer at least 40% of the window)
    import scipy.signal as sg
    cl = os.path.join(outdir, "clips"); os.makedirs(cl, exist_ok=True); W = 441000; hop = 44100
    for n, v in LAY.items():
        m = v.mean(1); e = np.array([np.sqrt((m[i:i + W] ** 2).mean()) for i in range(0, max(1, len(m) - W), hop)]); i0 = int(np.argmax(e)) * hop; seg = v[i0:i0 + W] * g
        seg[:2000] *= np.linspace(0, 1, 2000)[:, None]; seg[-4000:] *= np.linspace(1, 0, 4000)[:, None]; p = os.path.join(cl, f"{n}_{i0 // 44100 // 60}m{i0 // 44100 % 60:02d}s.wav"); sf.write(p, seg, 44100)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", p, "-b:a", "192k", p[:-4] + ".mp3"], check=True); os.remove(p)
print("LAYERS", sorted(LAY), "gain %.2f" % g)
