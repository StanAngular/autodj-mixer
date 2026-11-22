# Жанровые карточки (genres.py) и как с ними писать трек (для Claw и Hermes)

Что это: карточка жанра = из чего жанр сделан. BPM, нужные слои, папки звуков, ЗАПРЕЩЁННЫЕ семейства, запросы CLAP по ролям, профиль ритма, мастер по жанру. Карточки есть для всех стилей:
tech_house, house, deep, melodic, afro_house, garage, minimal, techno, downtempo, breaks, witch_house, ambient (алиасы: "tech house", "UK garage", "lo-fi" ...).

Порядок в партитуре:
1. `META["task"] = {"genre": "tech house", "style": "tech_house", "mood": "club"}` (genre даёт мастер по умолчанию и отчёт о палитре и похожести; style даёт ритм-профиль).
2. `c = genres.card("tech house")`; звуки: `genres.pick(c, "clap", rng, title, near=[kick])`, бочка `genres.pick_kick(c, "A", rng, title)` + `kicktune.retune`; бас и стабы идут через `tonal_ok` (soundgate + второй детектор высоты) ДО рендера.
3. Ритм: `rhythm_profiles.profile(...)`, `arrange.drum_plan_v2`, `rhythm_profiles.ensemble(trk, style, seed)`, `trk.align = "onset"`. Бас: `riffs.rolling_bass` (tech house) или `Plan.bass(kick=...)`.
4. Рендер: `python -m autodj.compose run score.py` (PYTHONPATH=/opt/autodj-mixer). Библиотека звуков для ВСЕХ пользователей: /home/cclaw/samples (у Hermes симлинк /home/hermes/samples; genres.py сам нормализует пути, env AUTODJ_SAMPLES меняет корень).
5. Мастер: tech_house и techno по карточке: target -10 LUFS, master studio, premaster clip knee -8, гейт лимитера 9 дБ. Остальные: -14, warm. Явные значения в META главнее.

Громкость: цель -9.5 LUFS при гейте лимитера 3 дБ невозможна для трека с резкой бочкой: авто-фикс мастера дважды опускает цель (это не баг цикла усиления, так вышло -20.7 LUFS в тесте). Либо мягче клиппер до лимитера (карточка это делает), либо цель выше.
Свежесть выбирает только внутри палитры жанра. Не делай подряд треки из одних и тех же звуков и оборотов (запрет повтора гармонии в движке уже включён).
Все числа карточек это гипотезы, подтверждённые слухом Стаса; tech house снят с двух его референсов (NO STATIC, DANGER).
