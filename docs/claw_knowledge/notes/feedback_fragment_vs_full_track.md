---
name: feedback-fragment-vs-full-track
description: Experiment 1 lesson (2026-10-21): a hook liked in a 16 s fragment failed in the full track; held maj7 melody notes sound like wrong notes
metadata:
  type: feedback
---

Experiment 1 (EXP-20261021-195315-hook_ideas_s11): Стас first ranked A riff > B > C, re-listened and chose D (slow piano long line) as best hook, A as groove, C arp as transition. In the full track (workspace/music/p109) D was «фигня, как любитель впервые за пианино, местами не попадает»; C too short; the tambourine on 2 and 4 all the time was superfluous. Gemini had ranked D first in the fragment too, so neither his nor Gemini's fragment pick predicts the full track.

Cause found in the notes, not the performance: D held E for up to 22 sixteenths over Fmaj7 (a maj7 is a semitone above the root). The clash gate treats maj7 as fine, so nothing flagged it. Fixed with harmony.stable_tone + long_line (held notes only 3rd/5th/b7 with no semitone neighbour in the chord, suspensions resolve with the chord).

**Why:** fragment tests are cheap but fool both the human and Gemini; a «legal» chord tone can still sound wrong when held.
**How to apply:** before a full track, test the chosen idea in a 30-60 s section with the full arrangement; check held melody notes with stable_tone; no constant tambourine backbeat. Related: [[project-engine-plan-p107]], [[feedback-diagnose-notes-before-performance]].

2026-11-27 Night Engine: Стас twice got a «different track» when he asked for the FULL version of the 1:33 sketch (v1 swapped leads/pads/arp/acid; v2 kept the sounds but rewrote the arrangement). Diagnosis: no code lock - my scores pin their loops by path, fresh.pick/hook registry never ran. The cause is my own habit from «fresh every track / blank page» being applied to a full version. RULE: a request for the full version of a sketch = copy the sketch's own score/config, keep seed, sounds, layer roles, sound-to-section mapping and groove; only (a) lengthen sections by repeating its phrases, (b) add the transitions asked for. Never re-pick or re-arrange. Verify before sending: the full track's first 90 s must match the sketch (compare chroma + spectral envelope of sketch vs full intro/drop), and say so in the report.
