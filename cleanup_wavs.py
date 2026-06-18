#!/usr/bin/env python3
"""
cleanup_wavs.py — безопасное удаление временных WAV (политика хранения).

Удаляет ТОЛЬКО shared/tracks/*.wav, чей video_id ПОДТВЕРЖДЁН в каталоге
(метаданные сохранены → трек перекачивается по youtube_url, анализ не повторяется).
Незарегистрированные WAV НЕ удаляет (предупреждает: «сперва catalog_register»).

По построению инструмент работает только с tracks-каталогом — shared/a1f_results/*
(полные A1F + .meta.json) и shared/ann/* (madmom) НЕ трогаются. MP3 остаётся.

Dry-run по умолчанию; реальное удаление — только с --apply. Опционально удаляет
WAV-микс, если рядом есть готовый MP3 (--mix-wav + --require-mp3).

wavs_safe_to_delete — чистая (тестируется офлайн); файловые операции — тонкие, под --apply.
"""
import os


def wavs_safe_to_delete(present_ids, catalog_ids) -> tuple[list[str], list[str]]:
    """
    Разбить присутствующие WAV-id на безопасные (есть в каталоге) и
    незарегистрированные (НЕ удалять). Чистая функция.
    """
    cat = set(catalog_ids)
    deletable = [i for i in present_ids if i in cat]
    unregistered = [i for i in present_ids if i not in cat]
    return deletable, unregistered


def scan_wav_ids(tracks_dir: str) -> list[str]:
    """video_id'ы из shared/tracks/*.wav (имя файла = id). Тонкий I/O."""
    if not os.path.isdir(tracks_dir):
        return []
    return sorted(f[:-4] for f in os.listdir(tracks_dir) if f.endswith(".wav"))


def catalog_ids(catalog_dir: str) -> set:
    """id'ы треков из каталога. Переиспользует catalog_utils. Тонкий I/O."""
    import sys
    sys.path.insert(0, catalog_dir)
    import catalog_utils as cu
    return set(cu.load_index().get("tracks", {}).keys())


def cleanup(tracks_dir: str, catalog_dir: str, apply: bool = False,
            mix_wav: str = "", require_mp3: str = "") -> dict:
    """Зачистка WAV под гардом каталога. Тонкий I/O. Возвращает статистику/планы."""
    present = scan_wav_ids(tracks_dir)
    cat = catalog_ids(catalog_dir)
    deletable, unregistered = wavs_safe_to_delete(present, cat)

    freed = 0
    if apply:
        for vid in deletable:
            p = os.path.join(tracks_dir, f"{vid}.wav")
            try:
                freed += os.path.getsize(p)
                os.remove(p)
            except OSError:
                pass

    mix_deleted = False
    if mix_wav and os.path.exists(mix_wav):
        if require_mp3 and os.path.exists(require_mp3):
            if apply:
                try:
                    os.remove(mix_wav)
                    mix_deleted = True
                except OSError:
                    pass
            else:
                mix_deleted = "would"          # dry-run
        # без готового MP3 микс НЕ трогаем

    return {
        "present": len(present),
        "deletable": deletable,
        "unregistered": unregistered,
        "applied": apply,
        "freed_mb": round(freed / 1e6, 1),
        "mix_deleted": mix_deleted,
    }


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Безопасное удаление временных WAV (гард каталога)")
    ap.add_argument("--tracks-dir", default="shared/tracks")
    ap.add_argument("--catalog-dir",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "shared", "catalog"))
    ap.add_argument("--apply", action="store_true", help="реально удалить (иначе dry-run)")
    ap.add_argument("--mix-wav", default="", help="WAV-микс к удалению (если есть MP3)")
    ap.add_argument("--require-mp3", default="", help="MP3, наличие которого разрешает удалить микс")
    args = ap.parse_args()

    res = cleanup(args.tracks_dir, args.catalog_dir, args.apply,
                  args.mix_wav, args.require_mp3)
    mode = "УДАЛЕНО" if res["applied"] else "DRY-RUN (ничего не удалено, добавь --apply)"
    print(f"[{mode}] WAV в {args.tracks_dir}: {res['present']}")
    print(f"  безопасно удалить (в каталоге): {len(res['deletable'])}"
          + (f" — освобождено {res['freed_mb']} МБ" if res['applied'] else ""))
    if res["unregistered"]:
        print(f"  ⚠ НЕ удаляю {len(res['unregistered'])} незарегистрированных "
              f"(сперва: catalog_register.py): {', '.join(res['unregistered'][:5])}"
              + (" …" if len(res['unregistered']) > 5 else ""))
    if res["mix_deleted"]:
        print(f"  микс-WAV: {'удалён' if res['mix_deleted'] is True else 'будет удалён (есть MP3)'}")


if __name__ == "__main__":
    _main()
