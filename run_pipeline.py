#!/usr/bin/env python3
"""
Run Pipeline — Pre-Analyze → Preview → [CONFIRM] → Mix → Analyze → Validate → Deliver.
Strict pipeline with gates between each stage.

MANDATORY STEPS (never skip without explicit flag):
  1. Pre-analysis: track order + BPM + Camelot
  2. Preview: transitions table sent to user for approval   ← HALT here by default
  3. [User confirms] → Full mix
  4. Analysis + Validate + Upload

Usage:
  python3 run_pipeline.py --config mix_config.py --feedback
  python3 run_pipeline.py --config mix_config.py --preview-only   # stop after preview
  python3 run_pipeline.py --config mix_config.py --no-preview     # skip confirm (CI/auto)
  python3 run_pipeline.py --config mix_config.py --analyze-only

Exit codes:
  0 = all PASS
  1 = mix complete, WARN (check output)
  2 = mix FAIL (problems found)
  3 = pipeline error
  4 = preview sent, awaiting confirmation (--preview-only)
"""
import sys, os, subprocess, argparse, importlib.util, time, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_config(config_path):
    """Load TRACKS list from config file."""
    spec = importlib.util.spec_from_file_location("cfg", config_path)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    tracks = cfg.TRACKS
    wav_dir = getattr(cfg, 'WAV_DIR', '.')
    ann_dir = getattr(cfg, 'ANN_DIR', '.')
    return tracks, wav_dir, ann_dir, cfg

def check_silence(mix_path, threshold=0.001, min_gap=2.0):
    """Check mix for silence gaps. Returns list of gaps."""
    try:
        import librosa
        import numpy as np
    except ImportError:
        return None  # can't check
    y, sr = librosa.load(mix_path, sr=None, mono=True)
    hop = 44100
    total = len(y) // sr
    gaps = []
    in_gap = False
    for i in range(total):
        frame = y[i*sr:(i+1)*sr]
        rms = np.sqrt(np.mean(frame**2))
        silent = rms < threshold
        if silent and not in_gap:
            gs = i
            in_gap = True
        elif not silent and in_gap:
            if i - gs >= min_gap:
                gaps.append((gs, i, i - gs))
            in_gap = False
    if in_gap and total - gs >= min_gap:
        gaps.append((gs, total, total - gs))
    return gaps

def check_exit_code(code, stage, output=None):
    """Check if a subprocess succeeded."""
    if code != 0:
        print(f"\n  ❌ {stage} failed (exit code {code})")
        if output:
            print(f"  Last output: {output[-500:]}")
        sys.exit(3)


def build_preview_table(tracks, wav_dir, ann_dir):
    """
    Build a preview transitions table from track annotations.
    Returns formatted string with track order, BPM, Camelot, estimated timestamps.
    """
    try:
        import numpy as np
    except ImportError:
        return None

    rows = []
    cumulative_s = 0.0
    CF_BARS = 16    # default crossfade length in bars
    EXIT_BARS = 8   # bars before track end used as exit point

    for i, track_def in enumerate(tracks):
        name = track_def[0]
        ann_file = track_def[2] if len(track_def) > 2 else None
        ann_path = os.path.join(ann_dir, ann_file) if ann_file else None

        bpm = None
        camelot = "?"
        track_dur_s = None

        if ann_path and os.path.exists(ann_path):
            try:
                beats = np.loadtxt(ann_path)
                if beats.ndim == 1:
                    beats = beats.reshape(1, -1)
                downbeats = beats[beats[:, 1] == 1, 0]   # sample positions
                if len(downbeats) > 4:
                    intervals = np.diff(downbeats.astype(float)) / 44100.0
                    med = float(np.median(intervals))
                    # bar-level or beat-level
                    if med < 0.7:
                        bpm = round(60.0 / med, 1)
                    else:
                        bpm = round(4 * 60.0 / med, 1)
                    track_dur_s = float(downbeats[-1]) / 44100.0
            except Exception:
                pass

        # Estimate solo time (full track minus CF overlap on both sides)
        if track_dur_s and bpm:
            bar_s = 4 * 60.0 / bpm
            # First track: no entry CF; last track: no exit CF
            entry_cf = CF_BARS * bar_s if i > 0 else 0
            exit_cf  = EXIT_BARS * bar_s if i < len(tracks) - 1 else 0
            solo_s = max(0, track_dur_s - entry_cf - exit_cf)
        else:
            solo_s = None

        t_start = cumulative_s
        if solo_s:
            cumulative_s += solo_s

        rows.append({
            'n': i + 1,
            'name': name,
            'bpm': bpm,
            'camelot': camelot,
            't_start': t_start,
            'solo_s': solo_s,
        })

    # Format table
    lines = []
    lines.append("┌─── PREVIEW: Transitions plan ───────────────────────────┐")
    lines.append(f"  {'#':<3} {'Track':<22} {'BPM':<7} {'Key':<6} {'Entry time':<12} {'Solo'}")
    lines.append("  " + "─" * 58)

    for r in rows:
        ts = r['t_start']
        t_str = f"{int(ts//60):02d}:{int(ts%60):02d}"
        solo_str = f"~{int(r['solo_s']//60)}:{int(r['solo_s']%60):02d}" if r['solo_s'] else "?"
        bpm_str = f"{r['bpm']}" if r['bpm'] else "?"
        lines.append(f"  {r['n']:<3} {r['name']:<22} {bpm_str:<7} {r['camelot']:<6} {t_str:<12} {solo_str}")

    total_m = int(cumulative_s // 60)
    total_s = int(cumulative_s % 60)
    lines.append("  " + "─" * 58)
    lines.append(f"  Estimated mix duration: ~{total_m}:{total_s:02d}")
    lines.append(f"  Crossfade: {CF_BARS} bars per transition")
    lines.append("└─────────────────────────────────────────────────────────┘")
    lines.append("")
    lines.append("⏸  Confirm to proceed with full mix.")
    lines.append("   Send 'ok' / 'да' / 'go' to continue, or adjust config.")

    return "\n".join(lines)

def main():
    p = argparse.ArgumentParser(description="Mix + Analyze + Validate pipeline")
    p.add_argument("--config", help="Python config file with TRACKS list")
    p.add_argument("--wav-dir", help="Source WAV directory (alternative to --config)")
    p.add_argument("--ann-dir", help="Annotation directory (alternative to --config)")
    p.add_argument("--output", default="", help="Output MP3 path (default: auto-named)")
    p.add_argument("--style", default="", help="Mix style name (auto-detect if empty)")
    p.add_argument("--bitrate", default="", help="MP3 bitrate (auto from genre if empty)")
    p.add_argument("--author", default="Hermes", help="Mix author")
    p.add_argument("--skip-preanalyze", action="store_true", help="Skip Step 0 pre-analysis")
    p.add_argument("--skip-genre", action="store_true", help="Skip genre detection (Step 0.5)")
    p.add_argument("--analyze-only", action="store_true", help="Skip mixing, only analyze")
    p.add_argument("--feedback", action="store_true", help="Generate tuning recommendations")
    p.add_argument("--no-validate", action="store_true", help="Skip validation step")
    p.add_argument("--strict", action="store_true", help="Strict validation thresholds")
    p.add_argument("--catbox", action="store_true", help="Upload to catbox when done")
    p.add_argument("--preview-only", action="store_true",
                   help="Stop after preview table (don't mix). Exit 4.")
    p.add_argument("--no-preview", action="store_true",
                   help="Skip preview confirmation (CI/auto runs only)")
    args = p.parse_args()

    config_path = args.config
    wav_dir = args.wav_dir
    ann_dir = args.ann_dir
    style = args.style
    bitrate = args.bitrate
    author = args.author
    output = args.output

    # Determine config output for pre-analysis
    optimized_config = os.path.join(SCRIPT_DIR, ".optimized_config.py")

    # ─── Step 0: Pre-Analyze Tracks ──────────────────────────────────
    if not args.analyze_only and not args.skip_preanalyze:
        print("\n" + "=" * 55)
        print("  Step 0: Pre-Analyze Tracks & Optimize Order")
        print("=" * 55)

        preanalyzer = os.path.join(SCRIPT_DIR, "track_analyzer.py")
        cmd = [sys.executable, preanalyzer]
        if config_path:
            cmd += ["--config", config_path]
        elif wav_dir and ann_dir:
            cmd += ["--wav-dir", wav_dir, "--ann-dir", ann_dir]
        else:
            p.error("--config or --wav-dir+--ann-dir required")
        cmd += ["--out", optimized_config]

        t0 = time.time()
        result = subprocess.run(cmd)
        check_exit_code(result.returncode, "Pre-Analysis")

        # Use the optimized config for mixing
        config_path = optimized_config
        print(f"  Pre-analysis: {time.time()-t0:.1f}s")
        print(f"  Using optimized config: {config_path}")

    # Load config (original or optimized)
    if config_path and os.path.exists(config_path):
        tracks, wav_dir, ann_dir, cfg = load_config(config_path)
    elif args.analyze_only:
        # For analyze-only, need existing mix path
        tracks, wav_dir, ann_dir = [], None, None
    else:
        p.error("No valid config found")

    # ─── Step 0.75: Preview (MANDATORY unless --no-preview) ──────────
    if not args.analyze_only and not getattr(args, 'no_preview', False):
        print("\n" + "=" * 55)
        print("  Step 0.75: Preview — Transitions Plan")
        print("=" * 55)

        preview = build_preview_table(tracks, wav_dir, ann_dir)
        if preview:
            print("\n" + preview)
        else:
            # Fallback: minimal text table
            print("\n  Track order:")
            for i, t in enumerate(tracks, 1):
                print(f"    {i}. {t[0]}")
            print("\n⏸  Confirm to proceed.")

        # Save preview to file (for Telegram bot to pick up)
        preview_path = os.path.join(SCRIPT_DIR, ".preview_pending.txt")
        with open(preview_path, "w") as f:
            f.write(preview or "Preview unavailable\n")
            f.write(f"\nConfig: {config_path}\n")

        if getattr(args, 'preview_only', False):
            print(f"\n  Preview saved → {preview_path}")
            print("  Run with --no-preview to skip confirmation and mix.")
            sys.exit(4)

        # CLI: interactive confirm
        print()
        try:
            ans = input("  Proceed with full mix? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""

        if ans not in ("y", "yes", "да", "ok", "go"):
            print("  Aborted. Adjust config and re-run.")
            sys.exit(0)

    # ─── Step 0.5: Genre Detection ──────────────────────────────────
    if not args.skip_genre:
        print("\n" + "=" * 55)
        print("  Step 0.5: Genre Detection")
        print("=" * 55)
        genre_detector = os.path.join(SCRIPT_DIR, "genre_detector.py")
        if os.path.exists(genre_detector) and wav_dir and ann_dir:
            t0 = time.time()
            result = subprocess.run(
                [sys.executable, genre_detector,
                 "--wav-dir", wav_dir, "--ann-dir", ann_dir, "--json"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                try:
                    gdata = json.loads(result.stdout)
                    ggenre = gdata.get("genre", "")
                    gbitrate = gdata.get("bitrate", "")
                    if not style and ggenre:
                        style = ggenre.replace("_", " ").title()
                    if not bitrate and gbitrate:
                        bitrate = gbitrate
                except json.JSONDecodeError:
                    pass
            print(f"  Genre: {style or 'auto'} | Bitrate: {bitrate or 'default'}")
            print(f"  Detection: {time.time()-t0:.1f}s")
        else:
            print(f"  [skip] genre_detector.py not found or no wav/ann dirs")

    # Determine output path
    if not output:
        import datetime
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        out_name = f"Mix_{date}_{style}_{author}.mp3"
        output = os.path.join(SCRIPT_DIR, out_name)

    mixer   = os.path.join(SCRIPT_DIR, "smart_mixer.py")
    analyzer = os.path.join(SCRIPT_DIR, "mix_analyzer.py")
    validator = os.path.join(SCRIPT_DIR, "mix_validator.py")
    source_checker = os.path.join(SCRIPT_DIR, "source_check.py")
    json_out = output.rsplit('.', 1)[0] + '_analysis.json'

    # ─── Gate 0: Source Quality Check ────────────────────────────────
    if not args.analyze_only and not args.skip_preanalyze:
        print("\n" + "=" * 55)
        print("  Gate 0: Source Quality Check")
        print("=" * 55)
        t0 = time.time()
        result = subprocess.run(
            [sys.executable, source_checker, "--config", config_path],
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print("  ❌ Source files FAIL quality check. Fix or replace tracks before mixing.")
            if result.stderr:
                print(f"  Error: {result.stderr[:300]}")
            sys.exit(2)

    # ─── Step 1: Mix ────────────────────────────────────────────────
    if not args.analyze_only:
        print("\n" + "=" * 55)
        print("  Step 1: Mixing Tracks")
        print("=" * 55)
        t0 = time.time()

        cmd = [sys.executable, mixer,
               "--config", config_path,
               "--output", output,
               "--style", style,
               "--author", author]

        if bitrate:
            cmd += ["--bitrate", bitrate]

        result = subprocess.run(cmd)
        check_exit_code(result.returncode, "Mixer")

        mix_time = time.time() - t0
        print(f"\n  Mix completed in {mix_time:.1f}s")

    # ─── Step 2: Analyze ────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  Step 2: Analyzing Mix Quality")
    print("=" * 55)

    if not os.path.exists(output):
        print(f"  ❌ Mix file not found: {output}")
        sys.exit(3)

    t1 = time.time()
    analyze_cmd = [sys.executable, analyzer,
                   "--mix", output,
                   "--wav-dir", wav_dir,
                   "--ann-dir", ann_dir,
                   "--json-out", json_out]
    if config_path and os.path.exists(config_path):
        analyze_cmd += ["--config", config_path]
    if args.feedback:
        analyze_cmd += ["--feedback"]

    result = subprocess.run(analyze_cmd)
    if result.returncode != 0:
        print(f"\n  ⚠️ Analyzer returned {result.returncode} (continuing)")
    print(f"  Analysis: {time.time()-t1:.1f}s")

    # ─── Gate: Silence Check ─────────────────────────────────────────
    print("\n" + "─" * 40)
    print("  Gate: Silence Check")
    print("─" * 40)
    gaps = check_silence(output)
    if gaps is None:
        print("  ⚠️  Can't check (librosa not available)")
    elif gaps:
        print(f"  ❌ Found {len(gaps)} silence gaps:")
        for gs, ge, d in gaps:
            print(f"     {gs//60:02d}:{gs%60:02d} - {ge//60:02d}:{ge%60:02d} ({d}s)")
        if not args.analyze_only:
            print("\n  ❌ Pipeline FAILED — fix script and re-run")
            sys.exit(2)
    else:
        print("  ✅ No silence gaps detected")

    # ─── Gate: Check JSON results ────────────────────────────────────
    print("\n" + "─" * 40)
    print("  Gate: Analysis Results")
    print("─" * 40)
    if os.path.exists(json_out):
        with open(json_out) as f:
            adata = json.load(f)
        # Check key metrics
        transitions = adata.get('transitions', [])
        artefacts = adata.get('artefacts_count', 0)
        source_arts = adata.get('source_artefacts', 0)
        mixer_arts = artefacts - source_arts
        print(f"  Transitions: {len(transitions)} | Events: {artefacts} total ({mixer_arts} mixer)")

        if mixer_arts > 200 and not args.analyze_only:
            print(f"  ❌ Too many mixer artifacts ({mixer_arts}) — needs fix")
        else:
            print(f"  ✅ Artifacts in acceptable range")
    else:
        print(f"  ⚠️  No analysis JSON found")

    if args.no_validate:
        if args.feedback:
            print("\n  Recommendations above. Apply fixes and re-run.")
        print(f"\n  Output: {output}")
        print(f"  Size: {os.path.getsize(output)/1024/1024:.0f} MB")
        sys.exit(0)

    # ─── Step 3: Validate ────────────────────────────────────────────
    if os.path.exists(validator) and os.path.exists(json_out):
        print("\n" + "=" * 55)
        print("  Step 3: Validating Mix")
        print("=" * 55)
        cmd = [sys.executable, validator, "--json", json_out]
        if args.strict:
            cmd += ["--strict"]
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    else:
        print(f"\n  Output: {output}")
        print(f"  Size: {os.path.getsize(output)/1024/1024:.0f} MB")
        sys.exit(0)

if __name__ == "__main__":
    main()