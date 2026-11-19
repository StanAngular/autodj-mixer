---
name: Harmony: new consonant by default
description: 2026-11-17 Стас switched new tracks to the P137 consonant harmony; old loop kept only on request
type: feedback
---
Стас 2026-11-17: «давай на новой гармонии поработаем, старую петлю не выкидывай, оставь, если я попрошу вернуть или сделать именно на ней; а так пока больше не будем её применять. Перерендер треков на джазовой гармонии не нужен.»
**How to apply:** новые треки: `chords.Plan.build(tonic, sections, home=<из C.idioms(mood)>, ...)` (palette="consonant" по умолчанию, P137, коммит после 7609b90); перед отправкой `tonal_notes` в сводке пусто. `kit.old_plan` / идиом `old_loop` только по прямой просьбе. Джаз (`palette="jazz"`) только по просьбе. Это заменяет правило 2026-11-13 «пока всё на старой петле».
