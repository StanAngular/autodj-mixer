#!/usr/bin/env python3
"""
repaint_transition.py — AI-переход через ACE-Step Repaint.

Генерирует плавный мост между треками, используя ACE-Step 1.5 Repaint.
Модель видит контекст (хвост A + голова B) и регенерирует только середину,
сохраняя оригинальные края — стыки получаются без швов.

Usage:
  uv run python3 repaint_transition.py \\
    --track-a /opt/autodj-mixer/tracks/Garden.wav \\
    --track-b /opt/autodj-mixer/tracks/Fever.wav \\
    --ann-a /opt/autodj-mixer/ann/Garden.txt \\
    --ann-b /opt/autodj-mixer/ann/Fever.txt \\
    --exit-bar 128 --entry-bar 75 \\
    --bpm 122 --style "melodic house" \\
    --output /tmp/ai_transitions/tr0_Garden_to_Fever.wav

Требования:
  - ACE-Step 1.5 установлен в ~/ACE-Step-1.5/
  - Запускать через `uv run` из ~/ACE-Step-1.5/
  - swap 12GB (без GPU)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import gc
from pathlib import Path

# CPU optimisation
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["TORCH_NUM_THREADS"] = "2"
os.environ["NUMEXPR_NUM_THREADS"] = "2"
os.environ["ACESTEP_DEVICE"] = "cpu"
os.environ["ACESTEP_DTYPE"] = "float32"
os.environ["ACESTEP_CPU_OFFLOAD"] = "true"

import torch
torch.set_num_threads(2)

import numpy as np

ACE_STEP_DIR = os.path.expanduser("~/ACE-Step-1.5")
sys.path.insert(0, ACE_STEP_DIR)

from acestep.handler import AceStepHandler
from acestep.inference import GenerationParams, GenerationConfig, generate_music

SR = 44100  # mixer sample rate

# ──────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────

def bar_sec(bpm: float) -> float:
    """Длительность одного такта в секундах (4 доли)."""
    return 4.0 * 60.0 / bpm


def load_dbeats_text(ann_path: str, sr: int = SR):
    """Загрузить downbeats из madmom-формата (сек, номер_доли)."""
    beats = []
    with open(ann_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            t = float(parts[0])
            bnum = int(round(float(parts[1]))) if len(parts) > 1 else 1
            beats.append((t, bnum))
    # Только downbeats (beat_number == 1)
    downbeats = [t for t, bnum in beats if bnum == 1]
    if not downbeats:
        # fallback: каждый 4-й бит
        downbeats = [t for i, (t, _) in enumerate(beats) if i % 4 == 0]
    return np.array(downbeats)


def bar_to_sample(downbeats: list, bar_idx: int, sr: int = SR) -> int:
    """Бар → сэмпл. bar_idx=0 → первый downbeat."""
    if bar_idx < 0:
        bar_idx = 0
    if bar_idx >= len(downbeats):
        bar_idx = len(downbeats) - 1
    return int(downbeats[bar_idx] * sr)


# ──────────────────────────────────────────────
# Audio helpers
# ──────────────────────────────────────────────

def cut_tail(input_wav: str, output_wav: str, start_sec: float, duration_sec: float):
    """Вырезать кусок из хвоста трека."""
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.4f}",
        "-i", input_wav,
        "-t", f"{duration_sec:.4f}",
        "-ar", str(SR), "-ac", "2",
        output_wav
    ], capture_output=True, check=True)


def cut_head(input_wav: str, output_wav: str, duration_sec: float):
    """Вырезать кусок из начала трека."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", input_wav,
        "-t", f"{duration_sec:.4f}",
        "-ar", str(SR), "-ac", "2",
        output_wav
    ], capture_output=True, check=True)


def concat_wavs(wav_a: str, wav_b: str, output_wav: str):
    """Склеить два WAV встык."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", wav_a, "-i", wav_b,
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]",
        "-map", "[out]",
        "-ar", str(SR), "-ac", "2",
        output_wav
    ], capture_output=True, check=True)


def get_duration(wav_path: str) -> float:
    """Получить длительность WAV в секундах."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", wav_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def cut_segment(input_wav: str, output_wav: str, start_sec: float, duration_sec: float):
    """Вырезать произвольный сегмент."""
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.4f}",
        "-i", input_wav,
        "-t", f"{duration_sec:.4f}",
        output_wav
    ], capture_output=True, check=True)


# ──────────────────────────────────────────────
# Repaint generation
# ──────────────────────────────────────────────

def generate_repaint_transition(
    track_a: str,
    track_b: str,
    ann_a: str,
    ann_b: str,
    exit_bar: int,
    entry_bar: int,
    bpm: float,
    output_path: str,
    style: str = "melodic house",
    bars: int = 16,
    offset_bars: int = 4,
    steps: int = 40,
    guidance: float = 7.0,
    seed: int = 42,
):
    """
    Главная функция repaint-пайплайна.

    1. Нарезка tail_a + head_b по тактовой сетке
    2. Склейка combined.wav
    3. ACE-Step Repaint
    4. Вырезка финального перехода
    """
    result = {
        "success": False, "output_path": None,
        "combined_duration": 0, "repaint_start": 0, "repaint_end": 0,
        "final_duration": 0, "prompt": "", "error": None, "time_sec": 0,
    }

    # Промпт
    prompt = (
        f"{bpm} BPM, {style}, smooth DJ transition section, "
        f"continuous four-on-the-floor kick, filter sweep movement, "
        f"warm chord progression, consistent groove throughout, "
        f"seamless blend, no break no drop, instrumental, no vocals, "
        f"consistent volume throughout, no silence"
    )
    result["prompt"] = prompt

    t_start = time.time()
    bar_s = bar_sec(bpm)
    bars_dur = bars * bar_s
    offset_dur = offset_bars * bar_s

    print(f"\n=== Repaint Transition ===")
    print(f"  {Path(track_a).name} (bar {exit_bar}) → {Path(track_b).name} (bar {entry_bar})")
    print(f"  BPM: {bpm} | Bars: {bars} ({bars_dur:.1f}s) | Offset: {offset_bars} bars ({offset_dur:.1f}s)")
    print(f"  Style: {style} | Steps: {steps} | Guidance: {guidance}")

    with tempfile.TemporaryDirectory() as tmpdir:
        # ── 1. Загрузить downbeats, найти сэмпл-позиции ──
        try:
            db_a = load_dbeats_text(ann_a)
            db_b = load_dbeats_text(ann_b)
            
            # bar → sample для точки выхода/входа
            exit_samp = bar_to_sample(db_a, exit_bar)
            entry_samp = bar_to_sample(db_b, entry_bar)
            
            # Длительность хвоста A: exit_samp - bars_dur секунд назад
            exit_sec = exit_samp / SR
            tail_start = exit_sec - bars_dur
            if tail_start < 0:
                tail_start = 0
                bars_dur = exit_sec
            
            # Для head B: стартуем с entry_samp
            entry_sec = entry_samp / SR
            
            print(f"  Tail A: {tail_start:.1f}s → {exit_sec:.1f}s ({bars_dur:.1f}s)")
            print(f"  Head B: {entry_sec:.1f}s → {entry_sec + bars_dur:.1f}s ({bars_dur:.1f}s)")
        except Exception as e:
            result["error"] = f"Annotation loading failed: {e}"
            return result

        # ── 2. Нарезать tail_a + head_b ──
        tail_a = os.path.join(tmpdir, "tail_a.wav")
        head_b = os.path.join(tmpdir, "head_b.wav")
        
        try:
            cut_segment(track_a, tail_a, tail_start, bars_dur)
            cut_segment(track_b, head_b, entry_sec, bars_dur)
        except subprocess.CalledProcessError as e:
            result["error"] = f"ffmpeg cut failed: {e}"
            return result

        # ── 3. Склеить combined.wav ──
        combined = os.path.join(tmpdir, "combined.wav")
        try:
            concat_wavs(tail_a, head_b, combined)
            combined_dur = get_duration(combined)
            result["combined_duration"] = combined_dur
            print(f"  Combined: {combined_dur:.1f}s")
        except subprocess.CalledProcessError as e:
            result["error"] = f"ffmpeg concat failed: {e}"
            return result

        # ── 4. Рассчитать зону repaint ──
        # Стык треков = начало head_b = tail_duration
        stitch_sec = bars_dur
        repaint_start = stitch_sec - offset_dur
        repaint_end = stitch_sec + offset_dur
        
        # Не даём выйти за границы combined.wav
        if repaint_start < 0:
            repaint_start = 0
        if repaint_end > combined_dur:
            repaint_end = combined_dur
        
        result["repaint_start"] = repaint_start
        result["repaint_end"] = repaint_end
        
        repaint_dur = repaint_end - repaint_start
        print(f"  Stitch point: {stitch_sec:.1f}s")
        print(f"  Repaint zone: {repaint_start:.1f}s → {repaint_end:.1f}s ({repaint_dur:.1f}s)")
        print(f"    (context: {offset_dur:.1f}s each side)")

        # ── 5. ACE-Step Repaint ──
        import gc
        gc.collect()
        
        print(f"\n  Loading ACE-Step model...")
        t0 = time.time()
        
        dit = AceStepHandler()
        dit.initialize_service(
            project_root=ACE_STEP_DIR,
            config_path="acestep-v15-turbo",
            device="cpu"
        )
        print(f"  Model loaded in {time.time()-t0:.0f}s")

        params = GenerationParams(
            task_type="repaint",
            caption=prompt,
            bpm=int(bpm),
            duration=combined_dur,
            src_audio=combined,          # combined.wav — референс слева и справа
            repainting_start=repaint_start,
            repainting_end=repaint_end,
            instrumental=True,
            inference_steps=steps,
            guidance_scale=guidance,
            seed=seed,
            thinking=False,
        )
        config = GenerationConfig(batch_size=1, audio_format="wav")

        print(f"  Generating repaint ({steps} steps, guidance={guidance})...")
        print(f"  ETA: ~{repaint_dur * 12:.0f}s on CPU")
        t0 = time.time()

        out_dir = os.path.join(tmpdir, "output")
        os.makedirs(out_dir, exist_ok=True)

        gen_result = generate_music(dit, None, params, config, save_dir=out_dir)
        gen_time = time.time() - t0

        if not gen_result.success or not gen_result.audios:
            result["error"] = gen_result.error or "Generation failed"
            print(f"  ❌ {result['error']}")
            return result

        gen_path = gen_result.audios[0]["path"]
        print(f"  Generation done in {gen_time:.0f}s")

        # ── 6. Вырезать финальный переход чуть шире зоны repaint ──
        final_start = repaint_start - 2.0
        if final_start < 0:
            final_start = 0
        final_dur = repaint_dur + 4.0  # +2s с каждой стороны
        if final_start + final_dur > combined_dur:
            final_dur = combined_dur - final_start

        transition_tmp = os.path.join(tmpdir, "final_transition.wav")
        cut_segment(gen_path, transition_tmp, final_start, final_dur)
        
        # Ресемпл 48k → 44.1k если нужно
        subprocess.run([
            "ffmpeg", "-y", "-i", transition_tmp,
            "-ar", str(SR), "-ac", "2",
            output_path
        ], capture_output=True, check=True)

        result["final_duration"] = get_duration(output_path)
        result["success"] = True
        result["output_path"] = output_path
        result["time_sec"] = time.time() - t_start

        print(f"\n  ✅ Final transition: {output_path}")
        print(f"  Duration: {result['final_duration']:.1f}s")
        print(f"  Total time: {result['time_sec']:.0f}s")

    return result


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate DJ transition via ACE-Step Repaint"
    )
    parser.add_argument("--track-a", required=True, help="Track A WAV path")
    parser.add_argument("--track-b", required=True, help="Track B WAV path")
    parser.add_argument("--ann-a", required=True, help="Track A annotation (.txt)")
    parser.add_argument("--ann-b", required=True, help="Track B annotation (.txt)")
    parser.add_argument("--exit-bar", type=int, required=True, help="Exit bar in track A")
    parser.add_argument("--entry-bar", type=int, required=True, help="Entry bar in track B")
    parser.add_argument("--bpm", type=float, required=True, help="BPM of the set")
    parser.add_argument("--output", required=True, help="Output transition WAV path")
    parser.add_argument("--style", default="melodic house", help="Music style")
    parser.add_argument("--bars", type=int, default=16, help="Tail/head length in bars")
    parser.add_argument("--offset-bars", type=int, default=4, help="Context offset from stitch (bars)")
    parser.add_argument("--steps", type=int, default=40, help="ACE-Step inference steps")
    parser.add_argument("--guidance", type=float, default=7.0, help="CFG guidance scale")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")

    args = parser.parse_args()

    res = generate_repaint_transition(
        track_a=args.track_a, track_b=args.track_b,
        ann_a=args.ann_a, ann_b=args.ann_b,
        exit_bar=args.exit_bar, entry_bar=args.entry_bar,
        bpm=args.bpm, output_path=args.output,
        style=args.style, bars=args.bars,
        offset_bars=args.offset_bars,
        steps=args.steps, guidance=args.guidance,
        seed=args.seed,
    )
    print(json.dumps(res, indent=2, default=str))
    sys.exit(0 if res["success"] else 1)