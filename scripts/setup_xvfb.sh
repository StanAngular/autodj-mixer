#!/usr/bin/env bash
set -euo pipefail

# Установка Xvfb для headed-скрейпинга (Tunebat/Beatport через Playwright).
# Запустить один раз вручную перед первым xvfb-run:
#   bash scripts/setup_xvfb.sh

if command -v xvfb-run &>/dev/null; then
    echo "✓ xvfb-run уже установлен: $(command -v xvfb-run)"
else
    echo "→ xvfb-run не найден, устанавливаю Xvfb..."
    sudo apt-get install -y xvfb
    echo "✓ Xvfb установлен"
fi