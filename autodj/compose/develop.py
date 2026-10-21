"""Micro-development (P107 stage 5; Gemini teacher: «8 тактов без изменений — вечность», «каждый инструмент дышит»).
Two tools:
- micro_plan: exactly ONE small event per 4-bar block (a perc in/out, an echo throw, a hat opening, a fill...), never
  the same event twice in a row and no fixed cycle; the score decides what each event name does;
- timbre motion inside a layer without touching its level: `breathe` (filter opens/closes on a slow lfo with a
  per-track period and phase) and `phrase_send` (an echo send that grows toward the end of each phrase)."""
import numpy as np
from .core import sweep, rms

MENU = ("perc_in", "perc_out", "echo_throw", "hat_open", "ghost_fill", "filter_lift", "reverse", "drop_beat")

def micro_plan(rng, bars, menu=MENU, every=4, start=0):
    """{bar: event}: the event lands in the LAST bar of each `every`-bar block (it leads into the next phrase)"""
    plan, last = {}, []
    for b0 in range(start, bars, every):
        bar = min(bars - 1, b0 + every - 1)
        c = [m for m in menu if m not in last[-1:] and (len(last) < 3 or [m] + last[-2:] != last[-3:])]
        ev = str(rng.choice(c or list(menu))); plan[bar] = ev; last.append(ev)
    return plan

def breathe(trk, x, cuts=(1500, 3000, 6000, 12000), period_bars=None, lo=.35, hi=1.0, rng=None):
    """the layer's tone moves (low-pass opens and closes) on a slow lfo; the RMS is put back so the level does not pump"""
    rng = rng or trk.rng; per = period_bars or int(rng.choice([8, 16, 32])); ph = float(rng.uniform(0, 1))
    c = lo + (hi - lo) * trk.lfo(per, ph)
    y = sweep(x, cuts, c, sr=trk.sr)
    return (y * (rms(x) / (rms(y) + 1e-12))).astype(np.float32)

def phrase_curve(trk, period_bars=4, power=2.0):
    """0 at the start of each phrase -> 1 at its end (per sample, (n,1))"""
    f = (trk.tt / (period_bars * trk.BAR)) % 1.0
    return (f ** power).astype(np.float32)[:, None]

def phrase_send(trk, x, delay_steps=3, fb=.35, period_bars=4, max_wet=.35, taps=4):
    """dotted/odd-step echo whose send grows toward each phrase end (the tail blooms into the next phrase)"""
    send = x * (max_wet * phrase_curve(trk, period_bars)); d = int(round(delay_steps * trk.S16 * trk.sr)); wet = np.zeros_like(x)
    for k in range(1, taps + 1):
        if k * d >= len(x): break
        g = fb ** (k - 1); src = send[:len(x) - k * d]
        if k % 2: wet[k * d:, 0] += src[:, 1] * g; wet[k * d:, 1] += src[:, 0] * g   # ping-pong
        else: wet[k * d:] += src * g
    return (x + wet).astype(np.float32)
