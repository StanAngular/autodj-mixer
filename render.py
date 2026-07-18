#!/usr/bin/env python3
"""
render.py — Universal track renderer

Usage:
  python render.py styles/cosmic_techno.json
  python render.py styles/melodic_house.json
  python render.py styles/dark_industrial.json

Style JSON defines everything: BPM, key, elements, automation.
No code needed to create a new style — just write a JSON file.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from music_engine import MusicEngine, load_style

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python render.py styles/<style>.json")
        print("\nAvailable styles:")
        styles_dir = os.path.join(os.path.dirname(__file__), "styles")
        for f in sorted(os.listdir(styles_dir)):
            if f.endswith('.json'):
                print(f"  styles/{f}")
        sys.exit(1)

    style_path = sys.argv[1]
    style = load_style(style_path)

    # Optional: override output path from CLI
    if len(sys.argv) >= 3:
        style['meta']['out'] = sys.argv[2]

    engine = MusicEngine(style)
    engine.render()
