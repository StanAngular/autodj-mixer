"""Unit tests for orchestrate.py pure cores (P30, offline)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import orchestrate as orch


def _stages(plan):
    return [s for s, _ in plan]


class TestBuildPlanPathB:
    def test_full_chain_order(self):
        plan = orch.build_plan("euro", path="b", artists="WADE,ANOTR",
                               bpm_min=122, bpm_max=128, source="youtube")
        st = _stages(plan)
        # порядок ключевых стадий
        assert st == ["seedlist", "discover", "resolve", "prescreen", "download",
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
        plan = orch.build_plan("x", path="b", artists="A", cleanup=False, source="youtube")
        res = orch.run_plan(plan, execute=False)
        assert res["executed"] is False
        out = capsys.readouterr().out
        assert "DRY-RUN" in out and "seed_discover.py" in out


# ── P32: лимиты в плане ─────────────────────────────────────────────────────

class TestPlanCaps:
    def test_seedlist_has_limit(self):
        plan = orch.build_plan("x", path="b", artists="A", seed_limit=20, source="youtube")
        sl = dict(plan)["seedlist"]
        assert "--limit" in sl and "20" in sl
    def test_prescreen_has_caps(self):
        plan = orch.build_plan("x", path="b", artists="A", max_probe=25, target=12)
        psr = dict(plan)["prescreen"]
        assert "--max-probe" in psr and "25" in psr and "--target" in psr and "12" in psr


class TestSourceBeatport:
    def test_beatport_stage_replaces_seedlist(self):
        plan = orch.build_plan("x", path="b", style="deep trance", source="beatport")
        st = [s for s, _ in plan]
        assert "beatport" in st and "seedlist" not in st and "discover" not in st
    def test_beatport_then_resolve_prescreen(self):
        st = [s for s, _ in orch.build_plan("x", style="trance", source="beatport")]
        assert st[0] == "beatport" and "resolve" in st and "prescreen" in st


class TestSortFlag:
    def test_sort_in_beatport_stage(self):
        plan = orch.build_plan("x", style="trance", source="beatport", sort="newest")
        bp_argv = dict(plan)["beatport"]
        assert "--sort" in bp_argv and "newest" in bp_argv
    def test_sort_in_compose_stage(self):
        plan = orch.build_plan("x", style="trance", source="auto", sort="bestsellers")
        assert "bestsellers" in dict(plan)["compose"]
    def test_no_sort_no_flag(self):
        plan = orch.build_plan("x", style="trance", source="beatport")
        assert "--sort" not in dict(plan)["beatport"]


class TestRemixFlag:
    def test_remix_in_default_compose(self):
        # дефолт auto → remix уходит в compose
        plan = orch.build_plan("x", artists="Lana Del Rey", remix=True)
        assert "--remix" in dict(plan)["compose"]
    def test_remix_in_youtube_discover(self):
        plan = orch.build_plan("x", artists="Lana Del Rey", remix=True, source="youtube")
        assert "--remix" in dict(plan)["discover"]
    def test_no_remix_no_flag(self):
        plan = orch.build_plan("x", artists="Lana Del Rey", source="youtube")
        assert "--remix" not in dict(plan)["discover"]


class TestDefaultAutoP46:
    def test_default_is_compose(self):
        st = [s for s, _ in orch.build_plan("x", style="deep trance")]
        assert st[0] == "compose" and "seedlist" not in st
    def test_youtube_override_style_gate(self):
        disc = dict(orch.build_plan("x", style="tech house", source="youtube"))["discover"]
        assert "--verify-style" in disc and "tech house" in disc


class TestTracklistInput:
    def test_tracklist_skips_discovery(self):
        st = [s for s, _ in orch.build_plan("x", tracklist="/tmp/tl.txt")]
        assert st[0] == "tracklist" and "seedlist" not in st and "compose" not in st
    def test_tracklist_feeds_file(self):
        tl = dict(orch.build_plan("x", tracklist="/tmp/tl.txt"))["tracklist"]
        assert "tracklist_source.py" in tl and "/tmp/tl.txt" in tl
    def test_tracklist_still_resolves_and_mixes(self):
        st = [s for s, _ in orch.build_plan("x", tracklist="/tmp/tl.txt")]
        assert "resolve" in st                     # дыры без меты добьёт каскад/local_enrich
