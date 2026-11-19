---
name: project-fable-audit-p130-p133
description: 2026-11-12 Claude Fable audit of autodj.compose, patches P130-P133 applied (commit e36886c); what they add, how new tracks should use them, open verdicts
metadata:
  type: project
---

Стас asked Claude Fable 5.2 to audit the engine; it sent 4 patches (applied «Применяй все», commit e36886c): P130 mix graph (bus.py: Track.add key=/band=/bus=/send=/depth=, trk.follow, shared spaces, master "studio", premaster "clip"), P131 living synth (synth.py), P132 soundlab (soundlab.py, archive shared/soundlab.json with 12 seed sounds, `python -m autodj.compose.soundlab search|vote|list`), P133 depth report (depth.py: summary["depth"] / "depth_notes", docs/COMPOSE_DEPTH.md, demo docs/examples/living_demo.py, A/B env AUTODJ_DEMO_FLAT=1).

**Why:** Fable's diagnosis of «flat» music: one resampled recording for every note, clock-based sidechain, per-layer reverb, no measure of «new sound», pre-master tanh over everything.
**How to apply:** new tracks follow docs/COMPOSE_DEPTH.md: sounds from the lab after Стас's votes, `depth_notes` fixed like `problems`, old scores unchanged (Dub Saw re-render bit-identical). Open: Стас has not yet voted on the lab reels (lab_bass_reel_A-F, lab_lead_reel_A-F, files not sent to me) nor judged A/B (living vs flat sent 2026-11-12); examples/ is hermes-owned so the demo sits in docs/examples. See [[feedback-check-silent-layers]], [[reference-ears-audiobox]].
