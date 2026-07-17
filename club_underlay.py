#!/usr/bin/env python3
"""
club_underlay.py — накладання клубного грува під готову пісню.
НЕ переструктуровує оригінал. Тільки підлаштовує drums/groove під темп і секції.

Логіка:
  1. Завантажуємо оригінал цілком
  2. Берємо drums стем клубного донора
  3. Стретчимо drums під BPM оригіналу (мінімальна зміна)
  4. Вирівнюємо по першому даунбіту
  5. Тайлимо drums по всій довжині з динамічним рівнем по секціях
  6. HPF drums (80Hz) щоб не конфліктував з басом
  7. Сайдчейн pumping для живості
  8. Мікс і вивід

CLI:
  python3 club_underlay.py --original pop.wav --donor-drums donor.wav \
      --demix-dir path/to/demix --drums-db -14 --out result.wav
"""
import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf


def _load(path: str, sr_target: int = 44100):
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    if sr != sr_target:
        raise RuntimeError(f"Sample rate {sr} != {sr_target}, convert first")
    return audio, sr


def _hpf(x: np.ndarray, sr: int, cutoff_hz: float = 80.0):
    """High-pass filter (butter 4th order)."""
    from scipy.signal import butter, sosfilt
    sos = butter(4, cutoff_hz / (sr / 2), btype="high", output="sos")
    return sosfilt(sos, x.T).T.astype("float32")


def _stretch(x: np.ndarray, sr: int, rate: float) -> np.ndarray:
    if abs(rate - 1.0) < 0.002:
        return x
    try:
        import pyrubberband as pyrb
        return pyrb.time_stretch(x, sr, rate).astype("float32")
    except (RuntimeError, FileNotFoundError):
        pass
    # Fallback: librosa phase vocoder (channel by channel)
    import librosa
    channels = [librosa.effects.time_stretch(x[:, c], rate=rate) for c in range(x.shape[1])]
    return np.stack(channels, axis=1).astype("float32")


def _xfade(a: np.ndarray, b: np.ndarray, fade_ms: int, sr: int) -> np.ndarray:
    """Crossfade кінець a з початком b."""
    n = min(int(sr * fade_ms / 1000), len(a), len(b))
    if n < 2:
        return np.concatenate([a, b])
    ramp = np.linspace(1, 0, n, dtype="float32")
    out = np.concatenate([a[:-n], a[-n:] * ramp[:, None] + b[:n] * (1 - ramp[:, None]), b[n:]])
    return out


def _tile_to_length(loop: np.ndarray, target_len: int, sr: int, xfade_ms: int = 50) -> np.ndarray:
    """Тайлимо loop до target_len семплів."""
    parts = []
    total = 0
    while total < target_len:
        parts.append(loop)
        total += len(loop)
    full = np.concatenate(parts)
    return full[:target_len]


def _load_a1f(wav_path: str):
    """Шукаємо JSON з A1F поруч з WAV."""
    base = os.path.splitext(wav_path)[0]
    for p in [base + ".json", base + "_a1f.json"]:
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    return None


def _stem_path(wav_path: str, demix_dir: str, stem: str) -> str:
    name = os.path.splitext(os.path.basename(wav_path))[0]
    return os.path.join(demix_dir, "htdemucs", name, f"{stem}.wav")


def _find_first_downbeat_sample(a1f: dict | None, sr: int) -> int:
    """Перший даунбіт в семплах."""
    if a1f and a1f.get("downbeats"):
        dbs = a1f["downbeats"]
        first = float(dbs[0]) if dbs else 0.0
        return int(first * sr)
    return 0


def _drums_loop_bars(drums: np.ndarray, sr: int, bpm: float, n_bars: int = 8) -> np.ndarray:
    """Вирізаємо n_bars тактів з drums."""
    bar_len = int(sr * 4 * 60.0 / bpm)
    end = bar_len * n_bars
    if end > len(drums):
        return drums
    return drums[:end]


def _section_level(t: float, segments: list[dict]) -> float:
    """Рівень drums (0-1) для секунди t, виходячи з типу секції."""
    label = "verse"
    for seg in segments:
        if seg["start"] <= t < seg["end"]:
            label = seg.get("label", "verse")
            break
    mapping = {
        "start": 0.30,
        "intro": 0.45,
        "verse": 0.60,
        "chorus": 0.80,
        "inst": 1.00,
        "break": 0.35,
        "build": 0.90,
        "drop": 1.00,
        "solo": 0.55,
        "bridge": 0.60,
        "outro": 0.30,
        "end": 0.10,
    }
    return mapping.get(label, 0.60)


def _dynamic_env(length: int, sr: int, segments: list[dict], fade_in_s: float = 0.5, fade_out_s: float = 3.0) -> np.ndarray:
    """Огинаюча гучності drums: за секціями + fade in/out."""
    env = np.ones(length, dtype="float32")
    hop = sr // 10  # 100ms хоп
    for i in range(0, length, hop):
        t = i / sr
        env[i:i + hop] = _section_level(t, segments)
    # fade in
    fi = int(fade_in_s * sr)
    if fi > 0 and fi < length:
        env[:fi] *= np.linspace(0, 1, fi, dtype="float32")
    # fade out
    fo = int(fade_out_s * sr)
    if fo > 0 and fo < length:
        env[-fo:] *= np.linspace(1, 0, fo, dtype="float32")
    return env


def sidechain_duck(x: np.ndarray, sr: int, quarter: int,
                   depth_db: float = -6.0, release_ms: float = 90.0) -> np.ndarray:
    """Класичний pumping: на кожній чверті drums тиснуть сигнал."""
    depth = 10 ** (depth_db / 20.0)
    rel = max(1, int(sr * release_ms / 1000))
    env = np.ones(len(x), dtype="float32")
    t = np.arange(rel, dtype="float32")
    curve = depth + (1.0 - depth) * (1.0 - np.exp(-5.0 * t / rel))
    for pos in range(0, len(x), quarter):
        seg = min(rel, len(x) - pos)
        env[pos:pos + seg] = np.minimum(env[pos:pos + seg], curve[:seg])
    return (x * env[:, None]).astype("float32")


def underlay(original_wav: str, donor_wav: str, demix_dir: str,
             drums_db: float = -13.0, hpf_hz: float = 80.0,
             loop_bars: int = 8, xfade_ms: int = 60,
             out_wav: str = "underlay_mix.wav", sr: int = 44100):
    print("Завантажую оригінал...")
    orig, _ = _load(original_wav, sr)

    # A1F оригіналу
    a1f_orig = _load_a1f(original_wav)
    orig_bpm = float(a1f_orig["bpm"]) if a1f_orig else 102.0
    orig_segs = a1f_orig.get("segments", []) if a1f_orig else []
    orig_db_sample = _find_first_downbeat_sample(a1f_orig, sr)
    print(f"Оригінал: {len(orig)/sr:.1f}s, BPM={orig_bpm:.1f}, перший даунбіт={orig_db_sample/sr:.2f}s")

    # Стем drums донора
    drums_path = _stem_path(donor_wav, demix_dir, "drums")
    print(f"Завантажую drums: {drums_path}")
    drums, _ = _load(drums_path, sr)

    # A1F донора
    a1f_donor = _load_a1f(donor_wav)
    donor_bpm = float(a1f_donor["bpm"]) if a1f_donor else 107.0
    donor_db_sample = _find_first_downbeat_sample(a1f_donor, sr)
    print(f"Донор drums: BPM={donor_bpm:.1f}, перший даунбіт={donor_db_sample/sr:.2f}s")

    # Вирізаємо drums з першого даунбіту (щоб уникнути pickup beats)
    drums = drums[donor_db_sample:]

    # Стретч drums під BPM оригіналу
    rate = orig_bpm / donor_bpm
    print(f"Стретч drums: ×{rate:.4f} ({donor_bpm:.1f}→{orig_bpm:.1f} BPM)")
    if abs(rate - 1.0) > 0.001:
        drums = _stretch(drums, sr, rate)

    # Беремо n_bars тактів для loop
    loop = _drums_loop_bars(drums, sr, orig_bpm, n_bars=loop_bars)
    print(f"Loop: {len(loop)/sr:.2f}s ({loop_bars} bars @ {orig_bpm:.1f} BPM)")

    # Тайлимо до довжини оригіналу
    # Вирівнюємо: оригінал зсунутий з orig_db_sample від початку
    # Тому drums починаємо з orig_db_sample
    total_len = len(orig)
    drums_tiled = _tile_to_length(loop, total_len - orig_db_sample, sr, xfade_ms)
    # Додаємо тишу перед першим даунбітом
    if orig_db_sample > 0:
        silence = np.zeros((orig_db_sample, 2), dtype="float32")
        drums_tiled = np.concatenate([silence, drums_tiled])
    drums_tiled = drums_tiled[:total_len]

    # HPF drums
    print(f"HPF {hpf_hz}Hz на drums...")
    drums_tiled = _hpf(drums_tiled, sr, hpf_hz)

    # Нормалізуємо drums
    drums_rms = np.sqrt(np.mean(drums_tiled ** 2)) + 1e-9
    orig_rms = np.sqrt(np.mean(orig ** 2)) + 1e-9
    # Встановлюємо рівень drums відносно оригіналу
    target_level = 10 ** (drums_db / 20.0)
    drums_tiled = drums_tiled * (orig_rms / drums_rms) * target_level

    # Динамічна огинаюча по секціях
    print("Застосовую динамічний рівень по секціях...")
    env = _dynamic_env(total_len, sr, orig_segs)
    drums_tiled = drums_tiled * env[:, None]

    # Sidechain duck на оригіналі
    quarter = int(sr * 60.0 / orig_bpm)
    print(f"Sidechain duck оригіналу (quarter={quarter/sr*1000:.0f}ms)...")
    orig_ducked = sidechain_duck(orig, sr, quarter, depth_db=-4.0, release_ms=80.0)
    # Лише де drums гучні (env > 0.3)
    env_thresh = (env > 0.3).astype("float32")
    orig_out = orig * (1 - env_thresh[:, None] * 0.2) + orig_ducked * (env_thresh[:, None] * 0.2)

    # Мікс
    mix = orig_out + drums_tiled
    # Лімітер
    peak = np.max(np.abs(mix))
    if peak > 0.98:
        mix = mix / peak * 0.96

    print(f"Зберігаю: {out_wav}")
    sf.write(out_wav, mix, sr)
    dur = len(mix) / sr
    print(f"Готово: {dur:.1f}s ({int(dur)//60}:{int(dur)%60:02d}) @ {orig_bpm:.1f} BPM")


def _main():
    ap = argparse.ArgumentParser(description="Club Underlay: drums під оригінальний трек")
    ap.add_argument("--original", required=True, help="оригінальний трек WAV")
    ap.add_argument("--donor-drums", required=True, help="клубний донор WAV (потрібен drums стем)")
    ap.add_argument("--demix-dir", required=True, help="папка з demucs стемами")
    ap.add_argument("--drums-db", type=float, default=-13.0, help="рівень drums відносно оригіналу (dB)")
    ap.add_argument("--hpf", type=float, default=80.0, help="частота HPF drums (Hz)")
    ap.add_argument("--loop-bars", type=int, default=8, help="кількість тактів в loop")
    ap.add_argument("--xfade-ms", type=int, default=60, help="кросфейд між лупами (ms)")
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--out", default="underlay_mix.wav")
    a = ap.parse_args()

    underlay(
        original_wav=a.original,
        donor_wav=a.donor_drums,
        demix_dir=a.demix_dir,
        drums_db=a.drums_db,
        hpf_hz=a.hpf,
        loop_bars=a.loop_bars,
        xfade_ms=a.xfade_ms,
        out_wav=a.out,
        sr=a.sr,
    )


if __name__ == "__main__":
    _main()
