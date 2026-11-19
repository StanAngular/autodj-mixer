---
name: feedback-music-warm-master
description: "Стас wants generated tracks soft/warm: tame 2.5-5 kHz and the top; use workspace/music/common/master_warm.py by default (2026-10-14)"
metadata:
  type: feedback
---

2026-10-14: after the deep house / indie arena track Стас said it sounds high-quality but "остренько", asked to soften it "как будто эквалайзер настроить", then "всё, что в высоком, ещё на 15% тише".

**Why:** he listens for comfort over long tracks; bright hats/presence tire him even when the mix is clean.
**How to apply:** master every AutoDJ render with `workspace/music/common/master_warm.py` (presence -3 dB @3.3k, -2 dB @6.5k, shelf -1.4 dB @4.5k, -2.5 dB @10k, slow glue, limiter -2.5 dB, body RMS about -12). Keep melodic parts out of high registers (his recurring "пиликает" complaint) and do not stack layers ("каша"). Related: [[project-autodj-generation-2026-10]].

(Updated 2026-10-17: scope.) For tracks built from one of Стас's references (`reftrack.py`), brightness and loudness come from that reference, set a bit warmer/quieter, not from these fixed numbers: the refs measured brighter and louder than master_warm, which made our versions dull. Warm master stays the default for everything else. Related: [[project-music-learning-loop]].

2026-10-17: Стас said the Lasha remix v8 was «глуховатой всю песню» — the warm master's presence/top cuts. For club tracks and remixes use `META["master"]="club"` (no presence cut, +1.5 dB air shelf) and a high_db gate around -11..-13; keep the warm master for calm/meditative tracks.
Also: the automatic "high" fix (high-shelf cut when 3-14 kHz is over the gate) silently dulled bright club mixes (piano house: -9.4 -> -13.1 dB). For club/remix tracks set `META["gates"]["high_db"]` near -8.5 so only real harshness is cut; piano house v2 sent at -9.2 dB.
