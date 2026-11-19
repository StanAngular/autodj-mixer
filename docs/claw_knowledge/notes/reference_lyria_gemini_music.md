---
name: reference-lyria-gemini-music
description: Google Lyria music models reachable with our GOOGLE_API_KEY (checked 2026-10-19) and prices; basis of plan P106
metadata:
  type: reference
---

`GET /v1beta/models` with the project GOOGLE_API_KEY lists `lyria-3-clip-preview` (~30 s, $0.04), `lyria-3-pro-preview` and `lyria-3.5` (full song with vocals/lyrics, 48 kHz, $0.08 per song; 3.5 released 2026-09-04), and `lyria-realtime-exp` (instrumental streaming over WebSocket, steerable: weighted prompts, BPM, scale, density, brightness). Docs: ai.google.dev/gemini-api/docs/music-generation and /realtime-music-generation. Not yet tested by a real call. Plan P106 in store/pending-improvements.md: Gemini as producer/critic + Lyria as sound source + per-genre verdict notebook. Related: [[feedback-music-sounds-90s]], [[reference-stable-audio-open]].
