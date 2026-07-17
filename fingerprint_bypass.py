#!/usr/bin/env python3
"""
fingerprint_bypass.py — зміна аудіо так щоб обійти авторський fingerprint.

Як працює audio fingerprinting (Suno, ACRCloud, Shazam):
  - Аналізує частотні піки в часі (constellation map)
  - Порівнює хеші з базою

Методи обходу (комбінація = ефективніше):
  1. Pitch shift (+/-N semitones) — змінює частотний профіль
  2. Tempo change — змінює часові відстані між піками
  3. High-freq noise — забруднює верхній спектр
  4. Time trim — cut silence + small offset

CLI:
  python3 fingerprint_bypass.py --input original.mp3 --out modified.mp3 [options]
  python3 fingerprint_bypass.py --input original.mp3 --out modified.mp3 --semitones 2 --tempo 1.03
"""
import argparse
import os
import subprocess
import sys
import tempfile


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Команда {cmd[0]} завершилась з кодом {result.returncode}:\n{result.stderr.decode()}")


def bypass(input_path: str, out_path: str,
           semitones: float = 2.0,
           tempo_factor: float = 1.0,
           noise_db: float = -55.0,
           trim_start_ms: int = 0) -> None:
    """
    semitones: скільки півтонів підняти/опустити (2 = мінімум для bypass fingerprint)
    tempo_factor: >1 = прискорити, <1 = уповільнити (1.0 = без зміни)
    noise_db: рівень noise floor (за замовчуванням -55 dBFS, ледь чутний)
    trim_start_ms: обрізати початок (ms) — offset від фінгерпринту
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Файл не знайдено: {input_path}")

    print(f"Input: {input_path}")
    print(f"Pitch shift: {semitones:+.1f} semitones")
    print(f"Tempo factor: {tempo_factor:.3f}")
    print(f"Noise floor: {noise_db:.0f} dBFS")
    if trim_start_ms:
        print(f"Trim start: {trim_start_ms}ms")

    # Pitch ratio = 2^(semitones/12)
    pitch_ratio = 2 ** (semitones / 12)

    # Будуємо ffmpeg фільтр ланцюжок
    filters = []

    # 1. Trim start (якщо потрібно)
    if trim_start_ms > 0:
        filters.append(f"atrim=start={trim_start_ms/1000:.3f}")

    # 2. Pitch shift через rubberband (без зміни темпу)
    if abs(semitones) > 0.01:
        filters.append(f"rubberband=pitch={pitch_ratio:.6f}:pitchq=quality")

    # 3. Tempo (якщо потрібно)
    if abs(tempo_factor - 1.0) > 0.005:
        # atempo обмежений 0.5-2.0
        if 0.5 <= tempo_factor <= 2.0:
            filters.append(f"atempo={tempo_factor:.4f}")
        else:
            # Два кроки для великих змін
            f1 = min(2.0, tempo_factor)
            f2 = tempo_factor / f1
            filters.append(f"atempo={f1:.4f},atempo={f2:.4f}")

    # 4. Додати мікро-noise (high frequency, вище 14kHz)
    # Це збиває спектральні піки fingerprint
    filters.append(f"aeval=val(0)+random(0)*pow(10\\,{noise_db}/20):c=same")

    # 5. Нормалізація гучності
    filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    if not filters:
        print("Нічого не змінювати, копіюю файл...")
        import shutil
        shutil.copy2(input_path, out_path)
        return

    filter_str = ",".join(filters)

    # Визначаємо кодек виводу
    ext = os.path.splitext(out_path)[1].lower()
    if ext == ".mp3":
        codec_args = ["-codec:a", "libmp3lame", "-b:a", "320k"]
    elif ext in (".wav",):
        codec_args = ["-codec:a", "pcm_s16le"]
    elif ext in (".flac",):
        codec_args = ["-codec:a", "flac"]
    else:
        codec_args = ["-codec:a", "libmp3lame", "-b:a", "320k"]

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", filter_str,
        *codec_args,
        out_path
    ]

    print(f"\nffmpeg filter: {filter_str[:80]}...")
    _run(cmd)
    print(f"\nГотово: {out_path}")

    # Розмір
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"Розмір: {size_mb:.1f} MB")


def _main():
    ap = argparse.ArgumentParser(description="Обхід audio fingerprint (Suno, ACRCloud)")
    ap.add_argument("--input", required=True, help="Вхідний файл (MP3/WAV/FLAC)")
    ap.add_argument("--out", required=True, help="Вихідний файл")
    ap.add_argument("--semitones", type=float, default=2.0,
                    help="Pitch shift в півтонах (default: +2, мін для bypass: 1.5+)")
    ap.add_argument("--tempo", type=float, default=1.0,
                    help="Зміна темпу (default: 1.0 = без зміни, 1.03 = +3%%)")
    ap.add_argument("--noise-db", type=float, default=-55.0,
                    help="Рівень high-freq noise dBFS (default: -55)")
    ap.add_argument("--trim-start-ms", type=int, default=0,
                    help="Зрізати N мс від початку (default: 0)")
    a = ap.parse_args()

    bypass(a.input, a.out,
           semitones=a.semitones,
           tempo_factor=a.tempo,
           noise_db=a.noise_db,
           trim_start_ms=a.trim_start_ms)


if __name__ == "__main__":
    _main()
