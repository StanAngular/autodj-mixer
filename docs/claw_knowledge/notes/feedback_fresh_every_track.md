---
name: feedback-fresh-every-track
description: 2026-11-12 Стас + Claude Fable audit: sounds, drum patterns and chord loops repeated across tracks; every new track chooses harmony, sounds and drums anew via the engine (chords.Plan, fresh.pick, fresh_notes), old helpers retired
metadata:
  type: feedback
---

Стас 2026-11-12: «ты по-прежнему тянешь старые паттерны, накладываешь звуки, которые уже использовал, и звуки и их использование негармонично, ударные подобраны явно по шаблону»; he suspected the memory itself. Fable read the scores and my memory and confirmed three causes: (1) harmony typed by hand and the same (i add9 – VI maj7 – iv m7 – V7sus4 looped for the whole track in Night Shift, Carthage, Glass Hours), (2) sample paths hard-coded in the helpers wk.py / vibe.py (W.A. shots, Kit 15, jRhodes, Karoryfer), (3) memory stored recipes («keep this recipe», «prefer WART_Kick_2/5/9») instead of principles. Measured: the same kicks / bass shots / Rhodes / kit in 9-17 project folders each.

**Why:** the engine did not remember what earlier tracks used and I filled the gap with safe defaults.
**How to apply:** harmony = `autodj.compose.chords.Plan.build` (idioms, sections, voicings; never type `CH = [4 chords]`), melody = `lines.py`, sounds and drum files = `fresh.pick` from folders, then read `fresh_notes`, `depth_notes`, `line_fit`, `problems` in the render summary and fix them; docs/COMPOSE_HARMONY.md, docs/COMPOSE_DEPTH.md. Old helpers retired 2026-11-12 (Стас: «к старым трекам не вернусь»): do not import wk.py / vibe.py / t10.py. Memory keeps principles, not recipes. See [[project-fable-audit-p130-p133]], [[feedback-night-shift-works]].

**2026-11-14 reinforcement (Стас):** the same STYLE as the previous track (ambient after ambient) does NOT mean the same effects and sounds. Every track starts from a blank page: do not look at earlier work for sounds, do not copy the previous score's helpers, instruments or chains; experiment, find new sounds, make each one more interesting and better. I broke this on 2026-11-13/14: asmr_sleep, cosmic_lofi and chem all reused Osiris piano / jRhodes / Ice Chime / experimental drones, the same sfz_from helper and the same reverb-pad-drone skeleton; chem copied dnb.py's drums. **How to apply:** before writing a score, do NOT open previous scores; list the sample libraries fresh, audition and pick 2-3 sources I have not used in the last tracks (fresh ledger), design a new processing chain, and say in the report what is new. Reading a score is allowed only to learn engine API, not to reuse sounds.
