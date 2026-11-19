---
name: project-lakh-midi-library
description: Lakh MIDI electronic corpus built 2026-10-19 into autodj.compose (progressions, bass lines, drums, tempo, part entry bars per style); ledger #5
metadata:
  type: project
---

Built 2026-10-19 (session 70c1d491, commit d9f1bbf in /opt/autodj-mixer, pushed) under jobwatch: 928 songs in 23 min, output `~/samples/lakh/patterns.json`, build code `autodj/compose/lakh.py` (per-file SIGALRM limit, per-group partial saves). A score can now pull progression, bass line, drum pattern and tempo for a style; each seed picks differently but only among frequent options. Cleanup on load: off-scale bass notes snapped to the score's mode, drum bars with the kick one 16th off dropped, doubled tempo halved.

Learned (reported to Стас): mostly minor, Fmaj7 next to the tonic almost everywhere (in A minor terms). House Fmaj7/Am7 + Esus4, bass «x..x..x...x...x.», drums enter bar 3, bass bar 10, lead bar 13; disco Am7-D7 (dorian), 8ths; eurodance 128-130, 8ths or gallop; trance 16ths/offbeat bass. Big beat has only 9 songs: seasoning, not a base. Synthpop dominates the count (511).

**Why:** Стас said single references don't lift the engine; a corpus gives note-level knowledge per genre ([[feedback-music-sounds-90s]]).
**How to apply:** use it in new scores via autodj.compose; next step per ledger #5 was a house/eurodance track on Lakh plus SAO samples for fus01 v2. Check `node dist/task-cli.js show 5` for current state. An uncommitted foreign test (muted layers) sits in test_compose.py: not mine, leave it out of commits unless Стас says otherwise.
