"""Machine-wide render slots shared by all agents (11 GB RAM: 3 parallel renders already killed the bot once)."""
import fcntl, os, time
from contextlib import contextmanager
SLOTS = int(os.environ.get("AUTODJ_RENDER_SLOTS", "2"))

@contextmanager
def render_slot(wait_s=3600, poll=5):
    t0 = time.time()
    while True:
        for k in range(SLOTS):
            p = f"/tmp/autodj-render-{k}.lock"; fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o666)
            try: os.chmod(p, 0o666)
            except PermissionError: pass
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd); continue
            try:
                yield k; return
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
        if time.time() - t0 > wait_s: raise TimeoutError("no free render slot")
        print("render slots busy, waiting...", flush=True); time.sleep(poll)
