---
name: CHIMERA vocal synth
description: 2026-11-18 installed at Стас request: physical-model singing voice, CLI path, how to feed notes + RU/EN syllables
type: reference
---
CHIMERA (github jamesondh/chimera-vocal-synth, MIT) installed 2026-11-18 at Стас request: Rust via rustup in ~/.rustup (600 MB) + ~/.cargo; binary ~/tools/chimera_20261118/target/release/chimera (cargo build --release -p chimera-cli, ~1 min).
- `chimera syllables "<lyrics>"` -> JSON syllables (EN via CMUdict, RU Cyrillic with acute stress marks `мо́ст`, Korean). No Ukrainian front end.
- `chimera render notes vox.json <out> male`: {"bpm","t0":0.3,"vibrato","notes":[[midi,beats],[0,rest]],"syllables":[...]}; one vowel = one note; 74 notes ~22 s CPU, 48 kHz mono. Strip t0 pre-roll when placing.
- Example: workspace/music/bridge_th_2026_11_18/vox.py + score.py (tech house «Bridge to Nowhere»).
**Rules:** pseudo-singing and Russian stay banned by default; this is an exception only when Стас asks for CHIMERA/VocalTractLab singing.
