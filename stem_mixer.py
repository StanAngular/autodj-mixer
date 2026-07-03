#!/usr/bin/env python3
"""
stem_mixer.py — M3: stem-мэшап. Вокал трека A поверх инструментала трека B —
не переход, а НАЛОЖЕНИЕ: из двух треков собирается третий (клубная версия попсы,
acapella-ремикс и т.п.).

Опирается на то, что УЖЕ есть в пайплайне:
  • demucs-стемы кэшируются A1F-прогоном (P55): <demix>/htdemucs/<name>/{vocals,bass,drums,other}.wav
  • темп: pyrubberband time_stretch (тот же движок, что warp_to_grid в миксере)
  • тональность: pyrubberband pitch_shift, сдвиг считается по Camelot ОБОИХ треков
  • Camelot/BPM берутся как везде: из каталога/метаданных или detect.

Совместимость (честный гейт, а не «как получится»):
  • |pitch shift| ≤ MAX_SEMITONES (3): дальше вокал звучит неестественно;
  • stretch в [0.92..1.08] (~8%, как BPM_DIFF_LIMIT миксера): дальше артефакты.
Не проходит гейт → отказ с причиной и подсказкой (какой трек подобрать).

Отдельный модуль: smart_mixer НЕ тронут, дефолты пайплайна целы. Opt-in CLI:
  python3 stem_mixer.py --vocal A.wav --instrumental B.wav --demix-dir shared/tracks/demix \
      --vocal-camelot 8A --inst-camelot 9A --vocal-bpm 120 --inst-bpm 124 --out mashup.wav
Стемов нет → подсказка прогнать batch_a1f (стемы появятся как побочный продукт -k).
"""
import argparse
import os
import sys

import numpy as np

# ─── Тональная математика (чистая) ───────────────────────────────────────────

def camelot_shift_semitones(vocal_cam: str, inst_cam: str) -> int | None:
    """Минимальный сдвиг вокала (в полутонах), при котором пара становится ГАРМОНИЧЕСКИ
    СОВМЕСТИМОЙ по Camelot (не «тоника к тонике»!): соседние камелоты совместимы без
    сдвига — колесо для этого и придумано. None — Camelot неизвестен. Чистая.
    Транспонирование на +1 полутон = +7 шагов по колесу (квинтовый круг)."""
    a, b = _parse_cam(vocal_cam), _parse_cam(inst_cam)
    if a is None or b is None:
        return None
    for shift in sorted(range(-6, 7), key=abs):           # 0, ±1, ±2, … — минимальный первым
        num = (a[0] - 1 + 7 * shift) % 12 + 1
        if _cam_compatible((num, a[1]), b):
            return shift
    return None                                            # недостижимо (не бывает на колесе)


def _parse_cam(cam: str) -> tuple[int, str] | None:
    cam = (cam or "").strip().upper()
    if len(cam) < 2 or cam[-1] not in ("A", "B"):
        return None
    try:
        num = int(cam[:-1])
    except ValueError:
        return None
    return (num, cam[-1]) if 1 <= num <= 12 else None


def _cam_compatible(a: tuple[int, str], b: tuple[int, str]) -> bool:
    """Стандартная Camelot-совместимость: тот же код, сосед по кругу (тот же режим),
    или тот же номер в другом режиме (относительный мажор/минор). Чистая."""
    if a == b:
        return True
    if a[1] == b[1]:
        d = abs(a[0] - b[0])
        return min(d, 12 - d) == 1
    return a[0] == b[0]


def stretch_ratio(vocal_bpm: float, inst_bpm: float) -> float | None:
    """rate для time_stretch вокала к темпу инструментала (rate>1 = ускорить). Чистая."""
    if not vocal_bpm or not inst_bpm:
        return None
    return float(inst_bpm) / float(vocal_bpm)


MAX_SEMITONES = 3
STRETCH_LO, STRETCH_HI = 0.92, 1.08


def mashup_gate(shift: int | None, rate: float | None) -> tuple[bool, str]:
    """Честная совместимость пары для мэшапа. Чистая. → (ok, причина)."""
    if shift is None:
        return False, "Camelot неизвестен у одного из треков (нет в метаданных/каталоге)"
    if rate is None:
        return False, "BPM неизвестен у одного из треков"
    if abs(shift) > MAX_SEMITONES:
        return False, (f"тональный сдвиг {shift:+d} полутонов > {MAX_SEMITONES} — вокал "
                       f"прозвучит неестественно; подбери инструментал ближе по Camelot")
    if not (STRETCH_LO <= rate <= STRETCH_HI):
        return False, (f"темп-растяжка ×{rate:.3f} вне [{STRETCH_LO}..{STRETCH_HI}] — "
                       f"артефакты; подбери инструментал ближе по BPM")
    return True, f"ok: shift {shift:+d} st, stretch ×{rate:.3f}"


# ─── Стемы (I/O-тонкое) ──────────────────────────────────────────────────────

STEMS = ("vocals", "bass", "drums", "other")


def stem_dir(wav_path: str, demix_dir: str) -> str:
    name = os.path.splitext(os.path.basename(wav_path))[0]
    return os.path.join(demix_dir, "htdemucs", name)


def load_stem(wav_path: str, demix_dir: str, stem: str):
    """Стем как stereo float32 (N,2). Ошибка — с подсказкой, как получить стемы."""
    import soundfile as sf
    p = os.path.join(stem_dir(wav_path, demix_dir), f"{stem}.wav")
    if not os.path.exists(p):
        raise FileNotFoundError(
            f"нет стема {p}. Стемы появляются после A1F: "
            f"python3 batch_a1f.py <wav_dir> --mode all (кэш -k, P55)")
    audio, _sr = sf.read(p, dtype="float32", always_2d=True)
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    return audio


def instrumental_of(wav_path: str, demix_dir: str):
    """Инструментал = bass+drums+other (всё, кроме vocals)."""
    parts = [load_stem(wav_path, demix_dir, s) for s in ("bass", "drums", "other")]
    n = min(len(p) for p in parts)
    return sum(p[:n] for p in parts)


# ─── Сборка мэшапа ───────────────────────────────────────────────────────────

def align_vocal(vocal: np.ndarray, sr: int, shift: int, rate: float) -> np.ndarray:
    """Подогнать вокал: время (rate) + тональность (shift). pyrubberband (как в миксере)."""
    import pyrubberband as pyrb
    out = vocal
    if abs(rate - 1.0) > 1e-3:
        out = pyrb.time_stretch(out, sr, rate).astype("float32")
    if shift:
        out = pyrb.pitch_shift(out, sr, shift).astype("float32")
    return out


def build_mashup(inst: np.ndarray, vocal: np.ndarray, sr: int,
                 offset_bars: int, inst_bpm: float, vocal_gain_db: float = -2.0):
    """Инструментал + вокал с offset_bars (вход после интро). Простой лимитер по пику.
    Чистая по данным (numpy in → numpy out)."""
    bar = int(round((60.0 / inst_bpm) * 4 * sr))
    start = min(offset_bars * bar, max(len(inst) - 1, 0))
    g = 10 ** (vocal_gain_db / 20.0)
    out = inst.copy()
    seg = min(len(vocal), len(out) - start)
    if seg > 0:
        out[start:start + seg] += vocal[:seg] * g
    peak = float(np.max(np.abs(out))) or 1.0
    if peak > 0.99:
        out *= 0.99 / peak
    return out


def _main():
    ap = argparse.ArgumentParser(description="M3: stem-мэшап — вокал A поверх инструментала B")
    ap.add_argument("--vocal", required=True, help="WAV трека-донора вокала (A)")
    ap.add_argument("--instrumental", required=True, help="WAV трека-основы (B)")
    ap.add_argument("--demix-dir", required=True, help="кэш стемов (P55): <dir>/htdemucs/<name>/")
    ap.add_argument("--vocal-camelot", required=True)
    ap.add_argument("--inst-camelot", required=True)
    ap.add_argument("--vocal-bpm", type=float, required=True)
    ap.add_argument("--inst-bpm", type=float, required=True)
    ap.add_argument("--offset-bars", type=int, default=16, help="вход вокала после интро B")
    ap.add_argument("--vocal-gain-db", type=float, default=-2.0)
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--out", default="mashup.wav")
    args = ap.parse_args()

    shift = camelot_shift_semitones(args.vocal_camelot, args.inst_camelot)
    rate = stretch_ratio(args.vocal_bpm, args.inst_bpm)
    ok, why = mashup_gate(shift, rate)
    print(f"Гейт: {why}")
    if not ok:
        sys.exit(2)

    import soundfile as sf
    inst = instrumental_of(args.instrumental, args.demix_dir)
    vocal = load_stem(args.vocal, args.demix_dir, "vocals")
    vocal = align_vocal(vocal, args.sr, shift, rate)
    out = build_mashup(inst, vocal, args.sr, args.offset_bars, args.inst_bpm,
                       args.vocal_gain_db)
    sf.write(args.out, out, args.sr)
    print(f"Мэшап: {args.out} ({len(out)/args.sr:.1f}s, вокал с бара {args.offset_bars}, "
          f"shift {shift:+d} st, stretch ×{rate:.3f})")


if __name__ == "__main__":
    _main()
