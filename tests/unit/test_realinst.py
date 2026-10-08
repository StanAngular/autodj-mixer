"""P98: настоящие инструменты. Чистые части (без плагина): обе стороны каждого фильтра."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import random
import pytest
from autodj.generate import realinst as ri


class TestCodec:
    def test_roundtrip(self):
        for b in (b"", b"a", bytes(range(256)) * 5 + b"xy"):
            assert ri.juce_b64_decode(ri.juce_b64_encode(b)) == b

    def test_wrap_state_keeps_private_tail_and_swaps_patch(self):
        tail = b"\x00" * 12 + b"JUCEPrivateData"
        old = b"sub3" + (6).to_bytes(4, "little") + b"OLDPAT" + tail
        xml = ('<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState><IComponent>'
               + ri.juce_b64_encode(old) + "</IComponent></VST3PluginState>").encode() + b"\x00"
        tmpl = b"VC2!" + len(xml).to_bytes(4, "little") + xml
        new_chunk = b"sub3" + (3).to_bytes(4, "little") + b"NEW"
        out = ri.wrap_state(tmpl, new_chunk)
        inner = out[8:].rstrip(b"\x00").decode()
        enc = inner.split("<IComponent>")[1].split("</IComponent>")[0]
        assert ri.juce_b64_decode(enc) == new_chunk + tail
        assert out[:4] == b"VC2!"


class TestResolve:
    IDX = {"pad": ["patches_factory/Pads/A.fxp", "patches_factory/Pads/B.fxp"]}

    def test_keys_selector_picks_from_pool(self):
        got = {ri.resolve("keys:@ep", random.Random(s)) for s in range(30)}
        assert got <= {"keys:" + p for p in ri.KEYS_POOLS["ep"]} and len(got) > 2

    def test_surge_selector_uses_index(self):
        got = {ri.resolve("surge:@pad", random.Random(s), self.IDX) for s in range(20)}
        assert got == {"surge:" + p for p in self.IDX["pad"]}

    def test_same_seed_same_choice(self):
        assert ri.resolve("keys:@ep", random.Random(7)) == ri.resolve("keys:@ep", random.Random(7))

    def test_concrete_and_non_real_pass_through(self):
        assert ri.resolve("keys:Straight Rhodes", random.Random(1)) == "keys:Straight Rhodes"
        assert ri.resolve("synth:pluck", random.Random(1)) == "synth:pluck"
        assert ri.resolve("electric_piano", random.Random(1)) == "electric_piano"

    def test_empty_pool_fails_loudly(self):
        with pytest.raises(RuntimeError):
            ri.resolve("surge:@lead", random.Random(1), {"pad": ["x"]})

    def test_is_real(self):
        assert ri.is_real("surge:@pad") and ri.is_real("keys:@ep")
        assert not ri.is_real("synth:pad") and not ri.is_real(None)


def mt(**kw):
    base = dict(rms=0.1, early=0.1, late=0.1, tail=0.05, centroid=1500, flatness=0.01,
                harmonicity=0.85, low_ratio=0.1, width=0.3)
    base.update(kw)
    return base


class TestClassify:
    def test_clean_sustained_pad_accepted(self):
        assert "pad" in ri.classify("Pads", "Warm Choir", mt(centroid=900))

    def test_noisy_or_inharmonic_rejected(self):
        assert ri.classify("Pads", "Warm", mt(flatness=0.4)) == []
        assert ri.classify("Leads", "Lead", mt(harmonicity=0.2)) == []
        assert ri.classify("Pads", "Quiet", mt(rms=0.001)) == []

    def test_fx_names_rejected(self):
        assert ri.classify("Pads", "Big Riser FX", mt()) == []
        assert ri.classify("Leads", "Arp Sequence", mt()) == []

    def test_pluck_must_decay_pad_must_sustain(self):
        assert "pluck" in ri.classify("Plucks", "Pick", mt(early=0.1, late=0.01))
        assert "pluck" not in ri.classify("Plucks", "Long", mt(early=0.1, late=0.09))
        assert "pad" not in ri.classify("Pads", "Short", mt(early=0.1, late=0.01))

    def test_bass_needs_low_end(self):
        assert "bass" in ri.classify("Basses", "Sub", mt(low_ratio=0.7, centroid=120))
        assert "bass" not in ri.classify("Basses", "Thin", mt(low_ratio=0.1, centroid=2500))


class TestLevelMatch:
    def test_quiet_raised_loud_lowered(self):
        import numpy as np
        x = np.zeros((1000, 2), np.float32); x[100:400] = 0.01
        y = ri.level_match(x)
        assert abs(float(np.sqrt(np.mean(y[100:400] ** 2))) - 0.08) < 1e-3
        assert np.all(y[:100] == 0)                        # тишина остаётся тишиной
        z = ri.level_match(np.full((100, 2), 0.5, np.float32))
        assert float(np.abs(z).max()) < 0.2

    def test_peak_capped_and_silence_untouched(self):
        import numpy as np
        x = np.zeros((1000, 2), np.float32); x[5] = 0.5; x[6:900] = 0.002
        assert float(np.abs(ri.level_match(x)).max()) <= 0.99 + 1e-6
        s = np.zeros((10, 2), np.float32)
        assert np.array_equal(ri.level_match(s), s)


class TestStricterP100:
    def test_markov_like_inharmonic_lead_rejected(self):
        assert ri.classify("Leads", "Markov", mt(harmonicity=0.53, centroid=1990)) == []

    def test_bright_noisy_pluck_rejected(self):
        assert ri.classify("Plucks", "Pipe", mt(early=0.12, late=0.001, centroid=3094,
                                                 flatness=0.17, harmonicity=0.66)) == []

    def test_bright_keys_rejected_warm_keys_kept(self):
        assert "keys" not in ri.classify("Polysynths", "Waver", mt(early=0.07, late=0.03, centroid=2696))
        assert "keys" in ri.classify("Keys", "Warm EP", mt(early=0.07, late=0.03, centroid=1200))

    def test_bell_and_dist_names_rejected(self):
        assert ri.classify("Keys", "Glass Bell", mt(early=0.07, late=0.03, centroid=1200)) == []
        assert ri.classify("Leads", "Dist Lead", mt()) == []

    def test_reclassify_uses_saved_metrics(self):
        idx = {"_meta": {"patches_factory/Pads/Warm.fxp": mt(centroid=900),
                         "patches_factory/Pads/Harsh.fxp": mt(centroid=900, flatness=0.3),
                         "patches_factory/Pads/Broken.fxp": {"error": "X"}}}
        out = ri.reclassify(idx)
        assert out["pad"] == ["patches_factory/Pads/Warm.fxp"]
