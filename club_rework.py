#!/usr/bin/env python3
"""
club_rework.py — M4: pop→club rework. Из поп-трека собирается КЛУБНАЯ версия:
DJ-структура (длинное луп-интро → тело → луп-аутро) + клубный грув (drums попсы
приглушаются, подкладывается drums-стем клубного донора) + клубный темп.

Опирается на уже построенное:
  • структура попсы: A1F bar_labels (intro/verse/chorus/…): smart_mixer.load_a1f_track_data
  • стемы: demucs-кэш P55 (<demix>/htdemucs/<name>/{vocals,bass,drums,other}.wav)
  • темп: pyrubberband (как M3); склейки: eq_pow из smart_mixer (equal-power)

Гейт темпа мягче миксового (rework — творческий инструмент): stretch 0.85–1.25;
за пределами — отказ с причиной (или --force, честно предупредив о качестве).

Opt-in отдельный модуль: smart_mixer/пайплайн не тронуты.
  python3 club_rework.py --pop pop.wav --drums-donor club.wav --demix-dir shared/tracks/demix \
      --ann-dir shared/ann --target-bpm 124 --out club_edit.wav
"""
import argparse
import os
import sys

import numpy as np

# ─── Структурный план (чистое) ───────────────────────────────────────────────

CALM = ("intro", "inst", "verse", "bridge", "start")     # интро-материал
TAIL = ("outro", "inst", "verse", "end")                 # аутро-материал
BODY = ("verse", "chorus", "bridge", "inst", "solo", "break")


def _blocks(bar_labels: list[str]) -> list[tuple[int, int, str]]:
    """bar_labels → непрерывные блоки (start_bar, end_bar, label). Чистая."""
    out = []
    if not bar_labels:
        return out
    s, cur = 0, bar_labels[0]
    for i, l in enumerate(bar_labels[1:], 1):
        if l != cur:
            out.append((s, i, cur))
            s, cur = i, l
    out.append((s, len(bar_labels), cur))
    return out


def _pick_loop(blocks, wanted, loop_len, from_end=False):
    """Первый (или последний) блок с меткой из wanted длиной ≥ loop_len//2 → (s, e)."""
    it = reversed(blocks) if from_end else blocks
    for s, e, l in it:
        if l in wanted and (e - s) >= max(2, loop_len // 2):
            return s, min(e, s + loop_len)
    return None


def rework_plan(bar_labels: list[str], intro_bars: int = 16, outro_bars: int = 16,
                loop_len: int = 8) -> list[tuple[int, int, int]]:
    """DJ-план: [(src_start_bar, src_end_bar, repeats)]. Чистая.
      1) луп-ИНТРО: спокойный блок начала, повторами до intro_bars;
      2) ТЕЛО: от первого BODY-бара до конца последнего BODY-блока — как есть;
      3) луп-АУТРО: хвостовой блок повторами до outro_bars.
    Нет меток → весь трек как есть (план без обмана)."""
    n = len(bar_labels or [])
    if n == 0:
        return []
    blocks = _blocks(bar_labels)

    intro = _pick_loop(blocks, CALM, loop_len)
    body_bars = [i for i, l in enumerate(bar_labels) if l in BODY]
    body = (body_bars[0], body_bars[-1] + 1) if body_bars else (0, n)
    outro = _pick_loop(blocks, TAIL, loop_len, from_end=True)

    plan: list[tuple[int, int, int]] = []
    if intro:
        s, e = intro
        reps = max(1, round(intro_bars / (e - s)))
        plan.append((s, e, reps))
    plan.append((body[0], body[1], 1))
    if outro and outro[0] >= body[1] - 1:                 # хвост, не середина
        s, e = outro
        reps = max(1, round(outro_bars / (e - s)))
        plan.append((s, e, reps))
    return plan


def plan_length_bars(plan) -> int:
    return sum((e - s) * r for s, e, r in plan)


# Потолок 1.25 сознательно: типовой rework «попса ~100-105 → клуб 122-126» = ×1.19-1.25,
# rubberband это тянет достойно (rework — творческий инструмент, не бит-матч перехода).
STRETCH_LO, STRETCH_HI = 0.85, 1.25


def club_gate(pop_bpm: float, target_bpm: float) -> tuple[bool, float, str]:
    """Гейт rework-стретча (мягче миксового). → (ok, rate, причина)."""
    if not pop_bpm or not target_bpm:
        return False, 0.0, "BPM неизвестен (попса или target)"
    rate = float(target_bpm) / float(pop_bpm)
    if not (STRETCH_LO <= rate <= STRETCH_HI):
        return False, rate, (f"stretch ×{rate:.3f} вне [{STRETCH_LO}..{STRETCH_HI}] — "
                             f"качество развалится; ближе target-bpm или --force")
    return True, rate, f"ok: ×{rate:.3f} ({pop_bpm:.0f}→{target_bpm:.0f} BPM)"


# ─── Рендер (numpy in → numpy out) ───────────────────────────────────────────

def _xfade_concat(parts: list[np.ndarray], sr: int, ms: int = 15) -> np.ndarray:
    """Склейка кусков с коротким equal-power кроссфейдом (без щелчков)."""
    from smart_mixer import eq_pow
    n = int(sr * ms / 1000)
    out = parts[0]
    for p in parts[1:]:
        if n and len(out) > n and len(p) > n:
            fo, fi = eq_pow(n)
            out = np.concatenate([out[:-n],
                                  out[-n:] * fo[:, None] + p[:n] * fi[:, None],
                                  p[n:]])
        else:
            out = np.concatenate([out, p])
    return out


def render_plan(audio: np.ndarray, downbeats: np.ndarray, plan, sr: int) -> np.ndarray:
    """Нарезать по даунбитам и склеить по плану (лупы повторами)."""
    parts = []
    last = len(downbeats) - 1
    for s, e, reps in plan:
        s, e = max(0, min(s, last)), max(1, min(e, last))
        if e <= s:
            continue
        seg = audio[int(downbeats[s]):int(downbeats[e])]
        parts.extend([seg] * reps)
    return _xfade_concat(parts, sr) if parts else audio


def tile_to_length(loop: np.ndarray, total: int, sr: int, xfade_ms: int = 15) -> np.ndarray:
    """Затайлить луп до total сэмплов (мягкие склейки). Каждый стык съедает xfade —
    репиты считаются по эффективной длине, добивается точно до total."""
    if len(loop) == 0:
        return np.zeros((total, 2), dtype="float32")
    n_x = int(sr * xfade_ms / 1000)
    eff = max(1, len(loop) - n_x)                    # вклад каждого следующего тайла
    reps = 1 + int(np.ceil(max(0, total - len(loop)) / eff))
    out = _xfade_concat([loop] * reps, sr, xfade_ms)
    if len(out) < total:                             # страховка на граничные случаи
        out = np.concatenate([out, np.zeros((total - len(out), out.shape[1]), dtype=out.dtype)])
    return out[:total]


def _limit(x: np.ndarray, ceiling: float = 0.99) -> np.ndarray:
    peak = float(np.max(np.abs(x))) or 1.0
    return x * (ceiling / peak) if peak > ceiling else x


def _stretch(x: np.ndarray, sr: int, rate: float) -> np.ndarray:
    if abs(rate - 1.0) < 1e-3:
        return x
    import pyrubberband as pyrb
    return pyrb.time_stretch(x, sr, rate).astype("float32")


# ─── Сборка (I/O) ────────────────────────────────────────────────────────────

def _load_track(wav, demix_dir, ann_dir, sr):
    """(стемы dict, downbeats samples, bpm) трека: A1F-грид (обязателен для попсы)."""
    from smart_mixer import load_a1f_track_data
    from stem_mixer import load_stem
    stems = {s: load_stem(wav, demix_dir, s) for s in ("vocals", "bass", "drums", "other")}
    a1f = load_a1f_track_data(wav, sr, a1f_dir=None, catalog_dir=None)
    if not a1f or a1f.get("downbeats") is None or not len(a1f.get("downbeats", [])):
        raise RuntimeError(f"нет A1F-данных для {wav} — прогони batch_a1f (нужны downbeats+структура)")
    return stems, np.asarray(a1f["downbeats"]), float(a1f.get("bpm") or 0), a1f.get("bar_labels") or []


def pop_to_club(pop_wav, donor_wav, demix_dir, ann_dir, target_bpm, sr=44100,
                intro_bars=16, outro_bars=16, pop_drums_db=-12.0, club_drums_db=0.0,
                force=False, out="club_edit.wav"):
    import soundfile as sf
    stems, db, pop_bpm, labels = _load_track(pop_wav, demix_dir, ann_dir, sr)
    d_stems, d_db, d_bpm, d_labels = _load_track(donor_wav, demix_dir, ann_dir, sr)
    tgt = target_bpm or d_bpm
    ok, rate, why = club_gate(pop_bpm, tgt)
    print(f"Гейт: {why}")
    if not ok and not force:
        sys.exit(2)

    plan = rework_plan(labels, intro_bars, outro_bars)
    print(f"План: {plan} ({plan_length_bars(plan)} бар из {len(labels)})")

    # поп-стемы: единый план → единая нарезка → стретч к клубному темпу
    rendered = {k: _stretch(render_plan(v, db, plan, sr), sr, rate) for k, v in stems.items()}
    total = min(len(v) for v in rendered.values())

    # клубный грув: 8 бар drums донора из середины, к target, тайлом на всю длину
    mid = max(0, (len(d_db) - 1) // 2 - 4)
    loop = d_stems["drums"][int(d_db[mid]):int(d_db[min(mid + 8, len(d_db) - 1)])]
    loop = _stretch(loop, sr, tgt / d_bpm if d_bpm else 1.0)
    club_drums = tile_to_length(loop, total, sr)

    g_pop, g_club = 10 ** (pop_drums_db / 20), 10 ** (club_drums_db / 20)
    mix = (rendered["vocals"][:total] + rendered["bass"][:total] +
           rendered["other"][:total] + rendered["drums"][:total] * g_pop +
           club_drums * g_club)
    mix = _limit(mix)
    sf.write(out, mix, sr)
    print(f"Club edit: {out} ({total/sr:.1f}s @ {tgt:.0f} BPM; поп-drums {pop_drums_db}dB, "
          f"клубный грув из {os.path.basename(donor_wav)})")
    return out


def _main():
    ap = argparse.ArgumentParser(description="M4: pop→club rework (структура+грув+темп)")
    ap.add_argument("--pop", required=True, help="поп-трек WAV (нужны его A1F + стемы)")
    ap.add_argument("--drums-donor", required=True, help="клубный трек WAV (его drums-стем = грув)")
    ap.add_argument("--demix-dir", required=True)
    ap.add_argument("--ann-dir", default=None)
    ap.add_argument("--target-bpm", type=float, default=0, help="дефолт: BPM донора")
    ap.add_argument("--intro-bars", type=int, default=16)
    ap.add_argument("--outro-bars", type=int, default=16)
    ap.add_argument("--pop-drums-db", type=float, default=-12.0)
    ap.add_argument("--club-drums-db", type=float, default=0.0)
    ap.add_argument("--force", action="store_true", help="пройти гейт стретча (качество на твоей совести)")
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--out", default="club_edit.wav")
    a = ap.parse_args()
    pop_to_club(a.pop, a.drums_donor, a.demix_dir, a.ann_dir, a.target_bpm, a.sr,
                a.intro_bars, a.outro_bars, a.pop_drums_db, a.club_drums_db, a.force, a.out)


if __name__ == "__main__":
    _main()
