"""P69: фразы вокала, хук-детекция, статтер. Офлайн (numpy)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import vocal_phrases as vp
import club_rework as cr


def _tone(freq, sec, sr=44100, amp=0.5):
    t = np.arange(int(sec * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype("float32")


def _voc(pieces, sr=44100):
    """[(freq|None, sec)] → стерео 'вокал' (None = пауза)."""
    parts = [np.zeros(int(sec * sr), "float32") if f is None else _tone(f, sec, sr)
             for f, sec in pieces]
    mono = np.concatenate(parts)
    return np.stack([mono, mono], 1)


class TestDetectPhrases:
    def test_splits_on_pauses(self):
        sr = 44100
        v = _voc([(440, 1.0), (None, 0.6), (440, 1.2), (None, 0.6), (440, 0.9)])
        ph = vp.detect_phrases(v, sr)
        assert len(ph) == 3
        assert abs(ph[0][0]) < sr * 0.1 and abs(ph[0][1] - sr) < sr * 0.15
    def test_short_blips_dropped(self):
        sr = 44100
        v = _voc([(440, 0.2), (None, 0.6), (440, 1.0)])          # 0.2s — не фраза
        assert len(vp.detect_phrases(v, sr)) == 1
    def test_silence_no_phrases(self):
        assert vp.detect_phrases(np.zeros((44100, 2), "float32"), 44100) == []


class TestHook:
    def test_repeated_phrase_wins(self):
        sr = 44100
        # A(440) ×3 раза, B(1200) ×1 — хук должен быть A
        v = _voc([(440, 1.0), (None, 0.6), (1200, 1.0), (None, 0.6),
                  (440, 1.0), (None, 0.6), (440, 1.0)])
        ph = vp.detect_phrases(v, sr)
        hk = vp.find_hook(v, sr, ph)
        assert hk is not None
        s, e = ph[hk["hook_index"]]
        fp_hook = vp.phrase_fingerprint(v[s:e], sr)
        fp_a = vp.phrase_fingerprint(_voc([(440, 1.0)]), sr)
        assert vp.cosine(fp_hook, fp_a) > 0.95                    # хук = фраза A
        assert len(hk["repeats"]) == 2
    def test_too_few_none(self):
        v = _voc([(440, 1.0)])
        assert vp.find_hook(v, 44100, vp.detect_phrases(v, 44100)) is None


class TestFingerprint:
    def test_same_similar_diff_far(self):
        sr = 44100
        a1, a2 = vp.phrase_fingerprint(_tone(440, 1.0), sr), vp.phrase_fingerprint(_tone(440, 1.1), sr)
        b = vp.phrase_fingerprint(_tone(3000, 1.0), sr)
        assert vp.cosine(a1, a2) > 0.95 and vp.cosine(a1, b) < 0.6


class TestStutterIntegration:
    def test_build_gets_hook_energy_and_intro_tease(self):
        sr, bar = 44100, 44100 // 4
        db = np.arange(0, 65) * bar
        pop = {"vocals": np.zeros((64 * bar, 2), "float32"),
               "other": np.zeros((64 * bar, 2), "float32"),
               "bass": np.zeros((64 * bar, 2), "float32")}
        loops = {"peak": np.zeros((bar, 2), "float32"), "sparse": np.zeros((bar, 2), "float32")}
        hook = np.ones((bar, 2), "float32") * 0.4
        for kind in ("build", "intro"):
            sec = dict(kind=kind, pop=None, bars=8, groove="peak" if kind == "build" else "sparse")
            no_hook = cr.render_section(sec, pop, db, loops, sr, bar, bar // 4)
            with_hook = cr.render_section(sec, pop, db, loops, sr, bar, bar // 4, hook_audio=hook)
            assert np.abs(with_hook).sum() > np.abs(no_hook).sum()   # хук реально звучит
    def test_stutter_lands_in_tail(self):
        bar, total = 1000, 8000
        hook = np.ones((600, 2), "float32")
        out = cr._hook_stutter(hook, bar, total, 44100)
        assert not out[:6500].any() and out[7000:].any()             # хвост build
