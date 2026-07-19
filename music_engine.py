#!/usr/bin/env python3
"""
music_engine.py — Universal Parametric Music Synthesis Engine

One engine for all styles. Style defined by JSON config.
Usage: python render.py styles/cosmic_techno.json

Architecture:
  DSP layer      — sine, saw, noise, filters, envelope, fade, stamp
  Synth layer    — kick, snare, hat, clap, acid, pad, drone, texture, bass
  Stereo layer   — haas, ping-pong, width
  Automation     — smooth keyframe curves (automation-driven, no section cuts)
  Renderers      — per-element full-track rendering
  Master bus     — compress, normalize, encode
"""
import numpy as np, scipy.signal, scipy.ndimage, soundfile as sf
import os, json, tempfile, warnings
warnings.filterwarnings("ignore")


class MusicEngine:
    SR = 44100

    def __init__(self, style: dict):
        meta          = style['meta']
        self.style    = style
        self.BPM      = float(meta['bpm'])
        self.TOTAL_S  = int(meta['duration_s'])
        self.N        = self.TOTAL_S * self.SR
        self.OUT      = meta.get('out', 'output.mp3')
        self.SPB      = int(self.SR * 60 / self.BPM)
        self.BAR      = self.SPB * 4
        self.EIGHTH   = self.SPB // 2
        self.SIXTEENTH = self.SPB // 4
        self._T       = np.linspace(0, self.TOTAL_S, self.N, dtype=np.float32)
        np.random.seed(meta.get('seed', 42))
        self._build_automation()

    # ── automation ────────────────────────────────────────────────────────────

    def _build_automation(self):
        self.AUTO = {}
        for name, cfg in self.style.get('automation', {}).items():
            if not isinstance(cfg, dict): continue  # skip _comments
            self.AUTO[name] = self.auto(cfg['keyframes'], cfg.get('sigma_s', 4.0))

    def auto(self, keyframes, sigma_s=4.0):
        """keyframes: [[sec, val], ...] → smooth array of length N.
        Operates at 2 pts/sec to avoid huge convolution on full N."""
        kf_sec = [k[0] for k in keyframes]
        kf_val = [k[1] for k in keyframes]
        n_short = self.TOTAL_S * 2
        t_short = np.linspace(0, self.TOTAL_S, n_short)
        arr = np.interp(t_short, kf_sec, kf_val).astype(np.float32)
        if sigma_s > 0:
            arr = scipy.ndimage.gaussian_filter1d(arr, max(1.0, sigma_s * 2)).astype(np.float32)
        return np.interp(self._T, t_short, arr).astype(np.float32)

    def get_auto(self, name, default=1.0):
        if name in self.AUTO:
            return self.AUTO[name]
        return np.full(self.N, default, dtype=np.float32)

    # ── DSP primitives ────────────────────────────────────────────────────────

    def t_arr(self, n):
        return np.arange(n, dtype=np.float64) / self.SR

    def sine(self, freq, n, phase=0.0):
        return np.sin(2*np.pi*freq*self.t_arr(n) + phase).astype(np.float32)

    def saw(self, freq, n):
        t = self.t_arr(n)
        return (2*((freq*t) % 1.0) - 1).astype(np.float32)

    def square(self, freq, n):
        return np.sign(self.sine(freq, n)).astype(np.float32)

    def noise(self, n):
        return np.random.randn(n).astype(np.float32)

    def lp(self, a, cut, order=4):
        sos = scipy.signal.butter(order, np.clip(cut, 20, self.SR/2-50)/(self.SR/2), 'low', output='sos')
        return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

    def hp(self, a, cut, order=2):
        sos = scipy.signal.butter(order, np.clip(cut, 10, self.SR/2-50)/(self.SR/2), 'high', output='sos')
        return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

    def bp(self, a, lo, hi, order=2):
        lo = np.clip(lo, 20, self.SR/2-100)
        hi = np.clip(hi, lo+10, self.SR/2-50)
        sos = scipy.signal.butter(order, [lo/(self.SR/2), hi/(self.SR/2)], 'band', output='sos')
        return scipy.signal.sosfiltfilt(sos, a).astype(np.float32)

    def env_n(self, n, atk, dec, sus, rel):
        e = np.zeros(n, np.float32)
        a1 = min(int(atk), n); d1 = min(a1+int(dec), n); r0 = max(0, n-int(rel))
        if a1:    e[:a1]   = np.linspace(0, 1, a1)
        if d1>a1: e[a1:d1] = np.linspace(1, sus, d1-a1)
        if r0>d1: e[d1:r0] = sus
        if n>r0:  e[r0:]   = np.linspace(sus, 0, n-r0)
        return e

    def fade(self, a, fi=256, fo=512):
        a = a.copy()
        fi = min(fi, len(a)//4); fo = min(fo, len(a)//4)
        if fi > 1: a[:fi]  *= np.linspace(0, 1, fi, dtype=np.float32)
        if fo > 1: a[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
        return a

    def stamp(self, buf, hit, pos, gain=1.0):
        pos = int(pos)
        if pos < 0 or pos >= len(buf): return
        end = min(pos+len(hit), len(buf)); n = end-pos
        if n > 0: buf[pos:end] += hit[:n] * gain

    # ── humanization ──────────────────────────────────────────────────────────

    def humanize_pos(self, pos, jitter_ms=3.0):
        """Randomize note timing ±jitter_ms milliseconds."""
        j = int(np.random.normal(0, jitter_ms * self.SR / 1000))
        return max(0, int(pos) + j)

    def swing_offset(self, step_idx, step_n, swing=0.0):
        """Push every odd 16th note late (swing feel). swing=0.55 = light jazz."""
        if swing <= 0 or step_idx % 2 == 0: return 0
        return int(swing * step_n * 0.5)

    def humanize_vel(self, gain, variation=0.15):
        """Random velocity variation ±variation."""
        return float(gain) * np.random.uniform(1.0 - variation, 1.0)

    def load_sample(self, path, normalize=True, trim_silence=True):
        """Load a WAV/MP3 one-shot. Returns float32 mono array at SR=44100."""
        data, sr = sf.read(path)
        if data.ndim > 1: data = data.mean(axis=1)
        if sr != self.SR:
            from scipy.signal import resample as rs
            data = rs(data, int(len(data) * self.SR / sr)).astype(np.float32)
        data = data.astype(np.float32)
        if trim_silence:
            mask = np.abs(data) > 0.002
            if mask.any(): data = data[mask.argmax():]
        if normalize:
            peak = np.abs(data).max()
            if peak > 0: data /= peak
        return self.fade(data, fi=32, fo=512)

    def apply_fx(self, audio, chain):
        from pedalboard import Pedalboard
        board = Pedalboard(chain)
        if audio.ndim == 1: audio = audio[np.newaxis, :]
        return board(audio, self.SR).astype(np.float32)

    # ── drum synthesizers ─────────────────────────────────────────────────────

    def mk_kick(self, cfg=None):
        cfg = cfg or {}
        n = int(0.50*self.SR); t = self.t_arr(n)
        f = cfg.get('freq_start', 62) + cfg.get('freq_sweep', 145) * np.exp(-t*28)
        ph = 2*np.pi*np.cumsum(f)/self.SR
        body  = np.sin(ph).astype(np.float32) * np.exp(-t*cfg.get('decay', 7.5)).astype(np.float32)
        click = self.noise(n) * np.exp(-t.astype(np.float32)*450) * 0.15
        k = self.lp(body+click, 6200); k = self.hp(k, 24)
        clip = cfg.get('clip', 2.3)
        k = np.tanh(k*clip)/clip
        return self.fade(k/(np.abs(k).max()+1e-6), fi=8, fo=1024)

    def mk_snare(self, cfg=None):
        cfg = cfg or {}
        n = int(0.22*self.SR); t = self.t_arr(n)
        body = self.sine(cfg.get('tone', 215), n) * 0.18 * np.exp(-t*44)
        nz   = self.noise(n) * 0.82 * np.exp(-t*21)
        s    = (body + self.hp(nz, 160)) * self.env_n(n, 12, int(.025*self.SR), .11, int(.07*self.SR))
        return self.fade(np.tanh(s*2.9)/2.9, fi=8, fo=256)

    def mk_clap(self, cfg=None):
        cfg = cfg or {}
        n = int(0.18*self.SR); t = self.t_arr(n)
        nz  = self.noise(n) * np.exp(-t*30)
        nz2 = self.noise(n) * np.exp(-t*80) * 0.4
        c = self.bp(nz+nz2, 800, 6000) * self.env_n(n, 4, int(.015*self.SR), .15, int(.06*self.SR))
        return self.fade(np.tanh(c*3)/3, fi=4, fo=256)

    def mk_hat_c(self, cfg=None):
        cfg = cfg or {}
        freqs = cfg.get('freqs', [5300, 7200, 9700, 13000, 17000])
        n = int(0.030*self.SR); t = self.t_arr(n)
        h = sum(np.sign(self.sine(f, n)) for f in freqs).astype(np.float32)
        return self.fade((self.hp(h, 6500)*np.exp(-t.astype(np.float32)*170)/len(freqs)).astype(np.float32), fi=4, fo=64)

    def mk_hat_o(self, cfg=None):
        cfg = cfg or {}
        freqs = cfg.get('freqs', [5300, 7200, 9700, 13000, 17000])
        n = int(0.12*self.SR); t = self.t_arr(n)
        h = sum(np.sign(self.sine(f, n)) for f in freqs).astype(np.float32)
        return self.fade((self.hp(h, 6500)*np.exp(-t.astype(np.float32)*25)/len(freqs)).astype(np.float32), fi=4, fo=512)

    # ── melodic synthesizers ──────────────────────────────────────────────────

    def acid_note(self, freq, n, cutoff, resonance=9.0):
        """TB-303 acid with resonant LP filter."""
        body = self.saw(freq, n)
        c = float(np.clip(cutoff, 30, self.SR/2-100))
        sos = scipy.signal.butter(2, c/(self.SR/2), 'low', output='sos')
        filtered = scipy.signal.sosfiltfilt(sos, body).astype(np.float32)
        mid = np.clip(c*0.6, 20, self.SR/2-200)
        hi  = np.clip(c*1.4, mid+10, self.SR/2-100)
        if hi > mid+10:
            sosr = scipy.signal.butter(2, [mid/(self.SR/2), hi/(self.SR/2)], 'band', output='sos')
            filtered += scipy.signal.sosfiltfilt(sosr, body).astype(np.float32) * (resonance*0.04)
        return self.fade((filtered*self.env_n(n, 40, int(.06*self.SR), .65, int(.09*self.SR))).astype(np.float32), fi=32, fo=512)

    def pluck_note(self, freq, n, decay=None, warmth=0.3):
        """Pluck/piano note. decay=None → auto (faster for high notes).
        warmth=0 → bright saw, warmth=1 → sine-heavy (piano-like)."""
        t = self.t_arr(n)
        body = self.saw(freq, n) * (1-warmth) + self.sine(freq, n) * warmth + self.sine(freq*2, n) * 0.15
        d = decay if decay is not None else (4.0 + freq/300)
        env = np.exp(-t * d).astype(np.float32)
        lp_cut = np.clip(freq * (4 + warmth*4), 400, self.SR/2-100)
        return self.fade(self.lp(body*env, lp_cut), fi=16, fo=512)

    def sub_bass(self, freq, n):
        """Sub bass: sine + 2nd + 3rd harmonic."""
        body = self.sine(freq,n)*.82 + self.sine(freq*2,n)*.14 + self.sine(freq*3,n)*.04
        return self.hp(self.lp(body*self.env_n(n, 50, int(.08*self.SR), .74, int(.12*self.SR)), 200), 25).astype(np.float32)

    def supersaw(self, freq, n, detune=13, voices=7, lfo_rate=0.14, lfo_depth=0.06):
        """Detuned supersaw."""
        t = self.t_arr(n)
        lfo = lfo_depth * np.sin(2*np.pi*lfo_rate*t)
        out = np.zeros(n, np.float32)
        for v in range(voices):
            det = ((v - voices//2) / max(1, voices//2)) * detune
            f   = freq * 2**(det/1200) * (1 + lfo*0.4)
            ph  = 2*np.pi*np.cumsum(f)/self.SR
            out += np.sin(ph).astype(np.float32)
        return out / voices

    def pad_chord(self, freqs, n, lp_cut, voices=5, detune=13, lfo_rate=0.14):
        """Supersaw pad from list of chord frequencies."""
        out = np.zeros(n, np.float32)
        for f in freqs:
            out += self.supersaw(f, n, detune=detune, voices=voices, lfo_rate=lfo_rate)
        out /= len(freqs)
        return self.lp(out, lp_cut)

    def drone_voice(self, freq, n):
        """Detuned drone with subtle beating."""
        t = self.t_arr(n)
        lfo1 = 0.003*np.sin(2*np.pi*0.038*t)
        lfo2 = 0.003*np.sin(2*np.pi*0.051*t + 1.7)
        out = np.zeros(n, np.float32)
        for ratio, gain in [(1.0, 0.5), (2.0, 0.2), (3.0, 0.1)]:
            f1 = freq*ratio*(1+lfo1); f2 = freq*ratio*1.001*(1+lfo2)
            ph1 = 2*np.pi*np.cumsum(f1)/self.SR
            ph2 = 2*np.pi*np.cumsum(f2)/self.SR
            out += (np.sin(ph1)*0.5 + np.sin(ph2)*0.5).astype(np.float32) * gain
        return self.lp(out, 400)

    def noise_texture(self, n, lp_cut=2500, hp_cut=600):
        """Filtered noise with AM modulation."""
        nz = self.lp(self.hp(self.noise(n), hp_cut), lp_cut)
        t  = self.t_arr(n)
        am = 0.5 + 0.5*np.sin(2*np.pi*0.09*t+1.2)*np.sin(2*np.pi*0.21*t)
        return (nz * am.astype(np.float32)).astype(np.float32)

    # ── acoustic / jazz synths ───────────────────────────────────────────────

    def rhodes_note(self, freq, n, decay=1.8):
        """Fender Rhodes electric piano: sine + tine (2x) + bell attack (3x)."""
        t = self.t_arr(n)
        fundamental = self.sine(freq, n) * 0.55
        tine = self.sine(freq*2, n) * 0.25 * np.exp(-t*4).astype(np.float32)
        bell = self.sine(freq*3, n) * 0.15 * np.exp(-t*14).astype(np.float32)
        body = fundamental + tine + bell
        env  = np.exp(-t * decay).astype(np.float32)
        return self.fade(self.lp(body*env, np.clip(freq*6, 400, 4000)), fi=16, fo=512)

    def rhodes_chord(self, freqs, n, decay=1.8):
        """Chord of Rhodes notes."""
        out = np.zeros(n, np.float32)
        for f in freqs:
            out += self.rhodes_note(f, n, decay)
        return out / len(freqs)

    def muted_trumpet(self, freq, n, vibrato_rate=5.0, vibrato_depth=0.004):
        """Muted trumpet / jazz flute: warm harmonics + vibrato + bandpass."""
        t = self.t_arr(n)
        vib = vibrato_depth * np.sin(2*np.pi*vibrato_rate*t)
        # delayed vibrato (starts after 80ms)
        vib *= np.clip((t - 0.08) * 12, 0, 1)
        f_mod = freq * (1 + vib)
        ph = 2*np.pi*np.cumsum(f_mod)/self.SR
        body = (np.sin(ph)*0.55 + np.sin(ph*2)*0.22 +
                np.sin(ph*3)*0.12 + np.sin(ph*4)*0.06 +
                np.sin(ph*5)*0.03).astype(np.float32)
        body = self.bp(body, max(freq*0.7, 80), min(freq*5, 3800))
        env = self.env_n(n, int(0.04*self.SR), int(0.08*self.SR), 0.72, int(0.12*self.SR))
        return self.fade(body * env, fi=32, fo=512)

    def upright_bass(self, freq, n):
        """Acoustic upright bass: plucky attack + warm harmonics."""
        t = self.t_arr(n)
        body = (self.sine(freq, n) * 0.45 +
                self.sine(freq*2, n) * 0.22 +
                self.sine(freq*3, n) * 0.14 +
                self.sine(freq*4, n) * 0.07 +
                self.noise(n) * 0.04 * np.exp(-t*35).astype(np.float32))
        env = self.env_n(n, 20, int(0.06*self.SR), 0.45, int(0.18*self.SR))
        return self.hp(self.lp(body * env, 900), 28).astype(np.float32)

    def vinyl_crackle(self, n, density=0.0008, click_amp=0.025, noise_level=0.006):
        """Vinyl crackle: sparse random clicks + warm hiss."""
        clicks = np.zeros(n, np.float32)
        n_clicks = max(1, int(n * density))
        positions = np.random.randint(0, max(1, n-8), n_clicks)
        for pos in positions:
            amp = np.random.exponential(click_amp)
            sign = 1 if np.random.random() > 0.5 else -1
            clicks[pos] = amp * sign
            if pos+1 < n: clicks[pos+1] = amp * 0.3 * sign
        nz = self.noise(n) * noise_level
        nz = self.bp(nz, 250, 4500)
        return (clicks + nz).astype(np.float32)

    def mk_brush_snare(self, cfg=None):
        """Jazz brush on snare: soft swish, no attack."""
        n = int(0.16*self.SR); t = self.t_arr(n)
        nz = self.noise(n) * np.exp(-t*12)
        body = self.bp(nz, 350, 5500) * self.env_n(n, 30, int(.05*self.SR), .06, int(.04*self.SR))
        return self.fade(body * 0.25, fi=8, fo=128)

    # ── stereo effects ────────────────────────────────────────────────────────

    def haas(self, mono, delay_ms):
        d = max(1, int(delay_ms*self.SR/1000))
        right = np.zeros_like(mono); right[d:] = mono[:-d]
        return np.stack([mono, right], axis=0).astype(np.float32)

    def ping_pong(self, mono, delay_s, fb=0.35, mix=0.32):
        d  = int(delay_s*self.SR); d2 = int(delay_s*self.SR*0.618)
        left = mono.copy(); right = mono.copy()
        for i in range(d,  len(mono)): right[i] += mono[i-d]*fb
        for i in range(d2, len(mono)): left[i]  += right[i-d2]*fb*0.72
        return np.stack([mono+right*mix, mono+left*mix], axis=0).astype(np.float32)

    def mono_stereo(self, mono, width=1.0):
        l = np.cos(np.pi/4)*np.sqrt(0.5+width*0.5)
        r = np.sin(np.pi/4)*np.sqrt(0.5+width*0.5)
        return np.stack([mono*l, mono*r]).astype(np.float32)

    def _add_stereo(self, out_L, out_R, st, pos=0, gain=1.0):
        """Add (2, M) stereo array into output buffers at pos."""
        l = min(st.shape[1], self.N-pos)
        if l > 0:
            out_L[pos:pos+l] += st[0, :l] * gain
            out_R[pos:pos+l] += st[1, :l] * gain

    # ── element renderers ─────────────────────────────────────────────────────

    def render_drone(self, elements, out_L, out_R):
        from pedalboard import Reverb
        cfg  = elements.get('drone', {});
        freq = cfg.get('freq', 36.71)
        LEVEL = self.get_auto('drone_level', 0.5)
        CHUNK = self.BAR * 32; overlap = int(.5*self.SR)
        for pos in range(0, self.N, CHUNK):
            n = min(CHUNK+overlap, self.N-pos)
            if n <= 0: break
            d   = self.drone_voice(freq, n)
            d  *= self.env_n(n, int(.3*self.SR), int(.2*self.SR), .92, int(.5*self.SR))
            lvl = LEVEL[pos:pos+len(d)]
            if len(lvl) < len(d): d = d[:len(lvl)]
            d_fx = self.apply_fx(d, [Reverb(0.95, 0.97, wet_level=0.88, dry_level=0.12)])
            d_mono = (d_fx[0] if d_fx.ndim>1 else d_fx) * lvl
            self._add_stereo(out_L, out_R, self.mono_stereo(d_mono, 0.05), pos)

    def render_texture(self, elements, out_L, out_R):
        from pedalboard import Reverb
        cfg    = elements.get('texture', {})
        lp_cut = cfg.get('lp_cut', 3000); hp_cut = cfg.get('hp_cut', 400)
        LEVEL  = self.get_auto('texture_level', 0.3)
        CHUNK  = self.BAR * 32
        for pos in range(0, self.N, CHUNK):
            n = min(CHUNK, self.N-pos)
            if n <= 0: break
            tx    = self.noise_texture(n, lp_cut=lp_cut, hp_cut=hp_cut)
            lvl   = LEVEL[pos:pos+n]
            tx_fx = self.apply_fx(tx, [Reverb(0.88, 0.90, wet_level=0.80, dry_level=0.20)])[0]
            self._add_stereo(out_L, out_R, self.mono_stereo(tx_fx*lvl, 0.8), pos)

    def render_pad(self, elements, out_L, out_R):
        cfg        = elements.get('pad', {})
        chords     = cfg.get('chords', [[73.42, 87.31, 110.0]])
        synth_type = cfg.get('synth_type', 'supersaw')   # 'supersaw' | 'rhodes'
        voices     = cfg.get('voices', 5)
        detune     = cfg.get('detune', 13)
        lfo_rate   = cfg.get('lfo_rate', 0.14)
        LEVEL  = self.get_auto('pad_level', 0.6)
        FILTER = self.get_auto('pad_filter', 1200.0)
        WIDTH  = self.get_auto('stereo_width', 8.0)
        overlap = int(0.25*self.SR)
        for pos in range(0, self.N, self.BAR):
            n = min(self.BAR+overlap, self.N-pos)
            if n <= 0: break
            ci  = (pos // self.BAR) % len(chords)
            if synth_type == 'rhodes':
                pad = self.rhodes_chord(chords[ci], n, decay=cfg.get('decay', 1.8))
                pad = self.lp(pad, float(FILTER[pos]))
            else:
                pad = self.pad_chord(chords[ci], n, float(FILTER[pos]),
                                     voices=voices, detune=detune, lfo_rate=lfo_rate)
            pad *= self.env_n(n, int(.15*self.SR), int(.08*self.SR), .85, int(.25*self.SR))
            self._add_stereo(out_L, out_R, self.haas(pad, float(WIDTH[pos])), pos,
                             gain=float(LEVEL[pos])*0.48)

    def render_acid(self, elements, out_L, out_R):
        from pedalboard import Compressor, Delay
        cfg      = elements.get('acid', {})
        patterns = cfg.get('patterns', [])
        if not patterns: return
        ACID_CUT = self.get_auto('acid_cut', 1200.0)
        dur      = int(self.SIXTEENTH * 0.88)
        n_bars   = self.N // self.BAR
        for pi, pat_cfg in enumerate(patterns):
            freqs     = pat_cfg['freqs']
            amp_auto  = self.get_auto(pat_cfg.get('amp_auto', 'acid_amp'), 1.0)
            cut_scale = pat_cfg.get('cut_scale', 1.0)
            gain_out  = pat_cfg.get('gain', 0.55)
            buf = np.zeros(self.N, np.float32)
            for bar in range(n_bars):
                for i, freq in enumerate(freqs):
                    pos = bar*self.BAR + i*self.SIXTEENTH
                    if pos+dur > self.N: break
                    amp = float(amp_auto[pos])
                    if amp < 0.01: continue
                    note = self.acid_note(freq, dur, float(ACID_CUT[pos])*cut_scale)
                    self.stamp(buf, note, pos, gain=amp)
            d_s   = self.EIGHTH/self.SR * (0.618 if pi>0 else 1.0)
            pp    = self.ping_pong(buf, d_s, fb=0.32, mix=0.28)
            if pi > 0: pp = np.stack([pp[1], pp[0]], axis=0)  # flip L/R
            fx = self.apply_fx(pp, [
                Compressor(-11, 3.5, 5, 90),
                Delay(delay_seconds=self.SIXTEENTH/self.SR, feedback=0.18, mix=0.16),
            ])
            self._add_stereo(out_L, out_R, fx, gain=gain_out)

    def render_lead(self, elements, out_L, out_R):
        """Lead melody: pluck, trumpet, or flute. Supports multi-bar patterns."""
        from pedalboard import Reverb, Delay, Compressor
        cfg      = elements.get('lead', {})
        patterns = cfg.get('patterns', [])
        if not patterns: return
        LEAD_AMP = self.get_auto('lead_amp', 1.0)
        dur      = int(self.EIGHTH * 0.92)
        n_bars   = self.N // self.BAR
        for pi, pat_cfg in enumerate(patterns):
            freqs      = pat_cfg['freqs']
            step       = pat_cfg.get('step', 'eighth')
            step_n     = self.EIGHTH if step == 'eighth' else self.SIXTEENTH
            gain_out   = pat_cfg.get('gain', 0.50)
            warmth     = pat_cfg.get('warmth', 0.3)
            note_decay = pat_cfg.get('decay', None)
            synth_type = pat_cfg.get('synth_type', 'pluck')   # 'pluck' | 'trumpet'
            # Multi-bar pattern support: place notes sequentially, cycle pattern
            steps_per_bar = max(1, self.BAR // step_n)
            pattern_bars  = max(1, len(freqs) // steps_per_bar)
            buf = np.zeros(self.N, np.float32)
            for bar in range(n_bars):
                cycle_bar = bar % pattern_bars
                for local_i in range(steps_per_bar):
                    i = cycle_bar * steps_per_bar + local_i
                    if i >= len(freqs): break
                    freq = freqs[i]
                    pos  = bar * self.BAR + local_i * step_n
                    if pos + dur > self.N: break
                    amp = float(LEAD_AMP[pos])
                    if amp < 0.01 or freq < 1: continue
                    if synth_type == 'trumpet':
                        note = self.muted_trumpet(freq, dur)
                    else:
                        note = self.pluck_note(freq, dur, decay=note_decay, warmth=warmth)
                    self.stamp(buf, note, pos, gain=amp)
            # FX chain
            if synth_type == 'trumpet':
                buf_fx = self.apply_fx(buf, [
                    Reverb(0.75, 0.80, wet_level=0.42, dry_level=0.58),
                    Delay(delay_seconds=self.EIGHTH/self.SR, feedback=0.15, mix=0.12),
                    Compressor(-8, 3, 5, 80),
                ])
            else:
                buf_fx = self.apply_fx(buf, [
                    Reverb(0.65, 0.70, wet_level=0.35, dry_level=0.65),
                    Delay(delay_seconds=self.EIGHTH/self.SR, feedback=0.25, mix=0.20),
                    Compressor(-10, 3, 5, 80),
                ])
            pp = self.ping_pong(buf_fx[0], self.EIGHTH/self.SR*1.5, fb=0.28, mix=0.25)
            self._add_stereo(out_L, out_R, pp, gain=gain_out)

    def render_bass(self, elements, out_L, out_R):
        from pedalboard import Compressor
        cfg        = elements.get('bass', {})
        roots      = cfg.get('roots', [36.71])
        synth_type = cfg.get('synth_type', 'sub')  # 'sub' | 'upright'
        BASS_AMP   = self.get_auto('bass_amp', self.get_auto('kick_amp', 1.0))
        buf        = np.zeros(self.N, np.float32)
        n_bars     = self.N // self.BAR
        bass_fn    = self.upright_bass if synth_type == 'upright' else self.sub_bass
        for bar in range(n_bars):
            root = roots[bar % len(roots)]
            self.stamp(buf, bass_fn(root, self.BAR),      bar*self.BAR)
            self.stamp(buf, bass_fn(root*1.5, self.SPB),  bar*self.BAR + self.SPB*2)
        buf *= np.clip(BASS_AMP*1.4, 0, 1)
        bass_fx = self.apply_fx(buf, [Compressor(-8, 4, 5, 100)])[0]
        self._add_stereo(out_L, out_R, self.mono_stereo(bass_fx, 0.04), gain=0.60)

    def render_drums(self, elements, out_L, out_R):
        from pedalboard import Reverb, Compressor, Gain
        cfg = elements.get('drums', {})
        K   = self.mk_kick(cfg.get('kick'))
        S   = self.mk_snare(cfg.get('snare'))
        CL  = self.mk_clap(cfg.get('clap'))
        HC  = self.mk_hat_c(cfg.get('hat'))
        HO  = self.mk_hat_o(cfg.get('hat'))
        KICK_AMP  = self.get_auto('kick_amp', 1.0)
        SNARE_AMP = self.get_auto('snare_amp', 1.0)
        HAT_AMP   = self.get_auto('hat_amp', 1.0)
        REV_WET   = self.get_auto('rev_wet', 0.3)
        pat         = cfg.get('pattern', {})
        kick_beats  = pat.get('kick', [0, 2])
        snare_beats = pat.get('snare', [1, 3])
        snare_type  = pat.get('snare_type', 'snare')
        hat_mode    = pat.get('hat', 'every16')
        # Humanization params
        swing     = cfg.get('swing', 0.0)          # 0.0=off, 0.5=triplet, 0.6=heavy
        jitter_ms = cfg.get('jitter_ms', 0.0)      # timing randomness in ms
        vel_var   = cfg.get('velocity_variation', 0.0)  # 0.0=off, 0.15=natural
        BR = self.mk_brush_snare(cfg.get('brush'))
        S_HIT = BR if snare_type == 'brush' else (CL if snare_type == 'clap' else S)
        drum_buf = np.zeros(self.N, np.float32)
        n_bars   = self.N // self.BAR
        s16_idx  = 0  # global 16th-note counter for swing
        for bar in range(n_bars):
            for beat in range(4):
                pb = bar*self.BAR + beat*self.SPB
                if pb >= self.N: break
                hat_a = float(HAT_AMP[pb])
                if hat_a > 0.005:
                    if hat_mode == 'every16':
                        for s16 in range(4):
                            p = pb + s16*self.SIXTEENTH
                            p += self.swing_offset(s16_idx + s16, self.SIXTEENTH, swing)
                            p = self.humanize_pos(p, jitter_ms)
                            g = self.humanize_vel(0.52*hat_a, vel_var)
                            self.stamp(drum_buf, HC*g, p)
                        p = self.humanize_pos(pb+self.EIGHTH, jitter_ms*0.5)
                        self.stamp(drum_buf, HO*self.humanize_vel(0.46*hat_a, vel_var), p)
                        s16_idx += 4
                    elif hat_mode == 'every8':
                        p = self.humanize_pos(pb, jitter_ms)
                        self.stamp(drum_buf, HC*self.humanize_vel(0.52*hat_a, vel_var), p)
                        p = self.humanize_pos(pb+self.EIGHTH, jitter_ms*0.5)
                        self.stamp(drum_buf, HO*self.humanize_vel(0.40*hat_a, vel_var), p)
                if beat in kick_beats:
                    k_a = float(KICK_AMP[pb])
                    if k_a > 0.005:
                        p = self.humanize_pos(pb, jitter_ms * 0.3)  # kick tightest
                        self.stamp(drum_buf, K*self.humanize_vel(k_a, vel_var*0.5), p)
                if beat in snare_beats:
                    s_a = float(SNARE_AMP[pb])
                    if s_a > 0.005:
                        p = self.humanize_pos(pb, jitter_ms)
                        self.stamp(drum_buf, S_HIT*self.humanize_vel(0.88*s_a, vel_var), p)
        # Chunked reverb (automated wet)
        processed = np.zeros(self.N, np.float32)
        chunk = self.BAR*4
        for pos in range(0, self.N, chunk):
            n = min(chunk, self.N-pos)
            if n <= 0: break
            wet = float(REV_WET[pos])
            fx  = self.apply_fx(drum_buf[pos:pos+n], [
                Compressor(-10, 4, 3, 70), Gain(2.0),
                Reverb(0.55, 0.65, wet_level=wet*0.5, dry_level=1.0-wet*0.6),
            ])[0]
            processed[pos:pos+n] += fx[:n]
        self._add_stereo(out_L, out_R, self.haas(processed, 4.0), gain=0.62)

    def render_vinyl(self, elements, out_L, out_R):
        """Vinyl crackle layer (full track)."""
        cfg     = elements.get('vinyl', {})
        density = cfg.get('density', 0.0008)
        LEVEL   = self.get_auto('vinyl_level', 0.4)
        CHUNK   = self.BAR * 32
        for pos in range(0, self.N, CHUNK):
            n = min(CHUNK, self.N-pos)
            if n <= 0: break
            vc  = self.vinyl_crackle(n, density=density)
            lvl = LEVEL[pos:pos+n]
            self._add_stereo(out_L, out_R, self.mono_stereo(vc*lvl, 0.3), pos)

    # ── master & export ───────────────────────────────────────────────────────

    def render(self):
        from pedalboard import Compressor, Gain, HighpassFilter
        title = self.style['meta'].get('title', 'Track')
        print(f"{title} | BPM={self.BPM} | {self.TOTAL_S}s | N={self.N:,}")
        out_L = np.zeros(self.N, np.float32)
        out_R = np.zeros(self.N, np.float32)
        elements = self.style.get('elements', {})
        # Render order matters for CPU/memory; keep light elements first
        for elem in ['vinyl', 'drone', 'texture', 'pad', 'lead', 'acid', 'bass', 'drums']:
            if elem not in elements: continue
            if not elements[elem].get('active', True): continue
            print(f"  {elem}...")
            getattr(self, f'render_{elem}')(elements, out_L, out_R)
        print("  master...")
        stereo = np.stack([out_L, out_R], axis=0)
        stereo = self.apply_fx(stereo, [HighpassFilter(cutoff_frequency_hz=22)])
        stereo = self.apply_fx(stereo, [Compressor(-5, 2.8, 3, 120), Gain(2.0)])
        stereo = np.tanh(stereo * 0.80) / 0.80
        peak = np.abs(stereo).max()
        if peak > 0: stereo *= (10**(-0.5/20)) / peak
        print("  encoding 320kbps MP3...")
        out_dir = os.path.dirname(self.OUT)
        if out_dir: os.makedirs(out_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        sf.write(tmp, stereo.T, self.SR, subtype="PCM_24")
        os.system(f'ffmpeg -y -i "{tmp}" -b:a 320k -q:a 0 "{self.OUT}" 2>/dev/null')
        os.unlink(tmp)
        size = os.path.getsize(self.OUT)/1024/1024
        print(f"\nDone: {self.OUT} ({size:.1f} MB)")
        return self.OUT


def load_style(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
