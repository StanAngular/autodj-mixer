"""G4a: собственные синт-голоса вместо GM-пресетов. Офлайн (numpy/scipy)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import pytest
from autodj.generate.synthvoice import (VOICES, parse_instrument, render_voice_note,
                                        render_notes_synth, _brightness, _drive)


def centroid(x, sr=44100):
    m = x.mean(1) if x.ndim == 2 else x
    X = np.abs(np.fft.rfft(m.astype(float)))
    f = np.fft.rfftfreq(len(m), 1 / sr)
    return float((X * f).sum() / max(X.sum(), 1e-9))


class TestParseInstrument:
    def test_synth_prefix(self):
        assert parse_instrument("synth:supersaw") == ("supersaw", {})
    def test_params(self):
        v, p = parse_instrument("synth:acid?drive=0.5&detune=20")
        assert v == "acid" and p == {"drive": 0.5, "detune": 20.0}
    def test_gm_passthrough(self):
        assert parse_instrument("synth_lead_sawtooth") == (None, {})
        assert parse_instrument("pan_flute") == (None, {})     # GM идёт в FluidSynth
    def test_bad_params_ignored(self):
        v, p = parse_instrument("synth:pad?drive=abc")
        assert v == "pad" and p == {}


class TestVoices:
    @pytest.mark.parametrize("voice", VOICES)
    def test_all_voices_produce_sound(self, voice):
        out = render_voice_note(voice, 57, 0.4, 100)
        assert len(out) > 0 and np.abs(out).max() > 0.01
        assert np.isfinite(out).all()
    def test_unknown_voice_raises(self):
        with pytest.raises(ValueError):
            render_voice_note("nope", 57, 0.2, 100)
    def test_note_pitch_differs(self):
        low, high = render_voice_note("supersaw", 45, 0.4, 100), render_voice_note("supersaw", 69, 0.4, 100)
        assert centroid(high) > centroid(low)


class TestVelocityBrightness:
    def test_velocity_opens_filter(self):
        # ГЛАВНОЕ отличие от GM: тихая нота ТЕМНЕЕ, громкая ярче (как на железе)
        quiet = render_voice_note("supersaw", 57, 0.5, 40)
        loud = render_voice_note("supersaw", 57, 0.5, 120)
        assert centroid(loud) > centroid(quiet) * 1.3
    def test_brightness_monotone(self):
        assert _brightness(20, 900) < _brightness(70, 900) < _brightness(127, 900)
    def test_drive_adds_harmonics(self):
        x = np.sin(2 * np.pi * 220 * np.arange(4410) / 44100).astype("float32") * 0.5
        assert centroid(_drive(x, 0.8)) > centroid(x)
        assert np.array_equal(_drive(x, 0.0), x)               # 0 = без изменений


class TestRenderNotesSynth:
    def test_events_placed(self):
        out = render_notes_synth("pluck", [(0.0, 60, 100, 0.2), (1.0, 64, 100, 0.2)], 2.0)
        assert out.shape[1] == 2
        assert np.abs(out[:2000]).max() > 0.01
        assert np.abs(out[44100:46000]).max() > 0.01
        assert np.abs(out[22050:24000]).max() < 0.01           # пауза между нотами
    def test_no_clipping(self):
        many = [(i * 0.05, 60 + i % 12, 127, 0.5) for i in range(40)]
        assert np.abs(render_notes_synth("supersaw", many, 3.0)).max() <= 0.995
    def test_empty_events(self):
        assert np.abs(render_notes_synth("pad", [], 1.0)).max() == 0
