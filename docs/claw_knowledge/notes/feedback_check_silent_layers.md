---
name: feedback-check-silent-layers
description: 2026-11-11 15 tracks went out with silent drums/bass/voice; after every render check *_raw.json layers_db for None before sending
metadata:
  type: feedback
---

2026-11-11 Стас: «hollow tape без битов, нет ударных вообще, проверь». Cause: my helper base() in workspace/music/vibe3/vibe.py called trk.sections with an empty dict, and Track.add() without env= takes the section level (0.0 for unnamed layers), so kick, snare, hats, bass, voice rendered silent. Gates do not catch a silent layer. 15 tracks were sent like that (Glass Hours, Hollow Tape, Choir of One, 5 Hollow dance, 5 Glass, Карфаген I/II, Hollow + Beats).

**Why:** I reported drums and voice that nobody could hear; Стас noticed by ear.
**How to apply:** after every render read `<name>_raw.json` → `layers_db`; any None for a layer the score adds = bug, do not send. When using trk.sections with partial dicts, every layer needs an explicit env or a section value. Fixed with `AllOn` dict in vibe.base. See [[feedback-progress-updates]].
