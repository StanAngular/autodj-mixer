#!/usr/bin/env python3
"""
synthvoice.py — G4a: собственные СИНТ-ГОЛОСА вместо GM-пресетов FluidSynth.

Диагноз (отчёт по New Age Techno): все мелодические партии играли GM-патчами —
`pan_flute #76` («сопілки»), `synth_pad_choir #92`, `sawtooth_lead #81`,
`synth_bass_1 #38`. Это пресеты стандарта General MIDI 1991 года: одна зацикленная
волна, статичный тембр, ноль движения. Никакая аранжировка их не спасёт.

Важное наблюдение по live-coding (dj_dave / Strudel): её лид — НЕ сэмпл и НЕ VST,
а встроенный синт: `.sound("supersaw").detune(1).distort(1).lpf(slider(...))`.
То есть современный техно-тембр = supersaw + расстройка + драйв + ДВИЖУЩИЙСЯ фильтр.
Всё это у нас уже есть в synthcore — не хватало только маршрутизации.

Голоса:
  supersaw — 7 расстроенных пил, фильтр-огибающая на ноту, драйв (лид/пад-стэк);
  acid     — TB-303: пила + резонансный свип (басы/секвенции);
  sub      — синус+пила, чистый низ (саб-бас);
  pad      — расстроенный стэк с мягкой атакой и открытым фильтром;
  pluck    — короткая атака, быстрый спад фильтра (арпеджио/стаккато).

Ключ к «живости»: velocity управляет не только громкостью, но и ЯРКОСТЬЮ (cutoff) —
как на железе. Тихая нота звучит темнее, громкая — открытее.

Формат событий тот же, что у GM-рендерера: [(время_сек, midi_note, velocity, длит_сек)].
"""
from __future__ import annotations

import numpy as np

from .synthcore import (SR_DEFAULT, adsr, lpf, midi_to_hz, mono_to_stereo,
                        sawtooth_bl, sine_wave, square_bl, supersaw)

VOICES = ("supersaw", "acid", "sub", "pad", "pluck", "square")


def _drive(x: np.ndarray, amount: float) -> np.ndarray:
    """Мягкое насыщение (tanh). amount 0..1. Чистая."""
    if amount <= 0:
        return x
    k = 1.0 + 12.0 * amount
    return (np.tanh(x * k) / np.tanh(k)).astype(np.float32)


def _brightness(velocity: int, base_hz: float, span: float = 3.5) -> float:
    """velocity → cutoff: тихая нота темнее, громкая ярче (как на железе). Чистая."""
    v = max(1, min(127, int(velocity))) / 127.0
    return float(base_hz * (0.35 + span * v * v))


def render_voice_note(voice: str, midi_note: int, dur_s: float, velocity: int,
                      sr: int = SR_DEFAULT, detune: float = 14.0,
                      drive: float = 0.25, cutoff_base: float = 900.0,
                      attack_ms: float = 6.0, release_ms: float = 180.0) -> np.ndarray:
    """Одна нота выбранным голосом → моно float32. Чистая."""
    n = max(1, int(dur_s * sr))
    f = midi_to_hz(midi_note)
    amp = (max(1, min(127, int(velocity))) / 127.0) ** 1.15
    cut = _brightness(velocity, cutoff_base)

    def _fit(a, b):
        m = min(len(a), len(b))
        return a[:m], b[:m]

    if voice == "supersaw":
        osc = supersaw(f, n, sr, detune_cents=detune, n_voices=7)
        env = adsr(attack_ms, 90, -6.0, release_ms, dur_s, sr)
        o, e = _fit(osc, env); out = lpf(o * e, cut, q=0.9, sr=sr)
        out = _drive(out, drive)
    elif voice == "acid":
        from .synthcore import acid_bass_note
        out = acid_bass_note(midi_note, dur_s, sr,
                             cutoff_start=cut * 1.6, cutoff_end=cut * 0.4,
                             resonance_q=4.5, accent=velocity > 100)
        out = _drive(out, min(0.6, drive + 0.15))
    elif voice == "sub":
        osc = 0.75 * sine_wave(f, n, sr) + 0.25 * sawtooth_bl(f, n, sr)
        env = adsr(4, 60, -3.0, 120, dur_s, sr)
        o, e = _fit(osc, env); out = lpf(o * e, max(180.0, cut * 0.5), q=0.7, sr=sr)
    elif voice == "pad":
        osc = supersaw(f, n, sr, detune_cents=detune * 1.6, n_voices=7)
        env = adsr(max(80.0, attack_ms * 20), 400, -3.0, max(600.0, release_ms * 3), dur_s, sr)
        o, e = _fit(osc, env); out = lpf(o * e, cut * 1.2, q=0.6, sr=sr)
    elif voice == "pluck":
        osc = sawtooth_bl(f, n, sr)
        env = adsr(2, 45, -18.0, 90, dur_s, sr)
        o, e = _fit(osc, env); out = lpf(o * e, cut * 1.4, q=1.2, sr=sr)
        out = _drive(out, drive * 0.6)
    elif voice == "square":
        osc = square_bl(f, n, sr)
        env = adsr(attack_ms, 80, -8.0, release_ms, dur_s, sr)
        o, e = _fit(osc, env); out = lpf(o * e, cut, q=1.0, sr=sr)
    else:
        raise ValueError(f"неизвестный голос {voice!r}; доступны: {VOICES}")

    return (out[:n] * amp).astype(np.float32)


def render_notes_synth(voice: str, notes: list, duration: float, sr: int = SR_DEFAULT,
                       pan: float = 0.0, detune: float = 14.0, drive: float = 0.25,
                       cutoff_base: float = 900.0) -> np.ndarray:
    """События [(t, midi, vel, dur)] → стерео буфер собственным синтом.
    Прямая замена instrument.render_notes для ролей, где GM звучит «по-миди»."""
    total = int(duration * sr) + sr
    out = np.zeros(total, dtype=np.float32)
    for ev in notes:
        t, note, vel, ndur = ev[0], int(ev[1]), int(ev[2]), float(ev[3])
        seg = render_voice_note(voice, note, max(0.03, ndur), vel, sr,
                                detune=detune, drive=drive, cutoff_base=cutoff_base)
        pos = int(t * sr)
        m = min(len(seg), total - pos)
        if m > 0:
            out[pos:pos + m] += seg[:m]
    peak = float(np.max(np.abs(out))) or 1.0
    if peak > 0.99:                                     # защита, НЕ нормализация слоя
        out *= 0.99 / peak
    return mono_to_stereo(out[:int(duration * sr) + 1], pan)


def parse_instrument(name: str) -> tuple[str | None, dict]:
    """`"synth:supersaw"` / `"synth:acid?drive=0.5&detune=20"` → (голос, параметры).
    Не synth-строка → (None, {}) и вызывающий идёт в GM. Чистая."""
    if not isinstance(name, str) or not name.startswith("synth:"):
        return None, {}
    body = name[len("synth:"):]
    voice, _, query = body.partition("?")
    params: dict[str, float] = {}
    for kv in query.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            try:
                params[k.strip()] = float(v)
            except ValueError:
                continue
    return (voice.strip() or "supersaw"), params
