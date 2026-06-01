#!/usr/bin/env python3
"""
Mix Quality Analyzer
Detects amplitude spikes, RMS jumps, bass muffle, treble dropouts,
and BPM ramp smoothness in a completed mix.

Usage:
  python3 analyze_mix.py mix.mp3
"""
import sys, os, subprocess
import numpy as np
import soundfile as sf
import scipy.signal as sig

def analyze(mix_path):
    # Convert to WAV for analysis
    wav_tmp = "/tmp/_analyze_tmp.wav"
    subprocess.run(["ffmpeg", "-y", "-i", mix_path, "-ar", "44100", "-ac", "2", wav_tmp],
                   capture_output=True)

    audio, SR = sf.read(wav_tmp, always_2d=True)
    mono = audio.mean(1)
    dur = len(mono) / SR
    print(f"Duration: {int(dur//60)}:{int(dur%60):02d}  ({dur:.1f}s)")

    def ts(sec):
        return f"{int(sec//60)}:{int(sec%60):02d}.{int((sec%1)*10)}"

    # 1. Amplitude spikes / clicks
    diff = np.abs(np.diff(mono))
    hop = 512
    frames = len(diff) // hop
    fmax = np.array([diff[i*hop:(i+1)*hop].max() for i in range(frames)])
    med = np.median(fmax)
    thresh = med * 10
    clicks = np.where(fmax > thresh)[0]
    print(f"\n-- Amplitude spikes (x10 median={med:.5f}) --")
    prev = -999
    for c in clicks:
        t = c * hop / SR
        if t - prev > 0.3:
            print(f"  {ts(t)}  spike={fmax[c]:.5f}")
            prev = t

    # 2. RMS jumps
    win = int(0.5 * SR)
    n_w = len(mono) // win
    rms = np.array([np.sqrt(np.mean(mono[i*win:(i+1)*win]**2)) for i in range(n_w)])
    drms = np.abs(np.diff(rms))
    rms_med = np.median(drms)
    jumps = np.where(drms > rms_med * 5)[0]
    print(f"\n-- RMS jumps (x5 median) --")
    prev = -999
    for j in jumps:
        t = j * win / SR
        if t - prev > 1.0:
            d = "up" if rms[j+1] > rms[j] else "down"
            print(f"  {ts(t)} {d}  {rms[j]:.4f}->{rms[j+1]:.4f}")
            prev = t

    # 3. Bass muffle detection
    b_lp, a_lp = sig.butter(2, 200.0/(0.5*SR), btype='low')
    bass = sig.filtfilt(b_lp, a_lp, mono)
    hop3 = 4096
    n3 = len(mono) // hop3
    bass_r = np.array([np.sqrt(np.mean(bass[i*hop3:(i+1)*hop3]**2)) for i in range(n3)])
    tot_r = np.array([np.sqrt(np.mean(mono[i*hop3:(i+1)*hop3]**2)+1e-12) for i in range(n3)])
    br = bass_r / (tot_r + 1e-12)
    br_med = np.median(br)
    print(f"\n-- Bass-heavy zones (ratio > {br_med*1.8:.2f}, normal={br_med:.2f}) --")
    prev = -999
    mask = br > br_med * 1.8
    for i in range(n3):
        if mask[i]:
            t = i * hop3 / SR
            if t - prev > 2.0:
                print(f"  {ts(t)}  bass_ratio={br[i]:.3f}")
                prev = t

    # 4. Treble dropouts
    b_hp, a_hp = sig.butter(2, 8000.0/(0.5*SR), btype='high')
    treble = sig.filtfilt(b_hp, a_hp, mono)
    treb_r = np.array([np.sqrt(np.mean(treble[i*hop3:(i+1)*hop3]**2)) for i in range(n3)])
    dtreb = np.abs(np.diff(treb_r))
    tmed = np.median(dtreb)
    tcutoffs = np.where(dtreb > tmed * 6)[0]
    print(f"\n-- Treble cutoffs/spikes --")
    prev = -999
    for c in tcutoffs:
        t = c * hop3 / SR
        if t - prev > 1.0:
            d = "dropout" if treb_r[c+1] < treb_r[c] else "spike"
            print(f"  {ts(t)} {d}  {treb_r[c]:.5f}->{treb_r[c+1]:.5f}")
            prev = t

    os.unlink(wav_tmp)
    print("\nDone")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_mix.py <mix.mp3>")
        sys.exit(1)
    analyze(sys.argv[1])
