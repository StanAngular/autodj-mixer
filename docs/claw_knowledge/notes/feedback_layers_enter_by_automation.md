---
name: Layers enter and leave by automation, not by switches
description: 2026-11-26 Стас on Low Cymbal Pulse: cymbals and beats switched in/out abruptly, cymbals without beats, changes too often, hard techno beats weak
type: feedback
---
Стас (Low Cymbal Pulse techno, 2026-11-26): «появление тарелки и битов не органичное, слой резко вводится и пропадает; тарелки без битов странно; слишком часто всё меняется; биты фигня».
**Why (my mistakes):** mk() sets step_env=True, so section levels are on/off steps at bar lines; my random 4-bar cymbal mask with a 0.4-bar fade = flicker every 4 bars; breakdowns kept the cymbals alone with no pulse; chords every 2 bars; «hard» inserts were the same grid with one driven kick, no rumble design.
**How to apply:**
- every layer enters/leaves by a curve over 4-16 bars: volume ramp + filter automation (zero-phase LP/HP bank crossfade, see hardtechno_demo/score.py filt_auto); all section levels 1, the score draws the curves;
- changes only on 8-bar phrase lines, bigger ones every 16 (research: something changes every 8 bars, elements fade in over 16-64 bars by volume/filter);
- melodic texture never alone without a pulse unless it is a deliberate breakdown with a filtered kick still present;
- harmony slower in techno (chord per 4 bars);
- hard techno drums 2025: ~145-155 BPM, TWO kicks: short distorted main kick on the beat + rumble kick (kick -> long dark reverb -> LP ~170 Hz -> drive, ducked by the main kick); offbeat hats, ride faded in, open hats in the peak, industrial metal hits, DJ high-pass on the kick in the build that snaps back on the drop. No clap.

2026-11-26 Low Pulse (techno, no cymbals) verdict: «ерунда, очень острые и не в попад, то ли cymbal то ли что-то похожее». Likely causes found in my code: pc_common.widen() builds a second side signal from np.roll(hp, 11 ms) = a flam/echo 11 ms after every transient when used on hats/percussion (off-grid, sharp); hats band 4.5-13 kHz with 16th ghost notes; metal hit on the offbeat. Rule: widen() only for sustained material (pads, stabs, cymbal textures), never on hats/drums (use a plain Haas/stereo sample pair or leave them mono-centred); no extra metal/ride-like sounds unless asked. Next: Стас sends samples for psy trance.
