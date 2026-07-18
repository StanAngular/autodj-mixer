#!/usr/bin/env python3
"""
dark_psychedelic_techno.py -- Dark Psychedelic Ambient -> Hard Techno
Gradual build: drone → psychedelic acid → full 132 BPM techno

Structure:
  0:00  Dark ambient drone (no beat)
  1:30  Ghost kicks + acid bass enters
  2:30  Psychedelic lead + tension build
  3:00  Hard techno drop 132 BPM
  4:30  Breakdown + acid
  5:00  Second drop (harder)
  6:00  Outro fade

Key: Dm | BPM: 132 | ~6 min
"""
import numpy as np, scipy.signal, soundfile as sf
import os, tempfile, warnings
warnings.filterwarnings("ignore")

SR  = 44100
BPM = 132.0
SPB = int(SR * 60 / BPM)   # samples per beat
BAR = SPB * 4               # samples per bar
EIGHTH    = SPB // 2
SIXTEENTH = SPB // 4

OUT = "shared/rework/dark_psychedelic_techno.mp3"

# ── primitives ────────────────────────────────────────────────────────────────

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
    cut = float(np.clip(cut, 30, SR/2 - 100))
    b, c = scipy.signal.butter(order, cut/(SR/2), 'low')
    return scipy.signal.filtfilt(b, c, a).astype(np.float32)

def hp(a, cut, order=2):
    cut = float(np.clip(cut, 10, SR/2 - 100))
    b, c = scipy.signal.butter(order, cut/(SR/2), 'high')
    return scipy.signal.filtfilt(b, c, a).astype(np.float32)

def bp(a, lo, hi, order=2):
    lo = float(np.clip(lo, 20, SR/2 - 200))
    hi = float(np.clip(hi, lo + 50, SR/2 - 100))
    b, c = scipy.signal.butter(order, [lo/(SR/2), hi/(SR/2)], 'band')
    return scipy.signal.filtfilt(b, c, a).astype(np.float32)

def env(n, atk, dec, sus, rel):
    e = np.zeros(n, np.float32)
    a1 = min(int(atk), n)
    d1 = min(a1+int(dec), n)
    r0 = max(0, n-int(rel))
    if a1:         e[:a1]   = np.linspace(0, 1, a1)
    if d1 > a1:    e[a1:d1] = np.linspace(1, sus, d1-a1)
    if r0 > d1:    e[d1:r0] = sus
    if n  > r0:    e[r0:]   = np.linspace(sus, 0, n-r0)
    return e

def stamp(buf, hit, pos, gain=1.0):
    pos = int(pos)
    if pos < 0 or pos >= len(buf): return
    end = min(pos+len(hit), len(buf))
    buf[pos:end] += hit[:end-pos] * gain

def apply_fx(audio, chain):
    from pedalboard import Pedalboard
    board = Pedalboard(chain)
    return board(audio[np.newaxis,:], SR)[0]

# ── drum synthesis ─────────────────────────────────────────────────────────────

def mk_kick_techno():
    """Hard techno kick: punchy, more attack, less tail"""
    n = int(0.48*SR)
    t = t_arr(n)
    f = 60 + 150*np.exp(-t*28)                     # fast pitch sweep
    ph = 2*np.pi*np.cumsum(f)/SR
    body = np.sin(ph).astype(np.float32)
    amp  = np.exp(-t*8.0).astype(np.float32)
    click = noise(n) * np.exp(-t*400) * 0.12
    k = (body*amp + click.astype(np.float32))
    k = lp(k, 6000); k = hp(k, 28)
    k = np.tanh(k * 1.8) / 1.8                     # light saturation
    return (k / (np.abs(k).max()+1e-6)).astype(np.float32)

def mk_kick_ghost():
    """Quiet, reverby ghost kick for ambient intro"""
    k = mk_kick_techno()
    return k * 0.25

def mk_snare_industrial():
    """Industrial snare: more white noise, metallic"""
    n = int(0.25*SR)
    t = t_arr(n)
    body = sine(210, n) * 0.20 * np.exp(-t*45)
    nz   = noise(n) * 0.80 * np.exp(-t*22)
    nz   = hp(nz, 180)
    s = (body + nz) * env(n, 20, int(.03*SR), .12, int(.08*SR))
    s = np.tanh(s * 2.5) / 2.5                    # saturation → gritty
    return s

def mk_hat_techno():
    """Tight, bright techno hat"""
    n = int(0.035*SR)
    t = t_arr(n)
    freqs = [5000, 6800, 9000, 12000, 15000]
    h = sum(np.sign(sine(f, n)) for f in freqs).astype(np.float32)
    h = lp(h, 18000); h = hp(h, 5500)
    return (h * np.exp(-t*160) / len(freqs)).astype(np.float32)

def mk_hat_open_techno():
    n = int(0.12*SR)
    t = t_arr(n)
    freqs = [5000, 6800, 9000, 12000, 15000]
    h = sum(np.sign(sine(f, n)) for f in freqs).astype(np.float32)
    h = lp(h, 18000); h = hp(h, 5500)
    return (h * np.exp(-t*35) / len(freqs)).astype(np.float32)

def mk_clap_industrial():
    n = int(0.18*SR)
    t = t_arr(n)
    out = np.zeros(n, np.float32)
    for d_ms in [0, 5, 11, 18]:
        d = int(d_ms*SR/1000)
        bn = min(n-d, int(.028*SR))
        if bn > 0:
            b = noise(bn) * np.exp(-np.arange(bn, dtype=np.float32)/SR*80)
            b = bp(b, 400, 6000)
            out[d:d+bn] += b
    return np.tanh((out * np.exp(-t*14)) * 3) / 3

# ── synth ─────────────────────────────────────────────────────────────────────

def supersaw(freq, n, voices=7, det=14):
    out = np.zeros(n, np.float32)
    mid = voices // 2
    for i in range(voices):
        ct = (i-mid)/max(mid,1)*det
        out += saw(freq*2**(ct/1200), n)
    return out / voices

def drone(freq, n, lfo_rate=0.08, lfo_depth=0.004):
    """Dark ambient drone with slow pitch LFO"""
    t = t_arr(n)
    lfo = lfo_depth * np.sin(2*np.pi*lfo_rate*t)
    ph = 2*np.pi * freq * np.cumsum(1.0 + lfo) / SR
    body = (np.sin(ph)*0.6 + np.sin(2*ph)*0.25 + np.sin(3*ph)*0.12 +
            np.sin(4*ph)*0.03).astype(np.float32)
    return lp(body, 800)

def dark_pad(freqs, n, lp_cut=900, lfo_rate=0.15):
    """Dark supersaw pad with tremolo"""
    t = t_arr(n)
    tremolo = 1.0 - 0.12*np.sin(2*np.pi*lfo_rate*t)
    out = np.zeros(n, np.float32)
    for f in freqs:
        out += supersaw(f, n, voices=5, det=16)
    out = (out / len(freqs)) * tremolo.astype(np.float32)
    return lp(out, lp_cut)

def acid_note(freq, n, cutoff_start=2200, cutoff_end=120, resonance=9.0):
    """TB-303 acid note: resonant LP filter sweep"""
    body = saw(freq, n)
    # biquad resonant LP with per-sample cutoff sweep
    cutoffs = np.geomspace(cutoff_start, cutoff_end, n)
    out = np.zeros(n, np.float32)
    # Implement simple 1-pole resonant LP via direct form 1
    # (proper biquad would need per-sample coefficient update)
    # Fast approximation: multiple butterworth passes
    sweep_steps = 8
    step = n // sweep_steps
    chunk = body.copy()
    for i in range(sweep_steps):
        s = i * step
        e = min(s + step + 1, n)
        t_cut = cutoffs[s]
        try:
            b2, a2 = scipy.signal.butter(2, t_cut/(SR/2), 'low')
            chunk[s:e] = scipy.signal.lfilter(b2, a2, chunk[s:e])
        except Exception:
            pass
    # Resonance boost via narrow BP near cutoff midpoint
    mid_cut = (cutoff_start + cutoff_end) / 2
    res_boost = bp(body, mid_cut*0.7, mid_cut*1.3, order=2) * (resonance * 0.04)
    result = (chunk + res_boost) * env(n, 60, int(.1*SR), 0.65, int(.12*SR))
    return result.astype(np.float32)

def psychedelic_lead(freq, n):
    """Pitch-modulated lead with ring mod"""
    t = t_arr(n)
    # pitch wobble
    wobble = 0.012 * np.sin(2*np.pi*3.7*t) + 0.006*np.sin(2*np.pi*1.1*t)
    ph = 2*np.pi*freq*np.cumsum(1.0 + wobble)/SR
    body = np.sin(ph).astype(np.float32)
    # ring mod (amplitude modulation)
    carrier = sine(freq*0.125, n)   # sub-harmonic ring
    body = body * (0.7 + 0.3*carrier)
    body = lp(body, 3500)
    return (body * env(n, int(.08*SR), int(.12*SR), 0.55, int(.15*SR))).astype(np.float32)

def sub_bass(freq, n):
    body = sine(freq, n)*0.82 + sine(freq*2, n)*0.14 + sine(freq*3, n)*0.04
    return hp(lp(body*env(n, 60, int(.1*SR), .72, int(.14*SR)), 200), 28).astype(np.float32)

# ── Dm progression ─────────────────────────────────────────────────────────────
# Dm - Bb - F - Cm (dark, psychedelic)

CHORDS_DARK = [
    [146.83, 174.61, 220.00],    # Dm:  D3  F3  A3
    [116.54, 146.83, 174.61],    # Bb:  Bb2 D3  F3
    [130.81, 164.81, 196.00],    # F:   C3  E3  G3
    [130.81, 155.56, 196.00],    # Cm:  C3  Eb3 G3
]
DRONE_FREQS  = [36.71, 36.71, 32.70, 32.70]   # D1, D1, C1, C1 (deep drone)
BASS_ROOTS   = [36.71, 29.14, 32.70, 32.70]   # D1 Bb0 C1 C1

# Acid bass pattern (1 bar at 132 BPM = 8 acid notes on 8th notes)
ACID_SEQS = [
    [146.83,146.83,220.00,195.00,146.83,130.81,146.83,110.00],  # Dm pattern
    [116.54,116.54,174.61,155.00,116.54,110.00,116.54, 87.31],  # Bb pattern
    [130.81,130.81,196.00,174.61,130.81,123.47,130.81, 98.00],  # F pattern
    [130.81,130.81,196.00,155.56,130.81,116.54,130.81, 98.00],  # Cm pattern
]

# ── section builders ──────────────────────────────────────────────────────────

def render_drums_techno(bars, kick=True, snare=True, roll=False, hat_every=1):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    K  = mk_kick_techno()
    S  = mk_snare_industrial()
    HC = mk_hat_techno()
    HO = mk_hat_open_techno()
    CL = mk_clap_industrial()

    for bar in range(bars):
        bs = bar*BAR
        for beat in range(4):
            bp_pos = bs + beat*SPB
            for s16 in range(4):
                if (bar % hat_every) == 0:
                    stamp(buf, HC*0.60, bp_pos + s16*SIXTEENTH)
            stamp(buf, HO*0.55, bp_pos + EIGHTH)
            if kick  and beat in (0,2): stamp(buf, K,       bp_pos)
            if snare and beat in (1,3):
                stamp(buf, S*0.88,   bp_pos)
                stamp(buf, CL*0.55,  bp_pos)

    if roll:
        last = (bars-1)*BAR + BAR//2
        s32  = SIXTEENTH // 2
        for i in range(16):
            vol = 0.3 + 0.7*(i/15)
            stamp(buf, S*vol, last + i*s32)

    return buf

def render_ghost_kicks(bars):
    """Faint reverbed kicks for ambient intro"""
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    K   = mk_kick_ghost()
    for bar in range(bars):
        for beat in range(4):
            if beat in (0, 2):
                stamp(buf, K, bar*BAR + beat*SPB)
    return buf

def render_dark_pads(n_samples, lp_cut=900):
    buf = np.zeros(n_samples, np.float32)
    bar_n = min(BAR + int(.3*SR), n_samples)
    for start in range(0, n_samples, BAR):
        ci = (start // BAR) % 4
        ln = min(bar_n, n_samples - start)
        if ln > 0:
            pad = dark_pad(CHORDS_DARK[ci], ln, lp_cut)
            pad *= env(ln, int(.15*SR), int(.1*SR), 0.82, int(.3*SR))
            stamp(buf, pad, start)
    return buf

def render_drone(n_samples):
    buf = np.zeros(n_samples, np.float32)
    bar_n = min(BAR*4, n_samples)  # drone held 4 bars
    for start in range(0, n_samples, BAR*4):
        ci = (start // (BAR*4)) % 4
        ln = min(bar_n, n_samples - start)
        if ln > 0:
            d = drone(DRONE_FREQS[ci], ln, lfo_rate=0.06, lfo_depth=0.003)
            d *= env(ln, int(.5*SR), int(.2*SR), 0.88, int(.8*SR))
            stamp(buf, d, start)
    return buf

def render_acid(bars, vol=1.0):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    for bar in range(bars):
        ci = bar % 4
        seq = ACID_SEQS[ci]
        for i, freq in enumerate(seq):
            dur = EIGHTH + SIXTEENTH//2
            note = acid_note(freq, dur) * vol
            stamp(buf, note, bar*BAR + i*EIGHTH)
    return buf

def render_psych_lead(bars):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    dur = EIGHTH
    for bar in range(bars):
        ci = bar % 4
        # sparse: play on beats 1 and 3 only
        for beat in (0, 2, 3):
            freq = CHORDS_DARK[ci][beat % len(CHORDS_DARK[ci])]
            note = psychedelic_lead(freq * 2, dur)   # up an octave
            stamp(buf, note, bar*BAR + beat*SPB)
    return buf

def render_sub_bass(bars):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    for bar in range(bars):
        ci  = bar % 4
        root = BASS_ROOTS[ci]
        stamp(buf, sub_bass(root, BAR),      bar*BAR)
        stamp(buf, sub_bass(root*1.5, SPB),  bar*BAR + SPB*2)
    return buf

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    from pedalboard import Reverb, Chorus, Compressor, Gain, Delay, Phaser

    os.makedirs("shared/rework", exist_ok=True)
    np.random.seed(99)

    print(f"BPM={BPM} | BAR={BAR/SR:.2f}s | SR={SR}")

    # ── Timeline in samples ────────────────────────────────────────────────────
    # 0:00  dark ambient drone  90s
    # 1:30  ghost kicks + acid  30s
    # 2:00  psych lead + build  30s
    # 2:30  tension build       30s
    # 3:00  TECHNO DROP 1       90s
    # 4:30  breakdown acid      30s
    # 5:00  TECHNO DROP 2       60s
    # 6:00  outro               30s

    T_AMB   = int(90  * SR)   # 0:00 - 1:30
    T_GHOST = int(30  * SR)   # 1:30 - 2:00
    T_PSYCH = int(30  * SR)   # 2:00 - 2:30
    T_BUILD = int(30  * SR)   # 2:30 - 3:00
    T_DROP1 = int(90  * SR)   # 3:00 - 4:30
    T_BREAK = int(30  * SR)   # 4:30 - 5:00
    T_DROP2 = int(60  * SR)   # 5:00 - 6:00
    T_OUTRO = int(30  * SR)   # 6:00 - 6:30

    TOTAL = T_AMB+T_GHOST+T_PSYCH+T_BUILD+T_DROP1+T_BREAK+T_DROP2+T_OUTRO
    mix   = np.zeros(TOTAL, np.float32)

    # Align section starts to BAR boundaries after T_AMB
    def bars_from_samples(s):
        return max(1, s // BAR)

    # ── 1. DARK AMBIENT DRONE (0:00 - 1:30) ─────────────────────────────────
    print("1. Dark ambient drone (90s)...")
    n = T_AMB
    dr  = render_drone(n)
    pad = render_dark_pads(n, lp_cut=700)

    dr_fx  = apply_fx(dr,  [Reverb(0.92, 0.95, wet_level=0.85, dry_level=0.15),
                              Gain(-2)])
    pad_fx = apply_fx(pad, [Chorus(0.3, 0.6, mix=0.55),
                              Reverb(0.88, 0.90, wet_level=0.75, dry_level=0.25)])
    mix[:n] += dr_fx*0.55 + pad_fx*0.45

    # ── 2. GHOST KICKS + ACID ENTERS (1:30 - 2:00) ──────────────────────────
    print("2. Ghost kicks + acid (30s)...")
    s = T_AMB; n = T_GHOST
    nb = bars_from_samples(n)
    gk  = render_ghost_kicks(nb)
    ac  = render_acid(nb, vol=0.5)
    pad2 = render_dark_pads(nb*BAR, lp_cut=600)

    gk_fx  = apply_fx(gk,  [Reverb(0.80, 0.85, wet_level=0.70, dry_level=0.30)])
    ac_fx  = apply_fx(ac,  [Reverb(0.65, 0.75, wet_level=0.55, dry_level=0.45)])
    pad_fx2 = apply_fx(pad2, [Reverb(0.85, 0.88, wet_level=0.72, dry_level=0.28)])

    L = min(n, nb*BAR)
    mix[s:s+L] += gk_fx[:L]*0.38 + ac_fx[:L]*0.40 + pad_fx2[:L]*0.42

    # ── 3. PSYCHEDELIC LEAD (2:00 - 2:30) ────────────────────────────────────
    print("3. Psychedelic lead (30s)...")
    s = T_AMB+T_GHOST; n = T_PSYCH
    nb = bars_from_samples(n)
    gk   = render_ghost_kicks(nb)
    ac   = render_acid(nb, vol=0.7)
    pl   = render_psych_lead(nb)
    pad3 = render_dark_pads(nb*BAR, lp_cut=500)

    pl_fx  = apply_fx(pl, [Phaser(rate_hz=0.4, mix=0.60),
                             Reverb(0.72, 0.80, wet_level=0.60, dry_level=0.40),
                             Delay(delay_seconds=EIGHTH/SR, feedback=0.42, mix=0.38)])
    ac_fx2 = apply_fx(ac, [Reverb(0.55, 0.70, wet_level=0.45, dry_level=0.55)])
    pad_fx3 = apply_fx(pad3, [Reverb(0.80, 0.85, wet_level=0.65, dry_level=0.35)])
    gk_fx2 = apply_fx(gk, [Reverb(0.72, 0.80, wet_level=0.60, dry_level=0.40)])

    L = min(n, nb*BAR)
    mix[s:s+L] += gk_fx2[:L]*0.42 + ac_fx2[:L]*0.50 + pl_fx[:L]*0.42 + pad_fx3[:L]*0.38

    # ── 4. TENSION BUILD (2:30 - 3:00) ───────────────────────────────────────
    print("4. Tension build (30s)...")
    s = T_AMB+T_GHOST+T_PSYCH; n = T_BUILD
    nb = bars_from_samples(n)
    bd = render_drums_techno(nb, kick=False, snare=True, roll=True)
    ac3 = render_acid(nb, vol=0.85)
    # pad with rising filter
    p0 = render_dark_pads(nb*BAR, lp_cut=300)
    p1 = render_dark_pads(nb*BAR, lp_cut=2800)
    fade = np.linspace(0, 1, nb*BAR, dtype=np.float32)
    pad4 = p0*(1-fade) + p1*fade

    bd_fx  = apply_fx(bd,  [Reverb(0.50, 0.65, wet_level=0.45, dry_level=0.55)])
    ac_fx3 = apply_fx(ac3, [Reverb(0.40, 0.60, wet_level=0.32, dry_level=0.68)])
    pad_fx4 = apply_fx(pad4, [Reverb(0.55, 0.70, wet_level=0.42, dry_level=0.58)])

    L = min(n, nb*BAR)
    mix[s:s+L] += bd_fx[:L]*0.55 + ac_fx3[:L]*0.60 + pad_fx4[:L]*0.45

    # ── 5. TECHNO DROP 1 (3:00 - 4:30) ──────────────────────────────────────
    print("5. Techno drop 1 (90s)...")
    s = T_AMB+T_GHOST+T_PSYCH+T_BUILD; n = T_DROP1
    nb = bars_from_samples(n)
    dr1  = render_drums_techno(nb, kick=True, snare=True)
    ac4  = render_acid(nb, vol=1.0)
    bs1  = render_sub_bass(nb)
    pad5 = render_dark_pads(nb*BAR, lp_cut=1600)
    pl2  = render_psych_lead(nb)

    dr_fx1   = apply_fx(dr1,  [Compressor(-9, 4, 3, 70), Gain(2.5)])
    ac_fx4   = apply_fx(ac4,  [Compressor(-10, 3.5, 5, 90),
                                 Delay(delay_seconds=SIXTEENTH/SR, feedback=0.18, mix=0.22)])
    bs_fx1   = apply_fx(bs1,  [Compressor(-8, 4.5, 6, 110)])
    pad_fx5  = apply_fx(pad5, [Chorus(0.5, 0.3, mix=0.35),
                                 Reverb(0.38, 0.55, wet_level=0.28, dry_level=0.72),
                                 Compressor(-14, 2.5, 20, 200)])
    pl_fx2   = apply_fx(pl2,  [Phaser(rate_hz=0.6, mix=0.40),
                                 Reverb(0.30, 0.50, wet_level=0.22, dry_level=0.78)])

    L = min(n, nb*BAR)
    mix[s:s+L] += (dr_fx1[:L]*0.60 + ac_fx4[:L]*0.52 + bs_fx1[:L]*0.58 +
                   pad_fx5[:L]*0.38 + pl_fx2[:L]*0.35)

    # ── 6. BREAKDOWN + ACID (4:30 - 5:00) ────────────────────────────────────
    print("6. Breakdown acid (30s)...")
    s = T_AMB+T_GHOST+T_PSYCH+T_BUILD+T_DROP1; n = T_BREAK
    nb = bars_from_samples(n)
    ac5  = render_acid(nb, vol=1.0)
    pad6 = render_dark_pads(nb*BAR, lp_cut=900)
    pl3  = render_psych_lead(nb)

    ac_fx5  = apply_fx(ac5,  [Reverb(0.70, 0.80, wet_level=0.60, dry_level=0.40),
                                Delay(delay_seconds=EIGHTH/SR, feedback=0.42, mix=0.40)])
    pad_fx6 = apply_fx(pad6, [Reverb(0.85, 0.90, wet_level=0.72, dry_level=0.28)])
    pl_fx3  = apply_fx(pl3,  [Phaser(rate_hz=0.3, mix=0.70),
                                Reverb(0.80, 0.85, wet_level=0.68, dry_level=0.32)])

    L = min(n, nb*BAR)
    mix[s:s+L] += ac_fx5[:L]*0.55 + pad_fx6[:L]*0.50 + pl_fx3[:L]*0.42

    # ── 7. TECHNO DROP 2 (5:00 - 6:00) ──────────────────────────────────────
    print("7. Techno drop 2 - HARDER (60s)...")
    s = T_AMB+T_GHOST+T_PSYCH+T_BUILD+T_DROP1+T_BREAK; n = T_DROP2
    nb = bars_from_samples(n)
    dr2  = render_drums_techno(nb, kick=True, snare=True)
    ac6  = render_acid(nb, vol=1.0)
    bs2  = render_sub_bass(nb)
    pad7 = render_dark_pads(nb*BAR, lp_cut=2200)

    dr_fx2  = apply_fx(dr2,  [Compressor(-8, 5, 2, 60), Gain(3.0)])
    ac_fx6  = apply_fx(ac6,  [Compressor(-9, 4, 4, 80),
                                Delay(delay_seconds=SIXTEENTH/SR, feedback=0.22, mix=0.25)])
    bs_fx2  = apply_fx(bs2,  [Compressor(-7, 5, 5, 100)])
    pad_fx7 = apply_fx(pad7, [Chorus(0.4, 0.4, mix=0.40),
                                Reverb(0.35, 0.52, wet_level=0.25, dry_level=0.75)])

    L = min(n, nb*BAR)
    mix[s:s+L] += (dr_fx2[:L]*0.64 + ac_fx6[:L]*0.56 + bs_fx2[:L]*0.60 +
                   pad_fx7[:L]*0.40)

    # ── 8. OUTRO FADE (6:00 - 6:30) ──────────────────────────────────────────
    print("8. Outro fade (30s)...")
    s = T_AMB+T_GHOST+T_PSYCH+T_BUILD+T_DROP1+T_BREAK+T_DROP2; n = T_OUTRO
    nb = bars_from_samples(n)
    dr3  = render_drums_techno(nb, kick=True, snare=True)
    ac7  = render_acid(nb, vol=0.8)
    fade_out = np.linspace(1, 0, n, np.float32)

    L = min(n, nb*BAR)
    dr_o = apply_fx(dr3, [Gain(2)])
    mix[s:s+L] += (dr_o[:L]*0.60 + ac7[:L]*0.50) * fade_out[:L]

    # ── MASTER ────────────────────────────────────────────────────────────────
    print("\nMaster bus...")
    mix = apply_fx(mix, [Compressor(-5, 3.0, 3, 100), Gain(1.8)])
    mix = np.tanh(mix * 0.80) / 0.80
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= (10**(-0.5/20)) / peak

    print("Encoding 320kbps MP3...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    sf.write(tmp, mix, SR, subtype="PCM_24")
    os.system(f'ffmpeg -y -i "{tmp}" -b:a 320k -q:a 0 "{OUT}" 2>/dev/null')
    os.unlink(tmp)

    size = os.path.getsize(OUT)/1024/1024
    print(f"\n* Done: {OUT} ({size:.1f} MB, {TOTAL/SR:.0f}s)")

if __name__ == "__main__":
    main()
