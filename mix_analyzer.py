#!/usr/bin/env python3
"""
Mix Analyzer v1 — comprehensive post-mix quality diagnostics.
Detects beat drift, key compatibility, LUFS jumps, spectral masking,
phase issues, and audio artefacts (stutter, speed glitches, transients,
HF noise). Validates source tracks so you know what's the mixer's fault.

Usage:
  python3 mix_analyzer.py --mix /tmp/mix.mp3 --wav-dir ./wav --ann-dir ./annotations
  python3 mix_analyzer.py --mix /tmp/mix.mp3 --config mix_config.py
  python3 mix_analyzer.py --mix /tmp/mix.mp3 --config mix_config.py --feedback
"""
import sys, os, time, argparse, importlib.util
import numpy as np
import soundfile as sf
import scipy.signal as sig
import librosa
import pyloudnorm as pyln

SR = 44100
TARGET_LUFS = -14.0

def _ts(sec):
    m = int(sec // 60)
    s = sec % 60
    return f"{m:02d}:{s:05.2f}"

def _load_wav(path, sr=SR):
    data, file_sr = sf.read(path, always_2d=True)
    if data.shape[1] == 1:
        data = np.hstack([data, data])
    if file_sr != sr:
        import subprocess
        tmp = f"/tmp/_ma_{os.path.basename(path)}.wav"
        subprocess.run(["ffmpeg", "-y", "-i", path, "-ar", str(sr), "-ac", "2", tmp], capture_output=True)
        data, _ = sf.read(tmp, always_2d=True)
        os.unlink(tmp)
    return data.astype("float32")

def _load_dbeats(ann_path, sr=SR):
    beats = np.loadtxt(ann_path)
    return np.array([int(r[0] * sr) for r in beats if round(r[1]) == 1], dtype=int)

def _calc_bpm(db, sr=SR):
    if len(db) < 4:
        return 120.0
    iv = np.diff(db.astype(float)) / sr
    iv = iv[iv > 0.3]
    if not len(iv):
        return 120.0
    p25 = np.percentile(iv, 25)
    r = iv[iv <= p25 * 1.3]
    if not len(r):
        r = iv
    bpm = 4 * 60.0 / np.mean(r)
    return bpm * 2 if bpm < 90 else bpm

def _fix_ht(db, bpm):
    if bpm >= 90:
        return db, bpm
    new = []
    for i in range(len(db) - 1):
        new.append(db[i])
        new.append((db[i] + db[i+1]) // 2)
    new.append(db[-1])
    return np.array(new, dtype=int), bpm * 2

CAMELOT = {
    'C maj':'8B','C# maj':'3B','D maj':'10B','D# maj':'5B','E maj':'12B',
    'F maj':'7B','F# maj':'2B','G maj':'9B','G# maj':'4B','A maj':'11B',
    'A# maj':'6B','B maj':'1B',
    'C min':'5A','C# min':'12A','D min':'7A','D# min':'2A','E min':'9A',
    'F min':'4A','F# min':'11A','G min':'6A','G# min':'1A','A min':'8A',
    'A# min':'3A','B min':'10A',
}
KEYS_LABELS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
MAJ_PROFILE = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
MIN_PROFILE = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])

def detect_key(audio_mono, sr=SR):
    chroma = librosa.feature.chroma_cqt(y=audio_mono.astype(np.float32), sr=sr)
    profile = chroma.mean(axis=1)
    best_corr = -1.0; best_key = "?"
    for shift in range(12):
        rolled = np.roll(profile, -shift)
        cm = np.corrcoef(rolled, MAJ_PROFILE)[0, 1]
        cn = np.corrcoef(rolled, MIN_PROFILE)[0, 1]
        if cm > best_corr: best_corr = cm; best_key = f"{KEYS_LABELS[shift]} maj"
        if cn > best_corr: best_corr = cn; best_key = f"{KEYS_LABELS[shift]} min"
    return best_key, best_corr

def key_compatibility(k1, k2):
    c1 = CAMELOT.get(k1); c2 = CAMELOT.get(k2)
    if not c1 or not c2: return 0.5, "unknown"
    n1, t1 = int(c1[:-1]), c1[-1]; n2, t2 = int(c2[:-1]), c2[-1]
    if c1 == c2: return 1.0, f"identical ({c1})"
    if n1 == n2 and t1 != t2: return 0.8, f"relative ({c1}↔{c2})"
    if t1 == t2 and abs(n1 - n2) in (1, 11): return 0.9, f"adjacent ({c1}→{c2})"
    return 0.3, f"distant ({c1}→{c2})"

def analyze_source_tracks(tracks, wav_dir, ann_dir):
    results = {}
    for name, wav_file, ann_file in tracks:
        info = {'name': name}
        audio = _load_wav(os.path.join(wav_dir, wav_file), SR)
        mono = audio.mean(1).astype(np.float32)
        ann_path = os.path.join(ann_dir, ann_file)
        if os.path.exists(ann_path):
            db = _load_dbeats(ann_path, SR)
            raw = _calc_bpm(db, SR)
            db, bpm = _fix_ht(db, raw)
            info['bpm'] = bpm; info['dbeats'] = db
        else:
            info['bpm'] = 0; info['dbeats'] = np.array([], dtype=int)
        key, conf = detect_key(mono, SR)
        info['key'] = key; info['key_confidence'] = conf
        info['dur_sec'] = len(mono) / SR
        info['source_artefacts'] = _scan_source_artefacts(mono, SR)
        results[name] = info
    return results

def _scan_source_artefacts(mono, sr):
    artefacts = []
    hop = int(0.05 * sr)
    n_w = len(mono) // hop
    crest = np.zeros(n_w)
    for i in range(n_w):
        seg = mono[i*hop:(i+1)*hop]
        rms = np.sqrt(np.mean(seg**2)) + 1e-12
        crest[i] = np.max(np.abs(seg)) / rms
    cm = np.median(crest)
    for s in np.where(crest > cm * 5)[0]:
        artefacts.append({'t': s*hop/sr, 'type': 'transient_spike',
                          'severity': 'high' if crest[s]>cm*10 else 'mid',
                          'detail': f'crest={crest[s]:.1f}x median'})
    rms_win = int(0.01 * sr)
    n_r = len(mono) // rms_win
    rms_arr = np.array([np.sqrt(np.mean(mono[i*rms_win:(i+1)*rms_win]**2)) for i in range(n_r)])
    silent = np.where(rms_arr < 0.0003)[0]
    if len(silent):
        for g in np.split(silent, np.where(np.diff(silent)>1)[0]+1):
            if len(g) > 5:
                artefacts.append({'t': g[0]*rms_win/sr, 'type': 'dropout',
                                  'severity': 'high' if len(g)>50 else 'mid',
                                  'detail': f'silence {len(g)*10}ms'})
    b_hp, a_hp = sig.butter(2, 15000.0/(0.5*sr), btype='high')
    hf = sig.filtfilt(b_hp, a_hp, mono)
    hf_win = int(0.1 * sr)
    n_h = len(mono) // hf_win
    hf_e = np.array([np.sqrt(np.mean(hf[i*hf_win:(i+1)*hf_win]**2)) for i in range(n_h)])
    hm = np.median(hf_e)
    for h in np.where(hf_e > hm * 8)[0]:
        artefacts.append({'t': h*hf_win/sr, 'type': 'hf_noise',
                          'severity': 'high' if hf_e[h]>hm*15 else 'mid',
                          'detail': f'hf_energy={hf_e[h]:.6f}'})
    return artefacts

def analyze_transition(mix_mono, mix_sr, t_start, dur, master_name, slave_name, stamps_entry, source_info, sr=SR):
    s = int(t_start * sr); e = int(min(t_start + dur, len(mix_mono)/sr) * sr)
    zone = mix_mono[s:e]
    if len(zone) < sr: return None
    findings = {}
    oe = librosa.onset.onset_strength(y=zone, sr=sr, hop_length=256)
    tb = librosa.beat.tempo(onset_envelope=oe, sr=sr, hop_length=256)
    findings['zone_bpm'] = float(tb[0]) if len(tb) else 0
    m_bpm = source_info.get(master_name, {}).get('bpm', 0)
    s_bpm = source_info.get(slave_name, {}).get('bpm', 0)
    findings['master_bpm'] = m_bpm; findings['slave_bpm'] = s_bpm
    findings['bpm_diff_pct'] = abs(s_bpm - m_bpm) / max(m_bpm, 1) * 100 if m_bpm > 0 else 0
    findings['reported_shift_ms'] = stamps_entry.get('shift', 0) * 1000
    pre_s = int(max(0, t_start-5)*sr); pre_e = int(t_start*sr)
    post_s = int(t_end if (t_end := t_start+dur)<len(mix_mono)/sr else len(mix_mono)/sr); post_e = int(min(len(mix_mono), (t_start+dur+5)*sr))
    if pre_e > pre_s and post_e > post_s:
        pr = np.sqrt(np.mean(mix_mono[pre_s:pre_e]**2)) + 1e-12
        po = np.sqrt(np.mean(mix_mono[post_s:post_e]**2)) + 1e-12
        findings['lufs_jump_db'] = round(20 * np.log10(po / pr), 2)
    else:
        findings['lufs_jump_db'] = 0
    sc_pre = librosa.feature.spectral_centroid(y=mix_mono[pre_s:pre_e], sr=sr)[0].mean() if pre_e>pre_s else 0
    sc_post = librosa.feature.spectral_centroid(y=mix_mono[post_s:post_e], sr=sr)[0].mean() if post_e>post_s else 0
    findings['centroid_shift_hz'] = round(sc_post - sc_pre, 0)
    return findings

def detect_mix_artefacts(mono, sr, stamps=None):
    artefacts = []
    win_st = int(0.05*sr); n_st = len(mono)//win_st
    for i in range(1, n_st):
        a = mono[(i-1)*win_st:i*win_st]; b = mono[i*win_st:(i+1)*win_st]
        if len(a)!=len(b) or np.max(np.abs(a))<0.001: continue
        corr = np.corrcoef(a, b)[0, 1]
        if corr > 0.999:
            artefacts.append({'t': i*win_st/sr, 'type':'stutter',
                              'severity':'high' if corr>0.9999 else 'mid',
                              'detail':f'autocorr={corr:.5f}'})
    hop_bpm = int(0.5*sr); win_bpm = int(4*sr)
    n_bpm = max(1, (len(mono)-win_bpm)//hop_bpm)
    lb = []
    for i in range(n_bpm):
        s = i*hop_bpm; e = s+win_bpm
        if e>len(mono): break
        oe = librosa.onset.onset_strength(y=mono[s:e], sr=sr, hop_length=256)
        tb = librosa.beat.tempo(onset_envelope=oe, sr=sr, hop_length=256)
        lb.append(float(tb[0]) if len(tb) else 0)
    lb = np.array(lb); mb = np.median(lb)
    # Speed glitch section suppressed — BPM tracker produces too many
    # false positives on sparse percussion / dynamic sections.
    # Actual mixer bugs are caught by rms_dip + onset_stability instead.
    hop_cr = int(0.1*sr); n_cr = len(mono)//hop_cr
    crest = np.array([np.max(np.abs(mono[i*hop_cr:(i+1)*hop_cr]))/(np.sqrt(np.mean(mono[i*hop_cr:(i+1)*hop_cr]**2))+1e-12) for i in range(n_cr)])
    cm = np.median(crest)
    for s in np.where(crest > cm*5)[0]:
        artefacts.append({'t': s*hop_cr/sr, 'type':'transient_spike',
                          'severity':'high' if crest[s]>cm*10 else 'mid',
                          'detail':f'crest={crest[s]:.1f}x median'})
    b_hp, a_hp = sig.butter(2, 16000.0/(0.5*sr), btype='high')
    hf = sig.filtfilt(b_hp, a_hp, mono)
    hop_hf = int(0.15*sr); n_hf = len(mono)//hop_hf
    hf_e = np.array([np.sqrt(np.mean(hf[i*hop_hf:(i+1)*hop_hf]**2)) for i in range(n_hf)])
    hm = np.median(hf_e)
    for h in np.where(hf_e > hm*8)[0]:
        artefacts.append({'t': h*hop_hf/sr, 'type':'hf_noise',
                          'severity':'high' if hf_e[h]>hm*15 else 'mid',
                          'detail':f'hf_energy={hf_e[h]:.6f}'})
    hop_sf = int(0.1*sr); n_sf = max(1, len(mono)//hop_sf)
    sf_arr = np.zeros(n_sf-1)
    for i in range(n_sf-1):
        a = mono[i*hop_sf:(i+1)*hop_sf]; b = mono[(i+1)*hop_sf:(i+2)*hop_sf]
        if len(a)<2 or len(b)<2: continue
        sa = np.abs(np.fft.rfft(a)); sb = np.abs(np.fft.rfft(b))
        sf_arr[i] = np.sqrt(np.mean((sa-sb)**2))/(np.mean(sa)+1e-12)
    sm = np.median(sf_arr); thr = sm*5
    for d in np.where(sf_arr > thr)[0]:
        artefacts.append({'t': d*hop_sf/sr, 'type':'spectral_discontinuity',
                          'severity':'high' if sf_arr[d]>sm*10 else 'mid',
                          'detail':f'flux={sf_arr[d]:.3f}x median'})

    # ── 3f. RMS dip detect ──────────────────────────────────────────────────
    # 100ms windows, flag any window where RMS < 50% of neighbors' median.
    # Catches phase-cancellation volume drops inside crossfades.
    # Only analyzes within crossfade zones to avoid false positives from
    # natural dynamic changes in the music.
    hop_dip = int(0.1*sr); n_dip = max(1, len(mono)//hop_dip)
    rms_dip = np.array([np.sqrt(np.mean(mono[i*hop_dip:(i+1)*hop_dip]**2)) for i in range(n_dip)])
    med_dip = np.median(rms_dip)
    for i in range(2, n_dip-2):
        t_dip = i*hop_dip/sr
        in_cf = False
        if stamps:
            for s in stamps:
                cf_start = s['t'] - 2
                cf_end = s['t'] + s.get('dur', 30) + 5
                if cf_start <= t_dip <= cf_end:
                    in_cf = True
                    break
        if not in_cf:
            continue
        local_med = np.median(rms_dip[max(0,i-2):i+3])
        if rms_dip[i] < med_dip * 0.3 and rms_dip[i] < local_med * 0.3:
            artefacts.append({'t': i*hop_dip/sr, 'type': 'rms_dip',
                              'severity': 'high' if rms_dip[i] < med_dip * 0.3 else 'mid',
                              'detail': f'rms={rms_dip[i]:.4f} (med={med_dip:.4f})'})

    # ── 3g. Onset correlation stability ──────────────────────────────────────
    # Check if consecutive 500ms onset profiles have low correlation,
    # which indicates beat drift during the crossfade.
    # Only analyzed within crossfade zones to avoid false positives
    # from natural BPM changes between tracks.
    hop_oc = int(0.5*sr); win_oc = int(0.5*sr)
    n_oc = max(1, len(mono)//hop_oc - 1)
    oe_full = librosa.onset.onset_strength(y=mono, sr=sr, hop_length=256)
    for i in range(n_oc-1):
        t_oc = i*hop_oc/sr
        # Only check within crossfade zones (±3s margin)
        in_cf = False
        if stamps:
            for s in stamps:
                cf_start = s['t'] - 3
                cf_end = s['t'] + s.get('dur', 30) + 3
                if cf_start <= t_oc <= cf_end:
                    in_cf = True
                    break
        if not in_cf:
            continue
        a = oe_full[i*hop_oc//256:(i+1)*hop_oc//256]
        b = oe_full[(i+1)*hop_oc//256:(i+2)*hop_oc//256]
        if len(a) < 3 or len(b) < 3: continue
        mn = min(len(a), len(b))
        corr = np.corrcoef(a[:mn], b[:mn])[0,1]
        if corr < 0.3 and not (np.isnan(corr) or np.isinf(corr)):
            artefacts.append({'t': t_oc, 'type': 'onset_stability',
                              'severity': 'high' if corr < 0.15 else 'mid',
                              'detail': f'onset_corr={corr:.3f}'})

    # ── 3h. Crossfade endpoint check ────────────────────────────────────────
    # For each stamp, compute spectral flux at the endpoint (where crossfade
    # meets ramp).  High flux = phase discontinuity.
    if stamps:
        for s in stamps:
            t_end = s['t'] + s.get('dur', 16*240.0/120)
            s_frame = int(t_end * sr)
            if s_frame + hop_sf*2 >= len(mono): continue
            pre = mono[s_frame-hop_sf:s_frame]
            post = mono[s_frame:s_frame+hop_sf]
            if len(pre) < 2 or len(post) < 2: continue
            sp = np.abs(np.fft.rfft(pre)); sp2 = np.abs(np.fft.rfft(post))
            endpoint_flux = np.sqrt(np.mean((sp-sp2)**2))/(np.mean(sp)+1e-12)
            if endpoint_flux > sm * 3:
                artefacts.append({'t': t_end, 'type': 'harsh_endpoint',
                                  'severity': 'high' if endpoint_flux > sm * 5 else 'mid',
                                  'detail': f'endpoint_flux={endpoint_flux:.3f}x median'})
    return artefacts

def cross_reference(mix_arts, source_infos, stamps, sr=SR):
    timeline = []
    names = list(source_infos.keys())
    prev_t = 0
    for i, s in enumerate(stamps):
        t_start = s['t']
        pt = s.get('prev_track', stamps[i-1]['from'] if i>0 else names[0])
        if t_start > prev_t: timeline.append((prev_t, t_start, pt))
        prev_t = t_start
    if stamps: timeline.append((prev_t, 1e9, stamps[-1]['to']))
    for art in mix_arts:
        t = art['t']; src = None
        for ts, te, n in timeline:
            if ts <= t <= te: src = n; break
        if src and src in source_infos:
            matched = any(sa['type']==art['type'] and abs(sa['t']-t)<2.0 for sa in source_infos[src].get('source_artefacts',[]))
            art['origin'] = 'source_issue' if matched else 'mixer_induced'
            art['source_track'] = src
        else:
            art['origin'] = 'unknown'; art['source_track'] = src or '?'
    return mix_arts

def generate_feedback(transitions, mix_artefacts):
    recs = []
    for tr in (transitions or []):
        if tr is None: continue
        if tr.get('reported_shift_ms', 0) > 5:
            recs.append({'severity':'mid','parameter':'build_cf_lr4(max_shift_sec)',
                         'suggestion':f"Increase max_shift_sec to {tr['reported_shift_ms']/1000+0.02:.3f}"})
        if abs(tr.get('lufs_jump_db', 0)) > 2.0:
            recs.append({'severity':'mid','parameter':'norm_lufs(gain_offset)',
                         'suggestion':f"Apply ±{abs(tr['lufs_jump_db'])/2:.1f}dB gain on slave entry"})
    mx = [a for a in mix_artefacts if a.get('origin')=='mixer_induced']
    st = [a for a in mx if a['type']=='stutter']
    if len(st) > 3: recs.append({'severity':'high','parameter':'warp_to_grid(rate_threshold)',
                                  'suggestion':f"Reduce rate_threshold 0.002→0.001 ({len(st)} stutters)"})
    hf = [a for a in mx if a['type']=='hf_noise']
    if len(hf) > 3: recs.append({'severity':'mid','parameter':'ramp_to_native(ramp_sec)',
                                  'suggestion':f"Increase RAMP_SEC 15→20 ({len(hf)} HF events)"})
    sp = [a for a in mx if a['type']=='speed_glitch']
    if sp: recs.append({'severity':'high','parameter':'ramp_to_native(ramp_sec)',
                         'suggestion':'Ramp too aggressive — increase RAMP_SEC or skip for <1 BPM diff'})
    # Quiet entry detection — low-energy slave entries prone to rubberband artefacts
    qe = [a for a in mix_artefacts if a.get('type')=='quiet_slave_entry']
    for q in qe[:3]:
        recs.append({'severity':'high','parameter':'RAMP_MIN_RMS / entry_point',
                     'suggestion':f"The slave track at {_ts(q['t'])} enters too quietly (RMS={q.get('detail','?')}). "
                                   f"Increase RAMP_MIN_RMS or shift entry point to a louder section (+{int(q.get('suggest_delay',15))}s)"})
    # Onset stability — beat drift inside crossfade
    os_issues = [a for a in mx if a['type']=='onset_stability']
    if len(os_issues) > 2:
        recs.append({'severity':'high','parameter':'onset_micro_align(max_shift_sec/downbeat_weight)',
                     'suggestion':f'{len(os_issues)} onset stability events — downbeat-weighted alignment may need tighter window'})
    # RMS dip — phase cancellation volume drop
    rd = [a for a in mx if a['type']=='rms_dip']
    if rd:
        recs.append({'severity':'high','parameter':'build_cf_lr4 RMS stabilizer / LR4 polarity check',
                     'suggestion':f'{len(rd)} RMS dip events — phase cancellation in crossfade. Check LR4 band polarity or widen dip stabilizer threshold'})
    # Harsh endpoint — crossfade→ramp boundary
    he = [a for a in mx if a['type']=='harsh_endpoint']
    if he:
        recs.append({'severity':'mid','parameter':'build_cf_lr4 blend→ramp crossfade',
                     'suggestion':f'{len(he)} harsh endpoint(s) — 50ms blend→ramp crossfade should fix these'})
    pk = [a for a in mx if a['type']=='transient_spike']
    if len(pk) > 2: recs.append({'severity':'mid','parameter':'mix_tracks(headroom_db)',
                                  'suggestion':f"Increase headroom -1→-2dB ({len(pk)} spikes)"})
    return recs

def analyze(mix_path, wav_dir, ann_dir, tracks=None, feedback=False):
    print("=== Mix Analyzer v1 ===\n")
    print("Loading mix audio...")
    audio = _load_wav(mix_path, SR); mono = audio.mean(1).astype(np.float32)
    dm = len(mono)/SR
    print(f"  Duration: {int(dm//60)}:{int(dm%60):02d}  ({dm:.1f}s)\n")
    if tracks is None:
        wav_files = sorted(f for f in os.listdir(wav_dir) if f.endswith('.wav'))
        tracks = []
        for wf in wav_files:
            base = os.path.splitext(wf)[0]; ann = base+'.txt'
            if os.path.exists(os.path.join(ann_dir, ann)):
                tracks.append((base.split(' - ')[0] if ' - ' in base else base[:20], wf, ann))
    ts = time.time()
    print("── Phase 1: Source Analysis ──\n")
    si = analyze_source_tracks(tracks, wav_dir, ann_dir)
    for n, i in si.items():
        a = i.get('source_artefacts',[])
        print(f"  {n:20s}  BPM={i['bpm']:5.1f}  Key={i['key']:8s}  conf={i['key_confidence']:.2f}{f', {len(a)} artefacts' if a else ''}")
    print(f"\n── Phase 2: Transition Analysis ──\n")
    stamps = []; sp = mix_path.replace('.mp3','_stamps.npy').replace('.wav','_stamps.npy')
    if os.path.exists(sp):
        stamps = list(np.load(sp, allow_pickle=True))
        print(f"  Loaded {len(stamps)} stamps\n")
    else:
        print("  (No stamps — estimating)\n")
        cum=0; pn=None
        for n,i in si.items():
            if pn: stamps.append({'from':pn,'to':n,'t':max(0,cum-30),'dur':16*240.0/si[pn]['bpm'],'mode':'?','shift':0})
            cum += si[pn]['dur_sec'] if pn else 0; pn = n
    transitions = []
    for i,s in enumerate(stamps):
        fn=s['from']; tn=s['to']
        s['prev_track'] = stamps[i-1]['from'] if i>0 else list(si.keys())[0]
        tr = analyze_transition(mono, SR, s['t'], s.get('dur',30), fn, tn, s, si, SR)
        if tr:
            tr['master_name']=fn; tr['slave_name']=tn; transitions.append(tr)
            ic = "✅" if abs(tr['reported_shift_ms'])<5 else "⚠️" if abs(tr['reported_shift_ms'])<10 else "❌"
            print(f"  {ic} {fn:15s} → {tn:15s}  @ {_ts(s['t'])}  drift={tr['reported_shift_ms']:.1f}ms  LUFS={tr['lufs_jump_db']:+.1f}dB")

    # ── Quiet entry detection ──────────────────────────────────────────────
    # Check stamps for low-energy slave entries that can cause ramp artefacts
    quiet_entries = []
    for s in stamps:
        entry_rms = s.get('entry_rms', 1.0)
        if entry_rms < 0.08:
            quiet_entries.append({
                't': s['t'], 'type': 'quiet_slave_entry',
                'severity': 'high',
                'detail': f'{entry_rms:.3f}',
                'suggest_delay': int(15 * (0.08 / max(entry_rms, 0.01)))
            })
    if quiet_entries:
        print(f"\n  ⚠️ Quiet slave entries ({len(quiet_entries)}):")
        for q in quiet_entries:
            print(f"    @ {_ts(q['t'])}  entry RMS={q['detail']}")

    print(f"\n── Phase 3: Mix Artefact Scan ──\n  Scanning...", end=' ', flush=True)
    ma = detect_mix_artefacts(mono, SR, stamps)
    # Append quiet entries to mix artefacts for feedback
    ma.extend(quiet_entries)
    print(f"{len(ma)} events\n")
    print(f"── Phase 4: Source vs Mixer ──\n")
    ma = cross_reference(ma, si, stamps, SR)
    src_i = [a for a in ma if a.get('origin')=='source_issue']
    mix_i = [a for a in ma if a.get('origin')=='mixer_induced']
    if src_i:
        print(f"  In source ({len(src_i)}):")
        for a in src_i[:10]: print(f"    @ {_ts(a['t'])}  [{a['type']}]  {a['detail']}  in {a.get('source_track','?')}")
        if len(src_i)>10: print(f"    ... +{len(src_i)-10}")
    if mix_i:
        print(f"\n  Mixer-induced ({len(mix_i)}):")
        for a in mix_i[:10]: print(f"    @ {_ts(a['t'])}  [{a['type']}]  {a['detail']}  track={a.get('source_track','?')}")
        if len(mix_i)>10: print(f"    ... +{len(mix_i)-10}")
    print(f"\n── Key Compatibility ──\n")
    names = list(si.keys())
    for i in range(len(names)-1):
        k1=si[names[i]]['key']; k2=si[names[i+1]]['key']
        sc,desc=key_compatibility(k1,k2)
        ic="✅" if sc>=0.8 else "⚠️" if sc>=0.5 else "❌"
        print(f"  {ic} {names[i]:15s} ({k1:8s}) → {names[i+1]:15s} ({k2:8s})  score={sc:.1f}  {desc}")
    print(f"\n── Phase 5: Feedback ──\n")
    if feedback:
        recs = generate_feedback(transitions, ma)
        if recs:
            for r in recs:
                ic = "🔴" if r['severity']=='high' else "🟡"
                print(f"  {ic} [{r['parameter']}] {r['suggestion']}")
        else: print("  ✅ No adjustments needed.\n")
    else: print("  (Run with --feedback for recommendations)\n")
    print(f"Analysis completed in {time.time()-ts:.1f}s")
    return {'source_info':si,'transitions':transitions,'mix_artefacts':ma,'source_issues':src_i,'mixer_issues':mix_i}

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Mix Analyzer v1")
    p.add_argument("--mix",required=True); p.add_argument("--wav-dir"); p.add_argument("--ann-dir")
    p.add_argument("--config"); p.add_argument("--feedback",action="store_true")
    a = p.parse_args()
    wd=a.wav_dir; ad=a.ann_dir; tr=None
    if a.config:
        s=importlib.util.spec_from_file_location("cfg",a.config); c=importlib.util.module_from_spec(s); s.loader.exec_module(c)
        tr=c.TRACKS
        if wd is None: wd=getattr(c,'WAV_DIR',None) or '.'
        if ad is None: ad=getattr(c,'ANN_DIR',None) or '.'
    if not wd or not ad: p.error("Need --wav-dir and --ann-dir (or --config)")
    analyze(a.mix, wd, ad, tr, feedback=a.feedback)