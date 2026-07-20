"""
backends/dawdreamer.py — DawDreamer backend (SPEC 008, G4)

Two synthesis modes:
  1. VST3 plugin (PluginProcessor) — Vital, Surge XT, Dexed etc. when available
  2. FaustProcessor — built-in Faust DSP synths (no plugins needed, always available)

Usage from engine.py:
    from backends.dawdreamer import DawDreamerBackend
    backend = DawDreamerBackend(sample_rate=44100)
    wav = backend.render(midi_events, duration_s)

Faust synth presets (no VST3 required):
    "supersaw"   — detuned sawtooth stack, LP filter (pad/lead)
    "pluck"      — Karplus-Strong string (pluck/arpeggios)
    "organ"      — additive Hammond-style (chords)
    "bass_sub"   — sine sub-bass (bass channel)
    "fm_bell"    — FM 2-op bell/mallet tone

VST3 (optional):
    Install free plugins to /usr/local/lib/vst3/ or ~/vst3/:
    - Surge XT: https://surge-synthesizer.github.io
    - Vital:    https://vital.audio
    - Dexed:    https://asb2m10.github.io/dexed
"""

import os
import sys
import logging

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Faust DSP presets
# ---------------------------------------------------------------------------

FAUST_PRESETS = {
    "supersaw": """
import("stdfaust.lib");
freq = hslider("freq[unit:Hz]", 440, 20, 20000, 0.01);
gain = hslider("gain", 0.5, 0, 1, 0.001);
gate = button("gate");
detune = 0.008;
env = en.adsr(0.015, 0.2, 0.75, 0.3, gate);
osc1 = os.sawtooth(freq);
osc2 = os.sawtooth(freq * (1 + detune));
osc3 = os.sawtooth(freq * (1 - detune));
osc4 = os.sawtooth(freq * (1 + detune*2.1));
osc5 = os.sawtooth(freq * (1 - detune*2.1));
mix = (osc1 + osc2 + osc3 + osc4 + osc5) / 5.0;
cutoff = 2000 + freq * 1.5;
filtered = fi.lowpass(2, cutoff, mix);
process = filtered * env * gain <: _, _;
""",

    "pluck": """
import("stdfaust.lib");
freq = hslider("freq[unit:Hz]", 440, 20, 20000, 0.01);
gain = hslider("gain", 0.7, 0, 1, 0.001);
gate = button("gate");
env = en.ar(0.001, 0.8, gate);
excite = no.noise * (gate : ba.impulsify);
ks = pm.ks(freq, 0.97, excite);
process = ks * env * gain <: _, _;
""",

    "organ": """
import("stdfaust.lib");
freq = hslider("freq[unit:Hz]", 440, 20, 20000, 0.01);
gain = hslider("gain", 0.5, 0, 1, 0.001);
gate = button("gate");
env = en.adsr(0.01, 0.0, 1.0, 0.05, gate);
h1 = os.osc(freq);
h2 = os.osc(freq * 2) * 0.7;
h3 = os.osc(freq * 3) * 0.5;
h4 = os.osc(freq * 4) * 0.3;
mix = (h1 + h2 + h3 + h4) / 2.5;
process = mix * env * gain <: _, _;
""",

    "bass_sub": """
import("stdfaust.lib");
freq = hslider("freq[unit:Hz]", 55, 20, 500, 0.01);
gain = hslider("gain", 0.9, 0, 1, 0.001);
gate = button("gate");
env = en.adsr(0.005, 0.15, 0.8, 0.2, gate);
sub = os.osc(freq);
body = os.osc(freq * 2) * 0.3;
click = no.noise * (gate : ba.impulsify) * 0.2;
sat = ma.tanh(sub * 1.2) / 1.2;
process = (sat + body + click) * env * gain <: _, _;
""",

    "fm_bell": """
import("stdfaust.lib");
freq = hslider("freq[unit:Hz]", 440, 20, 20000, 0.01);
gain = hslider("gain", 0.6, 0, 1, 0.001);
gate = button("gate");
env = en.adsr(0.001, 0.8, 0.2, 0.5, gate);
ratio = 3.5;
mod_depth = freq * 2.0;
mod_env = en.adsr(0.001, 0.3, 0.0, 0.0, gate);
modulator = os.osc(freq * ratio) * mod_depth * mod_env;
carrier = os.osc(freq + modulator);
process = carrier * env * gain <: _, _;
""",

    "strings": """
import("stdfaust.lib");
freq = hslider("freq[unit:Hz]", 440, 20, 20000, 0.01);
gain = hslider("gain", 0.5, 0, 1, 0.001);
gate = button("gate");
env = en.adsr(0.12, 0.3, 0.85, 0.5, gate);
osc1 = os.sawtooth(freq);
osc2 = os.sawtooth(freq * 0.998);
vib = os.osc(5.2) * 0.003;
osc3 = os.sawtooth(freq * (1 + vib));
mix = (osc1 + osc2 + osc3) / 3.0;
filtered = fi.lowpass(1, 3000, mix);
process = filtered * env * gain <: _, _;
""",

    "bass_reese": """
import("stdfaust.lib");
freq = hslider("freq[unit:Hz]", 55, 20, 500, 0.01);
gain = hslider("gain", 0.85, 0, 1, 0.001);
gate = button("gate");
env = en.adsr(0.008, 0.1, 0.9, 0.15, gate);
lfo = os.osc(0.3) * 0.006;
osc1 = os.sawtooth(freq * (1 + lfo));
osc2 = os.sawtooth(freq * (1.008 + lfo));
osc3 = os.sawtooth(freq * 0.994);
mix = (osc1 + osc2 + osc3) / 3.0;
cut_env = en.adsr(0.01, 0.4, 0.3, 0.1, gate) * 600 + 200;
filtered = fi.lowpass(2, cut_env, mix);
sat = ma.tanh(filtered * 1.5) / 1.5;
hp = fi.highpass(1, 80, sat);
process = hp * env * gain <: _, _;
""",
}

# GM program → faust preset mapping (when FluidSynth not available)
GM_TO_FAUST = {
    range(0, 8):   "organ",       # Piano family → organ approximation
    range(8, 16):  "fm_bell",     # Chromatic percussion → FM bell
    range(16, 24): "organ",       # Organ
    range(24, 32): "pluck",       # Guitar
    range(32, 40): "bass_sub",    # Bass
    range(40, 48): "strings",     # Strings
    range(48, 56): "strings",     # Ensemble
    range(56, 64): "supersaw",    # Brass → supersaw
    range(64, 72): "pluck",       # Reed/woodwind → pluck
    range(72, 80): "pluck",       # Pipe
    range(80, 88): "supersaw",    # Synth lead
    range(88, 96): "strings",     # Synth pad
}


def program_to_faust(gm_program: int) -> str:
    """Map GM program number to Faust preset name."""
    for r, preset in GM_TO_FAUST.items():
        if gm_program in r:
            return preset
    return "supersaw"


# ---------------------------------------------------------------------------
# VST3 scanner
# ---------------------------------------------------------------------------

VST3_SEARCH_PATHS = [
    "/usr/local/lib/vst3",
    "/usr/lib/vst3",
    "/home/hermes/.vst3",
    "/home/cclaw/.vst3",
    "/root/.vst3",
    os.path.expanduser("~/.vst3"),
]


def find_vst3(name: str = None) -> list:
    """
    Search for VST3 plugins.
    If name is given (e.g. "Surge XT"), return matching paths.
    Otherwise return all found .vst3 paths.
    """
    import glob
    found = []
    for base in VST3_SEARCH_PATHS:
        found.extend(glob.glob(os.path.join(base, "**/*.vst3"), recursive=True))
        found.extend(glob.glob(os.path.join(base, "*.vst3")))

    if name:
        name_lower = name.lower()
        found = [p for p in found if name_lower in os.path.basename(p).lower()]

    return list(set(found))


# ---------------------------------------------------------------------------
# DawDreamer backend
# ---------------------------------------------------------------------------

class DawDreamerBackend:
    """
    MIDI event list → stereo numpy WAV via DawDreamer.

    Channels map to Faust synth instances (or VST3 if available).
    Channel 9 = drums (simple noise-based via Faust).

    midi_events format: same as FluidSynthBackend
        (time_s, "note_on"|"note_off"|"program"|"control", channel, ...)
    """

    def __init__(
        self,
        sample_rate: int = 44100,
        block_size: int = 512,
        default_preset: str = "supersaw",
        vst3_plugins: dict = None,
    ):
        """
        Args:
            sample_rate: audio sample rate
            block_size: render block size (512 typical)
            default_preset: fallback Faust preset for unknown channels
            vst3_plugins: {channel: "/path/to/Plugin.vst3"} optional VST3 overrides
        """
        try:
            import dawdreamer as daw
        except ImportError:
            raise RuntimeError(
                "DawDreamer not available. Install: pip install dawdreamer"
            )

        self._daw = daw
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.default_preset = default_preset
        self.vst3_plugins = vst3_plugins or {}

        # Per-channel config: {ch: {"preset": str, "program": int}}
        self._ch_config = {}
        # Compiled Faust processors: {preset_name: FaustProcessor}
        self._faust_cache = {}

        log.info(f"DawDreamerBackend: SR={sample_rate} block={block_size}")

    def _get_faust(self, preset_name: str):
        """Get or compile a Faust processor (cached per preset)."""
        if preset_name in self._faust_cache:
            return self._faust_cache[preset_name]

        if preset_name not in FAUST_PRESETS:
            log.warning(f"Unknown preset '{preset_name}', using 'supersaw'")
            preset_name = "supersaw"

        eng = self._daw.RenderEngine(self.sample_rate, self.block_size)
        faust = eng.make_faust_processor(preset_name)
        faust.set_dsp_string(FAUST_PRESETS[preset_name])

        self._faust_cache[preset_name] = (eng, faust)
        log.debug(f"Compiled Faust preset: {preset_name}")
        return eng, faust

    def _resolve_channel_preset(self, ch: int) -> str:
        """Determine Faust preset for a channel."""
        if ch == 9:
            return None  # Drums handled separately
        cfg = self._ch_config.get(ch, {})
        program = cfg.get("program", 0)
        preset = cfg.get("preset", program_to_faust(program))
        return preset

    def render(self, midi_events: list, duration_s: float) -> np.ndarray:
        """
        Render MIDI events to stereo float32 numpy array.

        Groups events by channel, renders each channel with its Faust synth,
        mixes all channels to stereo output.

        Returns:
            np.ndarray (N, 2) float32, normalized to -0.5 dB
        """
        SR = self.sample_rate
        total_samples = int(duration_s * SR)
        output = np.zeros((total_samples, 2), dtype=np.float32)

        # Parse events and apply program changes
        events = sorted(midi_events, key=lambda e: e[0])
        for ev in events:
            if ev[1] == "program":
                _, _, ch, bank, prog = ev
                if ch not in self._ch_config:
                    self._ch_config[ch] = {}
                self._ch_config[ch]["program"] = prog

        # Group note events by channel
        ch_events = {}
        for ev in events:
            t, etype, ch, *rest = ev
            if etype in ("note_on", "note_off"):
                if ch not in ch_events:
                    ch_events[ch] = []
                ch_events[ch].append(ev)

        # Render each channel
        for ch, ch_evs in ch_events.items():
            if ch == 9:
                # Drums: simple Faust percussion
                ch_buf = self._render_drums_faust(ch_evs, duration_s)
            else:
                preset = self._resolve_channel_preset(ch)
                ch_buf = self._render_channel_faust(ch_evs, duration_s, preset)

            if ch_buf is not None:
                output += ch_buf

        # Normalize
        peak = np.abs(output).max()
        if peak > 1e-6:
            target = 10 ** (-0.5 / 20)
            output *= target / peak

        return output

    def _render_channel_faust(
        self, events: list, duration_s: float, preset: str
    ) -> np.ndarray:
        """
        Render one MIDI channel via Faust synth.
        Polyphony by rendering each note separately and summing.
        Uses automation arrays with /dawdreamer/ param prefix.
        """
        SR = self.sample_rate
        total_samples = int(duration_s * SR)
        output = np.zeros((total_samples, 2), dtype=np.float32)

        if preset not in FAUST_PRESETS:
            preset = "supersaw"

        # Extract note spans: [(t_on, t_off, midi_note, velocity), ...]
        note_spans = []
        note_ons = {}
        for ev in sorted(events, key=lambda e: e[0]):
            t, etype, ch, note, vel = ev
            if etype == "note_on" and vel > 0:
                note_ons[note] = (t, vel)
            elif etype == "note_off" or (etype == "note_on" and vel == 0):
                if note in note_ons:
                    t_on, velocity = note_ons.pop(note)
                    note_spans.append((t_on, t, note, velocity))
        # Flush open notes
        for note, (t_on, vel) in note_ons.items():
            note_spans.append((t_on, duration_s, note, vel))

        if not note_spans:
            return output

        # Render each note via automation arrays
        for t_on, t_off, midi_note, vel in note_spans:
            try:
                eng = self._daw.RenderEngine(SR, self.block_size)
                faust = eng.make_faust_processor("note")
                faust.set_dsp_string(FAUST_PRESETS[preset])
                faust.compile()

                # Build automation arrays
                hz = 440.0 * (2.0 ** ((midi_note - 69) / 12.0))
                gain_val = min(1.0, vel / 127.0 * 0.8)

                freq_arr = np.full(total_samples, hz, dtype=np.float32)
                gain_arr = np.full(total_samples, gain_val, dtype=np.float32)
                gate_arr = np.zeros(total_samples, dtype=np.float32)

                # Gate: on during note span with tiny attack/release ramp
                s_on  = max(0, int(t_on  * SR))
                s_off = min(total_samples, int(t_off * SR))
                if s_off > s_on:
                    gate_arr[s_on:s_off] = 1.0
                    # 20-sample fade at edges to avoid clicks
                    fade = min(20, (s_off - s_on) // 4)
                    if fade > 0:
                        gate_arr[s_on:s_on+fade] = np.linspace(0, 1, fade)
                        gate_arr[s_off-fade:s_off] = np.linspace(1, 0, fade)

                # Set automation (requires full /dawdreamer/ prefix)
                faust.set_automation("/dawdreamer/freq", freq_arr)
                faust.set_automation("/dawdreamer/gain", gain_arr)
                faust.set_automation("/dawdreamer/gate", gate_arr)

                eng.load_graph([(faust, [])])
                eng.render(duration_s)
                audio = faust.get_audio()  # (channels, samples)

                if audio.ndim == 1:
                    stereo = np.stack([audio, audio], axis=1).astype(np.float32)
                elif audio.shape[0] == 2:
                    stereo = audio.T.astype(np.float32)
                else:
                    stereo = np.stack([audio[0], audio[0]], axis=1).astype(np.float32)

                if len(stereo) < total_samples:
                    stereo = np.pad(stereo, ((0, total_samples - len(stereo)), (0, 0)))
                else:
                    stereo = stereo[:total_samples]

                output += stereo

            except Exception as e:
                log.error(f"Note render error (note={midi_note} preset={preset}): {e}")

        return output

    def _render_drums_faust(self, events: list, duration_s: float) -> np.ndarray:
        """
        Render GM drum events (ch 9) via Faust.
        Approximates: kick(36), snare(38), hat(42/46) with Faust percussion synths.
        """
        SR = self.sample_rate
        total_samples = int(duration_s * SR)

        KICK_CODE = """
import("stdfaust.lib");
freq = hslider("freq[unit:Hz]", 60, 20, 200, 0.01);
gain = hslider("gain", 0.9, 0, 1, 0.001);
gate = button("gate");
env_p = en.ar(0.001, 0.25, gate);
env_a = en.ar(0.001, 0.15, gate);
pitch = freq + 150 * env_p;
body = os.osc(pitch) * env_a;
click = no.noise * (gate : ba.impulsify) * 0.3;
sat = ma.tanh((body + click) * 2.0) / 2.0;
process = sat * gain <: _, _;
"""
        SNARE_CODE = """
import("stdfaust.lib");
gain = hslider("gain", 0.7, 0, 1, 0.001);
gate = button("gate");
env = en.ar(0.001, 0.18, gate);
noise_part = no.noise * 0.6;
tone_part = os.osc(200) * 0.4;
mix = (noise_part + tone_part) * env;
sat = ma.tanh(mix * 2.5) / 2.5;
process = sat * gain <: _, _;
"""
        HAT_CODE = """
import("stdfaust.lib");
gain = hslider("gain", 0.4, 0, 1, 0.001);
gate = button("gate");
env = en.ar(0.001, 0.07, gate);
hf = fi.highpass(2, 8000, no.noise);
process = hf * env * gain <: _, _;
"""

        # Map MIDI drum notes to synth code
        DRUM_SYNTHS = {
            36: ("kick",  KICK_CODE,  0.8),   # Kick
            35: ("kick",  KICK_CODE,  0.85),  # Kick 2
            38: ("snare", SNARE_CODE, 0.65),  # Snare
            40: ("snare", SNARE_CODE, 0.70),  # Snare 2
            39: ("snare", SNARE_CODE, 0.55),  # Clap
            42: ("hat",   HAT_CODE,   0.45),  # Closed hat
            44: ("hat",   HAT_CODE,   0.40),  # Pedal hat
            46: ("hat",   HAT_CODE,   0.55),  # Open hat
            51: ("hat",   HAT_CODE,   0.50),  # Ride
        }

        output = np.zeros((total_samples, 2), dtype=np.float32)

        # Group events by drum type
        drum_groups = {}
        for ev in events:
            if ev[1] != "note_on" or (len(ev) > 4 and ev[4] == 0):
                continue
            t, etype, ch, note = ev[0], ev[1], ev[2], ev[3]
            vel = ev[4] if len(ev) > 4 else 100
            synth_key = DRUM_SYNTHS.get(note)
            if synth_key is None:
                continue
            name, code, amp = synth_key
            if name not in drum_groups:
                drum_groups[name] = {"code": code, "events": [], "amp": amp}
            drum_groups[name]["events"].append((t, note, vel))

        for name, info in drum_groups.items():
            try:
                eng = self._daw.RenderEngine(SR, self.block_size)
                faust = eng.make_faust_processor(name)
                faust.set_dsp_string(info["code"])
                faust.compile()

                # Build gate automation: trigger gate for each hit (300ms bursts)
                gate_arr = np.zeros(total_samples, dtype=np.float32)
                gain_arr = np.full(total_samples, 0.8, dtype=np.float32)
                for t_hit, note, vel in info["events"]:
                    s_on = max(0, int(t_hit * SR))
                    s_off = min(total_samples, s_on + int(0.3 * SR))
                    gate_arr[s_on:s_off] = min(1.0, vel / 127.0)

                faust.set_automation("/dawdreamer/gain", gain_arr)
                faust.set_automation("/dawdreamer/gate", gate_arr)

                eng.load_graph([(faust, [])])
                eng.render(duration_s)
                audio = faust.get_audio()

                if audio.ndim == 1:
                    stereo = np.stack([audio, audio], axis=1).astype(np.float32)
                elif audio.shape[0] == 2:
                    stereo = audio.T.astype(np.float32)
                else:
                    stereo = np.stack([audio[0], audio[0]], axis=1).astype(np.float32)

                if len(stereo) < total_samples:
                    stereo = np.pad(stereo, ((0, total_samples - len(stereo)), (0, 0)))
                else:
                    stereo = stereo[:total_samples]

                output += stereo * info["amp"]

            except Exception as e:
                log.error(f"Drum render error ({name}): {e}")

        return output

    def close(self):
        self._faust_cache.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# VST3 helper
# ---------------------------------------------------------------------------

def load_vst3_plugin(eng, name: str, vst3_path: str):
    """
    Load a VST3 plugin into a DawDreamer PluginProcessor.
    Returns PluginProcessor or raises.
    """
    if not os.path.exists(vst3_path):
        raise FileNotFoundError(f"VST3 not found: {vst3_path}")
    plugin = eng.make_plugin_processor(name, vst3_path)
    log.info(f"VST3 loaded: {os.path.basename(vst3_path)}")
    return plugin
