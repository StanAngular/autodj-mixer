---
name: SongEval + CMI-RM evaluators
description: 2026-11-15 Groove Intelligence (Кирилл): external musicality judges; SongEval installed, CMI-RM blocked by disk
type: reference
---
Кирилл 2026-11-15: этап «Groove Intelligence» после планирования решает, что менять в ритме; SongEval / CMI-RM проверяют, что общая музыкальность не упала. Автоотбор только после сверки с оценками Стаса.
- SongEval: ~/evaluators/SongEval, обёртка `workspace/music/ears/songeval.sh f.mp3 ...` (CPU, ~1 мин/трек). 5 осей 1-5. Обучен на песнях с вокалом, для инструменталов только гипотеза. Калибровка 2026-11-15: Harmattan (понравился) Musicality 2.89; breaks D (плохо) 2.73; Furnace Embers (не музыка) 2.28 = самый низкий по всем осям. Audiobox CE у Embers 5.79.
- Требует transformers 4.57.3 (на 5.x muq падает); torchvision должен быть +cpu сборкой. demucs/whisper/Audiobox после этого работают.
- CMI-RM УДАЛЁН 2026-11-15 по слову Стаса («Cmi rm удаляй»): калибровка показала ранжирование против его вердиктов (Harmattan 0.67 последний, breaks D 2.01 первый), грува не меряет, 5.5 ГБ диска и ~8 ГБ RAM. Репо, веса, MuQ-MuLan и cmirm.sh удалены; torchcodec не ставить (ломает загрузку).
- Вердикт по оценщикам (2026-11-15): SongEval = слабый сигнал (низкая оценка = послушать внимательнее), не судья и не гейт; Audiobox оставлен; настоящий судья = голоса Стаса, предложено собирать таблицу (трек, вердикт, метрики) и через ~10 треков смотреть, что предсказывает вкус. Грув меряют наши syncopation/rhythm_metrics, а не нейро-оценщики.
