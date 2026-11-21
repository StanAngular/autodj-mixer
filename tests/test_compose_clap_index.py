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
