"""P169-P175: genre card tech_house (palette, deny words, fx plan, similarity report), riffs (stab plan, rolling bass, stabs), tech_house rhythm profile (both sides)"""
import types, numpy as np, pytest, soundfile as sf
from autodj.compose import genres as G, riffs as RF, rhythm_profiles as RP, arrange as A, chords as C

SECS = [(0, 16, "intro"), (16, 32, "home1"), (32, 48, "journey1"), (48, 56, "break"), (56, 64, "build"), (64, 80, "home2"), (80, 96, "outro")]

def test_card_aliases_and_unknown():
    assert G.card("Tech House")["name"] == "tech_house" and G.card("berlin tech house")["default_bpm"] == 128 and G.card("tech_house")["rhythm"] == "tech_house"
    assert G.card("afro house")["name"] == "afro_house" and G.card("UK garage")["name"] == "garage"
    with pytest.raises(ValueError): G.card("polka")

def test_palette_keeps_the_genre_folders_and_refuses_afro_lofi_families():
    c = G.card("tech house")
    assert G.in_palette(G.WA + "Kicks/WART_Kick_5.wav", c, "kick") and G.in_palette(G.T909 + "rolandtr909-hh/Hat.wav", c, "hats")
    assert not G.in_palette(G.S + "tidal-drum-machines/machines/KorgMinipops/korgminipops-misc/Conga-01.wav", c, "perc")          # not in the folders
    assert not G.in_palette(G.WA + "Percussion/WATE_Conga_01.wav", c, "perc") and not G.in_palette(G.WA + "Cymbals/Cabasa.wav", c, "ohat")      # in the folder, denied by name
    assert not G.in_palette(G.WA + "Kicks/WART_Kick_5.wav", c, "hats")                                                            # a folder of another role

def test_candidates_and_pick_stay_inside_the_palette(monkeypatch):
    from autodj.compose import clap_index as CI, fresh, drumq, verdicts
    paths = [G.S + "x/Conga.wav", G.WA + "Claps/WART_Clap_6.wav", G.WA + "Claps/WART_Clap_Conga.wav", G.T909 + "rolandtr909-cp/Clap.wav"]
    monkeypatch.setattr(CI, "candidates", lambda *a, **k: list(paths)); monkeypatch.setattr(drumq, "ok", lambda p, r, task=None: True); monkeypatch.setattr(verdicts, "check", lambda p, r: ([], []))
    c = G.card("tech house"); got = G.candidates(c, "clap"); assert got == [paths[1], paths[3]]
    monkeypatch.setattr(fresh, "pick", lambda cand, rng=None, k=None, title=None, **kw: cand[-1]); assert G.pick(c, "clap") == paths[3]
    monkeypatch.setattr(CI, "candidates", lambda *a, **k: [paths[0]])
    with pytest.raises(ValueError): G.pick(c, "clap")

def test_fx_plan_marks_drops_breaks_and_phrase_ends():
    fx = G.fx_plan(SECS); assert (62, "riser") in fx and (64, "impact") in fx and (48, "downlifter") in fx and (31, "vox") in fx and not any(k == "impact" and b == 16 for b, k in fx)
    assert G.fx_files(G.card("tech house"), "nothing") == []

def test_similarity_is_a_labelled_report(monkeypatch, tmp_path):
    from autodj.compose import clap_index as CI
    p = str(tmp_path / "m.wav"); sf.write(p, np.random.default_rng(0).normal(0, .1, 44100 * 30).astype(np.float32), 44100)
    monkeypatch.setattr(CI, "embed_audio", lambda arrs: np.stack([np.eye(512)[0]] * len(arrs))); monkeypatch.setattr(CI, "embed_text", lambda t: np.stack([np.eye(512)[i] for i in range(len(t))]))
    r = G.similarity(p, ("tech house", "afro house")); assert r == {"tech house": 1.0, "afro house": 0.0}

# ---- riffs ---------------------------------------------------------------------------------------------------------------------------------------------
def test_stab_plan_has_no_progression_one_dark_chord_and_a_move_only_in_journeys():
    P = RF.stab_plan("A", SECS); homes = {c.name for s0, n, c, nm in P.slots if C.role_of(nm) == "home"}; j = {c.name for s0, n, c, nm in P.slots if nm == "journey1"}
    assert homes == {"Am7"} and len(j) == 2 and all(n >= 8 * 16 for s0, n, c, nm in P.slots if C.role_of(nm) == "home")
    assert all(c.qual in ("m7", "maj7") for s0, n, c, nm in P.slots)

def test_rolling_bass_is_short_between_the_kicks_root_led_and_varied_at_phrase_ends():
    P = RF.stab_plan("A", SECS); b = RF.rolling_bass(P, np.random.default_rng(1), lambda bar: (0, 4, 8, 12), 28, 45)
    assert all(l == 1 and 28 <= m <= 45 for s, l, m, v in b) and not any(s % 16 in (0, 4, 8, 12) for s, l, m, v in b)
    roots = sum(1 for s, l, m, v in b if m % 12 == P.at(s).bass_pc); assert roots / len(b) >= .6
    bar = lambda k: tuple(s % 16 for s, *_ in b if s // 16 == k); assert bar(16) == bar(17) and bar(23) != bar(22)              # same riff, a variant on the phrase end
    assert RF.rolling_bass(P, np.random.default_rng(1), None, 28, 45, pattern=[2, 6, 10, 14])[0][0] % 16 == 2

def test_stab_events_follow_energy_and_change_cell_every_8_bars():
    P = RF.stab_plan("A", SECS); arc = A.energy_arc(SECS); ev = RF.stab_events(P, np.random.default_rng(2), SECS, arc)
    assert not [e for e in ev if e[0] < 16 * 16] and [e for e in ev if 16 * 16 <= e[0] < 32 * 16] and not [e for e in ev if 48 * 16 <= e[0] < 56 * 16]

# ---- tech house rhythm ----------------------------------------------------------------------------------------------------------------------------------
def test_tech_house_profile_has_16th_hats_shaker_fills_and_short_open_hat_and_no_afro_perc():
    p = RP.profile("tech house"); assert p["style"] == "tech_house" and p["shaker"] and p["fill_every"] == 8 and p["open_hat_s"][1] <= .3 and p["perc_per_bar"][1] <= 2
    d = A.drum_plan_v2(SECS, A.energy_arc(SECS), p, np.random.default_rng(1)); home = [x for x in d["hats"] if 64 <= x[0] < 80]
    assert {2, 6, 10, 14} <= {s for _, s, v in home} and d["shaker"] and d["fill"] and all(s in (12, 13, 14, 15) for _, s, v in d["fill"])      # P176: 8th hats with accents, the 16th line only when a style asks (hat16)
    assert not [x for x in d["shaker"] if 48 <= x[0] < 56]                                                                  # no shaker in the break
    h = A.drum_plan_v2(SECS, A.energy_arc(SECS), RP.profile("house"), np.random.default_rng(1)); assert h["shaker"] == [] and h["fill"] == []       # house unchanged

def test_role_names_closed_vs_open_hat_and_real_shakers():
    c = G.card("tech house")
    assert G.in_palette(G.WA + "Cymbals/WATE_Hithat_02.wav", c, "hats") and not G.in_palette(G.WA + "Cymbals/WATS_Open_HiHat_05.wav", c, "hats")
    assert G.in_palette(G.WA + "Cymbals/WATS_Open_HiHat_05.wav", c, "ohat") and not G.in_palette(G.WA + "Cymbals/WATE_Hithat_02.wav", c, "ohat")
    assert G.in_palette(G.S + "tidal-drum-machines/machines/KorgT3/korgt3-sh/Shaker-01.wav", c, "shaker") and not G.in_palette(G.S + "tidal-drum-machines/machines/X/x-perc/Tambourine.wav", c, "shaker")

# ---- P176: every genre has a card; the palette differs by genre; Hermes's home sees the same library; the master follows the genre ------------------------------
def test_every_genre_card_resolves_to_a_rhythm_profile_and_has_queries_for_its_roles():
    for n, c in G.CARDS.items():
        assert RP.profile(c["rhythm"])["style"] and c["bpm"][0] <= c["default_bpm"] <= c["bpm"][1] and c["labels"] and "master" in c
        for r in c["dirs"]: assert r in c["query"], (n, r)

def test_the_same_family_is_denied_in_one_genre_and_welcome_in_another():
    conga = G.WA + "Percussion/WATE_Conga_01.wav"
    assert not G.in_palette(conga, G.card("tech house"), "perc") and G.in_palette(conga, G.card("afro house"), "perc")                       # afro house is built on them
    rhodes = G.S + "x/Rhodes_chord.wav"; assert G.palette_problems([rhodes], G.card("techno")) and not G.palette_problems([rhodes], G.card("deep"))
    assert G.palette_problems(["sfz:pianet"], G.card("minimal")) and not G.palette_problems(["sfz:pianet"], G.card("deep"))
    assert G.palette_problems([G.S + "x/Kick_01.wav"], G.card("ambient")) and not G.palette_problems([G.S + "x/Kick_01.wav"], G.card("house"))   # no drums in ambient
    assert G.palette_problems(["/x/WART_Kick_5.wav", "/x/Hat.wav"], G.card("tech house")) == []

def test_hermes_home_paths_are_the_same_library():
    c = G.card("tech house"); assert G.in_palette("/home/hermes/samples/wa_techno/WAV MIDI Presets/Kicks/WART_Kick_5.wav", c, "kick") and G.in_palette(G.WA + "Kicks/WART_Kick_5.wav", c, "kick")
    assert G.S.startswith("/home/cclaw/samples/")

def test_master_defaults_follow_the_genre_and_explicit_values_win():
    t = G.meta_defaults(G.card("tech house")); assert t["target"] == -10.0 and t["master"] == "studio" and t["premaster"] == "clip" and t["premaster_knee"] == -8.0 and t["gates"]["limiter_max_db"] == 9.0
    d = G.meta_defaults(G.card("deep")); assert d["target"] == -14.0 and d["master"] == "warm" and "gates" not in d
    import inspect; from autodj.compose import run; src = inspect.getsource(run.main); assert "meta_defaults" in src and 'meta.get("premaster_knee"' in src
    from autodj.compose import master; assert "knee_db" in inspect.signature(master.premaster).parameters

def test_tech_house_card_carries_the_numbers_measured_on_the_references():
    c = G.card("tech house"); assert c["mix"]["bass_duck_db"] == (-17, -13) and c["mix"]["clap_vs_kick_db"][1] >= -8 and 125 <= 130 <= c["bpm"][1]
    assert RP.profile("tech_house")["swing"] >= .12 and RP.profile("tech_house")["hat_accent_db"] >= 6 and not RP.profile("tech_house")["hat16"]
    assert [1, 2, 5, 6, 9, 10, 13, 14] in RF.PATTERNS and [2, 5, 7, 10, 13, 15] in RF.PATTERNS

def test_pitched_shots_must_pass_soundgate_and_a_second_pitch_detector(monkeypatch):
    from autodj.compose import soundgate as SG, clap_index as CI
    meas = {"/x/ok.wav": {"root": 40.0, "wobble": 3, "noise": .001, "cents": 2, "kind": "note", "pcs": 1}, "/x/wobbly.wav": {"root": 40.0, "wobble": 142, "noise": .001, "cents": 0, "kind": "note", "pcs": 1},
            "/x/octave.wav": {"root": 40.0, "wobble": 3, "noise": .001, "cents": 2, "kind": "note", "pcs": 1}}
    monkeypatch.setattr(SG, "measure", lambda p: meas[p]); monkeypatch.setattr(G, "_true_root", lambda p: 52.0 if "octave" in p else 40.2)
    assert G.tonal_ok("/x/ok.wav") and not G.tonal_ok("/x/wobbly.wav") and not G.tonal_ok("/x/octave.wav")                       # wobble refused; the detectors disagree by an octave: refused
    c = G.card("tech house"); paths = [G.WA + "Synth & Bass Shots/ok.wav", G.WA + "Synth & Bass Shots/wobbly.wav"]
    monkeypatch.setattr(CI, "candidates", lambda *a, **k: list(paths)); monkeypatch.setattr(G, "tonal_ok", lambda p, role="bass": "wobbly" not in p)
    assert G.candidates(c, "bass") == [paths[0]]

def test_pick_kick_goes_through_kicktune(monkeypatch):
    from autodj.compose import kicktune
    monkeypatch.setattr(G, "candidates", lambda *a, **k: ["/x/k.wav"]); monkeypatch.setattr(kicktune, "kick_in_key", lambda cands, tonic, rng=None, title=None, **kw: (cands[0], 2.0))
    assert G.pick_kick(G.card("tech house"), "A") == ("/x/k.wav", 2.0)
