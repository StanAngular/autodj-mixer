#!/usr/bin/env python3
"""
source_check.py — проверка исходных WAV на битость ДО микса.
Проверяет: RMS провалы, BPM стабильность, clipping, длительность.
Вывод: PASS/FAIL для каждого трека.

Usage:
  python3 source_check.py --wav-dir ./shared/tracks --ann-dir ./shared/ann
  python3 source_check.py --config mix_config.py
  python3 source_check.py --wav-dir ./shared/tracks --ann-dir ./shared/ann --json out.json
"""
import sys, os, argparse, importlib.util, json
import numpy as np
import librosa

SR = 44100

def check_track(wav_path, ann_path=None):
    """Проверка одного WAV на качество. Возвращает dict с результатами."""
    result = {'wav': os.path.basename(wav_path), 'status': 'PASS', 'issues': []}

    if not os.path.exists(wav_path):
        result['status'] = 'FAIL'
        result['issues'].append('FILE_NOT_FOUND')
        return result

    try:
        audio, sr = librosa.load(wav_path, sr=None, mono=True)
    except Exception as e:
        result['status'] = 'FAIL'
        result['issues'].append(f'LOAD_ERROR: {e}')
        return result

    dur = len(audio) / sr
    result['duration'] = round(dur, 1)

    # 1. Длительность (минимум 30s)
    if dur < 30:
        result['issues'].append(f'TOO_SHORT: {dur:.0f}s < 30s')

    # 2. RMS провалы (битые участки)
    hop = sr  # 1s окна
    bad_zones = 0
    for i in range(0, int(dur) - 1):
        frame = audio[i * sr:(i + 1) * sr]
        rms = np.sqrt(np.mean(frame**2))
        if rms < 0.005:  # почти тишина
            bad_zones += 1

    bad_pct = bad_zones / max(1, int(dur)) * 100
    result['bad_rms_pct'] = round(bad_pct, 1)
    if bad_pct > 10:
        result['issues'].append(f'RMS_DROPS: {bad_pct:.0f}% зон с RMS<0.005 (битый файл?)')

    # 3. BPM стабильность
    bpm_readings = []
    for i in range(0, int(dur) - 10, 10):
        frame = audio[i * sr:(i + 10) * sr]
        rms = np.sqrt(np.mean(frame**2))
        if rms > 0.01:  # только где есть звук
            tempo, _ = librosa.beat.beat_track(y=frame, sr=sr)
            if isinstance(tempo, np.ndarray):
                tempo = float(tempo[0])
            if 60 < tempo < 200:  # разумный диапазон
                bpm_readings.append(tempo)

    if bpm_readings:
        median_bpm = float(np.median(bpm_readings))
        std_bpm = float(np.std(bpm_readings))
        result['bpm_median'] = round(median_bpm, 1)
        result['bpm_std'] = round(std_bpm, 1)

        if std_bpm > 15:
            result['issues'].append(f'BPM_UNSTABLE: std={std_bpm:.0f} (медиана={median_bpm:.0f})')
        elif std_bpm > 8:
            result['issues'].append(f'BPM_WARN: std={std_bpm:.0f}')
    else:
        result['issues'].append('BPM_NO_DATA')

    # 4. Clipping
    peak = float(np.max(np.abs(audio)))
    result['peak'] = round(peak, 4)
    if peak > 0.99:
        result['issues'].append(f'CLIPPING: peak={peak:.3f}')

    # 5. Общая RMS
    overall_rms = float(np.sqrt(np.mean(audio**2)))
    result['rms'] = round(overall_rms, 4)
    if overall_rms < 0.01:
        result['issues'].append('TOO_QUIET')

    # Итоговый статус
    if result['issues']:
        critical = [i for i in result['issues'] if not i.startswith('BPM_WARN')]
        if critical:
            result['status'] = 'FAIL'
        else:
            result['status'] = 'WARN'

    return result


def main():
    p = argparse.ArgumentParser(description='Check source WAV files for corruption before mixing')
    p.add_argument('--wav-dir', default=None)
    p.add_argument('--ann-dir', default=None)
    p.add_argument('--config', default=None, help='Config with TRACKS list')
    p.add_argument('--json', default=None, help='JSON output path')
    args = p.parse_args()

    wav_dir = args.wav_dir
    ann_dir = args.ann_dir
    targets = []

    if args.config:
        spec = importlib.util.spec_from_file_location('cfg', args.config)
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        for name, wav, ann in cfg.TRACKS:
            wd = getattr(cfg, 'WAV_DIR', wav_dir or '.')
            ad = getattr(cfg, 'ANN_DIR', ann_dir or '.')
            targets.append((name, os.path.join(wd, wav), os.path.join(ad, ann)))
    elif wav_dir:
        for f in sorted(os.listdir(wav_dir)):
            if f.endswith('.wav'):
                name = f.replace('.wav', '')
                ann_f = os.path.join(ann_dir or wav_dir, f.replace('.wav', '.txt'))
                targets.append((name, os.path.join(wav_dir, f), ann_f if os.path.exists(ann_f) else None))

    if not targets:
        print('No WAV files found')
        sys.exit(1)

    print(f"\n{'='*55}")
    print("  Source Quality Check")
    print('='*55)

    results = []
    failed = 0
    for name, wav, ann in targets:
        r = check_track(wav, ann)
        results.append(r)
        icon = '✅' if r['status'] == 'PASS' else '⚠️' if r['status'] == 'WARN' else '❌'
        issues = ', '.join(r['issues']) if r['issues'] else 'OK'
        print(f"  {icon} {name}: {r['duration']:.0f}s BPM={r.get('bpm_median', '?')} RMS={r.get('bad_rms_pct', '?')}% bad → {issues}")

    passed = sum(1 for r in results if r['status'] == 'PASS')
    warned = sum(1 for r in results if r['status'] == 'WARN')
    failed = sum(1 for r in results if r['status'] == 'FAIL')

    print(f"\n  {passed} PASS, {warned} WARN, {failed} FAIL")

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"  JSON → {args.json}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == '__main__':
    main()