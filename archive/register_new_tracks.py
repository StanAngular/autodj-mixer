#!/usr/bin/env python3
"""Register all new A1F results in catalog + run web genre search."""
import json, os, sys, glob

CATALOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shared', 'catalog')
A1F_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shared', 'a1f_results')
sys.path.insert(0, CATALOG_DIR)
from catalog_utils import add_to_catalog, lookup_track

# Known track names
TRACK_NAMES = {
    '5z6nKvaymHw': ('Gai Barone', 'Macula (Hernan Cattaneo & Simply City Remix)'),
    'RuX5XMAq64c': ('Trilucid', 'Hiera (Extended Mix)'),
    'OkhvrCpFIfw': ('Kasper Koman', 'Organist (Extended Mix)'),
    '8QXaeiKZ2m4': ('Rebel Of Sleep', 'Silent Memories (Extended Mix)'),
    'HF8PTa9H9Z0': ('Yotto & Tallac', 'Chemtrail Surfers (Extended Mix)'),
}

for vid, (artist, title) in TRACK_NAMES.items():
    json_path = os.path.join(A1F_DIR, f'{vid}.json')
    if not os.path.exists(json_path):
        print(f'⏳ {vid} — JSON not yet generated')
        continue
    
    existing = lookup_track(vid)
    if existing:
        print(f'✅ {vid} — already in catalog: {existing.get("title")}')
        continue
    
    print(f'📦 Registering {vid} ({title})...')
    ok = add_to_catalog(vid, json_path, title=title, artist=artist)
    if ok:
        print(f'   ✅ Registered')
    
print('Done.')
