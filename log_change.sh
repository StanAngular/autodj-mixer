#!/bin/bash
# log_change.sh — добавить запись в CHANGELOG.md
# Использование: ./log_change.sh <Категория> <Agent> <описание> [причина]
# Пример: ./log_change.sh fix_ht Hermes "новый порог для BPM 200+" "hardcore треки отваливались"
# Категории: fix_ht, warp, mixer, analyzer, pipeline, infra, bug

CATEGORY="$1"
AGENT="$2"
DESCRIPTION="$3"
REASON="${4:-}"

if [ -z "$CATEGORY" ] || [ -z "$AGENT" ] || [ -z "$DESCRIPTION" ]; then
    echo "Usage: $0 <Категория> <Agent> <описание> [причина]"
    echo "Пример: $0 bug Hermes \"fix: shift slice\" \"отрицательный shift ломал кроссфейд\""
    exit 1
fi

CHANGELOG="$(dirname "$0")/CHANGELOG.md"
DATE=$(date '+%Y-%m-%d %H:%M')
LINE="### [$CATEGORY] $AGENT — $DATE: $DESCRIPTION"
[ -n "$REASON" ] && LINE="$LINE | причина: $REASON"

echo "" >> "$CHANGELOG"
echo "$LINE" >> "$CHANGELOG"
echo "✅ Записано: $LINE"