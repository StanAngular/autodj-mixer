---
name: project-reel-techno-2026-11-22
description: "2026-11-22 Reel Techno: techno built from the sound of an instagram reel (Df1fj8pRy34); how the reel was used, palette name bugs found, loudness numbers"
metadata:
  type: project
---

2026-11-22 «Reel Techno»: Стас «скачай [reel Df1fj8pRy34], сделай техно с этим звуком». Reel (yt-dlp works for instagram without cookies; /opt/autodj-mixer/cookies.txt exists as fallback): 39 s, no speech, mechanical clicks (0-18 s), chirps (18-21), low grind (21-30), electronic warble (30-39); blind Gemini description is noisy. Score `workspace/music/reel_techno_2026_11_22/score.py`: reel slices = tick percussion (16ths), chirp fills/build, warble (time-stretched to 4 bars) as the hook in breaks and peaks, grind low-passed as rumble; everything else from the techno genre card (kick W.A. -1 st, 909-style hats, rolling bass riff in mono, drum_plan_v2, master -11.7 LUFS). 132 BPM, G, 4:10, sent with 10 layer clips; verdict pending; not heard by me.
**Findings:** palette name bugs (a hat that was a snare `sd02`, a bass that was a lead shot, a clap that was a perc) fixed for all cards (P180); techno has no shaker line in its profile (empty layer = SILENT gate: add the layer only when events exist); atonal sound design makes musicality FAIL «тональность не держится» (key_fit 0.32), expected here; hats «торчат» report is high because the mix has no tonal body.
**Loudness numbers (for any hard genre):** Стас's references NO STATIC / DANGER measure -8.1 / -7.1 LUFS, crest 9 dB; -11.5 LUFS needs ~6 dB of limiting on a normal mix, -10 needs 12-13 dB. Card: -11.5, clip knee -11, limiter gate 8, ceiling -2.5.
