---
name: feedback-music-sounds-90s
description: 2026-10-17 Стас's DJ friend: our tracks still sound primitive, "like the 90s"; Стас wants the engine to keep learning, not one-off fixes
metadata:
  type: feedback
---

2026-10-17: Стас relayed his DJ friend's verdict that the generated music "звучит как из 90-х", still primitive. Стас said it is very important that I get better at music and that learning must be an ongoing process (search where/how to learn, keep developing it).

2026-10-18 (session df570566): Стас said the output is still «зажатое», a single reference doesn't change much and I'm «на низком уровне» in how music is made. My honest diagnosis to him: I work from numbers, not hearing; the biggest jumps so far came from new sounds (W.A., Fishy Tech House) and found bugs (bass off-notes, dull master, «дудка»), not from references. That led to ledger #5: Lakh MIDI corpus knowledge ([[project-lakh-midi-library]]) and Stable Audio Open for missing samples ([[reference-stable-audio-open]]).

**Why:** grid-perfect drums, block chords and drum-machine/GM-like sources (LinnDrum, 707, plain saw synths) read as dated; one-off track fixes do not compound.
**How to apply:** improve the shared engine ([[project-compose-kit]], P104 in store/pending-improvements.md) rather than single tracks; prefer modern one-shots and Vital/VSCO over 80s/90s drum machines unless the style asks for them; learn from reference tracks Стас likes (stems via demucs in /opt/autodj-mixer/demix) and real-drummer grooves (Groove MIDI library in autodj/compose/groove.py).

2026-10-19: Стас: fus01 v2 "почти не отличается, хуже"; I applied knowledge selectively and treated "recreate" as "copy this track". He wants knowledge GENERALISED: new tracks should draw harmony/bass/drums/form from the corpus (Lakh per style), feel and levels from learned references, sounds from generators, and say which decision came from which source (decisions.json). Lesson: a Lakh bass line taken from another song must be refitted to our chords (rhythm + contour kept, pitches snapped to chord tones; beats on the root) or it rubs (14% clash before refit).
