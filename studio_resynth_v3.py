#!/usr/bin/env python3
"""
studio_resynth_v3.py -- Hybrid Sampler + Synthesizer

Extracts real drum/bass samples from demucs stems, pitch-shifts for target
notes via pyrubberband, synthesizes melody via DX7 FM.

Drums: real hits sliced from drums.wav (kick/snare/hat classified by spectral centroid)
Bass:  real note slices from bass.wav, pitch-shifted to target frequencies
Melody: DX7 FM synthesis (strings/ep/bells presets)

Usage:
  python3 studio_resynth_v3.py \\
    --stems-dir shared/rework/demix_hq/htdemucs/mozgoviy_original \\
    --out shared/rework/mozgoviy_v3_hybrid.mp3 \\
    --melody-preset strings
"""

import argparse, os, sys, tempfile, warnings
warnings.filterwarnings("ignore")

import numpy as np
import scipy.signal
import soundfile as sf
import librosa

HAS_PYRB = False  # rubberband CLI not installed, use scipy resampling

try:
    from pedalboard import (Pedalboard, Reverb, Chorus, Compressor,
                            Gain, LowpassFilter, HighpassFilter, Delay)
    HAS_PB = True
except ImportError:
    HAS_PB = False

try:
    from audio_dsp.synth import DX7FMSynth
    HAS_DX7 = True
except ImportError:
    HAS_DX7 = False

SR = 44100
HOP = 512

# ---- DX7 presets ----

DX7_PRESETS = {
    "ep": {
        "freq_ratios": [1.0, 14.0, 1.0, 1.0],
        "mod_indices":  [1.5,  0.3, 0.8, 0.5],
        "algorithm": 1, "feedback": 0.1,
        "adsr": [
            {"attack": 0.01, "decay": 0.3, "sustain": 0.6, "release": 0.4},
            {"attack": 0.01, "decay": 0.1, "sustain": 0.0, "release": 0.2},
            {"attack": 0.01, "decay": 0.2, "sustain": 0.7, "release": 0.3},
            {"attack": 0.01, "decay": 0.3, "sustain": 0.5, "release": 0.4},
        ]
    },
    "strings": {
        "freq_ratios": [1.0, 1.0, 2.0, 3.0],
        "mod_indices":  [0.6, 0.25, 1.0, 0.3],
        "algorithm": 3, "feedback": 0.0,
        "adsr": [
            {"attack": 0.08, "decay": 0.4, "sustain": 0.8, "release": 0.6},
            {"attack": 0.05, "decay": 0.3, "sustain": 0.6, "release": 0.4},
            {"attack": 0.10, "decay": 0.5, "sustain": 0.7, "release": 0.5},
            {"attack": 0.06, "decay": 0.3, "sustain": 0.5, "release": 0.4},
        ]
    },
    "bells": {
        "freq_ratios": [1.0, 3.5, 1.0, 7.0],
        "mod_indices":  [2.0, 0.1, 1.5, 0.05],
        "algorithm": 2, "feedback": 0.0,
        "adsr": [
            {"attack": 0.001, "decay": 1.5, "sustain": 0.1, "release": 0.5},
            {"attack": 0.001, "decay": 0.5, "sustain": 0.0, "release": 0.3},
            {"attack": 0.001, "decay": 1.2, "sustain": 0.05, "release": 0.4},
            {"attack": 0.001, "decay": 0.8, "sustain": 0.0, "release": 0.3},
        ]
    },
}


# ===========================================================================
#  DrumSampler -- extract real hits from drums.wav, replay on original grid
# ===========================================================================

class DrumSampler:
    LABELS = ("kick", "snare", "hat")

    def __init__(self, drums_wav, sr=SR):
        self.sr = sr
        print("  Loading drums stem...")
        audio, fsr = sf.read(drums_wav)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if fsr != sr:
            audio = librosa.resample(audio, orig_sr=fsr, target_sr=sr)
        self.audio = audio.astype(np.float32)

        # onset detection
        onsets = librosa.onset.onset_detect(
            y=self.audio, sr=sr, hop_length=HOP,
            backtrack=True, units="samples"
        )
        print(f"  {len(onsets)} raw onsets")

        # slice and classify
        self.pool = {"kick": [], "snare": [], "hat": []}
        win = int(0.28 * sr)
        for pos in onsets:
            end = min(pos + win, len(self.audio))
            hit = self.audio[pos:end].copy()
            if len(hit) < 400:
                continue
            # fade out
            fade = min(256, len(hit) // 4)
            hit[-fade:] *= np.linspace(1, 0, fade)
            label = self._classify(hit)
            self.pool[label].append((pos, hit))

        for lb in self.LABELS:
            print(f"    {lb}: {len(self.pool[lb])} samples")

        tempo, beats = librosa.beat.beat_track(
            y=self.audio, sr=sr, hop_length=HOP, units="samples"
        )
        self.tempo = float(np.atleast_1d(tempo)[0])
        self.beats = beats
        print(f"  BPM: {self.tempo:.1f}, {len(beats)} beats")

    def _classify(self, hit):
        sc = float(librosa.feature.spectral_centroid(
            y=hit, sr=self.sr, hop_length=HOP).mean())
        # low-frequency energy ratio (below 250Hz vs total)
        S = np.abs(np.fft.rfft(hit[:min(2048, len(hit))]))
        freqs = np.fft.rfftfreq(min(2048, len(hit)), 1.0 / self.sr)
        low_mask = freqs < 250
        low_ratio = float(np.sum(S[low_mask]**2) / (np.sum(S**2) + 1e-12))
        if low_ratio > 0.35 or sc < 600:
            return "kick"
        elif sc > 4000:
            return "hat"
        else:
            return "snare"

    def render(self, n_total):
        """Stamp extracted samples at original positions with slight variation."""
        out = np.zeros(n_total, dtype=np.float32)
        counts = {"kick": 0, "snare": 0, "hat": 0}

        for label in self.LABELS:
            items = self.pool[label]
            if not items:
                continue
            for idx, (pos, _original_hit) in enumerate(items):
                # Round-robin pick from pool for natural variation
                pick_idx = (idx + np.random.randint(0, max(1, len(items)//3))) % len(items)
                hit = items[pick_idx][1].copy()
                hit *= np.random.uniform(0.88, 1.0)  # slight velocity variation
                end = min(pos + len(hit), n_total)
                n = end - pos
                if n > 0 and pos >= 0:
                    # soft clip before adding to prevent accumulation spikes
                    chunk = np.tanh(hit[:n] * 0.8) / 0.8
                    out[pos:end] += chunk
                    counts[label] += 1

        print(f"  Stamped: kick={counts['kick']} snare={counts['snare']} hat={counts['hat']}")
        # soft clip entire drum bus, then normalize
        out = np.tanh(out * 0.7) / 0.7
        peak = np.abs(out).max()
        if peak > 0.01:
            out *= 0.80 / peak
        return out


# ===========================================================================
#  BassSampler -- extract note slices, pitch-shift via pyrubberband
# ===========================================================================

class BassSampler:
    def __init__(self, bass_wav, sr=SR):
        self.sr = sr
        print("  Loading bass stem...")
        audio, fsr = sf.read(bass_wav)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if fsr != sr:
            audio = librosa.resample(audio, orig_sr=fsr, target_sr=sr)
        self.audio = audio.astype(np.float32)

        print("  Bass pitch detection (pyin 40-400Hz)...")
        self.f0, self.voiced, _ = librosa.pyin(
            self.audio, fmin=40, fmax=400, sr=sr, hop_length=HOP
        )
        self.f0 = np.where(self.voiced & ~np.isnan(self.f0), self.f0, 0.0)

        # extract reference samples at distinct pitches
        self.refs = {}
        self._extract_refs()
        print(f"  {len(self.refs)} reference pitches extracted")

    def _extract_refs(self):
        f0 = self.f0
        min_frames = int(0.25 * self.sr / HOP)
        i = 0
        candidates = []
        while i < len(f0):
            if f0[i] > 0:
                j = i + 1
                while j < len(f0) and f0[j] > 0 and abs(f0[j] - f0[i]) < 6:
                    j += 1
                if (j - i) >= min_frames:
                    avg = float(np.mean(f0[i:j][f0[i:j] > 0]))
                    candidates.append((avg, i * HOP, j * HOP))
                i = j
            else:
                i += 1

        # group by semitone, keep longest
        grouped = {}
        for freq, s, e in candidates:
            midi = int(round(12 * np.log2(freq / 440.0) + 69))
            if midi not in grouped or (e - s) > (grouped[midi][2] - grouped[midi][1]):
                grouped[midi] = (freq, s, e)

        for midi, (freq, s, e) in grouped.items():
            pad = int(0.03 * self.sr)
            s2 = max(0, s - pad)
            e2 = min(len(self.audio), e + pad)
            sl = self.audio[s2:e2].copy()
            # fade
            fade = min(256, len(sl) // 6)
            sl[:fade] *= np.linspace(0, 1, fade)
            sl[-fade:] *= np.linspace(1, 0, fade)
            self.refs[midi] = {"audio": sl, "f0": freq}

    def _shift_sample(self, src, src_f0, tgt_f0, dur_s):
        ratio = tgt_f0 / src_f0 if src_f0 > 0 else 1.0
        # Cap shift to ±7 semitones to avoid extreme aliasing
        ratio = np.clip(ratio, 2**(-7/12), 2**(7/12))
        n_out = int(dur_s * self.sr)

        if abs(ratio - 1.0) > 0.005:
            new_len = max(64, int(len(src) / ratio))
            shifted = scipy.signal.resample(src, new_len).astype(np.float32)
            # LP filter after resample to kill aliasing (cutoff at 0.9 * Nyquist)
            b, a = scipy.signal.butter(4, 0.88, btype='low')
            shifted = scipy.signal.filtfilt(b, a, shifted).astype(np.float32)
        else:
            shifted = src.copy()

        # fade in/out on the source sample before looping
        fi = min(256, len(shifted) // 6)
        shifted[:fi] *= np.linspace(0, 1, fi)
        fo = min(512, len(shifted) // 4)
        shifted[-fo:] *= np.linspace(1, 0, fo)

        # trim or loop with overlap-add crossfade
        if len(shifted) >= n_out:
            result = shifted[:n_out].copy()
        else:
            xfade = min(512, len(shifted) // 3)
            result = np.zeros(n_out, dtype=np.float32)
            pos = 0
            while pos < n_out:
                seg_len = min(len(shifted), n_out - pos)
                # blend previous tail with new head
                blend = min(xfade, pos, seg_len)
                if blend > 0:
                    w = np.linspace(0, 1, blend, dtype=np.float32)
                    result[pos:pos + blend] = (
                        result[pos:pos + blend] * (1 - w) +
                        shifted[:blend] * w
                    )
                    result[pos + blend:pos + seg_len] += shifted[blend:seg_len]
                else:
                    result[pos:pos + seg_len] += shifted[:seg_len]
                pos += len(shifted) - xfade

        # final fade out to avoid click at note end
        fade = min(int(0.05 * self.sr), len(result) // 3)
        if fade > 1:
            result[-fade:] *= np.linspace(1, 0, fade)

        # DC block
        result -= result.mean()
        return result.astype(np.float32)

    def render(self, n_total):
        out = np.zeros(n_total, dtype=np.float32)
        if not self.refs:
            print("  No bass references, skipping")
            return out

        # build note list
        f0 = self.f0
        notes = []
        i = 0
        while i < len(f0):
            if f0[i] > 0:
                j = i + 1
                while j < len(f0) and f0[j] > 0 and abs(f0[j] - f0[i]) < 8:
                    j += 1
                dur = (j - i) * HOP / self.sr
                avg = float(np.mean(f0[i:j][f0[i:j] > 0]))
                notes.append((avg, i * HOP, dur))
                i = j
            else:
                i += 1

        print(f"  BassSampler: {len(notes)} notes to render")

        for tgt_f0, start, dur in notes:
            if tgt_f0 <= 0 or dur < 0.04:
                continue
            tgt_midi = 12 * np.log2(tgt_f0 / 440.0) + 69
            # find nearest ref
            nearest = min(self.refs.keys(), key=lambda m: abs(m - tgt_midi))
            ref = self.refs[nearest]
            note = self._shift_sample(ref["audio"], ref["f0"], tgt_f0, dur)
            pos = int(start)
            end = min(pos + len(note), n_total)
            n = end - pos
            if n > 0:
                out[pos:end] += note[:n]

        peak = np.abs(out).max()
        if peak > 0.01:
            out *= 0.78 / peak
        return out


# ===========================================================================
#  DX7 melody synth (from v2, with ADSR overflow fix)
# ===========================================================================

def synth_dx7_melody(f0_arr, preset_cfg, n_total):
    if not HAS_DX7:
        print("  DX7 not available, returning silence")
        return np.zeros(n_total, dtype=np.float32)

    max_rel = max(op.get("release", 0.2) for op in preset_cfg["adsr"])
    min_dur = max_rel + 0.15

    voiced_mask = (f0_arr > 0) & (~np.isnan(f0_arr))
    f0s = f0_arr.copy()
    if np.sum(voiced_mask) > 11:
        idxs = np.where(voiced_mask)[0]
        f0s[idxs] = scipy.signal.savgol_filter(f0_arr[idxs], 11, 2)

    notes = []
    i = 0
    while i < len(f0s):
        f = f0s[i]
        if f > 0 and not np.isnan(f):
            j = i + 1
            while (j < len(f0s) and f0s[j] > 0
                   and not np.isnan(f0s[j])
                   and abs(f0s[j] - f) < 8.0):
                j += 1
            # gap merge (up to 3 silent frames)
            if j < len(f0s) - 3:
                gap_silent = all(
                    f0s[k] <= 0 or np.isnan(f0s[k])
                    for k in range(j, min(j + 3, len(f0s)))
                )
                if gap_silent:
                    nv = j + 3
                    if (nv < len(f0s) and f0s[nv] > 0
                            and abs(f0s[nv] - f) < 12.0):
                        j = nv
            dur = (j - i) * HOP / SR
            seg = f0s[i:j][(f0s[i:j] > 0) & (~np.isnan(f0s[i:j]))]
            avg = float(np.mean(seg) if len(seg) > 0 else f)
            notes.append((avg, i * HOP, dur))
            i = j
        else:
            i += 1

    print(f"  DX7: {len(notes)} notes (min_dur={min_dur:.2f}s)")
    out = np.zeros(n_total, dtype=np.float32)

    for freq, start, dur in notes:
        dx = DX7FMSynth(SR)
        dx.freq_ratios = preset_cfg["freq_ratios"]
        dx.mod_indices = preset_cfg["mod_indices"]
        dx.algorithm = preset_cfg["algorithm"]
        dx.feedback = preset_cfg["feedback"]
        dx.adsr = preset_cfg["adsr"]

        synth_dur = max(dur, min_dur)
        try:
            audio = dx.synthesize(freq=float(freq), duration=float(synth_dur))
        except Exception:
            continue
        take = int(dur * SR)
        audio = audio[:take].astype(np.float32)
        pos = int(start)
        end = min(pos + len(audio), n_total)
        n = end - pos
        if n > 0:
            out[pos:end] += audio[:n]

    return out


# ===========================================================================
#  FX helper
# ===========================================================================

def fx(audio, chain):
    if not HAS_PB or not chain:
        return audio
    board = Pedalboard(chain)
    if audio.ndim == 1:
        audio = audio[np.newaxis, :]
    result = board(audio, SR)
    return result[0] if result.ndim > 1 else result


# ===========================================================================
#  Main
# ===========================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stems-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--melody-preset", default="strings",
                    choices=list(DX7_PRESETS.keys()))
    ap.add_argument("--bass-level",   type=float, default=0.65)
    ap.add_argument("--melody-level", type=float, default=0.50)
    ap.add_argument("--drums-level",  type=float, default=0.55)
    ap.add_argument("--match-reference", default=None)
    args = ap.parse_args()

    stems = args.stems_dir
    drums_path = os.path.join(stems, "drums.wav")
    bass_path  = os.path.join(stems, "bass.wav")
    other_path = os.path.join(stems, "other.wav")

    info = sf.info(other_path)
    n_total = int(info.frames * SR / info.samplerate)
    dur_s = n_total / SR
    print(f"\nTrack: {dur_s:.1f}s")
    print(f"Hybrid: DrumSampler + BassSampler + DX7 {args.melody_preset}\n")

    # ---- DRUMS (real samples) ----
    print("=== DRUMS (real samples) ===")
    ds = DrumSampler(drums_path)
    drums = ds.render(n_total)
    if HAS_PB:
        drums = fx(drums, [
            Compressor(threshold_db=-14, ratio=3.0, attack_ms=5, release_ms=80),
            Gain(gain_db=1.5),
        ])
    drums *= args.drums_level
    print()

    # ---- BASS (real samples + pitch shift) ----
    print("=== BASS (sampler + pyrubberband) ===")
    bs = BassSampler(bass_path)
    bass = bs.render(n_total)
    if HAS_PB:
        bass = fx(bass, [
            LowpassFilter(cutoff_frequency_hz=350),
            Compressor(threshold_db=-10, ratio=4.0, attack_ms=8, release_ms=120),
            Gain(gain_db=2.5),
        ])
    bass *= args.bass_level
    print()

    # ---- MELODY (DX7 FM) ----
    print(f"=== MELODY (DX7 {args.melody_preset}) ===")
    print("  Loading other.wav...")
    other, fsr = sf.read(other_path)
    if other.ndim > 1:
        other = other.mean(axis=1)
    if fsr != SR:
        other = librosa.resample(other, orig_sr=fsr, target_sr=SR)

    print("  Pitch detection (pyin 80-3000Hz)...")
    f0, voiced, _ = librosa.pyin(
        other.astype(np.float32), fmin=80, fmax=3000, sr=SR, hop_length=HOP
    )
    f0 = np.where(voiced & ~np.isnan(f0), f0, 0.0)
    pct = 100 * np.mean(voiced)
    print(f"  Voiced: {pct:.0f}%  |  preset: {args.melody_preset}")

    melody = synth_dx7_melody(f0, DX7_PRESETS[args.melody_preset], n_total)
    if HAS_PB:
        melody = fx(melody, [
            Chorus(rate_hz=0.7, depth=0.2, mix=0.35),
            Reverb(room_size=0.3, damping=0.5, wet_level=0.22, dry_level=0.78),
            Compressor(threshold_db=-14, ratio=2.5, attack_ms=20, release_ms=200),
        ])
    melody *= args.melody_level
    print()

    # ---- MIXDOWN ----
    print("=== MIXDOWN ===")
    L = min(len(drums), len(bass), len(melody))
    mix = drums[:L] + bass[:L] + melody[:L]

    # master bus
    if HAS_PB:
        mix = fx(mix, [
            Compressor(threshold_db=-6, ratio=2.5, attack_ms=5, release_ms=150),
            Gain(gain_db=1.0),
        ])

    # peak normalize to -1 dBFS
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= (10 ** (-1.0/20)) / peak

    # write WAV
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    sf.write(tmp_path, mix, SR, subtype="PCM_24")
    print(f"  WAV: {tmp_path}")

    # matchering (optional)
    if args.match_reference and os.path.exists(args.match_reference):
        try:
            import matchering as mg
            out_m = tmp_path.replace(".wav", "_matched.wav")
            mg.process(
                target=tmp_path,
                reference=args.match_reference,
                results=[mg.Result(out_m, subtype="PCM_16", use_limiter=True)]
            )
            tmp_path = out_m
            print("  Matchered OK")
        except Exception as e:
            print(f"  Matchering failed: {e}")

    # encode MP3 320k
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    os.system(f'ffmpeg -y -i "{tmp_path}" -b:a 320k -q:a 0 "{args.out}" 2>/dev/null')

    # cleanup
    for f in [tmp_path, tmp_path.replace(".wav", "_matched.wav")]:
        if os.path.exists(f):
            os.unlink(f)

    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"\n* Gotovo: {args.out} ({size:.1f} MB)")
    print(f"  Drums: real samples | Bass: sampler+pitchshift | Melody: DX7 {args.melody_preset}")


if __name__ == "__main__":
    main()
