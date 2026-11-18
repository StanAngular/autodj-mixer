"""P142: the reference's plan in numbers (blueprint.py) — Стас 2026-11-18: «даю ему другие треки и прошу их воссоздать ... не всегда
получается ... может не хватает инструментов»."""
import json, textwrap
import numpy as np
import pytest
from scipy.signal import butter, sosfilt
from autodj.compose import Track, mono2, chords as C, blueprint as B

SR = 44100
TL = [(0, 8, "intro", {"kick": 1, "pad": 1}), (8, 20, "home1", {"kick": 1, "hats": 1, "bass": 1, "pad": 1}),
      (20, 28, "break", {"pad": 1, "_break": 1}), (28, 40, "home2", {"kick": 1, "hats": 1, "bass": 1, "pad": 1})]

def make(path, bpm=124, seed=1, lowmid_db=0.0, busy=True):
    """a small track with a known plan: 4 sections, chords from chords.Plan, kick on the beat, hats on the off-beats"""
    trk = Track(bpm, 40, seed=seed, humanize_s=0).sections(TL); plan = C.Plan.build("A", TL, "minor_plagal", "lament", seed=seed, rhythm=2).attach(trk)
    rng = np.random.default_rng(seed); t = np.arange(int(.3 * SR)) / SR; f = 50 + 100 * np.exp(-t / .03)
    kick = mono2((np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .12)).astype(np.float32))
    hat = mono2((sosfilt(butter(2, 7000, "high", fs=SR, output="sos"), rng.normal(0, 1, 2000)) * np.exp(-np.arange(2000) / 300) * .3).astype(np.float32))
    k, h, pad, bass = trk.buf(), trk.buf(), trk.buf(), trk.buf(); tt = trk.tt
    for b in range(40):
        for st in range(16):
            if st % 4 == 0: trk.place(k, kick, trk.t(b, st))
            if st % 4 == 2 or (busy and st % 2 == 1 and rng.random() < .5): trk.place(h, hat, trk.t(b, st), .8)
    for s0, n, ms in plan.voicings("drop2", 52, 72, 4):
        a, e = int(s0 * trk.S16 * SR), int((s0 + n) * trk.S16 * SR); w = np.minimum(1, (tt[a:e] - tt[a]) / .05) * np.minimum(1, (tt[e - 1] - tt[a:e]) / .05 + 1e-3)
        for m in ms: pad[a:e] += mono2((.1 * np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * tt[a:e]) * w).astype(np.float32))
        mb = 33 + (plan.at(s0).bass_pc - 33) % 12; bass[a:e] += mono2((.3 * np.sin(2 * np.pi * 440 * 2 ** ((mb - 69) / 12) * tt[a:e]) * w).astype(np.float32))
    trk.add("kick", k, 1.0); trk.add("hats", h); trk.add("pad", pad); trk.add("bass", bass)
    if lowmid_db:
        from pedalboard import Pedalboard, PeakFilter
        trk.mix[:] = Pedalboard([PeakFilter(300, lowmid_db, 1.0)])(trk.mix.T.copy(), SR).T
    trk.finish(str(path)); return plan

@pytest.fixture(scope="module")
def ref(tmp_path_factory):
    d = tmp_path_factory.mktemp("bp"); plan = make(d / "ref.wav")
    return str(d / "ref.wav"), plan, d

def test_read_finds_tempo_key_sections_and_chords(ref):
    path, plan, _ = ref; bp = B.read(path)
    assert abs(bp["bpm"] - 124) < .5 and bp["key"] == "A minor" and bp["bars"] == 40
    cuts = [s["bars"][0] for s in bp["sections"][1:]]
    for want in (8, 20, 28): assert any(abs(c - want) <= 1 for c in cuts), (want, cuts)
    L = {tuple(s["bars"]): s["letter"] for s in bp["sections"]}; h1 = next(v for k, v in L.items() if k[0] == 8); h2 = next(v for k, v in L.items() if k[0] == 28)
    assert h1 == h2                                                                         # home1 and home2 are the same material
    ok = 0
    for b, x in enumerate(bp["per_bar"]):
        name = x["chord"]; root = next(i for i, n in enumerate(["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]) if name.startswith(n) and not name[len(n):len(n) + 1] in ("b", "#"))
        q = name[len(["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"][root]):]; pcs = {(root + i) % 12 for i in B.QUAL[q]}
        ok += pcs <= set(plan.at(b * 16).pcs)                                              # the chord read is inside the real one
    assert ok >= .8 * bp["bars"]
    assert json.load(open(path + ".blueprint.json"))["key"] == "A minor"

def test_compare_names_what_differs(ref):
    path, _, d = ref; make(d / "ours.wav", lowmid_db=9.0, busy=False)
    same = B.compare(path, path); assert same["score"] == 1.0 and same["notes"] == []
    c = B.compare(str(d / "ours.wav"), path)
    assert c["score"] < .95 and c["diff"]["bands_db"]["lowmid"] >= 2.0
    assert any("150-400" in n and "больше" in n for n in c["notes"])

def test_match_eq_moves_toward_the_reference(ref):
    path, _, d = ref
    if not (d / "ours.wav").exists(): make(d / "ours.wav", lowmid_db=9.0, busy=False)
    curve = dict(B.match_eq(str(d / "ours.wav"), path, amount=1.0))
    assert curve.get(250, 0) < -1.0 and curve.get(500, 0) < 0
    import soundfile as sf
    from pedalboard import Pedalboard
    x, sr = sf.read(str(d / "ours.wav"), dtype="float32"); y = Pedalboard(B.eq_plugins(list(curve.items())))(x.T.copy(), sr).T
    dist = lambda z: float(np.abs(B._ltas(z) - B._ltas(path)).mean())
    assert dist(y) < .8 * dist(x)

def test_form_stats_count_changes_and_runs():
    v = np.eye(4); vecs = [v[0]] * 8 + [v[1]] * 4 + [v[0]] * 4 + [v[2]] * 4
    f = B.form_stats(vecs, np.array([-20] * 8 + [-14] * 12))
    assert f["longest_same_run_bars"] == 7 and f["change_every_bars"] == round(20 / 3, 1) and f["new_material_share"] == .1 and f["loudness_travel_db"] == 6.0

def test_run_compares_with_the_reference_and_matches_its_balance(ref, tmp_path):
    path, _, _ = ref
    from autodj.compose.run import main
    import autodj.compose.run as R; R.REGISTRY = str(tmp_path / "reg.jsonl")
    score = tmp_path / "s.py"
    score.write_text(textwrap.dedent(f'''
        import numpy as np
        from autodj.compose import Track, mono2
        META = {{"title": "Ref Test", "target": -16, "reference": {path!r}, "match_eq": .5}}
        def build(seed):
            trk = Track(124, 16, seed=seed).sections([(0, 16, "home", {{"pad": 1}})])
            x = mono2((np.sin(2 * np.pi * 220 * trk.tt) * np.minimum(trk.tt / .02, 1) * .2).astype(np.float32)); trk.add("pad", x, .5); return trk
    '''))
    s = main(["run", str(score), "--seed", "1", "--outdir", str(tmp_path)])
    assert 0 <= s["reference"]["score"] <= 1 and s["reference_notes"][0].startswith("эталон: похожесть") and isinstance(s["match_eq"], list)
