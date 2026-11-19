---
name: A/B taste learning (P144)
description: 2026-11-18 shared preference log for Claw+Hermes, pair rules, round plan, R1 melodic house sent
type: project
---
Since 2026-11-18 Стас's taste is learned by blind A/B pairs (concept workspace/music/AB_LEARNING.md, tool autodj/compose/ab.py, commit 81ccc63).
- Log: /opt/autodj-mixer/shared/preference_log.jsonl (kinds pair/vote/single/pick, append-only, 664 group users, Hermes writes too); profile shared/preference_profile.json.
- Pair = ONE factor, same seed + same --title (same fresh picks), loudness matched, blind letters, gates clean; 30-50 s clips; 3 pairs per round, max 2 rounds/day; he answers "1B 2A 3=" (= no diff, 0 both bad, ! both good).
- Rule into engine after 3 wins in 2+ contexts with no loss; 3 ties = factor unimportant. Track hypothesis hit-rate.
- After each round: record votes (`python -m autodj.compose.ab vote R1 "..."`), report, proactively propose next 3 pairs (consolidate / develop / explore).
- R1 (melodic house, C#m 122, workspace/music/ab_r1_melodic_2026_11_18): p1 pad retrig(A)/held(B), p2 lead wurlitzer(A)/wa(B), p3 bass wa(A)/fashionbass(B). Awaiting his letters.
**Why:** his long verdicts were inconsistent, metrics weakly match his ear; one letter per one-factor pair is the cheapest honest signal.

**2026-11-18 correction (Стас on R1):** 3 one-factor pairs = near-identical, boring, and early on layers do not fit so nothing to choose. NEW: LADDER by stages like producers (1 hook, 2 beat, 3 bass, 4 pad/atmosphere, 5 transitions, 6 full 45-60 s segments A/B). Each stage = pick 1 of 4 clearly different variants of ONE new layer over the already chosen recipe (recipe.json); one letter answer, 0 = redo. Sections 10-11 of workspace/music/AB_LEARNING.md. Ladder dir workspace/music/ladder_melodic (hook_stage.py). Stage 1 sent: letters in shared log kind=pick stage=1 round L1.

**PAUSED 2026-11-18 evening (Stas: stop, continue maybe later): no new ladder rounds until he asks; stage 2 beat variants unanswered.**
