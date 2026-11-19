---
name: No left/right flicker
description: Стас 2026-10-25: never pan layers ear to ear (autopan, pingpong, alternating pan on hits)
type: feedback
---
Стас: «больше не делай мерцание правый левый канал». Источники в движке: `fx.autopan` на хуке в `builder.build_concept` (всегда включён), `O.pingpong`, чередование pan=(-.35,.35) на ударах перкуссии.
**How to apply:** в скорах глушить `fx.autopan = lambda trk, x, *a, **k: x`, pan=0 для сыгранных ударов, не брать PINGPONG/GATE. Шаблон: `workspace/music/iron2/iron2.py`. Ломаный ритм в клубных треках только как переходы (такты 7/15/23/27/39), бочка в остальном прямая.
