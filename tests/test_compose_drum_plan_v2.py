"""P165 drum_plan_v2 (kit from arc + profile) and P164 checklist, both sides"""
import types, numpy as np, pytest
from autodj.compose import arrange as A, rhythm_profiles as RP, rhythm as R

SECS = [(0, 16, "intro"), (16, 32, "home1"), (32, 48, "journey1"), (48, 52, "break"), (52, 56, "build"), (56, 72, "home2"), (72, 88, "journey2"), (88, 104, "home3"), (104, 120, "outro")]
ARC = A.energy_arc(SECS)
def plan(style, seed=1, **kw): return A.drum_plan_v2(SECS, ARC, RP.profile(style, **{"clap": True, **kw}), np.random.default_rng(seed))
def inbars(ev, a, b): return [x for x in ev if a <= x[0] < b]

@pytest.fixture(autouse=True)
def _reset(): R.set_task(); yield; R.set_task()

def test_house_has_the_whole_kit_with_accents_ghosts_open_hat_and_perc_growing_to_the_peak():
    p = plan("house"); h = inbars(p["hats"], 88, 104)
    strong = [v for _, s, v in h if s in (6, 14)]; weak = [v for _, s, v in h if s in (2, 10)]; assert np.mean(strong) > np.mean(weak) * 1.1                      # accent contrast
    assert any(s in (1, 3, 5, 9, 11, 13) for _, s, v in h) and p["ohat"] and all(l > 0 for *_, l in p["ohat"])                                            # ghosts, open hat with a length
    lens = {b // 16: l for b, s, v, l in p["ohat"]}; lo = np.mean([l for b, s, v, l in p["ohat"] if b < 40]); hi = np.mean([l for b, s, v, l in p["ohat"] if b >= 88]); assert hi > lo   # rings longer at the peak
    assert len(inbars(p["perc"], 88, 104)) > len(inbars(p["perc"], 16, 32))                                                                              # denser at the peak
    assert len(inbars(p["kick"], 88, 104)) <= 16 * 4 + 12                                                                                                 # ... while the kick stays a four

def test_the_kick_breathes_out_before_a_home_and_the_peak_but_never_inside_a_home():
    p = plan("house"); k = p["kick"]
    for peak_bar in (55, 87):                                                       # the bars before home2 / home3
        late = [x for x in inbars(k, peak_bar, peak_bar + 1) if x[1] in (8, 12)]; assert not late, peak_bar
    assert len(inbars(k, 100, 101)) >= 3 and len(inbars(k, 20, 21)) >= 3          # inside a home the four stays
    pk = inbars(p["perc"], 87, 88); assert all(s < 8 for _, s, v in pk)            # perc breathes with the kick
    assert RP.profile("ambient")["dropout_beats"] == 0 and RP.profile("house", dropout_beats=9)["dropout_beats"] == 4

def test_each_style_gets_its_own_kick_family_and_nothing_club_in_ambient():
    g = plan("garage"); a = plan("ambient"); d = plan("downtempo"); h = plan("house")
    assert {s for _, s, v in inbars(g["kick"], 16, 32)} <= {0, 7, 10} and {s for _, s, v in inbars(d["kick"], 16, 32)} <= {0, 6, 10}
    assert {s for _, s, v in inbars(d["clap"], 16, 32)} <= {8} and {4, 12} <= {s for _, s, v in inbars(h["clap"], 88, 104)}
    assert a["hats"] == [] and a["ohat"] == [] and a["clap"] == [] and len(a["kick"]) < len(h["kick"]) / 3

def test_the_clap_has_a_job_by_energy_and_ghosts_only_where_the_profile_wants_them():
    p = plan("deep"); assert not inbars(p["clap"], 0, 16) and not inbars(p["clap"], 48, 52) and any(s == 15 for _, s, v in inbars(p["clap"], 88, 104))     # deep: ghost_backbeat
    assert not any(s == 15 for _, s, v in plan("techno")["clap"])

def test_no_flat_loops_and_plans_are_reproducible_per_seed():
    p = plan("house"); st = A.drum_static(p); assert st["hats"] <= A.DRUM_STATIC_MAX and st["kick"] <= A.DRUM_STATIC_MAX and plan("house", 2) == plan("house", 2) and plan("house", 2) != plan("house", 3)
    assert A.drum_static_problems(types.SimpleNamespace(drum_events=p)) == []
    old = A.drum_plan(SECS, ARC, np.random.default_rng(1)); assert set(old) == {"kick", "clap"}                  # v1 untouched

# ---- P164 checklist ---------------------------------------------------------------------------------------------------------------------------------
def fake_trk(flat):
    E = {"kick": np.full((120 * 16, 4), 1e-12), "hats": np.full((120 * 16, 4), 1e-12)}
    for b in range(120):
        for s in (0, 4, 8, 12): E["kick"][b * 16 + s, 1] = 1e-2 * (1 if flat else (.5 + (b % 4) * .3))
        for s in (2, 6, 10, 14): E["hats"][b * 16 + s, 1] = 1e-3 * (1 if flat or s != 6 else 3)
    return types.SimpleNamespace(act=E, bars=120, tl=SECS, microtiming=None)

def test_checklist_has_six_answers_and_flags_a_flat_track_and_passes_a_lively_one():
    flat = R.checklist(fake_trk(True), {"kick_bass": .13}); lively = R.checklist(fake_trk(False), {"kick_bass": .13})
    assert len(flat) == 6 and [q[0][0] for q in flat] == [str(i) for i in range(1, 7)] and {s for _, s, _ in flat} <= {"ok", "warn", "unknown"}
    st = lambda cl, i: cl[i - 1][1]
    assert st(flat, 4) == "warn" and st(flat, 5) == "warn" and st(lively, 5) == "ok" and st(lively, 4) == "warn"                                          # lively kick, but no breath before the peak: still warns
    assert st(flat, 3) == "ok" and R.checklist(fake_trk(True), {"kick_bass": .9})[2][1] == "warn" and R.checklist(fake_trk(True), {})[2][1] == "unknown"
    assert st(flat, 6) == "unknown" and "✓" in R.checklist_text(flat) + "✓"

def test_style_accuracy_follows_the_task_profile():
    R.set_task(style="house"); assert R.checklist(fake_trk(True), {})[5][1] == "ok"                                 # a four-on-the-floor for house
    R.set_task(style="garage"); assert R.checklist(fake_trk(True), {})[5][1] == "warn"                              # the same drums are wrong for garage
    R.set_task(style="ambient"); assert R.checklist(fake_trk(True), {})[5][1] == "warn"


def test_no_clap_unless_the_score_asks():
    assert A.drum_plan_v2(SECS, ARC, RP.profile("house"), np.random.default_rng(1))["clap"] == [] and not RP.profile("techno")["clap"]
    assert A.drum_plan_v2(SECS, ARC, RP.profile("house", clap=True), np.random.default_rng(1))["clap"]
