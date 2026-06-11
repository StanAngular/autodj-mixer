#!/usr/bin/env python3
"""
delete_tracks.py — interactively delete tracks from the catalog.

Lists all cataloged tracks with their YouTube URLs, prompts for which
track(s) to delete by video ID, and removes:
  - The WAV from shared/tracks/
  - The ANN from shared/ann/
  - The A1F JSON from shared/a1f_results/
  - The entry from catalog_index.json

Usage:
  uv run python3 shared/catalog/delete_tracks.py
"""

import json
import os
import sys
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────
# This file lives at shared/catalog/delete_tracks.py
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))          # shared/catalog/
PROJECT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))      # autodj-mixer/
CATALOG_DIR = SCRIPT_DIR                                         # shared/catalog/
A1F_DIR = os.path.join(CATALOG_DIR, 'a1f_results')
TRACKS_DIR = os.path.join(PROJECT_DIR, 'shared', 'tracks')
ANN_DIR = os.path.join(PROJECT_DIR, 'shared', 'ann')
INDEX_PATH = os.path.join(CATALOG_DIR, 'catalog_index.json')

os.makedirs(A1F_DIR, exist_ok=True)


def load_index():
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH) as f:
            return json.load(f)
    return {"version": 1, "created": datetime.now().strftime("%Y-%m-%d"), "tracks": {}}


def save_index(index):
    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def list_tracks(index):
    """Display all tracks with index numbers and YouTube URLs."""
    tracks = sorted(index["tracks"].items())
    if not tracks:
        print("No tracks in catalog.")
        return tracks

    print(f"\n{'#':>3}  {'Video ID':<14}  {'Title':<40}  {'Artist':<20}  {'YouTube URL'}")
    print('-' * 120)
    for i, (vid, info) in enumerate(tracks, 1):
        title = (info.get('title') or '?')[:38]
        artist = (info.get('artist') or '?')[:18]
        url = info.get('youtube_url', '')
        print(f"{i:>3}  {vid:<14}  {title:<40}  {artist:<20}  {url}")
    return tracks


def delete_track(video_id, index):
    """Remove a track's files and catalog entry."""
    info = index["tracks"].get(video_id)
    if not info:
        print(f"  ❌ Track {video_id} not found in index.")
        return False

    title = info.get('title', video_id)
    artist = info.get('artist', '?')
    print(f"\n  Deleting: {artist} - {title} ({video_id})")

    # Files to delete
    wav_path = os.path.join(TRACKS_DIR, f"{video_id}.wav")
    ann_path = os.path.join(ANN_DIR, f"{video_id}.ann")
    a1f_path = os.path.join(A1F_DIR, f"{video_id}.json")
    meta_path = os.path.join(A1F_DIR, f"{video_id}.meta.json")

    deleted_any = False
    for label, path in [("WAV", wav_path), ("ANN", ann_path),
                         ("A1F JSON", a1f_path), ("Meta JSON", meta_path)]:
        if os.path.exists(path):
            os.remove(path)
            print(f"    ✓ Deleted {label}: {path}")
            deleted_any = True
        else:
            print(f"    - {label} not found (skipped)")

    # Remove from index
    del index["tracks"][video_id]
    save_index(index)
    print(f"    ✓ Removed from catalog index")
    return True


def main():
    index = load_index()
    tracks = list_tracks(index)

    if not tracks:
        return

    print("\nEnter video ID(s) to delete (comma/space separated), or 'q' to quit.")
    choice = input("> ").strip()

    if choice.lower() in ('q', 'quit', 'exit', ''):
        print("Exiting.")
        return

    # Parse IDs: split by comma or whitespace, strip whitespace
    ids = []
    for part in choice.replace(',', ' ').split():
        part = part.strip()
        if part:
            ids.append(part)

    if not ids:
        print("No IDs entered.")
        return

    # Check which IDs exist in catalog
    valid_ids = [vid for vid in ids if vid in index["tracks"]]
    unknown_ids = [vid for vid in ids if vid not in index["tracks"]]

    if unknown_ids:
        print(f"\n  ⚠ Unknown IDs (not in catalog): {', '.join(unknown_ids)}")

    if not valid_ids:
        print("No valid IDs to delete.")
        return

    print(f"\nReady to delete {len(valid_ids)} track(s):")
    for vid in valid_ids:
        info = index["tracks"][vid]
        print(f"  - {info.get('artist','?')} - {info.get('title','?')} ({vid})")

    confirm = input("\nProceed? (y/N): ").strip().lower()
    if confirm not in ('y', 'yes'):
        print("Cancelled.")
        return

    for vid in valid_ids:
        delete_track(vid, index)

    print(f"\nDone. {len(valid_ids)} track(s) deleted.")


if __name__ == '__main__':
    main()