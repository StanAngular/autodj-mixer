"""Sample generation with Stable Audio Open Small (Stability AI Community License), CPU.
  PYTHONPATH=$HOME/.local/lib/sao:/opt/autodj-mixer python3 -m autodj.compose.sao jobs.json OUTDIR
jobs.json: [{"name": "gtr1", "prompt": "...", "seconds": 8, "bpm": 123, "bars": 2, "seed": 1}, ...]
The model is loaded once per batch (~2 min); a 12 s clip then takes ~25 s (8 diffusion steps + decode).
IMPORTANT: the shipped config runs the decoder in float16, which on CPU took >10 min per clip; we force float32
(3 s per 3 s of audio). If bpm/bars are given, the clip is trimmed to whole bars from the first strong onset so it
loops on the grid. Generated audio is a starting point: check it by ear/measurement before using it in a track."""
import json, os, sys, time
import numpy as np, soundfile as sf

def load():
    import torch
    from stable_audio_tools import get_pretrained_model
    model, cfg = get_pretrained_model("stabilityai/stable-audio-open-small"); model = model.eval()
    model.pretransform.model_half = False; model.pretransform.model.float(); model.float()
    torch.set_num_threads(os.cpu_count() or 4)
    return model, cfg

def generate(model, cfg, prompt, seconds=8, seed=1, steps=8):
    import torch
    from stable_audio_tools.inference.generation import generate_diffusion_cond
    with torch.inference_mode():
        out = generate_diffusion_cond(model, steps=steps, conditioning=[{"prompt": prompt, "seconds_total": seconds}], sample_size=cfg["sample_size"],
                                      sampler_type="pingpong", device="cpu", seed=seed)
    a = out[0].float().clamp(-1, 1).numpy().T
    return a[:int(seconds * cfg["sample_rate"])], cfg["sample_rate"]

def to_bars(a, sr, bpm, bars):
    """start at the first strong onset, keep whole bars, 5 ms fades: loops cleanly on the grid"""
    import librosa
    m = a.mean(1); on = librosa.onset.onset_detect(y=m, sr=sr, units="samples", backtrack=True)
    s = int(on[0]) if len(on) else 0; n = int(round(bars * 4 * 60 / bpm * sr))
    x = a[s:s + n]
    if len(x) < n: x = np.pad(x, ((0, n - len(x)), (0, 0)))
    f = int(.005 * sr); x[:f] *= np.linspace(0, 1, f)[:, None]; x[-f:] *= np.linspace(1, 0, f)[:, None]
    return x

def main(jobs_path, outdir):
    jobs = json.load(open(jobs_path)); os.makedirs(outdir, exist_ok=True)
    t0 = time.time(); model, cfg = load(); print(f"model loaded {time.time() - t0:.0f}s", flush=True)
    for j in jobs:
        t = time.time(); a, sr = generate(model, cfg, j["prompt"], j.get("seconds", 8), j.get("seed", 1), j.get("steps", 8))
        if j.get("bpm") and j.get("bars"): a = to_bars(a, sr, j["bpm"], j["bars"])
        a = a / (np.abs(a).max() + 1e-9) * .89
        sf.write(os.path.join(outdir, j["name"] + ".wav"), a, sr); print(f"{j['name']}: {time.time() - t:.0f}s {len(a) / sr:.1f}s", flush=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
