---
name: feedback-seed-per-track
description: "Стас 2026-10-22: one seed only for variations of ONE track; every new track/sketch gets its own seed; hook registry blocks repeats"
metadata:
  type: feedback
---

Стас 2026-10-22, after deep techno sketch D came out with the same riff rhythm as tech house track D: «тот же сид нужен только для вариаций одного трека, а так должен быть разный». He also asked to find the cause of any repeat he did not request.

Cause then: all step-0 sketches were rendered with one shared seed, plus the same W.A. pluck and a similar acid chain. Fixes in the engine: `run.py` derives the seed from the track name when `--seed` is omitted; each concept in `autodj/compose/builder.py` salts its hook seed with its name; the used-hooks registry `shared/compose_used_hooks.json` (seen by Hermes too, also covers bass hooks since P110) re-picks a hook whose rhythm another track already used, unless a repeat is asked for explicitly.

**Why:** "every track is its own story" is his standing rule; a hidden shared seed silently broke it.
**How to apply:** pass the same explicit `--seed` only when re-rendering or varying one track. If he hears a repeat, check seed, sample choice and FX chain first. Related: [[project-engine-plan-p107]], [[feedback-music-micro-tricks]].
