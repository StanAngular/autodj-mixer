"""Unit tests for orchestrate.py pure cores (P30, offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import orchestrate as orch


def _stages(plan):
    return [s for s, _ in plan]


class TestBuildPlanPathB:
    def test_full_chain_order(self):
        plan = orch.build_plan("euro", path="b", artists="WADE,ANOTR",
                               bpm_min=122, bpm_max=128)
        st = _stages(plan)
        # порядок ключевых стадий
        assert st == ["seedlist", "discover", "prescreen", "download",
                      "annotate", "local_enrich", "bridge", "mix", "catalog"]
    def test_requires_seed_source(self):
        try:
            orch.build_plan("x", path="b")
            assert False, "должно требовать style/artists/tag"
        except ValueError:
            pass
    def test_no_prescreen_drops_stage(self):
        st = _stages(orch.build_plan("x", path="b", style="tech house", prescreen=False))
        assert "prescreen" not in st
    def test_cleanup_appended_last(self):
        st = _stages(orch.build_plan("x", path="b", artists="A", cleanup=True))
        assert st[-1] == "cleanup"
    def test_a1f_sets_mode(self):
        plan = orch.build_plan("x", path="b", artists="A", a1f=True)
        mix = dict(plan)["mix"]
        assert "a1f_fast" in mix
    def test_no_a1f_default_mode(self):
        plan = orch.build_plan("x", path="b", artists="A")
        assert "no_a1f" in dict(plan)["mix"]


class TestBuildPlanPathA:
    def test_curate_and_bridge_urls(self):
        st = _stages(orch.build_plan("m", path="a", config="brief.json"))
        assert st[0] == "curate" and "bridge_urls" in st
    def test_requires_config(self):
        try:
            orch.build_plan("m", path="a")
            assert False
        except ValueError:
            pass


class TestSummarizeStage:
    def test_last_nonempty_line(self):
        out = "lots of logs\nmore logs\nКаталог: зарегистрировано 18\n\n"
        assert orch.summarize_stage(out) == "Каталог: зарегистрировано 18"
    def test_empty(self):
        assert orch.summarize_stage("") == "(нет вывода)"


class TestRunPlanDryRun:
    def test_dry_run_does_not_execute(self, capsys):
        plan = orch.build_plan("x", path="b", artists="A", cleanup=False)
        res = orch.run_plan(plan, execute=False)
        assert res["executed"] is False
        out = capsys.readouterr().out
        assert "DRY-RUN" in out and "seed_discover.py" in out
