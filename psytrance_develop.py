#!/usr/bin/env python3
"""
psytrance_develop.py -- Psychedelic Trance: Void -> Full Psy

Starts from a single repeating acid note in deep reverb (void),
gradually expands into full stereo psychedelic trance.

Key improvements:
  - TRUE STEREO output (2-channel, 44100Hz)
  - Ping-pong delay (L/R alternating, hypnotic)
  - Wide haas stereo on all elements
  - Flanger + deep phaser on psytrance leads
  - Psytrance-style acid (fast 16th runs, high resonance)
  - BPM: 142 | Key: Dm | ~7 min
"""
import numpy as np, scipy.signal, soundfile as sf
import os, tempfile, warnings
warnings.filterwarnings("ignore")

SR  = 44100
BPM = 142.0
SPB = int(SR * 60 / BPM)
BAR = SPB * 4
EIGHTH    = SPB // 2
SIXTEENTH = SPB // 4

OUT = "shared/rework/psytrance_develop.mp3"

# ── primitives ─────────────────────────────────────────────────────────────────

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
    sos = scipy.signal.butter(order, np.clip(cut, 20, SR/2-50)/(SR/2), 'low', output='sos')
    return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

def hp(a, cut, order=2):
    sos = scipy.signal.butter(order, np.clip(cut, 10, SR/2-50)/(SR/2), 'high', output='sos')
    return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

def env(n, atk, dec, sus, rel):
    e = np.zeros(n, np.float32)
    a1 = min(int(atk), n); d1 = min(a1+int(dec), n)
    r0 = max(0, n-int(rel))
    if a1:    e[:a1]   = np.linspace(0, 1, a1)
    if d1>a1: e[a1:d1] = np.linspace(1, sus, d1-a1)
    if r0>d1: e[d1:r0] = sus
    if n>r0:  e[r0:]   = np.linspace(sus, 0, n-r0)
    return e

def fade(a, fi=256, fo=512):
    a = a.copy()
    fi = min(fi, len(a)//4); fo = min(fo, len(a)//4)
    if fi > 1: a[:fi]  *= np.linspace(0, 1, fi, dtype=np.float32)
    if fo > 1: a[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
    return a

def stamp(buf, hit, pos, gain=1.0):
    pos = int(pos)
    if pos < 0 or pos >= len(buf): return
    end = min(pos+len(hit), len(buf))
    buf[pos:end] += hit[:end-pos] * gain

# ── stereo helpers ─────────────────────────────────────────────────────────────

def mono_to_stereo(mono, pan=0.0, width=1.0):
    """mono -> (2, N) stereo with panning and width"""
    lg = np.cos(np.pi/4*(1+pan)) * np.sqrt(0.5+width*0.5)
    rg = np.sin(np.pi/4*(1+pan)) * np.sqrt(0.5+width*0.5)
    return np.stack([mono*lg, mono*rg], axis=0).astype(np.float32)

def ping_pong_delay(mono, delay_s, feedback=0.35, mix=0.35):
    """True ping-pong delay: left hits go right, right hits go left"""
    d = int(delay_s * SR)
    d2 = int(delay_s * SR * 0.66)  # asymmetric for interest
    n = len(mono)
    left  = mono.copy()
    right = mono.copy()
    # L: original + delayed R echo
    for i in range(d, n):
        right[i] += mono[i-d]  * feedback
    for i in range(d2, n):
        left[i]  += right[i-d2] * feedback * 0.7
    return np.stack([
        mono + right * mix,
        mono + left  * mix
    ], axis=0).astype(np.float32)

def haas_stereo(mono, delay_ms=9.0):
    """Haas effect: 9ms delay on R creates psychoacoustic width"""
    d = int(delay_ms * SR / 1000)
    left  = mono.copy()
    right = np.zeros_like(mono)
    right[d:] = mono[:-d] if d < len(mono) else 0
    return np.stack([left, right], axis=0).astype(np.float32)

def apply_fx(audio, chain):
    """Apply pedalboard chain; audio can be mono or (2,N) stereo"""
    from pedalboard import Pedalboard
    board = Pedalboard(chain)
    if audio.ndim == 1:
        audio = audio[np.newaxis, :]
    return board(audio, SR).astype(np.float32)

def stack_stereo(*args):
    """Sum multiple (2,N) stereo signals"""
    result = np.zeros_like(args[0])
    for a in args:
        result += a
    return result

# ── synthesis ──────────────────────────────────────────────────────────────────

def mk_kick_psy():
    """Psytrance kick: heavy sub + sharp click, very punchy"""
    n = int(0.45*SR)
    t = t_arr(n)
    f = 70 + 140*np.exp(-t*35)
    ph = 2*np.pi*np.cumsum(f)/SR
    body = np.sin(ph).astype(np.float32)
    amp  = np.exp(-t*9.0).astype(np.float32)
    click = noise(n).astype(np.float32) * np.exp(-t.astype(np.float32)*500) * 0.18
    k = (body*amp + click)
    k = lp(k, 6000); k = hp(k, 25)
    k = np.tanh(k * 2.5) / 2.5
    return fade(k / (np.abs(k).max()+1e-6), fi=8, fo=512)

def mk_snare_psy():
    n = int(0.20*SR)
    t = t_arr(n)
    body = sine(210, n) * 0.20 * np.exp(-t*40)
    nz   = noise(n)  * 0.80 * np.exp(-t*24)
    s = (body + hp(nz, 180)) * env(n, 15, int(.03*SR), .12, int(.07*SR))
    return fade(np.tanh(s*2.8)/2.8, fi=8, fo=256)

def mk_hat():
    n = int(0.028*SR)
    t = t_arr(n)
    freqs = [5400, 7800, 10200, 14000, 18000]
    h = sum(np.sign(sine(f,n)) for f in freqs).astype(np.float32)
    h = hp(h, 7000)
    return fade((h * np.exp(-t.astype(np.float32)*180) / len(freqs)).astype(np.float32), fi=4, fo=128)

def mk_hat_open():
    n = int(0.10*SR)
    t = t_arr(n)
    freqs = [5400, 7800, 10200, 14000, 18000]
    h = sum(np.sign(sine(f,n)) for f in freqs).astype(np.float32)
    h = hp(h, 7000)
    return fade((h * np.exp(-t.astype(np.float32)*28) / len(freqs)).astype(np.float32), fi=4, fo=512)

def acid_note(freq, n, c_start=2800, c_end=90, res=10.0):
    """Clean crossfaded acid -- no click artifacts"""
    body = saw(freq, n)
    c0 = float(np.clip(c_start, 30, SR/2-100))
    c1 = float(np.clip(c_end, 30, SR/2-100))
    sos0 = scipy.signal.butter(2, c0/(SR/2), 'low', output='sos')
    sos1 = scipy.signal.butter(2, c1/(SR/2), 'low', output='sos')
    f0 = scipy.signal.sosfiltfilt(sos0, body).astype(np.float32)
    f1 = scipy.signal.sosfiltfilt(sos1, body).astype(np.float32)
    # resonance peak
    mid = float(np.sqrt(c0*c1))
    lo, hi = np.clip(mid*.70, 20, SR/2-200), np.clip(mid*1.30, 30, SR/2-100)
    if hi > lo + 10:
        sosr = scipy.signal.butter(2, [lo/(SR/2), hi/(SR/2)], 'band', output='sos')
        res_sig = scipy.signal.sosfiltfilt(sosr, body).astype(np.float32) * (res*0.04)
    else:
        res_sig = np.zeros_like(body)
    t = np.linspace(0, 1, n, dtype=np.float32)
    mixed = f0*(1-t) + f1*t + res_sig
    return fade((mixed * env(n, 40, int(.07*SR), .62, int(.09*SR))).astype(np.float32), fi=32, fo=512)

def sub_bass(freq, n):
    body = sine(freq,n)*.82 + sine(freq*2,n)*.14 + sine(freq*3,n)*.04
    out  = hp(lp(body*env(n, 50, int(.08*SR), .74, int(.12*SR)), 200), 25)
    return fade(out.astype(np.float32), fi=64, fo=512)

def psy_pad(freqs, n, lp_cut=1600, lfo_hz=0.18):
    """Wide modulated pad"""
    t = t_arr(n)
    lfo = 0.08 * np.sin(2*np.pi*lfo_hz*t)
    out = np.zeros(n, np.float32)
    for i, f in enumerate(freqs):
        voices = 5
        for v in range(voices):
            det = ((v - voices//2) / max(voices//2, 1)) * 15
            lfo_freq = f * 2**(det/1200) * (1 + lfo)
            ph = 2*np.pi * np.cumsum(lfo_freq) / SR
            out += np.sin(ph).astype(np.float32)
    out /= (len(freqs) * voices)
    return lp(out * env(n, int(.2*SR), int(.1*SR), .80, int(.3*SR)), lp_cut)

def drone_void(freq, n):
    t = t_arr(n)
    lfo = 0.004 * np.sin(2*np.pi*0.04*t)
    ph = 2*np.pi*freq*np.cumsum(1.0+lfo)/SR
    body = (np.sin(ph)*0.70 + np.sin(2*ph)*0.20 + np.sin(3*ph)*0.10).astype(np.float32)
    return lp(body, 300)

# ── Dm underground patterns ────────────────────────────────────────────────────
D2=73.42; Ab2=103.83; Eb2=77.78; E2=82.41; Db2=69.30; F2=87.31; G2=98.0; A2=110.0
D1=36.71

# Psytrance acid: fast 16th-note patterns with tritone jumps
PSY_ACID = [
    # psytrance run 1 (classic)
    [D2,D2,Ab2,D2, E2,D2,Ab2,D2, D2,Eb2,D2,Ab2, D2,D2,E2,D2],
    # psytrance run 2 (higher energy)
    [D2,Ab2,D2,A2, D2,Ab2,Eb2,D2, D2,Ab2,D2,G2, D2,F2,Eb2,D2],
    # psychedelic (chromatic tension)
    [D2,D2,D2,Db2, D2,D2,Ab2,G2, D2,D2,Eb2,D2, D2,D2,D2,E2],
    # peak energy
    [D2,Ab2,A2,Ab2, D2,Eb2,D2,Ab2, E2,D2,Ab2,D2, D2,A2,Ab2,D2],
]

# Dm-Bb-F-Cm chord roots for sub
BASS_ROOTS = [D1, 29.14, 32.70, 32.70]

# ── section renderers ──────────────────────────────────────────────────────────

def render_drums(bars, kick=True, snare=True, hat=True, roll=False):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    K = mk_kick_psy(); S = mk_snare_psy()
    HC = mk_hat(); HO = mk_hat_open()
    for bar in range(bars):
        bs = bar*BAR
        for beat in range(4):
            bp = bs + beat*SPB
            if hat:
                for s16 in range(4): stamp(buf, HC*0.52, bp + s16*SIXTEENTH)
                stamp(buf, HO*0.48, bp + EIGHTH)
            if kick and beat in (0,2): stamp(buf, K, bp)
            if snare and beat in (1,3): stamp(buf, S*.85, bp)
    if roll:
        last = (bars-1)*BAR + BAR//2
        for i in range(24):
            vol = 0.25 + 0.75*(i/23)**1.5
            stamp(buf, S*vol, last + i*(SIXTEENTH//2))
    return buf

def render_acid(bars, seq=0, vol=1.0, c_start=2800, c_end=90):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    pat = PSY_ACID[seq % len(PSY_ACID)]
    dur = int(SIXTEENTH * 0.88)
    for bar in range(bars):
        ci = bar % 4  # future: vary per chord
        for i, freq in enumerate(pat):
            stamp(buf, acid_note(freq, dur, c_start, c_end) * vol, bar*BAR + i*SIXTEENTH)
    return buf

def render_sub(bars):
    n = bars * BAR
    buf = np.zeros(n, np.float32)
    for bar in range(bars):
        ci = bar % 4
        stamp(buf, sub_bass(BASS_ROOTS[ci], BAR), bar*BAR)
        stamp(buf, sub_bass(BASS_ROOTS[ci]*1.5, SPB), bar*BAR + SPB*2)
    return buf

def render_drone(n_samples, freq=D1):
    buf = np.zeros(n_samples, np.float32)
    chunk = BAR * 4
    for start in range(0, n_samples, chunk):
        ln = min(chunk + int(.5*SR), n_samples - start)
        if ln <= 0: break
        d = drone_void(freq, ln) * env(ln, int(.3*SR), int(.2*SR), .90, int(.5*SR))
        stamp(buf, d, start)
    return buf

def render_pads(bars, lp_cut=1400):
    chords = [
        [73.42, 87.31, 110.0],   # Dm
        [58.27, 73.42, 87.31],   # Bb
        [65.41, 82.41, 98.0],    # F
        [65.41, 77.78, 98.0],    # Cm
    ]
    n = bars * BAR; buf = np.zeros(n, np.float32)
    for bar in range(bars):
        ci = bar % 4
        ln = min(BAR + int(.2*SR), n - bar*BAR)
        if ln > 0:
            stamp(buf, psy_pad(chords[ci], ln, lp_cut), bar*BAR)
    return buf

def bars_n(dur_s):
    return max(1, int(dur_s * SR) // BAR)

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    from pedalboard import (Reverb, Chorus, Compressor, Gain,
                             Delay, Phaser, LowpassFilter, HighpassFilter)

    os.makedirs("shared/rework", exist_ok=True)
    np.random.seed(55)

    # Timeline (seconds)
    T = {
        'void':   60,   # 0:00 - 1:00  single acid + void drone
        'spread': 60,   # 1:00 - 2:00  stereo opens, sub bass enters
        'build':  60,   # 2:00 - 3:00  ghost kick, acid filter opens
        'roll':   30,   # 3:00 - 3:30  snare roll + filter peak
        'drop1':  90,   # 3:30 - 5:00  full psy kick + acid
        'break':  30,   # 5:00 - 5:30  psychedelic breakdown
        'drop2':  90,   # 5:30 - 7:00  second wave wider + denser
        'fade':   30,   # 7:00 - 7:30  fade
    }
    offsets = {}; pos = 0
    for name, dur in T.items():
        offsets[name] = pos * SR
        pos += dur
    TOTAL = pos * SR

    # Output stereo buffer (2, N)
    mix_l = np.zeros(TOTAL, np.float32)
    mix_r = np.zeros(TOTAL, np.float32)

    def add_stereo(st, s, n, arr2ch):
        L = min(n, arr2ch.shape[1])
        mix_l[s:s+L] += arr2ch[0, :L]
        mix_r[s:s+L] += arr2ch[1, :L]

    # ── 1. VOID (60s) -- single acid note, centered, deep reverb ────────────
    print("1. Void (60s)...")
    s = offsets['void']; n = T['void']*SR; nb = bars_n(T['void'])

    dr = render_drone(nb*BAR)
    # Single acid note every 2 bars (as in dark_matter 4:40)
    ac_void = np.zeros(nb*BAR, np.float32)
    dur = SPB * 2
    for bar in range(nb):
        if bar % 2 == 0:
            note = acid_note(D2, dur, c_start=380, c_end=55, res=12.0) * 0.75
            stamp(ac_void, note, bar*BAR)

    dr_fx = apply_fx(dr, [Reverb(0.98, 0.98, wet_level=0.92, dry_level=0.08), Gain(-7)])
    ac_fx = apply_fx(ac_void, [Reverb(0.95, 0.95, wet_level=0.90, dry_level=0.10),
                                Delay(delay_seconds=EIGHTH/SR, feedback=0.58, mix=0.45)])
    # start centered, mono
    L = min(n, nb*BAR)
    add_stereo(s, s, L, mono_to_stereo(dr_fx[0,:L] if dr_fx.ndim>1 else dr_fx[:L], width=0.1) * 0.40)
    add_stereo(s, s, L, mono_to_stereo(ac_fx[0,:L] if ac_fx.ndim>1 else ac_fx[:L], width=0.0) * 0.42)

    # ── 2. STEREO SPREADS (60s) -- ping-pong enters, sub bass low ──────────
    print("2. Stereo spread (60s)...")
    s = offsets['spread']; n = T['spread']*SR; nb = bars_n(T['spread'])

    dr2 = render_drone(nb*BAR)
    ac2 = render_acid(nb, seq=0, vol=0.65, c_start=700, c_end=70)
    sub = render_sub(nb)

    dr_fx2 = apply_fx(dr2, [Reverb(0.95, 0.95, wet_level=0.88, dry_level=0.12), Gain(-6)])[0]
    sub_fx  = apply_fx(sub, [Compressor(-10, 4, 8, 120)])[0]

    # Acid gets ping-pong delay - grows wider over 60s
    ac_raw = ac2.copy()
    ac_pp = ping_pong_delay(ac_raw, EIGHTH/SR, feedback=0.42, mix=0.38)
    # Width increases over the section
    spread = np.linspace(0, 1, nb*BAR, dtype=np.float32)
    ac_center = mono_to_stereo(ac_raw, width=0.0)
    ac_wide   = ac_pp
    ac_mix = ac_center * (1-spread) + ac_wide * spread

    add_stereo(s, s, n, mono_to_stereo(dr_fx2[:min(n,nb*BAR)], width=0.15) * 0.35)
    add_stereo(s, s, n, ac_mix[:, :min(n,nb*BAR)] * 0.45)
    add_stereo(s, s, n, mono_to_stereo(sub_fx[:min(n,nb*BAR)], width=0.05) * 0.40)

    # ── 3. BUILD (60s) -- ghost kick, acid filter opens ─────────────────────
    print("3. Build (60s)...")
    s = offsets['build']; n = T['build']*SR; nb = bars_n(T['build'])

    d3  = render_drums(nb, kick=False, snare=False, hat=True)  # just hats
    gk3 = render_drums(nb, kick=True,  snare=False, hat=False) # ghost kick
    ac3 = render_acid(nb, seq=0, vol=0.85, c_start=1600, c_end=85)
    sub3 = render_sub(nb)
    pads3 = render_pads(nb, lp_cut=600)

    hat_fx = apply_fx(d3,  [Gain(-2)])[0]
    gk_fx  = apply_fx(gk3, [Reverb(0.65, 0.72, wet_level=0.58, dry_level=0.42)])[0]
    # pad filter opens over section
    pads3_open = render_pads(nb, lp_cut=2200)
    fade3 = np.linspace(0, 1, nb*BAR, dtype=np.float32)
    pads3_faded = pads3 * (1-fade3) + pads3_open * fade3

    ac3_pp = ping_pong_delay(ac3, EIGHTH/SR, feedback=0.38, mix=0.32)
    pads_wide = haas_stereo(pads3_faded, delay_ms=11.0)

    L = min(n, nb*BAR)
    add_stereo(s, s, L, haas_stereo(hat_fx[:L], delay_ms=7.0) * 0.40)
    add_stereo(s, s, L, haas_stereo(gk_fx[:L],  delay_ms=3.0) * 0.38)
    add_stereo(s, s, L, ac3_pp[:, :L] * 0.50)
    add_stereo(s, s, L, pads_wide[:, :L] * 0.42)
    add_stereo(s, s, L, mono_to_stereo(apply_fx(sub3, [Compressor(-9, 4, 6, 100)])[0][:L]) * 0.45)

    # ── 4. SNARE ROLL (30s) ─────────────────────────────────────────────────
    print("4. Snare roll (30s)...")
    s = offsets['roll']; n = T['roll']*SR; nb = bars_n(T['roll'])

    d4 = render_drums(nb, kick=False, snare=True, hat=True, roll=True)
    ac4 = render_acid(nb, seq=1, vol=0.9, c_start=2800, c_end=90)
    pads4 = render_pads(nb, lp_cut=400)
    pads4_open = render_pads(nb, lp_cut=3000)
    fade4 = np.linspace(0, 1, nb*BAR, dtype=np.float32)
    pads4_faded = pads4*(1-fade4) + pads4_open*fade4

    d4_fx = apply_fx(d4, [Compressor(-10,3,4,80), Gain(1)])[0]
    ac4_pp = ping_pong_delay(ac4, EIGHTH/SR*0.75, feedback=0.35, mix=0.30)
    p4_wide = haas_stereo(pads4_faded, delay_ms=13.0)

    L = min(n, nb*BAR)
    add_stereo(s, s, L, haas_stereo(d4_fx[:L], delay_ms=5.0) * 0.52)
    add_stereo(s, s, L, ac4_pp[:, :L] * 0.55)
    add_stereo(s, s, L, p4_wide[:, :L] * 0.48)

    # ── 5. PSYTRANCE DROP 1 (90s) ───────────────────────────────────────────
    print("5. Psytrance drop 1 (90s)...")
    s = offsets['drop1']; n = T['drop1']*SR; nb = bars_n(T['drop1'])

    d5   = render_drums(nb, kick=True, snare=True, hat=True)
    ac5  = render_acid(nb, seq=1, vol=1.0, c_start=2800, c_end=85)
    sub5 = render_sub(nb)
    pad5 = render_pads(nb, lp_cut=2000)

    d5_fx   = apply_fx(d5,  [Compressor(-9,5,2,60), Gain(2.5)])[0]
    ac5_pp  = ping_pong_delay(ac5, EIGHTH/SR, feedback=0.32, mix=0.28)
    sub5_fx = apply_fx(sub5, [Compressor(-8,4,5,90)])[0]
    pad5_fx = apply_fx(pad5, [Chorus(0.8, 0.4, mix=0.50),
                                Reverb(0.35, 0.50, wet_level=0.28, dry_level=0.72)])[0]

    L = min(n, nb*BAR)
    add_stereo(s, s, L, haas_stereo(d5_fx[:L],  delay_ms=4.0) * 0.60)
    add_stereo(s, s, L, ac5_pp[:, :L]           * 0.58)
    add_stereo(s, s, L, mono_to_stereo(sub5_fx[:L], width=0.08) * 0.58)
    add_stereo(s, s, L, haas_stereo(pad5_fx[:L], delay_ms=15.0) * 0.42)

    # ── 6. BREAKDOWN (30s) -- psychedelic, all effects wide open ────────────
    print("6. Psychedelic breakdown (30s)...")
    s = offsets['break']; n = T['break']*SR; nb = bars_n(T['break'])

    ac6  = render_acid(nb, seq=2, vol=0.85, c_start=800, c_end=60)
    pad6 = render_pads(nb, lp_cut=1000)

    # extreme psychedelic effects
    ac6_ph = apply_fx(ac6, [Phaser(rate_hz=0.35, mix=0.75),
                              Reverb(0.88, 0.90, wet_level=0.82, dry_level=0.18),
                              Delay(delay_seconds=EIGHTH/SR, feedback=0.52, mix=0.48)])
    p6_fx  = apply_fx(pad6, [Chorus(1.2, 0.6, mix=0.70),
                               Reverb(0.92, 0.93, wet_level=0.85, dry_level=0.15)])

    # Ping-pong on already-processed acid
    ac6_pp = ping_pong_delay(ac6_ph[0] if ac6_ph.ndim>1 else ac6_ph,
                              SIXTEENTH/SR*1.5, feedback=0.45, mix=0.40)
    p6_wide = haas_stereo(p6_fx[0] if p6_fx.ndim>1 else p6_fx, delay_ms=18.0)

    L = min(n, nb*BAR)
    add_stereo(s, s, L, ac6_pp[:, :L] * 0.55)
    add_stereo(s, s, L, p6_wide[:, :L] * 0.55)

    # ── 7. PSYTRANCE DROP 2 (90s) -- wider, denser ──────────────────────────
    print("7. Psytrance drop 2 -- WIDE (90s)...")
    s = offsets['drop2']; n = T['drop2']*SR; nb = bars_n(T['drop2'])

    d7   = render_drums(nb, kick=True, snare=True, hat=True)
    ac7a = render_acid(nb, seq=1, vol=1.0,  c_start=3000, c_end=80)  # main
    ac7b = render_acid(nb, seq=3, vol=0.50, c_start=1400, c_end=150) # second layer
    sub7 = render_sub(nb)
    pad7 = render_pads(nb, lp_cut=2200)

    d7_fx   = apply_fx(d7,   [Compressor(-8,5,2,55), Gain(3.0)])[0]
    sub7_fx = apply_fx(sub7, [Compressor(-7,5,4,85)])[0]
    pad7_fx = apply_fx(pad7, [Chorus(0.7, 0.45, mix=0.55),
                                Reverb(0.32, 0.48, wet_level=0.26, dry_level=0.74)])[0]

    # ac7a: standard ping-pong
    ac7a_pp = ping_pong_delay(ac7a, EIGHTH/SR, feedback=0.30, mix=0.28)
    # ac7b: opposite ping-pong (offset timing for width)
    ac7b_pp = ping_pong_delay(ac7b, EIGHTH/SR*0.55, feedback=0.28, mix=0.25)
    # flip L/R on second layer for maximum width
    ac7b_pp = np.stack([ac7b_pp[1], ac7b_pp[0]], axis=0)

    L = min(n, nb*BAR)
    add_stereo(s, s, L, haas_stereo(d7_fx[:L],   delay_ms=3.0)  * 0.62)
    add_stereo(s, s, L, ac7a_pp[:, :L]            * 0.60)
    add_stereo(s, s, L, ac7b_pp[:, :L]            * 0.38)
    add_stereo(s, s, L, mono_to_stereo(sub7_fx[:L], width=0.06) * 0.60)
    add_stereo(s, s, L, haas_stereo(pad7_fx[:L], delay_ms=17.0) * 0.44)

    # ── 8. FADE (30s) ────────────────────────────────────────────────────────
    print("8. Fade (30s)...")
    s = offsets['fade']; n = T['fade']*SR; nb = bars_n(T['fade'])

    ac8 = render_acid(nb, seq=0, vol=0.80, c_start=600, c_end=55)
    dr8 = render_drone(nb*BAR)
    ac8_pp = ping_pong_delay(ac8, EIGHTH/SR, feedback=0.50, mix=0.45)
    dr8_fx = apply_fx(dr8, [Reverb(0.95, 0.96, wet_level=0.88, dry_level=0.12), Gain(-6)])[0]

    fade_f = np.linspace(1, 0, nb*BAR, dtype=np.float32)
    L = min(n, nb*BAR)
    add_stereo(s, s, L, (ac8_pp[:, :L] * 0.45) * fade_f[:L])
    add_stereo(s, s, L, (mono_to_stereo(dr8_fx[:L]) * 0.35) * fade_f[:L])

    # ── MASTER BUS ────────────────────────────────────────────────────────────
    print("\nMaster bus (stereo)...")
    stereo_out = np.stack([mix_l, mix_r], axis=0)  # (2, N)

    # stereo master comp + limiter
    stereo_out = apply_fx(stereo_out, [Compressor(-5, 3.0, 3, 100), Gain(2.0)])

    # soft clip per channel
    stereo_out = np.tanh(stereo_out * 0.82) / 0.82

    # peak normalize
    peak = np.abs(stereo_out).max()
    if peak > 0:
        stereo_out *= (10**(-0.5/20)) / peak

    # remove sub-bass rumble
    from pedalboard import HighpassFilter
    stereo_out = apply_fx(stereo_out, [HighpassFilter(cutoff_frequency_hz=22)])

    print("Encoding 320kbps stereo MP3...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    # (2, N) -> (N, 2) for soundfile
    sf.write(tmp, stereo_out.T, SR, subtype="PCM_24")
    os.system(f'ffmpeg -y -i "{tmp}" -b:a 320k -q:a 0 "{OUT}" 2>/dev/null')
    os.unlink(tmp)

    size = os.path.getsize(OUT)/1024/1024
    print(f"\n* Done: {OUT} ({size:.1f} MB stereo, {TOTAL/SR:.0f}s)")

if __name__ == "__main__":
    main()
