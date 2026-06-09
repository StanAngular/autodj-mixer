#!/usr/bin/env python3
"""
update_catalog.py — add/update track analysis in the track catalog.
Usage:
  python3 update_catalog.py <video_id> <a1f_json_path> [--title "Track Title"] [--artist "Artist"]
  python3 update_catalog.py --check <video_id>   # check if exists
  python3 update_catalog.py --list               # list all cataloged tracks
"""
import json, os, sys, argparse, shutil
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
    print(f"  ✅ Catalog index updated ({len(index['tracks'])} tracks)")

def add_track(video_id, a1f_path, title=None, artist=None):
    if not os.path.exists(a1f_path):
        print(f"  ❌ File not found: {a1f_path}")
        return False

    with open(a1f_path) as f:
        data = json.load(f)

    # Copy to catalog
    dst = os.path.join(A1F_DIR, f"{video_id}.json")
    shutil.copy2(a1f_path, dst)

    # Extract metadata
    segments = data.get("segments", [])
    structure = [{"start": s["start"], "end": s["end"], "label": s["label"]} for s in segments]

    index = load_index()
    index["tracks"][video_id] = {
        "title": title or os.path.basename(a1f_path).replace(".json", ""),
        "artist": artist or "",
        "bpm": data.get("bpm"),
        "duration": segments[-1]["end"] if segments else None,
        "structure": structure,
        "num_beats": len(data.get("beats", [])),
        "num_downbeats": len(data.get("downbeats", [])),
        "analyzed_at": datetime.now().isoformat(),
        "a1f_file": f"a1f_results/{video_id}.json"
    }
    save_index(index)
    print(f"  ✅ Added {video_id} to catalog (BPM: {data.get('bpm')}, {len(segments)} segments)")
    return True

def check_track(video_id):
    index = load_index()
    if video_id in index["tracks"]:
        t = index["tracks"][video_id]
        print(f"  ✅ Found in catalog: {t.get('title')} — BPM {t.get('bpm')}, {t.get('num_segments', len(t.get('structure', [])))} segments")
        return True
    print(f"  ❌ Not in catalog: {video_id}")
    return False

def list_tracks():
    index = load_index()
    if not index["tracks"]:
        print("  📭 Catalog is empty")
        return
    print(f"  📚 Track Catalog ({len(index['tracks'])} tracks):")
    for vid, t in sorted(index["tracks"].items()):
        title = t.get("title", "?")
        bpm = t.get("bpm", "?")
        dur = t.get("duration", "?")
        if dur and dur != "?":
            dur = f"{dur:.0f}s"
        print(f"    {vid} | {title} | {bpm} BPM | {dur}")

def main():
    p = argparse.ArgumentParser(description="Track analysis catalog manager")
    p.add_argument("video_id", nargs="?", help="YouTube video ID")
    p.add_argument("a1f_json", nargs="?", help="Path to all-in-one-fix JSON")
    p.add_argument("--title", help="Track title")
    p.add_argument("--artist", help="Artist name")
    p.add_argument("--check", action="store_true", help="Check if track exists")
    p.add_argument("--list", action="store_true", help="List all cataloged tracks")
    args = p.parse_args()

    if args.list:
        list_tracks()
        return
    if args.check:
        if not args.video_id:
            print("Need video_id for --check")
            sys.exit(1)
        check_track(args.video_id)
        return
    if args.video_id and args.a1f_json:
        add_track(args.video_id, args.a1f_json, args.title, args.artist)
        return

    p.print_help()

if __name__ == "__main__":
    main()