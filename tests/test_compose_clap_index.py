"""P152 clap_index: scan / build (resumable, bad files skipped) / search filters, with the model replaced by small fake embeddings (both sides)"""
import numpy as np, pytest, soundfile as sf
from autodj.compose import clap_index as CI

def vec(i, n=512):
    v = np.zeros(n, np.float32); v[i] = 1.0; return v

@pytest.fixture
def lib(tmp_path, monkeypatch):
    root = tmp_path / "lib"; (root / "sub").mkdir(parents=True)
    names = {"kick1.wav": 0, "kick2.wav": 0, "clap1.wav": 1, "sub/hat1.wav": 2}
    for n in names: sf.write(root / n, np.sin(np.arange(4800) / 7).astype(np.float32), 48000)
    (root / "broken.wav").write_bytes(b"not audio"); (root / "notes.txt").write_text("x"); (root / ".hidden.wav").write_bytes(b"x")
    kind = {str(root / n): i for n, i in names.items()}
    monkeypatch.setattr(CI, "embed_audio", lambda arrs: np.stack([vec(kind[CI._cur.pop(0)]) for _ in arrs]))
    CI._cur = []; orig = CI.load_audio
    def la(path, clip_s=CI.CLIP_S): x, d = orig(path, clip_s); CI._cur.append(path); return x, d
    monkeypatch.setattr(CI, "load_audio", la)
    monkeypatch.setattr(CI, "embed_text", lambda texts: np.stack([vec({"kick": 0, "clap": 1, "hat": 2}[t]) for t in texts]))
    return root, str(tmp_path / "idx")

def test_scan_takes_audio_only_and_skips_hidden(lib):
    root, _ = lib; got = [p.replace(str(root) + "/", "") for p in CI.scan(str(root))]; assert got == ["broken.wav", "clap1.wav", "kick1.wav", "kick2.wav", "sub/hat1.wav"]

def test_build_indexes_good_files_lists_the_bad_and_is_resumable(lib):
    root, idx = lib; CI.build(str(root), path=idx, shard=2, batch=2, log=lambda *_: None)
    P, E, D = CI.load_index(idx); assert len(P) == 4 and E.shape == (4, 512) and "broken.wav" in open(idx + "/bad.txt").read()
    assert all(abs(d - .1) < .01 for d in D)
    n_shards = len(__import__("glob").glob(idx + "/shard_*.npz")); CI.build(str(root), path=idx, log=lambda *_: None)          # second run: nothing new, no new shard
    assert len(__import__("glob").glob(idx + "/shard_*.npz")) == n_shards and len(CI.load_index(idx)[0]) == 4

def test_search_ranks_by_meaning_and_filters(lib):
    root, idx = lib; CI.build(str(root), path=idx, log=lambda *_: None)
    r = CI.search("kick", 5, path=idx); assert {p.split("/")[-1] for p, *_ in r[:2]} == {"kick1.wav", "kick2.wav"} and r[0][1] > r[2][1]
    assert CI.search("hat", 1, path=idx)[0][0].endswith("sub/hat1.wav") and CI.search("clap", 1, path=idx, contains="sub") != [] 
    assert CI.search("kick", 5, min_dur=5, path=idx) == [] and len(CI.search("kick", 5, max_dur=1, path=idx)) == 4          # duration filter both ways

def test_empty_index_gives_empty_results(tmp_path):
    assert CI.search("kick", 3, path=str(tmp_path / "none")) == []

def test_per_dir_limits_results_from_one_folder_and_default_keeps_all(lib):
    root, idx = lib; CI.build(str(root), path=idx, log=lambda *_: None)
    assert len(CI.search("kick", 4, path=idx)) == 4
    r = CI.search("kick", 4, path=idx, per_dir=1); dirs = [p.rsplit("/", 1)[0] for p, *_ in r]; assert len(dirs) == len(set(dirs)) and len(r) == 2      # root folder once, sub folder once

def _fake_index(tmp_path, monkeypatch):
    d = tmp_path / "fidx"; d.mkdir(); P = [f"/x/a/kick{i}.wav" for i in range(3)] + [f"/x/b/hat{i}.wav" for i in range(3)] + ["/x/c/pad.wav"]
    E = np.stack([vec(0) * .9 + vec(3) * .1 * i for i in range(3)] + [vec(2) * .9 + vec(4) * (.1 + .1 * i) for i in range(3)] + [vec(5)])
    E = E / np.linalg.norm(E, axis=1, keepdims=True); np.savez(d / "shard_0000.npz", paths=np.array(P), emb=E.astype(np.float16), dur=np.array([.3] * 6 + [8.0], np.float32))
    monkeypatch.setattr(CI, "embed_text", lambda texts: np.stack([vec({"kick": 0, "hat": 2, "pad": 5}[t]) for t in texts])); CI._IDX.clear(); return str(d), P

def test_candidates_by_text_by_near_and_both(tmp_path, monkeypatch):
    d, P = _fake_index(tmp_path, monkeypatch)
    assert all("kick" in p for p in CI.candidates("kick", 2, per_dir=None, path=d))
    near = CI.candidates(near=["/x/b/hat0.wav"], k=2, per_dir=None, path=d); assert all("hat" in p for p in near) and "/x/b/hat0.wav" not in near    # sounds like the chosen hat, the hat itself excluded
    mix = CI.candidates("hat", 3, near=["/x/a/kick0.wav"], near_weight=.3, per_dir=None, path=d); assert "hat" in mix[0]                               # text leads, near only re-orders
    assert CI.candidates("pad", 3, max_dur=1, per_dir=None, path=d)[0] != "/x/c/pad.wav"                                                                 # filters still apply
    with pytest.raises(ValueError): CI.candidates(path=d)

def test_pick_goes_through_soundgate_and_fresh(tmp_path, monkeypatch):
    d, P = _fake_index(tmp_path, monkeypatch); from autodj.compose import soundgate as SG
    seen = {}
    def fake_pick(c, **kw): seen["c"] = c; seen["kw"] = kw; return c[-1]
    monkeypatch.setattr(SG, "pick", fake_pick)
    monkeypatch.setattr(CI, "index_dir", lambda path=None: d); monkeypatch.setattr(CI, "sound_roles", lambda path=None: np.array(["kick"] * 3 + ["hats"] * 3 + ["pad"]))
    monkeypatch.setattr(CI, "embed_text", lambda texts: np.stack([vec({"kick": 0, "hat": 2, "pad": 5}[t]) for t in texts]))
    r = CI.pick("pad", role="pad", top=2, per_dir=None, margin=None); assert r in seen["c"] and seen["kw"]["role"] == "pad" and "/x/c/pad.wav" in seen["c"]
    monkeypatch.setattr(CI, "candidates", lambda *a, **k: [])
    with pytest.raises(ValueError): CI.pick("nothing")

def test_role_filter_uses_the_zero_shot_label_and_a_contradicting_name_vetoes_it(tmp_path, monkeypatch):
    d, P = _fake_index(tmp_path, monkeypatch); labels = np.array(["kick", "kick", "kick", "hats", "hats", "cymbal", "pad"])
    monkeypatch.setattr(CI, "sound_roles", lambda path=None: labels)
    assert set(CI.candidates("kick", 9, role="kick", per_dir=None, path=d)) == set(P[:3])
    assert set(CI.candidates("hat", 9, role="hats", per_dir=None, path=d)) == set(P[3:6])                      # hats family takes the cymbal too
    labels[1] = "kick"; P2 = list(P); 
    monkeypatch.setattr(CI, "_index", lambda path=None: (P[:1] + ["/x/a/Synth_Shot_10.wav"] + P[2:], *CI.load_index(d)[1:], {}))
    assert "/x/a/Synth_Shot_10.wav" not in CI.candidates("kick", 9, role="kick", per_dir=None, path=d)          # the name says synth: vetoed
    assert CI.candidates("kick", 9, role=None, per_dir=None, path=d)                                           # no role: no filter

def test_drums_skip_the_pitch_gate_and_tonal_roles_go_through_it(tmp_path, monkeypatch):
    d, P = _fake_index(tmp_path, monkeypatch); from autodj.compose import soundgate as SG, fresh
    monkeypatch.setattr(CI, "index_dir", lambda path=None: d); monkeypatch.setattr(CI, "sound_roles", lambda path=None: np.array(["kick"] * 3 + ["hats"] * 3 + ["pad"]))
    calls = []
    monkeypatch.setattr(SG, "pick", lambda c, **kw: calls.append("sg") or c[0]); monkeypatch.setattr(fresh, "pick", lambda c, rng=None, k=None, title=None, **kw: calls.append("fresh") or c[0])
    CI.pick("kick", role="kick", per_dir=None); assert calls == ["fresh"]
    calls.clear(); CI.pick("pad", role="pad", per_dir=None); assert calls == ["sg"]
