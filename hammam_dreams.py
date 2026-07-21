#!/usr/bin/env python3
"""
Hammam Dreams — Spa Massage Ambient (Turkish All-Inclusive)
Duration: 15:00 (900s)
BPM: 55 | Key: C Major Pentatonic (A=432 Hz)
Pure math synth — ultra-light, warm, meditative for massage room
"""
import os, sys, math, time, logging
import numpy as np

sys.path.insert(0, '/opt/autodj-mixer')
os.chdir('/opt/autodj-mixer')

from autodj.generate.synthcore import (
    sine_wave, sawtooth_bl, square_bl, supersaw,
    lpf, hpf, adsr,
    apply_reverb, apply_compressor,
    midi_to_hz, normalize_master, mono_to_stereo,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('hammam')

BPM = 55
SR = 44100
BAR_S = 60.0 / BPM * 4          # ~4.36 s
DURATION_S = 900                  # 15:00
N_SAMPLES = int(DURATION_S * SR)

A432_RATIO = 432.0 / 440.0

def c_pent(octave=4):
    c = 261.63 * A432_RATIO * (2 ** (octave - 4))
    return {
        'C': c, 'D': c * 2**(2/12), 'E': c * 2**(4/12),
        'G': c * 2**(7/12), 'A': c * 2**(9/12),
    }

# Warm middle eastern-ish scale: C D E G A + half-flat second for hint
def warm_scale(octave=4):
    c = 261.63 * A432_RATIO * (2 ** (octave - 4))
    return {
        'C': c,
        'D': c * 2**(2/12),
        'Eb_half': c * 2**(2.5/12),  # microtonal quarter
        'E': c * 2**(4/12),
        'G': c * 2**(7/12),
        'A': c * 2**(9/12),
        'Bb': c * 2**(10/12),
    }

C1 = c_pent(1); C2 = c_pent(2); C3 = c_pent(3)
C4 = c_pent(4); C5 = c_pent(5)
W3 = warm_scale(3); W4 = warm_scale(4); W5 = warm_scale(5)

PHASES = {
    'sunrise': (0, 240),        # 0:00-4:00 — warm drone enters
    'daylight': (240, 540),     # 4:00-9:00 — full warmth, soft chimes
    'sunset': (540, 780),       # 9:00-13:00 — winding down
    'night': (780, 900),        # 13:00-15:00 — fade to silence
}

def phase_at(t):
    for name, (s, e) in PHASES.items():
        if s <= t < e:
            return name, (t - s) / (e - s)
    return 'night', 1.0


def build_warm_drone():
    """Warm brown noise + sub-bass + air, very gentle."""
    log.info("Building warm drone...")
    t0 = time.time()
    t = np.arange(N_SAMPLES) / SR

    # Warm noise: pink-ish through LP
    np.random.seed(0)
    white = np.random.randn(N_SAMPLES)
    warm = np.cumsum(white)  # brownish
    warm = warm / np.max(np.abs(warm)) * 0.25
    warm = lpf(warm, 300, q=0.0, sr=SR)

    # Sub-bass: very gentle C1-G2 pedal
    roots = [C1['C'], C1['G'], C2['C'], C2['G'],
             C1['C'], C2['G'], C2['C'], C1['G']]
    sub = np.zeros(N_SAMPLES)
    chord_dur = 16 * BAR_S
    for i, root in enumerate(roots):
        s = int(i * chord_dur * SR)
        e = int(min((i + 1) * chord_dur, DURATION_S) * SR)
        n = max(e - s, 1)
        sub[s:e] = sine_wave(root, n, sr=SR) * 0.15 + sine_wave(root * 1.5, n, sr=SR) * 0.08

    # Air layer: filtered white noise, very quiet
    np.random.seed(7)
    air_noise = np.random.randn(N_SAMPLES) * 0.02
    air_noise = lpf(air_noise, 8000, q=0.0, sr=SR)

    # Gentle breathing LFO (12s cycle)
    phase = (t % 12.0) / 12.0
    rise_f = 5.0 / 12.0
    breath = np.where(phase < rise_f,
                      phase / rise_f,
                      1.0 - (phase - rise_f) / (1.0 - rise_f))
    breath = 0.6 + 0.4 * breath  # 0.6-1.0

    drone = warm * 0.35 + sub * 0.50 + air_noise * 0.15
    drone = drone * breath
    drone = lpf(drone, 500, q=0.4, sr=SR)

    log.info(f"  Drone done: {time.time()-t0:.1f}s")
    return drone


def build_warm_pad():
    """Very soft, warm pad — detuned sines, no harshness."""
    log.info("Building warm pad...")
    t0 = time.time()

    chords = [
        [C4['C'], C4['E'], C4['G'], C5['C']],
        [C4['G'], C4['D'], C5['G'], C3['C']],
        [W4['A'], W4['C'], W4['E'], W5['A']],
        [W4['D'], W4['G'], W5['D'], W4['A']],
        [C4['E'], C4['G'], C5['C'], C5['E']],
    ]

    out = np.zeros((N_SAMPLES, 2), dtype=np.float32)
    chord_dur = 12 * BAR_S  # ~52s per chord

    for ci, chord in enumerate(chords):
        s = int(ci * chord_dur * SR)
        e = int(min((ci + 1) * chord_dur, DURATION_S) * SR)
        if s >= N_SAMPLES: break
        n = e - s

        left = np.zeros(n)
        right = np.zeros(n)
        for freq in chord:
            # Very gentle detuned sines
            left += sine_wave(freq, n, sr=SR) * 0.08
            right += sine_wave(freq + 3.0, n, sr=SR) * 0.08
            # Add soft 5th overtone
            left += sine_wave(freq * 3, n, sr=SR) * 0.02
            right += sine_wave(freq * 3 + 3.0, n, sr=SR) * 0.02

        left = lpf(left, 2500, q=0.1, sr=SR)
        right = lpf(right, 2500, q=0.1, sr=SR)

        # Volume automation
        for j in range(n):
            tt = (s + j) / SR
            phase, prog = phase_at(tt)
            if phase == 'sunrise':
                vol = 0.06 + 0.10 * prog
            elif phase == 'daylight':
                vol = 0.16
            elif phase == 'sunset':
                vol = 0.16 - 0.10 * prog
            else:
                fade = max(0, (tt - 780) / 120)
                vol = 0.06 * (1 - fade)
            left[j] *= vol
            right[j] *= vol

        out[s:e, 0] += left
        out[s:e, 1] += right

    out = apply_reverb(out, sr=SR, room_size=0.7, damping=0.5, wet=0.35)

    log.info(f"  Pad done: {time.time()-t0:.1f}s")
    return out


def build_water_splashes():
    """Very gentle water droplet plinks — like a spa fountain."""
    log.info("Building water splashes...")
    t0 = time.time()

    stereo = np.zeros((N_SAMPLES, 2), dtype=np.float32)
    np.random.seed(42)
    count = 0

    for t_s in np.arange(0, DURATION_S, 0.6):
        phase, prog = phase_at(t_s)
        prob = 0.0
        if phase == 'sunrise':
            prob = 0.08 + 0.02 * np.sin(t_s * 0.06)
        elif phase == 'daylight':
            prob = 0.06 + 0.01 * np.sin(t_s * 0.05)
        elif phase == 'sunset':
            prob = 0.04 - 0.02 * prog
        elif phase == 'night':
            prob = 0.01 * max(0, 1 - prog * 2)

        if prob > 0 and np.random.random() < prob:
            pitches = [C5['C'], C5['E'], C5['G'], C5['A'],
                       W5['D'], W5['Eb_half'], C4['C']]
            freq = np.random.choice(pitches)
            vel = np.random.uniform(0.15, 0.30)  # very soft!
            dur_s = 0.06 + np.random.random() * 0.10
            s = int(t_s * SR)
            n = int(dur_s * SR)
            if s + n > N_SAMPLES: n = N_SAMPLES - s

            plink = sine_wave(freq, max(n, 1), sr=SR)
            plink = plink * np.exp(-np.linspace(0, 20, max(n, 1)))
            plink = plink * vel

            p = np.random.uniform(-0.7, 0.7)
            stereo[s:s+n, 0] += plink * (1 - p) * 0.5
            stereo[s:s+n, 1] += plink * (1 + p) * 0.5
            count += 1

    log.info(f"  {count} splashes done: {time.time()-t0:.1f}s")
    return stereo


def build_wind_chimes():
    """Very soft zither/harp-like gentle plucks — Turkish spa atmosphere."""
    log.info("Building wind chimes...")
    t0 = time.time()

    stereo = np.zeros((N_SAMPLES, 2), dtype=np.float32)
    np.random.seed(17)
    count = 0

    # Rare, gentle chime events
    for t_s in np.arange(0, DURATION_S, 1.5):
        phase, prog = phase_at(t_s)
        prob = 0.0
        if phase == 'sunrise':
            prob = 0.0
        elif phase == 'daylight':
            prob = 0.02 + 0.01 * np.sin(t_s * 0.03)
        elif phase == 'sunset':
            prob = 0.03 - 0.015 * prog
        elif phase == 'night':
            prob = 0.0

        if prob > 0 and np.random.random() < prob:
            # Zither-like: bright but soft
            pitches = [W5['C'], W5['E'], W5['G'], W5['A'],
                       W4['A'], W4['G'], W4['E']]
            freq = np.random.choice(pitches)
            vel = np.random.uniform(0.12, 0.25)
            dur_s = np.random.uniform(1.0, 3.5)
            s = int(t_s * SR)
            n = int(dur_s * SR)
            if s + n > N_SAMPLES: n = N_SAMPLES - s

            t_env = np.linspace(0, dur_s, max(n, 1))
            # Soft bell: multiple partials, slow decay
            chime = (
                np.sin(2 * np.pi * freq * t_env) +
                0.3 * np.sin(2 * np.pi * freq * 3.0 * t_env) +
                0.1 * np.sin(2 * np.pi * freq * 5.1 * t_env)
            )
            chime = chime * np.exp(-t_env * 0.8)
            chime = chime * vel * 0.3

            # Wide stereo pan with slight movement
            p = np.random.uniform(-0.9, 0.9)
            # Slow pan sweep
            sweep = 0.1 * np.sin(np.linspace(0, np.pi, max(n, 1)))
            p_swept = p + sweep

            stereo[s:s+n, 0] += chime * (1 - p_swept) * 0.4
            stereo[s:s+n, 1] += chime * (1 + p_swept) * 0.4
            count += 1

    # Light shimmer reverb
    stereo = apply_reverb(stereo, sr=SR, room_size=0.6, damping=0.3, wet=0.4)

    log.info(f"  {count} chimes done: {time.time()-t0:.1f}s")
    return stereo


def render():
    log.info("╔══════════════════════════════════════════════════════╗")
    log.info("║  HAMMAM DREAMS — Spa Massage Ambient                ║")
    log.info("║  55 BPM · Warm Pentatonic (432 Hz) · 15:00          ║")
    log.info("║  Turkish all inclusive · massage room · relaxation   ║")
    log.info("╚══════════════════════════════════════════════════════╝")
    total_t0 = time.time()

    drone = build_warm_drone()
    pad = build_warm_pad()
    water = build_water_splashes()
    chimes = build_wind_chimes()

    # ── Mix ──
    log.info("Mixing layers...")
    t0 = time.time()

    out = np.zeros((N_SAMPLES, 2), dtype=np.float32)
    # Drone → stereo (center, warm foundation)
    for ch in range(2):
        out[:, ch] += drone * 0.30

    # Pad → stereo
    out += pad * 0.25

    # Water drops (very gentle)
    out += water * 0.12

    # Wind chimes (subtle texture)
    out += chimes * 0.15

    # Master volume — intentionally low for spa (-18 dB RMS target)
    log.info("Master bus...")
    # Very gentle compressor
    out = apply_compressor(out, sr=SR, threshold_db=-24, ratio=1.5,
                           attack_ms=100, release_ms=600)
    out = normalize_master(out, target_db=-18)

    # Ultra-soft peak limit
    peak = np.abs(out).max()
    if peak > 0.5:
        out *= 0.5 / peak

    rms = np.sqrt(np.mean(out ** 2))
    log.info(f"Render complete: peak={np.abs(out).max():.4f}, RMS={20*np.log10(rms+1e-10):.1f} dBFS")
    log.info(f"Total time: {time.time()-total_t0:.0f}s")

    # ── Save ──
    import soundfile as sf
    wav_path = "/opt/autodj-mixer/Hammam_Dreams.wav"
    sf.write(wav_path, out, SR, subtype='PCM_24')
    log.info(f"Saved: {wav_path}")

    import subprocess
    mp3_path = wav_path.replace(".wav", ".mp3")
    subprocess.run([
        "ffmpeg", "-y", "-i", wav_path,
        "-b:a", "320k", "-q:a", "0",
        "-write_id3v1", "1",
        "-metadata", "title=Hammam Dreams",
        "-metadata", "artist=Xenolith",
        "-metadata", "genre=Spa Ambient",
        mp3_path
    ], capture_output=True)
    size_mb = os.path.getsize(mp3_path) / 1024 / 1024
    log.info(f"MP3: {mp3_path} ({size_mb:.1f} MB)")

    wav_size = os.path.getsize(wav_path) / 1024 / 1024
    print(f"\n✅ Hammam Dreams rendered!")
    print(f"   WAV: {wav_path} ({wav_size:.0f} MB)")
    print(f"   MP3: {mp3_path} ({size_mb:.1f} MB)")
    print(f"   Duration: {DURATION_S//60}:{DURATION_S%60:02d}")
    print(f"   Peak: {np.abs(out).max():.3f}  RMS: {20*np.log10(rms+1e-10):.1f} dBFS")

    return wav_path, mp3_path


if __name__ == "__main__":
    render()
