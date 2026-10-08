"""P97 (гармония) + P94/P95 (фактура, фильтр). Тесты на обе стороны."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import random
import numpy as np
from autodj.generate.music_theory import (voice_lead, voice_lead_sequence,
                                          diatonic_progression, resolve_progression)
from autodj.generate.motif import motif_to_notes, track_identity, melody_for_sections
from autodj.generate import texture as tx

DORIAN = [0, 2, 3, 5, 7, 9, 10]
MINOR = [0, 2, 3, 5, 7, 8, 10]
MAJOR = [0, 2, 4, 5, 7, 9, 11]


def abs_scale(root, iv):
    return sorted({root + o * 12 + i for o in range(-2, 3) for i in iv if 24 <= root + o * 12 + i <= 108})


# ═══ P97 ═══

class TestVoiceLead:
    def test_keeps_pitch_classes(self):
        prev, nxt = [66, 69, 73, 76], [71, 74, 78, 81]        # i7 → iv7 F#m
        out = voice_lead(prev, nxt)
        assert sorted(n % 12 for n in out) == sorted(n % 12 for n in nxt)

    def test_moves_smoothly(self):
        prev, nxt = [66, 69, 73, 76], [71, 74, 78, 81]
        out = voice_lead(prev, nxt)
        assert sum(abs(a - b) for a, b in zip(sorted(out), prev)) < \
               sum(abs(a - b) for a, b in zip(nxt, prev))      # ближе, чем как было
        assert max(abs(a - b) for a, b in zip(sorted(out), prev)) <= 6

    def test_sequence_never_adds_foreign_notes(self):
        for prog in ("neo_soul", "trance", "psychedelic", "deep_lounge", "indie"):
            raw = diatonic_progression(66, prog, DORIAN, use_7ths=True)
            led = voice_lead_sequence(raw)
            for r, l in zip(raw, led):
                assert sorted(n % 12 for n in r) == sorted(n % 12 for n in l)


class TestDiatonic:
    def test_all_notes_in_mode(self):
        for iv in (DORIAN, MINOR, MAJOR):
            pcs = {(66 + i) % 12 for i in iv}
            for prog in ("neo_soul", "trance", "lounge", "dark_techno", "modal_interchange"):
                for ch in diatonic_progression(66, prog, iv, use_7ths=True):
                    assert all(n % 12 in pcs for n in ch), (prog, ch)

    def test_minor_dominant_stays_major(self):
        ch = diatonic_progression(57, "secondary_dom", MINOR)[1]    # "V" в A minor
        assert (ch[1] - ch[0]) % 12 == 4

    def test_seventh_tables_fixed(self):
        iii7 = resolve_progression(57, "deep_lounge", use_7ths=True)[2]   # III7 в Am
        assert (iii7[3] - iii7[0]) == 11                                    # maj7: C-E-G-B

    def test_non_heptatonic_falls_back(self):
        assert diatonic_progression(57, "trance", [0, 3, 5, 7, 10])


class TestMotifRange:
    def test_absolute_scale_stays_in_range(self):
        sc = abs_scale(66, DORIAN)
        motif = [(2, 1.0), (2, 0.5), (3, 0.5), (2, 1.0)] * 4
        ev = motif_to_notes(motif, sc, 66, 0, 0.5, [66, 69, 73], 12)
        assert all(24 <= e[1] <= 100 for e in ev)

    def test_absolute_scale_in_mode(self):
        sc = abs_scale(66, DORIAN)
        pcs = {n % 12 for n in sc}
        ev = motif_to_notes([(1, 0.5), (-2, 0.5), (3, 1.0), (1, 1.0)] * 3, sc, 66, 0, 0.5)
        assert all(e[1] % 12 in pcs for e in ev)

    def test_interval_scale_still_works(self):
        ev = motif_to_notes([(0, 1.0), (2, 1.0)], DORIAN, 57, 0, 0.5)
        assert ev[0][1] == 57 and ev[1][1] == 57 + DORIAN[2]

    def test_melody_follows_chord_by_time(self):
        chords = [[57, 60, 64], [53, 57, 60]]
        idt = track_identity(seed=3)
        plan = [(0, 2, "intro"), (2, 34, "drop")]
        ev = melody_for_sections(plan, chords, abs_scale(57, MINOR), 57, 120, idt,
                                 random.Random(3), chord_bars=4)
        assert ev and all(24 <= e[1] <= 100 for e in ev)


# ═══ P94/P95 ═══

BPM = 90
BAR = 4 * 60 / BPM


def tex(seed=1):
    return tx.sample_texture(random.Random(seed))


class TestPlan:
    def test_variants_cover_track_without_gaps(self):
        for name in tx.PLAN_TEMPLATES:
            p = tx.plan_variant(150, name)
            assert p[0][0] == 0 and p[-1][1] == 150
            assert all(p[i][1] == p[i + 1][0] for i in range(len(p) - 1))

    def test_variants_differ(self):
        shapes = {tuple(k for _, _, k in tx.plan_variant(150, n)) for n in tx.PLAN_TEMPLATES}
        assert len(shapes) == len(tx.PLAN_TEMPLATES)

    def test_texture_differs_between_tracks(self):
        assert len({repr(tex(s)) for s in range(8)}) == 8
        assert tex(5) == tex(5)


class TestPhraseMelody:
    def setup_method(self):
        self.chords = voice_lead_sequence(diatonic_progression(62, "indie", DORIAN))
        self.scale = abs_scale(62, DORIAN)
        self.plan = tx.plan_variant(96, "classic")

    def mel(self, seed=1):
        return tx.phrase_melody(self.plan, self.chords, self.scale, BPM, 2, tex(seed),
                                random.Random(seed))

    def test_in_mode_and_range(self):
        pcs = {n % 12 for n in self.scale}
        ev = self.mel()
        assert ev and all(e[1] % 12 in pcs for e in ev)
        assert max(e[1] for e in ev) - min(e[1] for e in ev) <= 19

    def test_intro_silent(self):
        intro_end = self.plan[0][1] * BAR
        assert not [e for e in self.mel() if e[0] < intro_end]

    def test_strong_beats_are_chord_tones(self):
        ev = self.mel(2)
        hits = tot = 0
        for t, m, _, _ in ev:
            if abs((t / (BAR / 2)) - round(t / (BAR / 2))) < 1e-6:     # сильная доля
                ch = tx.chord_at(self.chords, t + 0.01, BAR, 2)
                tot += 1
                hits += m % 12 in {c % 12 for c in ch}
        assert tot and hits / tot > 0.85

    def test_motif_repeats(self):
        """Тема узнаваема: один и тот же ритм повторяется в дропе."""
        ev = self.mel(3)
        drop = [p for p in self.plan if p[2] == "drop"][0]
        rel = sorted(round((t / (60 / BPM)) % 8, 2) for t, *_ in ev
                     if drop[0] * BAR <= t < drop[1] * BAR)
        from collections import Counter
        assert Counter(rel).most_common(1)[0][1] >= 3

    def test_different_seeds_different_melodies(self):
        assert [e[1] for e in self.mel(1)][:12] != [e[1] for e in self.mel(9)][:12]


class TestComp:
    def test_syncopated_and_rootless_in_register(self):
        chords = diatonic_progression(62, "indie", DORIAN, use_7ths=True)
        ev = tx.comp_events(tx.plan_variant(64, "classic"), chords, 2, BPM, tex(1), random.Random(1))
        assert ev and all(55 <= e[1] <= 74 for e in ev)
        step = BAR / 16
        offbeat = sum(1 for t, *_ in ev if round((t % BAR) / step) % 4 != 0)
        assert offbeat > 0.2 * len(ev)                       # не всё на сильную долю

    def test_register_does_not_drift_on_long_track(self):
        """Голосоведение на 200 тактах не уводит Rhodes в бас (был дрейф до MIDI 23)."""
        chords = voice_lead_sequence(diatonic_progression(69, "lounge", DORIAN, use_7ths=True))
        for seed in range(6):
            ev = tx.comp_events([(0, 200, "drop")], chords, 4, 120, tex(seed), random.Random(seed))
            assert ev and all(55 <= e[1] <= 74 for e in ev)

    def test_silent_outside_active_sections(self):
        plan = [(0, 8, "intro"), (8, 16, "drop")]
        ev = tx.comp_events(plan, [[62, 65, 69]], 2, BPM, tex(1), random.Random(1))
        assert ev and min(e[0] for e in ev) >= 8 * BAR - 1e-6


class TestAnswers:
    def test_answers_land_in_gaps_and_on_chord_tones(self):
        chords = [[62, 65, 69]]
        lead = [(0.0, 74, 90, 0.5), (0.7, 72, 80, 0.5), (1.3, 69, 80, 0.4), (6.0, 74, 90, 0.5)]
        ev = tx.answer_events(lead, chords, 2, BPM, {**tex(1), "answer_prob": 1.0}, random.Random(1))
        assert ev
        assert all(1.7 <= t < 6.0 for t, *_ in ev)
        assert all(m % 12 in {2, 5, 9} for _, m, _, _ in ev)

    def test_no_gap_no_answer(self):
        lead = [(i * 0.3, 70, 80, 0.3) for i in range(20)]
        assert tx.answer_events(lead, [[62, 65, 69]], 2, BPM, {**tex(1), "answer_prob": 1.0},
                                random.Random(1)) == []


class TestFilterMacro:
    def test_closed_in_breakdown_open_in_drop(self):
        plan = [(0, 8, "intro"), (8, 16, "build"), (16, 32, "drop"), (32, 40, "breakdown"),
                (40, 48, "outro")]
        t = tex(1)
        sr, block = 8000, 512
        total = int(48 * BAR * sr)
        c = tx.cutoff_curve(plan, BAR, total, sr, t, block)
        at = lambda bar: c[int(bar * BAR * sr / block)]
        assert at(24) > 3 * at(36)                          # дроп ярче ямы
        assert at(24) > 3 * at(2)                           # и интро
        assert at(15) > at(9)                               # build раскрывается

    def test_filter_darkens_but_keeps_signal(self):
        sr = 8000
        x = np.random.RandomState(0).randn(sr * 8, 2).astype(np.float32) * 0.2
        plan = [(0, 8, "breakdown")]
        y = tx.filter_macro(x, sr, plan, 1.0, {**tex(1), "filter_lo": 300, "filter_hi": 600})
        assert y.shape == x.shape and np.isfinite(y).all()
        assert 0.05 < np.std(y) < np.std(x)


class TestRollingBass:
    def test_offbeat_only_in_register_and_sections(self):
        plan = [(0, 8, "intro"), (8, 24, "drop"), (24, 32, "breakdown")]
        chords = [[57, 60, 64], [53, 57, 60]]
        bar = 4 * 60 / 126
        for seed in range(6):
            ev = tx.rolling_bass(plan, chords, 2, 126, random.Random(seed))
            assert ev
            steps = {round((t % bar) / (bar / 16)) % 16 for t, *_ in ev}
            assert not steps & {0, 4, 8, 12}                 # бочке место
            assert all(24 <= m <= 59 for _, m, _, _ in ev)
            assert all(8 * bar <= t < 24 * bar for t, *_ in ev)   # интро и яма без баса

    def test_follows_chord_root(self):
        bar = 4 * 60 / 126
        ev = tx.rolling_bass([(0, 4, "drop")], [[57, 60, 64], [53, 57, 60]], 2, 126, random.Random(1))
        first = [m % 12 for t, m, _, _ in ev if t < 2 * bar]
        assert {57 % 12, (57 + 7) % 12} >= set(first)
