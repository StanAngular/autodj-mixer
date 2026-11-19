---
name: feedback-long-jobs-watchdog
description: Стас 2026-10-19: every big/long task must be planned and supervised against hanging, with periodic stage reports so he can see it is alive
metadata:
  type: feedback
---

Стас (2026-10-19, after the Lakh MIDI build silently stalled and my waits kept getting cut): for big tasks, plan anti-hang control BEFORE starting and keep it during the run, using the standard supervisor approach, and send him periodic reports of which stage is done so he knows nothing is stuck.

**Why:** long jobs here die or hang silently (turn ends, 600 s tool timeout, a bad input file looping, OOM with >2 renders); he only sees silence.
**How to apply:**
- Run long jobs detached under `workspace/tools/jobwatch.py --name X --stall S --max M --report R --retries N -- cmd`: heartbeat = new log output, kill on stall/timeout, retry once, Telegram ▶️/⏳/✅/⚠️/❌ messages. State: `jobwatch.py --status X` (/tmp/jobwatch/X.json).
- Make the job itself hang-proof and resumable: per-item time limit (SIGALRM), progress line every N items, save partial results per stage (example: autodj/compose/lakh.py build).
- Never wait on a job with `pgrep -f <pattern>` inside the same shell command: the pattern matches the waiting shell itself and the wait never ends (happened 3 times on 2026-10-17/18). Poll a state/done file or `ps -C python3`.
- Publish intermediate results as they appear, not one summary at the end: 2026-10-18 ~23:08 Стас asked «почему промежуточные результаты не публикуешь» after ~20 min of silence while I debugged the Stable Audio decode step. Send a short status (scripts/notify.sh) at each stage and any demo the moment it exists.
- Planned but not built: the same watchdog for the bot's own long turns (pending, needs Стас's «применяй»).
Related: [[feedback-finish-background-in-turn]], [[feedback-check-inflight-turn-before-explaining]].
