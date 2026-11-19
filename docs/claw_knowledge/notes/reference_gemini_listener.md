---
name: reference-gemini-listener
description: "Which Gemini model listens to our renders (gemini-3.8-flash since 2026-10-22, P112) and how far its hearing can be trusted"
metadata:
  type: reference
---

Since 2026-10-22 (P112) the engine's Gemini listener tries `gemini-3.8-flash` first, with `gemini-3-flash-preview` and `gemini-2.5-flash` as fallbacks. Comparison on Gated Depths v2 with known section times: 3-flash-preview invented a kick dropout every 15 s (source of earlier «made-up reasons»); 3.8-flash hit most entries within ~2 s but put the break 17 s early and misnamed layers; 3.1-pro hit a quota limit. Even 3.8 invented «303 slides» on the acid hooks and showed position bias on blind A-E. Full outputs: workspace/music/gemini_model_test_2026-10-23.txt.

**How to apply:** Gemini gives hypotheses and sound ideas only (its useful ones: tape saturation on drum bus, kick-ducked noise bed, small echoed perc clicks). Never gate or reject a render on its section timings; the engine knows its own timeline. Loudness, spectrum, mono-bass are measured in Python. Only Стас's letter decides. Related: [[project-engine-plan-p107]], [[reference-lyria-gemini-music]].
