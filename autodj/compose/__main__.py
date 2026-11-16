import sys
from .run import main
_s = main()
sys.exit(3 if isinstance(_s, dict) and _s.get("gate_failed") else 0)         # 2026-11-16: a hard gate (silent layer) fails the command, the mp3 and summary are still written
