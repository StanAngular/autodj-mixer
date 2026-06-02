#!/usr/bin/env python3
"""
Run Pipeline — Mix + Analyze + Validate in one command.
Runs smart_mixer.py to create a mix, mix_analyzer.py to diagnose it,
then mix_validator.py to issue PASS/WARN/FAIL verdict.

Usage:
  python3 run_pipeline.py --wav-dir ./wav --ann-dir ./annotations --output mix.mp3
  python3 run_pipeline.py --config mix_config.py
  python3 run_pipeline.py --config mix_config.py --analyze-only
  python3 run_pipeline.py --config mix_config.py --feedback
  python3 run_pipeline.py --config mix_config.py --strict

Exit codes:
  0 = mix complete, validation PASS
  1 = mix complete, validation WARN
  2 = mix complete, validation FAIL
  3 = mixer or analyzer error
"""
import sys, os, subprocess, argparse, importlib.util, time

def main():
    parser = argparse.ArgumentParser(description="Mix + Analyze + Validate pipeline")
    parser.add_argument("--wav-dir", help="Source WAV directory")
    parser.add_argument("--ann-dir", help="Annotation directory")
    parser.add_argument("--output", default="/tmp/mix.mp3", help="Output MP3 path")
    parser.add_argument("--bitrate", default="320k", help="MP3 bitrate")
    parser.add_argument("--config", help="Python config file with TRACKS list")
    parser.add_argument("--analyze-only", action="store_true",
                        help="Skip mixing, only analyze existing mix")
    parser.add_argument("--feedback", action="store_true",
                        help="Generate tuning recommendations")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip Step 3 validation")
    parser.add_argument("--strict", action="store_true",
                        help="Pass --strict to mix_validator (tighter thresholds)")
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
    mixer    = os.path.join(script_dir, "smart_mixer.py")
    analyzer = os.path.join(script_dir, "mix_analyzer.py")
    validator = os.path.join(script_dir, "mix_validator.py")

    # JSON analysis goes next to the mix output
    json_out = output.rsplit('.', 1)[0] + '_analysis.json'

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

        if args.config:
            cmd += ["--config", args.config]

        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\n❌ Mixer failed with exit code {result.returncode}")
            sys.exit(3)

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
                   "--ann-dir", ann_dir,
                   "--json-out", json_out]

    if args.config:
        analyze_cmd += ["--config", args.config]
    if args.feedback:
        analyze_cmd += ["--feedback"]

    result = subprocess.run(analyze_cmd)
    if result.returncode != 0:
        print(f"\n❌ Analyzer failed with exit code {result.returncode}")
        sys.exit(3)

    print(f"\n  Analysis completed in {time.time()-t1:.1f}s")

    if args.no_validate:
        if args.feedback:
            print("\n  Recommendations above. Apply to smart_mixer.py constants and re-run.")
        sys.exit(0)

    # ─── Step 3: Validate ───────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  Step 3: Validating mix quality")
    print("=" * 55)

    validate_cmd = [sys.executable, validator, "--json", json_out]
    if args.strict:
        validate_cmd += ["--strict"]

    result = subprocess.run(validate_cmd)
    # Propagate validator exit code (0=PASS, 1=WARN, 2=FAIL)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()