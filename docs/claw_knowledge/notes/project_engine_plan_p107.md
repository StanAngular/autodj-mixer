---
name: project-engine-plan-p107
description: "ACTIVE music engine plan (P107..P109 + 5-step pipeline); 3 best tracks as of 2026-10-23 and why; checklist in workspace/music/ENGINE_PLAN.md, ledger #6"
metadata:
  node_type: memory
  type: project
  originSessionId: abc546af-b233-429d-92fa-387db33238b0
  modified: 2026-10-22T01:01:44.017Z
---

Стас (2026-10-19): "всё плохо, включая piano house". He wants MY engine (`/opt/autodj-mixer/autodj/compose`) to compose better, not outsourcing to Lyria/Suno; Gemini is a teacher, not the judge. He asked that the plan survive token limits and nightly /dream, so the source of truth is `workspace/music/ENGINE_PLAN.md` (git-tracked, detailed per-step log with EXP ids) + ledger #6 + `workspace/music/experiments/` (one dir per EXP, `log.jsonl`, `PIPELINE.md`). This memory only keeps the arc and the lessons; read ENGINE_PLAN.md for the current step.

Arc (all 2026-10-21/22, from session df570566):
- P107 stages 1-6 (focus, hook.py, genre harmony, bass.py, develop.py, teacher.py + style_guide.json): demo «математический алгоритм», no tension.
- P107b (Стас's own Gemini rules, source stas in style_guide): no planing, voice leading <=2 st, tension/release via sus/V7, bass-lead dialog, hook on 2-3 anchor notes. Demo 2 «Рассвет над мостом» = «явно лучше», but sounds = cliché presets.
- P108 (sound, CLAP dropped by him): own SFZ player sfz.py (jRhodes3d, Osiris piano, Karoryfer bass; bass libs an octave low -> auto octave + cents calibration in _tuning.json), alive.py. Blind audition: he picked live dry samples, alive.py NOT default; VSCO violin = sad, no background strings unless sadness is intended.
- P109 (his ChatGPT+Gemini TZ, workspace/music/TZ_chatgpt_gemini_2026-10-21.md): ideas.py hook families, experiment.py, blind A-E letters. Exp 1 lesson -> [[feedback-fragment-vs-full-track]]. Exp 3 tech house on W.A. samples -> section th1 -> closed: best = soft v2, «космос» v1 > v2, minimal-insert v3 worse than v2.
- 2026-10-22 night: new pipeline (PIPELINE.md) step 0 = 5 totally different 1-min tracks, he picks one; step 1 = 5 hooks on it; step 2 = variants inside the winner (one variable); step 3 = ~1 min section with full arrangement; step 4 = full track. Run: step 0 D deep_pluck (F minor 124) -> step 1 B pluck riff 3+3+2 -> step 3 section -> step 2 riff sound B (other pluck). Full tracks sent: «рифф-мутант» (constant acid/robot/metal/stretch distortion of the overlay, rhythm kept) and «толстый рифф + голос» (sound D thick, overlay -15%, low Ukrainian voice phrases about movement, peak-aligned, -6 dB to music). Chant variants for hook D (EXP-20261022-012821) were never answered. Awaiting his verdicts.

Lessons: Gemini's text critique of a score is half useful, half misread; its invented rules stay «proposed» and its library facts need checking (called Karoryfer Emily a cello). On blind A/B it has order bias (picks position 2) and disagrees with itself between rounds, inventing reasons -> ab_pick returns tie, only Стас's letter decides. Clash: a hook on b3 over a stab 9th = m9 rub; under a hook give the stab 1-3-7. Bass must be checked against the actually sounding chord (A under a Gm7 stab rubbed with Bb).

**Why:** earlier upgrades (Lakh, Stable Audio, copying references) gave no audible improvement; only his ear on blind letters has moved things.
**How to apply:** on any music request or "продолжай", open ENGINE_PLAN.md + PIPELINE.md first, continue the first unchecked step, log his letter in the EXP, tick boxes and commit. Related: [[feedback-music-micro-tricks]], [[feedback-music-sounds-90s]], [[reference-lyria-gemini-music]].

2026-10-22: the track builder (build_concept, CONCEPTS, name-salted hook seeds, used-hooks registry) now lives in the engine: /opt/autodj-mixer/autodj/compose/builder.py, registry shared/compose_used_hooks.json. workspace/music/step0/th5.py is a shim (sys.modules alias), so old scores and dt5/mh5 still work. Still open in P103 (ledger #3): assets to /srv/music-assets, «Генерация» section in the mixer SKILL for Hermes. The overlay composer (th_D_comp/compose3.py) and morph/thick FX are still in workspace.

2026-10-22 evening / 2026-10-23 night (session 9228b64f):
- Стас named the 3 best tracks so far: «Тек-хаус A: космос (минимал-основа)», «Deep techno: Гипнотический рифф», «Shimmer in the Deep». Common trait: one hypnotic base, a restrained overlay that grows through filter and arrangement, few FX, solid kick+bass. Use this as the bar for new sketches; they were also stitched into «Deep Journey Mix» (mix3/score.py, re-rendered from scores by stems, not an mp3 crossfade).
- Minimal melodic house C closed («не нужен»); deep techno kept as a separate experiment branch (ledger #6). New series started: cinematic electronica (Röyksopp / Moderat / Jon Hopkins), ledger #7, see [[project-cinematic-series-2026-10]].
- P110 (bass-hook builder crash fix), P111 (StanPo author, see [[feedback-stanpo-author]]), P112 (Gemini listener) applied, commit 4b9bbdd. Seed rule: [[feedback-seed-per-track]]. Gemini as listener: [[reference-gemini-listener]].
- Biggest musical gap per TZ_Opus55_plan_2026-10-23.md: the hook sounds the same all track (development only by filter/arrangement); harmony only diatonic 2-3 chords.

2026-10-23/24 (session 9228b64f): P113 (energy) + P114 (timbre guard) applied. References via demucs + learn.py: Gravity and Feeling (grooves in ~/samples/grooves/refs/; a full 7-min track OOMs demucs, split into 2-min chunks) -> 5 sketches each, judged far from the originals, see [[feedback-reference-likeness]]. Then th_wa5 (5 W.A.-only tech house) -> «Low Pulse» full + «Low Pulse X»; «Glass Steps» experimental indie house; lofi5 (5 slow lo-fi/minimal/exp. deep house) -> «Slow Minimal» full + 5 hooks, «Night Bus» full. His requests drifted toward experimental, broken, slow material, see [[feedback-music-micro-tricks]]. Open at session end: he will send a track to recreate via demucs on top-quality sounds (asked whether the hook melody may be copied if authored StanPo); an Opus 5.5 review asked for humanize/velocity/swing on Rhodes, vibes and plucks and an engine plan with no repeated patterns per track.
