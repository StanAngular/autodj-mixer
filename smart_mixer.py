#!/usr/bin/env python3
"""
Smart Mixer v14 (Dynamic CF_BARS + Downbeat Snap + EQ Sweep + Dynamic Crossover)
Combines v7 argparse/track-loading with v13 algorithm improvements and Gemini-spec Phase 1-3:
  - --cf-bars arg (auto/int) for dynamic crossfade length
  - Downbeat snapping to 4-bar phrase grid
  - EQ Sweep bass swap (HPF/LPF IIR) replaces binary bass swap
  - Dynamic crossover frequency analysis

Usage:
  python3 smart_mixer.py --wav-dir ./wav --ann-dir ./annotations --output mix.mp3

Or configure via a Python config file:
  python3 smart_mixer.py --config mix_config.py
"""

import sys, os, time, subprocess, argparse, json
from datetime import datetime

import numpy as np
np.float = np.float64
np.int = np.int64
np.complex = np.complex128
np.bool = np.bool_

import soundfile as sf
import scipy.signal as signal
import pyrubberband as pyrb
import librosa
import pyloudnorm as pyln

# Ensure rubberband is in PATH
os.environ['PATH'] = '/tmp/rubberband-extract/usr/bin:' + os.environ.get('PATH', '')

SR = 44100
CF_BARS = 16                # Default crossfade duration in bars (overridable via --cf-bars)
RAMP_SEC = 15               # Post-crossfade BPM ramp-back duration (seconds)
RAMP_MIN_RMS = 0.08         # If entry RMS below this, volume-only fade instead of BPM ramp
TAIL_FADE_BARS = 0          # Redundant with seamless blend→ramp (17th bar warp bridge)
TARGET_LUFS = -14.0         # Loudness normalization target
BPM_DIFF_LIMIT = 0.08       # Max BPM difference ratio for crossfade (8%)
SWAP_BARS = 2               # Bass swap transition width in bars (used by old hpss mode)
PHRASE_GRID = 4             # Downbeat snapping grid (4-bar = 1 phrase)
MIN_PLAY_FRACTION = 0.70    # Track must play at least 70% before exit — no chopping
DRUM_SEARCH_LIMIT = 32      # Max bars to search forward for drum activity

# ============================================================
# Metadata & Genre Hints
# ============================================================


def search_track_genre(artist, title, yt_metadata_dir=None):
    """
    Determine track density/vocal-hint from available metadata.

    Priority:
      1. yt-dlp metadata JSON (if --yt-metadata-dir provided).
         Extracts 'genre', 'tags', 'description' for keyword matching.
      2. Keyword matching on artist/title (fast, no IO).

    Returns dict with keys:
      'vocal_hint': None | 'vocal' | 'instrumental'
      'density': None | 'dense' | 'sparse' | 'percussive'
    """
    result = {'vocal_hint': None, 'density': None}

    # Priority 1: yt-dlp metadata JSON
    if yt_metadata_dir and os.path.isdir(yt_metadata_dir):
        # Try: Artist_-_Title.info.json pattern (yt-dlp default naming with spaces→_-_)
        # Fallback: Artist_-_Title.json (compact naming)
        search_base = f"{artist} - {title}" if artist else title
        for root, dirs, files in os.walk(yt_metadata_dir):
            for fname in files:
                if fname.endswith(('.info.json', '.json')):
                    # Match base name loosely
                    if search_base.lower().replace(' ', '_') in fname.lower().replace(' ', '_'):
                        try:
                            with open(os.path.join(root, fname)) as f:
                                meta = json.load(f)
                            # Extract tags from yt-dlp metadata
                            tags = meta.get('tags', []) or []
                            genre_tag = meta.get('genre', '') or ''
                            desc = meta.get('description', '') or ''
                            combined = ' '.join(tags).lower() + ' ' + genre_tag.lower() + ' ' + desc.lower()
                            if any(kw in combined for kw in ['instrumental', 'inst', 'no vocals']):
                                result['vocal_hint'] = 'instrumental'
                                result['density'] = 'percussive'
                            elif any(kw in combined for kw in ['vocal', 'vocals', 'feat', 'lyric']):
                                result['vocal_hint'] = 'vocal'
                            if any(kw in combined for kw in ['dj mix', 'continuous', 'mix', 'extended']):
                                result['density'] = 'dense'
                            print(f"    ← yt-dlp metadata: vocal_hint={result['vocal_hint']}, density={result['density']}")
                            break
                        except (IOError, json.JSONDecodeError):
                            continue
            if result['vocal_hint'] is not None:
                break

    # Priority 2: keyword fallback on title
    if result['vocal_hint'] is None:
        query_lower = (f"{artist} {title}" if artist else title).lower()
        if any(kw in query_lower for kw in ['instrumental', 'inst', 'no vocal']):
            result['vocal_hint'] = 'instrumental'
            result['density'] = 'percussive'
        elif any(kw in query_lower for kw in ['vocal mix', 'club mix', 'extended mix', 'remix']):
            result['density'] = 'dense'
        # Electronic/instrumental genre keywords → force instrumental hint
        if result['vocal_hint'] is None:
            electronic_keywords = [
                'progressive', 'house', 'techno', 'melodic', 'trance',
                'deep house', 'tech house', 'minimal', 'dub', 'electronic',
                'dj mix', 'continuous mix', 'extended mix', 'club mix',
                'original mix', 'club', 'dub mix', 'mix',
            ]
            if any(kw in query_lower for kw in electronic_keywords):
                result['vocal_hint'] = 'instrumental'
                result['density'] = 'dense'
                print(f"    ← title keywords: electronic genre detected → instrumental")

    return result


def resolve_cf_bars(cf_arg, m_sec_label, s_sec_label, m_a1f_label=None, s_a1f_label=None,
                    default=16, has_a1f=False, m_genre_hint=None, s_genre_hint=None):
    """
    Resolve crossfade length in bars.

    cf_arg: 'auto' or int.
    When 'auto', picks length based on A1F labels (preferred) or VAD section labels:

      A1F mode (when m_a1f_label/s_a1f_label are available):
        Uses resolve_transition_params() which applies segment-based rules.

      VAD fallback (when no A1F):
        LONG:   QUIET→QUIET              → 16
        MEDIUM: QUIET/BUILD/ACTIVE→BUILD → 8
        DROP:   otherwise                 → 4

    CRITICAL RULE: When user passes a numeric --cf-bars (e.g. 16),
    that value is ABSOLUTE LAW — auto-profiles cannot override it.
    """
    if cf_arg != 'auto':
        try:
            return max(1, min(64, int(cf_arg)))
        except (ValueError, TypeError):
            return default

    # A1F mode (has actual A1F data)
    if m_a1f_label or s_a1f_label:
        tp = resolve_transition_params(m_a1f_label, s_a1f_label,
                                        has_a1f=has_a1f,
                                        m_genre_hint=m_genre_hint,
                                        s_genre_hint=s_genre_hint)
        return tp['cf_bars']

    # VAD fallback mode

    # VAD fallback mode — no STYLE_PROFILES, use pure segment-based defaults
    m = m_sec_label.upper() if m_sec_label else 'ACTIVE'
    s = s_sec_label.upper() if s_sec_label else 'ACTIVE'

    # Long blend: quiet→quiet
    if m in ('QUIET',) and s in ('QUIET',):
        return 16

    # Medium blend: active/build→build
    if m in ('QUIET', 'BUILD', 'ACTIVE') and s in ('BUILD',):
        return 8

    # Drop cut: everything else
    return 4


# ============================================================
# Key Detection + Camelot Wheel (from analyze_order.py)
# ============================================================

CAMELOT = {
    'C maj':'8B','C# maj':'3B','D maj':'10B','D# maj':'5B','E maj':'12B',
    'F maj':'7B','F# maj':'2B','G maj':'9B','G# maj':'4B','A maj':'11B',
    'A# maj':'6B','B maj':'1B',
    'C min':'5A','C# min':'12A','D min':'7A','D# min':'2A','E min':'9A',
    'F min':'4A','F# min':'11A','G min':'6A','G# min':'1A','A min':'8A',
    'A# min':'3A','B min':'10A',
}

KEYS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
MAJ_PROFILE = [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
MIN_PROFILE = [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]

def detect_key(audio_mono, sr):
    """Detect musical key via chroma CQT + Krumhansl-Schmuckler profiles."""
    chroma = librosa.feature.chroma_cqt(y=audio_mono, sr=sr)
    profile = chroma.mean(axis=1)
    best_corr = -1
    best_key = "?"
    for shift in range(12):
        rolled = np.roll(profile, -shift)
        cm = np.corrcoef(rolled, MAJ_PROFILE)[0, 1]
        cn = np.corrcoef(rolled, MIN_PROFILE)[0, 1]
        if cm > best_corr:
            best_corr = cm
            best_key = f"{KEYS[shift]} maj"
        if cn > best_corr:
            best_corr = cn
            best_key = f"{KEYS[shift]} min"
    return best_key

def camelot_code(key_str):
    """Convert key string to Camelot code (e.g. 'D maj' → '10B')."""
    return CAMELOT.get(key_str, '?')

def key_compat(k1, k2):
    """Camelot compatibility score: 1.0 (same), 0.9 (adjacent), 0.8 (relative), 0.3 (bad)."""
    c1 = camelot_code(k1)
    c2 = camelot_code(k2)
    if '?' in (c1, c2):
        return 0.5
    n1, t1 = int(c1[:-1]), c1[-1]
    n2, t2 = int(c2[:-1]), c2[-1]
    if c1 == c2:
        return 1.0
    if t1 == t2 and abs(n1 - n2) in (1, 11):
        return 0.9
    if n1 == n2 and t1 != t2:
        return 0.8
    return 0.3


def find_crossover(audio_m, audio_s, sr=SR, default_low=150, default_high=3000):
    """
    Analyze spectrum of both tracks in CF zone to pick optimal crossover frequencies.

    Returns (low_cut, high_cut) in Hz.
    low_cut: separates bass/kick from mids (typically 80-250Hz)
    high_cut: separates mids from highs (typically 2000-4000Hz)
    """
    def _best_low_cut(mono):
        """Find the bass→mid crossover by looking at spectral rolloff."""
        S = np.abs(librosa.stft(mono[:sr * 4], n_fft=2048, hop_length=512))  # 4 seconds
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        spec = S.mean(1)
        # Find the peak in sub-bass (40-100Hz) — that's the kick fundamental
        kick_band = (freqs >= 40) & (freqs <= 100)
        if kick_band.any():
            kick_peak_idx = np.argmax(spec * kick_band.astype(float))
            kick_freq = freqs[kick_peak_idx]
        else:
            kick_freq = 60.0
        # The optimal low cut is ~1.5-2 octaves above kick fundamental
        # This ensures kick harmonics are included, but not mud
        low_cut = min(250, max(80, kick_freq * 2.5))
        return low_cut

    def _best_high_cut(mono):
        """Find the mid→high crossover by looking at vocal range (1-4kHz)."""
        S = np.abs(librosa.stft(mono[:sr * 4], n_fft=2048, hop_length=512))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        spec = S.mean(1)
        # Find energy minimum between 1500-5000Hz (the gap between mids and highs)
        search_band = (freqs >= 1500) & (freqs <= 5000)
        if search_band.any():
            gap_idx = np.argmin(spec * search_band.astype(float))
            high_cut = max(2000, min(4500, freqs[gap_idx]))
        else:
            high_cut = 3000
        return high_cut

    mono_m = audio_m.mean(1) if audio_m.ndim > 1 else audio_m
    mono_s = audio_s.mean(1) if audio_s.ndim > 1 else audio_s

    l1 = _best_low_cut(mono_m)
    l2 = _best_low_cut(mono_s)
    low_cut = int(round((l1 + l2) / 2.0))  # average of both tracks
    low_cut = max(80, min(250, low_cut))

    h1 = _best_high_cut(mono_m)
    h2 = _best_high_cut(mono_s)
    high_cut = int(round((h1 + h2) / 2.0))
    high_cut = max(1500, min(5000, high_cut))

    if low_cut != default_low or high_cut != default_high:
        print(f"    Dynamic crossover: low={low_cut}Hz high={high_cut}Hz (was {default_low}/{default_high})")
    return low_cut, high_cut


def three_band_split(audio, low_cut, high_cut, sr):
    """
    Splits audio into Low, Mid, and High bands using sosfilt
    and 4th-order Linkwitz-Riley crossovers (minimum-phase, no pre-ringing).
    """
    nyq = 0.5 * sr
    sos_low = signal.butter(2, low_cut / nyq, btype='low', output='sos')
    sos_high = signal.butter(2, high_cut / nyq, btype='high', output='sos')

    low = np.zeros_like(audio, dtype=np.float32)
    high = np.zeros_like(audio, dtype=np.float32)

    for ch in range(audio.shape[1]):
        x = audio[:, ch].astype(np.float64)
        low[:, ch] = signal.sosfilt(sos_low, x).astype(np.float32)
        high[:, ch] = signal.sosfilt(sos_high, x).astype(np.float32)

    mid = audio - low - high
    return low, mid, high


# ============================================================
# Audio Helpers
# ============================================================

def load_stereo(path, sr=SR):
    """Load stereo WAV, convert mono to stereo, resample if needed."""
    data, file_sr = sf.read(path, always_2d=True)
    if data.shape[1] == 1:
        data = np.hstack([data, data])
    if file_sr != sr:
        tmp = f"/tmp/_rs_{os.path.basename(path)}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", str(sr), "-ac", "2", tmp],
            capture_output=True
        )
        data, _ = sf.read(tmp, always_2d=True)
        os.unlink(tmp)
    return data.astype("float32")


def norm_lufs(audio, target=TARGET_LUFS, sr=SR):
    """Loudness normalize to target LUFS using full audio."""
    meter = pyln.Meter(sr)
    loud = meter.integrated_loudness(audio.astype("float64"))
    if loud == float('-inf'):
        return audio
    n = pyln.normalize.loudness(audio.astype("float64"), loud, target).astype("float32")
    pk = np.max(np.abs(n))
    if pk > 0.99:
        n *= 0.99 / pk
    return n


def pt(a, n):
    """Pad or trim array to length n."""
    if len(a) >= n:
        return a[:n]
    sh = list(a.shape)
    sh[0] = n - len(a)
    return np.concatenate([a, np.zeros(sh, dtype=a.dtype)])


def bar_s(bpm):
    """Duration of one bar (4 beats) in seconds."""
    return 240.0 / bpm


def load_dbeats(ann_path, sr=SR):
    """Load downbeat positions from madmom annotation file."""
    beats = np.loadtxt(ann_path)
    return np.array([int(r[0] * sr) for r in beats if round(r[1]) == 1], dtype=int)


def calc_bpm(db, sr=SR):
    """Calculate BPM from downbeat array using IQR-based outlier rejection."""
    if len(db) < 4:
        return 120.0
    iv = np.diff(db.astype(float)) / sr
    iv = iv[iv > 0.3]
    if not len(iv):
        return 120.0
    p25, p75 = np.percentile(iv, [25, 75])
    ok = iv[(iv >= p25 - 1.5 * (p75 - p25)) & (iv <= p75 + 1.5 * (p75 - p25))]
    return 4 * 60.0 / np.mean(ok) if len(ok) else 120.0


def fix_ht(db, bpm):
    """
    Fix half-time (or double-time) BPM detection by checking beat-to-beat
    distance ratios against expected 4-beat-bar spacing.
    """
    if len(db) < 8:
        return db, bpm
    ns = int(db[8]) - int(db[4])
    if ns <= 0:
        return db, bpm
    ratio = ns / max(int(bar_s(bpm) * SR / 4), 1)

    if 1.9 < ratio < 2.1:
        # Half-time detected: skip every other downbeat to go from 1 every 2 beats → 1 per beat
        db = db[::2]
    elif 2.9 < ratio < 3.1:
        # Third-time detected
        db = db[::3]
    elif 0.45 < ratio < 0.55:
        # Double-time detected: insert a downbeat midway between each pair
        dl = []
        for d in db:
            dl.extend([d, d + (db[1] - db[0]) // 2])
        db = np.array(dl, dtype=int)

    return db, calc_bpm(db)


# ============================================================
# Structural Analysis
# ============================================================

def sections(audio, db, sr=SR, name=""):
    """Classify bars as QUIET/BUILD/ACTIVE/DROP based on RMS energy + bass ratio."""
    mono = audio.mean(1) if audio.ndim == 2 else audio
    n = len(db) - 1
    if n < 4:
        return [(0, n, "ACTIVE")]

    br = np.array([
        np.sqrt(np.mean(mono[db[i]:db[i+1]]**2))
        if db[i+1] > db[i] else 0.0 for i in range(n)
    ])

    b_low, a_low = signal.butter(2, 200.0 / (0.5 * sr), btype='low')
    mono_low = signal.filtfilt(b_low, a_low, mono)

    bl = np.array([
        np.sqrt(np.mean(mono_low[db[i]:db[i+1]]**2)) / (br[i] + 1e-12)
        if db[i+1] > db[i] else 0.0 for i in range(n)
    ])

    k = np.ones(4) / 4
    de = np.convolve(br, k, 'same') * np.convolve(bl, k, 'same')
    med = np.median(de[de > 0]) if np.any(de > 0) else 1e-12

    lb = [
        'DROP' if e > med * 1.2 else
        'ACTIVE' if e > med * 0.5 else
        'BUILD' if e > med * 0.2 else 'QUIET'
        for e in de
    ]

    sc = []
    cur = lb[0]
    s = 0
    for i in range(1, n):
        if lb[i] != cur:
            sc.append((s, i, cur))
            cur = lb[i]
            s = i
    sc.append((s, n, cur))

    # Merge short sections (<4 bars) into neighbors
    mg = []
    for s, e, l in sc:
        if mg and e - s < 4:
            mg[-1] = (mg[-1][0], e, mg[-1][2])
        else:
            mg.append((s, e, l))

    if name:
        for s, e, l in mg:
            t1 = db[s] / sr
            t2 = db[min(e, len(db) - 1)] / sr
            print(
                f"    {int(t1 // 60)}:{int(t1 % 60):02d}-"
                f"{int(t2 // 60)}:{int(t2 % 60):02d}  "
                f"bars {s:3d}-{e:3d} ({e-s:2d})  {l}"
            )
    return mg


def quiet_exit(secs):
    """Find a quiet/build section in the second half suitable for exit."""
    for s, e, l in secs:
        if l in ('QUIET', 'BUILD') and e - s >= 8:
            return s
    return None


def section_at_bar(secs, bar):
    """Return section label for a given bar index."""
    for s, e, l in secs:
        if s <= bar < e:
            return l
    return 'ACTIVE'


EXIT_SCORE = {'QUIET': 0, 'BUILD': 1, 'ACTIVE': 2, 'DROP': 3}


def snap_bar(bar, grid=4):
    """Snap bar index to nearest multiple of grid (phrase boundary)."""
    return round(bar / grid) * grid


# ============================================================
# A1F / OpenMIRLab Section Labels + Analysis
# ============================================================

A1F_PRIORITY = {
    'outro': 0, 'end': 0,      # highest — no vocals, steady beat
    'break': 1,                 # quiet break
    'intro': 2, 'start': 2,     # good for entry
    'inst': 2,                  # instrumental
    'verse': 3,                 # verse — has vocals usually
    'bridge': 3,                # bridge — may have vocals
    'chorus': 4,                # chorus — has vocals, not for exit
}


def load_a1f_track_data(wav_path, sr, a1f_dir=None, catalog_dir=None):
    """
    Load full A1F track analysis from JSON cache.

    Extracts: bpm, downbeats (sample positions), segments (start/end/label).

    Returns dict with keys 'bpm', 'downbeats', 'segments', 'bar_labels', 'source'
    or None if no JSON found.

    When 'downbeats' key exists in JSON, they are returned as sample positions
    and replace madmom downbeats as the master grid.
    'bar_labels' is derived by mapping each downbeat to its enclosing A1F segment.
    """
    base = os.path.splitext(os.path.basename(wav_path))[0]

    # Priority lookup: catalog → explicit a1f_dir → next to WAV → a1f_results subdir
    candidates = []
    if catalog_dir:
        candidates.append(os.path.join(catalog_dir, base + '.json'))
    if a1f_dir:
        candidates.append(os.path.join(a1f_dir, base + '.json'))
    wav_dir = os.path.dirname(wav_path)
    candidates.extend([
        os.path.join(wav_dir, base + '.json'),
        os.path.join(wav_dir, 'a1f_results', base + '.json'),
        os.path.join(wav_dir, 'a1f_results_full', base + '.json'),
    ])

    a1f_path = None
    for c in candidates:
        if os.path.exists(c):
            a1f_path = c
            break

    if a1f_path is None:
        return None

    try:
        with open(a1f_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    result = {'source': a1f_path}

    # BPM
    result['bpm'] = data.get('bpm')

    # Downbeats — convert seconds → sample positions
    raw_downbeats = data.get('downbeats', [])
    if raw_downbeats:
        result['downbeats'] = np.array([int(t * sr) for t in raw_downbeats], dtype=int)
    else:
        result['downbeats'] = None

    # Segments (start_sec, end_sec, label)
    raw_segments = data.get('segments', [])
    result['segments'] = raw_segments if raw_segments else None

    # Bar labels: map each downbeat to its segment label
    if result['downbeats'] is not None and result['segments']:
        labels = []
        for db_samp in result['downbeats']:
            t = db_samp / sr
            label = None
            for seg in result['segments']:
                if seg['start'] <= t < seg['end']:
                    label = seg['label']
                    break
            labels.append(label or 'verse')
        result['bar_labels'] = labels
    else:
        result['bar_labels'] = None

    # Vocal density: ratio of segments with vocal content
    if result['segments']:
        vocal_labels = ('verse', 'chorus', 'bridge')
        n_vocal = sum(1 for s in result['segments'] if s.get('label', '') in vocal_labels)
        result['vocal_density'] = n_vocal / max(len(result['segments']), 1)
    else:
        result['vocal_density'] = None

    # ── Extended A1F fields (v16.3.2+) ─────────────────────────────
    # Vocal intervals (from A1F JSON)
    result['vocal_intervals'] = data.get('vocal_intervals', [])

    # Beats — full grid (all beats, not just downbeats)
    raw_beats = data.get('beats', [])
    if raw_beats:
        result['beats'] = np.array([int(t * sr) for t in raw_beats], dtype=int)
    else:
        result['beats'] = None

    # Musical key + Camelot (computed by enrich_metadata.py)
    result['key_a1f'] = data.get('key')
    result['camelot_a1f'] = data.get('camelot')

    # ── Meta passport (.meta.json) ─────────────────────────────────
    meta_dir = os.path.dirname(a1f_path)
    meta_path = os.path.join(meta_dir, base + '.meta.json')
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as _mf:
                result['meta'] = json.load(_mf)
        except (IOError, json.JSONDecodeError):
            result['meta'] = None
    else:
        result['meta'] = None

    return result


def run_a1f_analysis(wav_path, cache_dir, timeout=600):
    """
    Launch allin1fix.cli for a single track, CPU-optimized (skip Demucs separation).

    Only runs if no A1F JSON already exists in cache_dir.
    Uses --skip-separation to avoid the heavy Demucs stem split (5-10x faster).
    Returns True if JSON was produced, False otherwise.
    """
    base = os.path.splitext(os.path.basename(wav_path))[0]
    out_path = os.path.join(cache_dir, base + '.json')
    if os.path.exists(out_path):
        return True  # already cached

    a1f_venv = os.path.expanduser('~/ai-tools/all-in-one-fix/venv/bin/python')
    if not os.path.exists(a1f_venv):
        print(f"    ⚠ A1F venv not found at {a1f_venv}")
        return False

    os.makedirs(cache_dir, exist_ok=True)
    try:
        r = subprocess.run(
            [a1f_venv, '-m', 'allin1fix.cli', wav_path,
             '-o', cache_dir, '--overwrite', '--skip-separation'],
            capture_output=True, text=True, timeout=timeout
        )
        if r.returncode == 0 and os.path.exists(out_path):
            print(f"    ✓ A1F analysis complete: {base}")
            return True
        else:
            print(f"    ⚠ A1F analysis failed (exit={r.returncode}): {r.stderr[-200:]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"    ⚠ A1F analysis timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"    ⚠ A1F launch error: {e}")
        return False


def resolve_transition_params(m_a1f_label, s_a1f_label,
                               m_vocal_density=None, s_vocal_density=None,
                               has_a1f=True,
                               m_genre_hint=None, s_genre_hint=None):
    """
    Universal transition parameter resolver.

    MODE 1 — A1F mode (has_a1f=True, default):
      Segment-intersection rules based on A1F labels:
        - LONG BLEND:  outro→intro/inst        → 16b, smooth_eq, notch=-3.5
        - MEDIUM BLEND: outro/break→verse/bridge → 8b, smooth_eq, notch=-5.0
        - SHORT CUT:   chorus/verse→intro/inst  → 4b, stepped, notch=-5.0
        - DROP CUT:    anything→chorus/verse    → 4b, stepped, notch=-5.0
        - DEFAULT:                               8b, smooth_eq, notch=-3.0

    MODE 2 — Fallback mode (has_a1f=False):
      Uses search_track_genre() hints instead of blind defaults.
      If genre_hint indicates electronic/instrumental/dense:
        → 16b, smooth_eq, notch=-3.5  (🎯 house_tech fallback)
      Otherwise:
        → 8b, smooth_eq, notch=-3.0

    Vocal density overrides: if m_vocal_density > 0.5 or s_vocal_density > 0.5,
    notch_db is made 1dB more aggressive (max -6.0).
    """
    # ── Mode 2: Fallback (no A1F data) ──────────────────────────────
    if not has_a1f:
        # Check genre hints from search_track_genre() + title keywords
        is_electronic = False
        for gh in [m_genre_hint, s_genre_hint]:
            if gh:
                if gh.get('vocal_hint') == 'instrumental' or \
                   gh.get('density') in ('dense', 'percussive'):
                    is_electronic = True
                    break

        if is_electronic:
            print(f"    🎯 fallback: electronic/instrumental → 16b, smooth_eq")
            params = {'cf_bars': 16, 'smooth_eq': True, 'notch_db': -3.5}
        else:
            params = {'cf_bars': 8, 'smooth_eq': True, 'notch_db': -3.0}

        # Vocal density notch override (applies to fallback too)
        md = m_vocal_density if m_vocal_density is not None else 0.0
        sd = s_vocal_density if s_vocal_density is not None else 0.0
        if md > 0.5 or sd > 0.5:
            params['notch_db'] = max(-6.0, params['notch_db'] - 1.0)
        return params

    # ── Mode 1: A1F segment-based ──────────────────────────────────
    m = m_a1f_label.lower() if m_a1f_label else ''
    s = s_a1f_label.lower() if s_a1f_label else ''

    # Vocal entry → drop cut
    if s in ('chorus', 'verse', 'bridge'):
        params = {'cf_bars': 4, 'smooth_eq': False, 'notch_db': -5.0}
    # outro → intro/inst/start: long blend
    elif m in ('outro', 'end') and s in ('intro', 'inst', 'start'):
        params = {'cf_bars': 16, 'smooth_eq': True, 'notch_db': -3.5}
    # outro/break → verse/bridge: medium blend
    elif m in ('outro', 'end', 'break') and s in ('verse', 'bridge'):
        params = {'cf_bars': 8, 'smooth_eq': True, 'notch_db': -5.0}
    # break → intro/inst: medium + smooth
    elif m in ('break',) and s in ('intro', 'inst', 'start'):
        params = {'cf_bars': 8, 'smooth_eq': True, 'notch_db': -3.0}
    # chorus/verse/drop → intro/inst: short cut
    elif m in ('chorus', 'verse', 'bridge', 'drop') and s in ('intro', 'inst', 'start'):
        params = {'cf_bars': 4, 'smooth_eq': False, 'notch_db': -5.0}
    # outro/break → outro/break: medium
    elif m in ('outro', 'end', 'break') and s in ('outro', 'end', 'break'):
        params = {'cf_bars': 8, 'smooth_eq': True, 'notch_db': -3.0}
    # Default
    else:
        params = {'cf_bars': 8, 'smooth_eq': True, 'notch_db': -3.0}

    # Vocal density notch override: denser tracks get more aggressive notch
    md = m_vocal_density if m_vocal_density is not None else 0.0
    sd = s_vocal_density if s_vocal_density is not None else 0.0
    if md > 0.5 or sd > 0.5:
        params['notch_db'] = max(-6.0, params['notch_db'] - 1.0)

    return params


def vocal_per_bar(audio, db, sr):
    """
    Per-bar vocal detection. Returns bool array: True if vocals likely present in that bar.
    """
    mono = audio.mean(1).astype(np.float32) if audio.ndim == 2 else audio.astype(np.float32)
    vpb = np.zeros(len(db) - 1, dtype=bool)
    for i in range(len(db) - 1):
        s = int(db[i])
        e = int(db[i + 1])
        if e <= s or s >= len(mono):
            continue
        chunk = mono[s:e]
        if len(chunk) < 256:
            continue
        zcr = librosa.feature.zero_crossing_rate(chunk, hop_length=512)[0].mean()
        S = np.abs(librosa.stft(chunk, n_fft=2048, hop_length=512))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        vmask = (freqs >= 1000) & (freqs <= 4000)
        vocal_ratio = S[vmask].sum() / (S.sum() + 1e-12)
        vpb[i] = bool(vocal_ratio > 0.10 and zcr > 0.03)
    return vpb


def drum_activity(audio_segment, sr, low_min=40, low_max=150):
    """
    Check whether a segment has steady kick drum / sub-bass activity.

    Returns ratio of low-frequency energy to total energy (0..1).
    >= 0.15 → drums present, suitable for mixing.
    """
    if audio_segment is None or len(audio_segment) < sr // 4:
        return 0.0
    mono = audio_segment.mean(1) if audio_segment.ndim > 1 else audio_segment
    S = np.abs(librosa.stft(mono.astype(np.float32), n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low_mask = (freqs >= low_min) & (freqs <= low_max)
    low_e = S[low_mask].sum()
    total_e = S.sum() + 1e-12
    return float(low_e / total_e)


def best_exit_bar_v2(a1f_labels, secs, default_bar, n_bars_total, cf_bars,
                     phrase=4, vocal_mask=None, min_bar=0):
    """
    Enhanced exit bar selection using A1F section labels.

    Args:
        min_bar: minimum allowed exit bar (enforces MIN_PLAY_FRACTION).

    Priority (A1F_PRIORITY): outro(0) < break(1) < intro/inst(2) < verse(3) < chorus(4).

    Prefers:
      1. Sections with lowest A1F priority (outro > break > intro > ...)
      2. No vocals (if vocal_mask provided)
      3. Phrase-aligned (4-bar grid)
      4. Respects min_bar — no chopping before track has played enough
    """
    candidates = []
    for k in [-3, -2, -1, 0, 1, 2]:
        eb = round((default_bar + k * phrase) / phrase) * phrase
        if eb < max(cf_bars, min_bar) or eb > n_bars_total - cf_bars:
            continue

        # Score from A1F labels (0=best, 4=worst)
        a1f_label = a1f_labels[eb] if a1f_labels and eb < len(a1f_labels) else None
        a1f_score = A1F_PRIORITY.get(a1f_label, 3) if a1f_label else (
            EXIT_SCORE.get(section_at_bar(secs, eb), 3)
        )

        # Vocal penalty
        vocal_penalty = 10 if (vocal_mask is not None and eb < len(vocal_mask) and vocal_mask[eb]) else 0

        # Drum bonus: prefer sections with steady drums
        drum_bonus = 0  # calculated later per candidate

        total_score = a1f_score + vocal_penalty
        candidates.append((total_score, eb, a1f_label or ''))

    if not candidates:
        return default_bar, '?'

    candidates.sort()
    best_score, best_bar, best_label = candidates[0]

    if best_bar != default_bar:
        old_label = a1f_labels[default_bar] if a1f_labels and default_bar < len(a1f_labels) else section_at_bar(secs, default_bar)
        print(f"    ↳ Exit shifted {default_bar}→{best_bar} ({old_label}→{best_label})")
    return best_bar, best_label


def dynamic_loop(audio, sr, bpm, n_bars, target_bars=16):
    """
    Loop a short section (e.g. 2-4 bar intro) to stretch it to target_bars.

    Returns looped audio segment of target_bars length.
    If n_bars >= target_bars, returns original (no loop needed).
    """
    if n_bars >= target_bars:
        return audio
    bar_samp = int(bar_s(bpm) * sr)
    n_samp = bar_samp * n_bars
    if len(audio) < n_samp:
        n_samp = len(audio)
    loop_src = audio[:n_samp]

    # Build loop: repeat until target length reached
    target_samp = bar_samp * target_bars
    loops_needed = max(2, target_samp // n_samp + 1)
    looped = np.tile(loop_src, (loops_needed, 1)) if loop_src.ndim > 1 else np.tile(loop_src, loops_needed)
    looped = looped[:target_samp]

    # Crossfade the loop boundary (last 1 bar into first 1 bar)
    cf = bar_samp
    fo = np.linspace(1.0, 0.0, cf).astype(np.float32)
    fi = np.linspace(0.0, 1.0, cf).astype(np.float32)
    if looped.ndim > 1:
        fo = fo[:, None]
        fi = fi[:, None]
    looped[:cf] = looped[:cf] * fo + looped[-cf:] * fi
    looped[-cf:] = looped[:cf][-cf:]  # reconstruct tail from blended head

    print(f"    Auto-loop: {n_bars} bars → {target_bars} bars (x{target_bars // n_bars})")
    return looped.astype(np.float32)


def best_exit_bar(secs, default_bar, n_bars_total, cf_bars, phrase=16):
    """
    Try default ± 1-2 phrases (16 bars each). Pick the exit bar where
    the master is in the quietest section (QUIET < BUILD < ACTIVE < DROP).
    Returns the best bar, rounded to phrase grid.
    """
    candidates = []
    for k in [-2, -1, 0, 1]:
        eb = ((default_bar // phrase) + k) * phrase
        if eb < cf_bars or eb > n_bars_total - cf_bars:
            continue
        label = section_at_bar(secs, eb)
        score = EXIT_SCORE.get(label, 2)
        candidates.append((score, eb))

    if not candidates:
        return default_bar

    candidates.sort()
    best_score, best_bar = candidates[0]
    default_score = EXIT_SCORE.get(section_at_bar(secs, default_bar), 2)
    if best_bar != default_bar and best_score < default_score:
        print(f"    ↳ Exit shifted {default_bar}→{best_bar} ({section_at_bar(secs,default_bar)}→{section_at_bar(secs,best_bar)})")
    return best_bar


def first_soft_entry(secs, mn_build=2, mn_active=8):
    """
    Prefer entering on a BUILD section (even short ≥ mn_build bars) before
    the first ACTIVE, so the slave fades in softly before full drums hit.
    Falls back to first_active if no BUILD found.
    """
    # Find first BUILD with at least mn_build bars
    for s, e, l in secs:
        if l == 'BUILD' and e - s >= mn_build:
            return s
    # Fall back: first ACTIVE/DROP with at least mn_active bars
    for s, e, l in secs:
        if l in ('DROP', 'ACTIVE') and e - s >= mn_active:
            return s
    return 0


def first_active(secs, mn=8):
    """Find first active/drop section with at least mn bars."""
    for s, e, l in secs:
        if l in ('DROP', 'ACTIVE') and e - s >= mn:
            return s
    return 0


def has_vocals(audio, sr, energy_thresh=0.10, zcr_thresh=0.03):
    """
    Simple vocal presence detector using ZCR + spectral energy in 1-4kHz.
    Returns True if vocals likely present.
    """
    if audio is None or len(audio) == 0:
        return False
    mono = audio.mean(1).astype(np.float32) if audio.ndim == 2 else audio.astype(np.float32)
    if mono.max() < 1e-6:
        return False
    zcr_mean = librosa.feature.zero_crossing_rate(mono, hop_length=512)[0].mean()
    S = np.abs(librosa.stft(mono, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    vmask = (freqs >= 1000) & (freqs <= 4000)
    vocal_ratio = S[vmask].sum() / (S.sum() + 1e-12)
    return bool(vocal_ratio > energy_thresh and zcr_mean > zcr_thresh)


# ============================================================
# Onset & Phase Micro-alignment (v13: downbeat-weighted)
# ============================================================

def onset_micro_align(m_mono, s_mono, bpm, max_shift_sec=0.05,
                      m_db_zone=None, s_db_zone=None, sr=SR):
    """
    Sub-bar transient alignment using onset strength cross-correlation.
    Downbeat frames weighted at 1.0, others at 0.3 for sharper alignment.

    Args:
        m_db_zone, s_db_zone: downbeat sample positions for weighting
    """
    hop = 32  # was 128 — 4x finer alignment (0.73ms vs 2.9ms)
    mo = librosa.onset.onset_strength(y=m_mono.astype(np.float32), sr=sr, hop_length=hop)
    so = librosa.onset.onset_strength(y=s_mono.astype(np.float32), sr=sr, hop_length=hop)

    # Downbeat-weight: frames at downbeat positions get 1.0, others 0.3
    if m_db_zone is not None and len(m_db_zone) > 1:
        wm = np.full_like(mo, 0.3)
        for db_s in m_db_zone:
            df = int(db_s / hop)
            if 0 <= df < len(wm):
                wm[df] = 1.0
        mo *= wm
    if s_db_zone is not None and len(s_db_zone) > 1:
        ws = np.full_like(so, 0.3)
        for db_s in s_db_zone:
            df = int(db_s / hop)
            if 0 <= df < len(ws):
                ws[df] = 1.0
        so *= ws

    mo /= (mo.max() + 1e-8)
    so /= (so.max() + 1e-8)

    max_hop_shift = int(max_shift_sec * sr / hop)
    corr = signal.fftconvolve(mo, so[::-1], mode='full')
    center = len(corr) // 2

    lo = max(0, center - max_hop_shift)
    hi = min(len(corr), center + max_hop_shift + 1)

    best = np.argmax(corr[lo:hi]) + lo - center
    return best * hop


# ============================================================
# Bar-by-Bar Warp (v13: CF_BARS+1 for extra bar)
# ============================================================

def warp_to_grid(slave_audio, s_db, m_db, sr):
    """
    Bar-by-bar time warp: stretch each slave bar to exactly match
    the corresponding master bar length. Eliminates phase drift
    accumulation over 16-bar crossfades.

    rate = s_bar_len / m_bar_len  (pyrubberband speed multiplier)
      >1: slave bar longer than master -> speed up
      <1: slave bar shorter than master -> slow down
    """
    n_bars = min(len(m_db) - 1, len(s_db) - 1)
    if n_bars < 2:
        return None, 0

    # Compute master bar lengths and smooth outliers
    m_raw_lens = np.array([int(m_db[i + 1]) - int(m_db[i]) for i in range(n_bars)])
    m_med = np.median(m_raw_lens)
    # Clamp outliers to ±25% of median (annotation jitter protection)
    m_lens = np.where((m_raw_lens > m_med * 0.75) & (m_raw_lens < m_med * 1.25),
                      m_raw_lens, int(m_med))

    bars = []
    consumed = 0
    for i in range(n_bars):
        m_bar_len = int(m_lens[i])
        s_start = int(s_db[i])
        s_end = int(s_db[i + 1])
        if s_end > len(slave_audio) or m_bar_len <= 0:
            break
        bar = slave_audio[s_start:s_end].astype("float64")
        if len(bar) == 0:
            bars.append(np.zeros((m_bar_len, slave_audio.shape[1]), dtype="float32"))
            consumed = s_end
            continue

        rate = len(bar) / m_bar_len
        if abs(rate - 1.0) > 0.002:  # skip stretch for tiny rate diff
            warped = pyrb.time_stretch(bar, sr, rate).astype("float32")
        else:
            warped = bar.astype("float32")

        if len(warped) >= m_bar_len:
            bars.append(warped[:m_bar_len])
        else:
            pad = np.zeros((m_bar_len - len(warped), slave_audio.shape[1]), dtype="float32")
            bars.append(np.concatenate([warped, pad]))
        consumed = s_end

    if not bars:
        return None, 0
    return np.concatenate(bars), consumed


# ============================================================
# BPM Ramp-back
# ============================================================

def ramp_to_native(slave_audio, s_db, m_bpm, s_bpm, sr, ramp_sec=RAMP_SEC, ser=1.0):
    """
    After crossfade, the slave was warped to master BPM.
    Smoothly ramp it back to native BPM over ramp_sec seconds.
    Linear interpolation: bar length goes from master-bar to native-bar.

    If ser (entry RMS) is below RAMP_MIN_RMS, do a simple volume fade instead.
    """
    bpm_diff = abs(m_bpm - s_bpm)
    if bpm_diff < 2.0:  # skip ramp for small BPM diff (was 0.5)
        return None, 0

    if ser < RAMP_MIN_RMS:
        fs = int(ramp_sec * sr)
        fs = min(fs, len(slave_audio))
        fd = np.linspace(0.0, 1.0, fs).astype("float32")
        faded = slave_audio[:fs].copy().astype("float32") * fd[:, None]
        print(f"    Volume fade (quiet rms={ser:.4f}): {fs/sr:.1f}s")
        return faded, fs

    m_bar_samp = bar_s(m_bpm) * sr
    s_bar_samp = bar_s(s_bpm) * sr

    n_bars_needed = int(ramp_sec / bar_s(s_bpm)) + 1
    n_bars = min(n_bars_needed, len(s_db) - 1)
    if n_bars < 2:
        return None, 0

    bars = []
    consumed = 0
    for i in range(n_bars):
        t = i / max(1, n_bars - 1)
        target_len = int(m_bar_samp + t * (s_bar_samp - m_bar_samp))

        s_start = int(s_db[i])
        s_end = int(s_db[i + 1])
        if s_end > len(slave_audio) or target_len <= 0:
            break
        bar = slave_audio[s_start:s_end]
        if len(bar) == 0:
            consumed = s_end
            continue

        rate = len(bar) / target_len
        if abs(rate - 1.0) > 0.002:
            warped = pyrb.time_stretch(bar.astype("float64"), sr, rate).astype("float32")
        else:
            warped = bar.astype("float32")

        if len(warped) >= target_len:
            bars.append(warped[:target_len])
        else:
            pad = np.zeros((target_len - len(warped), bar.shape[1]), dtype="float32")
            bars.append(np.concatenate([warped, pad]))
        consumed = s_end

    if not bars:
        return None, 0
    result = np.concatenate(bars)
    print(f"    BPM ramp: {m_bpm:.1f}->{s_bpm:.1f} over {len(result)/sr:.1f}s ({n_bars} bars)")
    return result, consumed


# ============================================================
# RMS Stabilizer with Lookahead (v13: narrow + lookahead)
# ============================================================

def rms_stabilizer_lookahead(blended, cf_len):
    """
    Narrow RMS stabilizer + lookahead:
    Only boosts dips < 0.3*median with a sharp drop (>30%) and quick recovery.
    Also checks next 3 windows for a recovery >2x (lookahead).
    Uses Hann kernel size=3 for shorter smoothing.
    """
    dw = int(0.1 * SR)
    nd = max(1, cf_len // dw - 2)
    rms = np.array([
        np.sqrt(np.mean(blended[j*dw:(j+1)*dw]**2)) for j in range(nd)
    ])
    med = np.median(rms)
    ge = np.ones(nd)
    dc = 0

    for j in range(1, nd - 1):
        if rms[j] < 0.3 * med:
            # Check sharp drop
            sharp = rms[j-1] > 0 and (rms[j-1] - rms[j]) / rms[j-1] > 0.3
            qr = False
            for k in range(j + 1, min(j + 4, nd)):
                if rms[k] > rms[j] * 1.5:
                    qr = True
                    break

            if sharp and qr:
                lm = max(np.median(rms[max(0, j-2):j+3]), 1e-12)
                if lm > rms[j] * 1.5:
                    ge[j] = min(1.3, lm / (rms[j] + 1e-12))
                    dc += 1
            # Lookahead: dips that precede a big rise
            elif rms[j] < 0.3 * med:
                for k in range(j + 1, min(j + 4, nd)):
                    if rms[k] > rms[j] * 2.0:
                        lm = max(np.median(rms[max(0, j-2):j+3]), 1e-12)
                        if lm > rms[j] * 1.5:
                            ge[j] = min(1.3, lm / (rms[j] + 1e-12))
                            dc += 1
                        break

    if dc:
        from scipy.signal.windows import hann
        k = hann(3)
        k /= k.sum()
        ge = np.convolve(ge, k, mode='same')
        for j in range(nd):
            blended[j*dw:(j+1)*dw] *= ge[j]
        print(f"    RMS stabilizer: {dc} dips (narrow+lookahead)")

    return blended


# ============================================================
# Equal-Power Fade Shapes
# ============================================================

def eq_pow(n):
    """Return cos²/sin² fade curves (power-law fades, fo²+fi²=1 at all points)."""
    t = np.linspace(0, np.pi / 2, n).astype("float32")
    return np.cos(t), np.sin(t)


# ============================================================
# EQ Sweep Module (HPF/LPF/Shelving IIR Filters)
# ============================================================

def _sweep_channel(audio, sr, filter_type, start_freq, end_freq, num_steps=32):
    """
    Sweep an IIR filter on mono audio using overlapped Hann-windowed frames.
    filter_type: 'highpass', 'lowpass', 'low_shelf', 'high_shelf'
    """
    n = len(audio)
    if n < 100:
        return audio.astype(np.float32)
    out = np.zeros(n, dtype=np.float64)
    weight = np.zeros(n, dtype=np.float64)
    step = max(1, n // num_steps)
    ov = max(1, step // 4)

    for i in range(num_steps):
        frac = i / max(num_steps - 1, 1)
        freq = start_freq + (end_freq - start_freq) * frac
        freq = max(10.0, min(freq, 0.45 * sr))

        if filter_type in ('low_shelf', 'high_shelf'):
            # Use biquad shelving via scipy, converted to sos (minimum-phase, no pre-ringing)
            b, a = _shelf_coeffs(freq, 0.707, 0.0, sr, filter_type)
            sos = signal.tf2sos(b, a)
        else:
            order = 2  # 12dB/oct — smooth DJ-style
            sos = signal.butter(order, freq / (0.5 * sr), btype=filter_type, output='sos')

        start = max(0, i * step - ov)
        end = min(n, start + step + 2 * ov)
        chunk = audio[start:end].astype(np.float64)
        wlen = len(chunk)

        if wlen < 10:
            continue

        filtered = signal.sosfilt(sos, chunk.ravel())

        win = np.hanning(wlen)
        out[start:end] += filtered * win
        weight[start:end] += win

    weight = np.where(weight > 0, weight, 1.0)
    return (out / weight).astype(np.float32)


def _shelf_coeffs(freq, q, gain_db, sr, shelf_type):
    """Design biquad low/high shelf coefficients."""
    w0 = 2.0 * np.pi * freq / sr
    A = 10.0 ** (gain_db / 40.0)  # amplitude
    alpha = np.sin(w0) / (2.0 * q)

    if shelf_type == 'low_shelf':
        b0 = A * ((A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha)
        b1 = 2 * A * ((A - 1) - (A + 1) * np.cos(w0))
        b2 = A * ((A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha)
        a0 = (A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha
        a1 = -2 * ((A - 1) + (A + 1) * np.cos(w0))
        a2 = (A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha
    elif shelf_type == 'high_shelf':
        b0 = A * ((A + 1) + (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha)
        b1 = -2 * A * ((A - 1) + (A + 1) * np.cos(w0))
        b2 = A * ((A + 1) + (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha)
        a0 = (A + 1) - (A - 1) * np.cos(w0) + 2 * np.sqrt(A) * alpha
        a1 = 2 * ((A - 1) - (A + 1) * np.cos(w0))
        a2 = (A + 1) - (A - 1) * np.cos(w0) - 2 * np.sqrt(A) * alpha
    else:
        return np.array([1.0]), np.array([1.0])

    # Normalize
    b = np.array([b0, b1, b2]) / a0
    a = np.array([a0, a1, a2]) / a0
    return b, a


def eq_sweep(audio, sr, filter_type='highpass', start_freq=20, end_freq=150, num_steps=32):
    """
    Apply a frequency sweep across audio using IIR filters.

    filter_type: 'highpass' — bass cut (master outgoing)
                 'lowpass'  — treble cut (slave incoming)
                 'low_shelf' — smooth bass reduction
                 'high_shelf' — smooth treble boost/cut
    start_freq, end_freq: sweep range in Hz
    num_steps: number of frames for the sweep (~ per-bar for 128 BPM = 32 steps over 16 bars)

    For zero-gain shelf, use gain_db=0 in _shelf_coeffs (flat = no-op).
    For actual bass swap:
      - Outgoing master: highpass 20→150Hz (bass disappears)
      - Incoming slave:  lowpass 150→20Hz  (bass appears, then highpass removed)
    """
    ch = audio.shape[1] if audio.ndim > 1 else 1
    out = np.zeros_like(audio, dtype=np.float32)
    for c in range(ch):
        out[:, c] = _sweep_channel(
            audio[:, c], sr, filter_type, start_freq, end_freq, num_steps
        )
    return out


def vocal_notch_sweep(audio, sr, num_steps=16, min_freq=1000, max_freq=4000,
                      gain_db=-12, q=1.5):
    """
    Sweep a notch/bell filter across the vocal range (1-4kHz) to duck
    master vocals during a vocal-clash crossfade.

    Applies a peaking EQ with negative gain that sweeps from min_freq to max_freq.
    Result: master vocals become muffled/'telephone-like', clearing space for slave.
    """
    ch = audio.shape[1] if audio.ndim > 1 else 1
    out = np.zeros_like(audio, dtype=np.float32)
    for c in range(ch):
        out[:, c] = _notch_sweep_channel(
            audio[:, c].astype(np.float64), sr, num_steps,
            min_freq, max_freq, gain_db, q
        )
    return out


def _notch_sweep_channel(mono, sr, num_steps, min_freq, max_freq, gain_db, q):
    """Mono notch sweep with overlapped Hann frames. Uses minimum-phase IIR (no pre-ringing)."""
    n = len(mono)
    if n < 100:
        return mono.astype(np.float32)
    out = np.zeros(n, dtype=np.float64)
    weight = np.zeros(n, dtype=np.float64)
    step = max(1, n // num_steps)
    ov = max(1, step // 4)

    for i in range(num_steps):
        frac = i / max(num_steps - 1, 1)
        freq = min_freq + (max_freq - min_freq) * frac
        freq = max(50.0, min(freq, 0.45 * sr))
        b, a = _bell_coeffs(freq, q, gain_db, sr)
        sos = signal.tf2sos(b, a)
        start = max(0, i * step - ov)
        end = min(n, start + step + 2 * ov)
        chunk = mono[start:end]
        wlen = len(chunk)
        if wlen < 10:
            continue
        filtered = signal.sosfilt(sos, chunk)
        win = np.hanning(wlen)
        out[start:end] += filtered * win
        weight[start:end] += win
    weight = np.where(weight > 0, weight, 1.0)
    return (out / weight).astype(np.float32)


def _bell_coeffs(freq, q, gain_db, sr):
    """Design biquad peaking (bell) filter coefficients."""
    w0 = 2.0 * np.pi * freq / sr
    A = 10.0 ** (gain_db / 40.0)
    alpha = np.sin(w0) / (2.0 * q)
    b0 = 1.0 + alpha * A
    b1 = -2.0 * np.cos(w0)
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * np.cos(w0)
    a2 = 1.0 - alpha / A
    b = np.array([b0, b1, b2]) / a0
    a = np.array([a0, a1, a2]) / a0
    return b, a


def soft_clipper_tanh(audio, threshold=0.707):
    """
    Standard fast minimum-distortion soft clipper using tanh.
    Leaves audio below threshold untouched (100% linear),
    smoothly compresses transients above threshold towards 1.0.
    
    Acts on multi-channel (stereo) or mono audio.
    """
    out = np.copy(audio)
    mask = np.abs(audio) > threshold
    if np.any(mask):
        scale = 1.0 - threshold
        out[mask] = (threshold + scale * np.tanh((np.abs(audio[mask]) - threshold) / scale)) * np.sign(audio[mask])
    
    # Final safety check to keep peak exactly under 0.999
    pk = np.max(np.abs(out))
    if pk > 0.999:
        out = out * (0.999 / pk)
    return out.astype(audio.dtype)

def build_cf_lr4(m_cf, s_cf, m_bpm, s_bpm, m_db, s_db, mode, cf_bars=16, sr=SR, stabilizer=True, vocal_clash=False, notch_db=-12.0, smooth_eq=True):
    """
    Build crossfade with LR4 3-band bass swap (or simple eq_power).

    mode='hpss': LR4 bass swap (bass switches instantly, mids/highs crossfade)
    mode='quiet': simple equal-power crossfade

    Args:
        cf_bars: number of bars for the crossfade (default 16)
        vocal_clash: if True, apply vocal_notch_sweep on master mid band
        notch_db: attenuation depth for vocal notch (from STYLE_PROFILES, default -12.0)
        smooth_eq: if True, use per-sample smooth EQ sweep instead of stepped frames

    Returns:
        blended, shift, consumed, warp_extra
        warp_extra: saved (cf_bars+1)th bar of warp for seamless blend→ramp transition
    """
    bpm_diff_ratio = abs(m_bpm - s_bpm) / m_bpm
    use_bpm_transition = (bpm_diff_ratio > 0.05)

    s_zone = None
    m_zone = None
    consumed = 0
    warp_extra = None

    if use_bpm_transition:
        cf_len = int(cf_bars * bar_s(s_bpm) * sr)
        n_m = min(cf_bars + 2, len(m_db))
        n_s = min(cf_bars + 2, len(s_db))
        
        m_db_zone = m_db[:cf_bars + 2]
        s_db_zone = s_db[:cf_bars + 2]
        
        warped_m, consumed_m = warp_to_grid(m_cf, m_db_zone, s_db_zone, sr)
        if warped_m is not None:
            print(f"    ↳ [BPM Transition (>5%)] Warp Master to Slave grid ({m_bpm:.1f}->{s_bpm:.1f})")
            m_zone = pt(warped_m, cf_len)
        else:
            rate_m = s_bpm / m_bpm
            print(f"    ↳ [BPM Transition] Fallback global stretch Master rate={rate_m:.4f}")
            m_zone = pyrb.time_stretch(pt(m_cf, cf_len + sr * 2).astype("float64"), sr, rate_m).astype("float32")
            m_zone = pt(m_zone, cf_len)
            
        s_zone = pt(s_cf, cf_len)
        consumed = cf_len
        warp_extra = None
    else:
        cf_len = int(cf_bars * bar_s(m_bpm) * sr)

        # 1. Bar-by-bar warp (primary method) — use cf_bars+2 for an extra bar
        #    (cf_bars+1 downbeats → cf_bars bars; cf_bars+2 downbeats → cf_bars+1 bars,
        #     giving a real 1-bar warp_extra for seamless blend→ramp transition)
        n_m = min(cf_bars + 2, len(m_db))
        n_s = min(cf_bars + 2, len(s_db))
        use_barwarp = (n_m >= cf_bars + 1 and n_s >= cf_bars + 1)
        warp_extra = None

        if use_barwarp:
            m_db_zone = m_db[:cf_bars + 2]
            s_db_zone = s_db[:cf_bars + 2]

            warped, consumed = warp_to_grid(s_cf, s_db_zone, m_db_zone, sr)
            if warped is not None:
                print(f"    Bar-by-bar warp: {min(n_m,len(m_db_zone))-1} bars | consumed {consumed/sr:.1f}s slave audio")
                s_zone = pt(warped, cf_len)
                # Save 17th bar for seamless blend→ramp transition
                warp_extra = warped[cf_len:] if len(warped) > cf_len else None
            else:
                use_barwarp = False
                warp_extra = None

        if not use_barwarp:
            # Fallback: single global stretch
            rate = m_bpm / s_bpm
            native_len = int(cf_bars * bar_s(s_bpm) * sr) + sr * 2
            s_raw = pt(s_cf, native_len)
            if abs(rate - 1.0) > 0.002:
                print(f"    Fallback global stretch {s_bpm:.1f}->{m_bpm:.1f}  rate={rate:.4f}")
                s_zone = pyrb.time_stretch(s_raw.astype("float64"), sr, rate).astype("float32")
            else:
                print(f"    No stretch needed ({abs(rate - 1) * 100:.2f}%)")
                s_zone = s_raw
            s_zone = pt(s_zone, cf_len)
            consumed = int(cf_bars * bar_s(s_bpm) * sr)
            warp_extra = None

        m_zone = pt(m_cf, cf_len)

    # 2. Residual micro-align (+/-50ms window, downbeat-weighted)
    mm = m_zone.mean(1)
    sm = s_zone.mean(1)
    shift = onset_micro_align(
        mm, sm, s_bpm if use_bpm_transition else m_bpm, max_shift_sec=0.05,
        m_db_zone=s_db_zone[:cf_bars + 1] if use_bpm_transition else m_db[:cf_bars + 1],
        s_db_zone=s_db_zone[:cf_bars + 1],
        sr=sr
    )
    print(f"    Residual shift after warp: {shift/sr*1000:.1f}ms")
    if abs(shift) > 0:
        if int(shift) > 0:
            s_zone = np.concatenate([s_zone[int(shift):], np.zeros((int(shift), 2), dtype="float32")])
        else:
            pad_n = -int(shift)
            s_zone = np.concatenate([np.zeros((pad_n, 2), dtype="float32"), s_zone[:-pad_n]])

    # NOTE: Per-bar re-alignment REMOVED (v3 fix).
    # warp_to_grid already aligns bar boundaries precisely.
    # Per-chunk independent shifts created discontinuities at chunk boundaries,
    # introducing audible phase jumps. Global micro-align (step 2) handles residual.

    # 3. LR4 3-Band blend with bass polarity check
    if mode == 'hpss':
        # ── Dynamic crossover frequency ──────────────────────────────────
        low_cut, high_cut = find_crossover(m_zone, s_zone, sr)
        print(f"    LR4 3-Band split @ low={low_cut}Hz high={high_cut}Hz...", flush=True)
        m_low, m_mid, m_high = three_band_split(m_zone, low_cut, high_cut, sr)
        s_low, s_mid, s_high = three_band_split(s_zone, low_cut, high_cut, sr)

        # Bass polarity check — weighted consensus across 5 points
        bar_samples = int(bar_s(m_bpm) * sr)
        bws = int(0.10 * SR)  # analysis window (100ms)
        n_points = 5
        polarities = []
        for pi in range(n_points):
            pc = int(cf_len * (pi + 1) / (n_points + 1))
            aw2 = m_low[pc - bws:pc + bws].flatten()
            bl3 = s_low[pc - bws:pc + bws].flatten()
            if len(aw2) == len(bl3) and len(aw2) > 50:
                co = np.corrcoef(aw2, bl3)[0, 1]
                if not np.isnan(co):
                    polarities.append(co)
        if polarities:
            mean_corr = float(np.mean(polarities))
            print(f"    Bass polarity: mean_corr={mean_corr:.2f} ({n_points} pts)", end='')
            # Also check kick band (60-120Hz) separately — more critical for phase cancellation
            sos = signal.butter(4, [60, 120], btype='band', fs=sr, output='sos')
            m_kick = signal.sosfilt(sos, m_low.mean(1))
            s_kick = signal.sosfilt(sos, s_low.mean(1))
            kick_corr = np.corrcoef(m_kick, s_kick)[0, 1] if len(m_kick) > 100 else 0
            if not np.isnan(kick_corr):
                print(f"  kick_corr={kick_corr:.2f}", end='')
            # Invert if EITHER full-band or kick band shows significant negative correlation
            if mean_corr < -0.3 or kick_corr < -0.5:
                s_low = -s_low
                print(" → INVERTED")
            else:
                print(" → OK")
        else:
            print("    Bass polarity: skipped (insufficient data)")

        fo, fi = eq_pow(cf_len)
        blended_mid = m_mid * fo[:, None] + s_mid * fi[:, None]
        blended_high = m_high * fo[:, None] + s_high * fi[:, None]

        # ── EQ Sweep Bass Swap (Phase 2) ─────────────────────────────────
        # Replaces old binary 2-bar swap with gradual HPF/LPF sweeps.
        # For smooth_eq=True, use per-sample step count for seamless sweep.
        if smooth_eq:
            num_sweep_steps = max(256, len(m_low) // 128)  # ~every 3ms
        else:
            num_sweep_steps = max(8, cf_bars * 2)  # ~2 steps per bar
        print(f"    EQ Sweep bass swap: {num_sweep_steps} steps{' (smooth)' if smooth_eq else ''}", flush=True)
        m_low_swept = eq_sweep(m_low, sr, filter_type='highpass',
                                start_freq=20, end_freq=150,
                                num_steps=num_sweep_steps)
        s_low_swept = eq_sweep(s_low, sr, filter_type='lowpass',
                                start_freq=150, end_freq=20,
                                num_steps=num_sweep_steps)

        blended_low = m_low_swept + s_low_swept

        # ── Vocal Notch Sweep (VAD Clash mitigation, profile-driven) ───
        if vocal_clash:
            # Duck master vocal range (1-4kHz) by notch_db from profile
            # This clears space for the slave's vocals without 'telephone' effect
            if smooth_eq:
                notch_steps = max(256, blended_mid.shape[0] // 128)
            else:
                notch_steps = max(24, cf_bars * 4)
            print(f"    Vocal Notch Sweep: {notch_steps} steps, {notch_db}dB @ 1-4kHz{' (smooth)' if smooth_eq else ''}", flush=True)
            blended_mid = vocal_notch_sweep(
                blended_mid, sr, num_steps=notch_steps,
                min_freq=1000, max_freq=4000, gain_db=notch_db, q=1.5
            )

        blended = blended_low + blended_mid + blended_high

        # Narrow RMS stabilizer with lookahead
        if stabilizer:
            blended = rms_stabilizer_lookahead(blended, cf_len)
    else:
        fo, fi = eq_pow(cf_len)
        blended = m_zone * fo[:, None] + s_zone * fi[:, None]

    # Tail fade (TAIL_FADE_BARS) — redundant with seamless blend→ramp, disabled by default
    tbs = int(TAIL_FADE_BARS * bar_s(m_bpm) * sr)
    if tbs > 0 and tbs < cf_len:
        tf = np.linspace(1.0, 0.0, tbs).astype("float32")
        blended[-tbs:] *= (fo[-tbs:] * tf + (1.0 - fo[-tbs:]))[:, None]

    pk = np.max(np.abs(blended))
    if pk > 0.99:
        blended *= 0.99 / pk

    return blended, shift, consumed, warp_extra


# ============================================================
# Main Mixing Pipeline
# ============================================================

def mix_tracks(tracks, wav_dir, ann_dir, output_mp3, bitrate="320k", sr=SR,
               style=None, author=None,
               use_quiet_exit=False, stabilizer=True, transitions_dir=None,
               cf_bars='auto', analysis_mode='a1f'):
    """
    Main entry point. Mix a list of tracks into a continuous DJ mix.

    Args:
        tracks: list of (name, wav_filename, annotation_filename) tuples
        wav_dir: directory containing WAV files
        ann_dir: directory containing madmom annotation .txt files
        output_mp3: output MP3 path
        bitrate: MP3 bitrate (default "320k")
        sr: sample rate (default 44100)
        style: genre/style name for metadata
        author: DJ/artist name for metadata
    """
    today = time.strftime("%Y-%m-%d")
    print(f"=== Smart Mixer: Bar-by-Bar Warp + LR4 + Narrow RMS + Seamless blend→ramp ===\n")
    if style:
        print(f"  Style: {style}  |  Date: {today}")
    if author:
        print(f"  Author: {author}")
    print()
    t_start = time.time()

    # Load + analyze tracks
    print("Loading and preparing tracks...")
    TD = []
    for name, wav_file, ann_file in tracks:
        print(f"\n  {name}:")
        t0 = time.time()
        audio = load_stereo(f'{wav_dir}/{wav_file}', sr)
        db = load_dbeats(f'{ann_dir}/{ann_file}', sr)
        raw = calc_bpm(db, sr)
        db, bpm = fix_ht(db, raw)
        print(f"    Detected BPM: {bpm:.1f} (in {time.time()-t0:.1f}s)")

        # ── A1F BPM cross-validation ──────────────────────────────────
        a1f_bpm = None
        a1f_path = os.path.join(wav_dir, 'a1f_results_full', os.path.splitext(wav_file)[0] + '.json')
        if os.path.exists(a1f_path):
            try:
                with open(a1f_path) as _f:
                    a1f_data = json.load(_f)
                a1f_bpm = a1f_data.get('bpm')
                if a1f_bpm:
                    old_bpm = bpm
                    bpm = float(a1f_bpm)
                    # Recompute downbeats to match corrected BPM
                    db, bpm = fix_ht(db, bpm)
                    print(f"    ↳ A1F BPM source of truth: {bpm:.1f} (madmom was {old_bpm:.1f})")
            except (IOError, json.JSONDecodeError):
                pass

        # Key detection + Camelot
        t_key = time.time()
        mono = audio.mean(1) if audio.ndim == 2 else audio
        key = detect_key(mono, sr)
        cam = camelot_code(key)
        print(f"    Key: {key:8s}  Camelot: {cam}  (in {time.time()-t_key:.1f}s)")

        secs = sections(audio, db, sr, name=name)
        act = [(s, e) for s, e, l in secs if l in ('ACTIVE', 'DROP')]
        if act:
            eb = max(0, act[0][0] - 2)
            xb = min(len(db) - 1, act[-1][1] + 2)
        else:
            eb, xb = 0, len(db) - 1

        s0 = int(db[eb])
        e0 = int(db[xb]) if xb < len(db) else len(audio)
        at = audio[s0:e0]
        dbt = db[eb:xb+1] - s0
        st = sections(at, dbt, sr)

        at = norm_lufs(at, TARGET_LUFS, sr)
        # ── hard peak clamp -3dB ──────────────────────────────────────────
        pk_at = np.max(np.abs(at))
        if pk_at > 0.707:
            at *= 0.707 / pk_at

        qe = quiet_exit(st)
        fa = first_active(st)
        se = first_soft_entry(st)  # BUILD preferred over ACTIVE for slave entry
        dur = len(at) / sr
        print(f"    Trimmed: {int(dur // 60)}:{int(dur % 60):02d}  bars {eb}-{xb}")
        print(f"    quiet_exit={'bar' + str(qe) if qe is not None else 'none'}  "
              f"soft_entry=bar{se}({section_at_bar(st,se)})  first_active=bar{fa}")

        # ── A1F Track Data + Genre Metadata ────────────────────────────
        # Run search_track_genre() for fallback metadata (always, regardless of mode)
        # Use filename as artist/title proxy for keyword matching
        name_parts = wav_file.replace('.wav', '').split(' - ')
        if len(name_parts) >= 2:
            track_artist = name_parts[0].strip()
            track_title = ' - '.join(name_parts[1:]).strip()
        else:
            track_artist = ''
            track_title = name_parts[0][:40]
        genre_hint = search_track_genre(track_artist, track_title)

        CATALOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'track_catalog', 'a1f_results')
        has_a1f_data = False
        a1f_data = None

        if analysis_mode != 'no_a1f':
            # Mode a1f or a1f_fast — try to load cached A1F data
            a1f_data = load_a1f_track_data(
                os.path.join(wav_dir, wav_file), sr,
                catalog_dir=CATALOG_DIR if os.path.exists(CATALOG_DIR) else None
            )

            # If not cached, launch background analysis
            if a1f_data is None and os.path.exists(CATALOG_DIR):
                a1f_venv = os.path.expanduser('~/ai-tools/all-in-one-fix/venv/bin/python')
                if os.path.exists(a1f_venv):
                    wav_abs = os.path.join(wav_dir, wav_file)
                    cmd = [a1f_venv, '-m', 'allin1fix.cli', wav_abs,
                           '-o', CATALOG_DIR, '--overwrite']
                    if analysis_mode == 'a1f_fast':
                        cmd.append('--skip-separation')
                    # full 'a1f' mode → no --skip-separation (Demucs + full precision)
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"    ↳ A1F analysis launched in background [{analysis_mode}] (results on next run)")

            if a1f_data:
                has_a1f_data = True
                # A1F BPM cross-validation
                if a1f_data.get('bpm'):
                    a1f_bpm = float(a1f_data['bpm'])
                    if abs(a1f_bpm - bpm) / max(bpm, 1) > 0.03:
                        old_bpm = bpm
                        bpm = a1f_bpm
                        db, bpm = fix_ht(db, bpm)
                        print(f"    ↳ A1F BPM cross-validated: {bpm:.1f} (madmom was {old_bpm:.1f})")

                # A1F downbeats → replace madmom grid when available
                if a1f_data.get('downbeats') is not None:
                    old_len = len(dbt)
                    dbt = a1f_data['downbeats']
                    print(f"    ↳ A1F downbeats: {len(dbt)} bars (was {old_len})")

        if not has_a1f_data:
            print(f"    Mode: {analysis_mode} — no A1F data, fallback to genre metadata")
        else:
            print(f"    Mode: {analysis_mode} — A1F data loaded")

        vpb = vocal_per_bar(at, dbt, sr) if len(at) > sr else np.zeros(len(dbt) - 1, dtype=bool)
        a1f_status = f'A1F:{len(a1f_data["bar_labels"]) if a1f_data and a1f_data["bar_labels"] else 0}bars' if has_a1f_data else 'A1F:none'
        print(f"    {a1f_status}  vocal_bars={vpb.sum()}/{len(vpb)}")

        # ── Vocal density (for transition param tuning) ──────────────────
        if a1f_data and a1f_data.get('vocal_density') is not None:
            track_vocal_density = a1f_data['vocal_density']
        else:
            track_vocal_density = int(vpb.sum()) / max(len(vpb), 1)
        print(f"    vocal_density={track_vocal_density:.2f}")

        TD.append({
            'name': name, 'audio': at, 'db': dbt, 'bpm': bpm,
            'key': key, 'cam': cam,
            'secs': st, 'qe': qe, 'fa': fa, 'se': se,
            'a1f': a1f_data,              # full A1F data dict (or None)
            'vpb': vpb,                    # per-bar VAD bool array
            'vocal_density': track_vocal_density,  # float 0..1
            'genre_hint': genre_hint,      # search_track_genre() result
            'has_a1f': has_a1f_data,       # bool flag for transition resolver
            'meta': a1f_data.get('meta') if a1f_data else None,  # artist/title/year
            'vocal_intervals': a1f_data.get('vocal_intervals', []) if a1f_data else [],
            'beats': a1f_data.get('beats') if a1f_data else None,
            'key_a1f': a1f_data.get('key_a1f') if a1f_data else None,
            'camelot_a1f': a1f_data.get('camelot_a1f') if a1f_data else None,
        })

        # Override display name with real meta if available
        meta = a1f_data.get('meta') if a1f_data else None
        if meta and meta.get('artist') and meta.get('track_title'):
            display_name = f"{meta['artist']} - {meta['track_title']}"
            print(f"    🏷 Real: {display_name}")
            TD[-1]['name'] = display_name  # update for stamps
        elif meta and meta.get('track_title'):
            print(f"    🏷 Title: {meta['track_title']}")

    # Print Camelot overview
    print(f"\n  === Camelot Wheel Overview ===")
    for td in TD:
        print(f"    {td['name']:15s}  {td['bpm']:5.1f} BPM  {td['key']:8s}  {td['cam']}")
    for i in range(len(TD) - 1):
        kc = key_compat(TD[i]['key'], TD[i+1]['key'])
        label = "SAME" if kc == 1.0 else "ADJ" if kc >= 0.9 else "REL" if kc >= 0.8 else "POOR"
        print(f"    {TD[i]['cam']} → {TD[i+1]['cam']}: compat={kc:.1f}  [{label}]")

    # Build the continuous mix
    print(f"\n\nBuilding mix (cf_bars={cf_bars})...\n")
    parts = []
    stamps = []
    mix_pos = 0
    cur = TD[0]
    cur_off = 0

    # Load AI transitions if directory provided
    ai_transitions = {}
    if transitions_dir and os.path.isdir(transitions_dir):
        print(f"  Loading AI transitions from: {transitions_dir}")
        for fname in os.listdir(transitions_dir):
            if fname.endswith('.wav') and fname.startswith('tr'):
                # Parse: tr0_TrackA_to_TrackB.wav
                ai_transitions[fname] = os.path.join(transitions_dir, fname)
        print(f"  Found {len(ai_transitions)} AI transition(s)")

    for i in range(1, len(TD)):
        nxt = TD[i]
        mb, sb = cur['bpm'], nxt['bpm']
        diff = abs(sb - mb) / mb

        print(f"  {cur['name']} ({mb:.1f}) -> {nxt['name']} ({sb:.1f})  diff={diff * 100:.1f}%")

        if diff > BPM_DIFF_LIMIT:
            print(f"    BPM difference too high (>{BPM_DIFF_LIMIT*100:.0f}%). Hard cut.")
            body = cur['audio'][cur_off:]
            parts.append(body)
            mix_pos += len(body)
            cur = nxt
            cur_off = 0
            continue

        # ── Resolve A1F labels and vocal masks ──────────────────────────────
        a1f_m = cur.get('a1f')
        a1f_s = nxt.get('a1f')
        vpb_m = cur.get('vpb')
        vpb_s = nxt.get('vpb')

        # Determine exit point using A1F priorities
        if use_quiet_exit and cur['qe'] is not None:
            exit_bar = cur['qe']
            exit_label = 'quiet_exit'
            print(f"    Quiet exit at bar {exit_bar}")
        else:
            total = len(cur['db']) - 1
            min_bar = int(MIN_PLAY_FRACTION * total)
            default_exit = max(min_bar, total - CF_BARS - 4)
            exit_bar, exit_label = best_exit_bar_v2(
                a1f_m, cur['secs'], default_exit, total, CF_BARS,
                vocal_mask=vpb_m, min_bar=min_bar
            )

        # Helper: get A1F bar label for a given bar index
        def _a1f_label(a1f_data, bar_idx, secs, fallback_bar=None):
            """Get A1F bar label from data dict, fall back to VAD section label."""
            if a1f_data and a1f_data.get('bar_labels') and bar_idx < len(a1f_data['bar_labels']):
                return a1f_data['bar_labels'][bar_idx]
            fb = fallback_bar if fallback_bar is not None else bar_idx
            return section_at_bar(secs, fb)

        # Resolve cf_bars + notch_db + smooth_eq from A1F segment intersection
        m_a1f_label = _a1f_label(a1f_m, exit_bar, cur['secs'])
        s_entry_guess = nxt['se']
        s_a1f_label = _a1f_label(a1f_s, s_entry_guess, nxt['secs'])

        # Use resolve_transition_params for all DSP parameters
        tp = resolve_transition_params(
            m_a1f_label, s_a1f_label,
            m_vocal_density=cur.get('vocal_density'),
            s_vocal_density=nxt.get('vocal_density'),
            has_a1f=cur.get('has_a1f', False) or nxt.get('has_a1f', False),
            m_genre_hint=cur.get('genre_hint'),
            s_genre_hint=nxt.get('genre_hint'),
        )
        used_notch_db = tp['notch_db']
        used_smooth_eq = tp['smooth_eq']

        # Resolve cf_bars (--cf-bars manual override wins)
        resolved_cf_bars = resolve_cf_bars(cf_bars, m_a1f_label, s_a1f_label,
                                            m_a1f_label=m_a1f_label, s_a1f_label=s_a1f_label,
                                            has_a1f=cur.get('has_a1f', False) or nxt.get('has_a1f', False),
                                            m_genre_hint=cur.get('genre_hint'),
                                            s_genre_hint=nxt.get('genre_hint'))
        print(f"    Transition: {m_a1f_label}→{s_a1f_label} | "
              f"cf_bars={resolved_cf_bars} | notch_db={used_notch_db} | smooth_eq={used_smooth_eq}")

        # Recompute exit with actual cf_bars using best_exit_bar_v2
        # Pass bar_labels list to best_exit_bar_v2
        a1f_bar_labels_m = a1f_m['bar_labels'] if a1f_m and a1f_m.get('bar_labels') else None
        if not (use_quiet_exit and cur['qe'] is not None):
            total = len(cur['db']) - 1
            min_bar = int(MIN_PLAY_FRACTION * total)
            default_exit = max(min_bar, total - resolved_cf_bars - 4)
            exit_bar, exit_label = best_exit_bar_v2(
                a1f_bar_labels_m, cur['secs'], default_exit, total, resolved_cf_bars,
                vocal_mask=vpb_m, min_bar=min_bar
            )
            # Re-resolve m_a1f_label after exit may have shifted
            m_a1f_label = _a1f_label(a1f_m, exit_bar, cur['secs'])

        # ── Downbeat snapping ────────────────────────────────────────────────
        snapped = snap_bar(exit_bar, PHRASE_GRID)
        if snapped != exit_bar and snapped >= resolved_cf_bars and snapped <= len(cur['db']) - 1 - resolved_cf_bars:
            s_label_new = _a1f_label(a1f_m, snapped, cur['secs'])
            exit_label_new = A1F_PRIORITY.get(s_label_new, 3) if (a1f_m and a1f_m.get('bar_labels')) else EXIT_SCORE.get(s_label_new, 2)
            exit_label_old = A1F_PRIORITY.get(exit_label, 3) if (a1f_m and a1f_m.get('bar_labels')) else EXIT_SCORE.get(exit_label, 2)
            if exit_label_new <= exit_label_old + 1:
                print(f"    ↳ Downbeat snap: exit {exit_bar}→{snapped}")
                exit_bar = snapped
                m_a1f_label = _a1f_label(a1f_m, exit_bar, cur['secs'])

        mode = 'hpss'
        cf_len = int(resolved_cf_bars * bar_s(mb) * sr)

        exit_samp = int(cur['db'][min(exit_bar, len(cur['db']) - 1)])
        body = cur['audio'][cur_off:exit_samp]
        exit_a1f = _a1f_label(a1f_m, exit_bar, cur['secs'])
        print(f"    Master exit bar {exit_bar} ({exit_samp / sr:.1f}s)  [{exit_a1f}]  mode={mode}  cf_len={cf_len/sr:.1f}s")

        m_cf = cur['audio'][exit_samp:exit_samp + cf_len + sr * 3]
        m_cf_db = cur['db'][cur['db'] >= exit_samp] - exit_samp

        # ── Slave entry with A1F + drum check + auto-loop ───────────────────
        s_entry = nxt['se']
        original_s_entry = s_entry  # save for fallback
        s_entry = snap_bar(s_entry, PHRASE_GRID)

        # Drum activity check: if slave intro has no drums, skip it
        s_entry_a1f = _a1f_label(a1f_s, s_entry, nxt['secs'])
        s_entry_samp = int(nxt['db'][min(s_entry, len(nxt['db']) - 1)])
        check_dur = int(min(8 * bar_s(sb) * sr, len(nxt['audio']) - s_entry_samp))
        drum_ratio = drum_activity(nxt['audio'][s_entry_samp:s_entry_samp + check_dur], sr)
        ambient_blend_fallback = False

        if drum_ratio < 0.15:
            print(f"    ⚠ No drums at entry (drum_ratio={drum_ratio:.2f}) — searching nearby (limit={DRUM_SEARCH_LIMIT} bars)")
            max_search = min(s_entry + DRUM_SEARCH_LIMIT, len(nxt['db']) - resolved_cf_bars)
            found_drums = False
            for shift_bar in range(s_entry + 4, max_search, 4):
                ss = int(nxt['db'][shift_bar])
                dr = drum_activity(nxt['audio'][ss:ss + check_dur], sr)
                if dr >= 0.15:
                    s_entry = snap_bar(shift_bar, PHRASE_GRID)
                    s_entry_a1f = _a1f_label(a1f_s, s_entry, nxt['secs'])
                    print(f"    → Drums found at bar {s_entry} ({s_entry_a1f})")
                    found_drums = True
                    break
            if not found_drums:
                print(f"    → No drums within {DRUM_SEARCH_LIMIT} bars. Activating Ambient Blend fallback!")
                s_entry = snap_bar(original_s_entry, PHRASE_GRID)
                s_entry_a1f = _a1f_label(a1f_s, s_entry, nxt['secs'])
                resolved_cf_bars = 16
                cf_len = int(resolved_cf_bars * bar_s(mb) * sr)
                mode = 'quiet'
                ambient_blend_fallback = True

        s_samp = int(nxt['db'][min(s_entry, len(nxt['db']) - 1)])
        s_cf = nxt['audio'][s_samp:]
        s_cf_db = nxt['db'][nxt['db'] >= s_samp] - s_samp
        print(f"    Slave entry bar {s_entry} ({s_samp / sr:.1f}s)  [{s_entry_a1f}]  drums={drum_ratio:.2f}")

        # ── Auto-looping for short intro with drums ──────────────────────────
        if s_entry_a1f in ('intro', 'inst', 'start') and resolved_cf_bars >= 8:
            # Count how many bars of intro we have
            intro_count = 0
            s_bi = s_entry
            a1f_bar_labels_s = a1f_s['bar_labels'] if a1f_s and a1f_s.get('bar_labels') else None
            while s_bi < len(a1f_bar_labels_s) if a1f_bar_labels_s else 0:
                lbl = a1f_bar_labels_s[s_bi] if a1f_bar_labels_s else section_at_bar(nxt['secs'], s_bi)
                if lbl in ('intro', 'inst', 'start'):
                    intro_count += 1
                    s_bi += 1
                else:
                    break
            if 2 <= intro_count < resolved_cf_bars:
                loop_len = intro_count
                target = max(loop_len + 4, min(resolved_cf_bars, 16))
                looped = dynamic_loop(nxt['audio'][s_samp:s_samp + int(loop_len * bar_s(sb) * sr)],
                                      sr, sb, loop_len, target)
                s_cf = np.concatenate([looped, nxt['audio'][s_samp + int(loop_len * bar_s(sb) * sr):]])
                print(f"    Auto-looped intro: {loop_len}→{target} bars")

        # ── Vocal Clash Detection → Notch Flag ────────────────────────────
        # Instead of blocking, we set vocal_clash=True which activates
        # vocal_notch_sweep() inside build_cf_lr4 to duck master's mid-range.
        vocal_clash_flag = False
        if ambient_blend_fallback:
            vocal_clash_flag = True
            print(f"    ↳ Ambient Blend fallback active — forcing Vocal Notch Sweep")
        elif vpb_m is not None and vpb_s is not None:
            m_vox_end = min(exit_bar + resolved_cf_bars, len(vpb_m))
            s_vox_end = min(s_entry + resolved_cf_bars, len(vpb_s))
            m_has_vox = vpb_m[exit_bar:m_vox_end].any() if exit_bar < len(vpb_m) else False
            s_has_vox = vpb_s[s_entry:s_vox_end].any() if s_entry < len(vpb_s) else False
            if m_has_vox and s_has_vox:
                vocal_clash_flag = True
                print(f"    ⚠ VAD clash detected — activating Vocal Notch Sweep")

        # Finalize sections after VAD override
        exit_samp = int(cur['db'][min(exit_bar, len(cur['db']) - 1)])
        body = cur['audio'][cur_off:exit_samp]
        m_cf = cur['audio'][exit_samp:exit_samp + cf_len + sr * 3]
        m_cf_db = cur['db'][cur['db'] >= exit_samp] - exit_samp

        # Calculate entry RMS for ramp decision
        ec = int(2 * bar_s(sb) * sr)
        entry_segment = nxt['audio'][s_samp:s_samp + ec] if ec < len(nxt['audio'][s_samp:]) else nxt['audio'][s_samp:]
        entry_rms = float(np.sqrt(np.mean(entry_segment**2)))

        # NOTE: Per-section LUFS gain matching REMOVED.
        # All tracks are pre-normalized to TARGET_LUFS=-14 at load time.
        # Applying per-CF gain caused artificial volume pumping:
        #   - QUIET exit (low RMS) → slave gained down → jump UP after CF
        #   - ACTIVE exit (high RMS) → slave gained up → drop after CF
        # Let equal-power crossfade handle natural level differences.
        lufs_gain = 1.0

        blended, shift, consumed, warp_extra = build_cf_lr4(
            m_cf, s_cf, mb, sb, m_cf_db, s_cf_db, mode, cf_bars=resolved_cf_bars, sr=sr,
            stabilizer=stabilizer, vocal_clash=vocal_clash_flag,
            notch_db=used_notch_db, smooth_eq=used_smooth_eq
        )

        # ── AI Transition check ────────────────────────────────────────────
        ai_loaded = None
        if transitions_dir:
            a_name = cur['name'].replace(' ', '_')
            b_name = nxt['name'].replace(' ', '_')
            # ищем: trN_A_to_B.wav
            for fname in os.listdir(transitions_dir):
                if fname.endswith('.wav') and a_name in fname and '_to_' in fname and b_name in fname:
                    ai_path = os.path.join(transitions_dir, fname)
                    try:
                        ai_loaded, _ = librosa.load(ai_path, sr=sr, mono=False)
                        if ai_loaded.ndim == 1:
                            ai_loaded = np.stack([ai_loaded, ai_loaded], axis=1)
                        elif ai_loaded.shape[0] == 2:
                            ai_loaded = ai_loaded.T  # (samples, ch)
                        ai_dur = len(ai_loaded) / sr
                        print(f"    AI transition found: {fname} ({ai_dur:.1f}s)")
                    except Exception as e:
                        print(f"    AI transition load failed: {e}")
                    break

        if ai_loaded is not None:
            # ── AI-blend mode ──────────────────────────────────────────────
            # 2-bar crossfade: body → AI → slave
            cf2 = int(2 * bar_s(mb) * sr)
            bf_ms = int(0.020 * sr)  # 20ms micro crossfade

            # Crossfade body tail into AI transition
            body_tail = body[-cf2:]
            ai_head = ai_loaded[:cf2]
            fade_out = np.linspace(1.0, 0.0, cf2).astype("float32")[:, None]
            fade_in = np.linspace(0.0, 1.0, cf2).astype("float32")[:, None]
            xtail = body_tail * fade_out + ai_head * fade_in

            # Crossfade AI transition into slave entry
            ai_tail = ai_loaded[-cf2:]
            s_head = s_cf[:cf2]
            fade_out2 = np.linspace(1.0, 0.0, cf2).astype("float32")[:, None]
            fade_in2  = np.linspace(0.0, 1.0, cf2).astype("float32")[:, None]
            xtail2 = ai_tail * fade_out2 + s_head * fade_in2

            # 20ms micro crossfade at AI body-to-slave boundary
            ai_body = ai_loaded[cf2:-cf2]
            parts.append(np.concatenate([
                body[:-cf2], xtail,
                ai_body, xtail2,
                s_cf[cf2:]
            ]))
            mix_pos += len(body) + len(ai_loaded) + len(s_cf) - cf2
            # Skip normal blend→ramp
            stamp_entry_rms = entry_rms
            # Update cur_off to end of slave entry (AI branch)
            cur_off = s_samp + int(resolved_cf_bars * bar_s(sb) * sr) // 2
            cur = nxt
            continue  # skip everything below

        ts = (mix_pos + len(body)) / sr
        stamps.append({
            'from': cur['name'], 'to': nxt['name'],
            'from_key': cur.get('cam', '?'), 'to_key': nxt.get('cam', '?'),
            'key_compat': key_compat(cur.get('key', '?'), nxt.get('key', '?')),
            't': ts, 'dur': resolved_cf_bars * bar_s(mb), 'mode': mode,
            'shift': shift / sr, 'entry_rms': entry_rms
        })

        parts.append(body)
        mix_pos += len(body)

        cur = nxt
        ramp_off = s_samp + consumed

        ramp_audio = nxt['audio'][ramp_off:]
        ramp_db = nxt['db'][nxt['db'] >= ramp_off] - ramp_off
        
        # If BPM transition was active, Master ramped to Slave's native BPM,
        # so Slave is already playing at its native speed. Skip the ramp.
        effective_mb = sb if (abs(mb - sb) / mb > 0.05) else mb
        ramp_result, ramp_consumed = ramp_to_native(
            ramp_audio, ramp_db, effective_mb, sb, sr, ser=entry_rms
        )

        if ramp_result is not None:
            # ── Apply lufs_gain to ramp, fade back to 1.0 ────────────────────
            # Without this, s_cf is gained but ramp_result stays at original
            # level → hard volume jump right after crossfade.
            if abs(lufs_gain - 1.0) > 0.05:
                n = len(ramp_result)
                gain_env = np.linspace(lufs_gain, 1.0, n, dtype=np.float32)[:, None]
                ramp_result = ramp_result * gain_env

            # ── Seamless blend→ramp boundary ─────────────────────────────────
            # blended (LR4-processed crossfade) is followed by ramp_result
            # (raw pyrubberband bars at master BPM → ramped to native BPM).
            # The LR4 processing + RMS stabilizer phase-shifts the audio,
            # creating a hard boundary.  Crossfade last/first 20ms to fix it.
            if warp_extra is not None:
                ramp_result = np.concatenate([warp_extra, ramp_result])
            # Crossfade between blended tail and ramp_result head
            bf_ms = int(0.020 * sr)  # 20ms crossfade
            if len(blended) >= bf_ms and len(ramp_result) >= bf_ms:
                fade_out = np.linspace(1.0, 0.0, bf_ms).astype("float32")[:, None]
                fade_in = np.linspace(0.0, 1.0, bf_ms).astype("float32")[:, None]
                blended_tail = blended[-bf_ms:] * fade_out
                ramp_head = ramp_result[:bf_ms] * fade_in
                smooth_boundary = blended_tail + ramp_head
                blended = np.concatenate([blended[:-bf_ms], smooth_boundary])
                ramp_result = ramp_result[bf_ms:]
            print(f"    blend->ramp: seamless {warp_extra is not None}")
            parts.append(blended)
            mix_pos += len(blended)
            parts.append(ramp_result)
            mix_pos += len(ramp_result)
            cur_off = ramp_off + ramp_consumed
        else:
            parts.append(blended)
            mix_pos += len(blended)
            # When ramp_result is None (same BPM), the slave body starts
            # immediately after blended. Apply a short gain ramp to avoid
            # a hard volume jump if lufs_gain was applied to the CF zone.
            if abs(lufs_gain - 1.0) > 0.05:
                fade_bars = 4
                fade_len = min(int(fade_bars * bar_s(sb) * sr),
                               len(cur['audio']) - ramp_off)
                if fade_len > 0:
                    gain_env = np.linspace(lufs_gain, 1.0, fade_len,
                                           dtype=np.float32)[:, None]
                    slave_fade = cur['audio'][ramp_off:ramp_off + fade_len] * gain_env
                    parts.append(slave_fade)
                    mix_pos += fade_len
                    cur_off = ramp_off + fade_len
                else:
                    cur_off = ramp_off
            else:
                cur_off = ramp_off

        if cur_off >= len(cur['audio']):
            cur_off = s_samp + int(resolved_cf_bars * bar_s(sb) * sr) // 2
        print(f"    Slave continues at {cur_off / sr:.1f}s\n")

    parts.append(cur['audio'][cur_off:])

    print("Concatenating...")
    mix = np.concatenate([p for p in parts if len(p) > 0])

    # Soft clipper — smooth transient compression using tanh, preserving total RMS
    mix = soft_clipper_tanh(mix, threshold=0.707)

    dur = len(mix) / sr
    print(f"Total mix duration: {int(dur // 60)}:{int(dur % 60):02d}")

    wav_out = os.path.splitext(output_mp3)[0] + '.wav'
    if os.path.abspath(wav_out) == os.path.abspath(output_mp3):
        wav_out += '_master.wav'
    print("Exporting WAV...")
    sf.write(wav_out, mix, sr, subtype="PCM_24")

    # Build title + metadata
    today = time.strftime("%Y-%m-%d")
    mp3_title = f"AutoDJ Mix"
    mp3_artist = "AutoDJ Mixer"
    if style:
        mp3_title = f"{style} Mix"
    if author:
        mp3_artist = author
    print(f"Encoding MP3 ({bitrate})...")
    r = subprocess.run([
        "ffmpeg", "-y", "-i", wav_out, "-b:a", bitrate,
        "-id3v2_version", "3",
        "-metadata", f"title={mp3_title}",
        "-metadata", f"artist={mp3_artist}",
        output_mp3
    ], capture_output=True, text=True)

    if r.returncode:
        print(f"  FFmpeg error: {r.stderr[-300:]}")
    else:
        sz = os.path.getsize(output_mp3) / 1e6
        print(f"  MP3: {output_mp3} ({sz:.1f} MB)")
        sz_wav = os.path.getsize(wav_out) / 1e6
        print(f"  WAV (24-bit master): {wav_out} ({sz_wav:.1f} MB)")

    print("\n=== TRANSITIONS ===")
    for st in stamps:
        m = int(st['t'] // 60)
        s = int(st['t'] % 60)
        m2 = int((st['t'] + st['dur']) // 60)
        s2 = int((st['t'] + st['dur']) % 60)
        kc = st.get('key_compat', 0)
        kc_label = "SAME" if kc >= 1.0 else "ADJ" if kc >= 0.9 else "REL" if kc >= 0.8 else "POOR"
        print(
            f"  {m:02d}:{s:02d}-{m2:02d}:{s2:02d}  "
            f"{st['from']} -> {st['to']}  "
            f"[{'BASS SWAP' if st['mode'] == 'hpss' else 'QUIET CROSS'}]  "
            f"{st.get('from_key','?')}→{st.get('to_key','?')} [{kc_label}]  "
            f"micro_shift={st['shift'] * 1000:.1f}ms  "
            f"entry_rms={st.get('entry_rms', 0):.4f}"
        )

    total_t = time.time() - t_start
    print(f"\nCompleted in {total_t:.1f}s")

    # Save stamps alongside output for analyzer
    if output_mp3:
        stamps_path = output_mp3.replace('.mp3', '_stamps.npy')
        np.save(stamps_path, np.array(stamps, dtype=object), allow_pickle=True)
        print(f"  Stamps saved → {stamps_path}")

    return stamps


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoDJ Smart Mixer (v7+v13)")
    parser.add_argument("--wav-dir", required=True, help="Directory with WAV files")
    parser.add_argument("--ann-dir", required=True, help="Directory with madmom annotation files")
    parser.add_argument("--output", default=None, help="Output MP3 path (default: auto-generated from style+date)")
    parser.add_argument("--style", default=None, help="Genre/style name (e.g. 'Melodic House', 'Techno')")
    parser.add_argument("--author", default=None, help="DJ/artist name for metadata")
    parser.add_argument("--bitrate", default="320k", help="MP3 bitrate (default: 320k)")
    parser.add_argument("--config", help="Python config file with TRACKS list")
    parser.add_argument("--use-quiet-exit", action="store_true", help="Exit on QUIET/BUILD section (shorter mix)")
    parser.add_argument("--no-stabilizer", action="store_true", help="Disable RMS stabilizer (may increase dips, less pumping)")
    parser.add_argument("--transitions-dir", default=None, help="Directory with pre-generated AI transition WAV files")
    parser.add_argument("--cf-bars", default="auto", help="Crossfade length: 'auto' (dynamic based on sections) or integer bars (1-64)")
    parser.add_argument("--analysis-mode", default="a1f", choices=["a1f", "a1f_fast", "no_a1f"],
                        help="Analysis mode: 'a1f' (full Demucs, default), 'a1f_fast' (skip Demucs), 'no_a1f' (skip neural)")
    args = parser.parse_args()

    # Auto-generate output filename if not provided
    if args.output is None:
        today = datetime.now().strftime("%Y-%m-%d")
        base = today
        if args.style:
            base = f"{args.style} Mix {today}"
        args.output = base.replace(" ", "_") + ".mp3"

    if args.config:
        import importlib.util
        spec = importlib.util.spec_from_file_location("config", args.config)
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        tracks = cfg.TRACKS
    else:
        # Auto-discover: pair .wav with .txt files by matching base names
        wav_files = sorted(f for f in os.listdir(args.wav_dir) if f.endswith('.wav'))
        tracks = []
        for wf in wav_files:
            base = os.path.splitext(wf)[0]
            ann = base + '.txt'
            if os.path.exists(os.path.join(args.ann_dir, ann)):
                name = base.split(' - ')[0] if ' - ' in base else base[:20]
                tracks.append((name, wf, ann))
            else:
                print(f"  Warning: no annotation for {wf}, skipping")

        if not tracks:
            print("No tracks found. Provide WAV files in --wav-dir with matching .txt annotations in --ann-dir")
            sys.exit(1)

    mix_tracks(tracks, args.wav_dir, args.ann_dir, args.output, args.bitrate,
               style=args.style, author=args.author,
               use_quiet_exit=args.use_quiet_exit, stabilizer=not args.no_stabilizer,
               transitions_dir=args.transitions_dir, cf_bars=args.cf_bars,
               analysis_mode=args.analysis_mode)