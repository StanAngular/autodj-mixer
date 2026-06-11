#!/usr/bin/env python3
"""
catalog_utils.py — check if a track is in the catalog, returns cached analysis.
Used by the pipeline to skip re-analysis.

Usage:
  from catalog_utils import lookup_track, add_to_catalog
  
  result = lookup_track("ADBKdSCbmiM")
  if result:
      print(f"BPM: {result['bpm']}, structure: {len(result['structure'])} segments")
  
  add_to_catalog("ADBKdSCbmiM", "/path/to/a1f.json", title="...", artist="...")
"""
import json, os, shutil
from datetime import datetime

CATALOG_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(CATALOG_DIR, "catalog_index.json")
A1F_DIR = os.path.join(CATALOG_DIR, "a1f_results")

os.makedirs(A1F_DIR, exist_ok=True)

def load_index():
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH) as f:
            return json.load(f)
    return {"version": 1, "created": datetime.now().strftime("%Y-%m-%d"), "tracks": {}}

def save_index(index):
    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

def lookup_track(video_id):
    """Check if a track is in the catalog. Returns dict or None."""
    index = load_index()
    if video_id not in index["tracks"]:
        return None
    info = index["tracks"][video_id]
    a1f_path = os.path.join(CATALOG_DIR, info["a1f_file"])
    if os.path.exists(a1f_path):
        with open(a1f_path) as f:
            info["full_analysis"] = json.load(f)
    return info

def add_to_catalog(video_id, a1f_path, title="", artist="", youtube_url=""):
    """Add a track analysis to the catalog. Returns True on success.

    Args:
        video_id: YouTube video ID.
        a1f_path: Path to the A1F analysis JSON file.
        title: Track title.
        artist: Track artist/uploader.
        youtube_url: Full YouTube URL for the track.
    """
    if not os.path.exists(a1f_path):
        print(f"  ❌ File not found: {a1f_path}")
        return False

    with open(a1f_path) as f:
        data = json.load(f)

    dst = os.path.join(A1F_DIR, f"{video_id}.json")
    if os.path.abspath(a1f_path) != os.path.abspath(dst):
        shutil.copy2(a1f_path, dst)

    segments = data.get("segments", [])
    index = load_index()
    index["tracks"][video_id] = {
        "title": title,
        "artist": artist,
        "youtube_url": youtube_url,
        "bpm": data.get("bpm"),
        "duration": segments[-1]["end"] if segments else None,
        "structure": [{"start": s["start"], "end": s["end"], "label": s["label"]} for s in segments],
        "num_beats": len(data.get("beats", [])),
        "num_downbeats": len(data.get("downbeats", [])),
        "analyzed_at": datetime.now().isoformat(),
        "a1f_file": f"a1f_results/{video_id}.json"
    }
    save_index(index)
    return True

def list_all():
    """Get all cataloged tracks as a list of dicts."""
    index = load_index()
    return [(vid, info) for vid, info in sorted(index["tracks"].items())]

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        for vid, info in list_all():
            print(f"{vid} | {info.get('title','?')} | {info.get('artist','?')} | BPM {info.get('bpm','?')}")
    elif len(sys.argv) > 1:
        info = lookup_track(sys.argv[1])
        if info:
            print(f"✅ Found: {info.get('title')} — BPM {info.get('bpm')}, {len(info.get('structure',[]))} segments")
        else:
            print(f"❌ Not in catalog: {sys.argv[1]}")