---
name: Ears substitutes (Audiobox + arc)
description: 2026-11-02 second-listener tooling in workspace/music/ears (Audiobox Aesthetics scores, arrangement arc/repetition), calibration numbers, how to use before sending a track
type: reference
---
`python3 workspace/music/ears/abx.py clip.wav ...` -> {CE enjoyment, CU usefulness, PC complexity, PQ production quality} 1-10 (Meta Audiobox Aesthetics, CPU, 416 MB model in ~/.cache/huggingface, code in ~/.local/lib/abx, loader patched to soundfile). `python3 workspace/music/ears/arc.py track.mp3 BPM` -> loudness range, rises/falls, share of bars identical to 8/16 bars earlier, longest unchanged run.
Calibration (20 s mid clip): Clay Path CE 7.4 / PQ 7.75 (Стас's favourite), Suno ref 7.14/7.69, Detuned III 6.85, Haunted 6.07, Orbit PQ 6.57 (he said «грубо»), Phone Line CE 4.86 PC 4.04 (flat). Line Busy x3 (5:34-6:17): CE 5.3-6.1, lb2 best; repetition 0.85-0.87 even after variation = not yet «интересно».
**How to apply:** score 3 clips (25/55/85 %) + arc before sending a full track; target CE >= 6.5, PQ >= 7.2, same-as-8-bars-ago <= 0.6, loudness range >= 6 dB; report the numbers honestly with the track. Disk is ~800 MB free: do not install more big models without asking.
