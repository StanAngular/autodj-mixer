---
name: feedback-slate-harbor-keys-clap
description: "2026-11-21 Slate Harbor: per-layer verdicts. sfz piano_natural = worst sound, sharp banal clap rejected; softened clap + rolled Pianet chords with a topline got «лучше»"
metadata:
  type: feedback
---

2026-11-21, Slate Harbor (first track on P147-P152 rules), Стас listened per layer (8 clips of ~10 s, normalized, sample name in the title):
- **clap** (K04DHit-02): «очень острый, резкий, глупый, банальный». Fix that got «лучше»: Linn LM-2 clap, low-passed 4.5 kHz, 4 ms attack, short smear; pattern not a flat 2+4 everywhere (only beat 2 in home1, soft ghost before the bar, none in break).
- **keys** (sfz piano_natural): «самое ужасное звучание, мелодия плохая, игра примитивная банальная». Fix: Hohner Pianet, chords rolled bottom to top over ~3 steps, held to chord end, one soft re-touch, top voice = L.topline (a slow melody of its own); a stereo piano must be folded to mono (steady wet=0), decorrelation made the L/R swing by pitch (±6 dB).
- Kick, hats, ohat, perc, bass, hook: «небольшой прогресс», left as they were.

**Why:** block-hit staccato chords + a bright clap on every 2 and 4 read as banal; he hears the layer, not the metric.
**How to apply:** send per-layer clips early (stems_run.py --clips, then loudnorm each clip, title = layer + sample name) and ask him to name the bad ones; replace only those. Check the clap's brightness and the keys' comping pattern BEFORE the first send. Pin the sounds of the chosen sketch when re-rendering (rng order shifts every pick).

**Update 2026-11-21 (later): kick and clap of v2.** «Kick сильно бьёт по мозгам, острый и резкий, непонятно почему втупую лупит постоянно» (CYCdh_Kurz07-Kick03 retuned +2 st, straight 4/4 on every bar of every section, 1:1 same hit). Clap «теперь лучше», но примитивный и «пользы от него кроме как забирает внимание нет». Стас: **запомнить на будущее, в этом треке НЕ исправлять.**
**How to apply (new tracks):** a kick is not on every beat of every bar by default: it enters, drops, changes density with the section and has a soft, round attack (check centroid/click before sending); a clap/backbeat needs a job (rhythmic role, section change) or is left out; judge both by what they DO in the arrangement, not only by timbre.

**2026-11-21 A/B clap alignment:** A (file start on the beat, attack 24.6 ms late) vs B (attack on the beat, `place(align="onset")`): Стас «вариант B вроде более нормальном месте стоит». Logged as R2-p1 in shared/preference_log.jsonl. **How to apply:** new scores set `trk.align = "onset"` (P163); old scores keep the old default.
