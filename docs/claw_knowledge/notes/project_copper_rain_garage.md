---
name: project-copper-rain-garage
description: "2026-11-21 Copper Rain (UK garage): first track on the full new stack (P147-P168 so far); lessons about pitch detectors, pluck choice, what was verified vs not heard"
metadata:
  type: project
---

2026-11-21 Copper Rain (UK garage), 130 BPM, F, 3:52, `workspace/music/copper_rain_2026_11_21/score.py`; sent with 8 per-layer clips. Built on: rhythm_profiles "garage" + arrange.drum_plan_v2 + microtiming v2 (`RP.ensemble`) + `trk.align="onset"` + chords.Plan(arc=) + lines.story + drumq/kicktune/CLAP picks. Checks: gates passed, musicality PASS (key_fit 0.81), rhythm checklist 5/6 ok (ohat accent contrast 1.3 dB warn). NOT heard by me; Стас's verdict pending.
**Lesson (bug found by the bad_sounds gate):** soundgate.measure and sfz.measure_keycenter both put CP80 `091-G6-F.flac` an octave low (79 vs real 91), so the hook was played -14 st; fix in the score = a second pitch opinion (yin) must agree with soundgate before a pluck/hook sample is used. The engine should do this check itself (not yet in the engine).
**Caption slip:** hook sample `b4mp.flac` is a Wurlitzer EP200 note (GregSullivan E-Pianos), not a pluck.
Single-send pattern: the last `send_stanpo.py` call of a batch prints nothing (happened twice); ask Стас if a clip is missing.

**Verdict 2026-11-21 (layer 6, bass sfz growlybass):** «полный фейл: ученик положил пластиковую линейку на край стола и дёргает, она вибрирует; иногда ненастроенная струна подбрынкивает». Measured: growlybass 1.5 kHz+ band -17.7 dB (the ruler twang; bass_pluck -70, fashionbass -45), pitch error p90 6.6 cents (bass_pluck 1). Replaced by `sfz:bass_pluck` (v2 sent). Logged in shared/layer_verdicts.jsonl; verdicts.py now holds INSTRUMENT verdicts (axes hf, err; measure_instrument; check_instrument); rule is `proposed` (warns) until Стас confirms.
**How to apply:** pick bass instruments only after `verdicts.check_instrument` and prefer low hf (< -40 dB above 1.5 kHz) + low pitch error; growlybass/growlybass_dirty not for bass roles.

**Final verdict 2026-11-21:** bass_pluck «существенно лучше», but the bass LINE «местами не очень сочетается» (melody of the bass vs the rest), which Стас reads as the general problem of over-simple, not musical enough writing. «На этом по этому треку стоп» (no more work on Copper Rain).
