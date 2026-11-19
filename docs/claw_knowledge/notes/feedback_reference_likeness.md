---
name: feedback-reference-likeness
description: Стас 2026-10-24 on Feeling/Gravity-like sketches — why they sounded far from the reference (tambourine, short notes, synth smell, missing «курлыканье» voice)
metadata:
  type: feedback
---
Стас on the reference-based sketches (Keinemusik/RY X «Feeling», Gravity): best were B muted harp and E string pulse, "but very far from the original". Causes he named, and what they were in code:
- background «бубен» in many tracks = the s10 organic/deep/melodic kits used VSCO **Tamb1-Shake** as "shaker" 16ths. Do not use a tambourine as a default shaker; reference hats/perc sit ~-27/-23 dB under the kick.
- "plays fast, sounds don't sustain like in the source" = hooks of 1-step notes; references use long tied notes and fewer onsets.
- "samples smell old-school synthy" = Vital presets (pads/bass/FM leads). Prefer W.A. shots (the kind used in the top-3 tracks) or live multisamples; synth timbres are wanted in ~1% of cases.
- "курлыканье", a sung warped voice in many references = a vocal vowel texture; s10.coo() renders it (stable vowel stretched, vibrato growing in, scoop from below, chorus/delay).
**Why:** these four, not harmony or groove, made the sketches sound unlike the references.
**How to apply:** for any reference-like work: no tambourine shaker, long notes, W.A./live sounds, consider a coo layer; check the summary gates before every send (a send went out at limiter 3.2 dB on 2026-10-24).

Follow-up 2026-10-24: v2 (same sketches moved to W.A. pad/bass + long notes + coo) was judged WORSE: «не стоило переделывать; на другие семплы оно уже не звучит; надо делать изначально всегда на лучших семплах — переделки потом не помогают». Rule: pick the final-quality sounds (W.A. / live, the top-3 kind) BEFORE the first sketch; never fix a weak sketch by swapping its sounds afterwards — start a new one instead.

2026-10-24 (weekly experiment run by hand): Стас: «всё ерунда, слышу паттерны создания треков схожие, схожие накладки — повторы»; Tide Glass «грязно, шумно звучит бас» = my tanh soft-clip «glue» on the whole mix (invented for Slow Minimal) saturates the sub -> never soft-clip the full mix, tame the kick layer instead; «мерцательный эффект топорный» = operators.gate -> voted -1 twice in the technique registry. Only Low Pulse X is a reference he likes; asked for 5 similar to it — similar character, but each with its own hook TYPE and sound, kit, key, tempo, techniques.

**2026-10-31 Dust Relay with a phone voice:** Стас (B sketch): «переходы с зависанием, пикалка телефонная — интересно, подмешай модем»; asked for a Ukrainian male voice saying «Ало / не чую / передзвоніть / ви не туди потрапили»; then «грубее и ниже, местами нервный, распад голоса когда зависает на букве, микро-паузы». Recipe: workspace/music/full_2026_10_31/phonevox.py (rough, micro_pauses at energy dips, freeze = grain loop that slows/crushes/dies, nervous = faster + pitch tremor + dropouts) on edge-tts uk-UA-OstapNeural pitch -24Hz, phone band 220-3300 Hz, level from the mix (-9 dB). Modem = synthesised answer tone + 300-baud FSK + training noise at hangs. Lessons: the verdict DB blocks sounds near rejected ones (his bad votes on SAO bass/bell blocked W.A. Pluck_07/Bass_Shot_9) -> add GOOD verdicts for sounds he liked in a sketch; master target -14.5 + premaster drive 1.0 cleared the HF step gate.
