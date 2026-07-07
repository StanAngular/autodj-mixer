#!/usr/bin/env python3
"""
club_rework.py — M4 v2: pop→club rework КАК ДЕЛАЮТ РЕМИКСЕРЫ, а не сумматор.
v1 честно провалил прослушку («два трека параллельно») — v2 строит СЕКЦИОННУЮ
клубную аранжировку по A1F обоих треков:

  groove-интро → verse (разреженно) → build (sweep+lift) → DROP = ПРИПЕВ попсы →
  breakdown (вокал без ударных) → build → DROP 2 = припев ПОВТОРНО (хук — главный
  актив) → groove-аутро (fade)

DJ-принципы, зашитые в рендер:
  • частотные РОЛИ, не гейны: низ принадлежит клубному груву (вся попса под HPF
    ~150Гц, поп-drums выброшены совсем); в breakdown попсе возвращается тело;
  • sidechain: кик-доли продавливают вокал/other (duck по четвертям);
  • лупы донора подбираются ПО ЕГО A1F: для дропа — из пиковой части, для
    интро — из разреженной (v1 брал «середину», попадая в 3-минутное интро Exhale);
  • приёмы на стыках: filter-sweep в build, drum-lift перед дропом, fade в аутро.

Опирается на уже построенное:
  • структура попсы: A1F bar_labels (intro/verse/chorus/…): smart_mixer.load_a1f_track_data
  • стемы: demucs-кэш P55 (<demix>/htdemucs/<name>/{vocals,bass,drums,other}.wav)
  • темп: pyrubberband (как M3); склейки: eq_pow из smart_mixer (equal-power)

Гейт темпа мягче миксового (rework — творческий инструмент): stretch 0.85–1.25;
за пределами — отказ с причиной (или --force, честно предупредив о качестве).

Opt-in отдельный модуль: smart_mixer/пайплайн не тронуты.
  python3 club_rework.py --pop pop.wav --drums-donor club.wav --demix-dir shared/tracks/demix \
      --ann-dir shared/ann --target-bpm 124 --out club_edit.wav
"""
import argparse
import os
import sys

import numpy as np

# ─── Структурный план (чистое) ───────────────────────────────────────────────

CALM = ("intro", "inst", "verse", "bridge", "start")     # интро-материал
TAIL = ("outro", "inst", "verse", "end")                 # аутро-материал
BODY = ("verse", "chorus", "bridge", "inst", "solo", "break")


def _blocks(bar_labels: list[str]) -> list[tuple[int, int, str]]:
    """bar_labels → непрерывные блоки (start_bar, end_bar, label). Чистая."""
    out = []
    if not bar_labels:
        return out
    s, cur = 0, bar_labels[0]
    for i, l in enumerate(bar_labels[1:], 1):
        if l != cur:
            out.append((s, i, cur))
            s, cur = i, l
    out.append((s, len(bar_labels), cur))
    return out


def _pick_loop(blocks, wanted, loop_len, from_end=False):
    """Первый (или последний) блок с меткой из wanted длиной ≥ loop_len//2 → (s, e)."""
    it = reversed(blocks) if from_end else blocks
    for s, e, l in it:
        if l in wanted and (e - s) >= max(2, loop_len // 2):
            return s, min(e, s + loop_len)
    return None


def rework_plan(bar_labels: list[str], intro_bars: int = 16, outro_bars: int = 16,
                loop_len: int = 8) -> list[tuple[int, int, int]]:
    """DJ-план: [(src_start_bar, src_end_bar, repeats)]. Чистая.
      1) луп-ИНТРО: спокойный блок начала, повторами до intro_bars;
      2) ТЕЛО: от первого BODY-бара до конца последнего BODY-блока — как есть;
      3) луп-АУТРО: хвостовой блок повторами до outro_bars.
    Нет меток → весь трек как есть (план без обмана)."""
    n = len(bar_labels or [])
    if n == 0:
        return []
    blocks = _blocks(bar_labels)

    intro = _pick_loop(blocks, CALM, loop_len)
    body_bars = [i for i, l in enumerate(bar_labels) if l in BODY]
    body = (body_bars[0], body_bars[-1] + 1) if body_bars else (0, n)
    outro = _pick_loop(blocks, TAIL, loop_len, from_end=True)

    plan: list[tuple[int, int, int]] = []
    if intro:
        s, e = intro
        reps = max(1, round(intro_bars / (e - s)))
        plan.append((s, e, reps))
    plan.append((body[0], body[1], 1))
    if outro and outro[0] >= body[1] - 1:                 # хвост, не середина
        s, e = outro
        reps = max(1, round(outro_bars / (e - s)))
        plan.append((s, e, reps))
    return plan


def plan_length_bars(plan) -> int:
    return sum((e - s) * r for s, e, r in plan)


# Потолок 1.25 сознательно: типовой rework «попса ~100-105 → клуб 122-126» = ×1.19-1.25,
# rubberband это тянет достойно (rework — творческий инструмент, не бит-матч перехода).
STRETCH_LO, STRETCH_HI = 0.85, 1.25


def club_gate(pop_bpm: float, target_bpm: float) -> tuple[bool, float, str]:
    """Гейт rework-стретча (мягче миксового). → (ok, rate, причина)."""
    if not pop_bpm or not target_bpm:
        return False, 0.0, "BPM неизвестен (попса или target)"
    rate = float(target_bpm) / float(pop_bpm)
    if not (STRETCH_LO <= rate <= STRETCH_HI):
        return False, rate, (f"stretch ×{rate:.3f} вне [{STRETCH_LO}..{STRETCH_HI}] — "
                             f"качество развалится; ближе target-bpm или --force")
    return True, rate, f"ok: ×{rate:.3f} ({pop_bpm:.0f}→{target_bpm:.0f} BPM)"


# ─── Рендер (numpy in → numpy out) ───────────────────────────────────────────

def _xfade_concat(parts: list[np.ndarray], sr: int, ms: int = 15) -> np.ndarray:
    """Склейка кусков с коротким equal-power кроссфейдом (без щелчков)."""
    from smart_mixer import eq_pow
    n = int(sr * ms / 1000)
    out = parts[0]
    for p in parts[1:]:
        if n and len(out) > n and len(p) > n:
            fo, fi = eq_pow(n)
            out = np.concatenate([out[:-n],
                                  out[-n:] * fo[:, None] + p[:n] * fi[:, None],
                                  p[n:]])
        else:
            out = np.concatenate([out, p])
    return out


def render_plan(audio: np.ndarray, downbeats: np.ndarray, plan, sr: int) -> np.ndarray:
    """Нарезать по даунбитам и склеить по плану (лупы повторами)."""
    parts = []
    last = len(downbeats) - 1
    for s, e, reps in plan:
        s, e = max(0, min(s, last)), max(1, min(e, last))
        if e <= s:
            continue
        seg = audio[int(downbeats[s]):int(downbeats[e])]
        parts.extend([seg] * reps)
    return _xfade_concat(parts, sr) if parts else audio


def tile_to_length(loop: np.ndarray, total: int, sr: int, xfade_ms: int = 15) -> np.ndarray:
    """Затайлить луп до total сэмплов (мягкие склейки). Каждый стык съедает xfade —
    репиты считаются по эффективной длине, добивается точно до total."""
    if len(loop) == 0:
        return np.zeros((total, 2), dtype="float32")
    n_x = int(sr * xfade_ms / 1000)
    eff = max(1, len(loop) - n_x)                    # вклад каждого следующего тайла
    reps = 1 + int(np.ceil(max(0, total - len(loop)) / eff))
    out = _xfade_concat([loop] * reps, sr, xfade_ms)
    if len(out) < total:                             # страховка на граничные случаи
        out = np.concatenate([out, np.zeros((total - len(out), out.shape[1]), dtype=out.dtype)])
    return out[:total]


def _limit(x: np.ndarray, ceiling: float = 0.99) -> np.ndarray:
    peak = float(np.max(np.abs(x))) or 1.0
    return x * (ceiling / peak) if peak > ceiling else x


def _stretch(x: np.ndarray, sr: int, rate: float) -> np.ndarray:
    if abs(rate - 1.0) < 1e-3:
        return x
    import pyrubberband as pyrb
    return pyrb.time_stretch(x, sr, rate).astype("float32")


# ─── v2: DSP-кирпичи ремиксера (чистые numpy) ────────────────────────────────

def _sos_filter(x: np.ndarray, sr: int, fc: float, btype: str) -> np.ndarray:
    import scipy.signal as signal
    sos = signal.butter(4, fc / (sr / 2), btype=btype, output="sos")
    out = np.empty_like(x)
    for ch in range(x.shape[1]):
        out[:, ch] = signal.sosfilt(sos, x[:, ch]).astype(np.float32)
    return out


def hpf(x, sr, fc):
    """High-pass: срезать низ (частотная РОЛЬ: низ отдан клубному груву)."""
    return _sos_filter(x, sr, fc, "high")


def lpf(x, sr, fc):
    return _sos_filter(x, sr, fc, "low")


def sidechain_duck(x: np.ndarray, sr: int, quarter: int, depth_db: float = -5.0,
                   release_ms: float = 110.0) -> np.ndarray:
    """Кик продавливает слой: на каждой четверти гейн падает до depth и экспоненциально
    восстанавливается (классический pumping). quarter — интервал доли в сэмплах."""
    if quarter <= 0 or len(x) == 0:
        return x
    depth = 10 ** (depth_db / 20.0)
    rel = max(1, int(sr * release_ms / 1000))
    env = np.ones(len(x), dtype="float32")
    t = np.arange(rel, dtype="float32")
    curve = depth + (1.0 - depth) * (1.0 - np.exp(-4.0 * t / rel))
    for pos in range(0, len(x), quarter):
        seg = min(rel, len(x) - pos)
        env[pos:pos + seg] = np.minimum(env[pos:pos + seg], curve[:seg])
    return x * env[:, None]


def hpf_sweep(x: np.ndarray, sr: int, fc_from: float, fc_to: float, blocks: int = 8) -> np.ndarray:
    """Filter-sweep для build: cutoff растёт ступенями по блокам (дёшево и музыкально)."""
    if len(x) == 0 or blocks < 1:
        return x
    out = np.empty_like(x)
    step = max(1, len(x) // blocks)
    for i in range(blocks):
        a, b = i * step, (len(x) if i == blocks - 1 else (i + 1) * step)
        fc = fc_from + (fc_to - fc_from) * (i / max(1, blocks - 1))
        out[a:b] = _sos_filter(x[a:b], sr, fc, "high")
    return out


def fade_gain(x: np.ndarray, g_from: float, g_to: float) -> np.ndarray:
    """Линейная гейн-рампа (fade аутро)."""
    if len(x) == 0:
        return x
    return x * np.linspace(g_from, g_to, len(x), dtype="float32")[:, None]


# ─── v2: выбор лупов донора по ЕГО A1F ───────────────────────────────────────

def pick_donor_loop_bars(d_labels: list[str], kind: str, loop_len: int = 8) -> tuple[int, int]:
    """Бары лупа донора по его меткам. 'peak' — из энергетической части (chorus/drop/inst
    после интро), 'sparse' — из интро/разреженного начала. Чистая; фоллбэк — середина."""
    n = len(d_labels or [])
    if n == 0:
        return (0, loop_len)
    blocks = _blocks(d_labels)
    if kind == "sparse":
        got = _pick_loop(blocks, ("intro", "start", "verse"), loop_len)
        if got:
            return got
        return (0, min(loop_len, n))
    # peak: первый содержательный блок ПОСЛЕ интро
    for s, e, l in blocks:
        if l in ("chorus", "solo", "inst", "break", "verse") and s >= max(4, n // 10):
            return (s, min(e, s + loop_len))
    mid = max(0, n // 2 - loop_len // 2)
    return (mid, min(n, mid + loop_len))


# ─── v2: секционная аранжировка ─────────────────────────────────────────────

def club_arrangement(bar_labels: list[str], intro_bars: int = 16, build_bars: int = 8,
                     outro_bars: int = 16) -> list[dict]:
    """Клубная арка из A1F-структуры попсы. Чистая. Секция:
      {kind, pop: (s,e)|None, bars, groove: 'peak'|'sparse'|None}
    Хук (chorus) играет ДВАЖДЫ (drop1/drop2) — главный актив попсы."""
    blocks = _blocks(bar_labels or [])
    verses = [(s, e) for s, e, l in blocks if l == "verse"]
    chors = [(s, e) for s, e, l in blocks if l == "chorus"]
    breaks = [(s, e) for s, e, l in blocks if l in ("bridge", "inst", "break")]
    n = len(bar_labels or [])
    if not chors:                                        # структуры нет — честный фоллбэк
        chors = [(0, n)] if n else [(0, 8)]
    hook = max(chors, key=lambda p: p[1] - p[0])         # самый длинный припев = хук
    verse1 = verses[0] if verses else None
    brk = breaks[0] if breaks else (verses[1] if len(verses) > 1 else None)

    arr: list[dict] = [
        dict(kind="intro", pop=None, bars=intro_bars, groove="sparse"),
    ]
    if verse1:
        arr.append(dict(kind="verse", pop=verse1, bars=verse1[1] - verse1[0], groove="peak"))
    arr.append(dict(kind="build", pop=None, bars=build_bars, groove="peak"))
    arr.append(dict(kind="drop", pop=hook, bars=hook[1] - hook[0], groove="peak"))
    if brk:
        arr.append(dict(kind="breakdown", pop=brk, bars=brk[1] - brk[0], groove=None))
        arr.append(dict(kind="build", pop=None, bars=build_bars, groove="peak"))
        arr.append(dict(kind="drop", pop=hook, bars=hook[1] - hook[0], groove="peak"))
    arr.append(dict(kind="outro", pop=None, bars=outro_bars, groove="peak"))
    return arr


HPF_POP = 150.0          # частотная роль: низ у клубного грува
DUCK_DB = -5.0


def _slice_bars(audio: np.ndarray, db: np.ndarray, s: int, e: int) -> np.ndarray:
    last = len(db) - 1
    s, e = max(0, min(s, last)), max(1, min(e, last))
    return audio[int(db[s]):int(db[e])] if e > s else audio[:0]


def render_section(sec: dict, pop: dict, db: np.ndarray, groove_loops: dict,
                   sr: int, bar_len: int, quarter: int) -> np.ndarray:
    """Секция → аудио по DJ-ролям. pop = {'vocals','other','bass'} (drums попсы ВЫБРОШЕНЫ)."""
    total = sec["bars"] * bar_len
    layers: list[np.ndarray] = []

    if sec["groove"]:
        g = tile_to_length(groove_loops[sec["groove"]], total, sr)
        if sec["kind"] == "build":
            g = g.copy()
            lift = min(bar_len, total)                   # drum-lift: последний бар без ударных
            g[-lift:] = 0.0
        if sec["kind"] == "outro":
            g = fade_gain(g, 1.0, 0.15)
        layers.append(g)

    if sec["pop"] is not None:
        s, e = sec["pop"]
        voc = _slice_bars(pop["vocals"], db, s, e)[:total]
        oth = _slice_bars(pop["other"], db, s, e)[:total]
        bas = _slice_bars(pop["bass"], db, s, e)[:total]
        if sec["kind"] == "breakdown":                   # попсе возвращают тело, грува нет
            mix_pop = voc + oth + bas * 0.8
        else:                                            # частотные роли: низ не её
            mix_pop = hpf(voc + oth, sr, HPF_POP)
            if sec["groove"]:
                mix_pop = sidechain_duck(mix_pop, sr, quarter, DUCK_DB)
        pad = total - len(mix_pop)
        if pad > 0:
            mix_pop = np.concatenate([mix_pop, np.zeros((pad, mix_pop.shape[1]), dtype=mix_pop.dtype)])
        layers.append(mix_pop)

    if sec["kind"] == "build" and layers:                # sweep на всём билде
        layers = [hpf_sweep(sum(layers), sr, 120, 700, blocks=max(2, sec["bars"] // 1))]

    out = sum(layers) if layers else np.zeros((total, 2), dtype="float32")
    return out[:total]


# ─── Сборка (I/O) ────────────────────────────────────────────────────────────

def _load_track(wav, demix_dir, ann_dir, sr):
    """(стемы dict, downbeats samples, bpm) трека: A1F-грид (обязателен для попсы)."""
    from smart_mixer import load_a1f_track_data
    from stem_mixer import load_stem
    stems = {s: load_stem(wav, demix_dir, s) for s in ("vocals", "bass", "drums", "other")}
    a1f = load_a1f_track_data(wav, sr, a1f_dir=None, catalog_dir=None)
    if not a1f or a1f.get("downbeats") is None or not len(a1f.get("downbeats", [])):
        raise RuntimeError(f"нет A1F-данных для {wav} — прогони batch_a1f (нужны downbeats+структура)")
    return stems, np.asarray(a1f["downbeats"]), float(a1f.get("bpm") or 0), a1f.get("bar_labels") or []


def pop_to_club(pop_wav, donor_wav, demix_dir, ann_dir, target_bpm, sr=44100,
                intro_bars=16, outro_bars=16, pop_drums_db=-12.0, club_drums_db=0.0,
                force=False, out="club_edit.wav"):
    """v2: секционная аранжировка (см. докстринг модуля). pop_drums_db сохранён в
    сигнатуре для совместимости, но поп-drums в v2 ВЫБРОШЕНЫ (частотная роль грува)."""
    import soundfile as sf
    stems, db, pop_bpm, labels = _load_track(pop_wav, demix_dir, ann_dir, sr)
    d_stems, d_db, d_bpm, d_labels = _load_track(donor_wav, demix_dir, ann_dir, sr)
    tgt = target_bpm or d_bpm
    ok, rate, why = club_gate(pop_bpm, tgt)
    print(f"Гейт: {why}")
    if not ok and not force:
        sys.exit(2)

    # попса: стретч стемов к клубному темпу один раз; сетка масштабируется тем же rate
    pop = {k: _stretch(v, sr, rate) for k, v in stems.items() if k != "drums"}
    db_s = (np.asarray(db, dtype="float64") / rate).astype("int64")

    # грув: 2 лупа донора по ЕГО A1F (peak для тела, sparse для интро), к target-темпу
    d_rate = (tgt / d_bpm) if d_bpm else 1.0
    loops = {}
    for kind in ("peak", "sparse"):
        ls, le = pick_donor_loop_bars(d_labels, kind)
        raw = _slice_bars(d_stems["drums"], d_db, ls, le)
        loops[kind] = _stretch(raw, sr, d_rate) if len(raw) else np.zeros((1, 2), "float32")
    if not len(loops["sparse"]):
        loops["sparse"] = loops["peak"]

    bar_len = int(round(60.0 / tgt * 4 * sr))
    quarter = max(1, bar_len // 4)
    arr = club_arrangement(labels, intro_bars=intro_bars, outro_bars=outro_bars)
    print("Аранжировка: " + " → ".join(f"{s['kind']}({s['bars']}b)" for s in arr))

    parts = [render_section(sec, pop, db_s, loops, sr, bar_len, quarter) for sec in arr]
    mix = _limit(_xfade_concat(parts, sr, ms=25))
    sf.write(out, mix, sr)
    g_club = 10 ** (club_drums_db / 20)                  # noqa: сохранён для CLI-совместимости
    print(f"Club edit v2: {out} ({len(mix)/sr:.1f}s @ {tgt:.0f} BPM; хук ×2, sidechain, "
          f"HPF {HPF_POP:.0f}Гц, грув по A1F донора)")
    return out


def _main():
    ap = argparse.ArgumentParser(description="M4: pop→club rework (структура+грув+темп)")
    ap.add_argument("--pop", required=True, help="поп-трек WAV (нужны его A1F + стемы)")
    ap.add_argument("--drums-donor", required=True, help="клубный трек WAV (его drums-стем = грув)")
    ap.add_argument("--demix-dir", required=True)
    ap.add_argument("--ann-dir", default=None)
    ap.add_argument("--target-bpm", type=float, default=0, help="дефолт: BPM донора")
    ap.add_argument("--intro-bars", type=int, default=16)
    ap.add_argument("--outro-bars", type=int, default=16)
    ap.add_argument("--pop-drums-db", type=float, default=-12.0)
    ap.add_argument("--club-drums-db", type=float, default=0.0)
    ap.add_argument("--force", action="store_true", help="пройти гейт стретча (качество на твоей совести)")
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--out", default="club_edit.wav")
    a = ap.parse_args()
    pop_to_club(a.pop, a.drums_donor, a.demix_dir, a.ann_dir, a.target_bpm, a.sr,
                a.intro_bars, a.outro_bars, a.pop_drums_db, a.club_drums_db, a.force, a.out)


if __name__ == "__main__":
    _main()
