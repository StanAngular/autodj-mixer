---
name: feedback-music-artifact-causes
description: "When Стас names a stray sound («дудка», щелчки, глюки на M:SS, хрип), the causes found so far (Oct 2026); check these before re-mixing"
metadata:
  node_type: memory
  type: feedback
  originSessionId: ebd9a313-f5ed-4e6b-a2c8-6c2872485ad7
  modified: 2026-10-18T01:01:47.580Z
---

Стас reports artifacts by ear and often with a timestamp; Gemini usually misses them (see [[project-music-learning-loop]]). Causes confirmed so far:
- **«Дудка» from the start** (Lasha piano house v2, 2026-10-17): a 700 Hz sine click added on every bass note "for small speakers" was a pitched, off-key tone. Use a pitchless noise click; avoid tonal percussion samples in keyed tracks.
- **Strong clicks** (house v3 -> v4, 2026-10-17): a clap of 4 layers slightly offset in time = flam; a kick transposed >2 semitones to hit the key root clicks in the attack (keep `tune_kick` shifts small, pick a kick already near the key); hard W.A. closed hats above 13 kHz.
- **«Глюки» at 2:32 / 3:52** (house v3): drum fills taken from a real drummer (Groove MIDI) and mapped onto pack percussion became a scatter of random hits. With pack samples use a plain build fill: kick on beats 1-2, then snare 8ths -> 16ths rising into the downbeat.
- **«Бах-бах», хрип, завал, accordion dirt:** see [[project-autodj-generation-2026-10]] (kick click, saturation above 0 dBFS, <60 Hz energy) and the Lasha v7 note in [[project-music-learning-loop]] (time-stretched stems).
- **«Пережал/переобрезал», dull top:** too much drum-bus saturation (9 dB -> 5), hard compressors, and the automatic high-shelf fix; see [[feedback-music-warm-master]].
- **«Жёсткое пианино» inside a gated pad (Gated Depths 2:04, 2026-10-22):** when the gate opened up, the pad sample re-triggered its attack every bar. Fix: mute the gated pad there and swell a different soft pad.

**Why:** each of these took a full render round to find; the same mistakes recur across tracks.
**How to apply:** when he flags a sound, solo the layer at that second and check this list first; name the exact cause in the reply (he accepted that well). When he says he likes an earlier version best (2026-10-17: «больше нравится 3 версия» of the Lasha house remix), refine that version, don't start a new one.

2026-11-24 Tape Memory: «касета тянется, хрипит» = flutter ~80 cents at 7.3 Hz (displacement amplitude not converted to pitch), sample-rate crush + 10-bit (aliasing grit), and two differently wowed copies of one part playing at once (comb/flanging). Fix that worked in the full track: wow in CENTS (3-12, slow 0.13-0.45 Hz, flutter <= 2), no crush/bits, wear = zero-phase LP bank blended in phase on ONE signal, then one wow; ghost reverse in with equal-power crossfade.
