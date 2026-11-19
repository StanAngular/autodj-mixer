---
name: Progress updates on long music jobs
description: Стас 2026-10-31 and 2026-11-02 complained twice: no interim results while renders run; send a notify after EVERY stage
type: feedback
---
Twice Стас had to ask «скинь промежуточный результат / почему ничего не скинул из этапов». **How to apply:** for any job longer than ~5 minutes (full tracks, several renders, research) call `scripts/notify.sh "этап: что готово, что дальше"` after each stage (render done, gates read, re-render started, measures done) and send finished files as soon as they pass gates, not at the end. A silent background render is not progress.
Tools from 2026-11-02 (workspace/music/ears/): abx.py = Meta Audiobox Aesthetics (CE enjoyment, CU usefulness, PC complexity, PQ quality; calibrated: Clay Path 7.4/7.9/5.8/7.8, Suno ref 7.1, Phone Line 4.9/6.9/4.0/7.1, Orbit PQ 6.6); arc.py = arrangement arc (loudness range, repetition vs 8/16 bars ago, longest unchanged run; Clay Path 7 dB / 0.77 / 23 bars, Haunted 6.8 dB / 0.54 / 39, Phone Line 3.2 / 0.85 / 71, Riff Under Glass 0.4 / 0.83 / 109). Target for a «interesting» 5-6 min track: loudness range >= 6 dB, same-as-8-bars-ago <= 0.7, unchanged run <= 32 bars, CE >= 7.
