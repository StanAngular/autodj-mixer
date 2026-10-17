"""Where shared sound assets live. Override with env vars so other agents/users can point elsewhere."""
import os
ASSETS = os.environ.get("AUTODJ_ASSETS", "/home/cclaw/samples")
WA = os.path.join(ASSETS, "wa_techno", "WAV MIDI Presets")                    # W.A. Production techno packs
TDM = os.path.join(ASSETS, "tidal-drum-machines", "machines")                # LinnDrum, 707, 808, 909, R8 ...
MUSICRADAR = os.path.join(ASSETS, "musicradar")
WA2 = os.path.join(ASSETS, "wa2", "WAV MIDI Loops")                        # W.A. Fishy Tech House one-shots, loops, shots
VSCO = os.path.join(ASSETS, "vsco2")
VITAL_PRESETS = os.path.join(ASSETS, "vital_presets")
VITAL_VST3 = os.environ.get("AUTODJ_VITAL", "/home/cclaw/.vst3/Vital.vst3")
EDGE_TTS = os.environ.get("AUTODJ_EDGETTS", "/home/cclaw/.local/lib/edgetts")
