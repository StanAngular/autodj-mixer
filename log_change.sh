#!/bin/bash
# Quick helper to update changelog
APPEND="### [mixer] Hermes — $(date '+%Y-%m-%d %H:%M')
smart_mixer.py — fixes from v2 analyzer findings:
  • blend→ramp boundary: 10ms crossfade между warp_extra и ramp_result
    (раньше был np.concatenate — жёсткая склейка давала 5 микрозапинов)
  • Bass polarity: 5-точечный weighted consensus (была 1 точка в центре)
  • Kick band (60-120Hz) отдельная проверка polarity

### [analyzer] Hermes — $(date '+%Y-%m-%d %H:%M')
  • boundary_glitch: spike > 1.8x, gradient > 5x (было 1.5 и 3)
  • stutter: diff_ratio < 0.001, 20ms windows, 3+ consecutive
  • threshold tweaks for v2 stability
"

echo "$APPEND" >> /opt/autodj-mixer/CHANGELOG.md
echo "Updated changelog"
