"""P136: the reference score docs/examples/deep_harmony_demo.py (composition only: no audio is rendered here)."""
import pytest

# ---- P136: the reference score -------------------------------------------------------------------------------------------------
def _demo(monkeypatch, old, style="garage"):
    import importlib.util, os
    from autodj.compose.harmony import clashes
    monkeypatch.setenv("AUTODJ_DEMO_SYNTH_KIT", "1"); monkeypatch.setenv("AUTODJ_DEMO_STYLE", style)
    monkeypatch.setenv("AUTODJ_DEMO_HARMONY", "old") if old else monkeypatch.delenv("AUTODJ_DEMO_HARMONY", raising=False)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "examples", "deep_harmony_demo.py")
    spec = importlib.util.spec_from_file_location(f"harmony_demo_{style}_{old}", path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    trk, plan, lines_, EV = m.write(11); return trk, plan, lines_, clashes(trk.notes, trk.S16, min_len_s=trk.S16 * 1.5)[0]

@pytest.mark.parametrize("style", ["garage", "deep", "melodic"])
def test_harmony_demo_is_rich_and_still_does_not_rub_and_its_old_twin_is_the_four_chord_loop(monkeypatch, style):
    new, pn, ln, cn = _demo(monkeypatch, False, style); old, po, lo_, co = _demo(monkeypatch, True, style)
    assert new.harmony["chords"] >= 15 and old.harmony["chords"] == 4 and old.harmony["fingerprint"].startswith("0:madd9 8:maj7 5:m7 7:7sus4")
    assert cn < .04 and co < .04                                                         # the engine's own clash check, independent of lines.clean
    assert new.line_fit["hook"]["avoid"] == 0 and new.line_fit["hook"]["rub"] == 0 and new.line_fit["hook"]["colour"] > 0
    assert set(new.notes) >= {"bass", "keys", "pad", "hook", "ost", "arp", "top"} and "top" not in old.notes and new.bars == old.bars == 96
    assert len(ln["hook"]) > 80 and len(lo_["hook"]) > 80
