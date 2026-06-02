#!/usr/bin/env python3
"""
Mix Validator — automatic pass/warn/fail verdict for a completed mix.
Reads JSON output from mix_analyzer.py and applies quality thresholds.

Usage:
  python3 mix_validator.py --json mix_analysis.json
  python3 mix_validator.py --json mix_analysis.json --strict

Exit codes:
  0 = PASS
  1 = WARN
  2 = FAIL
"""

import sys, os, json, argparse

# ---- Quality Thresholds --------------------------------------------------

THRESHOLDS = {
    # mixer-induced high-severity artefacts
    'mixer_high_pass':  0,
    'mixer_high_warn':  3,
    # speed glitches (none allowed for pass)
    'speed_glitch_pass': 0,
    'speed_glitch_warn': 1,
    # stutter events
    'stutter_pass': 2,
    'stutter_warn': 5,
    # LUFS jump at transition boundary (dB)
    'lufs_jump_pass': 3.0,
    'lufs_jump_warn': 5.0,
    # beat drift at transitions (ms)
    'drift_pass': 10.0,
    'drift_warn': 20.0,
    # key compatibility score (Camelot)
    'key_compat_warn': 0.5,   # below this = WARN
    'key_compat_fail': 0.3,   # below this = FAIL
}

STRICT_THRESHOLDS = {
    **THRESHOLDS,
    'mixer_high_pass': 0,
    'mixer_high_warn': 1,
    'stutter_pass': 0,
    'stutter_warn': 2,
    'lufs_jump_pass': 2.0,
    'lufs_jump_warn': 3.5,
    'drift_pass': 5.0,
    'drift_warn': 10.0,
}


# ---- Verdict Logic -------------------------------------------------------

def validate(analysis: dict, strict: bool = False) -> dict:
    """
    Takes structured analysis dict (from mix_analyzer --json).
    Returns: {'verdict': 'PASS'|'WARN'|'FAIL', 'issues': [...], 'recommendations': [...]}
    """
    thr = STRICT_THRESHOLDS if strict else THRESHOLDS
    issues = []
    verdict = 'PASS'

    def downgrade(level):
        nonlocal verdict
        if level == 'FAIL':
            verdict = 'FAIL'
        elif level == 'WARN' and verdict == 'PASS':
            verdict = 'WARN'

    def ts(sec):
        return f"{int(sec//60):02d}:{int(sec%60):02d}"

    # 1. Mixer-induced artefacts
    mixer_arts = analysis.get('mixer_issues', [])
    high = [a for a in mixer_arts if a.get('severity') == 'high']
    mid  = [a for a in mixer_arts if a.get('severity') == 'mid']

    speed_glitches = [a for a in mixer_arts if a['type'] == 'speed_glitch']
    stutters       = [a for a in mixer_arts if a['type'] == 'stutter']
    hf_noise       = [a for a in mixer_arts if a['type'] == 'hf_noise']

    if len(high) > thr['mixer_high_warn']:
        downgrade('FAIL')
        issues.append(f"[FAIL] {len(high)} high-severity mixer artefacts "
                      f"(limit {thr['mixer_high_warn']})")
    elif len(high) > thr['mixer_high_pass']:
        downgrade('WARN')
        issues.append(f"[WARN] {len(high)} high-severity mixer artefacts")

    if len(speed_glitches) > thr['speed_glitch_warn']:
        downgrade('FAIL')
        issues.append(f"[FAIL] {len(speed_glitches)} speed glitches detected")
    elif len(speed_glitches) > thr['speed_glitch_pass']:
        downgrade('WARN')
        tlist = ', '.join(ts(a['t']) for a in speed_glitches[:3])
        issues.append(f"[WARN] speed glitch @ {tlist}")

    if len(stutters) > thr['stutter_warn']:
        downgrade('FAIL')
        issues.append(f"[FAIL] {len(stutters)} stutter events (limit {thr['stutter_warn']})")
    elif len(stutters) > thr['stutter_pass']:
        downgrade('WARN')
        tlist = ', '.join(ts(a['t']) for a in stutters[:4])
        issues.append(f"[WARN] {len(stutters)} stutter events @ {tlist}")

    if len(hf_noise) > 5:
        downgrade('WARN')
        issues.append(f"[WARN] {len(hf_noise)} HF noise events (rubberband artifacts) "
                      f"-- try --no-stabilizer or increase RAMP_SEC")

    # 2. Transition quality
    for tr in analysis.get('transitions', []):
        name = f"{tr.get('master_name','?')}->{tr.get('slave_name','?')}"
        t = tr.get('t', 0)

        lufs = abs(tr.get('lufs_jump_db', 0))
        if lufs > thr['lufs_jump_warn']:
            downgrade('FAIL')
            issues.append(f"[FAIL] {name} @ {ts(t)}: LUFS jump {lufs:+.1f}dB "
                          f"(limit {thr['lufs_jump_warn']}dB)")
        elif lufs > thr['lufs_jump_pass']:
            downgrade('WARN')
            issues.append(f"[WARN] {name} @ {ts(t)}: LUFS jump {lufs:+.1f}dB")

        drift = abs(tr.get('reported_shift_ms', 0))
        if drift > thr['drift_warn']:
            downgrade('FAIL')
            issues.append(f"[FAIL] {name} @ {ts(t)}: beat drift {drift:.1f}ms "
                          f"(limit {thr['drift_warn']}ms)")
        elif drift > thr['drift_pass']:
            downgrade('WARN')
            issues.append(f"[WARN] {name} @ {ts(t)}: beat drift {drift:.1f}ms")

    # 3. Key compatibility
    source_info = analysis.get('source_info', {})
    names = list(source_info.keys())
    for i in range(len(names) - 1):
        k1 = source_info[names[i]].get('key', '?')
        k2 = source_info[names[i+1]].get('key', '?')
        compat = _key_compat_score(k1, k2)
        if compat <= thr['key_compat_fail']:
            downgrade('FAIL')
            issues.append(f"[FAIL] key clash: {names[i]}({k1}) -> {names[i+1]}({k2}) "
                          f"score={compat:.1f}")
        elif compat < thr['key_compat_warn']:
            downgrade('WARN')
            issues.append(f"[WARN] key mismatch: {names[i]}({k1}) -> {names[i+1]}({k2}) "
                          f"score={compat:.1f}")

    # 4. Source issues (not mixer's fault, but noteworthy)
    src_issues = analysis.get('source_issues', [])
    if len(src_issues) > 10:
        issues.append(f"[INFO] {len(src_issues)} artefacts in source tracks "
                      f"(not mixer-induced)")

    # 5. Build recommendations from existing feedback
    recommendations = []
    for fb in analysis.get('feedback', []):
        sev = fb.get('severity', 'mid')
        param = fb.get('parameter', '')
        suggestion = fb.get('suggestion', '')
        icon = "🔴" if sev == 'high' else "🟡"
        recommendations.append(f"{icon} [{param}] {suggestion}")

    # Generic recs based on verdict
    if verdict == 'FAIL' and not recommendations:
        if any('speed_glitch' in i for i in issues):
            recommendations.append("🔴 Try increasing RAMP_SEC (15->20) "
                                    "or skip ramp for transitions < 1 BPM diff")
        if any('stutter' in i for i in issues):
            recommendations.append("🔴 Reduce warp rate_threshold 0.002->0.001")
        if any('LUFS' in i for i in issues):
            recommendations.append("🟡 Check per-track LUFS normalization "
                                    "(full-track sample vs 30s sample mismatch)")

    return {
        'verdict': verdict,
        'issues': issues,
        'recommendations': recommendations,
        'counts': {
            'mixer_high': len(high),
            'mixer_mid': len(mid),
            'speed_glitch': len(speed_glitches),
            'stutter': len(stutters),
            'hf_noise': len(hf_noise),
            'source_issues': len(src_issues),
        }
    }


def _key_compat_score(k1, k2):
    CAMELOT = {
        'C maj':'8B','C# maj':'3B','D maj':'10B','D# maj':'5B','E maj':'12B',
        'F maj':'7B','F# maj':'2B','G maj':'9B','G# maj':'4B','A maj':'11B',
        'A# maj':'6B','B maj':'1B',
        'C min':'5A','C# min':'12A','D min':'7A','D# min':'2A','E min':'9A',
        'F min':'4A','F# min':'11A','G min':'6A','G# min':'1A','A min':'8A',
        'A# min':'3A','B min':'10A',
    }
    c1 = CAMELOT.get(k1); c2 = CAMELOT.get(k2)
    if not c1 or not c2:
        return 0.5
    n1, t1 = int(c1[:-1]), c1[-1]
    n2, t2 = int(c2[:-1]), c2[-1]
    if c1 == c2:
        return 1.0
    if n1 == n2 and t1 != t2:
        return 0.8
    if t1 == t2 and abs(n1 - n2) in (1, 11):
        return 0.9
    return 0.3


def print_report(result: dict, mix_path: str = ''):
    verdict = result['verdict']
    icon = {'PASS': '✅', 'WARN': '⚠️', 'FAIL': '❌'}[verdict]

    print(f"\n{'='*50}")
    print(f"  MIX VALIDATION {icon}  {verdict}")
    if mix_path:
        print(f"  {os.path.basename(mix_path)}")
    print(f"{'='*50}")

    c = result['counts']
    print(f"\n  Artefacts (mixer-induced): {c['mixer_high']} high, {c['mixer_mid']} mid")
    print(f"  Speed glitches: {c['speed_glitch']}  |  Stutters: {c['stutter']}")
    print(f"  HF noise (rubberband): {c['hf_noise']}")
    print(f"  Source issues (not our fault): {c['source_issues']}")

    if result['issues']:
        print(f"\n  Issues:")
        for issue in result['issues']:
            print(f"    {issue}")

    if result['recommendations']:
        print(f"\n  Recommendations:")
        for rec in result['recommendations']:
            print(f"    {rec}")

    if verdict == 'PASS':
        print(f"\n  Ready to deliver.")
    elif verdict == 'WARN':
        print(f"\n  Listenable, but check the issues above.")
    else:
        print(f"\n  Do not deliver. Fix issues and re-run.")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mix quality validator")
    parser.add_argument("--json", required=True, help="JSON file from mix_analyzer --json")
    parser.add_argument("--strict", action="store_true",
                        help="Apply stricter thresholds")
    parser.add_argument("--mix", default="", help="Mix path (for display only)")
    args = parser.parse_args()

    if not os.path.exists(args.json):
        print(f"Error: {args.json} not found")
        sys.exit(2)

    with open(args.json) as f:
        analysis = json.load(f)

    result = validate(analysis, strict=args.strict)
    print_report(result, args.mix)

    exit_codes = {'PASS': 0, 'WARN': 1, 'FAIL': 2}
    sys.exit(exit_codes[result['verdict']])
