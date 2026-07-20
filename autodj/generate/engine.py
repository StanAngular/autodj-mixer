"""
autodj/generate/engine.py — Backend dispatcher for music generation (SPEC 008)

Dispatch order:
  1. "fluidsynth" — pyfluidsynth + SF2 soundfonts (real samples, orchestral/GM)
  2. "dawdreamer"  — DawDreamer + VST3 plugins (professional synths) [G4, not yet]
  3. "synth"       — music_engine.py parametric DSP (fallback, always available)

Entry point:
    from autodj.generate.engine import GenerateEngine
    engine = GenerateEngine(style)
    wav, sr = engine.render()       # numpy (N,2) float32 + sample rate
    engine.save("out.wav")

Style JSON extension (SPEC 008 G1):
    Style follows existing music_engine format, plus optional:
    {
      "generate": {
        "backend": "fluidsynth",          // or "synth", "auto" (default)
        "sf2": "/path/to/bank.sf2",       // optional, auto-detected if omitted
        "instrument_mapping": {
          "lead":   {"channel": 0, "bank": 0, "program": 56},  // trumpet
          "pad":    {"channel": 1, "bank": 0, "program": 49},  // slow strings
          "bass":   {"channel": 2, "bank": 0, "program": 32},  // acoustic bass
          "drums":  {"channel": 9, "bank": 0, "program": 0}    // GM drums
        }
      }
    }

If "generate" key is absent or backend="auto": tries fluidsynth, falls back to synth.
If backend="synth": always uses music_engine (original behavior, render.py compatible).
"""

import os
import sys
import logging
import json
import importlib

import numpy as np
import soundfile as sf

# Path setup: ensure /opt/autodj-mixer is importable
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Availability probes (cached)
# ---------------------------------------------------------------------------

_FLUIDSYNTH_AVAILABLE = None
_DAWDREAMER_AVAILABLE = None


def _check_fluidsynth() -> bool:
    global _FLUIDSYNTH_AVAILABLE
    if _FLUIDSYNTH_AVAILABLE is None:
        try:
            import fluidsynth  # noqa
            _FLUIDSYNTH_AVAILABLE = True
        except (ImportError, OSError):
            _FLUIDSYNTH_AVAILABLE = False
    return _FLUIDSYNTH_AVAILABLE


def _check_dawdreamer() -> bool:
    global _DAWDREAMER_AVAILABLE
    if _DAWDREAMER_AVAILABLE is None:
        try:
            import dawdreamer  # noqa
            _DAWDREAMER_AVAILABLE = True
        except (ImportError, OSError):
            _DAWDREAMER_AVAILABLE = False
    return _DAWDREAMER_AVAILABLE


def _check_synth() -> bool:
    """music_engine is always available as fallback."""
    try:
        import music_engine  # noqa
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Doctor info (for /doctor command)
# ---------------------------------------------------------------------------

def doctor_status() -> dict:
    """
    Return availability dict for all backends.
    Called by /doctor health check.
    """
    from backends.fluidsynth import SF2_SEARCH_PATHS, find_sf2

    sf2_found = None
    try:
        sf2_found = find_sf2()
    except FileNotFoundError:
        pass

    return {
        "fluidsynth_python": _check_fluidsynth(),
        "fluidsynth_binary": _binary_available("fluidsynth"),
        "dawdreamer": _check_dawdreamer(),
        "basic_pitch": _module_available("basic_pitch"),
        "mido": _module_available("mido"),
        "synth_fallback": _check_synth(),
        "sf2_banks": sf2_found,
        "sf2_search_paths": SF2_SEARCH_PATHS,
    }


def _binary_available(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def print_doctor():
    """Print human-readable doctor output."""
    status = doctor_status()
    OK = "✅"
    NO = "❌"
    def fmt(v): return OK if v else NO

    print("=== Generate Backend Doctor ===")
    print(f"  {fmt(status['fluidsynth_python'])} pyfluidsynth (Python binding)")
    print(f"  {fmt(status['fluidsynth_binary'])} fluidsynth (system binary)")
    print(f"  {fmt(status['dawdreamer'])}         dawdreamer (VST3)")
    print(f"  {fmt(status['basic_pitch'])}         basic-pitch (hum2midi)")
    print(f"  {fmt(status['mido'])}         mido (MIDI I/O)")
    print(f"  {fmt(status['synth_fallback'])} music_engine (synth fallback)")
    sf2 = status["sf2_banks"]
    if sf2:
        print(f"  {OK} SF2 bank: {sf2}")
    else:
        print(f"  {NO} SF2 bank not found")
        print("     Install: download MuseScore_General.sf2 → /opt/autodj-mixer/shared/")
    print()
    if not status["fluidsynth_python"]:
        print("  To enable FluidSynth:")
        print("    apt install fluidsynth libfluidsynth-dev")
        print("    pip install pyfluidsynth")


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

# Default instrument_mapping when none specified in style JSON
DEFAULT_INSTRUMENT_MAPPING = {
    "lead":    {"channel": 0, "bank": 0, "program": 56},   # Trumpet (GM 56)
    "pad":     {"channel": 1, "bank": 0, "program": 49},   # Slow strings
    "bass":    {"channel": 2, "bank": 0, "program": 32},   # Acoustic bass
    "chord":   {"channel": 3, "bank": 0, "program": 0},    # Grand piano
    "drums":   {"channel": 9, "bank": 0, "program": 0},    # GM drums (ch9)
}


class GenerateEngine:
    """
    High-level generate engine. Selects backend, builds MIDI events, renders WAV.

    Args:
        style (dict): loaded style JSON (same format as music_engine uses)
    """

    def __init__(self, style: dict):
        self.style = style
        self.meta = style.get("meta", {})
        self.bpm = self.meta.get("bpm", 120)
        self.sr = self.meta.get("sample_rate", 44100)
        self.duration_s = self.meta.get("duration_s", 120)
        self.out_path = self.meta.get("out", "output.wav")

        gen_cfg = style.get("generate", {})
        self.backend_hint = gen_cfg.get("backend", "auto")
        self.sf2_path = gen_cfg.get("sf2", None)
        self.instrument_mapping = gen_cfg.get(
            "instrument_mapping", DEFAULT_INSTRUMENT_MAPPING
        )

        self._backend_name = None
        self._wav = None

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    def _select_backend(self) -> str:
        hint = self.backend_hint
        if hint == "synth":
            return "synth"
        if hint == "fluidsynth":
            if not _check_fluidsynth():
                raise RuntimeError(
                    "FluidSynth backend requested but not available.\n"
                    "Install: apt install fluidsynth libfluidsynth-dev && pip install pyfluidsynth"
                )
            return "fluidsynth"
        if hint == "dawdreamer":
            if not _check_dawdreamer():
                raise RuntimeError(
                    "DawDreamer backend requested but not available.\n"
                    "Install: pip install dawdreamer"
                )
            return "dawdreamer"
        # "auto" — try in order
        if _check_fluidsynth():
            log.info("Auto-selected backend: fluidsynth")
            return "fluidsynth"
        if _check_dawdreamer():
            log.info("Auto-selected backend: dawdreamer")
            return "dawdreamer"
        log.info("Auto-selected backend: synth (fallback)")
        return "synth"

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self) -> tuple:
        """
        Render track.
        Returns: (wav_array, sample_rate)
            wav_array: np.ndarray (N, 2) float32
        """
        backend = self._select_backend()
        self._backend_name = backend
        log.info(f"Rendering with backend: {backend}")

        if backend == "fluidsynth":
            wav = self._render_fluidsynth()
        elif backend == "dawdreamer":
            wav = self._render_dawdreamer()
        else:
            wav = self._render_synth()

        self._wav = wav
        return wav, self.sr

    def _render_fluidsynth(self) -> np.ndarray:
        from backends.fluidsynth import (
            FluidSynthBackend, find_sf2,
            build_melody_events, build_chord_events,
            build_drum_events, build_bass_events,
        )

        elements = self.style.get("elements", {})
        bar_s = 60.0 / self.bpm * 4  # 4/4 bar duration
        n_bars = int(self.duration_s / bar_s) + 1

        all_events = []

        # Program change events from instrument_mapping
        for elem_name, mapping in self.instrument_mapping.items():
            ch = mapping.get("channel", 0)
            bank = mapping.get("bank", 0)
            prog = mapping.get("program", 0)
            all_events.append((0.0, "program", ch, bank, prog))

        # Lead melody
        if elements.get("lead", {}).get("active"):
            ch_cfg = self.instrument_mapping.get("lead", DEFAULT_INSTRUMENT_MAPPING["lead"])
            ch = ch_cfg["channel"]
            for pattern in elements["lead"].get("patterns", []):
                freqs = pattern.get("freqs", [])
                step_type = pattern.get("step", "eighth")
                step_s = bar_s / (8 if step_type == "eighth" else 16)
                gain = pattern.get("gain", 0.7)
                velocity = min(127, int(gain * 127))
                # Repeat pattern to fill duration
                total_steps = int(self.duration_s / step_s) + 1
                repeated = (freqs * ((total_steps // len(freqs)) + 1))[:total_steps]
                evs = build_melody_events(repeated, step_s, channel=ch, velocity=velocity)
                all_events.extend(evs)

        # Pad / chord
        if elements.get("pad", {}).get("active"):
            ch_cfg = self.instrument_mapping.get("pad", DEFAULT_INSTRUMENT_MAPPING["pad"])
            ch = ch_cfg["channel"]
            chords = elements["pad"].get("chords", [])
            if chords:
                # Repeat chord progression to fill duration
                n_chord_bars = int(self.duration_s / bar_s) + 1
                repeated = (chords * ((n_chord_bars // len(chords)) + 1))[:n_chord_bars]
                evs = build_chord_events(repeated, bar_s, channel=ch)
                all_events.extend(evs)

        # Bass
        if elements.get("bass", {}).get("active"):
            ch_cfg = self.instrument_mapping.get("bass", DEFAULT_INSTRUMENT_MAPPING["bass"])
            ch = ch_cfg["channel"]
            roots = elements["bass"].get("roots", [])
            if roots:
                evs = build_bass_events(roots, bar_s, n_bars=n_bars, channel=ch)
                all_events.extend(evs)

        # Drums
        if elements.get("drums", {}).get("active"):
            pattern = elements["drums"].get("pattern", {})
            pattern = {**pattern}  # copy
            if "snare_type" in elements["drums"]:
                pattern["snare_type"] = elements["drums"]["snare_type"]
            evs = build_drum_events(pattern, bar_s, n_bars=n_bars)
            all_events.extend(evs)

        # Render
        with FluidSynthBackend(sf2_path=self.sf2_path, sample_rate=self.sr) as backend:
            wav = backend.render(all_events, self.duration_s)

        return wav

    def _render_dawdreamer(self) -> np.ndarray:
        # G4 — not yet implemented
        raise NotImplementedError(
            "DawDreamer backend is planned for G4. "
            "Use backend='fluidsynth' or backend='synth'."
        )

    def _render_synth(self) -> np.ndarray:
        """Fall back to original music_engine (parametric DSP)."""
        import tempfile
        import soundfile as sf2
        from music_engine import MusicEngine

        # Set OUT to a temp .wav BEFORE creating MusicEngine (it caches self.OUT in __init__)
        tmp = tempfile.mktemp(suffix=".wav")
        orig_out = self.style["meta"].get("out", "output.mp3")
        self.style["meta"]["out"] = tmp
        try:
            eng = MusicEngine(self.style)
            eng.render()   # ffmpeg encodes to tmp (.wav → pcm via ffmpeg)
            data, sr = sf2.read(tmp)
        finally:
            self.style["meta"]["out"] = orig_out
            if os.path.exists(tmp):
                os.unlink(tmp)
        # Ensure stereo float32
        if data.ndim == 1:
            data = np.stack([data, data], axis=1)
        return data.astype(np.float32)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, path: str = None, format: str = "wav") -> str:
        """
        Save rendered audio.

        Args:
            path: output path (default: style meta.out, .wav suffix)
            format: "wav" or "mp3"

        Returns: actual output path
        """
        if self._wav is None:
            self.render()

        out = path or self.out_path
        # Ensure .wav for direct soundfile write
        if not out.endswith(".wav"):
            out_wav = out.rsplit(".", 1)[0] + ".wav"
        else:
            out_wav = out

        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        sf.write(out_wav, self._wav, self.sr)
        log.info(f"Saved: {out_wav}  backend={self._backend_name}")

        if format == "mp3":
            out_mp3 = out_wav.replace(".wav", ".mp3")
            _wav_to_mp3(out_wav, out_mp3)
            return out_mp3

        return out_wav


def _wav_to_mp3(wav_path: str, mp3_path: str, bitrate: str = "320k"):
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-i", wav_path,
        "-b:a", bitrate, "-q:a", "0",
        mp3_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
    log.info(f"MP3 encoded: {mp3_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Generate music via FluidSynth/Synth backend")
    parser.add_argument("style", nargs="?", help="Style JSON path")
    parser.add_argument("--out", help="Output file path (WAV or MP3)")
    parser.add_argument("--backend", choices=["auto", "fluidsynth", "dawdreamer", "synth"],
                        default="auto")
    parser.add_argument("--doctor", action="store_true", help="Show backend availability")
    args = parser.parse_args()

    if args.doctor:
        print_doctor()
        sys.exit(0)

    if not args.style:
        parser.print_help()
        sys.exit(1)

    with open(args.style) as f:
        style = json.load(f)

    if "generate" not in style:
        style["generate"] = {}
    style["generate"]["backend"] = args.backend

    eng = GenerateEngine(style)
    wav, sr = eng.render()
    out = eng.save(args.out, format="mp3" if (args.out or "").endswith(".mp3") else "wav")
    print(f"Output: {out}  ({len(wav)/sr:.1f}s, backend={eng._backend_name})")
