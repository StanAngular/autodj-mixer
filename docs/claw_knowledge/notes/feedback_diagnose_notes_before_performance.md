---
name: feedback-diagnose-notes-before-performance
description: "When generated music sounds bad, check the notes (pitch range, scale, chords) before tuning groove/velocity -- learned 2026-10-07 on AutoDJ"
metadata:
  type: feedback
---

2026-10-07 (session af71f0d9): Стас called the psy trip-hop render "хрень, а не музыка". I first shipped groove/velocity fixes (P93/P96); he said it barely changed. The real cause was the notes: lead pitches computed up to MIDI 171 (337 of 477 notes above the MIDI range, heard as squeal), half the lead out of scale, voice leading shifting notes into foreign pitches, pad and bass changing chords at different times. Fixed as P97 (commit 0947f01 in /opt/autodj-mixer). Logged in friction.log 2026-10-08.

**Why:** performance polish on wrong notes is wasted work and burns Стас's patience; he judges by ear and doesn't read code.
**How to apply:** for any "sounds bad / no melody" complaint about generated audio, first dump the note data (pitch range within MIDI 0-127, notes in mode, chord tones on strong beats, pad/bass chord alignment), then mix/levels, and only then groove/humanization. Related: [[project-autodj-generation-2026-10]].
