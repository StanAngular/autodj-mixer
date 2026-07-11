#!/usr/bin/env python3
"""
vocal_phrases.py — P69: фразовый уровень вокала. Три задачи:
  1) РЕЗКА vocals-стема на фразы по паузам (энергетическая огибающая);
  2) ХУК-ДЕТЕКЦИЯ: «что именно прёт» — фраза, которая повторяется чаще всех
     (спектральные отпечатки фраз + косинусная близость, чистый numpy);
  3) СЛОВА (опционально): плагинный ASR — любой CLI (whisper и т.п.) через
     --asr-cmd 'команда {wav}', текст фразы из stdout. Без ASR фразы безымянные.

Зачем: rework оперирует не только куплетом/припевом целиком, но и ФРАЗАМИ —
hook-stutter перед дропом, тизер в интро, интересные повторы (идея Стаса).
Кому: club_rework (P69-интеграция), stem_mixer (точечные вставки), отчёты.

CLI:
  python3 vocal_phrases.py --wav pop.wav --demix-dir D [--asr-cmd 'whisper {wav}'] --out phrases.json
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

# ─── Огибающая и резка на фразы (чистое) ─────────────────────────────────────

def rms_envelope(x: np.ndarray, sr: int, win_ms: float = 50, hop_ms: float = 25):
    """RMS-огибающая моно/стерео сигнала. → (env, hop_samples). Чистая."""
    mono = x.mean(1) if x.ndim == 2 else x
    win, hop = max(1, int(sr * win_ms / 1000)), max(1, int(sr * hop_ms / 1000))
    n = max(0, (len(mono) - win) // hop + 1)
    env = np.empty(n, dtype="float64")
    for i in range(n):
        seg = mono[i * hop:i * hop + win]
        env[i] = np.sqrt((seg.astype("float64") ** 2).mean())
    return env, hop


def detect_phrases(vocals: np.ndarray, sr: int, min_pause_ms: float = 400,
                   min_phrase_ms: float = 600, thresh_ratio: float = 0.10,
                   max_phrase_s: float = 12.0) -> list[tuple[int, int]]:
    """Фразы вокала: активные участки между паузами. Порог адаптивный
    (thresh_ratio × 95-й перцентиль огибающей). Куски длиннее max_phrase_s РЕКУРСИВНО
    дробятся по самой глубокой внутренней паузе (96-секундная «фраза» — не фраза,
    а слипшийся припев: live-урок P69). → [(start, end)] в сэмплах. Чистая."""
    env, hop = rms_envelope(vocals, sr)
    if len(env) == 0:
        return []
    thr = thresh_ratio * float(np.percentile(env, 95))
    active = env > thr
    min_pause = max(1, int(sr * min_pause_ms / 1000 / hop))
    min_phrase = int(sr * min_phrase_ms / 1000)

    phrases, start, gap = [], None, 0
    for i, a in enumerate(active):
        if a:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_pause:
                s, e = start * hop, (i - gap + 1) * hop
                if e - s >= min_phrase:
                    phrases.append((s, e))
                start, gap = None, 0
    if start is not None:
        s, e = start * hop, len(env) * hop
        if e - s >= min_phrase:
            phrases.append((s, e))
    return _split_long(vocals, sr, phrases, env, hop, int(max_phrase_s * sr), min_phrase)


def _split_long(vocals, sr, phrases, env, hop, max_len, min_phrase):
    """Рекурсивно дробит длинные куски по самой тихой точке внутри (глубочайшая пауза)."""
    out = []
    for s, e in phrases:
        if e - s <= max_len:
            out.append((s, e))
            continue
        i0, i1 = s // hop, e // hop
        pad = max(1, (i1 - i0) // 8)                     # не резать у краёв
        seg = env[i0 + pad:i1 - pad]
        if len(seg) == 0:
            out.append((s, e))
            continue
        cut = (i0 + pad + int(np.argmin(seg))) * hop
        if cut - s >= min_phrase and e - cut >= min_phrase:
            out.extend(_split_long(vocals, sr, [(s, cut), (cut, e)], env, hop, max_len, min_phrase))
        else:
            out.append((s, e))
    return out


# ─── Отпечатки и хук (чистое, numpy) ─────────────────────────────────────────

def phrase_fingerprint(x: np.ndarray, sr: int, bands: int = 24) -> np.ndarray:
    """Спектральный отпечаток фразы: лог-мощность в лог-разнесённых полосах,
    ЦЕНТРИРОВАННАЯ (минус среднее) — иначе общий «пьедестал» лог-энергий делает все
    фразы похожими. Окно Ханна против спектральной утечки. Чистый numpy. Чистая."""
    mono = x.mean(1) if x.ndim == 2 else x
    if len(mono) < 256:
        return np.zeros(bands)
    w = np.hanning(len(mono))
    spec = np.abs(np.fft.rfft(mono.astype("float64") * w)) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    edges = np.geomspace(80, min(8000, sr / 2 - 1), bands + 1)
    v = np.array([spec[(freqs >= edges[i]) & (freqs < edges[i + 1])].sum() for i in range(bands)])
    v = np.log1p(v)
    v = v - v.mean()
    n = np.linalg.norm(v)
    return v / n if n else v


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def find_hook(vocals: np.ndarray, sr: int, phrases: list[tuple[int, int]],
              sim_thresh: float = 0.92) -> dict | None:
    """«Что прёт»: фраза с наибольшим числом похожих повторов (хук). Чистая.
    → {hook_index, repeats(индексы), score} | None (мало фраз)."""
    if len(phrases) < 2:
        return None
    fps = [phrase_fingerprint(vocals[s:e], sr) for s, e in phrases]
    best = None
    for i in range(len(phrases)):
        reps = [j for j in range(len(phrases))
                if j != i and cosine(fps[i], fps[j]) >= sim_thresh]
        dur = (phrases[i][1] - phrases[i][0]) / sr
        score = len(reps) * 10 + dur
        if reps and (best is None or score > best["score"]):
            best = {"hook_index": i, "repeats": reps, "score": round(score, 2)}
    return best


# ─── ASR-плагин (I/O-тонкое) ─────────────────────────────────────────────────

# ─── P70: слова с таймингами + фраза ПО ТЕКСТУ ──────────────────────────────

def transcribe_words(vocals: np.ndarray, sr: int, asr: str = "groq") -> list[dict]:
    """Word-level распознавание ВСЕГО вокала → [{word, start, end}] (сэмплы, абсолютные).
    asr='groq' — Groq Whisper API (env GROQ_API_KEY, verbose_json + word timestamps,
    тот же стек, что в ClaudeClaw); иначе asr = CLI-шаблон '{wav}', ожидающий JSON
    [{word,start,end(сек)}] в stdout. Ошибки → [] (слова опциональны)."""
    try:
        import soundfile as sf
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, vocals, sr)
            path = f.name
        if asr == "groq":
            words = _groq_words(path)
        else:
            r = subprocess.run(asr.replace("{wav}", path).split(),
                               capture_output=True, text=True, timeout=600)
            words = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
        os.unlink(path)
        return [{"word": w["word"].strip(), "start": int(float(w["start"]) * sr),
                 "end": int(float(w["end"]) * sr)} for w in words if w.get("word")]
    except Exception:
        return []


def _groq_words(wav_path: str) -> list[dict]:
    """Groq Whisper: verbose_json + word timestamps. env GROQ_API_KEY."""
    import requests
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return []
    with open(wav_path, "rb") as fh:
        r = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (os.path.basename(wav_path), fh, "audio/wav")},
            data={"model": "whisper-large-v3", "response_format": "verbose_json",
                  "timestamp_granularities[]": "word"},
            timeout=300)
    r.raise_for_status()
    return r.json().get("words") or []


def _norm_text(t: str) -> list[str]:
    import re
    return [w for w in re.sub(r"[^\w\s]", " ", (t or "").lower()).split() if w]


def find_text_span(words: list[dict], query: str, min_ratio: float = 0.55):
    """Найти фразу ПО ТЕКСТУ («бери фразу: Я приходжу…»): скользящее окно слов,
    похожесть SequenceMatcher (терпит неточную цитату). → (start, end, ratio, matched)
    в сэмплах | None. Чистая."""
    from difflib import SequenceMatcher
    q = _norm_text(query)
    toks = [_norm_text(w["word"]) for w in words]
    flat = [(t[0], i) for i, t in enumerate(toks) if t]
    if not q or not flat:
        return None
    best = None
    n = len(q)
    for width in {max(1, n - 2), n, n + 2}:
        for i in range(0, max(1, len(flat) - width + 1)):
            win = flat[i:i + width]
            ratio = SequenceMatcher(None, " ".join(q), " ".join(w for w, _ in win)).ratio()
            if ratio >= min_ratio and (best is None or ratio > best[2]):
                s = words[win[0][1]]["start"]
                e = words[win[-1][1]]["end"]
                best = (s, e, round(ratio, 3), " ".join(w for w, _ in win))
    return best


def transcribe_phrase(vocals: np.ndarray, sr: int, s: int, e: int, asr_cmd: str) -> str:
    """Текст фразы внешним ASR: '{wav}' в asr_cmd подменяется на temp-файл фразы,
    stdout = текст. Любая ошибка → '' (слова опциональны)."""
    if not asr_cmd:
        return ""
    try:
        import soundfile as sf
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, vocals[s:e], sr)
            path = f.name
        r = subprocess.run(asr_cmd.replace("{wav}", path).split(),
                           capture_output=True, text=True, timeout=120)
        os.unlink(path)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def phrases_report(wav: str, demix_dir: str, sr: int = 44100, asr_cmd: str = "") -> dict:
    """Полный фразовый отчёт трека: фразы + хук + (опц.) слова."""
    from stem_mixer import load_stem
    vocals = load_stem(wav, demix_dir, "vocals")
    ph = detect_phrases(vocals, sr)
    hook = find_hook(vocals, sr, ph)
    items = []
    for i, (s, e) in enumerate(ph):
        items.append({
            "index": i, "start_s": round(s / sr, 2), "end_s": round(e / sr, 2),
            "dur_s": round((e - s) / sr, 2),
            "text": transcribe_phrase(vocals, sr, s, e, asr_cmd),
            "is_hook": bool(hook and (i == hook["hook_index"] or i in hook["repeats"])),
        })
    return {"track": os.path.basename(wav), "phrases": items, "hook": hook}


def _main():
    ap = argparse.ArgumentParser(description="P69: фразы вокала + хук + (опц.) слова")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--demix-dir", required=True)
    ap.add_argument("--asr-cmd", default="", help="CLI ASR, '{wav}' → файл фразы (напр. 'whisper-cli {wav}')")
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--out", default="phrases.json")
    a = ap.parse_args()
    rep = phrases_report(a.wav, a.demix_dir, a.sr, a.asr_cmd)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    hook = rep["hook"]
    print(f"{len(rep['phrases'])} фраз → {a.out}" +
          (f"; ХУК: фраза #{hook['hook_index']} (повторов: {len(hook['repeats'])})" if hook else "; хук не выявлен"))


if __name__ == "__main__":
    _main()
