#!/usr/bin/env python3
"""
dark_matter_techno.py -- Dark Matter: Psychedelic Ambient -> Hard Underground Techno

No pop motifs. No melodic hooks. Pure texture, acid, and industrial rhythm.
Key: Dm (tritones + minor 2nds -- dissonant, industrial)
BPM: 135 | Duration: ~8:30

Structure:
  0:00  Sub-harmonic void (barely audible, felt in chest)
  1:00  Noise texture + atmospheric fragments
  2:00  Ghost acid pulses (every 8 beats, buried in reverb)
  3:00  Acid opens + ghost kick enters
  4:00  FALSE DROP -- kick slams then cuts to silence
  4:30  Void -- drone + single repeating acid note
  5:00  Rebuild -- elements re-enter layer by layer
  6:00  HARD TECHNO -- double acid, industrial percussion
  7:30  Deconstruction -- layers drop out
  8:00  Final acid fade
"""
import numpy as np, scipy.signal, soundfile as sf
import os, tempfile, warnings
warnings.filterwarnings("ignore")

SR  = 44100
BPM = 135.0
SPB = int(SR * 60 / BPM)
BAR = SPB * 4
EIGHTH    = SPB // 2
SIXTEENTH = SPB // 4

OUT = "shared/rework/dark_matter_techno.mp3"

# ── anti-click helpers ────────────────────────────────────────────────────────

def fade_in_out(a, fi=256, fo=512):
    a = a.copy()
    fi = min(fi, len(a) // 4)
    fo = min(fo, len(a) // 4)
    if fi > 0: a[:fi]  *= np.linspace(0, 1, fi, dtype=np.float32)
    if fo > 0: a[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
    return a

def t_arr(n):
    return np.arange(n, dtype=np.float64) / SR

def sine(freq, n, phase=0.0):
    return np.sin(2*np.pi*freq*t_arr(n) + phase).astype(np.float32)

def saw(freq, n):
    t = t_arr(n)
    return (2*((freq*t) % 1.0) - 1).astype(np.float32)

def noise(n):
    return np.random.randn(n).astype(np.float32)

def lp_sos(a, cut, order=4):
    cut = float(np.clip(cut, 20, SR/2 - 50))
    sos = scipy.signal.butter(order, cut/(SR/2), 'low', output='sos')
    return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

def hp_sos(a, cut, order=2):
    cut = float(np.clip(cut, 10, SR/2 - 50))
    sos = scipy.signal.butter(order, cut/(SR/2), 'high', output='sos')
    return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

def env(n, atk, dec, sus, rel):
    e = np.zeros(n, np.float32)
    a1 = min(int(atk), n)
    d1 = min(a1+int(dec), n)
    r0 = max(0, n-int(rel))
    if a1:      e[:a1]   = np.linspace(0, 1, a1)
    if d1>a1:   e[a1:d1] = np.linspace(1, sus, d1-a1)
    if r0>d1:   e[d1:r0] = sus
    if n>r0:    e[r0:]   = np.linspace(sus, 0, n-r0)
    return e

def stamp(buf, hit, pos, gain=1.0):
    pos = int(pos)
    if pos < 0 or pos >= len(buf): return
    end = min(pos+len(hit), len(buf))
    n = end - pos
    if n > 0:
        buf[pos:end] += np.tanh(hit[:n] * gain * 0.9) / 0.9

def apply_fx(audio, chain):
    from pedalboard import Pedalboard
    board = Pedalboard(chain)
    r = board(audio[np.newaxis,:], SR)
    return r[0].astype(np.float32)

# ── drums -- hard industrial ──────────────────────────────────────────────────

def mk_kick():
    n = int(0.52*SR)
    t = t_arr(n)
    f = 65 + 145*np.exp(-t*30)
    ph = 2*np.pi*np.cumsum(f)/SR
    body = np.sin(ph).astype(np.float32)
    amp  = np.exp(-t*7.5).astype(np.float32)
    click = noise(n).astype(np.float32) * np.exp(-t.astype(np.float32)*420) * 0.14
    k = (body*amp + click)
    k = lp_sos(k, 6500); k = hp_sos(k, 25)
    k = np.tanh(k * 2.2) / 2.2
    k = fade_in_out(k, fi=16, fo=1024)
    return (k / (np.abs(k).max()+1e-6)).astype(np.float32)

def mk_snare_hard():
    n = int(0.22*SR)
    t = t_arr(n)
    body = sine(220, n) * 0.15 * np.exp(-t*50)
    nz   = noise(n) * 0.85 * np.exp(-t*20)
    nz   = hp_sos(nz, 200)
    s = (body + nz) * env(n, 15, int(.025*SR), .10, int(.07*SR))
    s = np.tanh(s * 3.0) / 3.0
    return fade_in_out(s, fi=8, fo=256)

def mk_hat():
    n = int(0.032*SR)
    t = t_arr(n)
    freqs = [5200, 7100, 9400, 12500, 16000]
    h = sum(np.sign(sine(f, n)) for f in freqs).astype(np.float32)
    h = lp_sos(h, 18000); h = hp_sos(h, 6000)
    return fade_in_out((h * np.exp(-t.astype(np.float32)*180) / len(freqs)).astype(np.float32))

def mk_hat_open():
    n = int(0.11*SR)
    t = t_arr(n)
    freqs = [5200, 7100, 9400, 12500, 16000]
    h = sum(np.sign(sine(f, n)) for f in freqs).astype(np.float32)
    h = lp_sos(h, 18000); h = hp_sos(h, 6000)
    return fade_in_out((h * np.exp(-t.astype(np.float32)*32) / len(freqs)).astype(np.float32))

def mk_industrial_hit():
    """Metallic industrial percussion"""
    n = int(0.35*SR)
    t = t_arr(n)
    # ring mod two metallic oscillators
    osc1 = sine(87.3, n)   # F2
    osc2 = sine(311.1, n)  # Eb4 -- dissonant
    ring = (osc1 * osc2).astype(np.float32)
    ring = ring * np.exp(-t.astype(np.float32)*12)
    nz = noise(n).astype(np.float32) * np.exp(-t.astype(np.float32)*20) * 0.3
    out = hp_sos(ring + nz, 120)
    out = np.tanh(out * 2.5) / 2.5
    return fade_in_out(out, fi=8, fo=512)

def mk_reversed_crash():
    """Reversed noise burst (cinematic riser)"""
    n = int(1.5*SR)
    t = t_arr(n)
    nz = noise(n)
    nz = lp_sos(nz, 8000); nz = hp_sos(nz, 1000)
    env_v = np.linspace(0, 1.0, n, dtype=np.float32)**1.8
    return fade_in_out((nz * env_v).astype(np.float32), fi=64, fo=64)

# ── synth ─────────────────────────────────────────────────────────────────────

def drone(freq, n, lfo_hz=0.05, depth=0.003):
    """Sub-harmonic drone with very slow LFO"""
    t = t_arr(n)
    lfo = depth * np.sin(2*np.pi*lfo_hz*t)
    ph = 2*np.pi*freq*np.cumsum(1.0 + lfo)/SR
    body = (np.sin(ph)*0.65 + np.sin(2*ph)*0.22 + np.sin(0.5*ph)*0.13).astype(np.float32)
    return lp_sos(body, 320)

def noise_texture(n, lp_cut=3000, hp_cut=800):
    """Evolving noise texture for atmosphere"""
    nz = noise(n)
    nz = lp_sos(nz, lp_cut); nz = hp_sos(nz, hp_cut)
    # slow AM modulation
    t = t_arr(n)
    am = 0.5 + 0.5*np.sin(2*np.pi*0.12*t)
    return (nz * am.astype(np.float32)).astype(np.float32)

def acid_note(freq, n, c_start=2400, c_end=80, resonance=9.0):
    """TB-303 acid -- TWO full filter passes crossfaded (no click artifacts)"""
    body = saw(freq, n)
    c0 = float(np.clip(c_start, 30, SR/2-100))
    c1 = float(np.clip(c_end,   30, SR/2-100))
    # Two filter renders
    sos_o = scipy.signal.butter(2, c0/(SR/2), 'low', output='sos')
    sos_c = scipy.signal.butter(2, c1/(SR/2), 'low', output='sos')
    f_open   = scipy.signal.sosfiltfilt(sos_o, body).astype(np.float32)
    f_closed = scipy.signal.sosfiltfilt(sos_c, body).astype(np.float32)
    # Resonance boost (bandpass near geometric mean cutoff)
    mid_cut = float(np.sqrt(c0*c1))
    res_lo = np.clip(mid_cut*0.70, 20, SR/2-200)
    res_hi = np.clip(mid_cut*1.30, res_lo+10, SR/2-100)
    if res_hi > res_lo + 10:
        sos_r = scipy.signal.butter(2, [res_lo/(SR/2), res_hi/(SR/2)], 'band', output='sos')
        res   = scipy.signal.sosfiltfilt(sos_r, body).astype(np.float32) * (resonance * 0.04)
    else:
        res = np.zeros_like(body)
    # Smooth crossfade open -> closed
    xfade = np.linspace(0, 1, n, dtype=np.float32)
    mixed = f_open*(1-xfade) + f_closed*xfade + res
    e = env(n, 50, int(.07*SR), 0.60, int(.10*SR))
    return fade_in_out((mixed * e).astype(np.float32), fi=32, fo=512)

def sub_bass(freq, n):
    body = sine(freq, n)*0.82 + sine(freq*2, n)*0.14 + sine(freq*3, n)*0.04
    out = hp_sos(lp_sos(body*env(n, 50, int(.08*SR), .75, int(.12*SR)), 240), 25)
    return fade_in_out(out.astype(np.float32), fi=64, fo=512)

# ── acid patterns (underground: tritones, minor 2nds, no triads) ──────────────
D2  = 73.42;  Db2 = 69.30;  Eb2 = 77.78;  E2  = 82.41
F2  = 87.31;  Ab2 = 103.83; A2  = 110.00;  G2  = 98.00
D1  = 36.71;  Bb1 = 58.27;  Ab1 = 51.91

ACID_SEQS = [
    # sparse industrial (every other 8th note)
    [D2,  0,   D2,  0,   Ab2, 0,   D2,  0  ],
    # tight underground
    [D2,  D2,  Ab2, D2,  Eb2, D2,  Ab2, D2 ],
    # chromatic descent
    [D2,  Db2, D2,  65.41,       Db2, D2,  Eb2, D2 ],  # C2
    # power acid
    [D2,  Ab2, D2,  G2,  D2,  Ab2, D2,  F2 ],
]

# fix the C_ shorthand
def _build_acid_seqs():
    C2 = 65.41
    return [
        [D2,   0,    D2,   0,    Ab2,  0,    D2,   0   ],
        [D2,   D2,   Ab2,  D2,   Eb2,  D2,   Ab2,  D2  ],
        [D2,   Db2,  D2,   C2,   Db2,  D2,   Eb2,  D2  ],
        [D2,   Ab2,  D2,   G2,   D2,   Ab2,  D2,   F2  ],
    ]

ACID_SEQS = _build_acid_seqs()

# ── renderer helpers ──────────────────────────────────────────────────────────

def render_acid_bars(bars, seq_idx=1, vol=1.0, c_start=2400, c_end=80):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    seq = ACID_SEQS[seq_idx % len(ACID_SEQS)]
    dur = EIGHTH + SIXTEENTH//4
    for bar in range(bars):
        for i, freq in enumerate(seq):
            if freq == 0: continue
            note = acid_note(freq, dur, c_start, c_end) * vol
            stamp(buf, note, bar*BAR + i*EIGHTH, gain=1.0)
    return buf

def render_drums(bars, kick=True, snare=True, hat=True, roll=False,
                 ghost_kick=False, ind_perc=False):
    n   = bars * BAR
    buf = np.zeros(n, np.float32)
    K  = mk_kick()
    S  = mk_snare_hard()
    HC = mk_hat()
    HO = mk_hat_open()
    IH = mk_industrial_hit()

    for bar in range(bars):
        bs = bar*BAR
        for beat in range(4):
            bp = bs + beat*SPB
            if hat:
                for s16 in range(4):
                    stamp(buf, HC*0.55, bp + s16*SIXTEENTH)
                stamp(buf, HO*0.50, bp + EIGHTH)
            if kick and beat in (0, 2):
                stamp(buf, K, bp)
            elif ghost_kick and beat in (0, 2):
                stamp(buf, K*0.18, bp)
            if snare and beat in (1, 3):
                stamp(buf, S*0.85, bp)
            if ind_perc and beat == 3 and (bar % 2 == 1):
                stamp(buf, IH*0.55, bp + SIXTEENTH)

    if roll:
        last = (bars-1)*BAR + BAR//2
        s32  = SIXTEENTH // 2
        for i in range(24):
            vol = 0.25 + 0.75*(i/23)**1.5
            stamp(buf, S*vol, last + i*s32)

    return buf

def render_drone(n_samples, freq=D1, lfo_hz=0.05):
    buf = np.zeros(n_samples, np.float32)
    chunk = BAR * 4
    for start in range(0, n_samples, chunk):
        ln = min(chunk + int(.5*SR), n_samples - start)
        if ln <= 0: break
        d = drone(freq, ln, lfo_hz)
        d *= env(ln, int(.3*SR), int(.2*SR), .90, int(.5*SR))
        stamp(buf, d, start)
    return buf

def render_sub(bars):
    n = bars * BAR
    buf = np.zeros(n, np.float32)
    for bar in range(bars):
        stamp(buf, sub_bass(D2, BAR), bar*BAR)
    return buf

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    from pedalboard import Reverb, Chorus, Compressor, Gain, Delay, Phaser, HighpassFilter, LowpassFilter

    os.makedirs("shared/rework", exist_ok=True)
    np.random.seed(77)

    # Timeline in seconds
    T = {
        'void':    90,   # 0:00 - 1:30  sub drone only
        'texture': 60,   # 1:30 - 2:30  noise + atmosphere
        'ghost':   60,   # 2:30 - 3:30  acid pulses, ghost kick
        'build':   60,   # 3:30 - 4:30  building tension
        'false':   10,   # 4:30 - 4:40  FALSE DROP (loud then CUT)
        'void2':   50,   # 4:40 - 5:30  silence/void
        'rebuild': 60,   # 5:30 - 6:30  layers return
        'drop1':   90,   # 6:30 - 8:00  HARD TECHNO
        'decon':   30,   # 8:00 - 8:30  deconstruct
        'fade':    30,   # 8:30 - 9:00  acid fade
    }
    sections = list(T.items())
    offsets = {}
    pos = 0
    for name, dur in sections:
        offsets[name] = pos * SR
        pos += dur
    TOTAL = pos * SR
    mix = np.zeros(TOTAL, np.float32)

    def bars_n(dur_s):
        return max(1, int(dur_s * SR) // BAR)

    # 1. VOID -- sub-harmonic drone barely audible ----------------------------
    print("1. Sub-harmonic void (90s)...")
    s = offsets['void']; n = T['void']*SR
    dr = render_drone(n, freq=D1, lfo_hz=0.04)
    dr_fx = apply_fx(dr, [
        Reverb(0.98, 0.98, wet_level=0.92, dry_level=0.08),
        Gain(-6),
    ])
    mix[s:s+n] += dr_fx * 0.45

    # 2. NOISE TEXTURE -- atmospheric fragments ------------------------------
    print("2. Noise texture (60s)...")
    s = offsets['texture']; n = T['texture']*SR
    dr2  = render_drone(n, freq=D1)
    nz   = noise_texture(n, lp_cut=2500, hp_cut=600)
    # cinematic riser at end
    rc   = mk_reversed_crash()
    if n - len(rc) > 0:
        mix[s + n - len(rc) : s + n] += rc * 0.28

    dr_fx2 = apply_fx(dr2, [Reverb(0.95, 0.96, wet_level=0.88, dry_level=0.12), Gain(-5)])
    nz_fx  = apply_fx(nz,  [Reverb(0.85, 0.88, wet_level=0.75, dry_level=0.25),
                              Phaser(rate_hz=0.08, mix=0.45)])
    mix[s:s+n] += dr_fx2*0.40 + nz_fx*0.22

    # 3. GHOST ACID -- pulses every 8 beats, very filtered -------------------
    print("3. Ghost acid pulses (60s)...")
    s = offsets['ghost']; n = T['ghost']*SR
    nb = bars_n(T['ghost'])
    dr3 = render_drone(nb*BAR, freq=D1)
    ac0 = render_acid_bars(nb, seq_idx=0, vol=0.70, c_start=600, c_end=80)
    gk  = render_drums(nb, kick=False, snare=False, hat=False, ghost_kick=True)

    ac_fx0 = apply_fx(ac0, [Reverb(0.88, 0.90, wet_level=0.82, dry_level=0.18),
                              Delay(delay_seconds=EIGHTH/SR, feedback=0.50, mix=0.42)])
    dr_fx3 = apply_fx(dr3, [Reverb(0.92, 0.94, wet_level=0.85, dry_level=0.15), Gain(-5)])
    gk_fx  = apply_fx(gk,  [Reverb(0.78, 0.82, wet_level=0.70, dry_level=0.30)])
    L = min(n, nb*BAR)
    mix[s:s+L] += dr_fx3[:L]*0.38 + ac_fx0[:L]*0.42 + gk_fx[:L]*0.28

    # 4. BUILD -- acid opens + industrial perc + tension ---------------------
    print("4. Tension build (60s)...")
    s = offsets['build']; n = T['build']*SR
    nb = bars_n(T['build'])
    dr4 = render_drone(nb*BAR, freq=D1)
    ac1 = render_acid_bars(nb, seq_idx=1, vol=0.85, c_start=1800, c_end=100)
    d4  = render_drums(nb, kick=False, snare=True, hat=True, roll=True, ind_perc=True)
    sub = render_sub(nb)

    # snare roll building from quiet to loud
    ac_fx1 = apply_fx(ac1, [Reverb(0.60, 0.72, wet_level=0.52, dry_level=0.48),
                              Delay(delay_seconds=SIXTEENTH/SR, feedback=0.30, mix=0.28)])
    d_fx4  = apply_fx(d4,  [Compressor(-12, 3, 5, 80), Gain(1)])
    dr_fx4 = apply_fx(dr4, [Reverb(0.88, 0.90, wet_level=0.78, dry_level=0.22), Gain(-5)])
    sub_fx = apply_fx(sub, [Compressor(-10, 4, 8, 120)])

    L = min(n, nb*BAR)
    # gradual vol ramp
    ramp = np.linspace(0.3, 1.0, L, dtype=np.float32)
    mix[s:s+L] += (dr_fx4[:L]*0.35 + ac_fx1[:L]*0.55 + d_fx4[:L]*0.52 + sub_fx[:L]*0.45) * ramp

    # 5. FALSE DROP -- slam kick LOUD then abrupt silence --------------------
    print("5. False drop (10s)...")
    s = offsets['false']; n = T['false']*SR
    nb = bars_n(T['false'])
    fd = render_drums(nb, kick=True, snare=True, hat=True)
    ac_fd = render_acid_bars(nb, seq_idx=3, vol=1.0, c_start=3000, c_end=120)
    fd_fx = apply_fx(fd, [Compressor(-8, 5, 2, 50), Gain(3.5)])
    ac_fdfx = apply_fx(ac_fd, [Compressor(-9, 4, 3, 80)])
    L = min(n, nb*BAR)
    # first 5s loud, then hard cut to near-silence
    cut = min(L, int(5*SR))
    mix[s:s+cut]  += fd_fx[:cut]*0.65 + ac_fdfx[:cut]*0.58
    # abrupt silence -- just residual drone
    mix[s+cut:s+L] *= 0.03

    # 6. VOID 2 -- near silence, single acid note repeating -----------------
    print("6. Void 2 (50s)...")
    s = offsets['void2']; n = T['void2']*SR
    nb = bars_n(T['void2'])
    dr5 = render_drone(nb*BAR, freq=D1, lfo_hz=0.03)
    # single acid note every 4 beats
    ac_void = np.zeros(nb*BAR, np.float32)
    dur = SPB * 2
    for bar in range(nb):
        if bar % 2 == 0:
            note = acid_note(D2, dur, c_start=400, c_end=60, resonance=11.0)
            stamp(ac_void, note, bar*BAR, gain=0.7)

    dr_fx5 = apply_fx(dr5, [Reverb(0.98, 0.98, wet_level=0.92, dry_level=0.08), Gain(-7)])
    ac_vfx = apply_fx(ac_void, [Reverb(0.90, 0.92, wet_level=0.85, dry_level=0.15),
                                  Delay(delay_seconds=EIGHTH/SR, feedback=0.55, mix=0.45)])
    L = min(n, nb*BAR)
    mix[s:s+L] += dr_fx5[:L]*0.40 + ac_vfx[:L]*0.38

    # 7. REBUILD -- layers return one by one --------------------------------
    print("7. Rebuild (60s)...")
    s = offsets['rebuild']; n = T['rebuild']*SR
    nb = bars_n(T['rebuild'])
    nb4 = nb // 4

    # first quarter: just sub + closed acid
    for q, (kick, snare, hat, ac_vol, ac_seq) in enumerate([
        (False, False, False, 0.5, 0),
        (False, True,  True,  0.7, 1),
        (True,  True,  True,  0.9, 1),
        (True,  True,  True,  1.0, 3),
    ]):
        qstart = s + q * nb4 * BAR
        dr_q = render_drums(nb4, kick=kick, snare=snare, hat=hat, ind_perc=True)
        ac_q = render_acid_bars(nb4, seq_idx=ac_seq, vol=ac_vol, c_start=2200, c_end=90)
        sub_q = render_sub(nb4)
        dr_fxq = apply_fx(dr_q, [Compressor(-10, 4, 3, 70), Gain(2)])
        ac_fxq = apply_fx(ac_q, [Compressor(-10, 3.5, 5, 90),
                                    Delay(delay_seconds=SIXTEENTH/SR, feedback=0.20, mix=0.22)])
        sf_q   = apply_fx(sub_q, [Compressor(-8, 4, 6, 100)])
        L = nb4*BAR
        mix[qstart:qstart+L] += dr_fxq*0.58 + ac_fxq*0.55 + sf_q*0.55

    # 8. HARD TECHNO DROP 1 -------------------------------------------------
    print("8. Hard techno drop (90s)...")
    s = offsets['drop1']; n = T['drop1']*SR
    nb = bars_n(T['drop1'])
    dr6  = render_drums(nb, kick=True, snare=True, hat=True, ind_perc=True)
    ac6a = render_acid_bars(nb, seq_idx=1, vol=1.0, c_start=2800, c_end=80)
    ac6b = render_acid_bars(nb, seq_idx=3, vol=0.55, c_start=1200, c_end=200)  # 2nd acid layer
    sub6 = render_sub(nb)
    dr_fx6  = apply_fx(dr6,  [Compressor(-8, 5, 2, 60), Gain(3.0)])
    ac_fx6a = apply_fx(ac6a, [Compressor(-9, 4, 4, 80),
                                Delay(delay_seconds=SIXTEENTH/SR, feedback=0.18, mix=0.20)])
    ac_fx6b = apply_fx(ac6b, [Compressor(-11, 3.5, 5, 90), Gain(-2)])
    sub_fx6 = apply_fx(sub6, [Compressor(-7, 5, 5, 100)])
    L = min(n, nb*BAR)
    mix[s:s+L] += (dr_fx6[:L]*0.62 + ac_fx6a[:L]*0.58 + ac_fx6b[:L]*0.38 + sub_fx6[:L]*0.60)

    # 9. DECONSTRUCTION -- elements drop out randomly -----------------------
    print("9. Deconstruction (30s)...")
    s = offsets['decon']; n = T['decon']*SR
    nb = bars_n(T['decon'])
    dr7  = render_drums(nb, kick=True, snare=True, hat=False)
    ac7  = render_acid_bars(nb, seq_idx=2, vol=0.9, c_start=1500, c_end=80)
    fade_d = np.linspace(1, 0.1, nb*BAR, dtype=np.float32)
    dr_fx7 = apply_fx(dr7, [Compressor(-9, 4, 3, 70), Gain(2.5)])
    ac_fx7 = apply_fx(ac7, [Reverb(0.55, 0.65, wet_level=0.45, dry_level=0.55)])
    L = min(n, nb*BAR)
    mix[s:s+L] += (dr_fx7[:L]*0.58 + ac_fx7[:L]*0.52) * fade_d[:L]

    # 10. FADE -- acid only -------------------------------------------------
    print("10. Final acid fade (30s)...")
    s = offsets['fade']; n = T['fade']*SR
    nb = bars_n(T['fade'])
    ac8  = render_acid_bars(nb, seq_idx=0, vol=0.8, c_start=800, c_end=60)
    dr8  = render_drone(nb*BAR, freq=D1)
    ac_fx8 = apply_fx(ac8, [Reverb(0.85, 0.90, wet_level=0.78, dry_level=0.22),
                              Delay(delay_seconds=EIGHTH/SR, feedback=0.45, mix=0.40)])
    dr_fx8 = apply_fx(dr8, [Reverb(0.95, 0.96, wet_level=0.88, dry_level=0.12), Gain(-5)])
    fade_f = np.linspace(1, 0, nb*BAR, dtype=np.float32)
    L = min(n, nb*BAR)
    mix[s:s+L] += (ac_fx8[:L]*0.45 + dr_fx8[:L]*0.35) * fade_f[:L]

    # ── MASTER ────────────────────────────────────────────────────────────────
    print("\nMaster bus...")
    mix = hp_sos(mix, 22)                     # remove DC and sub-20Hz rumble
    mix = apply_fx(mix, [Compressor(-5, 3.0, 3, 100), Gain(2.0)])
    mix = np.tanh(mix * 0.82) / 0.82          # soft clip (not hard)
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
