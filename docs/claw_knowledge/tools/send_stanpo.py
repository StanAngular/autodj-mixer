"""send an mp3 to Telegram with performer StanPo + ID3 tags (until P111 is applied to the engine)"""
import sys, os, json, uuid, subprocess, urllib.request
path, title, genre = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "")
# 2026-11-16 hard gate: the render next to this mp3 reported a silent layer (a muted part of the arrangement) -> do not send. FORCE_SEND=1 overrides.
_sj = os.path.splitext(path)[0] + ".summary.json"
if os.path.exists(_sj) and not os.environ.get("FORCE_SEND"):
    _s = json.load(open(_sj))
    if _s.get("gate_failed") or _s.get("silent_layers"): print("REFUSED: silent layers / failed gate in", _sj, _s.get("gate_failed") or _s.get("silent_layers"), "(FORCE_SEND=1 to override)"); sys.exit(2)
tagged = os.path.join(os.path.dirname(path), f"StanPo - {title}.mp3".replace("/", "-"))
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-c", "copy", "-metadata", f"title={title}", "-metadata", "artist=StanPo", "-metadata", f"genre={genre}", tagged], check=True)
tok, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["ALLOWED_CHAT_ID"]; b = uuid.uuid4().hex
f = lambda k, v: f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
body = b"".join([f("chat_id", chat), f("title", title), f("performer", "StanPo"),
                 f"--{b}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{os.path.basename(tagged)}\"\r\nContent-Type: audio/mpeg\r\n\r\n".encode(),
                 open(tagged, "rb").read(), f"\r\n--{b}--\r\n".encode()])
r = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendAudio", data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
print("sent" if json.load(urllib.request.urlopen(r, timeout=600)).get("ok") else "failed")
