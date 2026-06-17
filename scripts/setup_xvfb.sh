#!/usr/bin/env bash
# Устанавливает Xvfb для headed-скрейпинга (Tunebat/Beatport), если он отсутствует.
# Запускать ОСОЗНАННО один раз (нужен sudo). Скрипт НЕ вызывается автоматически.
set -euo pipefail

if command -v xvfb-run >/dev/null 2>&1; then
  echo "✓ xvfb-run уже установлен: $(command -v xvfb-run)"
  exit 0
fi

echo "xvfb-run не найден — устанавливаю Xvfb (нужен sudo)…"
sudo apt-get update
sudo apt-get install -y xvfb

echo ""
echo "✓ Готово. Теперь запускай curate ПОД xvfb, чтобы заработал Tunebat/Beatport:"
echo "    xvfb-run --auto-servernum python3 curate_tracks.py --config examples/curation_brief.example.json"
