---
name: reference-stable-audio-open
description: How Stable Audio Open Small runs on this CPU box (install path, HF token, fp16 decoder trap, timings) for generating missing samples
metadata:
  type: reference
---

Installed 2026-10-19 without touching system packages (no python3-venv on the box): `pip install --target ~/.local/lib/sao --no-deps` stable-audio-tools 0.0.19 + minimal deps (transformers 4.46.3, tokenizers 0.20.3, huggingface_hub 0.36.0 pinned there because system hub is 1.15, sentencepiece, torchsde, torchdiffeq, k-diffusion 0.1.1 with `__init__` trimmed to sampling/utils/external and torchvision made optional in utils.py). Use `PYTHONPATH=~/.local/lib/sao:/opt/autodj-mixer python3 -m autodj.compose.sao jobs.json OUTDIR`.
HF token (Стас's, read) in `~/.cache/huggingface/token` (600); model cache ~1.6 GB.
Trap: model_config sets the decoder `model_half: true`; on CPU fp16 decode took >10 min per clip. `autodj/compose/sao.py` forces float32 -> ~2 min load, ~25 s per 4-12 s clip.
Disk is tight (~2.5-5 GB free): pip installs without `--no-deps` pull a full torch and fill the disk.
