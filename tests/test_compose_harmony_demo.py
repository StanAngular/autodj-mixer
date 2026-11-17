"""P136 / P137: the reference score docs/examples/deep_harmony_demo.py (composition only: no audio is rendered here).
Three harmonies on the same sounds: consonant (default, P137), jazz (the P134 palette), old (the four-chord loop)."""
import importlib.util, io, contextlib, os
import pytest

def _demo(monkeypatch, harm, style="garage", seed=11):
    from autodj.compose.harmony import clashes
    monkeypatch.setenv("AUTODJ_DEMO_SYNTH_KIT", "1"); monkeypatch.setenv("AUTODJ_DEMO_STYLE", style); monkeypatch.setenv("AUTODJ_DEMO_HARMONY", harm)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "examples", "deep_harmony_demo.py")
    spec = importlib.util.spec_from_file_location(f"harmony_demo_{style}_{harm}_{seed}", path); m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(m); trk, plan, lines_, EV = m.write(seed)
    return m, trk, plan, lines_, clashes(trk.notes, trk.S16, min_len_s=trk.S16 * 1.5)[0]

@pytest.mark.parametrize("style", ["garage", "deep", "melodic"])
def test_the_three_harmonies_share_the_form_and_differ_in_the_chords(monkeypatch, style):
    mc, cons, pc, lc, cc = _demo(monkeypatch, "consonant", style); mj, jazz, pj, lj, cj = _demo(monkeypatch, "jazz", style); mo, old, po, lo_, co = _demo(monkeypatch, "old", style)
    assert cons.bars == jazz.bars == old.bars == 96 and cons.tl == jazz.tl == old.tl
    assert pc.palette == "consonant" and pj.palette == "jazz" and mc.META["lead"] == "hook" and "jazz harmony" in mj.META["title"] and "old harmony" in mo.META["title"]
    assert old.harmony["chords"] == 4 and old.harmony["fingerprint"].startswith("0:madd9 8:maj7 5:m7 7:7sus4")
    assert jazz.harmony["chords"] >= 15 and 8 <= cons.harmony["chords"] <= 16                  # more harmony than the loop, far less than the jazz palette
    assert all(set(c.pcs) <= pc.key for _, _, c, _ in pc.slots) and cons.harmony["strength"]["home"] >= .85
    assert cc < .04 and co < .04                                                               # the engine's own clash check
    assert cons.line_fit["hook"]["avoid"] == 0 and cons.line_fit["hook"]["rub"] == 0
    assert set(cons.notes) >= {"bass", "keys", "pad", "hook", "ost", "arp", "top"} and "top" not in old.notes
