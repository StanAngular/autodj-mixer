---
name: feedback-no-clap
description: "2026-11-22 Стас: no clap by default in any track; it adds banality and makes most tracks worse; only on explicit request"
metadata:
  type: feedback
---

2026-11-22 (Reel Techno layer 4): «Clap бесполезный и опять банальности добавляет, зачем он? В большинстве треков он ухудшает восприятие. Отменяем. Запомни это.»
Earlier: Slate Harbor clap «острый, банальный», then «примитивный, забирает внимание»; Berlin Pulse rim instead of clap; Copper Rain clap smoothed.
**How to apply:** no clap (and no clap-like backbeat stand-in) in new tracks. Engine default since commit after 4346b2c: rhythm_profiles clap=False, drum_plan_v2 emits a clap only with profile(..., clap=True), genre cards have no clap layer. Add a clap only when Стас asks for it in that track. The backbeat function, if needed, goes to something with a job (a rim fill, a perc answer), not a 2-and-4 clap.
