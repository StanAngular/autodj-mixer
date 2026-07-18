#!/usr/bin/env python3
"""
melodic_house_synth.py -- Energetic melodic house generator
BPM: 124 | Key: Am | ~4 min
Structure: Intro -> Build -> Drop -> Breakdown -> Build -> Drop -> Outro
"""
import numpy as np, scipy.signal, soundfile as sf
import os, sys, tempfile, warnings
warnings.filterwarnings("ignore")

SR  = 44100
BPM = 124.0
SPB = int(SR * 60 / BPM)   # samples per beat
BAR = SPB * 4               # samples per bar (2 bars / sec roughly)
EIGHTH    = SPB // 2
SIXTEENTH = SPB // 4

OUT = "shared/rework/melodic_house_124.mp3"

# ── helpers ───────────────────────────────────────────────────────────────────

def t_arr(n):
    return np.arange(n, dtype=np.float64) / SR

def sine(freq, n, phase=0.0):
    return np.sin(2*np.pi*freq*t_arr(n) + phase).astype(np.float32)

def saw(freq, n):
    t = t_arr(n)
    return (2*((freq*t) % 1.0) - 1).astype(np.float32)

def noise(n):
    return np.random.randn(n).astype(np.float32)

def lp(a, cut, order=4):
    b, c = scipy.signal.butter(order, min(cut,SR/2-1)/(SR/2), 'low')
    return scipy.signal.filtfilt(b, c, a).astype(np.float32)

def hp(a, cut, order=2):
    b, c = scipy.signal.butter(order, max(cut,20)/(SR/2), 'high')
    return scipy.signal.filtfilt(b, c, a).astype(np.float32)

def env(n, atk, dec, sus, rel):
    e = np.zeros(n, np.float32)
    a1 = min(atk, n)
    d1 = min(a1+dec, n)
    r0 = max(0, n-rel)
    if a1 > 0:     e[:a1]   = np.linspace(0, 1,   a1)
    if d1 > a1:    e[a1:d1] = np.linspace(1, sus,  d1-a1)
    if r0 > d1:    e[d1:r0] = sus
    if n  > r0:    e[r0:]   = np.linspace(sus, 0, n-r0)
    return e

def stamp(buf, hit, pos):
    pos = int(pos)
    if pos < 0 or pos >= len(buf): return
    end = min(pos+len(hit), len(buf))
    buf[pos:end] += hit[:end-pos]

def apply_fx(audio, chain):
    from pedalboard import Pedalboard
    board = Pedalboard(chain)
    return board(audio[np.newaxis,:], SR)[0]

# ── drums ──────────────────────────────────────────────────────────────────────

def mk_kick():
    n = int(0.50*SR)
    t = t_arr(n)
    f = 50 + 160*np.exp(-t*20)                    # pitch sweep 210 -> 50 Hz
    ph = 2*np.pi * np.cumsum(f)/SR
    body = np.sin(ph).astype(np.float32)
    amp = np.exp(-t*5.5).astype(np.float32)
    click = noise(n) * np.exp(-t*280) * 0.06      # transient click
    k = (body*amp + click.astype(np.float32))
    k = lp(k, 5500); k = hp(k, 22)
    return (k / (np.abs(k).max()+1e-6)).astype(np.float32)

def mk_snare():
    n = int(0.22*SR)
    t = t_arr(n)
    body = sine(195, n) * 0.30 * np.exp(-t*38)
    nz   = lp(noise(n), 7500) * 0.70 * np.exp(-t*26)
    s = (body + nz) * env(n, 30, int(.04*SR), .15, int(.07*SR))
    return hp(s, 100)

def mk_hat_c():
    n = int(0.042*SR)
    t = t_arr(n)
    freqs = [4100, 5300, 7500, 9900, 12400]
    h = sum(np.sign(sine(f,n)) for f in freqs).astype(np.float32)
    h = lp(h, 16000); h = hp(h, 4600)
    return (h * np.exp(-t*130) / len(freqs)).astype(np.float32)

def mk_hat_o():
    n = int(0.20*SR)
    t = t_arr(n)
    freqs = [4100, 5300, 7500, 9900, 12400]
    h = sum(np.sign(sine(f,n)) for f in freqs).astype(np.float32)
    h = lp(h, 17000); h = hp(h, 4600)
    return (h * np.exp(-t*18) / len(freqs)).astype(np.float32)

def mk_clap():
    n = int(0.15*SR)
    t = t_arr(n)
    out = np.zeros(n, np.float32)
    for d_ms in [0, 7, 15]:
        d = int(d_ms*SR/1000)
        bn = min(n-d, int(.038*SR))
        if bn > 0:
            b = lp(noise(bn), 5500) * np.exp(-np.arange(bn, dtype=np.float32)/SR*68)
            out[d:d+bn] += b
    return lp(hp(out * np.exp(-t*18), 260), 8500)

# ── synth ─────────────────────────────────────────────────────────────────────

def supersaw(freq, n, voices=7, det=14):
    out = np.zeros(n, np.float32)
    mid = voices // 2
    for i in range(voices):
        ct = (i-mid) / max(mid,1) * det
        out += saw(freq * 2**(ct/1200), n)
    return out / voices

def pad_note(freq, n, lp_cut=1800):
    body = supersaw(freq, n, voices=5, det=11)
    body = lp(body, lp_cut)
    return (body * env(n, int(.14*SR), int(.08*SR), .78, int(.28*SR))).astype(np.float32)

def pad_chord(freqs, n, lp_cut=1800):
    return sum(pad_note(f, n, lp_cut) for f in freqs).astype(np.float32) / len(freqs)

def sub_note(freq, n):
    body = sine(freq,n)*0.80 + sine(freq*2,n)*0.15 + sine(freq*3,n)*0.05
    out = (body * env(n, 80, int(.1*SR), .72, int(.14*SR))).astype(np.float32)
    return hp(lp(out, 240), 28)

def lead_note(freq, n):
    body = supersaw(freq, n, voices=3, det=7)
    body = lp(body, 4800)
    return (body * env(n, 40, int(.09*SR), .60, int(.11*SR))).astype(np.float32)

# ── progression ───────────────────────────────────────────────────────────────
# Am - F - C - G (each 1 bar, 4-bar loop)

CHORDS = [
    [220.00, 261.63, 329.63],   # Am: A3 C4 E4
    [174.61, 220.00, 261.63],   # F:  F3 A3 C4
    [130.81, 164.81, 196.00],   # C:  C3 E3 G3
    [196.00, 246.94, 293.66],   # G:  G3 B3 D4
]
ROOTS = [55.00, 43.65, 65.41, 49.00]  # A1 F1 C2 G1 (sub bass)

# 16th note arp sequences (16 notes per bar)
ARP = [
    [440.0,523.2,659.3,784.0, 659.3,523.2,440.0,392.0,
     440.0,523.2,659.3,880.0, 659.3,523.2,440.0,392.0],  # Am
    [349.2,440.0,523.2,659.3, 523.2,440.0,349.2,329.6,
     349.2,440.0,523.2,698.5, 523.2,440.0,349.2,329.6],  # F
    [261.6,329.6,392.0,523.2, 392.0,329.6,261.6,246.9,
     261.6,329.6,392.0,523.2, 392.0,329.6,261.6,246.9],  # C
    [196.0,246.9,293.7,392.0, 293.7,246.9,196.0,174.6,
     196.0,246.9,293.7,392.0, 293.7,246.9,196.0,174.6],  # G
]

# ── section renderers ─────────────────────────────────────────────────────────

def render_drums(bars, kick=True, snare=True, roll=False):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    K = mk_kick(); S = mk_snare()
    HC = mk_hat_c(); HO = mk_hat_o(); CL = mk_clap()

    for bar in range(bars):
        bs = bar * BAR
        for beat in range(4):
            bp = bs + beat*SPB
            for s16 in range(4):                # closed hat every 16th
                stamp(buf, HC*0.55, bp + s16*SIXTEENTH)
            stamp(buf, HO*0.70, bp + EIGHTH)    # open hat offbeat
            if kick  and beat in (0,2): stamp(buf, K,  bp)
            if snare and beat in (1,3):
                stamp(buf, S*0.90, bp)
                stamp(buf, CL*0.65, bp)

    if roll:
        last = (bars-1)*BAR
        s32 = SIXTEENTH // 2
        for i in range(16):
            vol = 0.35 + 0.65*i/15
            stamp(buf, S*vol, last + BAR//2 + i*s32)

    return buf

def render_bass(bars):
    n = bars * BAR
    buf = np.zeros(n, np.float32)
    for bar in range(bars):
        ci = bar % 4
        root = ROOTS[ci]
        stamp(buf, sub_note(root, BAR),      bar*BAR)
        stamp(buf, sub_note(root*1.5, SPB),  bar*BAR + SPB*2)
    return buf

def render_pads(bars, lp_cut=1800):
    n = bars * BAR
    buf = np.zeros(n, np.float32)
    for bar in range(bars):
        ci = bar % 4
        ln = min(BAR + int(.18*SR), n - bar*BAR)
        if ln > 0:
            stamp(buf, pad_chord(CHORDS[ci], ln, lp_cut), bar*BAR)
    return buf

def render_lead(bars):
    n = bars * BAR
    buf = np.zeros(n, np.float32)
    dur = int(SIXTEENTH * 0.82)
    for bar in range(bars):
        ci = bar % 4
        for i, freq in enumerate(ARP[ci]):
            stamp(buf, lead_note(freq, dur), bar*BAR + i*SIXTEENTH)
    return buf

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    from pedalboard import Reverb, Chorus, Compressor, Gain, Delay

    os.makedirs("shared/rework", exist_ok=True)
    np.random.seed(42)

    print(f"BPM={BPM} | BAR={BAR/SR:.2f}s | SR={SR}")

    # Layout (bars): Intro(8) Build1(16) Drop1(32) BD(16) Build2(8) Drop2(32) Outro(8) = 120 bars
    SECTIONS = {
        "intro":   (0,   8),
        "build1":  (8,  16),
        "drop1":   (24, 32),
        "break":   (56, 16),
        "build2":  (72,  8),
        "drop2":   (80, 32),
        "outro":   (112, 8),
    }
    TOTAL = 120
    N = TOTAL * BAR
    print(f"Total: {TOTAL} bars = {N/SR:.0f}s\n")

    mix = np.zeros(N, np.float32)

    # ── INTRO: hats + bass only ───────────────────────────────────────────────
    print("INTRO (8 bars) ...")
    s, nb = SECTIONS["intro"]
    d = render_drums(nb, kick=True, snare=False)
    b = render_bass(nb)
    dfx = apply_fx(d, [Compressor(-12,3,5,80), Gain(0.5)])
    bfx = apply_fx(b, [Compressor(-10,4,8,120)])
    mix[s*BAR:(s+nb)*BAR] += dfx*0.52 + bfx*0.58

    # ── BUILD 1: + pads with rising LP filter ─────────────────────────────────
    print("BUILD 1 (16 bars) ...")
    s, nb = SECTIONS["build1"]
    d  = render_drums(nb, kick=True, snare=False)
    b  = render_bass(nb)
    p0 = render_pads(nb, lp_cut=500)
    p1 = render_pads(nb, lp_cut=2000)
    fade = np.linspace(0, 1, nb*BAR, dtype=np.float32)
    p  = p0*(1-fade) + p1*fade

    dfx = apply_fx(d, [Compressor(-12,3,5,80), Gain(0.5)])
    bfx = apply_fx(b, [Compressor(-10,4,8,120)])
    pfx = apply_fx(p, [Chorus(0.8,0.3,mix=0.42), Reverb(0.50,0.6,wet_level=0.40,dry_level=0.60)])

    mix[s*BAR:(s+nb)*BAR] += dfx*0.52 + bfx*0.55 + pfx*0.40

    # ── DROP 1: full beat ──────────────────────────────────────────────────────
    print("DROP 1 (32 bars) ...")
    s, nb = SECTIONS["drop1"]
    d = render_drums(nb, kick=True, snare=True)
    b = render_bass(nb)
    p = render_pads(nb, lp_cut=2200)
    l = render_lead(nb)

    dfx = apply_fx(d, [Compressor(-10,3.5,4,80), Gain(2)])
    bfx = apply_fx(b, [Compressor(-8, 4.0,6,100)])
    pfx = apply_fx(p, [Chorus(0.7,0.25,mix=0.35), Reverb(0.38,0.55,wet_level=0.28,dry_level=0.72),
                        Compressor(-14,2.5,20,200)])
    lfx = apply_fx(l, [Delay(delay_seconds=EIGHTH/SR, feedback=0.22, mix=0.25),
                        Reverb(0.25,0.5,wet_level=0.18,dry_level=0.82)])

    mix[s*BAR:(s+nb)*BAR] += dfx*0.58 + bfx*0.62 + pfx*0.40 + lfx*0.48

    # ── BREAKDOWN: dreamy, no kick/snare ──────────────────────────────────────
    print("BREAKDOWN (16 bars) ...")
    s, nb = SECTIONS["break"]
    p = render_pads(nb, lp_cut=1100)
    b = render_bass(nb)
    l = render_lead(nb)

    pfx = apply_fx(p, [Chorus(1.0,0.5,mix=0.60), Reverb(0.80,0.85,wet_level=0.70,dry_level=0.30)])
    bfx = apply_fx(b*0.35, [Reverb(0.55,0.7,wet_level=0.30,dry_level=0.70)])
    lfx = apply_fx(l, [Reverb(0.65,0.75,wet_level=0.55,dry_level=0.45),
                        Delay(delay_seconds=EIGHTH/SR, feedback=0.38, mix=0.32)])

    mix[s*BAR:(s+nb)*BAR] += pfx*0.52 + bfx*0.38 + lfx*0.40

    # ── BUILD 2: snare roll + filter rise ─────────────────────────────────────
    print("BUILD 2 (8 bars) ...")
    s, nb = SECTIONS["build2"]
    d  = render_drums(nb, kick=False, snare=True, roll=True)
    p0 = render_pads(nb, lp_cut=350)
    p1 = render_pads(nb, lp_cut=2800)
    fade = np.linspace(0, 1, nb*BAR, dtype=np.float32)
    p  = p0*(1-fade) + p1*fade

    dfx = apply_fx(d, [Compressor(-12,3,5,80)])
    pfx = apply_fx(p, [Reverb(0.5,0.65,wet_level=0.42,dry_level=0.58)])

    mix[s*BAR:(s+nb)*BAR] += dfx*0.52 + pfx*0.48

    # ── DROP 2: louder, more energy ────────────────────────────────────────────
    print("DROP 2 (32 bars) ...")
    s, nb = SECTIONS["drop2"]
    d = render_drums(nb, kick=True, snare=True)
    b = render_bass(nb)
    p = render_pads(nb, lp_cut=2500)
    l = render_lead(nb)

    dfx = apply_fx(d, [Compressor(-9,4,3,70), Gain(2.5)])
    bfx = apply_fx(b, [Compressor(-7,4.5,5,100)])
    pfx = apply_fx(p, [Chorus(0.6,0.3,mix=0.40), Reverb(0.35,0.5,wet_level=0.25,dry_level=0.75),
                        Compressor(-12,2.5,18,180)])
    lfx = apply_fx(l, [Delay(delay_seconds=EIGHTH/SR, feedback=0.28, mix=0.28),
                        Reverb(0.22,0.45,wet_level=0.15,dry_level=0.85)])

    mix[s*BAR:(s+nb)*BAR] += dfx*0.60 + bfx*0.64 + pfx*0.42 + lfx*0.50

    # ── OUTRO: fade out ────────────────────────────────────────────────────────
    print("OUTRO (8 bars) ...")
    s, nb = SECTIONS["outro"]
    d = render_drums(nb, kick=True, snare=True)
    p = render_pads(nb, lp_cut=2000)
    fade_out = np.linspace(1, 0, nb*BAR, dtype=np.float32)

    dfx = apply_fx(d, [Compressor(-10,3,4,80), Gain(2)])
    pfx = apply_fx(p, [Reverb(0.4,0.6,wet_level=0.35,dry_level=0.65)])

    mix[s*BAR:(s+nb)*BAR] += (dfx*0.58 + pfx*0.45) * fade_out

    # ── MASTER ────────────────────────────────────────────────────────────────
    print("\nMaster bus...")
    mix = apply_fx(mix, [Compressor(-5,3.0,3,100), Gain(1.5)])
    mix = np.tanh(mix * 0.85) / 0.85   # soft clip
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= (10**(-0.5/20)) / peak  # normalize to -0.5 dBFS

    # encode
    print("Encoding 320kbps MP3...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    sf.write(tmp, mix, SR, subtype="PCM_24")
    os.system(f'ffmpeg -y -i "{tmp}" -b:a 320k -q:a 0 "{OUT}" 2>/dev/null')
    os.unlink(tmp)

    size = os.path.getsize(OUT)/1024/1024
    print(f"\n* Done: {OUT} ({size:.1f} MB, {N/SR:.0f}s)")

if __name__ == "__main__":
    main()
