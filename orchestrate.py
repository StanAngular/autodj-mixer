#!/usr/bin/env python3
"""
orchestrate.py — одна foreground-команда на всю цепочку подбор→микс→отчёт.

Token-efficiency: полный вывод каждой стадии пишется в logs/<stage>.log, а в
контекст агента идёт ТОЛЬКО финальная строка-сводка стадии (наши скрипты её всегда
печатают). Стоп на первой ошибке с хвостом лога. Dry-run по умолчанию — печатает
план (точные команды) для ревью; реальный прогон — флаг --run.

Не нарушает §0 SKILL: всё foreground, видимо, без фоновых задач и импровизаций —
оркестратор лишь выстраивает и прогоняет известные команды, показывая результат.

Пресеты:
  path B (по знанию): build_seedlist → seed_discover → [prescreen] → download →
                      annotate → local_enrich → bridge --prune → run_pipeline →
                      catalog_register → [cleanup]
  path A (по чартам): curate_tracks → bridge(urls) → [prescreen] → download → …

build_plan и summarize_stage — чистые (тестируются офлайн). run_plan — тонкий I/O.
"""
import sys
import os
import subprocess


def build_plan(name: str, path: str = "b", config: str = "", style: str = "",
               artists: str = "", tag: str = "", bpm_min=None, bpm_max=None,
               prescreen: bool = True, a1f: bool = False, cleanup: bool = False,
               seed_limit: int = 24, max_probe: int = 30, target: int = 16,
               source: str = "auto", sort: str = "", remix: bool = False,
               tracklist: str = "") -> list[tuple]:
    """Построить упорядоченный план [(stage, argv)]. Чистая функция.
    Лимиты (seed_limit/max_probe/target) — чтобы НЕ качать сотни вслепую (SKILL §7).
    source: youtube (сиды+last.fm) | beatport (чарты жанра с готовыми BPM/Camelot)."""
    cand = f"{name}_cand.json"
    plan: list[tuple] = []

    if tracklist:
        # явный список (поиск/LLM): метаданные BPM/Camelot ЕДУТ с сидами (как Beatport) →
        # resolve/prescreen их не перепроверяют (smart-bypass). Любой жанр/год, мимо Cloudflare.
        plan.append(("tracklist", ["python3", "tracklist_source.py", "--tracklist", tracklist,
                                   "--out", cand]))
        urls = f"{name}_urls.txt"
    elif path == "a":
        if not config:
            raise ValueError("path A требует --config")
        plan.append(("curate", ["python3", "curate_tracks.py", "--config", config, "--out", cand]))
        plan.append(("bridge_urls", ["python3", "curation_bridge.py", cand, "--name", name]))
        urls = f"urls_{name}.txt"
    elif source == "beatport":
        genre = style or tag
        if not genre:
            raise ValueError("source beatport требует --style/--tag (жанр)")
        bp_cmd = ["python3", "beatport_source.py", "--genre", genre, "--per", "5", "--out", cand]
        if sort:
            bp_cmd += ["--sort", sort]
        plan.append(("beatport", bp_cmd))
        urls = f"{name}_urls.txt"
    elif source == "auto":
        if not (style or artists or tag):
            raise ValueError("source auto требует --style/--artists/--tag")
        comp = ["python3", "compose_sources.py", "--target", str(target), "--out", cand]
        if style:   comp += ["--style", style]
        if artists: comp += ["--artists", artists]
        if tag:     comp += ["--tag", tag]
        if sort:    comp += ["--sort", sort]
        if remix:   comp += ["--remix"]
        plan.append(("compose", comp))
        urls = f"{name}_urls.txt"
    else:
        if not (style or artists or tag):
            raise ValueError("path B требует хотя бы --style/--artists/--tag")
        seeds = f"{name}_seeds.txt"
        sl = ["python3", "build_seedlist.py", "--out", seeds, "--limit", str(seed_limit)]
        if style:   sl += ["--style", style]
        if artists: sl += ["--artists", artists]
        if tag:     sl += ["--tag", tag]
        plan.append(("seedlist", sl))
        disc = ["python3", "seed_discover.py", "--artists-file", seeds,
                "--per", "1", "--out", cand]
        if style or tag:
            disc += ["--verify-style", style or tag]     # гейт стиля Path B
        if remix:
            disc.append("--remix")
        plan.append(("discover", disc))
        urls = f"{name}_urls.txt"

    # каскад без скачивания: каталог→кэш→(опц.Tunebat) ДО prescreen — закачка последней
    plan.append(("resolve", ["python3", "resolve_metadata.py", cand, "--out", cand]))

    if prescreen:
        ps = ["python3", "prescreen.py", cand, "--out", cand, "--url-file", f"{name}_urls.txt",
              "--max-probe", str(max_probe), "--target", str(target)]
        if bpm_min is not None: ps += ["--bpm-min", str(bpm_min)]
        if bpm_max is not None: ps += ["--bpm-max", str(bpm_max)]
        plan.append(("prescreen", ps))
        urls = f"{name}_urls.txt"

    plan.append(("download", ["python3", "yt_download.py", "--url-file", urls]))
    plan.append(("annotate", ["python3", "batch_annotate.py"]))
    plan.append(("local_enrich", ["python3", "local_enrich.py", cand, "--tracks-dir", "shared/tracks"]))
    plan.append(("bridge", ["python3", "curation_bridge.py", cand, "--name", name,
                            "--prune-wav-dir", "shared/tracks"]))
    plan.append(("mix", ["python3", "run_pipeline.py", "--wav-dir", "shared/tracks",
                         "--ann-dir", "shared/ann", "--config", f"mix_config_{name}.py",
                         "--analysis-mode", "a1f_fast" if a1f else "no_a1f"]))
    plan.append(("catalog", ["python3", "catalog_register.py", cand, "--a1f-dir", "shared/a1f_results"]))
    if cleanup:
        plan.append(("cleanup", ["python3", "cleanup_wavs.py", "--tracks-dir", "shared/tracks", "--apply"]))
    return plan


def summarize_stage(stdout: str) -> str:
    """Компактная сводка стадии = последняя непустая строка её вывода. Чистая."""
    for line in reversed((stdout or "").splitlines()):
        if line.strip():
            return line.strip()
    return "(нет вывода)"


def run_plan(plan: list[tuple], log_dir: str = "logs", execute: bool = False,
             cwd: str | None = None) -> dict:
    """
    Прогнать план. Без execute — печатает план (dry-run). Тонкий I/O.
    Полный вывод → logs/<stage>.log; в stdout — компактная сводка. Стоп на ошибке.
    """
    if not execute:
        print("DRY-RUN — план (проверь команды, затем добавь --run):")
        for i, (stage, argv) in enumerate(plan, 1):
            print(f"  {i:2}. {stage}: {' '.join(argv)}")
        return {"executed": False, "stages": len(plan)}

    os.makedirs(log_dir, exist_ok=True)
    done = []
    for stage, argv in plan:
        print(f"▶ {stage} …", flush=True)
        try:
            res = subprocess.run(argv, capture_output=True, text=True, cwd=cwd)
        except OSError as e:
            print(f"✗ {stage}: не удалось запустить ({e})")
            return {"executed": True, "failed": stage, "done": done}
        log = os.path.join(log_dir, f"{stage}.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write(res.stdout + "\n--- stderr ---\n" + res.stderr)
        if res.returncode != 0:
            tail = "\n    ".join((res.stdout + res.stderr).strip().splitlines()[-4:])
            print(f"✗ {stage} (код {res.returncode}). Хвост:\n    {tail}\n  полный лог: {log}")
            print(f"СТОП на стадии '{stage}'. Предыдущие выполнены: {', '.join(done) or '—'}")
            return {"executed": True, "failed": stage, "done": done}
        print(f"✓ {stage}: {summarize_stage(res.stdout)}")
        done.append(stage)
    print(f"ГОТОВО — все {len(plan)} стадий. Логи в {log_dir}/.")
    return {"executed": True, "failed": None, "done": done}


def doctor_checks() -> list[tuple[str, bool, str]]:
    """Само-проверка каналов/инструментов ДО работы: (имя, ok, подсказка). Чистая по структуре,
    I/O — только локальные который/env/import (быстро, без сети). Смысл: агент ЗАРАНЕЕ знает,
    чем располагает, а не выясняет 13-ю шагами в бою (кейс deep disco)."""
    import shutil
    checks: list[tuple[str, bool, str]] = []

    def _which(name, hint):
        checks.append((name, shutil.which(name) is not None, hint))

    _which("yt-dlp", "pip install yt-dlp — discovery (ytsearch/scsearch) и скачивание")
    _which("ffmpeg", "apt install ffmpeg — конвертация аудио")
    _which("xvfb-run", "apt install xvfb — только для playwright-скрейпа (мёртв за Cloudflare, не критично)")

    try:
        from a1f import a1f_python
        checks.append(("A1F venv", os.path.exists(a1f_python()),
                       "структурный анализ; env A1F_PYTHON или ~/ai-tools/all-in-one-fix/venv"))
    except Exception:
        checks.append(("A1F venv", False, "модуль a1f.py недоступен"))

    for env, what in (("LASTFM_API_KEY", "верификация стиля артиста (seed_discover --verify-style)"),
                      ("DISCOGS_TOKEN", "официальный API Discogs — поиск жанр+год с VPS (Фаза 1)"),
                      ("SOCKS5_PROXY", "Cloudflare Warp для скрейпа (не критично: скрейп мёртв)")):
        checks.append((f"env {env}", bool(os.environ.get(env)), what))

    for mod, what in (("madmom", "битовая сетка (batch_annotate)"),
                      ("librosa", "аудио-анализ"),
                      ("soundfile", "чтение WAV")):
        try:
            __import__(mod); checks.append((f"py {mod}", True, what))
        except Exception:
            checks.append((f"py {mod}", False, f"pip install {mod} — {what}"))
    return checks


def run_doctor() -> int:
    """Печать таблицы doctor_checks. Возврат: число проваленных КРИТИЧНЫХ (yt-dlp/ffmpeg)."""
    checks = doctor_checks()
    critical_fail = 0
    print("=== autodj doctor: что живо на этой машине ===")
    for name, ok, hint in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name:18s} — {hint}" if not ok else f"  {mark} {name}")
        if not ok and name in ("yt-dlp", "ffmpeg"):
            critical_fail += 1
    print("Итог: " + ("готов к работе" if critical_fail == 0
          else f"КРИТИЧНО отсутствует: {critical_fail} (discovery/mix не поедут)"))
    return critical_fail


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Оркестратор пайплайна autodj-mixer")
    ap.add_argument("name", nargs="?", default="", help="имя микса (префикс файлов); не нужно для --doctor")
    ap.add_argument("--path", choices=["a", "b"], default="b", help="a=чарты, b=по знанию")
    ap.add_argument("--config", default="", help="для path A: brief.json/конфиг курации")
    ap.add_argument("--style", default="")
    ap.add_argument("--artists", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--bpm-min", type=float, default=None)
    ap.add_argument("--bpm-max", type=float, default=None)
    ap.add_argument("--no-prescreen", action="store_true")
    ap.add_argument("--a1f", action="store_true", help="run_pipeline в режиме a1f_fast")
    ap.add_argument("--cleanup", action="store_true", help="удалить WAV после микса (гард каталога)")
    ap.add_argument("--seed-limit", type=int, default=24, help="потолок сид-строк")
    ap.add_argument("--max-probe", type=int, default=30, help="потолок MP3-проб")
    ap.add_argument("--target", type=int, default=16, help="сколько треков набрать (стоп)")
    ap.add_argument("--source", choices=["youtube", "beatport", "auto"], default="auto",
                    help="ДЕФОЛТ auto: по богатству данных Beatport→Bandcamp→last.fm/YT; youtube/beatport — оверрайд")
    ap.add_argument("--sort", default="", choices=["", "newest", "bestsellers"],
                    help="порядок пула Beatport: newest (свежее) / bestsellers (популярнее)")
    ap.add_argument("--remix", action="store_true",
                    help="искать ремиксы, не оригиналы (Path B / discover)")
    ap.add_argument("--tracklist", default="",
                    help="файл с явным списком 'Artist - Title' (из поиска/LLM): минует подбор по жанру, "
                         "находит аудио и обогащает метаданные. Любой жанр/год, мимо Cloudflare")
    ap.add_argument("--run", action="store_true", help="выполнить (иначе dry-run)")
    ap.add_argument("--doctor", action="store_true",
                    help="само-проверка: какие инструменты/каналы живы на этой машине")
    ap.add_argument("--log-dir", default="logs")
    args = ap.parse_args()

    if args.doctor:
        sys.exit(1 if run_doctor() else 0)
    if not args.name:
        ap.error("name обязателен (кроме --doctor)")

    plan = build_plan(args.name, args.path, args.config, args.style, args.artists,
                      args.tag, args.bpm_min, args.bpm_max,
                      prescreen=not args.no_prescreen, a1f=args.a1f, cleanup=args.cleanup,
                      seed_limit=args.seed_limit, max_probe=args.max_probe, target=args.target,
                      source=args.source, sort=args.sort, remix=args.remix,
                      tracklist=args.tracklist)
    run_plan(plan, args.log_dir, execute=args.run)


if __name__ == "__main__":
    _main()
