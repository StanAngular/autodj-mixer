"""P135: the freshness ledger: which sound sources, drum patterns and progressions earlier tracks already used."""
import json, os, textwrap
import numpy as np
import pytest
from autodj.compose import fresh as F, Track, mono2

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    p = str(tmp_path / "ledger.json"); monkeypatch.setenv("AUTODJ_FRESH_LEDGER", p); F.reset(); return p

def info(src, rh=None, fp=None):
    return {"sources": src, "rhythms": rh or {}, "harmony": {"fingerprint": fp} if fp else None}

def test_sources_are_noted_by_file_name_from_every_loader(tmp_path, ledger):
    import soundfile as sf
    from autodj.compose import load_sample
    w = tmp_path / "pack" / "WART_Kick_5.wav"; os.makedirs(w.parent); sf.write(w, np.zeros(2000, np.float32), 44100)
    load_sample(str(w)); load_sample(str(w)); F.used("sfz:rhodes")
    assert F.USED == {"WART_Kick_5.wav": 2, "sfz:rhodes": 1} and F.key_of("/a/b/c.wav") == "c.wav" and F.key_of("lab:bass-1") == "lab:bass-1"
    F.reset(); assert F.USED == {}

def test_review_counts_only_other_tracks_and_names_worn_sounds(ledger):
    for t in ("One", "Two", "Three"): F.record(info(["WART_Kick_5.wav", "sfz:rhodes", f"own_{t}.wav"]), t)
    r = F.review(info(["WART_Kick_5.wav", "sfz:rhodes", "new_clap.wav", "new_hat.wav"]), "Four")
    assert r["reused"] == {"WART_Kick_5.wav": 3, "sfz:rhodes": 3} and r["worn"] == r["reused"] and r["reuse_share"] == .5 and r["tracks_known"] == 3
    assert any("«WART_Kick_5.wav» уже в 3 прошлых треках" in n for n in r["notes"])
    again = F.review(info(["WART_Kick_5.wav", "own_One.wav"]), "One")                       # a re-render is not counted against itself
    assert again["reused"] == {"WART_Kick_5.wav": 2} and again["worn"] == {} and again["notes"] == []
    fresh = F.review(info(["a.wav", "b.wav"]), "Five"); assert fresh["reuse_share"] == 0 and fresh["notes"] == []

def test_rhythm_and_harmony_repeats_are_found(ledger):
    hat = "..x...x...x...x."
    for t in ("One", "Two", "Three"): F.record(info([], {"hat": hat, "kick": "x...x...x...x..."}, "0:madd9 8:maj7 5:m7 7:7sus4"), t)
    r = F.review(info([], {"hat": hat, "kick": "x.....x...x....."}, "0:madd9 8:maj7 5:m7 7:7sus4"), "Four")
    assert r["rhythm_repeats"] == {"hat": [hat, 3]} and r["harmony_seen"] == ["One", "Two", "Three"]
    assert any("рисунок «hat»" in n for n in r["notes"]) and any("та же последовательность аккордов" in n for n in r["notes"])
    assert F.gates(r, None) == [] and len(F.gates(r, {"fresh_rhythm_max": 0, "fresh_harmony_new": True, "fresh_reuse_max": .3})) == 2

def test_pick_prefers_what_was_used_least(ledger):
    for t in ("One", "Two"): F.record(info(["k1.wav", "k2.wav"]), t)
    F.record(info(["k2.wav"]), "Three"); c = ["/p/k1.wav", "/p/k2.wav", "/p/k3.wav", "/p/k4.wav"]; rng = np.random.default_rng(0)
    assert F.pick(c, rng) in ("/p/k3.wav", "/p/k4.wav") and set(F.pick(c, rng, k=3)) == {"/p/k3.wav", "/p/k4.wav", "/p/k1.wav"}
    assert {F.pick(c, np.random.default_rng(s)) for s in range(12)} == {"/p/k3.wav", "/p/k4.wav"}       # ties are broken at random
    with pytest.raises(ValueError): F.pick([])

def test_drum_patterns_come_from_what_the_layers_played():
    trk = Track(120, 8, seed=1, humanize_s=0).sections([(0, 8, "A", {"kick": 1, "hats": 1, "pad": 1})]); t = np.arange(int(.1 * trk.sr)) / trk.sr
    hit = mono2((np.sin(2 * np.pi * 60 * t) * np.exp(-t / .03)).astype(np.float32)); tick = mono2((np.random.default_rng(0).normal(0, .2, len(t)) * np.exp(-t / .01)).astype(np.float32))
    kb, hb = trk.buf(), trk.buf()
    for br in range(8):
        for st in (0, 4, 8, 12): trk.place(kb, hit, br * trk.BAR + st * trk.S16)
        for st in (2, 6, 10, 14): trk.place(hb, tick, br * trk.BAR + st * trk.S16)
    trk.add("kick", kb, 1.0); trk.add("hats", hb, .3); trk.add("pad", mono2((np.sin(2 * np.pi * 220 * trk.tt) * .1).astype(np.float32)), .2)
    assert F.rhythms(trk) == {"kick": "x...x...x...x...", "hat": "..x...x...x...x."} and F.drum_class("WATE_Shaker") == "shaker" and F.drum_class("pad") is None

def test_scan_bootstraps_history_from_old_scores(tmp_path, ledger):
    a = tmp_path / "music" / "night_shift"; b = tmp_path / "music" / "carthage"; os.makedirs(a); os.makedirs(b)
    (a / "score.py").write_text('K = f"{W}/Kicks/WART_Kick_5.wav"\nrh = SFZ("rhodes")\nbass = oneshot(f"{SH}/WATE_Gm_Bass_01.wav")\n')
    (b / "c2.py").write_text('kick = load_sample(W + "/Kicks/WART_Kick_5.wav")\nrh = SFZ( "rhodes" )\n')
    r = F.scan(str(tmp_path / "music")); db = F.load()
    assert r == {"night_shift": 3, "carthage": 2} and db["tracks"]["legacy:night_shift"]["sources"] == ["WART_Kick_5.wav", "WATE_Gm_Bass_01.wav", "sfz:rhodes"]
    assert F.review(info(["WART_Kick_5.wav"]), "New")["reused"] == {"WART_Kick_5.wav": 2}
    rows = F.main(["top", "--n", "2"]); assert rows[0][0] in ("WART_Kick_5.wav", "sfz:rhodes") and len(rows[0][1]) == 2

def test_run_reports_freshness_and_records_the_track(tmp_path, ledger):
    from autodj.compose.run import main
    import autodj.compose.run as R; R.REGISTRY = str(tmp_path / "reg.jsonl")
    score = tmp_path / "s.py"
    score.write_text(textwrap.dedent('''
        import numpy as np, soundfile as sf, os
        from autodj.compose import Track, mono2, load_sample, chords
        HERE = os.path.dirname(os.path.abspath(__file__)); META = {"title": "Ledger Test", "target": -18}
        def build(seed):
            t = np.arange(4410) / 44100; sf.write(HERE + "/my_kick.wav", (np.sin(2 * np.pi * 60 * t) * np.exp(-t / .03)).astype(np.float32), 44100)
            trk = Track(120, 8, seed=seed).sections([(0, 8, "home", {"kick": 1, "tone": 1})]); k = load_sample(HERE + "/my_kick.wav"); kb = trk.buf()
            for br in range(8):
                for st in (0, 4, 8, 12): trk.place(kb, k, br * trk.BAR + st * trk.S16)
            chords.Plan.build("C", trk.tl, "dorian_vamp", seed=seed).attach(trk)
            trk.add("kick", kb, 1.0); trk.add("tone", mono2((np.sin(2*np.pi*110*trk.tt) * .1).astype(np.float32)), .4); return trk
    '''))
    s1 = main(["run", str(score), "--seed", "1", "--outdir", str(tmp_path)]); db = F.load()
    assert s1["fresh"]["reuse_share"] == 0 and s1["fresh_notes"] == [] and s1["harmony"]["home"] == "dorian_vamp" and "Cm9" in s1["harmony"]["chart"]["home"]
    assert db["tracks"]["Ledger Test"]["sources"] == ["my_kick.wav"] and db["tracks"]["Ledger Test"]["rhythms"]["kick"] == "x...x...x...x..." and db["tracks"]["Ledger Test"]["harmony"].startswith("0:m9 5:13")
    for t in ("A", "B", "C"): F.record(info(["my_kick.wav"], {"kick": "x...x...x...x..."}, db["tracks"]["Ledger Test"]["harmony"]), t)
    s2 = main(["run", str(score), "--seed", "1", "--outdir", str(tmp_path), "--title", "Another One"])
    assert s2["fresh"]["worn"] == {"my_kick.wav": 4} and s2["fresh"]["harmony_seen"] and len(s2["fresh_notes"]) >= 3 and s2["problems"] == s1["problems"]   # notes, not gates
