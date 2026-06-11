#!/usr/bin/env python3
"""
AutoDJ Pipeline v1 — один вызов для полного цикла:
  1. Pre-flight check (аннотации, A1F, формат)
  2. Mix (no_a1f default, a1f если готово)
  3. Upload to catbox
  4. Transitions preview
  5. Article (DJ AI001 format)

Usage:
  .venv/bin/python3 run_pipeline.py --wav-dir shared/tracks --ann-dir shared/ann --config mix_config_organic.py
"""
import argparse, os, sys, time, json, subprocess, numpy as np

SR = 44100
TARGET_LUFS = -14.0

def preflight(wav_dir, ann_dir, a1f_dir=None):
    """Check annotations format, WAV/ann pairing, BPM sanity."""
    issues = []
    
    wavs = {f.replace('.wav','') for f in os.listdir(wav_dir) if f.endswith('.wav')}
    anns = {f.replace('.txt','') for f in os.listdir(ann_dir) if f.endswith('.txt')}
    
    # 1. Missing annotations
    missing = wavs - anns
    if missing:
        issues.append(f"❌ Missing annotations: {', '.join(sorted(missing))}")
    
    # 2. Orphan annotations
    orphan = anns - wavs
    if orphan:
        print(f"  ⚠ Orphan annotations (no WAV): {', '.join(sorted(orphan))}")
    
    # 3. Annotation format check (time-based vs sample-based)
    for base in sorted(wavs & anns):
        fp = os.path.join(ann_dir, f"{base}.txt")
        with open(fp) as fh:
            first = fh.readline().strip()
        if first:
            has_dot = '.' in first.split()[0]
            if not has_dot:
                issues.append(f"❌ {base}.txt: sample-based format (expected time in seconds)")
    
    # 4. BPM sanity check
    bpm_values = []
    for base in sorted(wavs & anns):
        fp = os.path.join(ann_dir, f"{base}.txt")
        beats = np.loadtxt(fp)
        db = np.array([int(r[0] * SR) for r in beats if round(r[1]) == 1], dtype=int)
        if len(db) >= 4:
            iv = np.diff(db.astype(float)) / SR
            iv = iv[iv > 0.3]
            if len(iv):
                p25, p75 = np.percentile(iv, [25, 75])
                ok = iv[(iv >= p25 - 1.5*(p75-p25)) & (iv <= p75 + 1.5*(p75-p25))]
                if len(ok):
                    bpm = 4 * 60.0 / np.mean(ok)
                    bpm_values.append((base, bpm))
    
    if len(bpm_values) >= 2:
        bpm_list = [b for _, b in bpm_values]
        spread = max(bpm_list) - min(bpm_list)
        avg_bpm = np.mean(bpm_list)
        spread_pct = spread / avg_bpm * 100
        if spread_pct > 15:
            names = [n for n, b in bpm_values]
            issues.append(f"⚠ BPM spread {spread_pct:.0f}% ({min(bpm_list):.0f}-{max(bpm_list):.0f}): {', '.join(names[:3])}...")
    
    # 5. A1F availability
    if a1f_dir and os.path.isdir(a1f_dir):
        a1f_files = {f.replace('.json','') for f in os.listdir(a1f_dir) if f.endswith('.json')}
        a1f_ready = wavs & a1f_files
        a1f_missing = wavs - a1f_files
        print(f"  A1F: {len(a1f_ready)} ready, {len(a1f_missing)} missing")
    
    return issues


def fix_annotations(wav_dir, ann_dir, sr=44100):
    """Re-annotate tracks with sample-based format to time-based format."""
    import numpy as np
    np.float = np.float64; np.int = np.int64; np.complex = np.complex128; np.bool = np.bool_
    import collections
    from collections.abc import MutableSequence; collections.MutableSequence = MutableSequence
    from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor
    
    to_fix = []
    for f in os.listdir(ann_dir):
        if not f.endswith('.txt'):
            continue
        fp = os.path.join(ann_dir, f)
        with open(fp) as fh:
            first = fh.readline().strip()
        if first and '.' not in first.split()[0]:
            to_fix.append(f[:-4])
    
    if not to_fix:
        print("  All annotations valid ✓")
        return
    
    print(f"  Re-annotating {len(to_fix)} tracks (sample→time)...")
    proc = DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)
    for i, base in enumerate(to_fix):
        wav = os.path.join(wav_dir, f"{base}.wav")
        out = os.path.join(ann_dir, f"{base}.txt")
        if not os.path.exists(wav):
            print(f"    SKIP {base} (no WAV)")
            continue
        t0 = time.time()
        act = RNNDownBeatProcessor()(wav)
        beats = proc(act)
        rows = [[b[0], int(round(b[1]))] for b in beats if int(round(b[1])) in (1,2,3,4)]
        np.savetxt(out, rows, fmt="%.6f %d")
        n_dbs = sum(1 for _, bt in rows if bt == 1)
        print(f"    [{i+1}/{len(to_fix)}] {base}: {n_dbs} dbs ({time.time()-t0:.1f}s)", flush=True)


def run_mix(wav_dir, ann_dir, config, output, style="AutoDJ Mix", author="DJ AGENT 01",
            analysis_mode="no_a1f", bitrate="320k", cf_bars="auto"):
    """Run smart_mixer.py with given params."""
    cmd = [
        ".venv/bin/python3", "smart_mixer.py",
        "--wav-dir", wav_dir,
        "--ann-dir", ann_dir,
        "--config", config,
        f"--analysis-mode={analysis_mode}",
        "--style", style,
        "--author", author,
        "--output", output,
        f"--bitrate={bitrate}",
    ]
    if cf_bars:
        cmd.extend([f"--cf-bars={cf_bars}"])
    
    print(f"  Running: {' '.join(cmd[:6])}...")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    elapsed = time.time() - t0
    
    if r.returncode != 0:
        print(f"  ❌ Mix failed (exit={r.returncode}, {elapsed:.0f}s)")
        print(r.stderr[-300:])
        return False
    
    print(f"  ✅ Mix done in {elapsed:.0f}s")
    # Print transitions summary
    for line in r.stdout.split('\n'):
        if line.startswith('  ') and '->' in line and 'BASS SWAP' in line:
            print(line)
    return True


def upload_to_catbox(filepath):
    """Upload file to litterbox.catbox.moe (72h)."""
    import subprocess
    r = subprocess.run([
        "curl", "-s", "-F", "reqtype=fileupload", "-F", "time=72h",
        "-F", f"fileToUpload=@{filepath}"
    ], capture_output=True, text=True, timeout=120)
    url = r.stdout.strip()
    if url.startswith("https://"):
        print(f"  📤 Catbox: {url}")
        return url
    print(f"  ❌ Upload failed: {url[:100]}")
    return None


def main():
    parser = argparse.ArgumentParser(description="AutoDJ Pipeline v1")
    parser.add_argument("--wav-dir", required=True)
    parser.add_argument("--ann-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--style", default="AutoDJ Mix")
    parser.add_argument("--author", default="DJ AGENT 01")
    parser.add_argument("--analysis-mode", default="a1f_fast", choices=["a1f", "a1f_fast", "no_a1f"])
    parser.add_argument("--a1f-dir", default=None)
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--skip-preview", action="store_true")
    parser.add_argument("--upload-only", action="store_true")
    args = parser.parse_args()
    
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    print(f"\n{'='*50}")
    print(f"  AutoDJ Pipeline v1")
    print(f"  Style: {args.style}")
    print(f"  Mode: {args.analysis_mode}")
    print(f"{'='*50}\n")
    
    # Step 1: Pre-flight
    print("🔍 Pre-flight check...")
    issues = preflight(args.wav_dir, args.ann_dir, args.a1f_dir)
    if issues:
        for issue in issues:
            print(f"  {issue}")
        if any("❌" in i for i in issues):
            print("  🔧 Auto-fixing annotations...")
            fix_annotations(args.wav_dir, args.ann_dir)
            # Re-check
            issues2 = preflight(args.wav_dir, args.ann_dir, args.a1f_dir)
            if any("❌" in i for i in issues2):
                print("  ❌ Cannot fix automatically. Abort.")
                sys.exit(1)
    
    # Step 2: Mix
    mix_num = 0
    outname = ''
    if not args.upload_only:
        # ── Mix numbering ────────────────────────────────
        counter_file = '/opt/autodj-mixer/.mix_counter'
        try:
            with open(counter_file) as f:
                mix_num = int(f.read().strip()) + 1
        except (FileNotFoundError, ValueError):
            mix_num = 1
        with open(counter_file, 'w') as f:
            f.write(str(mix_num))
        print(f"  🎯 Mix #{mix_num}")

        print("\n🎛 Running mix...")
        style_slug = args.style.replace(' ', '_')
        datestamp = time.strftime('%Y%m%d')
        outname = args.output or f"MIX-{mix_num}_{style_slug}_{datestamp}"
        ok = run_mix(args.wav_dir, args.ann_dir, args.config, f"{outname}.mp3",
                     style=args.style, author=args.author, analysis_mode=args.analysis_mode)
        if not ok:
            sys.exit(1)
        
        # Step 3: Upload
        if not args.skip_upload:
            print("\n📤 Uploading mix...")
            mix_url = upload_to_catbox(f"{outname}.mp3")
            if mix_url:
                print(f"  Mix: {mix_url}")
    
        # Step 4: Transitions preview
        if not args.skip_preview:
            print("\n🎬 Creating transitions preview...")
            stamps_path = f"{outname}_stamps.npy"
            wav_path = f"{outname}.wav"
            preview_path = f"{outname}_preview.mp3"
            if os.path.exists(stamps_path) and os.path.exists(wav_path):
                try:
                    stamps = np.load(stamps_path, allow_pickle=True)
                    segments = []
                    for i, s in enumerate(stamps):
                        t_start = max(0, s['t'] - 5)
                        t_end = s['t'] + s['dur'] + 8
                        dur_seg = t_end - t_start
                        tmp = f'/tmp/tr_{i+1:02d}.wav'
                        subprocess.run(['ffmpeg', '-y', '-ss', str(t_start), '-t', str(dur_seg),
                                        '-i', wav_path, '-acodec', 'pcm_s24le', '-ar', str(SR), tmp],
                                       capture_output=True, timeout=60)
                        segments.append(tmp)
                    
                    concat_path = '/tmp/concat_pipeline.txt'
                    with open(concat_path, 'w') as f:
                        for seg in segments:
                            f.write(f"file '{seg}'\n")
                    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                                    '-i', concat_path, '-b:a', '192k', preview_path],
                                   capture_output=True, timeout=60)
                    
                    if not args.skip_upload and os.path.exists(preview_path):
                        prev_url = upload_to_catbox(preview_path)
                        if prev_url:
                            print(f"  Preview: {prev_url}")
                    
                    for seg in segments:
                        if os.path.exists(seg):
                            os.remove(seg)
                except Exception as e:
                    print(f"  ⚠ Preview failed: {e}")
    
        print(f"\n{'='*50}")
        print(f"  ✅ Pipeline complete — Mix #{mix_num}")
        print(f"     Output: {outname}.mp3")
        print(f"{'='*50}")
    
    if args.upload_only:
        print(f"\n{'='*50}")
        print(f"  ✅ Pipeline complete (upload-only)")
        print(f"{'='*50}")


if __name__ == "__main__":
    main()