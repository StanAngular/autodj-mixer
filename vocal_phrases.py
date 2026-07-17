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

def fetch_lyrics(title: str, artist: str, cache_path: str = "") -> str:
    """Автопоиск текста песни: кэш → AZLyrics → ''.
    cache_path: если задан, читаем кэш и пишем результат туда.
    Без внешних зависимостей (только urllib stdlib)."""
    if cache_path and os.path.exists(cache_path):
        try:
            return open(cache_path, encoding="utf-8").read().strip()
        except Exception:
            pass
    import re
    import urllib.request
    def _az(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())
    url = f"https://www.azlyrics.com/lyrics/{_az(artist)}/{_az(title)}.html"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        m = re.search(
            r'<!-- Usage of azlyrics\.com content.*?-->\s*(.*?)\s*<!-- MxM banner',
            html, re.S)
        if m:
            text = re.sub(r"<[^>]+>", "", m.group(1))
            text = re.sub(r"\r\n|\r", "\n", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) >= 50:
                if cache_path:
                    try:
                        with open(cache_path, "w", encoding="utf-8") as f:
                            f.write(text)
                    except Exception:
                        pass
                return text
    except Exception:
        pass
    return ""


def transcribe_chorus_words(vocals: np.ndarray, sr: int, segments: list[dict],
                             asr: str = "groq", language: str = "",
                             vocal_labels: tuple = ("chorus", "verse", "bridge")) -> list[dict]:
    """ASR только по вокальным сегментам (chorus/verse/bridge из A1F).
    Намного чище полного трека: 15с хоруса vs 200с целиком.
    language: ISO-639-1 код -- критически важен для неангл. треков.
    Fallback на полный transcribe_words если segments пустые."""
    if not segments:
        return transcribe_words(vocals, sr, asr=asr, language=language)
    vocal_segs = [(s["start"], s["end"]) for s in segments
                  if s.get("label", "") in vocal_labels]
    if not vocal_segs:
        return transcribe_words(vocals, sr, asr=asr, language=language)
    all_words: list[dict] = []
    for seg_start_s, seg_end_s in vocal_segs:
        s_samp = int(seg_start_s * sr)
        e_samp = min(int(seg_end_s * sr), len(vocals))
        if e_samp <= s_samp + sr // 2:          # < 0.5с — пропуск
            continue
        chunk = vocals[s_samp:e_samp]
        words = transcribe_words(chunk, sr, asr=asr, language=language)
        for w in words:                          # сдвиг к абсолютным позициям
            w["start"] += s_samp
            w["end"] += s_samp
        all_words.extend(words)
    return all_words


def trim_to_phrase_start(words: list[dict], span_start: int, span_end: int,
                          query: str) -> tuple[int, int]:
    """Обрезать найденный ASR-спан к границам запроса: trim и с начала, и с конца.
    Начало -- до первого слова запроса, конец -- после последнего слова запроса.
    Убирает "хвост" предыдущей строки и лишние слова после фразы (напр. "духмяні").
    Универсально: fuzzy-match по нормализованным словам query."""
    from difflib import SequenceMatcher
    q_words = _norm_text(query)
    if not q_words:
        return span_start, span_end
    span_words = [w for w in words if w["start"] >= span_start and w["end"] <= span_end]
    if not span_words:
        return span_start, span_end
    # trim начала: первое слово запроса (fuzzy, т.к. ASR может слить "А липи" → "Алиби")
    first_q = q_words[0]
    new_start = span_start
    for w in span_words:
        wn = _norm_text(w["word"])
        if wn and SequenceMatcher(None, first_q, wn[0]).ratio() >= 0.4:
            new_start = w["start"]
            break
    # trim конца: последнее слово запроса
    last_q = q_words[-1]
    new_end = span_end
    for w in reversed(span_words):
        wn = _norm_text(w["word"])
        if wn and SequenceMatcher(None, last_q, wn[0]).ratio() >= 0.5:
            new_end = w["end"]
            break
    return new_start, new_end


def transcribe_words(vocals: np.ndarray, sr: int, asr: str = "groq",
                      language: str = "") -> list[dict]:
    """Word-level распознавание ВСЕГО вокала → [{word, start, end}] (сэмплы, абсолютные).
    asr='groq' — Groq Whisper API (env GROQ_API_KEY, verbose_json + word timestamps).
    language: ISO-639-1 ('uk', 'en', ...). Без него Whisper auto-detect, что даёт ошибки
    для неанглийских треков (напр. украинский→русский транскрипт).
    Ошибки → [] (слова опциональны)."""
    try:
        import soundfile as sf
        # даунсемпл до 16kHz моно (Whisper не нужно стерео/высокий SR)
        mono = vocals.mean(1).astype("float32") if vocals.ndim == 2 else vocals.astype("float32")
        if sr != 16000:
            import scipy.signal
            ds = int(sr / 16000)
            mono = scipy.signal.resample(mono, max(1, len(mono) // ds))
            sr = 16000
        dur = len(mono) / sr
        max_chunk = 90.0                                   # 90с × 16kHz × 2byte ≈ 2.88MB, безопасно
        orig_sr = int(len(vocals) / dur) if dur else 44100
        if asr == "groq":
            all_words = []
            for chunk_start in range(0, int(dur), int(max_chunk)):
                ch_e = min(chunk_start + max_chunk, dur)
                seg = mono[int(chunk_start * sr):int(ch_e * sr)]
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    sf.write(f.name, seg, sr)
                    path = f.name
                try:
                    words = _groq_words(path, language=language) or []
                except Exception:
                    words = []
                if words:
                    for w in words:
                        w["start"] = int((float(w["start"]) + chunk_start) * orig_sr)
                        w["end"] = int((float(w["end"]) + chunk_start) * orig_sr)
                    all_words.extend(words)
                os.unlink(path)
            return [{"word": w["word"].strip(), "start": w["start"],
                     "end": w["end"]} for w in all_words if w.get("word")]
        else:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, mono, sr)
                path = f.name
            r = subprocess.run(asr.replace("{wav}", path).split(),
                               capture_output=True, text=True, timeout=600)
            words = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
            os.unlink(path)
            return [{"word": w["word"].strip(), "start": int(float(w["start"]) * sr),
                     "end": int(float(w["end"]) * sr)} for w in words if w.get("word")]
    except Exception:
        return []


def _groq_words(wav_path: str, language: str = "") -> list[dict]:
    """Groq Whisper: verbose_json + word timestamps. env GROQ_API_KEY.
    language: ISO-639-1 код ('uk', 'en', 'ru'...). Пустой = auto-detect (хуже для неангл. яз).
    Прокси socks5://127.0.0.1:40000 если доступен (VPS за блокировками)."""
    import requests
    try:
        from dotenv import load_dotenv
        here = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(os.path.join(here, ".env"))
    except Exception:
        pass
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        # Fallback: parse .env manually (when dotenv not installed)
        for env_path in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
            os.path.join(os.path.expanduser("~"), "claudeclaw-build", ".env"),
        ]:
            try:
                with open(env_path, "r") as _f:
                    for _line in _f:
                        _line = _line.strip()
                        if _line.startswith("GROQ_API_KEY=") and not _line.startswith("#"):
                            key = _line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
                if key:
                    break
            except Exception:
                pass
    if not key:
        return []
    data: dict = {"model": "whisper-large-v3", "response_format": "verbose_json",
                  "timestamp_granularities[]": "word"}
    if language:
        data["language"] = language
    kw = {
        "headers": {"Authorization": f"Bearer {key}"},
        "data": data,
        "timeout": 300,
    }
    # проверка доступности прокси (не блокирующая — просто пробуем)
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    proxy_ok = s.connect_ex(("127.0.0.1", 40000)) == 0
    s.close()
    if proxy_ok:
        kw["proxies"] = {"https": "socks5://127.0.0.1:40000"}
    with open(wav_path, "rb") as fh:
        kw["files"] = {"file": (os.path.basename(wav_path), fh, "audio/wav")}
        r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions", **kw)
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



# ─── P71: сверка с каноническим текстом песни (лирикой) ─────────────────────

def align_lyrics(words: list[dict], lyrics: str) -> tuple[list[dict], float]:
    """Скорректировать ASR-слова каноническим текстом (найденным в интернете агентом):
    выравнивание последовательностей (difflib), совпавшие/заменённые слова получают
    КАНОНИЧЕСКОЕ написание (тайминги ASR сохраняются). → (слова', покрытие 0..1). Чистая.
    Повышает точность find_text_span: цитаты ищутся по каноническим словам."""
    from difflib import SequenceMatcher
    canon = _norm_text(lyrics)
    asr = [_norm_text(w["word"]) for w in words]
    flat = [(t[0], i) for i, t in enumerate(asr) if t]
    if not canon or not flat:
        return words, 0.0
    sm = SequenceMatcher(None, [w for w, _ in flat], canon, autojunk=False)
    out = [dict(w) for w in words]
    matched = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal", "replace") and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                out[flat[i1 + k][1]]["word"] = canon[j1 + k]
                matched += 1
    return out, round(matched / max(1, len(canon)), 3)



# ─── P72: транскрипт для агента + слово-юниты ────────────────────────────────

def transcript_lines(words: list[dict], sr: int, bar_len: int = 0,
                     gap_ms: float = 700) -> list[dict]:
    """Полный текст СТРОКАМИ (разрыв по паузам между словами > gap_ms) с таймингами и
    барами. Агент ЧИТАЕТ это, понимает смысл → осмысленно строит vocal-plan. Чистая."""
    if not words:
        return []
    gap = int(sr * gap_ms / 1000)
    lines, cur = [], [words[0]]
    for w in words[1:]:
        if w["start"] - cur[-1]["end"] > gap:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    lines.append(cur)
    out = []
    for ln in lines:
        s0, e0 = ln[0]["start"], ln[-1]["end"]
        d = {"text": " ".join(w["word"] for w in ln),
             "start_s": round(s0 / sr, 2), "end_s": round(e0 / sr, 2)}
        if bar_len:
            d["start_bar"] = round(s0 / bar_len, 1)
        out.append(d)
    return out


def find_word_span(words: list[dict], word: str, occurrence: int = 1):
    """k-е вхождение СЛОВА → (start, end) в сэмплах | None. Для слово-статтера
    («я, я, я» — универсально для любого трека). Чистая."""
    target = _norm_text(word)
    if len(target) != 1:
        return None
    n = 0
    for w in words:
        if _norm_text(w["word"]) == target:
            n += 1
            if n == occurrence:
                return (w["start"], w["end"])
    return None


# ─── P74: аудит обрывов фраз в рендере ────────────────────────────────────────

def audit_vocal_phrases(wav_path: str, lyrics: str = "", sr: int = 44100,
                         asr: str = "groq", language: str = "",
                         min_phrase_s: float = 0.5) -> list[dict]:
    """Обнаружение обрывов/незаконченных фраз в рендере.
    Запускает ASR → строит фразы по паузам → сверяет с lyrics.
    Фразы которые обрываются посреди строки лирики = TRUNCATED.
    Возвращает [{time_s, text, status, issue}]. Чистая (I/O через ASR)."""
    import soundfile as sf
    audio, file_sr = sf.read(wav_path, dtype="float32", always_2d=True)
    if file_sr != sr:
        sr = file_sr
    words = transcribe_words(audio, sr, asr=asr, language=language)
    if not words:
        return [{"time_s": 0, "text": "", "status": "error", "issue": "ASR вернул 0 слов"}]
    if lyrics:
        words, _ = align_lyrics(words, lyrics)
    # строки по паузам
    lines = transcript_lines(words, sr, gap_ms=600)
    # разбить lyrics на строки для сверки
    lyr_lines = [l.strip() for l in lyrics.split("\n") if l.strip()] if lyrics else []
    results: list[dict] = []
    for ln in lines:
        text = ln["text"]
        t = ln["start_s"]
        # проверка: есть ли эта строка целиком в lyrics?
        status = "ok"
        issue = ""
        if lyr_lines:
            # fuzzy-match к ближайшей строке лирики
            from difflib import SequenceMatcher
            best_ratio, best_line = 0.0, ""
            for ll in lyr_lines:
                r = SequenceMatcher(None, text.lower(), ll.lower()).ratio()
                if r > best_ratio:
                    best_ratio, best_line = r, ll
            if best_ratio >= 0.4:
                # проверить: текст покрывает всю строку или обрыв?
                text_words = _norm_text(text)
                line_words = _norm_text(best_line)
                if len(text_words) < len(line_words) * 0.7:
                    status = "truncated"
                    issue = f"обрыв: {len(text_words)}/{len(line_words)} слов от «{best_line}»"
            else:
                status = "unmatched"
                issue = f"не найдено в лирике (best ratio {best_ratio:.2f})"
        results.append({"time_s": t, "text": text, "status": status, "issue": issue})
    return results


def _main():
    ap = argparse.ArgumentParser(description="P69: фразы вокала + хук + (опц.) слова")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--demix-dir", required=True)
    ap.add_argument("--transcript", action="store_true",
                    help="P72: полный текст строками (агент читает и думает) вместо phrases.json")
    ap.add_argument("--lyrics-file", default="", help="канонический текст песни (сверка ASR)")
    ap.add_argument("--asr-cmd", default="", help="CLI ASR, '{wav}' → файл фразы (напр. 'whisper-cli {wav}')")
    ap.add_argument("--audit", default="", help="P74: аудит рендера — WAV файл для проверки обрывов фраз")
    ap.add_argument("--asr-language", default="", help="ISO-639-1 код языка для ASR")
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--out", default="phrases.json")
    a = ap.parse_args()
    if a.audit:
        lyr = ""
        if a.lyrics_file and os.path.exists(a.lyrics_file):
            lyr = open(a.lyrics_file, encoding="utf-8").read()
        results = audit_vocal_phrases(a.audit, lyrics=lyr, sr=a.sr,
                                       language=a.asr_language)
        for r in results:
            icon = {"ok": "✓", "truncated": "✂", "unmatched": "?", "error": "✗"}.get(r["status"], "?")
            m = int(r["time_s"] // 60)
            s = r["time_s"] % 60
            print(f"  {icon} {m:02d}:{s:05.2f}  «{r['text'][:60]}»")
            if r["issue"]:
                print(f"          {r['issue']}")
        n_trunc = sum(1 for r in results if r["status"] == "truncated")
        print(f"\nИтого: {len(results)} фраз, {n_trunc} обрывов")
        return
    rep = phrases_report(a.wav, a.demix_dir, a.sr, a.asr_cmd)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    hook = rep["hook"]
    print(f"{len(rep['phrases'])} фраз → {a.out}" +
          (f"; ХУК: фраза #{hook['hook_index']} (повторов: {len(hook['repeats'])})" if hook else "; хук не выявлен"))


if __name__ == "__main__":
    _main()