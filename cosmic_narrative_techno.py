#!/usr/bin/env python3
"""
cosmic_narrative_techno.py -- Cosmic Narrative Techno

Architecture: AUTOMATION-DRIVEN (no section cuts)
Every parameter evolves continuously via smooth curves.
Nothing "starts" or "stops" abruptly -- everything fades in/out over bars.

Elements run for the FULL track duration:
  - Drone: always, level automation
  - Pad: always, filter + level automation
  - Acid: always, filter cutoff automation (200Hz→3200Hz→800Hz→3000Hz)
  - Kick: amplitude automation (ghost→full→breakdown→return)
  - Hats: amplitude automation (before kick)
  - Snare: amplitude automation (after kick)
  - Cosmic noise texture: always, level automation

BPM: 133 | Key: Dm | Stereo | ~10 min
"""
import numpy as np, scipy.signal, scipy.ndimage, soundfile as sf
import os, sys, tempfile, warnings
warnings.filterwarnings("ignore")

SR  = 44100
BPM = 133.0
SPB = int(SR * 60 / BPM)
BAR = SPB * 4
EIGHTH    = SPB // 2
SIXTEENTH = SPB // 4

TOTAL_S = 600          # 10 minutes
N = TOTAL_S * SR
OUT = "shared/rework/cosmic_narrative_techno.mp3"

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
    sos = scipy.signal.butter(order, np.clip(cut,20,SR/2-50)/(SR/2), 'low', output='sos')
    return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

def hp(a, cut, order=2):
    sos = scipy.signal.butter(order, np.clip(cut,10,SR/2-50)/(SR/2), 'high', output='sos')
    return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

def env_n(n, atk, dec, sus, rel):
    e = np.zeros(n, np.float32)
    a1=min(int(atk),n); d1=min(a1+int(dec),n); r0=max(0,n-int(rel))
    if a1:    e[:a1]   = np.linspace(0, 1, a1)
    if d1>a1: e[a1:d1] = np.linspace(1, sus, d1-a1)
    if r0>d1: e[d1:r0] = sus
    if n>r0:  e[r0:]   = np.linspace(sus, 0, n-r0)
    return e

def fade(a, fi=256, fo=512):
    a=a.copy(); fi=min(fi,len(a)//4); fo=min(fo,len(a)//4)
    if fi>1: a[:fi]  *= np.linspace(0,1,fi,dtype=np.float32)
    if fo>1: a[-fo:] *= np.linspace(1,0,fo,dtype=np.float32)
    return a

def stamp(buf, hit, pos, gain=1.0):
    pos=int(pos)
    if pos<0 or pos>=len(buf): return
    end=min(pos+len(hit),len(buf)); n=end-pos
    if n>0: buf[pos:end] += hit[:n]*gain

def apply_fx(audio, chain):
    from pedalboard import Pedalboard
    board=Pedalboard(chain)
    if audio.ndim==1: audio=audio[np.newaxis,:]
    return board(audio, SR).astype(np.float32)

# ── smooth automation curves ──────────────────────────────────────────────────

_T = np.linspace(0, TOTAL_S, N, dtype=np.float32)

def auto(kf_sec, kf_val, sigma_s=4.0):
    """Smooth automation curve: keyframes in seconds → array of length N.
    Works at 2 pts/sec resolution to avoid huge gaussian convolution."""
    n_short = TOTAL_S * 2          # 1200 points for 600s
    t_short = np.linspace(0, TOTAL_S, n_short)
    arr_short = np.interp(t_short, kf_sec, kf_val).astype(np.float32)
    if sigma_s > 0:
        sigma_pts = max(1.0, sigma_s * 2)   # sigma in short-array pts
        arr_short = scipy.ndimage.gaussian_filter1d(arr_short, sigma_pts).astype(np.float32)
    return np.interp(_T, t_short, arr_short).astype(np.float32)

# Narrative arc keyframes (seconds):
#  0→120: cosmic intro, very slow build
#  120→210: elements appear
#  210→300: first techno peak
#  300→360: breakdown (cosmic)
#  360→480: second build, darker
#  480→540: second peak, hardest
#  540→600: gradual cosmic fade

KICK_AMP = auto(
    [0,  90,  120, 150, 210, 300, 330, 360, 420, 480, 540, 570, 600],
    [0,  0,   0.06, 0.35, 1.0, 1.0, 0.12, 0.0, 0.7, 1.0, 1.0, 0.4, 0],
    sigma_s=5.0
)
SNARE_AMP = auto(
    [0,  120, 150, 180, 210, 300, 360, 420, 480, 540, 570, 600],
    [0,  0,   0.0, 0.2, 0.9, 0.9, 0.0, 0.5, 1.0, 1.0, 0.3, 0],
    sigma_s=5.0
)
HAT_AMP = auto(
    [0,  60,  90, 120, 300, 360, 390, 480, 540, 570, 600],
    [0,  0,  0.15, 0.8, 0.8, 0.0, 0.6, 1.0, 1.0, 0.35, 0],
    sigma_s=4.0
)
# Acid filter cutoff automation (Hz)
ACID_CUT = auto(
    [0,  60, 120, 150, 210, 300, 360, 420, 480, 540, 570, 600],
    [200,210, 280, 800, 3000,3000,400, 1200,3200,3200,1000,200],
    sigma_s=8.0
)
# Acid amplitude automation
ACID_AMP = auto(
    [0,  30,  90, 120, 210, 300, 360, 420, 480, 540, 570, 600],
    [0,  0.08,0.3, 0.7, 1.0, 1.0, 0.6, 0.9, 1.0, 1.0, 0.6, 0],
    sigma_s=4.0
)
# Second acid layer (enters later, different pattern)
ACID2_AMP = auto(
    [0, 240, 270, 360, 420, 480, 540, 570, 600],
    [0, 0,   0.4, 0.0, 0.3, 0.7, 0.7, 0.2,  0],
    sigma_s=5.0
)
PAD_LEVEL = auto(
    [0,  0,   60,  90,  210, 270, 300, 360, 420, 480, 540, 600],
    [0.7,0.7, 0.9, 0.9, 0.4, 0.4, 0.9, 0.9, 0.35, 0.35, 0.6, 0.8],
    sigma_s=5.0
)
PAD_FILTER = auto(
    [0,   60,  120, 210, 300, 360, 420, 480, 540, 600],
    [500, 700, 900, 1800,1600,800, 2200,2000,1400, 600],
    sigma_s=8.0
)
DRONE_LEVEL = auto(
    [0,  0,  60,  210, 300, 360, 480, 540, 600],
    [0.6,0.6,0.65, 0.3, 0.4, 0.7, 0.3, 0.4, 0.7],
    sigma_s=6.0
)
TEXTURE_LEVEL = auto(
    [0,  0,  90,  120, 210, 300, 360, 480, 540, 600],
    [0.4,0.4, 0.5, 0.3, 0.1, 0.1, 0.5, 0.1, 0.15, 0.5],
    sigma_s=5.0
)
# Reverb wet level (automated)
REV_WET = auto(
    [0,  0,  90,  150, 210, 300, 360, 480, 540, 600],
    [0.85,0.85,0.80, 0.45, 0.28, 0.70, 0.70, 0.26, 0.35, 0.80],
    sigma_s=4.0
)
# Stereo width (for pads, via haas delay ms)
STEREO_W = auto(
    [0,  60,  120, 210, 300, 360, 480, 540, 600],
    [0,  2,    8,   12,  16,  18,  15,  16,   8],
    sigma_s=5.0
)

# ── drum templates ────────────────────────────────────────────────────────────

def mk_kick():
    n=int(0.50*SR); t=t_arr(n)
    f=62+145*np.exp(-t*28)
    ph=2*np.pi*np.cumsum(f)/SR
    body=np.sin(ph).astype(np.float32)*np.exp(-t*7.5).astype(np.float32)
    click=noise(n).astype(np.float32)*np.exp(-t.astype(np.float32)*450)*0.15
    k=lp(body+click, 6200); k=hp(k, 24)
    k=np.tanh(k*2.3)/2.3
    return fade(k/(np.abs(k).max()+1e-6), fi=8, fo=1024)

def mk_snare():
    n=int(0.22*SR); t=t_arr(n)
    body=sine(215,n)*0.18*np.exp(-t*44)
    nz=noise(n)*0.82*np.exp(-t*21)
    s=(body+hp(nz,160))*env_n(n,12,int(.025*SR),.11,int(.07*SR))
    return fade(np.tanh(s*2.9)/2.9, fi=8, fo=256)

def mk_hat_c():
    n=int(0.030*SR); t=t_arr(n)
    freqs=[5300,7200,9700,13000,17000]
    h=sum(np.sign(sine(f,n)) for f in freqs).astype(np.float32)
    return fade((hp(h,6500)*np.exp(-t.astype(np.float32)*170)/len(freqs)).astype(np.float32), fi=4, fo=64)

def mk_hat_o():
    n=int(0.12*SR); t=t_arr(n)
    freqs=[5300,7200,9700,13000,17000]
    h=sum(np.sign(sine(f,n)) for f in freqs).astype(np.float32)
    return fade((hp(h,6500)*np.exp(-t.astype(np.float32)*25)/len(freqs)).astype(np.float32), fi=4, fo=512)

# ── synthesis ─────────────────────────────────────────────────────────────────

def acid_note_cut(freq, n, cutoff):
    """Acid note with specific filter cutoff (no animation within note)"""
    body=saw(freq,n)
    c=float(np.clip(cutoff,30,SR/2-100))
    sos=scipy.signal.butter(2, c/(SR/2), 'low', output='sos')
    filtered=scipy.signal.sosfiltfilt(sos, body).astype(np.float32)
    # mild resonance
    mid=np.clip(c*0.6, 20, SR/2-200)
    hi=np.clip(c*1.4, mid+10, SR/2-100)
    if hi>mid+10:
        sosr=scipy.signal.butter(2,[mid/(SR/2),hi/(SR/2)],'band',output='sos')
        filtered += scipy.signal.sosfiltfilt(sosr, body).astype(np.float32)*(9*0.04)
    return fade((filtered*env_n(n,40,int(.06*SR),.65,int(.09*SR))).astype(np.float32), fi=32, fo=512)

def sub_bass_note(freq, n):
    body=sine(freq,n)*.82+sine(freq*2,n)*.14+sine(freq*3,n)*.04
    return hp(lp(body*env_n(n,50,int(.08*SR),.74,int(.12*SR)),200),25).astype(np.float32)

def cosmic_drone(n):
    t=t_arr(n)
    # Two detuned drones creating slow beating
    lfo1=0.003*np.sin(2*np.pi*0.038*t)
    lfo2=0.003*np.sin(2*np.pi*0.051*t + 1.7)
    f1=36.71*(1+lfo1); f2=36.71*1.001*(1+lfo2)  # D1, slightly sharp
    ph1=2*np.pi*np.cumsum(f1)/SR
    ph2=2*np.pi*np.cumsum(f2)/SR
    body=(np.sin(ph1)*0.5+np.sin(ph2)*0.5+
          np.sin(ph1*2)*0.2+np.sin(ph2*3)*0.1).astype(np.float32)
    return lp(body, 400)

def cosmic_pad_chunk(freqs, n, lp_cut):
    """Slow supersaw pad"""
    t=t_arr(n); lfo=0.06*np.sin(2*np.pi*0.14*t)
    out=np.zeros(n, np.float32)
    for f in freqs:
        for v in range(5):
            det=((v-2)/2)*13
            lfo_f=f*2**(det/1200)*(1+lfo*0.4)
            ph=2*np.pi*np.cumsum(lfo_f)/SR
            out+=np.sin(ph).astype(np.float32)
    out/=(len(freqs)*5)
    return lp(out, lp_cut)

def cosmic_noise_texture(n, lp_cut=2500, hp_cut=600):
    nz=noise(n); nz=lp(nz,lp_cut); nz=hp(nz,hp_cut)
    t=t_arr(n)
    am=0.5+0.5*np.sin(2*np.pi*0.09*t+1.2)*np.sin(2*np.pi*0.21*t)
    return (nz*am.astype(np.float32)).astype(np.float32)

# ── stereo helpers ─────────────────────────────────────────────────────────────

def haas(mono, delay_ms):
    d=max(1, int(delay_ms*SR/1000))
    right=np.zeros_like(mono); right[d:]=mono[:-d]
    return np.stack([mono, right], axis=0).astype(np.float32)

def ping_pong(mono, delay_s, fb=0.35, mix=0.32):
    d=int(delay_s*SR); d2=int(delay_s*SR*0.618)
    left=mono.copy(); right=mono.copy()
    for i in range(d,  len(mono)): right[i]+=mono[i-d]*fb
    for i in range(d2, len(mono)): left[i] +=right[i-d2]*fb*0.72
    return np.stack([mono+right*mix, mono+left*mix], axis=0).astype(np.float32)

def mono_stereo(mono, width=1.0):
    l=np.cos(np.pi/4)*np.sqrt(0.5+width*0.5)
    r=np.sin(np.pi/4)*np.sqrt(0.5+width*0.5)
    return np.stack([mono*l, mono*r]).astype(np.float32)

# ── patterns ──────────────────────────────────────────────────────────────────

D2=73.42; Ab2=103.83; Eb2=77.78; Db2=69.30; F2=87.31; G2=98.0; E2=82.41; A2=110.0
D1=36.71

ACID_PAT_1 = [D2,D2,Ab2,D2, Eb2,D2,Ab2,D2, D2,D2,Ab2,Eb2, D2,D2,E2,D2]   # 16 steps
ACID_PAT_2 = [D2,Ab2,D2,G2, D2,Ab2,Eb2,D2, D2,Ab2,D2,F2,  Db2,D2,A2,D2]  # second layer

PAD_CHORDS = [
    [73.42, 87.31, 110.0],   # Dm
    [58.27, 73.42, 87.31],   # Bb
    [65.41, 82.41, 98.0],    # F
    [65.41, 77.78, 98.0],    # Cm
]

BASS_ROOTS = [36.71, 29.14, 32.70, 32.70]   # D1 Bb0 C1 C1

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    from pedalboard import Reverb, Chorus, Compressor, Gain, Delay, Phaser, HighpassFilter

    os.makedirs("shared/rework", exist_ok=True)
    np.random.seed(42)

    print(f"Cosmic Narrative Techno | BPM={BPM} | {TOTAL_S}s | N={N:,}")
    print("Building automation-driven track (no section cuts)...\n")

    # Output: stereo (2, N)
    out_L = np.zeros(N, np.float32)
    out_R = np.zeros(N, np.float32)

    def add_stereo(ch2, pos=0, gain=1.0):
        l=min(ch2.shape[1], N-pos)
        if l>0:
            out_L[pos:pos+l] += ch2[0,:l]*gain
            out_R[pos:pos+l] += ch2[1,:l]*gain

    def add_mono(mono, pos=0, gain=1.0, width=1.0):
        s=haas(mono, 0) if width<0.1 else mono_stereo(mono, width)
        add_stereo(s, pos, gain)

    # ── 1. COSMIC DRONE (full track) ─────────────────────────────────────────
    print("Rendering drone (full track)...")
    CHUNK = BAR * 32
    for pos in range(0, N, CHUNK):
        n = min(CHUNK + int(.5*SR), N - pos)
        if n <= 0: break
        d = cosmic_drone(n)
        d *= env_n(n, int(.3*SR), int(.2*SR), .92, int(.5*SR))
        # apply drone level automation
        lvl = DRONE_LEVEL[pos:pos+len(d)]
        if len(lvl) < len(d): d = d[:len(lvl)]
        d_fx = apply_fx(d, [Reverb(0.95, 0.97, wet_level=0.88, dry_level=0.12)])
        d_mono = (d_fx[0] if d_fx.ndim>1 else d_fx) * lvl
        add_mono(d_mono, pos, width=0.05)

    # ── 2. NOISE TEXTURE (full track) ────────────────────────────────────────
    print("Rendering cosmic texture (full track)...")
    for pos in range(0, N, CHUNK):
        n = min(CHUNK, N - pos)
        if n <= 0: break
        tx = cosmic_noise_texture(n, lp_cut=3000, hp_cut=400)
        lvl = TEXTURE_LEVEL[pos:pos+n]
        tx_fx = apply_fx(tx, [Reverb(0.88, 0.90, wet_level=0.80, dry_level=0.20)])[0]
        add_mono(tx_fx * lvl, pos, width=0.8)

    # ── 3. PAD (full track, filter + level automation) ────────────────────────
    print("Rendering pad (full track)...")
    for pos in range(0, N, BAR):
        n = min(BAR + int(.25*SR), N - pos)
        if n <= 0: break
        ci = (pos // BAR) % 4
        lp_cut = float(PAD_FILTER[pos])
        pad = cosmic_pad_chunk(PAD_CHORDS[ci], n, lp_cut)
        pad *= env_n(n, int(.15*SR), int(.08*SR), .85, int(.25*SR))
        lvl = PAD_LEVEL[pos]
        # haas delay width from automation
        delay_ms = float(STEREO_W[pos])
        p_st = haas(pad, delay_ms)
        add_stereo(p_st, pos, gain=lvl*0.48)

    # ── 4. ACID LAYER 1 (full track, filter automation per note) ─────────────
    print("Rendering acid layer 1 (filter automation per note)...")
    acid_buf = np.zeros(N, np.float32)
    dur = int(SIXTEENTH * 0.88)
    n_bars = N // BAR
    for bar in range(n_bars):
        for i, freq in enumerate(ACID_PAT_1):
            pos = bar*BAR + i*SIXTEENTH
            if pos + dur > N: break
            cutoff = float(ACID_CUT[pos])       # per-note filter from automation
            amp    = float(ACID_AMP[pos])
            if amp < 0.01: continue
            note = acid_note_cut(freq, dur, cutoff)
            stamp(acid_buf, note, pos, gain=amp)

    acid1_pp = ping_pong(acid_buf, EIGHTH/SR, fb=0.32, mix=0.28)
    acid1_fx = apply_fx(acid1_pp, [
        Compressor(-11, 3.5, 5, 90),
        Delay(delay_seconds=SIXTEENTH/SR, feedback=0.18, mix=0.16),
    ])
    add_stereo(acid1_fx * 0.58)

    # ── 5. ACID LAYER 2 (enters at 4:00, opposite pan) ───────────────────────
    print("Rendering acid layer 2 (second pattern)...")
    acid2_buf = np.zeros(N, np.float32)
    for bar in range(n_bars):
        for i, freq in enumerate(ACID_PAT_2):
            pos = bar*BAR + i*SIXTEENTH
            if pos + dur > N: break
            cutoff = float(ACID_CUT[pos]) * 0.65  # darker filter
            amp    = float(ACID2_AMP[pos])
            if amp < 0.01: continue
            note = acid_note_cut(freq, dur, cutoff)
            stamp(acid2_buf, note, pos, gain=amp)

    acid2_pp = ping_pong(acid2_buf, EIGHTH/SR*0.618, fb=0.30, mix=0.26)
    acid2_pp = np.stack([acid2_pp[1], acid2_pp[0]], axis=0)  # flip L/R
    acid2_fx = apply_fx(acid2_pp, [Compressor(-12, 3, 5, 100)])
    add_stereo(acid2_fx * 0.40)

    # ── 6. SUB BASS (full track) ──────────────────────────────────────────────
    print("Rendering sub bass...")
    bass_buf = np.zeros(N, np.float32)
    for bar in range(n_bars):
        ci = bar % 4
        root = BASS_ROOTS[ci]
        stamp(bass_buf, sub_bass_note(root, BAR),     bar*BAR)
        stamp(bass_buf, sub_bass_note(root*1.5, SPB), bar*BAR + SPB*2)
    # amplitude follows kick automation (bass = kick companion)
    bass_env = np.clip(KICK_AMP * 1.4, 0, 1)
    bass_buf *= bass_env
    bass_fx = apply_fx(bass_buf, [Compressor(-8, 4, 5, 100)])[0]
    add_mono(bass_fx, width=0.04, gain=0.60)

    # ── 7. DRUMS (per-hit amplitude from automation) ──────────────────────────
    print("Rendering drums (automation per hit)...")
    K=mk_kick(); S=mk_snare(); HC=mk_hat_c(); HO=mk_hat_o()

    drum_buf = np.zeros(N, np.float32)
    for bar in range(n_bars):
        for beat in range(4):
            pos_beat = bar*BAR + beat*SPB
            if pos_beat >= N: break

            # Hats: every 16th + open on 8th offbeat
            hat_a = float(HAT_AMP[pos_beat])
            if hat_a > 0.005:
                for s16 in range(4):
                    p = pos_beat + s16*SIXTEENTH
                    stamp(drum_buf, HC*0.52*hat_a, p)
                stamp(drum_buf, HO*0.46*hat_a, pos_beat + EIGHTH)

            # Kick on 1 and 3
            if beat in (0, 2):
                k_a = float(KICK_AMP[pos_beat])
                if k_a > 0.005:
                    stamp(drum_buf, K*k_a, pos_beat)

            # Snare/clap on 2 and 4
            if beat in (1, 3):
                s_a = float(SNARE_AMP[pos_beat])
                if s_a > 0.005:
                    stamp(drum_buf, S*0.88*s_a, pos_beat)

    # Per-section reverb wet: apply global reverb post-mix
    # Heavy reverb in intro/breakdown, tight in drops
    # We'll apply per-chunk with reverb_wet automation
    drum_parts = np.zeros(N, np.float32)
    for pos in range(0, N, BAR*4):
        n = min(BAR*4, N-pos)
        if n <= 0: break
        chunk = drum_buf[pos:pos+n]
        wet = float(REV_WET[pos])
        dry = 1.0 - wet * 0.6
        chunk_fx = apply_fx(chunk, [
            Compressor(-10, 4, 3, 70),
            Gain(2.0),
            Reverb(0.55, 0.65, wet_level=wet*0.5, dry_level=dry),
        ])[0]
        drum_parts[pos:pos+n] += chunk_fx[:n]

    drum_stereo = haas(drum_parts, 4.0)
    add_stereo(drum_stereo * 0.62)

    # ── MASTER ────────────────────────────────────────────────────────────────
    print("\nMaster bus...")
    stereo = np.stack([out_L, out_R], axis=0)

    # Global low-end cleanup
    stereo = apply_fx(stereo, [HighpassFilter(cutoff_frequency_hz=22)])

    # Master compression
    stereo = apply_fx(stereo, [Compressor(-5, 2.8, 3, 120), Gain(2.0)])

    # Soft clip (no hard distortion)
    stereo = np.tanh(stereo * 0.80) / 0.80

    # Normalize to -0.5 dBFS
    peak = np.abs(stereo).max()
    if peak > 0:
        stereo *= (10**(-0.5/20)) / peak

    print("Encoding 320kbps stereo MP3...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    sf.write(tmp, stereo.T, SR, subtype="PCM_24")
    os.system(f'ffmpeg -y -i "{tmp}" -b:a 320k -q:a 0 "{OUT}" 2>/dev/null')
    os.unlink(tmp)

    size = os.path.getsize(OUT)/1024/1024
    print(f"\n* Done: {OUT} ({size:.1f} MB, {TOTAL_S}s)")

    # Print automation profile for reference
    print("\nAutomation peaks:")
    for name, arr in [("Kick", KICK_AMP), ("Acid cut", ACID_CUT), ("Pad level", PAD_LEVEL)]:
        print(f"  {name}: min={arr.min():.2f} max={arr.max():.2f}")

if __name__ == "__main__":
    main()
