---
name: project-compose-kit
description: How new tracks are made since 2026-10-17: short score.py on autodj.compose + one CLI run; gate calibration; what P103 still lacks
metadata:
  type: project
---

Since 2026-10-17 (P103 п.1-4, commit a0f8396 in /opt/autodj-mixer) a new track = `workspace/music/<track>/score.py` with `build(seed) -> Track` and `META`, run by
`cd /opt/autodj-mixer && python3 -m autodj.compose run <score.py> --seed N [--send]` (source claudeclaw .env first for --send). It renders inside a machine-wide slot (max 2), premasters, warm-masters, runs gates, applies one master-side fix (high shelf / low shelf / lower target) and prints a one-line JSON summary; `problems` left in it need a score change (hats, voice level), not another master. Example: `workspace/music/vyrub/score.py`. workspace/music is a local git repo (commit scores there); Стас decided 2026-10-17 to keep scores on disk only, no off-site remote for now. Next-stage plan is P104 in store/pending-improvements.md (stage A = ledger #4: Groove MIDI groove, harmony, role-based mixing).

Gate calibration: high_db is the 3-14 kHz band vs the whole mix; Sieben v1 -15.8 was «шик-шик», v2 -23.1 was fine, gate -19. Voice lines spoken into tape-stop gaps measure ~+6.5 dB lift by construction, so that voice flag is expected there.

Open (ledger #3): п.5 fingerprint registry / anti-repeat, п.6 assets to a shared read-only dir (paths still /home/cclaw via autodj/compose/assets.py env overrides), п.7 Hermes section in the mixer skill. Related: [[project-autodj-generation-2026-10]], [[feedback-music-warm-master]].
