---
name: feedback-check-tuning-of-sources
description: "«Гармония хромает» on 2026-10-17 was a Vital bass preset sounding an octave + ~a semitone off plus m2 clusters in voicings; check source tuning before anything else; keep Gemini blind"
metadata:
  type: feedback
---

2026-10-17, «Тепло рук»: Стас heard layers that «не попадают гармонично»; Gemini (given only the audio) missed it and rated harmony 7. Cause 1: Vital «Psychill Bass Clean» has a frequency-shift/transpose inside: it sounded an octave and roughly a semitone below the written note (and pushed sub to 50%). An audit of ~70 bass presets found several transposed by a tone, a semitone or a tritone. Cause 2: rootless 9th voicings contained minor 2nds (E-F, B-C) that rubbed across layers.

**Why:** score-level note checks (all notes in key) cannot see a preset that sounds different from its MIDI note.
**How to apply:** autodj.compose now measures every Vital preset (tuning.py, cache `_tuning3.json`) and transposes or flags it; VSCO samples are corrected to the cent; `harmony.clashes` gates m2/m9 between layers. When a render "sounds out of key", check `Vital(...).in_tune`/the clash ratio first, see [[feedback-diagnose-notes-before-performance]]. Gemini is suggestible: when our number (e.g. 34% clashes) was in the prompt it "confirmed" it; keep its review blind (review.py does).

2026-10-24 (Uncertain v2 stem comparison): **WART_Gm_Pad_Shot_1 is a recorded F-minor CHORD (chroma F 1.00, C .73, Ab .60), not one note** — played at other pitches it adds foreign notes (F#/Eb showed up in the pads). Also suspicious: WATE_Gm_Pd_02 (G + F# .58 + D .53, re-struck = «hard piano»). Single-pitch sustained pad: **WATE_Gm_Pd_01** (G, sus .93). Before using any «Gm …» shot as a pitched instrument, check its chroma with bins_per_octave=36: one strong class (+ its 5th) only.

2026-11-15 Ёлочка DnB (elochka_dnb/score.py), три новых источника «фальши», найдены замером:
- `sfz.oneshot(..., policy="fold")` сдвигает ноты октавами в +-6 от высоты записи: мелодия шире октавы ломается (C5 звучал как C3). Для мелодий брать сэмпл с измеренным корнем внутри диапазона мелодии и policy="warn".
- W.A. Synth Shots часто детюн-суперсо (пики по +-1 полутону вокруг ноты): для мелодии не годятся. Чистые: WART_Gm_Lead_Shot_6/7/19, WATE_Gm_Lead_15/16 (корень G4, pyin стабилен).
- Дроны MusicRadar experimental это АККОРДЫ (chroma: 4-5 сильных классов), сдвиг к тонике не делает их тоничными: в фа миноре оказывались A/D/E. В тональную музыку не класть; подложку делать из чистого звука по нотам аккорда (rother/common.sustained).
