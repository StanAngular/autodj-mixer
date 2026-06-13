#!/usr/bin/env python3
"""
run_preflight.py — Pre-flight check before any mix.

Запускается ПЕРЕД smart_mixer.py. Проверяет всё что может сломать микс.
Выход: 0 = всё OK, 1 = есть WARN, 2 = есть ERROR (блокирующий).

Usage:
  ./run_preflight.py --wav-dir shared/tracks --ann-dir shared/ann
  ./run_preflight.py --wav-dir shared/tracks --ann-dir shared/ann --a1f-dir shared/a1f_results

Без флагов — проверка текущей директории (глобальные проверки).
"""

import argparse
import os
import re
import subprocess
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
SMART_MIXER = os.path.join(SRC_DIR, "smart_mixer.py")

ERRORS = []
WARNS = []


def err(msg):
    ERRORS.append(msg)
    print(f"  ❌ {msg}")


def warn(msg):
    WARNS.append(msg)
    print(f"  ⚠️  {msg}")


def ok(msg):
    print(f"  ✅ {msg}")


# ── 1. Проверка norm_lufs headroom ──────────────────────────────────────

def check_headroom():
    """Проверка что `if pk > 0.707`, не `0.99`."""
    if not os.path.exists(SMART_MIXER):
        warn(f"smart_mixer.py не найден в {SRC_DIR}")
        return
    with open(SMART_MIXER) as f:
        content = f.read()
    # Ищем norm_lufs function headroom (только if pk > в контексте norm_lufs)
    # Не трогаем soft_clipper_tanh (0.999) и build_cf_lr4 (0.99) — они свои
    match = re.search(r'def norm_lufs.*?if pk > ([\d.]+)', content, re.DOTALL)
    if not match:
        warn("Не найден headroom check в norm_lufs()")
        return
    val = match.group(1)
    if float(val) != 0.707:
        err(f"Неправильный headroom в norm_lufs: {val} (должен быть 0.707 / -3dB)")
    else:
        ok(f"Headroom norm_lufs: {val} ✓")


# ── 2. Git status ───────────────────────────────────────────────────────

def check_git():
    """Проверка незакоммиченных изменений и отставания от remote."""
    git_dir = os.path.join(SRC_DIR, ".git")
    if not os.path.exists(git_dir):
        warn(f"Не git-репозиторий: {SRC_DIR}")
        return

    # Uncommitted changes
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=SRC_DIR
    )
    if r.stdout.strip():
        changed = r.stdout.strip().split("\n")
        warn(f"Незакоммиченные изменения ({len(changed)} файлов):")
        for line in changed[:5]:
            print(f"         {line}")
        if len(changed) > 5:
            print(f"         ... и ещё {len(changed)-5}")

    # Behind remote
    subprocess.run(["git", "fetch"], capture_output=True, cwd=SRC_DIR)
    r = subprocess.run(
        ["git", "rev-list", "--count", "HEAD..@{u}"],
        capture_output=True, text=True, cwd=SRC_DIR
    )
    if r.stdout.strip() and int(r.stdout.strip()) > 0:
        warn(f"Ветка отстаёт от remote на {r.stdout.strip()} коммитов — нужен git pull")

    ok("Git check done")


# ── 3. Annotation format (time-based vs sample-based) ────────────────────

def check_annotations(ann_dir):
    """Проверка формата аннотаций: время в секундах (с точкой), не сэмплы."""
    if not os.path.isdir(ann_dir):
        err(f"Директория аннотаций не найдена: {ann_dir}")
        return

    txt_files = sorted(f for f in os.listdir(ann_dir) if f.endswith(".txt"))
    if not txt_files:
        warn(f"Нет .txt файлов в {ann_dir}")
        return

    bad = []
    good = 0
    for fname in txt_files:
        path = os.path.join(ann_dir, fname)
        try:
            with open(path) as f:
                first_line = f.readline().strip()
            if not first_line:
                bad.append(f"{fname}: пустой файл")
                continue
            first_val = first_line.split()[0]
            if "." in first_val:
                good += 1
            else:
                bad.append(f"{fname}: sample-based (first={first_val})")
        except Exception as e:
            bad.append(f"{fname}: {e}")

    if bad:
        err(f"{len(bad)}/{len(txt_files)} аннотаций sample-based:")
        for line in bad[:3]:
            print(f"         {line}")
        if len(bad) > 3:
            print(f"         ... и ещё {len(bad)-3}")
    else:
        ok(f"Аннотации: {good}/{len(txt_files)} time-based ✓")


# ── 4. Enrich meta.json ─────────────────────────────────────────────────

def check_enrich(a1f_dir):
    """Проверка наличия meta.json для всех треков."""
    if not os.path.isdir(a1f_dir):
        warn(f"Директория A1F не найдена: {a1f_dir} — пропускаю проверку enrich")
        return

    meta_files = [f for f in os.listdir(a1f_dir) if f.endswith(".meta.json")]
    a1f_files = [f for f in os.listdir(a1f_dir) if f.endswith(".json")
                  and not f.endswith(".meta.json")]

    if not a1f_files:
        warn(f"Нет A1F JSON в {a1f_dir}")
        return

    # Check youtube_url in meta
    missing_youtube = 0
    for mf in meta_files:
        import json
        try:
            with open(os.path.join(a1f_dir, mf)) as f:
                meta = json.load(f)
            if not meta.get("youtube_url"):
                missing_youtube += 1
                warn(f"{mf}: нет youtube_url")
        except Exception:
            warn(f"{mf}: не читается")

    if missing_youtube == 0 and meta_files:
        ok(f"Enrich: {len(meta_files)} meta.json, все с youtube_url ✓")
    elif not meta_files:
        warn(f"Нет meta.json — enrich_metadata.py не запущен (0/{len(a1f_files)} A1F)")


# ── 5. A1F JSON validity ────────────────────────────────────────────────

def check_a1f(a1f_dir):
    """Проверка что A1F JSON читаемы и содержат нужные поля."""
    if not os.path.isdir(a1f_dir):
        warn(f"Директория A1F не найдена: {a1f_dir}")
        return

    a1f_files = sorted(f for f in os.listdir(a1f_dir) if f.endswith(".json")
                       and not f.endswith(".meta.json"))
    if not a1f_files:
        warn(f"Нет A1F JSON файлов в {a1f_dir}")
        return

    import json
    ok_count = 0
    for fname in a1f_files:
        path = os.path.join(a1f_dir, fname)
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            err(f"{fname}: НЕ ЧИТАЕТСЯ")
            continue
        missing = []
        for key in ["bpm", "segments"]:
            if key not in data:
                missing.append(key)
        if missing:
            warn(f"{fname}: нет полей {missing}")
        else:
            ok_count += 1

    ok(f"A1F: {ok_count}/{len(a1f_files)} валидны ✓")


# ── 6. WAV ←→ annotation pairing ────────────────────────────────────────

def check_pairing(wav_dir, ann_dir):
    """Проверка что для каждого WAV есть аннотация и наоборот."""
    if not os.path.isdir(wav_dir) or not os.path.isdir(ann_dir):
        err(f"WAV dir ({wav_dir}) или ANN dir ({ann_dir}) не найдены")
        return

    wavs = {os.path.splitext(f)[0] for f in os.listdir(wav_dir) if f.endswith(".wav")}
    anns = {os.path.splitext(f)[0] for f in os.listdir(ann_dir) if f.endswith(".txt")}

    orphan_wavs = wavs - anns
    orphan_anns = anns - wavs

    if orphan_wavs:
        err(f"WAV без аннотаций ({len(orphan_wavs)}): {', '.join(sorted(orphan_wavs)[:5])}")
    if orphan_anns:
        warn(f"Аннотации без WAV ({len(orphan_anns)}): {', '.join(sorted(orphan_anns)[:5])}")
    if not orphan_wavs and not orphan_anns:
        ok(f"Пар WAV/ann: {len(wavs)} ✓")


# ── 7. Demucs stem directories for A1F ──────────────────────────────────

def check_demucs_stems(wav_dir):
    """Проверка наличия Demucs stem-директорий для A1F --skip-separation."""
    demucs_dir = os.path.join(SRC_DIR, "demix", "htdemucs")
    if not os.path.isdir(demucs_dir):
        warn(f"Demucs stem-директория не найдена: {demucs_dir}")
        warn("A1F --skip-separation упадёт с FileNotFoundError")
        return

    wavs = [os.path.splitext(f)[0] for f in os.listdir(wav_dir) if f.endswith(".wav")]
    missing_stems = []
    for base in wavs:
        stem_dir = os.path.join(demucs_dir, base)
        if not os.path.isdir(stem_dir):
            missing_stems.append(base)
        else:
            # Проверка что есть все 4 стема
            for stem in ["bass.wav", "drums.wav", "other.wav", "vocals.wav"]:
                if not os.path.exists(os.path.join(stem_dir, stem)):
                    missing_stems.append(f"{base}/{stem}")

    if missing_stems:
        warn(f"Нет Demucs stems для {len(missing_stems)} треков (A1F --skip-separation упадёт)")
    else:
        ok("Demucs stems: все присутствуют ✓")


# ── 8. Проверка что preview + confirmation от пользователя получены ──────

def check_preview_flag():
    """Напоминание: не запускать микс без превью."""
    # Это не скриптовая проверка — это напоминание агенту
    warn("НЕ ЗАПУСКАЙТЕ МИКС без отправки превью пользователю "
         "и получения подтверждения!")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pre-flight check for AutoDJ Mixer")
    parser.add_argument("--wav-dir", default=None, help="WAV directory")
    parser.add_argument("--ann-dir", default=None, help="Annotation directory")
    parser.add_argument("--a1f-dir", default=None, help="A1F results directory")
    parser.add_argument("--mix-dir", default=None, help="Mix output directory (for stamps check)")
    args = parser.parse_args()

    # Resolve defaults
    wav_dir = args.wav_dir or os.path.join(SRC_DIR, "shared", "tracks")
    ann_dir = args.ann_dir or os.path.join(SRC_DIR, "shared", "ann")
    a1f_dir = args.a1f_dir or os.path.join(SRC_DIR, "shared", "a1f_results")

    print(f"\n{'='*60}")
    print(f"  🔍 AutoDJ Pre-flight Check")
    print(f"  SRC:  {SRC_DIR}")
    print(f"  WAV:  {wav_dir}")
    print(f"  ANN:  {ann_dir}")
    print(f"  A1F:  {a1f_dir}")
    print(f"{'='*60}\n")

    # ── Global checks (всегда) ──
    print("── Headroom ──")
    check_headroom()

    print("\n── Git ──")
    check_git()

    print("\n── Preview Reminder ──")
    check_preview_flag()

    # ── Directory checks (если есть куда) ──
    print("\n── Annotations ──")
    if os.path.isdir(ann_dir):
        check_annotations(ann_dir)
    else:
        warn(f"ANN dir {ann_dir} не существует")

    print("\n── WAV/ANN Pairing ──")
    if os.path.isdir(wav_dir) or os.path.isdir(ann_dir):
        check_pairing(wav_dir, ann_dir)
    else:
        warn("Ни WAV ни ANN директории не найдены — пропускаю pairing")

    print("\n── A1F Enrich ──")
    check_enrich(a1f_dir)

    print("\n── A1F JSON ──")
    check_a1f(a1f_dir)

    print("\n── Demucs Stems ──")
    check_demucs_stems(wav_dir)

    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"  РЕЗЮМЕ:")
    print(f"    Ошибки: {len(ERRORS)}  Предупреждения: {len(WARNS)}")
    print(f"{'='*60}")

    if ERRORS:
        print("\n❌ БЛОКИРУЮЩИЕ ОШИБКИ — микс НЕ ЗАПУСКАТЬ до исправления:")
        for e in ERRORS:
            print(f"  • {e}")
    if WARNS:
        print("\n⚠️  ПРЕДУПРЕЖДЕНИЯ — желательно исправить:")
        for w in WARNS:
            print(f"  • {w}")
    if not ERRORS and not WARNS:
        print("\n✅ ВСЁ ЧИСТО — можно запускать микс!")
    print()

    if ERRORS:
        sys.exit(2)
    elif WARNS:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
