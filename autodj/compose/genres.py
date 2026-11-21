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

S = os.path.expanduser("~/samples/")
WA, WA2, T909, T808 = S + "wa_techno/WAV MIDI Presets/", S + "wa2/WAV MIDI Loops/", S + "tidal-drum-machines/machines/RolandTR909/", S + "tidal-drum-machines/machines/RolandTR808/"
AFRO_LOFI = r"conga|bongo|cabasa|clave|maraca|guiro|agogo|djembe|tumba|shekere|marimba|kalimba|vibra|xylo|bell|glock|chime|rhodes|piano|pianet|wurl|cp80|e-piano|epiano|harp|flute|sitar|steel|tabla|udu|cajon|kora|acoustic|upright|dbass|tuba|sax"
CARDS = {
    "tech_house": dict(
        bpm=(124, 128), default_bpm=126, rhythm="tech_house", mood="club", harmony="stab", bass="rolling_riff",
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
        mix={"hats_vs_kick_db": (-21, -15), "bass_vs_kick_db": (-0.5, 6.0), "perc_vs_kick_db": (-13, -11)},
        fx={"riser": "Uplifter", "downlifter": "Downlifter", "impact": "Kick_Boom", "sweep": "Sweep", "vox": "Vox_Crazy"},
        need={"ohat": r"open|^oh|_oh", "shaker": r"shak|^sh|_sh|shk"},                      # the file name must say it (CLAP alone called a cabasa an open hat)
        name_deny={"hats": r"open|^oh|_oh|crash|ride|cymbal_crash", "shaker": r"tamb|vib|guir"},
        refs=("sven_v_th_face_it", "mike_morrisey_ollie_bc_d"), labels=("tech house", "afro house", "deep house", "lo-fi hip hop", "techno")),
}
ALIAS = {"tech house": "tech_house", "tech-house": "tech_house", "berlin tech house": "tech_house", "techhouse": "tech_house"}

def card(name):
    n = (name or "").lower().strip(); n = ALIAS.get(n, n)
    if n not in CARDS: raise ValueError(f"no genre card {name!r}: {sorted(CARDS)}")
    c = copy.deepcopy(CARDS[n]); c["name"] = n; return c

def in_palette(path, c, role):
    p = str(path); low = os.path.basename(p).lower()
    if re.search(c["deny"], low) or re.search(c["deny"], p.lower().replace(S.lower(), "")): return False
    if (c.get("need") or {}).get(role) and not re.search(c["need"][role], low): return False
    if (c.get("name_deny") or {}).get(role) and re.search(c["name_deny"][role], low): return False
    return any(p.startswith(d) for d in c["dirs"].get(role, []))

def candidates(c, role, k=12, near=None, **kw):
    """CLAP candidates for the role restricted to the card's folders (contains is not enough: several folders) and deny words; drumq + verdicts for drum roles"""
    from . import clap_index as CI
    r = c["roles"].get(role); cand = CI.candidates(c["query"][role], 400, near=near, role=r, per_dir=None, **kw)
    cand = [p for p in cand if in_palette(p, c, role)]
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
