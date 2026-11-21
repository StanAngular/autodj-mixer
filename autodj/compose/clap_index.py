"""P152 (2026-11-21, step 5 of the order of work, ledger #20): CLAP sample index. LAION `clap-htsat-unfused` (Apache 2.0, ~600 MB, CPU, transformers; larger_clap_music was tried first and gives collapsed embeddings here)
puts every audio file and every text into one embedding space: search a sound by what it SOUNDS like ("short dry punchy techno kick", "dusty noise
texture"), or find sounds similar to one you already chose. CLAP only PROPOSES candidates: pitch / noise / wobble stay with soundgate.pick and
soundq, the final choice stays with the score (and Стас). Nothing here changes a render by itself.

    python -m autodj.compose.clap_index build [--root ~/samples] [--limit N] [--shard 256]   resumable: finished shards are kept, bad files are skipped
    python -m autodj.compose.clap_index search "short dry punchy techno kick" [-k 20] [--min-dur .05 --max-dur .6]
    python -m autodj.compose.clap_index similar /path/to/sample.wav [-k 20]
    python -m autodj.compose.clap_index status

In a score:  from autodj.compose import clap_index as CI;  CI.search("soft closed hi-hat", k=20)  ->  [(path, score, dur_s)]
Index: shared/clap_index/shard_NNNN.npz (paths, float16 embeddings, durations); override the folder with env AUTODJ_CLAP_INDEX."""
import argparse, glob, os, signal, sys, time
import numpy as np

MODEL = "laion/clap-htsat-unfused"   # NOT larger_clap_music: its embeddings collapse under transformers 4.57 (text-text cosine 1.0, tested 2026-11-21)
SR = 48000; CLIP_S = 10.0
EXT = (".wav", ".flac", ".aif", ".aiff", ".ogg", ".mp3")
INDEX = "/opt/autodj-mixer/shared/clap_index"
def index_dir(path=None): return path or os.environ.get("AUTODJ_CLAP_INDEX") or INDEX

_M = {}
def model():
    """(ClapModel, ClapProcessor), loaded once; torch threads = all cores"""
    if not _M:
        import torch; from transformers import ClapModel, ClapProcessor
        _M["m"] = ClapModel.from_pretrained(MODEL).eval(); _M["p"] = ClapProcessor.from_pretrained(MODEL); _M["t"] = torch
    return _M["m"], _M["p"]

def load_audio(path, clip_s=CLIP_S):
    """(mono float32 at 48 kHz, duration of the whole file in s); only the first clip_s seconds are read"""
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    with sf.SoundFile(path) as f:
        sr, n = f.samplerate, f.frames; x = f.read(int(min(n, clip_s * sr)), dtype="float32", always_2d=True)
    x = x.mean(1)
    if sr != SR: g = gcd(SR, sr); x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x, n / sr

def _norm(a): return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)

def embed_audio(arrays):
    """list of mono 48 kHz arrays -> (n, 512) unit vectors"""
    m, p = model(); t = _M["t"]
    inp = p(audio=[a for a in arrays], sampling_rate=SR, return_tensors="pt", padding=True)
    with t.no_grad(): e = m.get_audio_features(**{k: v for k, v in inp.items() if k in ("input_features", "is_longer")})
    return _norm(e.numpy().astype(np.float32))

def embed_text(texts):
    m, p = model(); t = _M["t"]; inp = p(text=list(texts), return_tensors="pt", padding=True)
    with t.no_grad(): e = m.get_text_features(**inp)
    return _norm(e.numpy().astype(np.float32))

def scan(root):
    out = []
    for dp, dn, fs in os.walk(os.path.expanduser(root)):
        dn[:] = [d for d in dn if not d.startswith(".")]
        out += [os.path.join(dp, f) for f in fs if f.lower().endswith(EXT) and not f.startswith(".")]
    return sorted(out)

def load_index(path=None):
    """(paths list, embeddings (n,512) float32, durations (n,)) of all shards"""
    files = sorted(glob.glob(os.path.join(index_dir(path), "shard_*.npz")))
    if not files: return [], np.zeros((0, 512), np.float32), np.zeros(0, np.float32)
    P, E, D = [], [], []
    for f in files:
        z = np.load(f, allow_pickle=False); P += z["paths"].tolist(); E.append(z["emb"].astype(np.float32)); D.append(z["dur"])
    return P, np.concatenate(E), np.concatenate(D)

def _rank(P, E, D, q, k, min_dur, max_dur, exclude=None, per_dir=None):
    """per_dir: at most this many results from one folder (a multisample library lists one sound as dozens of near-identical files)"""
    s = E @ q; ok = np.ones(len(P), bool)
    if min_dur is not None: ok &= D >= min_dur
    if max_dur is not None: ok &= D <= max_dur
    s = np.where(ok, s, -9)
    out, seen = [], {}
    for i in np.argsort(-s):
        if s[i] <= -9 or len(out) >= k: break
        if P[i] == exclude: continue
        d = os.path.dirname(P[i])
        if per_dir and seen.get(d, 0) >= per_dir: continue
        seen[d] = seen.get(d, 0) + 1; out.append((P[i], round(float(s[i]), 3), round(float(D[i]), 2)))
    return out

def search(text, k=20, min_dur=None, max_dur=None, path=None, contains=None, per_dir=None):
    """text -> the k best files [(path, cosine, duration_s)]; contains: keep only paths with this substring (e.g. "Kicks")"""
    P, E, D = load_index(path)
    if contains:
        keep = [i for i, p in enumerate(P) if contains.lower() in p.lower()]; P, E, D = [P[i] for i in keep], E[keep], D[keep]
    return _rank(P, E, D, embed_text([text])[0], k, min_dur, max_dur, per_dir=per_dir) if len(P) else []

def similar(sample, k=20, min_dur=None, max_dur=None, path=None, per_dir=None):
    """files that sound like `sample` (an indexed path or any audio file), the sample itself excluded"""
    P, E, D = load_index(path); x, _ = load_audio(sample)
    return _rank(P, E, D, embed_audio([x])[0], k, min_dur, max_dur, exclude=sample, per_dir=per_dir) if len(P) else []

class _Timeout(Exception): pass
def _alarm(sig, frm): raise _Timeout()

def build(root="~/samples", limit=None, shard=256, batch=16, path=None, per_file_s=30, log=print):
    """index every audio file under root that is not in the index yet; one shard per `shard` files, saved as soon as it is full (resumable).
    A file that fails or takes longer than per_file_s is skipped and listed in bad.txt. Prints a progress line per shard."""
    d = index_dir(path); os.makedirs(d, exist_ok=True)
    done = set(load_index(path)[0]); todo = [f for f in scan(root) if f not in done]
    if limit: todo = todo[:limit]
    n0 = len(glob.glob(os.path.join(d, "shard_*.npz"))); t0 = time.time(); total = len(todo); log(f"clap build: {total} files to do, {len(done)} already indexed")
    signal.signal(signal.SIGALRM, _alarm); bad = open(os.path.join(d, "bad.txt"), "a")
    for si, a in enumerate(range(0, total, shard)):
        chunk = todo[a:a + shard]; P, E, D = [], [], []
        for b in range(0, len(chunk), batch):
            arrs, names, durs = [], [], []
            for f in chunk[b:b + batch]:
                signal.alarm(per_file_s)
                try: x, dur = load_audio(f); assert len(x) > 64; arrs.append(x); names.append(f); durs.append(dur)
                except Exception as e: bad.write(f"{f}\t{type(e).__name__}\n"); bad.flush()
                finally: signal.alarm(0)
            if not arrs: continue
            try:
                signal.alarm(per_file_s * len(arrs)); e = embed_audio(arrs); signal.alarm(0); P += names; E.append(e); D += durs
            except Exception as ex:
                signal.alarm(0)
                for f in names: bad.write(f"{f}\tembed:{type(ex).__name__}\n")
                bad.flush()
        if P:
            out = os.path.join(d, f"shard_{n0 + si:04d}.npz"); np.savez(out + ".tmp.npz", paths=np.array(P), emb=np.concatenate(E).astype(np.float16), dur=np.array(D, np.float32)); os.replace(out + ".tmp.npz", out)
        el = time.time() - t0; fin = min(total, a + shard)
        log(f"shard {n0 + si}: {fin}/{total} files, {el / 60:.1f} min, eta {el / max(1, fin) * (total - fin) / 60:.0f} min")
    log("clap build: done"); return total

def main(argv=None):
    ap = argparse.ArgumentParser(prog="autodj.compose.clap_index"); sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--root", default="~/samples"); b.add_argument("--limit", type=int); b.add_argument("--shard", type=int, default=256); b.add_argument("--batch", type=int, default=16)
    s = sub.add_parser("search"); s.add_argument("text"); s.add_argument("-k", type=int, default=20); s.add_argument("--min-dur", type=float); s.add_argument("--max-dur", type=float); s.add_argument("--contains"); s.add_argument("--per-dir", type=int)
    m = sub.add_parser("similar"); m.add_argument("path"); m.add_argument("-k", type=int, default=20); m.add_argument("--min-dur", type=float); m.add_argument("--max-dur", type=float); m.add_argument("--per-dir", type=int)
    sub.add_parser("status"); a = ap.parse_args(argv)
    if a.cmd == "build": build(a.root, a.limit, a.shard, a.batch)
    elif a.cmd == "search":
        for r in search(a.text, a.k, a.min_dur, a.max_dur, contains=a.contains, per_dir=a.per_dir): print(*r, sep="\t")
    elif a.cmd == "similar":
        for r in similar(a.path, a.k, a.min_dur, a.max_dur, per_dir=a.per_dir): print(*r, sep="\t")
    else:
        P, E, D = load_index(); bad = os.path.join(index_dir(), "bad.txt"); print(f"{len(P)} files indexed, {len(glob.glob(os.path.join(index_dir(), 'shard_*.npz')))} shards, bad: {sum(1 for _ in open(bad)) if os.path.exists(bad) else 0}")

if __name__ == "__main__": main()
