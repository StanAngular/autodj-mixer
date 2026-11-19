---
name: Recreation sound gap (Detuned Dreams)
description: 2026-10-26 Стас «95% не похоже, звуки не тянутся и не искажаются»: stem-by-stem numbers ref vs ours, what to change
type: feedback
---
Detuned Dreams v1 (workspace/music/detuned/, compare in detuned/cmp/cmp.py + gemini_cmp.md). Demucs stems ORIG vs OURS:
drums kick -22 vs -18 dB, kick decay 189 vs 293 ms, onsets 8.5/s vs 3.8 (orig = many quiet short noisy hits = «жидкие слабые»);
bass -19 vs -14 dB, orig brighter (centroid 204 vs 128 Hz = harmonics), fewer re-attacks; other (pads/pulses) orig sustained tonal
(voiced .61 vs .29), darker 1830 vs 2437 Hz, more pitch drift; vocals orig 9 dB quieter, SUNG (voiced .65 vs .31), 94 % in 200-2k, wide .7 vs .25.
**Why:** I played short W.A. one-shots + my usual kit (Стас: «паттерны из прошлых треков»), TTS speech instead of sung lines.
**How to apply:** for a recreation measure stems first and match: sustained/stretched pads with wow-flutter, quiet short drums, vocal sung + band-limited + wide + far back; never default to my W.A. kit. Gemini called our male voice «female» = still unreliable on details.

**2026-10-26 Detuned Dreams II (workspace/music/detuned2/, sent):** rebuilt from scratch with the lessons, stems now close to the ref:
other sustain .97/.96, wobble 4.0/4.6 c, voice level -28.8/-28.9 dB, voice wobble 8.6/10.2, drums 10.8 vs 8.5 onsets/s, kick 160 vs 189 ms.
Recipe that worked (reuse): soft synth kick (41 Hz + 55 Hz drop, 75 ms exp, LPF 900) on steps 0/4/12 (+8 alt bars); 808 sd -3 st + rim on beat 3
band 350-3.2k + room; noise ticks 16ths instead of hats; reese = sine + 2 saws ±8 c, Ladder LPF24 380 + Distortion 5, drift .8 Hz 12 c + .23 Hz 8 c;
pads = W.A. Pd_01 time-stretched x0.36 (cached), held 2 bars, wow() delay-line .8 Hz 14 c + .21 Hz 20 c, sat 4, chorus, hall; voice = edge-tts ->
pyworld (sing.py: voiced runs = syllables, melody f0, stretched vowels, +aperiodicity = airy) + static +9 c/16 ms double, band 220-4.2k, far back -7 dB.
Still off: drums darker/quieter (centroid 1850 vs 3140, ticks -6 dB), bass +2 dB and darker, pads narrower (.47 vs .71).

**2026-10-28 Detuned Dreams III (workspace/music/detuned3/, fragment 40 bars sent):** Стас «II: до 28 с все инструменты звучат неверно» +
his Gemini TZ (witch house): no stretched samples, no pure sines, no W.A. bright kits. Rebuilt with detuned3/analog.py: polyBLEP detuned saw
stacks (+-12-14 c) + square, per-osc drift 8-12 c + random 9 Hz flutter, Juno chorus (static width), tube/tape asym. sat, bass filter-env «quack»,
soft 58 Hz kick, snare + dark long tail, ticks/shaker +5 dB, rolls in dark delay, synthetic dark IR (Convolution) on the melodic group.
Trap: spiky layers (snare/voice/rolls, crest 24-36 dB) made the limiter eat 12 dB -> fx.tame every non-kick layer. Bass enters bar 10 (=0:18 like ref).
**2026-10-28 III fragment v2 (Стас: «хрип, щелчки, песок; качество и мягкость главное»):** drive -55..-60 % everywhere (bass tape 1.1, pads .8,
plucks 1.0, voice .7, kick sat 1.2), double LPF 4.8 kHz on pads AFTER the saturation, kick 52 Hz slow (9 ms attack, 120 ms decay, LPF 240),
bass sub at the NOTE pitch (A.stack sub_ratio=1.0: the old f0/2 sub sat at 17-29 Hz = useless rumble), noise rolls removed, ticks/shaker -10/-6 dB
with 3 ms attack. A real click was IN detuned2/vox/v1_sung.wav (pyworld) -> declick() on all sung lines. Measure: 45-90 Hz share .37 (ref .32).
**2026-10-28 III full (dd3_full, sent):** Стас on fragment v2: «хрип на 0:41, примитивный быстрый ритм, хлопки примитивные, ещё мягче».
Cause of хрип = bass +1 dB over kick ref = loudest layer before the kick enters -> peak >0 dBFS -> limiter. Fix: bass -5, master warm -13 LUFS-ish,
low-ratio bus comp; 808 snare/16th noise ticks banned for this style -> MC303 brush tap in dark hall + brush swish on a 7-step cycle.
Стас's sound TZ (uploads/1793144811463_pasted-text--2-.txt) + SOS/Attack/Vector-DSP ambient articles = the rulebook; check side ratio 20-150 < .01, true peak, clicks every render.
**2026-10-28 «Тінь» (wh_uk/, sent) after Стас: «перегрузка на голосе»:** in dd3 the voice layer sat only 4 dB under the mix rms with peak -2.3 dB, so the
pre-master sum went over 0 dBFS and the limiter squashed it. New rule in wh_uk/score.py: no saturation on the voice, set its gain FROM THE MIX (-10 dB
under mix rms), fx.tame 9, scale the sum to peak <= 0.7 before the master. Ukrainian sung lines: edge-tts uk-UA-PolinaNeural rate -25 % -> detuned2/sing.py
(pyworld), notes F minor; stray pyin low notes were <2.5 % energy = ignore. tzcheck.py (workspace/music/) = true peak, LUFS, side ratio, mono-fold, clicks.
**2026-10-28 «AI essence» x5 (ai5/, sent):** wide stereo WITHOUT motion = M/S side boost above 350-400 Hz, allpass decorrelation, Haas, L/R split of detuned copies,
fixed binaural positions (ILD+ITD+shadow); check L/R balance std per 1 s (< 1 dB) and S/M > 400 Hz (0.7-1.0). Traps: a stretched W.A. one-shot can be shorter than the chord
(Synth_02 stretched = 1 s) -> loudness holes: measure the sounding length vs 2 bars; relative click detector false-alarms on very dark mixes (check absolute HF jump, < -35 dBFS is fine);
polymetric nodes at +-0.8 swing L/R 9 dB = «мерцание» again, keep +-0.45.
**2026-10-28 AI-essence x5 (workspace/music/ai5/, sent):** Стас «5 вариантов, электронная сущность ИИ, расширенное стерео, ambient downtempo, семплы WA».
Framework ai5.py + variants.py (cfg per variant: key, bpm, prog, kit, pad, hook type poly_pluck/arp/bass_lead/pulse_pad/cloud, width method).
STATIC width only (Стас banned L/R motion): ms_widen above 400 Hz, allpass decorr, Haas, L/R split of detuned copies, fixed binaural positions (ILD+ITD+shadow).
Traps found: (1) one-shot pads stretched x0.4 can be SHORTER than 2 bars (Synth_02 = 1 s) -> loudness holes: always check stretched length vs chord length;
(2) node positions +-0.8 gave 9 dB L/R balance swings = feels like flicker -> keep +-0.45; (3) click detector (99.9 pct x3) false-alarms on very dark mixes:
check absolute HF jump too; (4) first versions >4k share .0001-.0006 = too muffled, opened LPFs (pad 7k, group 9k). Tools: workspace/music/widecheck.py, tzcheck.py.
**2026-10-28 «странное звучание, давай техно космическое» (after the 5 AI-ambient tracks):** answered with space3/ (3 space-techno sketches on the liked Космос recipe, static wide stereo). If he calls a sound «странное» next time, go back to the three liked tracks (Космос v1, Гипнотический рифф, Shimmer in the Deep) instead of inventing a new concept.
**2026-10-31 weekly A/B full versions + voice:** Стас liked weekly sketch A (Clay Path, sung coo voice = progress) and B (Dust Relay: hang transitions, phone-beep hook, wants a modem sound) -> full 5-7 min versions (workspace/music/full_2026_10_31/, full_a.py, full_b.py). B voice version: male Ukrainian phone voice (Ало / не чую / передзвоніть / ви не туди потрапили), v2 = rougher lower, nervous, freeze-on-a-letter + micro-pauses (phonevox.py). C: «инструменты старые, примитивные».
Audition votes 31.10: pad @0:17 (musicradar Drone 10) good, rest bad; ALL plucks/harps bad («дверной звонок»); only W.A. Bass_Shot_7 good -> in timbre_verdicts.json. Side effect: new timbre_guard refuses sounds NEAR a rejected one (Bass_Shot_9, Pluck_07, Karoryfer bass) -> after the audition add GOOD verdicts for the sounds he liked in sketches (the guard needs both sides).
Turn length: (Updated 2026-11-02, previously a hard 30 min kill) P123 applied 2026-11-02: idle timer 20 min without events, 3 h total cap. Still render in background and poll in short calls.

**2026-10-31/11-01 follow-ups (from session):** Haunted House (acid breakbeat, 132 BPM Em + F ghost note, sung «coo» ghosts like Clay Path but darker/more energetic) was sent 10-31. The «задача выполняется более 30 минут» kill hit a healthy long Dust Relay turn: fix = idle timer 20 min + 3 h cap, applied 2026-11-02. After the 11-01 usage limit the queue was: apply pending updates (done 2026-11-02), 5 different 1-min Haunted House variants (sharper/faster and smoother), full 5-6 min version of «Riff Under Glass (tech house)».

2026-11-18 reel DeUZ: recreation rule — keep the first analysis (grid, pitches, plan) as the BASE; spectrograms/new facts only correct it with SMALL deltas, never restart (v2 dropped the grid-matched v1 and Стас: "вообще не похоже"). Also: compare spectrograms by viewing the PNG (Read) early, and use the real instruments he names (upright double bass dbass, tuba).

2026-11-18 Стас: for RECREATIONS synthesis/generated sounds are allowed (only «repeat the original» matters); the samples-only rule is for new tracks. His note on reel DeUZ: v1 was closer, especially at the start.

Stas 2026-11-18: do NOT use spectrograms (or spectral EQ matching) for recreations; ask Gemini (several runs, blind) what instruments/style/vibe, trust only overlaps between runs; also compare ref vs attempt with Gemini (2 runs) and apply fixes both runs agree on. Keep own timing/pitch plan as the base. Gemini genre guesses were wildly inconsistent (eurodance/hyperpop/jungle/bass house) for the same clip.
