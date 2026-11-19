---
name: feedback-music-micro-tricks
description: "Стас's tech house notes 2026-10-21/22: swell+DJ dip once, never reuse a signature trick; broken rhythm only short; clap/open hat soft; FX deep and dark, not pings"
metadata:
  node_type: memory
  type: feedback
  originSessionId: abc546af-b233-429d-92fa-387db33238b0
  modified: 2026-10-22T01:01:52.226Z
---

From the tech house session 2026-10-21/22 (session df570566):
- A new top layer may grow in with a swell and, near full level, one «диджейский финт» (whole mix dips for a beat, back on the downbeat). He liked it in th1, but for the next track said: don't copy the fader dip, use other micro tricks (kick skips a beat + reversed note, echo throws at phrase ends, one stutter, octave lift at the end). Rule: no signature trick repeated from track to track or every 16 bars.
- Broken-rhythm passages are interesting only as short (1-bar) inserts; long ones break the dance groove.
- Clap and open hat get «навязчивые» over a whole track even at -15%: keep them soft, not constant. No constant tambourine.
- Morse-like pings and lasers = banal. Wanted: dark, deep, robotic sounds «прорывается из глубины», not bright or sharp.
- Distorting an overlay (acid/robot/stretched) is fine as long as its rhythmic pattern stays readable.
- Spoken voice inserts: align the loud peak of the first syllable to the beat (late syllables sounded off), keep ~6 dB under the music, compress before the mix. Earlier voice that "didn't sit clearly" was removed entirely.

**Why:** these were his direct corrections on rendered tracks; repeating a liked trick made it a cliché for him.
**How to apply:** check this list before arranging a tech house/techno track; vary micro tricks per track. Overrides the 2026-10-17 «no fade-ins» note only for single top-layer entries he asked to swell. Related: [[feedback-music-transitions-pullback]], [[project-engine-plan-p107]].

2026-10-22: Стас asked that overlay alternation be COMPOSED, not DJ-faded: per bar decide which notes/syllables each overlay plays (relay half-bar handoff, question-answer, mirror, weave into gaps, ghost echo, drone on a tone stable over all its bars). Implementation: workspace/music/th_D_comp/compose3.py. Also found: ideas.riff put an out-of-key E on Db when the root did not fit the range (fixed 2026-10-22, all earlier track-D riffs had it).

2026-10-22: track D closed — «неплохо, прогресс есть, качество растёт», but too many FX/tricks for a final track: dose them. Kick choice: some W.A. kicks carry heavy sub (limiter 4+ dB) and some make the track quiet, so measure every kick candidate on the track itself; do NOT keep a fixed «preferred kicks» list (2026-11-12: the same 4 kicks sat in 9-12 projects each, Стас heard it as a drum template). Pick per track with `fresh.pick`.


Seed rule moved to [[feedback-seed-per-track]] (2026-10-23).

2026-10-23/24 (session 9228b64f, experimental branch): «ударные у тебя лупят всегда» — for experimental/indie/lo-fi tracks vary the kick per phrase (straight 4/4 only as contrast, broken patterns, half-time in the deep part, off-grid hits, 3/16 percussion cycles). Broken passages stay short (2-4 bar inserts used in Night Bus, verdict pending) so the dance count survives; inside them the hook plays in the gaps the broken kick leaves (drums ask, melody answers). A layer that pops in abruptly (his note at 0:15) must grow in over a bar. The «телефон» band-pass works best right before a drum entry.

2026-10-24: Стас liked **Low Pulse X** (thw_pulse_x/score.py) — «тема с экспериментами имеет потенциал». What it had: the liked Low Pulse base kept intact (same riff/kit/seed), drums PLAYED (kick pattern changes per phrase, straight only as contrast, off-grid kicks, ghost rim, 32nd hat rolls, 3-step perc polymeter, phrase-end fills) and experimental moves used once or twice each (granular freeze, reversed riff echo, riff displaced 3/16 for 8 bars, 2-bar sample-rate crush, riff an octave down in the deep part, telephone right before the peak's drums, 1-bar 16th L/R ping-pong). Others of that day (Glass Steps, Slow Minimal, Night Bus, Uncertainty): «надо ещё подумать». He wants experiments made periodically from now on.
