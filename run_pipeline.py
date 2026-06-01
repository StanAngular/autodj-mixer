#!/usr/bin/env python3
"""
Run Pipeline — Mix + Analyze in one command.
Runs smart_mixer.py to create a mix, then mix_analyzer.py to diagnose it.

Usage:
  python3 run_pipeline.py --wav-dir ./wav --ann-dir ./annotations --output mix.mp3
  python3 run_pipeline.py --config mix_config.py
  python3 run_pipeline.py --config mix_config.py --analyze-only
  python3 run_pipeline.py --config mix_config.py --feedback
"""
import sys, os, subprocess, argparse, importlib.util, time

def main():
    parser = argparse.ArgumentParser(description="Mix + Analyze pipeline")
    parser.add_argument("--wav-dir", help="Source WAV directory")
    parser.add_argument("--ann-dir", help="Annotation directory")
    parser.add_argument("--output", default="/tmp/mix.mp3", help="Output MP3 path")
    parser.add_argument("--bitrate", default="320k", help="MP3 bitrate")
    parser.add_argument("--config", help="Python config file with TRACKS list")
    parser.add_argument("--analyze-only", action="store_true",
                        help="Skip mixing, only analyze existing mix")
    parser.add_argument("--feedback", action="store_true",
                        help="Generate tuning recommendations")
    args = parser.parse_args()

    wav_dir = args.wav_dir
    ann_dir = args.ann_dir
    bitrate = args.bitrate
    output = args.output

    # Load config if provided
    tracks_cli = []
    if args.config:
        spec = importlib.util.spec_from_file_location("cfg", args.config)
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        tracks_cli = cfg.TRACKS
        if wav_dir is None:
            wav_dir = getattr(cfg, 'WAV_DIR', '/tmp/wav')
        if ann_dir is None:
            ann_dir = getattr(cfg, 'ANN_DIR', '/tmp/ann')

    if not wav_dir or not ann_dir:
        parser.error("--wav-dir and --ann-dir are required (or use --config)")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    mixer = os.path.join(script_dir, "smart_mixer.py")
    analyzer = os.path.join(script_dir, "mix_analyzer.py")

    # ─── Step 1: Mix ────────────────────────────────────────────────
    if not args.analyze_only:
        print("=" * 55)
        print("  Step 1: Mixing tracks")
        print("=" * 55)
        t0 = time.time()

        cmd = [sys.executable, mixer,
               "--wav-dir", wav_dir,
               "--ann-dir", ann_dir,
               "--output", output,
               "--bitrate", bitrate]

        # If config has TRACKS, pass it as --config
        if args.config:
            cmd += ["--config", args.config]

        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\n❌ Mixer failed with exit code {result.returncode}")
            sys.exit(1)

        mix_time = time.time() - t0
        print(f"\n  Mix completed in {mix_time:.1f}s\n")

    # ─── Step 2: Analyze ────────────────────────────────────────────
    print("=" * 55)
    print("  Step 2: Analyzing mix quality")
    print("=" * 55)
    t1 = time.time()

    analyze_cmd = [sys.executable, analyzer,
                   "--mix", output,
                   "--wav-dir", wav_dir,
                   "--ann-dir", ann_dir]

    if args.config:
        analyze_cmd += ["--config", args.config]
    if args.feedback:
        analyze_cmd += ["--feedback"]

    result = subprocess.run(analyze_cmd)
    if result.returncode != 0:
        print(f"\n❌ Analyzer failed with exit code {result.returncode}")
        sys.exit(1)

    total = time.time() - t1
    print(f"\n  Analysis completed in {total:.1f}s")

    # Summary
    if args.feedback:
        print("\n  Recommendations above. Apply to smart_mixer.py constants and re-run.")

if __name__ == "__main__":
    main()