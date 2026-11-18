"""P144 A/B preference log: both sides (what is refused / what passes, what counts)."""
import json, os, random, pytest
from autodj.compose import ab

@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTODJ_PREF_LOG", str(tmp_path / "log.jsonl")); monkeypatch.setenv("AUTODJ_PREF_PROFILE", str(tmp_path / "prof.json")); return tmp_path

def pair(r, n, factor, a, b, genre, expected=None, seed=1):
    return ab.make_pair(__file__, factor, a, b, r, n, seed, genre, expected=expected, dry=True, rng=random.Random(n))

def test_parse_one_line_answer():
    assert ab.parse("1B 2A мягче 3=") == [(1, "B", ""), (2, "A", "мягче"), (3, "=", "")]
    assert ab.parse("1а 2В") == [(1, "A", ""), (2, "B", "")]          # Cyrillic letters accepted
    assert ab.parse("1! 2 0") == [(1, "!", ""), (2, "0", "")]

def test_check_pair_refuses_broken_and_accepts_clean():
    ok = {"seed": 3, "bpm": 124, "gate_failed": [], "silent_layers": []}
    assert ab.check_pair(ok, dict(ok)) == []
    assert ab.check_pair(ok, dict(ok, gate_failed=["bad_sounds"])) and ab.check_pair(ok, dict(ok, seed=4)) and ab.check_pair(ok, dict(ok, silent_layers=["pad"]))

def test_vote_maps_blind_letter_to_value_and_profile_counts(logs):
    p = pair("R1", 1, "pad", "retrig", "held", "melodic house", expected="held")
    L = [k for k, v in p["letters"].items() if v == "held"][0]
    ab.vote("R1", f"1{L} мягче"); prof = ab.profile()
    assert prof["factors"]["pad"]["held"]["wins"] == 1 and prof["factors"]["pad"]["retrig"]["losses"] == 1
    assert prof["factors"]["pad"]["held"]["words"] == ["мягче"] and prof["hypotheses"]["share"] == 1.0
    assert os.path.exists(os.environ["AUTODJ_PREF_PROFILE"])

def test_rule_needs_three_wins_in_two_contexts_and_no_loss(logs):
    for i, g in enumerate(["melodic house", "melodic house", "tech house"], 1):
        p = pair(f"R{i}", 1, "bass", "shot", "multi", g); L = [k for k, v in p["letters"].items() if v == "multi"][0]; ab.vote(f"R{i}", f"1{L}")
    assert {"factor": "bass", "value": "multi", "wins": 3, "contexts": ["melodic house", "tech house"]} in ab.profile()["rules"]
    p = pair("R4", 1, "bass", "shot", "multi", "dnb"); L = [k for k, v in p["letters"].items() if v == "shot"][0]; ab.vote("R4", f"1{L}")
    assert not ab.profile()["rules"]                                                      # one loss takes the rule back

def test_ties_mark_factor_unimportant_only_after_three(logs):
    for i in range(1, 3): pair(f"T{i}", 1, "colour", "0", "1", "deep"); ab.vote(f"T{i}", "1=")
    assert "colour" not in ab.profile()["unimportant"]
    pair("T3", 1, "colour", "0", "1", "deep"); ab.vote("T3", "1=")
    assert "colour" in ab.profile()["unimportant"]

def test_other_paths_go_to_the_same_log_and_file_is_group_writable(logs):
    ab.log_single("Frequency v2", "/x.mp3", "tech house", verdict="ok", word="хэты лишние"); ab.log_pick("S1", ["A", "B", "C"], "B", "indie")
    kinds = [e["kind"] for e in ab.read()]; assert kinds == ["single", "pick"]
    assert oct(os.stat(os.environ["AUTODJ_PREF_LOG"]).st_mode & 0o777) == "0o664"
