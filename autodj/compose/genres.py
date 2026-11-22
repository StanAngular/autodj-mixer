"""P169 + P170 + P174 + P175 (2026-11-21, audit 4: «Berlin Pulse» was «лайт-афро lo-fi, не tech house»). A GENRE CARD says what a genre is made of: tempo,
the layers it needs, the folders its sounds come from, the families it must NOT use, the CLAP description per role, the rhythm profile, the harmony mode,
the bass type, the FX moments and the mix targets. Freshness chooses only INSIDE the card's palette (the old way let it pick the rarest drum machines).

  card(name)                      the card (copy); "tech house" / "tech_house" / "berlin tech house" -> tech_house
  candidates(card, role, k=12, near=None, **kw)   CLAP candidates for the role inside the card's folders, the card's deny words and drumq / verdicts applied
  pick(card, role, rng, title, near=None, k=None) the least used of those (fresh.pick); ValueError when the palette has nothing for the role
  fx_plan(sections, card)         [(bar, kind)]: riser into a drop, downlifter after it, impact on the drop's downbeat, vocal chop at phrase ends (sparse)
  similarity(mp3, labels)         CLAP: the mix (3 clips) against text labels of genres -> {label: cosine}; a REPORT, never a gate
The card values come from the audit's research (Wikipedia, MusicRadar, Native Instruments, LANDR; references sven_v_th_face_it / mike_morrisey for the
mix targets) and are hypotheses until Стас has heard them."""
import copy, os, re
import numpy as np

S = (os.environ.get("AUTODJ_SAMPLES") or "/home/cclaw/samples").rstrip("/") + "/"              # the library lives in /home/cclaw/samples for EVERY user (Hermes sees it through a symlink)
ALT_ROOTS = ("/home/hermes/samples/", os.path.expanduser("~/samples/"))
def _norm(p):
    p = str(p)
    for a in ALT_ROOTS:
        if p.startswith(a) and a != S: return S + p[len(a):]
    return p
WA, WA2, T909, T808 = S + "wa_techno/WAV MIDI Presets/", S + "wa2/WAV MIDI Loops/", S + "tidal-drum-machines/machines/RolandTR909/", S + "tidal-drum-machines/machines/RolandTR808/"
AFRO_LOFI = r"conga|bongo|cabasa|clave|maraca|guiro|agogo|djembe|tumba|shekere|marimba|kalimba|vibra|xylo|bell|glock|chime|rhodes|piano|pianet|wurl|cp80|e-piano|epiano|harp|flute|sitar|steel|tabla|udu|cajon|kora|acoustic|upright|dbass|tuba|sax"
CARDS = {
    "tech_house": dict(
        bpm=(124, 130), default_bpm=128, rhythm="tech_house", mood="club", harmony="stab", bass="rolling_riff",
        layers=("kick", "hats", "ohat", "shaker", "clap", "rim", "bass", "stab", "fx"),
        dirs={"kick": [WA + "Kicks", WA2 + "Percussion", T909 + "rolandtr909-bd", T808], "hats": [WA + "Cymbals", WA2 + "Percussion", T909 + "rolandtr909-hh"],
              "ohat": [WA + "Cymbals", WA2 + "Percussion", T909 + "rolandtr909-oh"], "clap": [WA + "Claps", WA2 + "Percussion", T909 + "rolandtr909-cp"],
              "rim": [T909 + "rolandtr909-rim", WA + "Percussion", WA2 + "Percussion"], "shaker": [S + "tidal-drum-machines/machines/", WA + "Percussion", WA2 + "Percussion"],
              "perc": [WA + "Percussion", WA2 + "Percussion"], "bass": [WA + "Synth & Bass Shots"], "stab": [WA + "Synth Shot", WA2 + "Synth Shots", WA + "Synth & Bass Shots"],
              "fx": [WA + "Effects", WA + "FX", WA2 + "FX"], "vox": [WA + "FX"]},
        deny=AFRO_LOFI,
        query={"kick": "short tight punchy tech house kick drum, dense thump, slightly saturated", "hats": "crisp closed 909 hi-hat, short", "ohat": "short open 909 hi-hat",
               "shaker": "short shaker, steady sixteenth", "clap": "tech house clap, dry and wide", "rim": "909 rimshot, short click", "perc": "short machine percussion hit, techy",
               "bass": "deep humming synth bass note, short", "stab": "dark dub chord stab or organ stab, short", "fx": "riser sweep or downlifter effect", "vox": "short vocal chop shout"},
        roles={"kick": "kick", "hats": "hats", "ohat": "hats", "shaker": "shaker", "clap": "clap", "rim": "rim", "perc": "perc", "bass": "bass", "stab": None, "fx": None, "vox": None},
        mix={"hats_vs_kick_db": (-21, -12), "bass_vs_kick_db": (-2.0, 6.0), "perc_vs_kick_db": (-13, -11), "clap_vs_kick_db": (-12, -8), "stab_vs_kick_db": (-9, -6), "vocal_vs_kick_db": (-9, -3),
             "bass_duck_db": (-17, -13), "bass_note_s": (.12, .23), "bass_midi": (25, 33), "hat_odd_shift_16th": (.12, .28)},      # measured on NO STATIC and DANGER (Стас's references, 130 BPM)
        fx={"riser": "Uplifter", "downlifter": "Downlifter", "impact": "Kick_Boom", "sweep": "Sweep", "vox": "Vox_Crazy"},
        need={"ohat": r"open|^oh|_oh", "shaker": r"shak|^sh|_sh|shk"},                      # the file name must say it (CLAP alone called a cabasa an open hat)
        name_deny={"hats": r"open|^oh|_oh|crash|ride|cymbal_crash", "shaker": r"tamb|vib|guir"},
        refs=("sven_v_th_face_it", "mike_morrisey_ollie_bc_d"), labels=("tech house", "afro house", "deep house", "lo-fi hip hop", "techno")),
}
# ---- the other genres (Стас 2026-11-22: «ты сделал под tech house отдельные жёсткие правила, а что с другими стилями») ----------------------------------
KITS = [WA + "Kicks", WA + "Claps", WA + "Cymbals", WA + "Percussion", WA2 + "Percussion", T909, T808, S + "tidal-drum-machines/machines/RolandTR707", S + "musicradar/house", S + "musicradar/drums"]
ROLE_Q = {"bass": "deep humming synth bass note, short", "stab": "chord stab, short", "fx": "riser sweep or downlifter effect", "vox": "short vocal chop", "kick": "kick drum", "hats": "closed hi-hat, short", "ohat": "open hi-hat", "shaker": "shaker", "clap": "clap", "rim": "rimshot", "perc": "percussion hit", "snare": "snare drum"}
ROLE_R = {"kick": "kick", "hats": "hats", "ohat": "hats", "shaker": "shaker", "clap": "clap", "rim": "rim", "perc": "perc", "snare": "snare", "bass": "bass", "stab": None, "fx": None, "vox": None}
def _card(bpm, default, rhythm, mood, harmony, bass, deny, queries=None, dirs=None, keys=(), basses=(), labels=(), master=None, extra_need=None, name_deny=None):
    c = dict(bpm=bpm, default_bpm=default, rhythm=rhythm, mood=mood, harmony=harmony, bass=bass, layers=("kick", "hats", "clap", "perc", "bass"),
             dirs={r: list(KITS) for r in ("kick", "hats", "ohat", "shaker", "clap", "rim", "perc", "snare")}, deny=deny, query={**ROLE_Q, **(queries or {})}, roles=dict(ROLE_R),
             need={"ohat": r"open|^oh|_oh", "shaker": r"shak|^sh|_sh|shk", **(extra_need or {})}, name_deny={"hats": r"open|^oh|_oh|crash|ride", "shaker": r"tamb|vib|guir", **(name_deny or {})},
             instruments={"keys": list(keys), "bass": list(basses)}, mix={}, fx={"riser": "Uplifter", "downlifter": "Downlifter", "impact": "Kick_Boom", "sweep": "Sweep"}, refs=(), labels=labels,
             master=master or {"target": -14.0, "master": "warm", "premaster": "sat"})
    c["dirs"]["bass"] = [WA + "Synth & Bass Shots"]; c["dirs"]["stab"] = [WA + "Synth Shot", WA2 + "Synth Shots"]; c["dirs"]["fx"] = [WA + "Effects", WA + "FX", WA2 + "FX"]; return c
HARSH = r"conga|bongo|cabasa|clave|maraca|guiro|agogo|djembe|tabla|sitar|shekere|udu|kora"
CARDS.update({
    "house": _card((120, 126), 124, "house", "club", "chords", "groove", HARSH + r"|trap|dist", keys=("rhodes", "wurlitzer", "cp80", "pianet"), basses=("bass", "bass_pluck", "fashionbass"), labels=("house", "tech house", "deep house", "afro house")),
    "deep": _card((118, 124), 122, "deep", "soft", "jazz-ish chords", "round sub", HARSH + r"|trap|hard|aggress|dist|industrial", keys=("rhodes", "wurlitzer", "cp80", "pianet", "piano"), basses=("bass", "bass_pluck", "dbass"), labels=("deep house", "house", "tech house", "lo-fi hip hop")),
    "melodic": _card((120, 126), 124, "melodic", "club", "chords+hook", "round sub", HARSH + r"|trap|hard|aggress|dist", keys=("rhodes", "wurlitzer", "cp80", "pianet", "piano"), basses=("bass", "bass_pluck", "fashionbass"), labels=("melodic house", "deep house", "tech house", "techno")),
    "afro_house": _card((118, 126), 122, "afro_house", "warm", "chords", "round sub", r"trap|hard|aggress|dist|industrial", queries={"perc": "conga, bongo, shaker or wooden percussion hit, organic", "kick": "round soft kick drum, warm"},
                        keys=("rhodes", "wurlitzer", "pianet", "piano"), basses=("bass", "bass_pluck", "dbass"), labels=("afro house", "deep house", "house", "tech house")),
    "garage": _card((128, 134), 130, "garage", "soft", "chords", "sub", HARSH + r"|aggress|dist|industrial", keys=("rhodes", "wurlitzer", "cp80", "pianet"), basses=("bass", "bass_pluck", "fashionbass"), labels=("uk garage", "house", "deep house", "drum and bass")),
    "minimal": _card((120, 128), 124, "minimal", "club", "stab", "short", r"piano|rhodes|pianet|wurl|cp80|bell|marimba|harp|flute|sax|pad|aggress", basses=("bass", "bass_pluck"), labels=("minimal techno", "tech house", "techno", "ambient")),
    "techno": _card((126, 140), 132, "techno", "hard", "stab", "rumble", r"conga|bongo|cabasa|clave|maraca|guiro|agogo|marimba|kalimba|rhodes|piano|pianet|wurl|cp80|harp|flute|sax|acoustic", basses=("bass",), labels=("techno", "tech house", "house", "ambient")),
    "downtempo": _card((70, 105), 90, "downtempo", "soft", "chords", "round sub", r"hard|aggress|dist|industrial|trap|crash", keys=("rhodes", "wurlitzer", "cp80", "pianet", "piano"), basses=("bass", "bass_pluck", "dbass", "fashionbass"), labels=("downtempo", "lo-fi hip hop", "trip hop", "ambient")),
    "breaks": _card((125, 140), 132, "breaks", "club", "chords", "reese-ish", r"conga|bongo|cabasa|clave|djembe|tabla|bell|marimba", keys=("rhodes", "wurlitzer", "cp80", "pianet"), basses=("bass", "growlybass", "fashionbass"), labels=("breakbeat", "drum and bass", "techno", "house")),
    "witch_house": _card((60, 80), 70, "witch_house", "soft", "dark chords", "sub", r"conga|bongo|cabasa|clave|bright|bell|marimba|kalimba|shaker", keys=("piano", "wurlitzer"), basses=("bass", "dbass"), labels=("witch house", "ambient", "trap", "downtempo")),
    "ambient": _card((60, 90), 72, "ambient", "ambient", "pads", "drone", r"kick|snare|hat|clap|conga|bongo|cabasa|clave|aggress|dist|industrial", queries={"perc": "soft bell or chime hit"}, keys=("rhodes", "wurlitzer", "piano", "pianet"), basses=("bass", "dbass_arco"), labels=("ambient", "downtempo", "lo-fi hip hop", "techno")),
})
for _n, _c in CARDS.items():
    _c.setdefault("master", {"target": -14.0, "master": "warm", "premaster": "sat"}); _c.setdefault("instruments", {"keys": [], "bass": []}); _c.setdefault("name_deny", {}); _c.setdefault("need", {})
CARDS["tech_house"]["master"] = {"target": -11.5, "master": "studio", "premaster": "clip", "premaster_knee": -11.0, "gates": {"limiter_max_db": 8.0}}     # loud on purpose (references NO STATIC / DANGER measure -8.1 / -7.1 LUFS, crest 9 dB, a commercial clipped master): -11.5 LUFS needs only 6-7 dB of limiting on a normal mix; -10 needs 12-13 dB
CARDS["tech_house"]["instruments"] = {"keys": [], "bass": []}
CARDS["techno"]["master"] = {"target": -11.5, "master": "studio", "premaster": "clip", "premaster_knee": -11.0, "gates": {"limiter_max_db": 8.0}}
ALIAS = {"tech house": "tech_house", "tech-house": "tech_house", "berlin tech house": "tech_house", "techhouse": "tech_house"}

def card(name):
    n = (name or "").lower().strip(); n = ALIAS.get(n, n)
    if n not in CARDS: raise ValueError(f"no genre card {name!r}: {sorted(CARDS)}")
    c = copy.deepcopy(CARDS[n]); c["name"] = n; return c

def in_palette(path, c, role):
    p = _norm(path); low = os.path.basename(p).lower()
    if re.search(c["deny"], low) or re.search(c["deny"], p.lower().replace(S.lower(), "")): return False
    if (c.get("need") or {}).get(role) and not re.search(c["need"][role], low): return False
    if (c.get("name_deny") or {}).get(role) and re.search(c["name_deny"][role], low): return False
    return any(p.startswith(d) for d in c["dirs"].get(role, []))

def _true_root(p):
    import librosa
    y, sr = librosa.load(p, sr=22050, duration=.4); return float(np.median(librosa.hz_to_midi(librosa.yin(y, fmin=40, fmax=2000, sr=sr))))

def tonal_ok(p, role="bass"):
    """a pitched shot (bass / stab) is usable only when soundgate finds no hard defect (wobble, noisy stack) AND a second pitch detector agrees on the octave
    (Hermes's tech house track died on Bass_Shot_4 ±142 cents and Chord_Shot_1 ±193 cents; Copper Rain on a G6 read as G5)"""
    from . import soundgate as SG
    m = SG.measure(p)
    if not m or m.get("error") or m.get("root") is None or SG.quality(m, role)[1]: return False
    try: return abs(_true_root(p) - m["root"]) <= 1.5
    except Exception: return False

def pick_kick(c, tonic, rng=None, title=None, near=None, **kw):
    """(path, semitones to retune): the least used kick of the palette that kicktune can put on the tonic or the fifth (<= 3 st); the shift is registered for the report"""
    from . import kicktune
    return kicktune.kick_in_key(candidates(c, "kick", 24, near=near, **kw), tonic, rng, title)

def candidates(c, role, k=12, near=None, **kw):
    """CLAP candidates for the role restricted to the card's folders (contains is not enough: several folders) and deny words; drumq + verdicts for drum roles"""
    from . import clap_index as CI
    r = c["roles"].get(role); cand = CI.candidates(c["query"][role], 1500 if role in ("bass", "stab") else 400, near=near, role=r, per_dir=None, **kw)
    cand = [p for p in cand if in_palette(p, c, role)]
    if role in ("bass", "stab"): cand = [p for p in cand if tonal_ok(p, "bass" if role == "bass" else "pad")]                 # P176: pitched shots must pass the gate BEFORE the render
    if r in ("kick", "clap", "snare", "hats", "rim", "perc", "shaker"):
        from . import drumq, verdicts
        lim = "kick" if r == "kick" else ("clap" if r in ("clap", "rim") else None)
        if lim: cand = [p for p in cand if drumq.ok(p, lim) and not verdicts.check(p, lim)[0]] or cand
        cand = [p for p in cand if not (lim and verdicts.check(p, lim)[1])] or cand
    return cand[:k]

def pick(c, role, rng=None, title=None, near=None, k=None, **kw):
    from . import fresh
    cand = candidates(c, role, 12 if k is None else max(12, 3 * k), near=near, **kw)
    if not cand: raise ValueError(f"genre card {c['name']}: nothing in the palette for {role!r} ({c['dirs'].get(role)})")
    return fresh.pick(cand, rng, k=k, title=title)

def fx_files(c, kind):
    pat = c["fx"].get(kind)
    if not pat: return []
    out = []
    for d in c["dirs"]["fx"] + c["dirs"].get("vox", []):
        if os.path.isdir(d): out += sorted(os.path.join(d, f) for f in os.listdir(d) if pat.lower() in f.lower() and f.lower().endswith(".wav"))
    return sorted(set(out))

def fx_plan(sections, c=None, every=16):
    """[(bar, kind)]: a riser over the 2 bars before every home that follows a break / build, an impact on its downbeat, a downlifter in the first bar of a
    break, a vocal chop on the last bar of every `every` bars inside homes (not twice in a row of phrases)"""
    from .chords import role_of
    secs = [(int(a), int(b), n) for a, b, n, *_ in sections if int(b) > int(a)]; out = []
    for i, (a, b, n) in enumerate(secs):
        r = role_of(n); prev = role_of(secs[i - 1][2]) if i else None
        if r == "home" and prev in ("break", "build"): out += [(a - 2, "riser"), (a, "impact")]
        if r == "break": out.append((a, "downlifter"))
        if r == "home": out += [(bar, "vox") for k_, bar in enumerate(range(a + every - 1, b, every)) if k_ % 2 == 0]
    return sorted(set(out))

def similarity(mp3, labels, clips=(.3, .55, .8), clip_s=10.0):
    """{label: mean cosine of 3 clips of the mix against the CLAP text "a <label> track"} - a report for Стас, never a gate"""
    from . import clap_index as CI
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    x, sr = sf.read(mp3, dtype="float32", always_2d=True); x = x.mean(1); n = int(clip_s * sr); arrs = []
    for f in clips:
        a = int(max(0, min(len(x) - n, f * len(x) - n / 2))); seg = x[a:a + n]
        if sr != CI.SR: g = gcd(CI.SR, sr); seg = resample_poly(seg, CI.SR // g, sr // g).astype(np.float32)
        arrs.append(seg)
    A = CI.embed_audio(arrs).mean(0); A = A / (np.linalg.norm(A) + 1e-9); T = CI.embed_text([f"a {l} track" for l in labels])
    return {l: round(float(t @ A), 3) for l, t in zip(labels, T)}


def palette_problems(sources, c):
    """P176: problem lines for sources of a render that belong to a DENIED family of the card's genre (name or path), file names and sfz names alike"""
    out = []
    for src in sources or []:
        low = str(src).lower().replace(S.lower(), "")
        if re.search(c["deny"], low): out.append(f"{os.path.basename(str(src))}: семейство запрещено в жанре {c['name']} (карточка): подбери звук из палитры жанра (genres.pick)")
    return out

def meta_defaults(c):
    """what a score's META takes from the card (explicit META values win): target loudness, master mode, premaster mode and knee, limiter gate"""
    m = dict(c.get("master") or {}); g = m.pop("gates", None)
    return {**({"ceil_db": m["ceil_db"]} if "ceil_db" in m else {}), "target": m.get("target", -14.0), "master": m.get("master", "warm"), "premaster": m.get("premaster", "sat"), **({"premaster_knee": m["premaster_knee"]} if "premaster_knee" in m else {}), **({"gates": g} if g else {})}

ALIAS.update({"afro": "afro_house", "afro house": "afro_house", "deep house": "deep", "melodic house": "melodic", "deep melodic house": "melodic", "uk garage": "garage", "2-step": "garage", "lofi": "downtempo",
              "lo-fi": "downtempo", "trip hop": "downtempo", "witch house": "witch_house", "breakbeat": "breaks", "dnb": "breaks", "minimal techno": "minimal", "hard techno": "techno",
              "deep techno": "techno", "magical ambient": "ambient", "drone": "ambient", "house music": "house"})


# ---- P177 (Hermes's tech house: «stab громче бочки на 12.5 дБ, хэты на -25, верх тихий»): levels per role as numbers, and a report against them ---------------
# active-RMS of each stem relative to the kick (drums stem 35-140 Hz) on NO STATIC / DANGER: hats -15.2 / -17.7, clap -10.7 / -13.4, bass -3.1 / -4.4, other (stabs) -11.1 / -9.8, vocals -10.5 / -5.8
CARDS["tech_house"]["levels_db"] = {"kick": 0.0, "bass": -4.0, "clap": -12.0, "hats": -16.5, "ohat": -17.0, "shaker": -20.0, "rim": -16.0, "perc": -16.0, "stab": -10.5, "vocal": -8.0, "fx": -14.0}
for _n, _c in CARDS.items():
    _c.setdefault("levels_db", {"kick": 0.0, "bass": -3.0, "clap": -12.0, "hats": -18.0, "ohat": -18.0, "shaker": -20.0, "rim": -16.0, "perc": -17.0, "stab": -11.0, "keys": -11.0, "pad": -14.0, "hook": -10.0, "vocal": -8.0, "fx": -15.0})
CARDS["tech_house"]["master"]["ceil_db"] = -2.5; CARDS["techno"]["master"]["ceil_db"] = -2.5            # the mp3 of a hard-limited master overshoots: true peak -0.88 with a -2 dB ceiling

def level(c, role):
    """linear level for Track.add (RMS relative to the first layer = the kick) from the card's levels_db"""
    return 10 ** (c["levels_db"].get(role, -12.0) / 20)

def mix_problems(layers_db, c, tol=4.0):
    """report lines: a layer whose ACTIVE level (layers_db, dBFS) relative to the kick is more than tol dB off the card's levels_db"""
    if not layers_db or layers_db.get("kick") is None: return []
    k = layers_db["kick"]; out = []
    for n, v in layers_db.items():
        if v is None or n == "kick": continue
        role = next((r for r in c["levels_db"] if n.startswith(r)), None)
        if role is None: continue
        d = (v - k) - c["levels_db"][role]
        if abs(d) > tol: out.append(f"слой {n}: {v - k:+.1f} дБ к бочке, по карточке {c['name']} {c['levels_db'][role]:+.1f} ({'громче' if d > 0 else 'тише'} на {abs(d):.1f} дБ): поставь genres.level(card, '{role}')")
    return out


# ---- P180 (2026-11-22, Reel Techno: the «hat» was sd02 = a snare, the «bass» a lead shot, the «clap» a perc): role NAMES for every genre --------------------------------
for _n, _c in CARDS.items():
    _c["need"] = {**_c.get("need", {}), "bass": r"bass|sub", "clap": r"clap|(^|[^a-z])cp|snap|hand"}
    nd = _c.get("name_deny", {})
    _c["name_deny"] = {**nd, "hats": (nd.get("hats", "") + "|" if nd.get("hats") else "") + r"(^|[^a-z])sd|snare|snr|(^|[^a-z])sn[0-9_]|tom|rim|clap|ophat|op_hat|ophh|oh[0-9]",
                       "bass": r"lead|chord|arp|pluck|pad|vox|stab", "clap": r"perc|snare|(^|[^a-z])sd|rim|tom|kick|hat", "kick": r"snare|clap|hat|(^|[^a-z])sd|synth|lead|bass_shot"}
