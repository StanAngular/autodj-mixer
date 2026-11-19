---
name: feedback-report-token-cost
description: 2026-11-13 Стас: after every created track report how many tokens/cost it took; if a lot, why and how to optimise without losing quality
metadata:
  type: feedback
---

Стас 2026-11-13: «после каждого создания трека говори, сколько токенов было потрачено; если много, то почему и как оптимизировать, но не в ущерб качеству».

**Why:** the session context is ~800k tokens, every tool call re-reads it (cache), so a track with 8-10 tool calls costs millions of cached tokens (~$1.5-2 per track at 2026-11-13 context size).
**How to apply:** at the end of each track reply add one line: tool calls, USD used this turn (from the budget line), main cost driver. Optimise by: batching render+measure+send in one command, fewer fix-and-rerender loops (check peaks/levels in the first render's summary), short command output, and suggesting /newchat when context >80%.
