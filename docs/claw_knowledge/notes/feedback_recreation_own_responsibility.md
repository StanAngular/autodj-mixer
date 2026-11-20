---
name: feedback-recreation-own-responsibility
description: 2026-11-19 Стас: when recognising/recreating, do not copy the analyzer blindly; correct the melody by harmony and style so the result sounds good; rules for every future recognition/recreation
metadata:
  type: feedback
---
Стас 2026-11-19 (sax-in-parking reel De3UtoQRS4e): «если в лоб повторить, на выходе будет фигня; бери ответственность, логически додумывай, понимая стиль, делай небольшую корректировку по законам гармонии и приятности; используй это как правила для дальнейших распознаваний и воссозданий». Also: «сразу распознавай стиль» (Quadratic Helm had a light breakbeat, my recreation sounded indie pop).
**Rules (apply every time):**
1. Name the style first (genre, groove type e.g. 3+3+2 broken kick, mood) and keep every later choice inside it.
2. Analyzer notes are a draft: merge glitches <70 ms and same-pitch re-attacks; fold octave errors to the neighbour contour and the instrument's real range; snap out-of-key notes to the key (minor pentatonic first), keep chromatic notes only as short neighbours/trills or a leading tone; legato inside phrases; resolve the last phrase to the tonic if the clip just stops. Print every correction.
3. Pick the instrument by its real range; transpose the whole melody (not single notes) to fit it; never squeeze samples > 7 st.
4. Use real played samples (velocity layers, round robin) for short notes and played attack -> sustain for long ones; looped sustains alone sound «synthetic» (blind Gemini said so).
5. Space is part of the style (parking = long bright concrete reverb), add breaths/room tone.
6. End with musicality.py (chroma vs ref, Audiobox CE/PQ gap); blind Gemini is unreliable (it heard the sax reel as a «violin»).
Example: workspace/music/reel_De3UtoQRS4e/rec/rec.py.
**2026-11-20 follow-up:** Стас on Salt Line (breaks with sax): «сильно примитивно». Plan he set: he sends the next reference -> I recreate it (rules above) -> then a completely different new track built from what the recreation taught, «не в тупую»: musicality + interesting fresh sound. Primitive = thin: one 4-bar theme repeated, 4 sounds under it, simple chord loop reused (Emadd9-Cmaj7-Am7-B7sus4 already in 3 tracks). Next time: develop the theme (variation, counter-line, change of texture per section), richer arrangement, a harmony that is new.
**2026-11-20 rule for the next recreation + new track (Стас: «обрати внимание на стерео звучание и мягкость, точнее смягчённость всех слоёв»):** every layer, not just the mix, gets a stereo and softness check against the reference, per stem. Stereo: width (M/S side/mid by band: <150 Hz mono, 150-2k, >2k), L/R correlation, balance drift (no flicker), panorama of each stem, mono-fold loss. Softness: attack time (10-90 %), spectral centroid and share above 6 kHz, crest factor, saturation (harmonic distortion), HF step clicks. Then match the reference: round the attacks (2-8 ms fades), tilt the top down, tame the hat/snare transients, glue bus, M/S widen mids/highs only (stereo.steady / ms_widen / decorr), bass and kick mono. Report the per-layer table ref vs ours. Tools: autodj.compose.stereo (width_ratio, balance_stats, width_high), reftrack/blueprint.
