"""P86: мотивный генератор + гарантия новизны каждого трека. Офлайн."""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from autodj.generate.motif import (new_motif, invert, retrograde, augment, diminish,
                                   ornament, develop, euclidean, random_rhythm,
                                   track_identity, motif_to_notes, melody_for_sections)


class TestMotifTransforms:
    def test_invert_flips_intervals(self):
        assert invert([(2, 1.0), (-1, 0.5)]) == [(-2, 1.0), (1, 0.5)]
    def test_retrograde_reverses(self):
        assert retrograde([(1, 1.0), (2, 0.5)]) == [(2, 0.5), (1, 1.0)]
    def test_augment_and_diminish(self):
        assert augment([(1, 1.0)], 2.0) == [(1, 2.0)]
        assert diminish([(1, 1.0)], 0.5) == [(1, 0.5)]
    def test_diminish_has_floor(self):
        assert diminish([(1, 0.125)], 0.1)[0][1] >= 0.125        # не схлопывается в ноль
    def test_ornament_adds_notes(self):
        out = ornament([(1, 2.0)] * 6, random.Random(1), prob=1.0)
        assert len(out) > 6

    def test_new_motif_is_musical_not_noise(self):
        m = new_motif(random.Random(3))
        assert 4 <= len(m) <= 8
        assert all(abs(s) <= 2 for s, _ in m)                     # шаги по гамме, не скачки
        assert all(d > 0 for _, d in m)


class TestSectionDevelopment:
    def test_sections_differ(self):
        m = new_motif(random.Random(5))
        rng = random.Random(5)
        outs = {k: develop(m, k, rng) for k in ("build", "drop", "breakdown", "outro")}
        assert len({tuple(v) for v in outs.values()}) > 1          # секции звучат по-разному
    def test_fragment_shorter_than_theme(self):
        m = new_motif(random.Random(7))
        assert len(develop(m, "outro", random.Random(7))) <= len(m)
    def test_theme_recognizable_in_drop(self):
        m = [(1, 1.0), (2, 0.5), (-1, 0.5), (1, 1.0)]
        d = develop(m, "drop", random.Random(0))
        assert len(d) >= len(m)                                   # тема целиком (+орнамент)


class TestRhythmNoTemplates:
    def test_euclidean_distributes_pulses(self):
        p = euclidean(4, 16)
        assert sum(p) == 4 and len(p) == 16
    def test_random_rhythm_varies_between_tracks(self):
        a = [tuple(random_rhythm(random.Random(i))) for i in range(6)]
        assert len(set(a)) >= 5                                   # не 5-7 шаблонов


class TestTrackNovelty:
    def test_each_render_is_new(self):
        fps = {track_identity()["fingerprint"] for _ in range(6)}
        assert len(fps) == 6                                      # НИКАКОГО наследования
    def test_explicit_seed_reproduces(self):
        a, b = track_identity(seed=123), track_identity(seed=123)
        assert a["fingerprint"] == b["fingerprint"] and a["motif"] == b["motif"]
    def test_identity_has_variation_params(self):
        idt = track_identity(seed=9)
        for k in ("motif", "rhythm", "lead_octave", "lead_density", "syncopation",
                  "reverb_jitter", "gain_jitter", "swing", "fingerprint"):
            assert k in idt
    def test_different_seeds_differ(self):
        assert track_identity(seed=1)["fingerprint"] != track_identity(seed=2)["fingerprint"]


class TestMelodyBuild:
    def _plan(self):
        return [(0, 8, "intro"), (8, 16, "build"), (16, 32, "drop"), (32, 40, "outro")]

    def test_notes_generated_and_sorted(self):
        idt = track_identity(seed=11)
        ev = melody_for_sections(self._plan(), [[57, 60, 64]], [0, 2, 3, 5, 7, 9, 10],
                                 57, 125, idt, random.Random(11))
        assert ev and all(ev[i][0] <= ev[i + 1][0] for i in range(len(ev) - 1))
        assert all(len(e) == 4 for e in ev)                       # (t, midi, vel, dur)

    def test_intro_stays_empty(self):
        idt = track_identity(seed=12)
        ev = melody_for_sections(self._plan(), [[57, 60, 64]], [0, 2, 3, 5, 7, 9, 10],
                                 57, 125, idt, random.Random(12))
        intro_end = 8 * 4 * (60.0 / 125)
        assert not [e for e in ev if e[0] < intro_end]            # тема входит позже

    def test_notes_in_reasonable_range(self):
        idt = track_identity(seed=13)
        ev = melody_for_sections(self._plan(), [[57, 60, 64]], [0, 2, 3, 5, 7, 9, 10],
                                 57, 125, idt, random.Random(13))
        assert all(24 <= e[1] <= 100 for e in ev)                 # без ультразвука и инфра
