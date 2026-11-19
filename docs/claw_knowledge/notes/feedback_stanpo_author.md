---
name: feedback-stanpo-author
description: "Стас 2026-10-22: every generated track is authored StanPo; title = «Name (style)», never «StanPo –» in the title"
metadata:
  type: feedback
---

Стас 2026-10-22: «Да, автор StanPo у всех. В заголовки не пиши StanPo, там пиши название и стиль». Names are invented in English. Enforced in the engine since P111 (commit 4b9bbdd): Telegram performer and mp3 ID3 artist = StanPo for all senders including Hermes; a leading «StanPo –» in a title is stripped.

**Why:** earlier tracks went out with «Клод» as the card author, and one had «StanPo –» baked into the title.
**How to apply:** title format «Gated Depths (deep techno)»; don't hand-set the author, let the engine do it; if sending outside the engine (old send scripts), check the card shows StanPo. Related: [[project-engine-plan-p107]].
