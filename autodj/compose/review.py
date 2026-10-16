"""Second ear: Gemini listens to the finished mp3 with our measurements in the prompt (without them it invents things)
and must answer in a fixed format so the scores can be tracked from track to track."""
import json, os, re, time, urllib.request

PROMPT = """Ты опытный продюсер и звукорежиссёр электронной музыки. Послушай трек целиком и дай жёсткий профессиональный разбор.
Трек: «{title}». Задумка: {story}. Тональность: {key}. Темп {bpm} BPM, длительность {dur}.
Части (начало-конец, мин): {sections}
Громкость слоёв (RMS дБ): {layers}
Наши замеры: верх 3-14 кГц {high_db} дБ к общему, саб {sub}%, лимитер {lim} дБ, скачок частей {jump} дБ. (Свою оценку гармоничности дай сам, на слух, без подсказок.)
Голос (сек): {voice}
Ответь по-русски, с таймкодами:
1. Топ-6 проблем: элемент, таймкод, почему, как исправить (дБ, частоты, замена звука).
2. ОТДЕЛЬНО: гармоничность. Попадают ли слои друг в друга по высоте и строю? Есть ли расстроенные инструменты, слои «мимо нот», биения, грязные интервалы? Где именно.
3. Какие элементы выпирают или не сочетаются.
4. Что звучит хорошо.
Говори только о том, что действительно слышишь; если не уверен, так и скажи.
Последней строкой строго: ОЦЕНКИ: палитра=N; сведение=N; грув=N; гармония=N; строй=N; аранжировка=N (N от 1 до 10)"""

def _upload(path, key):
    data = open(path, "rb").read()
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={key}", method="POST",
        data=json.dumps({"file": {"display_name": os.path.basename(path)}}).encode(),
        headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start", "X-Goog-Upload-Header-Content-Length": str(len(data)),
                 "X-Goog-Upload-Header-Content-Type": "audio/mpeg", "Content-Type": "application/json"})
    url = urllib.request.urlopen(req).headers["X-Goog-Upload-URL"]
    f = json.load(urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST",
        headers={"X-Goog-Upload-Command": "upload, finalize", "X-Goog-Upload-Offset": "0", "Content-Length": str(len(data))})))["file"]
    for _ in range(40):
        if f.get("state") == "ACTIVE": break
        time.sleep(3); f = json.load(urllib.request.urlopen(f"https://generativelanguage.googleapis.com/v1beta/{f['name']}?key={key}"))
    return f["uri"]

def review(mp3, summ, info, meta, out_txt, models=("gemini-3-flash-preview", "gemini-2.5-flash")):
    key = os.environ.get("GOOGLE_API_KEY")
    if not key: return {"error": "no GOOGLE_API_KEY"}
    bar = 240 / summ["bpm"]
    p = PROMPT.format(title=summ["title"], story=meta.get("story", "-"), key=meta.get("key", "-"), bpm=summ["bpm"], dur=f"{summ['dur_s'] // 60}:{summ['dur_s'] % 60:02d}",
                      sections=", ".join(f"{a * bar / 60:.1f}-{b * bar / 60:.1f} {n}" for a, b, n, _ in info["plan"]),
                      layers=", ".join(f"{k} {v}" for k, v in info.get("layers_db", {}).items()), high_db=summ["high_db"], sub=round(summ["sub_mean"] * 100),
                      lim=summ["master"]["limiter_max_db"], jump=summ["jump_db"], clash=round(info.get("clash_ratio", 0) * 100, 1),
                      voice=", ".join(f"{t:.0f}" for t, _ in info.get("voice", [])) or "нет")
    uri = _upload(mp3, key)
    body = {"contents": [{"parts": [{"file_data": {"mime_type": "audio/mpeg", "file_uri": uri}}, {"text": p}]}]}
    for m in models:
        try:
            req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            t = json.load(urllib.request.urlopen(req, timeout=500))["candidates"][0]["content"]["parts"][-1]["text"]
            open(out_txt, "w").write(m + "\n" + t)
            sc = re.search(r"ОЦЕНКИ:(.*)", t)
            scores = {k.strip(): int(v) for k, v in re.findall(r"([а-яё]+)\s*=\s*(\d+)", sc.group(1))} if sc else {}
            return {"model": m, "scores": scores, "file": out_txt}
        except Exception as e:
            err = str(e); time.sleep(5)
    return {"error": err}
