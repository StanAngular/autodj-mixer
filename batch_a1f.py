#!/usr/bin/env python3
"""batch_a1f.py — A1F ПАЧКОЙ по трекам, с кэшем/резюмом/скипом, чтобы микс не падал.

Проблема: тяжёлый A1F (структура трека) на 14 треках в ОДНОМ процессе не успевает за
таймаут стадии mix → весь прогон валится. Ровно так уже было с madmom — и решилось
batch_annotate: считаем ЗАРАНЕЕ, ПО ОДНОМУ треку, кладём JSON в a1f_dir. Микс потом
читает кэш мгновенно, а СУЩЕСТВУЮЩИЙ шаг catalog_register укладывает A1F-json в каталог
к остальным данным трека (camelot/youtube_url/madmom/yt-dlp мета). То есть это не отдельный
«кэш сбоку» — это штатное место a1f_results, откуда и микс читает, и каталог забирает.

Свойства (как у batch_annotate):
  • Резюм   — трек с готовым JSON пропускается; повторный запуск дешёвый.
  • Изоляция — каждый трек отдельный процесс со СВОИМ таймаутом; упал один → остальные идут.
  • Фон     — запускать через `nohup … &`, чтобы не рвалось при обрыве сессии.
  • Деградация — что не посчиталось, для того микс сам возьмёт no_a1f (не падает).

СТЕМЫ И СКОРОСТЬ (важно): модель A1F работает на 4 demucs-стемах — «fast без стемов» НЕ
существует by design (прежний --skip-separation без стемов и был багом, см. a1f.py). Реальный
ускоритель — КЭШ стемов: первый прогон трека считает demucs и СОХРАНЯЕТ стемы в --demix-dir,
последующие прогоны (этот микс или будущие) их ПЕРЕИСПОЛЬЗУЮТ (--skip-separation, быстро).
A1F всегда собирает полный набор (вокал-интервалы тоже) — стемы для этого уже есть. Команду
строит a1f.a1f_command (он сам решает demucs-run vs reuse по наличию стемов).

ТОЧЕЧНОСТЬ (--mode auto): не гнать тяжёлый A1F на все треки. По дешёвым первичным признакам
  (длительность + регулярность madmom-даунбитов) решаем по-треково: короткий/нерегулярный →
  A1F; регулярный трек нормальной длины → madmom достаточно. Это по-трековое дополнение к
  пул-уровневой curation_bridge.recommend_analysis (та решает «нужен ли A1F всему миксу»).

Usage:
  python3 batch_a1f.py <wav_dir> [a1f_dir] [--mode auto|all] [--demix-dir D] [--ann-dir D] [--timeout 600]
  # a1f_dir по умолчанию = <wav_dir>/a1f_results (откуда микс читает и catalog_register забирает)
  # --mode auto (дефолт): A1F точечно (короткие/сложные); --ann-dir даёт madmom для оценки
  # потом: микс с --a1f-dir <a1f_dir> → catalog_register уложит A1F в каталог к остальному
"""
import argparse
import os
import subprocess
import time
import json

from a1f import a1f_command


# ── Прогресс-файл для внешнего watcher (прогресс-бар в телегу) ───────────────
PROGRESS_FILE = "/tmp/a1f_progress.json"
MILESTONES = [1, 5, 25, 50, 75, 100]


def write_progress(pct: float, total: int, done: int, fail: int, skip: int,
                   current: str, status: str, eta_s: int = 0):
    """Записать прогресс в JSON для внешнего watcher (крон шлёт в телегу)."""
    data = {
        "total": total, "completed": done, "failed": fail, "skipped": skip,
        "current": current, "status": status,
        "progress_pct": round(pct),
        "milestones": {},
        "eta_sec": eta_s,
    }
    for m in MILESTONES:
        data["milestones"][m] = pct >= m
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

# Пороги по-трековой рекомендации (прозрачны/настраиваемы, в духе curation_bridge)
SHORT_TRACK_SEC = 300       # < 5 мин — короткий: тайтовые переходы, структура критична → A1F
IRREGULAR_CV = 0.10         # CV интервалов даунбитов выше → нерегулярная структура → A1F


def track_duration(wav_path: str) -> float:
    """Длительность wav в секундах через soundfile. 0.0 при ошибке."""
    try:
        import soundfile as sf
        info = sf.info(wav_path)
        return info.frames / float(info.samplerate)
    except Exception:
        return 0.0


def downbeat_cv(ann_path: str):
    """Коэф. вариации интервалов между madmom-даунбитами (мера нерегулярности структуры).
    None если данных мало/ошибка. Формат ann — как у batch_annotate: 'pos beat' (beat==1 = даунбит)."""
    try:
        import numpy as np
        a = np.loadtxt(ann_path)
        if a.ndim == 1:
            a = a.reshape(1, -1)
        downs = np.array([r[0] for r in a if round(r[1]) == 1], dtype=float)
        if len(downs) < 4:
            return None
        d = np.diff(downs)
        m = d.mean()
        return float(d.std() / m) if m else None
    except Exception:
        return None


def recommend_track_a1f(wav_path: str, ann_path: str | None = None) -> tuple[bool, str]:
    """Нужен ли ЭТОМУ треку A1F (точечно). Короткий ИЛИ нерегулярный по madmom → да;
    регулярный трек нормальной длины → madmom достаточно. Ошибки → не рекомендуем лишнего."""
    reasons = []
    dur = track_duration(wav_path)
    if dur and dur < SHORT_TRACK_SEC:
        reasons.append(f"короткий {dur:.0f}s")
    if ann_path and os.path.exists(ann_path):
        cv = downbeat_cv(ann_path)
        if cv is not None and cv > IRREGULAR_CV:
            reasons.append(f"нерегулярная структура CV={cv:.2f}")
    rec = bool(reasons)
    return rec, (", ".join(reasons) if rec else "регулярный трек нормальной длины — madmom достаточно")



def pending(wav_dir: str, a1f_dir: str) -> list[str]:
    """Какие wav ещё без JSON в кэше (резюм). Чистая."""
    wavs = sorted(f for f in os.listdir(wav_dir) if f.endswith(".wav"))
    return [w for w in wavs
            if not os.path.exists(os.path.join(a1f_dir, os.path.splitext(w)[0] + ".json"))]


def run_one(wav: str, wav_dir: str, a1f_dir: str, timeout: int, demix_dir: str) -> bool:
    """Посчитать A1F для одного трека (свой таймаут, ошибки не пробрасываются). True если ок.
    a1f_command сам решает: demucs-run+сохранить стемы ИЛИ reuse (--skip-separation)."""
    path = os.path.join(wav_dir, wav)
    out_json = os.path.join(a1f_dir, os.path.splitext(wav)[0] + ".json")
    cmd = a1f_command(path, a1f_dir, demix_dir=demix_dir)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0 and os.path.exists(out_json):
            print(f"     ✓ {time.time() - t0:.0f}s", flush=True)
            return True
        print(f"     ✗ rc={r.returncode} {(r.stderr or '')[-200:]}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"     ✗ таймаут >{timeout}s — пропуск (микс возьмёт no_a1f для него)", flush=True)
    except Exception as e:
        print(f"     ✗ {type(e).__name__}: {e}", flush=True)
    return False


def main():
    ap = argparse.ArgumentParser(description="A1F пачкой по трекам с кэшем/резюмом")
    ap.add_argument("wav_dir")
    ap.add_argument("a1f_dir", nargs="?", default=None,
                    help="куда класть A1F-json; дефолт <wav_dir>/a1f_results (штатное место "
                         "для микса и catalog_register)")
    ap.add_argument("--mode", choices=["auto", "all"], default="auto",
                    help="auto: A1F точечно (короткие/нерегулярные; остальным madmom достаточно); all: всем")
    ap.add_argument("--demix-dir", default=None,
                    help="кэш demucs-стемов; дефолт <wav_dir>/demix. Первый прогон считает и "
                         "сохраняет стемы, следующие — переиспользуют (быстро)")
    ap.add_argument("--ann-dir", default=None, help="madmom-аннотации (.txt) для рекомендации в auto")
    ap.add_argument("--timeout", type=int, default=600, help="секунд на ОДИН трек (дефолт 600; full тяжелее)")
    args = ap.parse_args()

    a1f_dir = args.a1f_dir or os.path.join(args.wav_dir, "a1f_results")
    demix_dir = args.demix_dir or os.path.join(args.wav_dir, "demix")
    os.makedirs(a1f_dir, exist_ok=True)
    os.makedirs(demix_dir, exist_ok=True)
    total = len([f for f in os.listdir(args.wav_dir) if f.endswith(".wav")])
    todo = pending(args.wav_dir, a1f_dir)
    print(f"A1F batch: всего {total}, к расчёту {len(todo)}, уже готово {total - len(todo)}",
          flush=True)

    ok, fail, skipped = 0, [], []
    write_progress(0, len(todo), 0, 0, 0, "", "starting")
    for i, wav in enumerate(todo, 1):
        if args.mode == "auto":
            ann = os.path.join(args.ann_dir, os.path.splitext(wav)[0] + ".txt") if args.ann_dir else None
            rec, why = recommend_track_a1f(os.path.join(args.wav_dir, wav), ann)
            if not rec:
                skipped.append(wav)
                print(f"[{i}/{len(todo)}] {wav} — пропуск A1F ({why}; микс возьмёт madmom/no_a1f)", flush=True)
                write_progress(round(i / len(todo) * 100), len(todo), ok, len(fail), len(skipped),
                               wav + " (skip)", "running")
                continue
            tag = "reuse-stems" if __import__("a1f").stems_ready(os.path.join(args.wav_dir, wav), demix_dir) else "demucs"
            print(f"[{i}/{len(todo)}] {wav} — A1F нужен: {why} [{tag}] …", flush=True)
        else:
            print(f"[{i}/{len(todo)}] {wav} …", flush=True)
        write_progress(round((i - 0.5) / len(todo) * 100), len(todo), ok, len(fail), len(skipped),
                       wav, "processing")
        t0_track = time.time()
        if run_one(wav, args.wav_dir, a1f_dir, args.timeout, demix_dir):
            ok += 1
            track_time = time.time() - t0_track
            remaining = len(todo) - i
            eta_s = int(track_time * remaining) if remaining else 0
            write_progress(round(i / len(todo) * 100), len(todo), ok, len(fail), len(skipped),
                           "", "running", eta_s=eta_s)
        else:
            fail.append(wav)

    print(f"\nИтог: A1F посчитан {ok}/{len(todo)} (пропущено по рекомендации {len(skipped)}). "
          f"Не удалось: {len(fail)}", flush=True)
    if fail:
        print("  не вышло (микс возьмёт no_a1f): " + ", ".join(fail), flush=True)
    print(f"Готово в {a1f_dir}. Микс: --a1f-dir {a1f_dir} → catalog_register уложит A1F в каталог.", flush=True)
    write_progress(100, len(todo), ok, len(fail), len(skipped), "", "done")


if __name__ == "__main__":
    main()
