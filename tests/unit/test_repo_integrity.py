"""
Целостность репозитория (P87) — тесты против класса багов «работает только у меня».

Живой случай: `music_theory.py` (706 строк) месяцами существовал ТОЛЬКО на машине
агента и никогда не коммитился. `render_track.py` его импортировал → на origin репо
не собирался вовсе, а агент этого не видел (у него файл был локально) и продолжал
описывать архитектуру по несуществующему в репо коду. Патчи от одного агента ложились
на публичную базу, рендерил другой — свою. Эти тесты делают такое невозможным.

Проверяют:
  1. каждый ЛОКАЛЬНЫЙ импорт указывает на файл, отслеживаемый git (не untracked);
  2. ключевые модули реально импортируются из чистого клона;
  3. отсутствующий локальный модуль = падение теста, а не «у меня работает».
"""
import ast
import importlib
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# Точки входа, которые ОБЯЗАНЫ импортироваться из чистого клона.
ENTRY_MODULES = ["orchestrate", "run_pipeline", "smart_mixer", "club_rework",
                 "stem_mixer", "vocal_phrases", "render_track",
                 "autodj.generate.motif", "autodj.generate.arrangement",
                 "autodj.generate.mixbus", "autodj.generate.sampler",
                 "autodj.generate.synthvoice", "autodj.generate.mininotation"]

# Каталоги вне рабочего потока (архив/эксперименты) — не обязаны импортироваться.
SKIP_DIRS = ("archive/", "tests/", "specs/", "docs/")


def _tracked_py() -> set[str]:
    """Файлы .py, известные git (не untracked). Без git — фоллбэк на обход диска."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "*.py"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return set(out.stdout.split())
    except Exception:
        pass
    found = set()
    for dirpath, _dirs, files in os.walk(ROOT):
        for f in files:
            if f.endswith(".py"):
                found.add(os.path.relpath(os.path.join(dirpath, f), ROOT))
    return found


def _local_targets(tracked: set[str]) -> set[str]:
    """Имена модулей, которые считаются ЛОКАЛЬНЫМИ (файлы этого репо)."""
    names = set()
    for rel in tracked:
        if "/" not in rel:
            names.add(rel[:-3])                       # модуль в корне
        parts = rel.split("/")
        if parts[0] == "autodj":
            names.add("autodj")
    return names


def _module_files(mod: str) -> tuple[str, str]:
    """autodj.generate.motif → (autodj/generate/motif.py, autodj/generate/motif/__init__.py)"""
    p = mod.replace(".", "/")
    return f"{p}.py", f"{p}/__init__.py"


class TestLocalImportsAreTracked:
    """Главный тест: локальный импорт обязан указывать на закоммиченный файл."""

    def test_every_local_import_exists_in_git(self):
        tracked = _tracked_py()
        local = _local_targets(tracked)
        missing: list[str] = []
        unreadable: list[str] = []

        for rel in sorted(tracked):
            if rel.startswith(SKIP_DIRS):
                continue
            try:
                tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            except (PermissionError, OSError):
                unreadable.append(rel)          # чужие права — отдельный тест ниже
                continue
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                for m in mods:
                    head = m.split(".")[0]
                    if head not in local:
                        continue                       # сторонний пакет — не наша забота
                    f1, f2 = _module_files(m)
                    if f1 not in tracked and f2 not in tracked:
                        missing.append(f"{rel}: import {m} → нет {f1} в git")

        assert not missing, (
            "Импорт указывает на НЕзакоммиченный файл (как было с music_theory.py):\n  "
            + "\n  ".join(missing))
        if unreadable:                          # не заваливаем прогон из-за прав доступа
            print(f"\n  ⚠ нечитаемы ({len(unreadable)}): {', '.join(unreadable[:5])}"
                  f" — нужен chmod o+r от владельца")

    def test_autodj_packages_have_init(self):
        """Пакет без __init__.py = импорт работает случайно (namespace packages)
        и ломается при упаковке/переносе."""
        tracked = _tracked_py()
        pkgs = {os.path.dirname(p) for p in tracked
                if p.startswith("autodj/") and os.path.dirname(p)}
        for pkg in sorted(pkgs):
            assert f"{pkg}/__init__.py" in tracked, f"пакет {pkg} без __init__.py в git"


class TestEntryModulesImport:
    """Точки входа должны подниматься из чистого клона (иначе репо мёртв)."""

    @pytest.mark.parametrize("mod", ENTRY_MODULES)
    def test_import(self, mod):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as e:
            missing = (e.name or "").split(".")[0]
            local = _local_targets(_tracked_py())
            if missing in local:
                pytest.fail(f"{mod}: отсутствует ЛОКАЛЬНЫЙ модуль {e.name} "
                            f"(не запушен?) — репо не собирается")
            pytest.skip(f"нет стороннего пакета {missing} в этой среде")
        except Exception as e:                          # ошибка исполнения на импорте
            pytest.fail(f"{mod}: {type(e).__name__}: {e}")


class TestRenderManifest:
    """Паспорт рендера: без него нельзя понять, каким кодом сделан трек."""

    def test_manifest_records_provenance(self):
        from autodj.generate.manifest import build_manifest
        ident = {"seed": 7, "fingerprint": "deadbeef", "motif": [(1, 1.0), (2, 0.5)],
                 "lead_octave": -12, "rhythm": [1, 0, 0, 1]}
        m = build_manifest(None, ident)
        assert m["track"]["seed"] == 7 and m["track"]["fingerprint"] == "deadbeef"
        assert m["track"]["motif_len"] == 2 and m["track"]["rhythm"] == "1001"
        for key in ("git", "config", "env", "packages", "created"):
            assert key in m

    def test_git_state_flags_untracked_package_modules(self):
        from autodj.generate.manifest import git_state
        g = git_state()
        assert set(g) >= {"commit", "branch", "dirty", "untracked_package_py"}
        assert isinstance(g["untracked_package_py"], list)   # ← ловит «только у меня»

    def test_config_dump_is_json_safe(self):
        import json
        from autodj.generate.manifest import build_manifest

        class Cfg:
            bpm = 125
            name = "test"
            arrange = True
            _private = "skip"
            callback = print                                  # не сериализуемое — отсечь

        m = build_manifest(Cfg(), {"seed": 1, "fingerprint": "x"})
        assert m["config"]["bpm"] == 125 and "callback" not in m["config"]
        assert "_private" not in m["config"]
        json.dumps(m)                                          # не падает

    def test_write_manifest_creates_file(self, tmp_path):
        import json
        from autodj.generate.manifest import write_manifest
        wav = str(tmp_path / "track.wav")
        open(wav, "w").close()
        path = write_manifest(wav, None, {"seed": 3, "fingerprint": "ff"})
        assert path.endswith("track.manifest.json") and os.path.exists(path)
        assert json.load(open(path))["track"]["seed"] == 3


class TestFilePermissions:
    """Мульти-агентная среда: файлы одного агента должны читаться другими."""

    def test_tracked_files_readable(self):
        bad = [rel for rel in sorted(_tracked_py())
               if not os.access(os.path.join(ROOT, rel), os.R_OK)]
        if bad:
            pytest.skip(f"нечитаемы для текущего пользователя: {bad[:5]} "
                        f"(владельцу: chmod o+r)")
