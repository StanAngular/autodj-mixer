---
name: feedback-musicality-check-at-end
description: 2026-11-19 Стас «в конце надо оценивать музыкальность, её реально нет»: recreation DfsJYtGMwn3 v1 was noise; final musicality check before sending; what our checks can and cannot see
metadata:
  type: feedback
---
Стас 2026-11-19 on reel DfsJYtGMwn3 v1: «музыкальности реально нет, значит ты херню распознал и создал». Rule: evaluate musicality at the END, before sending; do not send on FAIL.
**Root causes found:** (1) Karoryfer black guitar `stac/` files are muted thumps with NO pitch (CQT peak D2/F2 for "c4"/"c5"); some `ord/` files are unreadable. Always pitch-test an instrument (render 2-3 notes, measure) before using it. (2) pyin on upright-bass stem turned the pizz attack glide into fake A1/G1/A#1 neighbours; the bass was one note. Check per-note pitch stability, not just the median.
**Tool:** workspace/music/musicality.py ours.wav [ref.wav]: key fit, harmonic flatness, chroma similarity to ref, Audiobox CE gap, blind Gemini 1-10.
**Calibration:** blind Gemini gave 8/10 to the noisy v1 (ref got 7): NOT a musicality judge, never trust it alone. key_fit is low for chromatic techno refs too (ref 0.24), so judge against the ref, not an absolute threshold. Chroma similarity to the ref and Audiobox CE gap were the signals that agreed with Стас.
