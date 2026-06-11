#!/usr/bin/env python3
"""
enrich_metadata.py — enrich track catalog with yt-dlp metadata + A1F extended data.

For each track ID:
  1. Fetches yt-dlp metadata (artist, title, genre, year) → [ID].meta.json
  2. Extracts vocal_intervals from A1F segments → adds to A1F JSON
  3. Computes musical key via librosa → adds to A1F JSON

Usage:
  python3 enrich_metadata.py [--all] [--ids ID1 ID2 ...]
"""

import json, os, subprocess, sys, time, glob
import numpy as np
import soundfile as sf
import librosa

SR = 44100
A1F_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shared', 'a1f_results')
TRACKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shared', 'tracks')
ANN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shared', 'ann')

# ── Key detection (from smart_mixer.py) ───────────────────────────────
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
    chroma = librosa.feature.chroma_cqt(y=audio_mono, sr=sr)
    profile = chroma.mean(axis=1)
    best_corr, best_key = -1, "?"
    for shift in range(12):
        rolled = np.roll(profile, -shift)
        cm = np.corrcoef(rolled, MAJ_PROFILE)[0, 1]
        cn = np.corrcoef(rolled, MIN_PROFILE)[0, 1]
        if cm > best_corr:
            best_corr, best_key = cm, f"{KEYS[shift]} maj"
        if cn > best_corr:
            best_corr, best_key = cn, f"{KEYS[shift]} min"
    return best_key

def camelot_code(key_str):
    return CAMELOT.get(key_str, '?')


def fetch_ytdlp_meta(track_id):
    """Fetch metadata from YouTube via yt-dlp --dump-json."""
    url = f"https://www.youtube.com/watch?v={track_id}"
    try:
        r = subprocess.run(
            ['yt-dlp', '--proxy', 'socks5://127.0.0.1:40000',
             '--dump-json', url],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            print(f"  ⚠ yt-dlp failed for {track_id}: {r.stderr[:200]}")
            return None
        
        data = json.loads(r.stdout)
        meta = {
            'artist': data.get('uploader', ''),
            'track_title': data.get('title', ''),
            'upload_date': data.get('upload_date', ''),
            'duration_sec': data.get('duration', 0),
            'tags': data.get('tags', []),
            'categories': data.get('categories', []),
            'description': (data.get('description') or '')[:500],
            'youtube_url': url,
        }
        # Parse year from upload_date (YYYYMMDD)
        if meta['upload_date'] and len(meta['upload_date']) >= 4:
            meta['year'] = int(meta['upload_date'][:4])
        else:
            meta['year'] = 0
        
        # Extract genre from tags
        genre_keywords = {
            'house': 'House', 'techno': 'Techno', 'progressive': 'Progressive',
            'melodic': 'Melodic', 'trance': 'Trance', 'downtempo': 'Downtempo',
            'ambient': 'Ambient', 'electronic': 'Electronic', 'deep': 'Deep House',
        }
        all_text = ' '.join(meta['tags']).lower() + ' ' + meta.get('description', '').lower()
        meta['genre'] = 'Electronic'
        for kw, genre in genre_keywords.items():
            if kw in all_text:
                meta['genre'] = genre
                break

        # Russian track filter
        russian_keywords = ['русский', 'russian', 'москва', 'спб', 'россия', 'russia', 'санкт-петербург', 'московский']
        all_text_for_russian = ' '.join(meta.get('tags', [])).lower() + ' ' + meta.get('description', '').lower() + ' ' + meta.get('artist', '').lower() + ' ' + meta.get('track_title', '').lower()
        meta['is_russian'] = any(kw in all_text_for_russian for kw in russian_keywords)
        
        return meta
    except subprocess.TimeoutExpired:
        print(f"  ⚠ yt-dlp timed out for {track_id}")
        return None
    except Exception as e:
        print(f"  ⚠ yt-dlp error for {track_id}: {e}")
        return None


def extract_vocal_intervals(segments):
    """Extract vocal sections (verse, chorus, bridge) from A1F segments."""
    vocal_labels = ('verse', 'chorus', 'bridge')
    intervals = []
    for seg in segments:
        if seg.get('label', '') in vocal_labels:
            intervals.append({
                'start': seg['start'],
                'end': seg['end'],
                'label': seg['label'],
            })
    return intervals


def compute_key(wav_path):
    """Compute key + Camelot for a WAV file."""
    if not os.path.exists(wav_path):
        return None, None
    try:
        audio, sr = sf.read(wav_path, always_2d=True)
        mono = audio.mean(1) if audio.ndim == 2 else audio
        if len(mono) < sr * 10:
            return None, None
        # Use first 60s for speed
        mono = mono[:min(len(mono), sr * 60)]
        key = detect_key(mono, sr)
        cam = camelot_code(key)
        return key, cam
    except Exception as e:
        print(f"  ⚠ Key detection failed: {e}")
        return None, None


def enrich_track(track_id, force=False):
    """Enrich a single track with metadata + extended A1F data."""
    a1f_path = os.path.join(A1F_DIR, f"{track_id}.json")
    meta_path = os.path.join(A1F_DIR, f"{track_id}.meta.json")
    wav_path = os.path.join(TRACKS_DIR, f"{track_id}.wav")
    
    if not os.path.exists(a1f_path):
        print(f"  ⚠ No A1F JSON for {track_id}, skipping")
        return False
    
    # ── Step 1: yt-dlp metadata ──────────────────────────────────
    if not os.path.exists(meta_path) or force:
        print(f"  📡 Fetching yt-dlp metadata for {track_id}...")
        meta = fetch_ytdlp_meta(track_id)
        if meta:
            with open(meta_path, 'w') as f:
                json.dump(meta, f, indent=2)
            print(f"    ✓ Saved {meta_path}")
            print(f"      Artist: {meta['artist']}")
            print(f"      Title:  {meta['track_title']}")
            print(f"      Year:   {meta['year']}")
            print(f"      Genre:  {meta['genre']}")
            print(f"      Russian: {meta.get('is_russian', False)}")
            print(f"      URL:    {meta['youtube_url']}")
        else:
            print(f"    ⚠ Failed to fetch metadata")
    else:
        with open(meta_path) as f:
            meta = json.load(f)
        print(f"    ✓ Meta already cached: {meta.get('artist','?')} - {meta.get('track_title','?')}")
    
    # ── Step 2: Update A1F JSON with extended data ─────────────────
    with open(a1f_path) as f:
        a1f_data = json.load(f)
    
    needs_update = False
    
    # Vocal intervals from segments
    if 'vocal_intervals' not in a1f_data or force:
        segments = a1f_data.get('segments', [])
        a1f_data['vocal_intervals'] = extract_vocal_intervals(segments)
        needs_update = True
        n_vocal = len(a1f_data['vocal_intervals'])
        vocal_dur = sum(v['end'] - v['start'] for v in a1f_data['vocal_intervals'])
        total = (segments[-1]['end'] if segments else 1)
        print(f"    Vocal intervals: {n_vocal} zones, {vocal_dur:.0f}s ({vocal_dur/total*100:.0f}%)")
    
    # Musical key + Camelot
    if 'key' not in a1f_data or force:
        key, cam = compute_key(wav_path)
        if key:
            a1f_data['key'] = key
            a1f_data['camelot'] = cam
            needs_update = True
            print(f"    Key: {key} ({cam})")
    
    if needs_update:
        with open(a1f_path, 'w') as f:
            json.dump(a1f_data, f, indent=2)
        print(f"    ✓ A1F JSON updated with extended fields")
    
    return True


def main():
    import argparse
    p = argparse.ArgumentParser(description='Enrich track catalog with metadata')
    p.add_argument('--all', action='store_true', help='Process all tracks with A1F JSON')
    p.add_argument('--ids', nargs='*', help='Specific track IDs to process')
    p.add_argument('--force', action='store_true', help='Re-fetch even if cached')
    args = p.parse_args()
    
    os.makedirs(A1F_DIR, exist_ok=True)
    
    if args.ids:
        track_ids = [t.replace('.json', '') for t in args.ids]
    elif args.all:
        track_ids = sorted(set(
            f.replace('.json', '') for f in os.listdir(A1F_DIR) if f.endswith('.json') and not f.endswith('.meta.json')
        ))
    else:
        print("Specify --all or --ids")
        sys.exit(1)
    
    print(f"Enriching {len(track_ids)} tracks...")
    success = 0
    for tid in track_ids:
        print(f"\n[{track_ids.index(tid)+1}/{len(track_ids)}] {tid}")
        if enrich_track(tid, force=args.force):
            success += 1
        time.sleep(1)  # Rate limit
    
    print(f"\nDone: {success}/{len(track_ids)} enriched")


if __name__ == '__main__':
    main()