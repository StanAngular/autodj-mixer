"""Experiment memory + blind comparison (P109, ТЗ ChatGPT+Gemini 2026-10-21, sections 6 and 10).
One experiment = one musical question, 3-5 variants that differ in ONE musical idea, rendered under identical
conditions, labelled with random letters. Stored as  <root>/<EXP-id>/experiment.json  + variant audio, plus one line
per experiment in <root>/log.jsonl. Nothing is overwritten: a new idea is a new variant or a new experiment.

Gemini judges in two rounds (random order, then the order rotated by n//2); a ranking counts only where the two
rounds agree (Gemini has a measured position bias: on 2026-10-21 it chose «№2» in both rounds although №2 was a
different clip each time). Стас's vote is stored separately and always outranks the model."""
import datetime, json, os, re, string
import numpy as np

ROOT = os.environ.get("AUTODJ_EXPERIMENTS", "/home/cclaw/claudeclaw-build/workspace/music/experiments")

PROMPT = """Ты независимый музыкальный критик и слушаешь реально звучащие аудиофрагменты. Жанр и задача: {task}
Сравни варианты по МУЗЫКАЛЬНОЙ привлекательности, а не по технической корректности. Порядок отрывков случайный.
{guide}
Для каждого варианта (по букве из его подписи):
1. насколько выразительна и узнаваема основная музыкальная идея;
2. насколько интересен грув и взаимодействие инструментов;
3. есть ли собственная идентичность;
4. естественно ли развивается фраза;
5. что привлекает внимание, а что мешает;
6. хочется ли слушать дальше.
Не выбирай победителя за громкость, яркость, плотность или количество нот. Не придумывай то, чего не слышно; если варианты близки, так и скажи.
В конце строго две строки:
РЕЙТИНГ: <буквы от лучшего к худшему через >, например C > A > B>
ГИПОТЕЗА: <одна проверяемая причина, почему лучший лучше, и один конкретный следующий эксперимент>"""

class Experiment:
    def __init__(self, name, question, root=ROOT, seed=None):
        self.id = datetime.datetime.now().strftime("EXP-%Y%m%d-%H%M%S-") + re.sub(r"\W+", "_", name)[:30]
        self.dir = os.path.join(root, self.id); os.makedirs(self.dir, exist_ok=True); self.root = root
        self.data = {"id": self.id, "name": name, "question": question, "created": datetime.datetime.now().isoformat(timespec="seconds"),
                     "variants": {}, "labels": {}, "gemini": [], "votes": [], "chosen": None}
        self.rng = np.random.default_rng(seed); self.save()
    @classmethod
    def load(cls, path):
        self = cls.__new__(cls); self.dir = path if os.path.isdir(path) else os.path.dirname(path); self.root = os.path.dirname(self.dir)
        self.data = json.load(open(os.path.join(self.dir, "experiment.json"))); self.id = self.data["id"]; self.rng = np.random.default_rng()
        return self
    def save(self):
        tmp = os.path.join(self.dir, "experiment.json.tmp"); json.dump(self.data, open(tmp, "w"), ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(self.dir, "experiment.json"))
    def add(self, vid, audio_path, diff, params=None):
        assert vid not in self.data["variants"], f"variant {vid} exists: never overwrite, add a new one"
        self.data["variants"][vid] = {"audio": os.path.relpath(audio_path, self.dir), "diff": diff, "params": params or {}}; self.save()
    def blind(self):
        """random letters -> variant ids (stored; the evaluator never sees ids or diffs)"""
        ids = list(self.data["variants"]); letters = list(string.ascii_uppercase[:len(ids)])
        self.data["labels"] = dict(zip(letters, [ids[i] for i in self.rng.permutation(len(ids))])); self.save()
        return self.data["labels"]
    def audio(self, letter):
        return os.path.join(self.dir, self.data["variants"][self.data["labels"][letter]]["audio"])

    def judge(self, task, ask=None, genre=None, guide_path=None):
        """two Gemini rounds; ask(list_of_(letter, path), prompt) -> text. Returns the agreed ranking (may be partial)."""
        from .teacher import guide_text, _call, _audio_part
        letters = sorted(self.data["labels"]); n = len(letters)
        p = PROMPT.format(task=task, guide=guide_text(genre, guide_path))
        if ask is None:
            def ask(items, pr):
                parts = []
                for L, f in items: parts += [{"text": f"Вариант {L}:"}, _audio_part(f)]
                return _call(parts + [{"text": pr}])[1]
        perm = [letters[i] for i in self.rng.permutation(n)]; sh = max(1, n // 2); rounds = []
        for order in (perm, perm[sh:] + perm[:sh]):
            t = ask([(L, self.audio(L)) for L in order], p); t = t.replace("*", "")       # «**РЕЙТИНГ:**» markdown
            m = re.findall(r"РЕЙТИНГ:\s*([A-Z](?:\s*>\s*[A-Z])*)", t); rank = re.findall(r"[A-Z]", m[-1]) if m else []
            hyp = (re.findall(r"ГИПОТЕЗА:\s*(.+)", t) or [""])[-1].strip()
            rounds.append({"order": order, "ranking": rank, "hypothesis": hyp, "text": t})
        r1, r2 = rounds[0]["ranking"], rounds[1]["ranking"]
        pos = lambda r, L: r.index(L) if L in r else None
        agreed_best = r1[0] if r1 and r2 and r1[0] == r2[0] else None
        borda = {L: sum((n - 1 - pos(r, L)) for r in (r1, r2) if pos(r, L) is not None) for L in letters}
        stable = [L for L in letters if pos(r1, L) is not None and pos(r2, L) is not None and abs(pos(r1, L) - pos(r2, L)) <= 1]
        res = {"rounds": rounds, "agreed_best": agreed_best, "borda": borda, "stable_letters": stable,
               "position_bias_suspect": bool(r1 and r2 and r1[0] != r2[0] and perm.index(r1[0]) == (perm[sh:] + perm[:sh]).index(r2[0]))}
        self.data["gemini"].append(res); self.save(); self._log()
        return res

    def rejudge(self, i=-1):
        """recompute the agreement of a stored judgement from its saved texts (e.g. after a parser fix)"""
        g = self.data["gemini"][i]; texts = iter([r["text"] for r in g["rounds"]])
        orders = [r["order"] for r in g["rounds"]]; self.data["gemini"].pop(i)
        saved = self.rng; self.rng = type("R", (), {"permutation": lambda _s, n: [sorted(self.data["labels"]).index(L) for L in orders[0]]})()
        try: return self.judge("", ask=lambda items, p: next(texts))
        finally: self.rng = saved

    def vote(self, letter, who="stas", note=""):
        vid = self.data["labels"][letter]
        self.data["votes"].append({"who": who, "letter": letter, "variant": vid, "note": note, "at": datetime.datetime.now().isoformat(timespec="seconds")})
        if who == "stas": self.data["chosen"] = vid                            # the human ear decides
        self.save(); self._log(); return vid

    def _log(self):
        g = self.data["gemini"][-1] if self.data["gemini"] else {}
        line = {"id": self.id, "question": self.data["question"], "variants": {k: v["diff"] for k, v in self.data["variants"].items()},
                "gemini_best": self.data["labels"].get(g.get("agreed_best")) if g.get("agreed_best") else None,
                "chosen": self.data["chosen"], "votes": self.data["votes"]}
        with open(os.path.join(self.root, "log.jsonl"), "a") as f: f.write(json.dumps(line, ensure_ascii=False) + "\n")
