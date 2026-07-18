#!/usr/bin/env python3
"""
studio_resynth_v2.py — Professional re-synthesis using audio_dsp engines.

Upgrade over v1:
  - MELODY: DX7FMSynth (Yamaha DX7 emulation, 4-operator FM)
            → warm electric piano / strings / bells depending on preset
  - BASS:   DX7FMSynth bass preset OR SubtractiveSynth
  - DRUMS:  audio_dsp DrumSynth (kick/snare/cymbal/clap/tom)
            with all parameters exposed and tunable
  - EFFECTS: pedalboard (Spotify) per stem + master bus
  - MASTERING: matchering (optional, reference-based auto-master)

Usage:
  python3 studio_resynth_v2.py \
    --stems-dir shared/rework/demix_hq/htdemucs/mozgoviy_original \
    --out shared/rework/mozgoviy_studio_v2.mp3 \
    [--melody-preset ep|strings|bells|flute]
    [--bass-preset fm|sub|acid]
    [--match-reference path/to/reference.mp3]
"""

import argparse, os, sys, tempfile, subprocess, json
import numpy as np
import scipy.signal
import librosa
import soundfile as sf

try:
    from pedalboard import (Pedalboard, Reverb, Chorus, Compressor,
                            Gain, LowpassFilter, HighpassFilter, Delay)
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

try:
    from audio_dsp.synth import DX7FMSynth, SubtractiveSynth, DrumSynth
    HAS_AUDIODSP = True
except ImportError:
    HAS_AUDIODSP = False

try:
    import matchering
    HAS_MATCHERING = True
except ImportError:
    HAS_MATCHERING = False

SR = 44100
HOP = 512


# ═══════════════════════════════════════════
# DX7 FM presets
# ═══════════════════════════════════════════

DX7_PRESETS = {
    "ep": {
        # Classic Yamaha DX7 electric piano (Rhodes-like)
        "freq_ratios": [1.0, 14.0, 1.0, 1.0],
        "mod_indices":  [1.5,  0.3,  0.8, 0.5],
        "algorithm":    1,
        "feedback":     0.1,
        "adsr": [
            {"attack": 0.008, "decay": 0.4, "sustain": 0.3, "release": 0.6},
            {"attack": 0.005, "decay": 0.25, "sustain": 0.15, "release": 0.3},
            {"attack": 0.008, "decay": 0.35, "sustain": 0.4, "release": 0.5},
            {"attack": 0.008, "decay": 0.35, "sustain": 0.4, "release": 0.5},
        ],
    },
    "strings": {
        # Soft string ensemble
        "freq_ratios": [1.0, 1.0, 2.0, 3.0],
        "mod_indices":  [0.6, 0.25, 1.0, 0.3],
        "algorithm":    3,
        "feedback":     0.0,
        "adsr": [
            {"attack": 0.08, "decay": 0.3, "sustain": 0.8, "release": 0.6},
            {"attack": 0.06, "decay": 0.2, "sustain": 0.6, "release": 0.4},
            {"attack": 0.08, "decay": 0.3, "sustain": 0.8, "release": 0.6},
            {"attack": 0.08, "decay": 0.3, "sustain": 0.8, "release": 0.6},
        ],
    },
    "bells": {
        # Bell / vibraphone character
        "freq_ratios": [1.0, 3.5, 1.0, 7.0],
        "mod_indices":  [2.0, 0.1, 1.5, 0.05],
        "algorithm":    2,
        "feedback":     0.0,
        "adsr": [
            {"attack": 0.003, "decay": 1.5, "sustain": 0.0, "release": 1.0},
            {"attack": 0.003, "decay": 1.0, "sustain": 0.0, "release": 0.8},
            {"attack": 0.003, "decay": 1.5, "sustain": 0.0, "release": 1.0},
            {"attack": 0.003, "decay": 1.5, "sustain": 0.0, "release": 1.0},
        ],
    },
    "organ": {
        # Hammond-like organ
        "freq_ratios": [1.0, 2.0, 3.0, 4.0],
        "mod_indices":  [0.5, 0.4, 0.3, 0.2],
        "algorithm":    0,
        "feedback":     0.3,
        "adsr": [
            {"attack": 0.01, "decay": 0.05, "sustain": 0.9, "release": 0.05},
            {"attack": 0.01, "decay": 0.05, "sustain": 0.9, "release": 0.05},
            {"attack": 0.01, "decay": 0.05, "sustain": 0.9, "release": 0.05},
            {"attack": 0.01, "decay": 0.05, "sustain": 0.9, "release": 0.05},
        ],
    },
}

DX7_BASS_PRESETS = {
    "fm": {
        # Rich FM bass (Juno/DX-style)
        "freq_ratios": [1.0, 3.0, 0.5, 2.0],
        "mod_indices":  [3.5, 0.2, 2.5, 0.3],
        "algorithm":    4,
        "feedback":     0.15,
        "adsr": [
            {"attack": 0.005, "decay": 0.25, "sustain": 0.6, "release": 0.15},
            {"attack": 0.004, "decay": 0.15, "sustain": 0.3, "release": 0.1},
            {"attack": 0.005, "decay": 0.2, "sustain": 0.5, "release": 0.1},
            {"attack": 0.005, "decay": 0.2, "sustain": 0.5, "release": 0.1},
        ],
    },
}


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════

def butter_lp(y, cutoff, order=4):
    sos = scipy.signal.butter(order, cutoff, btype='low', fs=SR, output='sos')
    return scipy.signal.sosfilt(sos, y).astype(np.float32)


def butter_hp(y, cutoff, order=4):
    sos = scipy.signal.butter(order, cutoff, btype='high', fs=SR, output='sos')
    return scipy.signal.sosfilt(sos, y).astype(np.float32)


def apply_fx(y_mono, preset, level_db=0):
    """Apply pedalboard effects chain per stem."""
    if not HAS_PEDALBOARD:
        return y_mono
    audio = y_mono.reshape(1, -1).astype(np.float32)

    if preset == "melody_ep":
        board = Pedalboard([
            Chorus(rate_hz=0.7, depth=0.35, mix=0.25),
            Reverb(room_size=0.55, damping=0.6, wet_level=0.30, dry_level=0.70, width=0.9),
            Compressor(threshold_db=-18, ratio=2.5, attack_ms=10, release_ms=100),
            Gain(gain_db=level_db),
        ])
    elif preset == "melody_strings":
        board = Pedalboard([
            Chorus(rate_hz=0.4, depth=0.5, mix=0.35),
            Reverb(room_size=0.7, damping=0.5, wet_level=0.40, dry_level=0.60, width=1.0),
            Compressor(threshold_db=-20, ratio=2.0, attack_ms=20, release_ms=200),
            Gain(gain_db=level_db),
        ])
    elif preset == "bass":
        board = Pedalboard([
            Compressor(threshold_db=-12, ratio=4.0, attack_ms=4, release_ms=60),
            LowpassFilter(cutoff_frequency_hz=500),
            Gain(gain_db=level_db + 2),
        ])
    elif preset == "drums":
        board = Pedalboard([
            Compressor(threshold_db=-16, ratio=3.0, attack_ms=2, release_ms=50),
            Reverb(room_size=0.15, damping=0.85, wet_level=0.08, dry_level=0.92, width=0.5),
            Gain(gain_db=level_db),
        ])
    elif preset == "master":
        board = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=28),
            Compressor(threshold_db=-14, ratio=2.2, attack_ms=12, release_ms=130),
            LowpassFilter(cutoff_frequency_hz=18000),
            Gain(gain_db=level_db),
        ])
    else:
        return y_mono

    return board(audio, SR).flatten().astype(np.float32)


def orig_envelope(y_orig, smooth_ms=500):
    """Extract amplitude envelope from original stem."""
    win = max(3, int(smooth_ms * SR / 1000))
    if win % 2 == 0:
        win += 1
    env = np.abs(y_orig)
    env = scipy.signal.savgol_filter(env, win, 3)
    env = np.clip(env, 0, None)
    mx = np.max(env)
    if mx > 0:
        env /= mx
    return env.astype(np.float32)


def haas_stereo(y_mono, delay_ms=8.0):
    """Haas-effect stereo width."""
    delay = int(delay_ms * SR / 1000)
    n = len(y_mono)
    stereo = np.zeros((n, 2), dtype=np.float32)
    stereo[:, 0] = y_mono
    if delay < n:
        stereo[delay:, 1] = y_mono[:-delay] * 0.85
    return stereo


def mono_to_stereo(y_mono):
    return np.column_stack([y_mono, y_mono])


# ═══════════════════════════════════════════
# DX7 pitch-track synthesizer
# ═══════════════════════════════════════════

def synth_dx7_track(f0_arr, preset_cfg, n_total):
    """
    Render full track using DX7FMSynth.
    Groups consecutive similar pitches into notes, merges short fragments,
    enforces minimum synthesis duration >= max(release) to avoid ADSR overflow.
    """
    if not HAS_AUDIODSP:
        raise RuntimeError("audio_dsp not installed")

    # Max release time across all operators (need at least this much duration)
    max_release = max(op.get("release", 0.2) for op in preset_cfg["adsr"])
    min_dur = max_release + 0.15  # minimum note duration passed to DX7

    # Smooth out micro-variations in pitch (savgol filter)
    voiced_mask = (f0_arr > 0) & (~np.isnan(f0_arr))
    f0_smooth = f0_arr.copy()
    if np.sum(voiced_mask) > 11:
        idxs = np.where(voiced_mask)[0]
        f0_smooth[idxs] = scipy.signal.savgol_filter(f0_arr[idxs], 11, 2)

    # Build note list with looser grouping (±8Hz = same note)
    notes = []
    i = 0
    while i < len(f0_smooth):
        f = f0_smooth[i]
        if f > 0 and not np.isnan(f):
            j = i + 1
            while (j < len(f0_smooth) and
                   f0_smooth[j] > 0 and
                   abs(f0_smooth[j] - f) < 8.0):
                j += 1
            # Merge gap of <= 3 silent frames into note
            if (j < len(f0_smooth) - 3 and
                    all(f0_smooth[k] <= 0 for k in range(j, min(j+3, len(f0_smooth))))):
                next_voiced = j + 3
                if (next_voiced < len(f0_smooth) and
                        f0_smooth[next_voiced] > 0 and
                        abs(f0_smooth[next_voiced] - f) < 12.0):
                    j = next_voiced
            dur_s = (j - i) * HOP / SR
            seg = f0_smooth[i:j][f0_smooth[i:j] > 0]
            avg_f = float(np.mean(seg) if len(seg) > 0 else f)
            notes.append((avg_f, i * HOP, j * HOP, dur_s))
            i = j
        else:
            i += 1

    print(f"  DX7: {len(notes)} notes (min_dur={min_dur:.2f}s)")

    out = np.zeros(n_total, dtype=np.float32)

    for f0, start, end, dur in notes:
        dx = DX7FMSynth(SR)
        dx.freq_ratios = preset_cfg["freq_ratios"]
        dx.mod_indices  = preset_cfg["mod_indices"]
        dx.algorithm    = preset_cfg["algorithm"]
        dx.feedback     = preset_cfg["feedback"]
        dx.adsr         = preset_cfg["adsr"]

        f0_rand = f0 * (1 + np.random.uniform(-0.0008, 0.0008))

        # Synthesize at least min_dur to avoid ADSR overflow
        synth_dur = max(dur, min_dur)
        note_audio = dx.synthesize(freq=float(f0_rand), duration=float(synth_dur))
        # Take only the note's actual duration (with fade-out from release)
        take_samples = int(dur * SR)
        note_audio = note_audio[:take_samples].astype(np.float32)

        note_len = len(note_audio)
        avail = n_total - start
        write_len = min(note_len, avail)
        if write_len > 0:
            out[start : start + write_len] += note_audio[:write_len]

    return out


# ═══════════════════════════════════════════
# Per-stem processors
# ═══════════════════════════════════════════

def process_melody(path, preset_name="ep"):
    """Other stem → DX7 FM synthesis with chosen preset."""
    print(f"  Loading {os.path.basename(path)}...")
    y, _ = librosa.load(path, sr=SR, mono=True)
    n_total = len(y)

    print(f"  Pitch detection (pyin 80-3000Hz)...")
    f0, voiced, prob = librosa.pyin(
        y, fmin=80, fmax=3000, sr=SR,
        hop_length=HOP, fill_na=0.0
    )
    voiced_pct = np.mean(voiced) * 100
    print(f"  Voiced: {voiced_pct:.0f}%  |  preset: {preset_name}")

    cfg = DX7_PRESETS.get(preset_name, DX7_PRESETS["ep"])
    synth = synth_dx7_track(f0, cfg, n_total)

    # Follow original dynamics
    env = orig_envelope(y, smooth_ms=800)
    n = min(len(env), len(synth))
    synth[:n] *= env[:n]

    # LP to remove harsh artifacts from FM at high pitches
    synth = butter_lp(synth, 7000)

    fx_preset = "melody_ep" if preset_name in ("ep", "organ") else "melody_strings"
    synth = apply_fx(synth, fx_preset)

    return synth


def process_bass(path, preset_name="fm"):
    """Bass stem → DX7 FM bass synthesis."""
    print(f"  Loading {os.path.basename(path)}...")
    y, _ = librosa.load(path, sr=SR, mono=True)
    n_total = len(y)

    print(f"  Bass pitch detection (pyin 40-400Hz)...")
    f0, voiced, prob = librosa.pyin(
        y, fmin=40, fmax=400, sr=SR,
        hop_length=HOP, fill_na=0.0
    )

    cfg = DX7_BASS_PRESETS.get(preset_name, DX7_BASS_PRESETS["fm"])
    synth = synth_dx7_track(f0, cfg, n_total)

    env = orig_envelope(y, smooth_ms=300)
    n = min(len(env), len(synth))
    synth[:n] *= env[:n]

    synth = butter_lp(synth, 400)
    synth = apply_fx(synth, "bass")

    return synth


def process_drums(path, n_total):
    """Drums → audio_dsp DrumSynth (kick/snare/cymbal/clap/tom)."""
    print(f"  Loading drum stem for analysis...")
    y, _ = librosa.load(path, sr=SR, mono=True)

    # Beat tracking
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=SR, hop_length=HOP)
    beat_samples = librosa.frames_to_samples(beat_frames, hop_length=HOP)
    tempo_val = float(np.atleast_1d(tempo)[0])

    # Onset detection
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=SR, hop_length=HOP, backtrack=True, units='frames'
    )
    onset_samples = librosa.frames_to_samples(onset_frames, hop_length=HOP)

    # Spectral centroid for hit classification
    centroids = librosa.feature.spectral_centroid(y=y, sr=SR, hop_length=HOP)[0]

    print(f"  {len(beat_samples)} beats @ {tempo_val:.1f} BPM, {len(onset_samples)} onsets")

    # Instantiate DrumSynth with tuned parameters
    drum = DrumSynth(SR)

    # Pre-render hits (soft, low-frequency, warm)
    kick   = drum.kick(length=0.5,  max_pitch=200,  min_pitch=40,   decay_factor=20)
    snare  = drum.snare(length=0.4, high_pitch=600, low_pitch=200,  decay_factor=45, mix=0.4)
    cym    = drum.cymbal(length=0.18, op_a_freq=5000, op_b_freq=600,
                         noise_env=70, tone_env=12, cutoff=4000, mix=0.4)
    clap   = drum.clap(length=0.3)
    tom_hi = drum.tom(length=0.35, max_pitch=200, min_pitch=100, decay_factor=25)
    tom_lo = drum.tom(length=0.45, max_pitch=100, min_pitch=60,  decay_factor=20)

    out = np.zeros(n_total, dtype=np.float32)

    def stamp(buf, hit, pos):
        end = min(pos + len(hit), len(buf))
        n = end - pos
        if n > 0 and pos >= 0:
            buf[pos:end] += hit[:n]

    # Kick: every 2 beats (beats 1, 3)
    # Snare: offbeats (beats 2, 4)
    for i, pos in enumerate(beat_samples):
        if pos >= n_total:
            break
        if i % 2 == 0:
            stamp(out, kick, pos)
        else:
            # Alternate snare and clap for variety
            stamp(out, snare if (i // 2) % 4 != 2 else clap, pos)

    # Hi-hats from onsets above spectral centroid threshold
    for pos in onset_samples:
        if pos >= n_total:
            break
        too_close = any(abs(pos - b) < HOP * 3 for b in beat_samples)
        if too_close:
            continue
        frame_idx = min(pos // HOP, len(centroids) - 1)
        cent = centroids[frame_idx]
        if cent > 3500:
            stamp(out, cym, pos)

    # Occasional tom fills (every 8 beats, before the snare)
    for i, pos in enumerate(beat_samples):
        if i % 8 == 6 and pos >= n_total * 0.1:  # skip intro
            if pos + HOP < n_total:
                stamp(out, tom_hi, pos)
            if pos + HOP * 2 < n_total:
                stamp(out, tom_lo, pos + HOP * 2)

    # Normalize
    mx = np.max(np.abs(out))
    if mx > 0:
        out /= mx

    out = apply_fx(out, "drums")
    return out


# ═══════════════════════════════════════════
# Main
# ═══════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Studio v2: DX7FM + DrumSynth + pedalboard + optional matchering"
    )
    ap.add_argument("--stems-dir",   required=True)
    ap.add_argument("--out",         required=True)
    ap.add_argument("--melody-preset", default="ep",
                    choices=list(DX7_PRESETS.keys()),
                    help="DX7 melody preset. Default: ep")
    ap.add_argument("--bass-preset", default="fm",
                    choices=list(DX7_BASS_PRESETS.keys()))
    ap.add_argument("--bass-level",   type=float, default=0.70)
    ap.add_argument("--melody-level", type=float, default=0.55)
    ap.add_argument("--drums-level",  type=float, default=0.50)
    ap.add_argument("--match-reference", default=None,
                    help="Optional audio file to match mastering level/EQ to")
    args = ap.parse_args()

    bass_path  = os.path.join(args.stems_dir, "bass.wav")
    other_path = os.path.join(args.stems_dir, "other.wav")
    drums_path = os.path.join(args.stems_dir, "drums.wav")

    for p in [bass_path, other_path, drums_path]:
        if not os.path.exists(p):
            print(f"ERROR: {p} not found", file=sys.stderr)
            sys.exit(1)

    ref_dur = librosa.get_duration(path=bass_path)
    n_total = int(ref_dur * SR)
    print(f"Track: {ref_dur:.1f}s")
    print(f"Synth: DX7FMSynth + DrumSynth | Pedalboard: {HAS_PEDALBOARD}")
    print(f"Melody preset: {args.melody_preset} | Bass: {args.bass_preset}")
    print()

    # ── Synthesize ──
    print("═══ MELODY (DX7 FM) ═══")
    melody = process_melody(other_path, args.melody_preset)
    melody = melody[:n_total] if len(melody) >= n_total else np.pad(melody, (0, n_total - len(melody)))

    print("\n═══ BASS (DX7 FM) ═══")
    bass = process_bass(bass_path, args.bass_preset)
    bass = bass[:n_total] if len(bass) >= n_total else np.pad(bass, (0, n_total - len(bass)))

    print("\n═══ DRUMS (DrumSynth) ═══")
    drums = process_drums(drums_path, n_total)
    drums = drums[:n_total] if len(drums) >= n_total else np.pad(drums, (0, n_total - len(drums)))

    # ── Stereo mixdown ──
    print("\n═══ MIXDOWN ═══")
    mel_stereo   = haas_stereo(melody * args.melody_level, delay_ms=9.0)
    bass_stereo  = mono_to_stereo(bass * args.bass_level)
    drums_stereo = haas_stereo(drums * args.drums_level, delay_ms=2.5)

    n_min = min(mel_stereo.shape[0], bass_stereo.shape[0], drums_stereo.shape[0])
    mix = mel_stereo[:n_min] + bass_stereo[:n_min] + drums_stereo[:n_min]

    # Master bus
    for ch in range(2):
        mix[:, ch] = apply_fx(mix[:, ch], "master")

    # Peak normalize -1dBFS
    mx = np.max(np.abs(mix))
    if mx > 0:
        mix = mix / mx * 0.891

    # ── Export WAV ──
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = tmp.name
    sf.write(tmp_wav, mix, SR, subtype='PCM_24')
    print(f"  WAV written: {tmp_wav}")

    # ── Matchering (optional) ──
    if args.match_reference and HAS_MATCHERING and os.path.exists(args.match_reference):
        print(f"  Matchering against: {args.match_reference}")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as m:
            matched_wav = m.name
        try:
            matchering.process(
                target=tmp_wav,
                reference=args.match_reference,
                results=[matchering.Result(matched_wav, use_limiter=True, normalize=True)]
            )
            os.unlink(tmp_wav)
            tmp_wav = matched_wav
            print("  Matchering: DONE")
        except Exception as e:
            print(f"  Matchering failed: {e} -- using unmatched")

    # ── Encode MP3 ──
    print(f"  Encoding → {args.out}")
    cmd = ["ffmpeg", "-y", "-i", tmp_wav,
           "-af", "loudnorm=I=-14:TP=-1:LRA=9",
           "-c:a", "libmp3lame", "-b:a", "320k",
           args.out]
    r = subprocess.run(cmd, capture_output=True)
    os.unlink(tmp_wav)

    if r.returncode != 0:
        print(r.stderr.decode()[-1000:], file=sys.stderr)
        sys.exit(1)

    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"\n✓ Готово: {args.out} ({size:.1f} MB)")
    print(f"  Instruments: DX7 {args.melody_preset} | DX7 bass | DrumSynth")


if __name__ == "__main__":
    main()
