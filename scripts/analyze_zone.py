#!/usr/bin/env python3
"""
Targeted zone analyzer for investigating specific time ranges in a mix.
Provides BPM trace, RMS energy, and spectral centroid at high resolution.

Usage:
  python3 analyze_zone.py mix.mp3 22:00 23:10
"""
import sys, os, subprocess
import numpy as np
import soundfile as sf
import librosa

def ts(sec):
    return f"{int(sec//60)}:{int(sec%60):02d}.{int((sec%1)*10)}"

def parse_time(s):
    parts = s.split(':')
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(s)

def analyze_zone(mix_path, start_str, end_str):
    start_sec = parse_time(start_str)
    end_sec = parse_time(end_str)
    duration = end_sec - start_sec

    wav_tmp = "/tmp/_zone_tmp.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", mix_path,
        "-ar", "44100", "-ac", "2",
        "-ss", str(start_sec), "-t", str(duration),
        wav_tmp
    ], capture_output=True)

    audio, SR = sf.read(wav_tmp, always_2d=True)
    mono = audio.mean(1).astype(np.float32)

    print(f"=== Zone analysis: {start_str} - {end_str} ===\n")

    # 1. BPM trace (4s windows, 0.5s hop)
    print("--- LOCAL BPM TRACE ---")
    for offset in np.arange(0, duration, 0.5):
        s = int(offset * SR)
        e = int((offset + 4.0) * SR)
        if e > len(mono): break
        seg = mono[s:e]
        onset_env = librosa.onset.onset_strength(y=seg, sr=SR, hop_length=256)
        tempo = librosa.beat.tempo(onset_envelope=onset_env, sr=SR, hop_length=256)
        bpm = tempo[0] if len(tempo) else 0
        t_abs = start_sec + offset
        print(f"  {ts(t_abs)}  BPM={bpm:5.1f}")

    # 2. RMS energy (100ms windows)
    print(f"\n--- RMS ENERGY ---")
    win = int(0.1 * SR)
    for offset in np.arange(0, duration, 0.1):
        s = int(offset * SR)
        e = s + win
        if e > len(mono): break
        rms = np.sqrt(np.mean(mono[s:e]**2))
        t_abs = start_sec + offset
        if rms < 0.02:
            print(f"  {ts(t_abs)}  {rms:.4f}  LOW")
        else:
            print(f"  {ts(t_abs)}  {rms:.4f}")

    # 3. Spectral centroid (0.5s windows)
    print(f"\n--- SPECTRAL CENTROID ---")
    for offset in np.arange(0, duration, 0.5):
        s = int(offset * SR)
        e = int((offset + 0.5) * SR)
        if e > len(mono): break
        seg = mono[s:e]
        sc = librosa.feature.spectral_centroid(y=seg, sr=SR)[0].mean()
        t_abs = start_sec + offset
        print(f"  {ts(t_abs)}  centroid={sc:6.0f}Hz")

    os.unlink(wav_tmp)
    print("\nDone")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 analyze_zone.py <mix.mp3> <start_time> <end_time>")
        print("  Example: python3 analyze_zone.py mix.mp3 22:00 23:10")
        sys.exit(1)
    analyze_zone(sys.argv[1], sys.argv[2], sys.argv[3])
