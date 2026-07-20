#!/usr/bin/env python3
"""
render_dark_matter.py — "Dark Matter"
12 minutes. 138 BPM. D minor. Underground.

Architecture:
  - Every layer is a full 12-min buffer.
  - All section envelopes: cosine crossfade 8 bars (~13.9s).
  - No hard cuts anywhere. Elements never enter/exit simultaneously.
  - Drum velocity ramps over 4-8 bars when entering/leaving.
  - No peak >1.0 before master. Explicit headroom on every layer.
  - Beat patterns: hard-coded 16-step per section, switch is gradual.

Journey (8 acts):
  Void        0:00-2:00   cosmic ambience only, sub drone
  Emergence   2:00-3:30   +sub bass, kick fades in from nothing
  Prime       3:30-5:00   full hard techno: 4/4 kick, tight 16th hats, acid
  Collapse    5:00-6:00   stripped breakdown — pad + rumble + half-time kick
  Shift       6:00-7:30   breakbeat pattern materializes, heavier sub
  Hard Core   7:30-10:00  peak: hard techno + breakbeat layered, super-saw
  Dissipation 10:00-11:00 energy decays, reverb tails dominate
  Return      11:00-12:00 ambient void, echoes
"""

import sys, os, logging, numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt
sys.path.insert(0, "/opt/autodj-mixer")

from autodj.generate.synth909 import render_drums, drum_hit, normalize
from autodj.generate.synthcore import (
    midi_to_hz, sawtooth_bl, square_bl, supersaw, sine_wave,
    adsr, lpf, hpf, lpf_sweep,
    acid_bass_note, pad_note,
    apply_reverb, apply_delay, apply_compressor,
    make_section_envelope, mono_to_stereo, master_chain,
    normalize_master, _wavetable_osc
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("dark_matter")

SR     = 44100
BPM    = 138.0
DUR    = 720.0        # 12:00
BAR_S  = 60 / BPM * 4
BEAT_S = 60 / BPM
STEP_S = BAR_S / 16
TOTAL  = int(DUR * SR)

# ---------------------------------------------------------------------------
# Act boundaries (seconds)
# ---------------------------------------------------------------------------
A_VOID    = (0.0,    120.0)
A_EMERGE  = (108.0,  210.0)   # overlaps Void 12s
A_PRIME   = (198.0,  300.0)   # overlaps Emerge 12s
A_COLLAPSE= (290.0,  360.0)
A_SHIFT   = (350.0,  450.0)   # overlaps Collapse 10s
A_HARD    = (438.0,  600.0)   # overlaps Shift 12s
A_DISSIP  = (590.0,  660.0)
A_RETURN  = (650.0,  720.0)

def in_act(t, act):
    return act[0] <= t < act[1]

def act_progress(t, act):
    """0.0 at start of act, 1.0 at end."""
    return np.clip((t - act[0]) / (act[1] - act[0]), 0, 1)

# Dm scale MIDI
CHORD_PROG = [
    [50, 53, 57],   # Dm  D3 F3 A3
    [43, 47, 50],   # Gm  G2 B2 D3
    [46, 50, 53],   # Bb  Bb2 D3 F3
    [40, 44, 47],   # Am  A2 C3 E3
]

# Acid sequences (D minor flavour)
ACID_A = [50,0,50,0, 53,52,50,0, 48,0,50,0, 55,0,53,50]
ACID_B = [50,0,48,0, 46,0,48,50, 52,0,50,0, 53,0,52,50]


# ---------------------------------------------------------------------------
# DRUM PATTERNS (16-step, True/False mask)
# velocity: 0-127 per step, 0 = rest
# ---------------------------------------------------------------------------
def mk_pat(kick, snare, hat_c, hat_o=None, clap=None):
    if hat_o is None:  hat_o  = [0]*16
    if clap  is None:  clap   = [0]*16
    return dict(kick=kick, snare=snare, hat_c=hat_c, hat_o=hat_o, clap=clap)

# 4/4 hard techno (acts: Prime, Hard Core)
PAT_TECHNO = mk_pat(
    kick  = [127,0,0,0, 127,0,0,0, 127,0,0,0, 127,0,0,0],
    snare = [0,0,0,0,   100,0,0,0, 0,0,0,0,   100,0,0,0],
    hat_c = [80,0,80,0, 80,0,80,0, 80,0,80,0, 80,0,80,0],
    hat_o = [0,0,0,0,   0,0,0,95,  0,0,0,0,   0,0,0,95],
)

# Breakbeat (act: Shift, Hard Core overlay)
# Amen-inspired — kick on 1, 3-and; snare on 2, 4-and, 4-ee
PAT_BREAK = mk_pat(
    kick  = [127,0,0,0, 0,0,0,0,  110,0,0,90, 0,0,0,0],
    snare = [0,0,0,0,   100,0,0,0, 0,0,0,0,   95,0,80,0],
    hat_c = [90,90,90,90,90,90,90,90,90,90,90,90,90,90,90,90],
    hat_o = [0,0,0,0,   0,0,0,90,  0,0,0,0,   0,0,0,90],
    clap  = [0,0,0,0,   80,0,0,0,  0,0,0,0,   80,0,0,0],
)

# Half-time (Collapse)
PAT_HALF = mk_pat(
    kick  = [100,0,0,0, 0,0,0,0,  0,0,0,0,   0,0,0,0],
    snare = [0,0,0,0,   0,0,0,0,  90,0,0,0,  0,0,0,0],
    hat_c = [60,0,0,0,  60,0,0,0, 60,0,0,0,  60,0,0,0],
)

# Hybrid: techno kick + breakbeat rhythm (peak of Hard Core)
PAT_HYBRID = mk_pat(
    kick  = [127,0,0,0, 0,0,0,0,  127,0,0,90, 0,0,0,0],
    snare = [0,0,0,0,   110,0,0,0, 0,0,0,0,   100,0,90,0],
    hat_c = [90,90,90,90,90,90,90,90,90,90,90,90,90,90,90,90],
    hat_o = [0,0,0,0,   0,0,0,90,  0,0,0,0,   0,0,0,95],
    clap  = [0,0,0,0,   90,0,0,0,  0,0,0,0,   90,0,0,0],
)


def pat_at(t):
    """Return drum pattern and velocity scale for time t."""
    if in_act(t, A_VOID):
        return None, 0.0
    if in_act(t, A_EMERGE):
        p = act_progress(t, A_EMERGE)
        # Kick only, velocity ramps from 0 to 60
        pat = mk_pat(
            kick  = [80,0,0,0]*4,
            snare = [0]*16,
            hat_c = [0]*16,
        )
        return pat, p * 0.5
    if in_act(t, A_PRIME):
        p = act_progress(t, A_PRIME)
        return PAT_TECHNO, min(1.0, p * 1.5) * 0.9
    if in_act(t, A_COLLAPSE):
        p = act_progress(t, A_COLLAPSE)
        return PAT_HALF, 0.6 - p * 0.2
    if in_act(t, A_SHIFT):
        p = act_progress(t, A_SHIFT)
        return PAT_BREAK, 0.5 + p * 0.4
    if in_act(t, A_HARD):
        p = act_progress(t, A_HARD)
        # First 30s: techno, then blend into hybrid
        if p < 0.2:
            return PAT_TECHNO, 0.9 + p
        else:
            return PAT_HYBRID, 1.0
    if in_act(t, A_DISSIP):
        p = act_progress(t, A_DISSIP)
        return PAT_TECHNO, max(0, 1.0 - p * 1.2)
    # Return
    return None, 0.0


# ---------------------------------------------------------------------------
# 1. DRUMS
# ---------------------------------------------------------------------------
def build_drum_events():
    events = []
    total_steps = int(DUR / STEP_S) + 4
    NAME_ORDER = ["kick", "snare", "hat_c", "hat_o", "clap"]

    for step in range(total_steps):
        t = step * STEP_S
        if t >= DUR:
            break
        step_in_bar = step % 16

        pat, vel_scale = pat_at(t)
        if pat is None or vel_scale < 0.01:
            continue

        for inst in NAME_ORDER:
            base_vel = pat.get(inst, [0]*16)[step_in_bar]
            if base_vel == 0:
                continue
            final_vel = int(base_vel * vel_scale)
            if final_vel < 5:
                continue
            events.append((t, inst, final_vel))

    return events


# ---------------------------------------------------------------------------
# Distorted kick (for Hard Core section) — synthesize separately
# ---------------------------------------------------------------------------
def make_hard_kick(sr=SR):
    """Heavy 808-style sub kick: sine sweep + saturation, longer decay."""
    from autodj.generate.synth909 import kick_909
    k = kick_909(sr, decay_ms=750, start_hz=130, end_hz=38, punch=3.5)
    # Saturation for hardstyle punch
    k = np.tanh(k * 2.5) / 1.5
    return normalize(k)


def build_hard_kick_events():
    """Extra distorted kick only in Hard Core (stacked on 909 kick)."""
    events = []
    total_beats = int(DUR / BEAT_S) + 2
    for beat in range(total_beats):
        t = beat * BEAT_S
        if not in_act(t, A_HARD):
            continue
        p = act_progress(t, A_HARD)
        # Hard kick enters gradually in first 30s of Hard Core
        vel = int(max(0, min(100, (p - 0.15) / 0.15 * 80)))
        if vel > 10:
            events.append((t, vel))
    return events


def render_hard_kicks(events, total_samples, sr=SR):
    sample = make_hard_kick(sr)
    buf = np.zeros(total_samples, dtype=np.float32)
    for (t_s, vel) in events:
        start = int(t_s * sr)
        gain = (vel / 100.0) ** 1.3
        end = min(start + len(sample), total_samples)
        n = end - start
        if n > 0:
            buf[start:end] += sample[:n] * gain
    return buf


# ---------------------------------------------------------------------------
# 2. SUB BASS (sidechain-ducked)
# ---------------------------------------------------------------------------
def build_sub_bass(drum_events):
    log.info("  Sub bass...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    active_secs = [
        (A_EMERGE[0],  A_VOID[1],   0.6),   # entering with emerge
        (A_VOID[1],    A_DISSIP[1], 1.0),
        (A_DISSIP[0],  A_RETURN[1], 0.4),
    ]
    sec_env = make_section_envelope(TOTAL, active_secs, SR, crossfade_bars=8, bpm=BPM)

    bar_count = int(DUR / BAR_S) + 2
    for bar in range(bar_count):
        t_bar = bar * BAR_S
        if t_bar >= DUR:
            break
        chord = CHORD_PROG[bar % len(CHORD_PROG)]
        root = chord[0]

        # Hard Core: add octave unison sub for depth
        sub_note = root - 12
        freq = midi_to_hz(sub_note)

        n_note = int(BAR_S * 0.95 * SR)
        t_arr = np.arange(n_note, dtype=np.float64) / SR
        tone = np.sin(2 * np.pi * freq * t_arr)
        env = adsr(3, 60, -2, 40, BAR_S * 0.95, SR)
        tone = (tone * env).astype(np.float32)

        start = int(t_bar * SR)
        end = min(start + n_note, TOTAL)
        buf[start:end] += tone[:end - start]

    buf *= sec_env

    # Sidechain: kick ducks sub
    for ev in drum_events:
        if ev[1] == "kick":
            s = int(ev[0] * SR)
            r_s = int(0.10 * SR)
            end = min(s + r_s, TOTAL)
            n = end - s
            if n > 0:
                recovery = 0.1 + 0.9 * 0.5 * (1 - np.cos(np.pi * np.arange(n) / n))
                buf[s:end] *= recovery.astype(np.float32)

    stereo = mono_to_stereo(buf, pan=0.0)
    return apply_compressor(stereo, SR, threshold_db=-6, ratio=8, attack_ms=2, release_ms=60)


# ---------------------------------------------------------------------------
# 3. ACID BASS 303
# ---------------------------------------------------------------------------
def build_acid_bass():
    log.info("  Acid bass...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    active_secs = [
        (A_PRIME[0],    A_COLLAPSE[0], 1.0),
        (A_SHIFT[0],    A_DISSIP[0],   1.0),
    ]
    sec_env = make_section_envelope(TOTAL, active_secs, SR, crossfade_bars=8, bpm=BPM)

    def cutoff_at(t):
        if in_act(t, A_PRIME):
            p = act_progress(t, A_PRIME)
            return 300 + p * 1400
        if in_act(t, A_HARD):
            return 2000
        return 800

    total_steps = int(DUR / STEP_S) + 4
    prev = None
    seq_len = len(ACID_A)

    for step in range(total_steps):
        t = step * STEP_S
        if t >= DUR:
            break
        s_idx = min(int(t * SR), TOTAL - 1)
        if sec_env[s_idx] < 0.01:
            continue

        # Choose sequence by act
        seq = ACID_B if (in_act(t, A_SHIFT) or in_act(t, A_HARD)) else ACID_A
        note = seq[step % seq_len]
        if note == 0:
            continue

        cutoff = cutoff_at(t)
        accent = (step % 8 == 0)
        dur = STEP_S * 0.85
        tone = acid_bass_note(note, dur, SR,
                              cutoff_start=cutoff * 2.0,
                              cutoff_end=cutoff * 0.3,
                              accent=accent)
        gain = sec_env[s_idx]
        start = int(t * SR)
        end = min(start + len(tone), TOTAL)
        buf[start:end] += tone[:end - start] * gain
        prev = note

    buf = np.tanh(buf * 1.4) / 1.4
    stereo = mono_to_stereo(buf, pan=-0.08)
    return apply_compressor(stereo, SR, threshold_db=-8, ratio=4, attack_ms=3, release_ms=50)


# ---------------------------------------------------------------------------
# 4. DARK PAD (supersaw, hall reverb)
# ---------------------------------------------------------------------------
def build_dark_pad():
    log.info("  Dark pad...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    active_secs = [
        (0.0,           A_COLLAPSE[0], 1.0),
        (A_COLLAPSE[0], A_SHIFT[1],    0.8),
        (A_DISSIP[0],   DUR,           0.7),
    ]
    sec_env = make_section_envelope(TOTAL, active_secs, SR, crossfade_bars=8, bpm=BPM)

    chord_dur = BAR_S * 2 * 0.98
    n_chords = int(DUR / (BAR_S * 2)) + 2

    for i in range(n_chords):
        t_c = i * BAR_S * 2
        if t_c >= DUR:
            break
        chord = CHORD_PROG[i % len(CHORD_PROG)]
        n_s = int(chord_dur * SR)
        chord_buf = np.zeros(n_s, dtype=np.float32)

        # In Hard Core: brighter, more detuned supersaw
        if in_act(t_c, A_HARD):
            detune = 20.0
            cutoff = 3500
            attack = 400
        elif in_act(t_c, A_SHIFT):
            detune = 16.0
            cutoff = 2500
            attack = 800
        else:
            detune = 12.0
            cutoff = 1800
            attack = 1400

        for note in chord:
            voice = pad_note(note, chord_dur, SR,
                             attack_ms=attack, cutoff_hz=cutoff,
                             detune_cents=detune, n_voices=7)
            chord_buf[:len(voice)] += voice[:n_s]

        peak = np.abs(chord_buf).max()
        if peak > 0:
            chord_buf *= 0.6 / peak

        start = int(t_c * SR)
        end = min(start + n_s, TOTAL)
        buf[start:end] += chord_buf[:end - start]

    buf *= sec_env
    stereo = mono_to_stereo(buf, pan=0.0)
    stereo = apply_reverb(stereo, SR, room_size=0.85, wet=0.45, damping=0.25)
    return stereo


# ---------------------------------------------------------------------------
# 5. LEAD / MELODIC ARP (dark, no pop melody — minor intervals, dissonant)
# ---------------------------------------------------------------------------
def build_lead():
    log.info("  Lead arp...")
    buf = np.zeros(TOTAL, dtype=np.float32)

    # Active only in Prime and Hard Core
    active_secs = [
        (A_PRIME[0] + 20,  A_COLLAPSE[0], 1.0),
        (A_HARD[0] + 16,   A_DISSIP[0],   1.0),
    ]
    sec_env = make_section_envelope(TOTAL, active_secs, SR, crossfade_bars=6, bpm=BPM)

    # Dark, underground pattern — no "melody", more like a Dm modal riff
    # Uses dim/tritone intervals = dark/tense feel
    RIFF = [50, 53, 50, 57, 55, 52, 50, 48,   # D3 F3 D3 A3 G3 E3 D3 C3
            50, 53, 55, 57, 60, 57, 55, 52]    # ascending→descending

    step_dur = BEAT_S * 0.5  # 8th notes
    total_steps = int(DUR / step_dur) + 4

    for step in range(total_steps):
        t = step * step_dur
        if t >= DUR:
            break
        s_idx = min(int(t * SR), TOTAL - 1)
        g = sec_env[s_idx]
        if g < 0.01:
            continue

        note = RIFF[step % len(RIFF)]
        # Shift up octave in Hard Core for intensity
        if in_act(t, A_HARD):
            note += 12

        freq = midi_to_hz(note)
        dur_s = step_dur * 0.65
        n = int(dur_s * SR)

        osc = _wavetable_osc(freq, n, SR, "square")
        # Anti-alias
        cutoff = min(freq * 6, 8000)
        osc = lpf(osc, cutoff, sr=SR)
        env = adsr(2, 50, -6, 15, dur_s, SR)
        tone = (osc * env * g).astype(np.float32)

        start = int(t * SR)
        end = min(start + n, TOTAL)
        buf[start:end] += tone[:end - start]

    delay_ms = BEAT_S * 1000 * 0.5
    stereo = mono_to_stereo(buf, pan=0.2)
    stereo = apply_delay(stereo, SR, delay_ms=delay_ms, feedback=0.35, wet=0.25)
    stereo = apply_reverb(stereo, SR, room_size=0.45, wet=0.2)
    return stereo


# ---------------------------------------------------------------------------
# 6. COSMIC TEXTURE + WIND (stereo rotation, slow LFOs)
# ---------------------------------------------------------------------------
def build_cosmic_texture():
    log.info("  Cosmic texture...")
    n = TOTAL
    t_arr = np.arange(n, dtype=np.float64) / SR

    # Sub-low rumble
    noise1 = np.random.randn(n).astype(np.float32)
    sos_lo = butter(4, [25, 90], btype='bandpass', fs=SR, output='sos')
    rumble = sosfilt(sos_lo, noise1).astype(np.float32)

    # D1 drone
    df = midi_to_hz(26)
    drone = (0.22 * np.sin(2*np.pi*df*t_arr) +
             0.10 * np.sin(2*np.pi*df*2*t_arr) +
             0.05 * np.sin(2*np.pi*df*3*t_arr)).astype(np.float32)

    # Wind — organic LFO amplitude modulation
    noise_w = np.random.randn(n).astype(np.float32)
    sos_w = butter(4, [60, 500], btype='bandpass', fs=SR, output='sos')
    wind_raw = sosfilt(sos_w, noise_w).astype(np.float32)
    wind_env = np.zeros(n, dtype=np.float32)
    for period_s, amp, off_s in [(22.0,0.7,0), (13.0,0.5,8), (31.0,0.4,4), (17.0,0.35,25)]:
        lfo = 0.5 * (1 - np.cos(2*np.pi*(t_arr - off_s) / period_s))
        wind_env += amp * np.clip(lfo, 0, 1).astype(np.float32)
    wind_env = np.clip(wind_env / wind_env.max(), 0, 1)
    wind = wind_raw * wind_env * 0.45

    # High shimmer
    noise_h = np.random.randn(n).astype(np.float32)
    hi_cut = min(12000, SR//2-100)
    sos_h = butter(4, [5000, hi_cut], btype='bandpass', fs=SR, output='sos')
    stars = sosfilt(sos_h, noise_h).astype(np.float32)
    stars_lfo = (0.5 + 0.5 * np.sin(2*np.pi*t_arr/9.1)).astype(np.float32)
    stars *= stars_lfo * 0.05

    # In Hard Core: add high-frequency metallic texture
    noise_m = np.random.randn(n).astype(np.float32)
    sos_m = butter(4, [3000, min(8000, SR//2-100)], btype='bandpass', fs=SR, output='sos')
    metal = sosfilt(sos_m, noise_m).astype(np.float32)
    metal_env = make_section_envelope(TOTAL, [(A_HARD[0], A_HARD[1], 1.0)],
                                      SR, crossfade_bars=12, bpm=BPM)
    metal *= metal_env * 0.08

    mono = (rumble * 0.25 + drone * 0.35 + wind * 0.50 + stars + metal).astype(np.float32)

    # Global envelope: 20s fade in, 20s fade out
    global_env = np.ones(n, dtype=np.float32)
    fi = int(20 * SR)
    global_env[:fi] = 0.5 * (1 - np.cos(np.pi * np.arange(fi) / fi))
    fo = int(20 * SR)
    global_env[-fo:] = 0.5 * (1 + np.cos(np.pi * np.arange(fo) / fo))
    mono *= global_env

    # Stereo rotation: pan sweeps R→L period 28s
    pan_lfo = np.sin(2*np.pi*t_arr / 28.0).astype(np.float32)
    pan_l = np.sqrt(0.5 * (1 - pan_lfo))
    pan_r = np.sqrt(0.5 * (1 + pan_lfo))
    stereo = np.stack([mono * pan_l, mono * pan_r], axis=1).astype(np.float32)
    stereo = apply_reverb(stereo, SR, room_size=0.95, wet=0.55, damping=0.10)
    return stereo


# ---------------------------------------------------------------------------
# 7. RISERS + DOWNLIFTERS (smooth cosine envelopes)
# ---------------------------------------------------------------------------
def build_risers():
    buf = np.zeros((TOTAL, 2), dtype=np.float32)

    transitions = [
        (A_PRIME[0],    "up",   5.0),  # before Prime
        (A_COLLAPSE[0], "down", 4.0),  # into Collapse
        (A_SHIFT[0],    "up",   5.0),  # before Shift
        (A_HARD[0],     "up",   6.0),  # before Hard Core — bigger
        (A_DISSIP[0],   "down", 6.0),  # into Dissipation
    ]

    for (t_center, direction, dur) in transitions:
        n_r = int(dur * SR)
        t_start = t_center - dur if direction == "up" else t_center

        if t_start < 0:
            t_start = 0
        if t_start >= DUR:
            continue

        noise = np.random.randn(n_r).astype(np.float32)

        if direction == "up":
            f_start, f_end = 80, 9000
        else:
            f_start, f_end = 9000, 60

        seg = 60
        seg_len = n_r // seg
        swept = np.zeros(n_r, dtype=np.float32)
        for i in range(seg):
            p = i / seg
            c = float(f_start * (f_end / f_start) ** p)
            c = max(20.0, min(float(SR//2 - 100), c))
            sos = butter(4, c, btype='lowpass', fs=SR, output='sos')
            s, e = i*seg_len, (i+1)*seg_len if i < seg-1 else n_r
            swept[s:e] = sosfilt(sos, noise[s:e])

        t_norm = np.arange(n_r, dtype=np.float32) / n_r
        if direction == "up":
            amp_env = 0.5 * (1 - np.cos(np.pi * t_norm))
        else:
            amp_env = 0.5 * (1 + np.cos(np.pi * t_norm))
        swept *= amp_env

        # Stereo: slight L/R offset
        s_start = int(t_start * SR)
        s_end = min(s_start + n_r, TOTAL)
        sn = s_end - s_start
        buf[s_start:s_end, 0] += swept[:sn] * 0.9
        buf[s_start:s_end, 1] += swept[:sn] * 1.0

    return buf


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    log.info(f"Dark Matter | BPM={BPM} | Dm | {DUR:.0f}s (12:00)")

    log.info("Building drum events...")
    drum_events = build_drum_events()
    log.info(f"  {len(drum_events)} drum hits")

    log.info("Rendering 909 drums...")
    drum_buf = render_drums(drum_events, TOTAL, SR, stereo=True)
    peak = np.abs(drum_buf).max()
    if peak > 0:
        drum_buf *= 0.75 / peak
    log.info(f"  drums peak={np.abs(drum_buf).max():.3f}")

    log.info("Rendering hard kicks (distorted)...")
    hk_events = build_hard_kick_events()
    hk_mono = render_hard_kicks(hk_events, TOTAL, SR)
    hk_peak = np.abs(hk_mono).max()
    if hk_peak > 0:
        hk_mono *= 0.55 / hk_peak
    hk_buf = mono_to_stereo(hk_mono * 0.7, pan=0.0)
    log.info(f"  hard kick peak={np.abs(hk_buf).max():.3f}")

    log.info("Compressing drums...")
    drum_buf = apply_compressor(drum_buf, SR, threshold_db=-8, ratio=4, attack_ms=2, release_ms=80)

    sub_buf  = build_sub_bass(drum_events)
    acid_buf = build_acid_bass()
    pad_buf  = build_dark_pad()
    lead_buf = build_lead()
    tex_buf  = build_cosmic_texture()
    riser_buf= build_risers()

    def trim(b, n=TOTAL):
        if len(b) >= n:
            return b[:n]
        return np.pad(b, ((0, n - len(b)), (0, 0)))

    # --- MIX with headroom ---
    log.info("Mixing...")
    mix = np.zeros((TOTAL, 2), dtype=np.float32)
    mix += trim(drum_buf)  * 0.80
    mix += trim(hk_buf)    * 0.65
    mix += trim(sub_buf)   * 0.65
    mix += trim(acid_buf)  * 0.50
    mix += trim(pad_buf)   * 0.45
    mix += trim(lead_buf)  * 0.40
    mix += trim(tex_buf)   * 0.18
    mix += trim(riser_buf) * 0.55

    # Global fade-in 3s, fade-out 5s
    fi = int(3 * SR)
    fo = int(5 * SR)
    fi_env = 0.5 * (1 - np.cos(np.pi * np.arange(fi) / fi)).astype(np.float32)
    fo_env = 0.5 * (1 + np.cos(np.pi * np.arange(fo) / fo)).astype(np.float32)
    mix[:fi, 0] *= fi_env; mix[:fi, 1] *= fi_env
    mix[-fo:, 0] *= fo_env; mix[-fo:, 1] *= fo_env

    # --- MASTER ---
    log.info("Mastering...")
    # Safety clip before master chain
    mix = np.clip(mix, -3.0, 3.0)
    mix = master_chain(mix, SR)

    if not np.isfinite(mix).all():
        mix = np.nan_to_num(mix, nan=0.0, posinf=1.0, neginf=-1.0)

    out_wav = "/tmp/dark_matter.wav"
    out_mp3 = "/tmp/dark_matter.mp3"
    log.info(f"Writing {out_wav}...")
    sf.write(out_wav, mix, SR)
    log.info("Converting to MP3 320k...")
    os.system(f'ffmpeg -y -i "{out_wav}" -b:a 320k "{out_mp3}" 2>/dev/null')

    size_mb = os.path.getsize(out_mp3) / 1024**2
    log.info(f"Done: {out_mp3} ({size_mb:.1f} MB)")
    return out_mp3


if __name__ == "__main__":
    mp3 = main()
    print(f"\nOutput: {mp3}")
