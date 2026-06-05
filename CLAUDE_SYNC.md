# ClaudeClaw — инструкция по синхронизации

Актуальная версия скилла по DJ миксам — в корне репозитория:
**`/opt/autodj-mixer/SKILL.md`**

## Что делать перед каждым миксом

```bash
# 1. Проверить обновления
cd /opt/autodj-mixer
git fetch origin
git log HEAD..origin/main --oneline

# 2. Если есть новые коммиты — принять
git pull origin main

# 3. Прочитать актуальный скилл
cat /opt/autodj-mixer/SKILL.md
```

## Что делать после изменений кода

1. Обновить `/opt/autodj-mixer/SKILL.md` если в нём есть устаревшая информация
2. Закоммитить **все связанные файлы вместе**:
   ```bash
   git add smart_mixer.py mix_analyzer.py run_pipeline.py mix_validator.py SKILL.md
   git commit -m "fix: описание изменения"
   git push origin main
   ```

## Твой скилл mixer

Обнови `~/.claude/skills/mixer/SKILL.md` до такого содержания:

```markdown
---
name: mixer
description: "DJ mix automation — каноничный скилл в репозитории"
---

# Mixer — Automated DJ Mix

**Source of truth:** `/opt/autodj-mixer/SKILL.md`

Перед любым миксом читать этот файл через terminal: `cat /opt/autodj-mixer/SKILL.md`

При изменениях кода — обновлять `/opt/autodj-mixer/SKILL.md` и коммитить вместе с кодом.
```

## Что проверять

| Проверка | Команда |
|----------|---------|
| Новые коммиты | `git log HEAD..origin/main --oneline` |
| Diff smart_mixer.py | `git diff HEAD~1 -- smart_mixer.py` |
| fix_ht версия | `from smart_mixer import load_dbeats, fix_ht, calc_bpm, SR; db=load_dbeats('ann/...', SR); dbf,bpm=fix_ht(db.copy(), calc_bpm(db, SR)); print(f'{len(db)}→{len(dbf)}')` |
| Статус | `git status` |
