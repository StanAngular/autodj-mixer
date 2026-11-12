"""P132: the sound lab. A search must (1) only return sounds that work for the role, (2) refuse static and out-of-tune ones,
(3) prefer what is unlike the archive, (4) return candidates unlike each other, (5) learn from votes, (6) never hand one sound to two tracks."""
import json, os
import numpy as np
import pytest
from autodj.compose import soundlab as L
from autodj.compose.synth import Synth, patch

SR = 44100
STATIC = patch(osc=[dict(wave="saw")], filt=dict(cutoff=700, res=.1), drift=0, amp=dict(a=.003, d=.3, s=.8, r=.1, vel=0))

def render(p, role, **kw):
    ev, tot = L.phrase_events(role); return Synth(p, bpm=L.BPM, **kw).render(ev, tot), ev

@pytest.fixture
def arc(tmp_path):
    return L.Archive(str(tmp_path / "lab.json"))

# ---- drawing ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", sorted(L.ROLES))
def test_random_patches_are_valid_serialisable_and_repeatable(role):
    a = L.random_patch(np.random.default_rng(5), role); b = L.random_patch(np.random.default_rng(5), role); c = L.random_patch(np.random.default_rng(6), role)
    assert a == b and a != c and json.loads(json.dumps(a)) == a and 2 <= len(a["mods"]) <= 4
    ev, tot = L.phrase_events(role); x = L.make(a).render(ev[:3], 1.5)
    assert np.isfinite(x).all() and np.abs(x).max() > 1e-4

def test_mutation_stays_in_bounds_and_moves():
    rng = np.random.default_rng(2); p = L.random_patch(rng, "bass"); q = p
    for _ in range(30): q = L.mutate(q, rng, .5, "bass")
    assert q != p and L.BOUNDS["cutoff"][0] <= q["filt"]["cutoff"] <= L.BOUNDS["cutoff"][1] and 0 <= q["filt"]["res"] <= .85
    assert all(L.BOUNDS["amt"][0] <= m["amt"] <= L.BOUNDS["amt"][1] for m in q["mods"]) and p == json.loads(json.dumps(p))   # the parent is untouched

def test_tables_named_in_the_patch_are_rebuilt_from_the_name(tmp_path):
    import soundfile as sf
    t = np.arange(SR) / SR; sf.write(tmp_path / "src.wav", (np.sin(2 * np.pi * 200 * t) + .5 * np.sin(2 * np.pi * 600 * t)).astype(np.float32), SR)
    p = patch(osc=[dict(wave="wt", table="proc:7"), dict(wave="wt", table=f"wav:{tmp_path / 'src.wav'}")])
    T = L.tables_for(p); assert set(T) == {"proc:7", f"wav:{tmp_path / 'src.wav'}"} and np.allclose(T["proc:7"], L.tables_for(p)["proc:7"])
    assert L.make(p).render([(0, 57, 100, .3)], .5).any()
    with pytest.raises(ValueError): L.tables_for(patch(osc=[dict(wave="wt", table="vital:x")]))

# ---- describing -------------------------------------------------------------------------------------------------------
def test_motion_tells_a_living_sound_from_a_static_one():
    live = patch(STATIC, filt=dict(cutoff=250, env=4, vel=2), fenv=dict(a=.001, d=.1, s=0, r=.1), mods=[dict(src="lfo", dst="cutoff", amt=1, rate="1b"), dict(src="rand", dst="cutoff", amt=.4)])
    xs, ev = render(STATIC, "bass"); xl, _ = render(live, "bass"); ds, dl = L.describe(xs, events=ev), L.describe(xl, events=ev)
    assert ds["motion"] < .6 and dl["motion"] > 4.0 and dl["evolve"] > 2.0 and dl["vary"] > ds["vary"] + .5        # dB per band
    assert L.judge(ds, "bass", 0.0)[0] is False and "статичен" in L.judge(ds, "bass", 0.0)[2][0]
    assert L.describe(np.zeros((SR, 2), np.float32)) is None and L.judge(None, "bass")[0] is False

def test_description_separates_dark_bright_soft_sharp_wide_narrow():
    dark, ev = render(patch(STATIC, filt=dict(cutoff=300)), "lead"); bright, _ = render(patch(STATIC, filt=dict(cutoff=6000)), "lead")
    soft, _ = render(patch(STATIC, amp=dict(a=.15)), "lead"); wide, _ = render(patch(STATIC, osc=[dict(wave="saw", unison=5, detune=20, spread=1)]), "lead")
    D = lambda x: L.describe(x, events=ev)
    assert D(bright)["cen"] > D(dark)["cen"] + 1 and D(bright)["tilt"] > D(dark)["tilt"] and D(soft)["attack"] > D(dark)["attack"] + .8
    assert D(wide)["width"] > .2 > D(dark)["width"] and len(L.vector(D(dark))) == len(L.SCALE) + 6
    assert np.linalg.norm(L.vector(D(bright)) - L.vector(D(dark))) > 1.5 > np.linalg.norm(L.vector(D(dark)) - L.vector(D(dark)))

def test_out_of_tune_and_wrong_register_are_refused():
    x, ev = render(patch(STATIC, osc=[dict(wave="saw", cents=60)]), "lead"); y, _ = render(STATIC, "lead")
    assert abs(L.pitch_error_cents(x, 69) - 60) < 8 and abs(L.pitch_error_cents(y, 69)) < 6 and abs(L.pitch_error_cents(y, 57)) < 6    # octaves fold
    d = L.describe(y, events=ev); d["motion"] = 9.0
    assert L.judge(d, "lead", 60.0)[0] is False and L.judge(d, "lead", 3.0)[0] is True and L.judge(d, "lead", None)[2] == ["нет высоты"]
    thin = L.describe(render(patch(STATIC, filt=dict(mode="hp", cutoff=900)), "bass")[0], events=L.phrase_events("bass")[0]); thin["motion"] = 9.0
    assert L.judge(thin, "bass", 0.0)[0] is False                                           # a bass without low end is not a bass
    harsh = dict(d, buzz=2.0); assert L.judge(harsh, "lead", 0.0)[1] < L.judge(d, "lead", 0.0)[1]

# ---- archive ----------------------------------------------------------------------------------------------------------
def _cand(role="bass", seed=1):
    rng = np.random.default_rng(seed)
    while True:
        c = L.evaluate(L.random_patch(rng, role), role)
        if c["ok"]: c.update(novelty=1.0, score=1.0); return c

def test_archive_votes_claims_and_one_sound_one_track(arc):
    c = _cand(); arc.add(c); sid = c["id"]
    assert L.Archive(arc.path).db["sounds"][sid]["patch"] == c["patch"] and arc.fresh("bass") == [sid]
    arc.vote(sid, 1, "качает"); syn = arc.synth(sid, bpm=124, track="Track A")
    assert syn.render([(0, 36, 100, .2)], .5).any() and arc.db["sounds"][sid]["used_in"] == ["Track A"] and arc.fresh("bass") == []
    arc.claim(sid, "Track A")                                                                # the same track again: fine
    with pytest.raises(ValueError, match="already belongs"): arc.claim(sid, "Track B")
    arc.claim(sid, "Track B", reuse=True); assert L.Archive(arc.path).db["sounds"][sid]["used_in"] == ["Track A", "Track B"]
    c2 = _cand(seed=2); arc.add(c2); arc.vote(c2["id"], -1, "дёшево")
    with pytest.raises(ValueError, match="rejected"): arc.claim(c2["id"], "Track C")
    with pytest.raises(ValueError): arc.vote(sid, 5)

def test_recordings_can_be_registered_so_the_lab_keeps_away_from_them(arc):
    x, ev = render(patch(STATIC, mods=[dict(src="lfo", dst="cutoff", amt=1, rate="1b")]), "lead")
    arc.add_audio("wa Lead_Shot_26", x, "lead", verdict=-1, note="дешёвая флейта", events=ev)
    assert arc.vectors("lead", -1)[0][0] == "wa Lead_Shot_26" and arc.fresh("lead") == []
    with pytest.raises(ValueError): arc.synth("wa Lead_Shot_26")

# ---- the search ---------------------------------------------------------------------------------------------------------
def test_search_returns_working_sounds_unlike_each_other_and_is_repeatable(arc):
    out = L.search("bass", n=14, keep=4, seed=3, generations=2, archive=arc); again = L.search("bass", n=14, keep=4, seed=3, generations=2, archive=arc)
    assert 2 <= len(out) <= 4 and [c["id"] for c in out] == [c["id"] for c in again]
    for c in out:
        ok, q, why = L.judge(c["desc"], "bass", 0.0); assert ok and c["desc"]["motion"] >= L.ROLES["bass"]["motion"] and c["novelty"] > 0
    V = np.array([c["vec"] for c in out]); D = np.linalg.norm(V[:, None] - V[None], axis=2)
    assert D[np.triu_indices(len(out), 1)].min() > 1.0 and out[0]["stats"]["rendered"] >= 14
    with pytest.raises(ValueError): L.search("flute", archive=arc)

def test_search_moves_away_from_what_is_in_the_archive_and_from_rejected_sounds(arc):
    first = L.search("pluck", n=12, keep=3, seed=4, generations=1, archive=arc)
    for c in first: arc.add(c)
    arc.vote(first[0]["id"], -1, "дверной звонок"); bad = first[0]["vec"]
    second = L.search("pluck", n=12, keep=3, seed=4, generations=1, archive=arc)                # the same seed, a different archive
    assert not {c["id"] for c in first} & {c["id"] for c in second}                             # nothing is offered twice
    assert all(np.linalg.norm(c["vec"] - bad) >= L.BAD_RADIUS for c in second)
    known = np.array([c["vec"] for c in first])
    assert all(np.linalg.norm(known - c["vec"][None], axis=1).min() > .5 for c in second)

def test_liked_sounds_seed_the_next_search(arc, monkeypatch):
    c = _cand("bass", 7); arc.add(c); arc.vote(c["id"], 1); seen = []
    real = L.mutate; monkeypatch.setattr(L, "mutate", lambda p, *a, **k: (seen.append(p), real(p, *a, **k))[1])
    L.search("bass", n=10, keep=2, seed=1, generations=1, archive=arc)
    assert any(p == c["patch"] for p in seen)                                                    # children of the liked patch were tried

def test_guard_hook_can_veto(arc):
    assert L.search("bass", n=6, keep=3, seed=3, generations=1, archive=arc, guard=lambda x: False) == []

# ---- reel and command line ----------------------------------------------------------------------------------------------
def test_reel_is_blind_level_matched_and_keyed(tmp_path, arc):
    import soundfile as sf
    cs = [_cand("bass", 1), _cand("bass", 2)]; key = L.reel(cs, str(tmp_path / "r.wav")); x, sr = sf.read(tmp_path / "r.wav")
    assert [k["letter"] for k in key] == ["A", "B"] and key[1]["start_s"] > key[0]["end_s"] and json.load(open(str(tmp_path / "r.wav") + ".json")) == key
    seg = lambda k: x[int(k["start_s"] * sr):int(k["end_s"] * sr)]; r = lambda s: 20 * np.log10(np.sqrt(np.mean(s[np.abs(s).max(1) > 1e-4] ** 2)))
    assert abs(r(seg(key[0])) - r(seg(key[1]))) < 1.5 and np.abs(x).max() <= .9

def test_command_line_search_vote_list(tmp_path, capsys):
    a = str(tmp_path / "lab.json"); key = L.main(["search", "bass", "--n", "8", "--keep", "2", "--seed", "3", "--out", str(tmp_path), "--archive", a])
    assert key and os.path.exists(tmp_path / "lab_bass_3.wav") and set(L.Archive(a).db["sounds"]) == {k["id"] for k in key}
    L.main(["vote", key[0]["id"], "1", "тёплый", "--archive", a]); L.main(["claim", key[0]["id"], "Demo", "--archive", a]); L.main(["list", "bass", "--archive", a])
    s = L.Archive(a).db["sounds"][key[0]["id"]]; assert s["verdict"] == 1 and s["used_in"] == ["Demo"] and key[0]["id"] in capsys.readouterr().out
