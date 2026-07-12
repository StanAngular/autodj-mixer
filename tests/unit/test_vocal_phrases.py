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


# ═══ P70: дробление слипшихся, фраза по тексту, статтер целиком ═══

class TestSplitLong:
    def test_giant_phrase_split_at_quietest(self):
        sr = 44100
        # 30s почти сплошного тона с проседанием посередине (пауз >400мс нет → P69 слил бы)
        a = _tone(440, 14.5); dip = _tone(440, 1.0, amp=0.06); b = _tone(440, 14.5)
        v = np.stack([np.concatenate([a, dip, b])]*2, 1)
        ph = vp.detect_phrases(v, sr, max_phrase_s=12.0)
        assert len(ph) >= 2                                        # разрезано
        assert all((e - s) <= 16 * sr for s, e in ph)              # гигантов нет
    def test_short_untouched(self):
        v = _voc([(440, 2.0)])
        assert len(vp.detect_phrases(v, 44100, max_phrase_s=12.0)) == 1


class TestFindTextSpan:
    WORDS = [{"word": w, "start": i * 1000, "end": i * 1000 + 900}
             for i, w in enumerate("я приходжу я іду до тебе знову на душевну розмову".split())]
    def test_exact_quote(self):
        hit = vp.find_text_span(self.WORDS, "іду до тебе знову")
        assert hit and hit[0] == 3000 and hit[1] == 6900           # точные сэмплы слов
    def test_fuzzy_quote_tolerated(self):
        hit = vp.find_text_span(self.WORDS, "iду до тебе знов")    # неточная цитата
        assert hit is not None and hit[2] >= 0.55
    def test_absent_none(self):
        assert vp.find_text_span(self.WORDS, "совсем другой текст про зиму") is None
    def test_empty(self):
        assert vp.find_text_span([], "что-то") is None
        assert vp.find_text_span(self.WORDS, "") is None


class TestWholePhraseStutter:
    def test_never_cuts_midword(self):
        bar, total = 1000, 8000
        hook = np.ones((2600, 2), "float32")                       # фраза 2.6 бара
        out = cr._hook_stutter(hook, bar, total, 44100)
        nz = np.nonzero(out[:, 0])[0]
        assert len(nz) % 2600 == 0                                 # только ЦЕЛЫЕ повторы
    def test_too_long_refuses(self):
        out = cr._hook_stutter(np.ones((9000, 2), "float32"), 1000, 8000, 44100)
        assert not out.any()                                       # лучше без, чем обрубок
    def test_fits_repeats(self):
        out = cr._hook_stutter(np.ones((3000, 2), "float32"), 1000, 8000, 44100)
        assert np.nonzero(out[:, 0])[0].size == 6000               # 2 целых повтора


class TestGrooveNotSwept:
    def test_build_groove_keeps_bass(self):
        sr, bar = 44100, 44100 // 4
        db = np.arange(0, 65) * bar
        t = np.arange(bar) / sr
        bassloop = np.stack([np.sin(2 * np.pi * 80 * t)] * 2, 1).astype("float32")
        pop = {"vocals": np.zeros((64*bar, 2), "float32"),
               "other": np.zeros((64*bar, 2), "float32"),
               "bass": np.zeros((64*bar, 2), "float32")}
        loops = {"peak": bassloop, "sparse": bassloop}
        sec = dict(kind="build", pop=None, bars=8, groove="peak")
        out = cr.render_section(sec, pop, db, loops, sr, bar, bar // 4)
        seg = slice(2048, 4 * bar)                                 # до lift-хвоста
        # P70: 80Гц грува ЖИВЫ в build (раньше hpf_sweep 120→700 их убивал)
        assert np.abs(out[seg]).mean() > 0.4


# ═══ P71: лирика-сверка + исполняемый план фраз ═══

class TestAlignLyrics:
    WORDS = [{"word": w, "start": i * 100, "end": i * 100 + 90}
             for i, w in enumerate("ya prihodju ya idu do tebe znovu".split())]
    def test_canonical_spelling_applied_timings_kept(self):
        out, cover = vp.align_lyrics(self.WORDS, "я приходжу я іду до тебе знову")
        assert cover > 0.9
        assert out[1]["word"] == "приходжу" and out[1]["start"] == 100   # тайминг ASR цел
    def test_no_lyrics_zero(self):
        out, cover = vp.align_lyrics(self.WORDS, "")
        assert cover == 0.0 and out[0]["word"] == "ya"


class TestPlacePhraseLayer:
    def test_placed_at_bar_with_repeats(self):
        sr, bar = 44100, 1000
        seg = np.ones((800, 2), "float32")
        out = cr.place_phrase_layer([{"audio": seg, "at_bar": 3, "repeat": 2}],
                                    total=10000, bar_len=bar, sr=sr, quarter=250)
        assert not out[:2900].any() and out[3100:3200].any()             # с бара 3
    def test_overflow_skipped_whole(self):
        seg = np.ones((5000, 2), "float32")
        out = cr.place_phrase_layer([{"audio": seg, "at_bar": 8, "repeat": 1}],
                                    total=10000, bar_len=1000, sr=44100, quarter=250)
        assert not out.any()                                             # целиком не влезла — пропуск
