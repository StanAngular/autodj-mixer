#!/usr/bin/env python3
"""
prescreen.py — дешёвая MP3-проба перед тяжёлым WAV.

Идея: качаем лёгкий MP3 (~10-15 МБ, ~30с), считаем Camelot/BPM из него, и WAV
докачиваем ТОЛЬКО для подходящих треков. Экономия ~10× по времени/трафику на
отбраковке — особенно для Path B, где много кандидатов «на угад».

Поток: seed_discover → prescreen (mp3 → проба → фильтр) → yt_download (WAV только
keeper'ов) → batch_annotate → bridge → mix.

Тонкости:
  • soundfile НЕ читает mp3 → проба через librosa.load (mp3/m4a/webm via ffmpeg);
  • BPM на пробе приблизительный (librosa.tempo); точную сетку даёт madmom/A1F на WAV;
  • Camelot из librosa-хромы так же точен, как на WAV (тот же detect_key).

fit_check и partition_keepers — чистые (тестируются офлайн). probe_audio и
ensure_mp3 — тонкий I/O (librosa / yt-dlp).
"""
import json
import os
import subprocess

from local_enrich import video_id          # переиспользуем извлечение id


def fit_check(track: dict, bpm_lo: float | None = None, bpm_hi: float | None = None,
              bpm_tol: float = 2.0) -> tuple[bool, str]:
    """
    Прошёл ли трек пробу: Camelot определился И BPM в диапазоне (если задан). Чистая.
    Возвращает (ok, причина_отказа).
    """
    cam = (track.get("camelot") or "").strip()
    if not cam or cam == "?":
        return False, "Camelot не определился"
    try:
        b = float(track.get("bpm") or 0)
    except (ValueError, TypeError):
        b = 0.0
    if b and bpm_lo and bpm_hi and not (bpm_lo - bpm_tol <= b <= bpm_hi + bpm_tol):
        return False, f"BPM {b:.0f} вне {bpm_lo}-{bpm_hi}"
    return True, ""


def partition_keepers(candidates: list[dict], bpm_lo: float | None = None,
                      bpm_hi: float | None = None, bpm_tol: float = 2.0
                      ) -> tuple[list[dict], list[dict]]:
    """Разбить кандидатов на keepers / rejects по результату пробы. Чистая."""
    keepers, rejects = [], []
    for t in candidates:
        ok, reason = fit_check(t, bpm_lo, bpm_hi, bpm_tol)
        if ok:
            keepers.append(t)
        else:
            rejects.append({**t, "_reject": reason})
    return keepers, rejects


def _coerce_bpm(tempo) -> int:
    """tempo от librosa (скаляр ИЛИ numpy-массив в новых версиях) → int BPM. Чистая.
    Раньше float(array) кидал TypeError → bpm=0 → не сохранялся (баг BPM=None)."""
    try:
        import numpy as np
        arr = np.ravel(tempo)
        if arr.size == 0:
            return 0
        return int(round(float(arr[0])))
    except (TypeError, ValueError):
        return 0


def probe_audio(path: str) -> tuple[str, str, int]:
    """Camelot + приблизительный BPM из любого аудио (mp3/wav) через librosa. Тонкий I/O."""
    import librosa
    from enrich_metadata import detect_key, camelot_code
    y, sr = librosa.load(path, sr=22050, mono=True, duration=90)
    key = detect_key(y, sr)
    cam = camelot_code(key)
    bpm = _coerce_bpm(librosa.beat.beat_track(y=y, sr=sr)[0])
    return key, cam, bpm


def ensure_mp3(url: str, out_dir: str) -> str | None:
    """Скачать лёгкий MP3 для пробы, если ещё нет. Возвращает путь или None. Тонкий I/O."""
    vid = video_id(url)
    if not vid:
        return None
    dst = os.path.join(out_dir, f"{vid}.mp3")
    if os.path.exists(dst):
        return dst
    os.makedirs(out_dir, exist_ok=True)
    try:
        res = subprocess.run(
            ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3",
             "--audio-quality", "5", "-o", os.path.join(out_dir, f"{vid}.%(ext)s"),
             "--no-warnings", url],
            capture_output=True, text=True, timeout=120)
        return dst if res.returncode == 0 and os.path.exists(dst) else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def cap_probe(candidates: list[dict], max_probe: int | None) -> list[dict]:
    """Из кандидатов без Camelot взять не больше max_probe для пробы. Чистая.
    Защита от скачивания сотен MP3 вслепую (см. SKILL §7)."""
    need = [t for t in candidates if not (t.get("camelot") or "").strip()]
    if max_probe and max_probe > 0:
        return need[:max_probe]
    return need


def prescreen(candidates: list[dict], mp3_dir: str, bpm_lo: float | None = None,
              bpm_hi: float | None = None, download: bool = True,
              max_probe: int | None = None, target: int | None = None) -> dict:
    """
    Дешёвая MP3-проба с ЖЁСТКИМИ лимитами. Тонкий I/O.
      • max_probe — максимум кандидатов на пробу (не качать сотни MP3 вслепую);
      • target — остановиться, как только набралось столько keeper'ов (не качать лишнее).
    Возвращает {keepers, rejects, n_keep, n_reject, probed}.
    """
    to_probe = cap_probe(candidates, max_probe)
    probe_ids = {id(t) for t in to_probe}
    probed = 0
    keep_so_far = 0
    for t in candidates:
        if id(t) not in probe_ids:
            continue
        if target and keep_so_far >= target:
            break                                   # хватит — цель набрана
        url = t.get("youtube_url", "")
        vid = video_id(url)
        mp3 = os.path.join(mp3_dir, f"{vid}.mp3") if vid else ""
        if download and (not mp3 or not os.path.exists(mp3)):
            mp3 = ensure_mp3(url, mp3_dir) or ""
        if mp3 and os.path.exists(mp3):
            probed += 1
            key, cam, bpm = probe_audio(mp3)
            if cam and cam != "?":
                t["key"] = key
                t["camelot"] = cam
                t["camelot_source"] = "probe-mp3"
            if not t.get("bpm") and bpm:
                t["bpm"] = bpm
            ok, _ = fit_check(t, bpm_lo, bpm_hi)
            if ok:
                keep_so_far += 1

    keepers, rejects = partition_keepers(candidates, bpm_lo, bpm_hi)
    if target and len(keepers) > target:
        rejects += [{**t, "_reject": "сверх target"} for t in keepers[target:]]
        keepers = keepers[:target]
    return {"keepers": keepers, "rejects": rejects,
            "n_keep": len(keepers), "n_reject": len(rejects), "probed": probed}


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="MP3-проба: дёшево отсеять до WAV")
    ap.add_argument("candidates", help="cand.json (напр. от seed_discover)")
    ap.add_argument("--mp3-dir", default="shared/probe_mp3")
    ap.add_argument("--bpm-min", type=float, default=None)
    ap.add_argument("--bpm-max", type=float, default=None)
    ap.add_argument("--max-probe", type=int, default=30, help="максимум MP3 на пробу (антираздувание)")
    ap.add_argument("--target", type=int, default=16, help="хватит keeper'ов — стоп (не качать лишнее)")
    ap.add_argument("--no-download", action="store_true", help="MP3 уже скачаны")
    ap.add_argument("--out", default="keepers.json")
    ap.add_argument("--url-file", default="keepers_urls.txt",
                    help="url-файл keeper'ов для yt_download (WAV)")
    args = ap.parse_args()

    cands = json.load(open(args.candidates, encoding="utf-8"))
    res = prescreen(cands, args.mp3_dir, args.bpm_min, args.bpm_max,
                    download=not args.no_download, max_probe=args.max_probe, target=args.target)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res["keepers"], f, ensure_ascii=False, indent=2)
    with open(args.url_file, "w", encoding="utf-8") as f:
        for t in res["keepers"]:
            if t.get("youtube_url"):
                f.write(t["youtube_url"] + "\n")
    print(f"MP3-проба: пробовано {res['probed']}, keeper'ов {res['n_keep']}, отсеяно {res['n_reject']}. "
          f"→ {args.out} + {args.url_file}. Дальше: yt_download --url-file {args.url_file} (WAV).")
    for r in res["rejects"]:
        print(f"  ✗ {r.get('artist','?')} — {r.get('track','?')}: {r['_reject']}")


if __name__ == "__main__":
    _main()
