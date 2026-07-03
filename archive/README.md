# archive/ — код вне рабочего потока (НЕ удалён, чтобы не терять наработки)

Сюда перемещено то, что НЕ вызывается ни orchestrate, ни run_pipeline, ни SKILL-потоком
(аудит Фазы 0, 2026-07). История git сохранена (git mv). Если что-то понадобилось —
`git mv archive/<f>.py .` и вернуть тест.

- mix_config*.py, yt_mix_config.py, v14_test_config.py — конфиги КОНКРЕТНЫХ старых миксов.
  Рабочие конфиги генерирует curation_bridge (mix_config_<name>.py) на лету.
- smart_mixer_orig.py — старая копия микшера (до рефакторинга).
- mix_analyzer_test.py — старый скрипт-тест в корне (актуальные тесты в tests/unit).
- run_mix3.py, redo_ann.py, gen_ann.py, run_annotations.py — одноразовые скрипты эпохи ручного потока.
- register_new_tracks.py — старая регистрация в каталог (заменена catalog_register.py).

НЕ переносились (живые/связанные): playwright_scraper.py (вызывается subprocess'ом из
curate_tracks; уйдёт при резке монолита в Фазе 3), brief_parser/genre_detector/
track_analyzer/enrich_metadata/source_check/run_preflight/repaint_transition (орфаны с
потенциалом — решение по ним в Фазе 2/3), scripts/, shared/catalog/ (живые утилиты).
