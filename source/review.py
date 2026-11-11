"""📝 Review: questions the Teacher got wrong / partly right / ran out of time on, plus ⭐ starred ones.

One file per lesson: lessons/<id>/review.json  ->  {"version": 1, "items": {key: entry}}
An entry stays in the list until it's mastered ("I get it now", or a correct 🔁 second chance) or deleted.
"""
import datetime
import hashlib
import json
import os
import threading

import engine as E

FILE = "review.json"


def key_for(question):
    return hashlib.sha1(E.norm_q(question or "").encode()).hexdigest()[:16]


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def visible(e):
    """Shown in the Review tab (and can come back as a second chance)."""
    return not e.get("mastered") and (e.get("missed", 0) > 0 or e.get("timeouts", 0) > 0 or e.get("starred"))


def kind_of(e):
    """missed / timeout / starred: what the row's badge says (the most recent miss wins)."""
    if e.get("missed", 0) or e.get("timeouts", 0):
        return "timeout" if e.get("last") == "TIMEOUT" else "missed"
    return "starred"


class Review:
    def __init__(self, library):
        self.lib = library
        self.lock = threading.RLock()
        self.cache = {}
        self.rev = 1                     # bumps on every change (the UI reloads the list)

    # ---------------------------------------------------------- files

    def _load(self, lid, title=None, sessions_dir=None, by_name=None):
        if lid in self.cache:
            return self.cache[lid]
        data = self.lib.read_json(lid, FILE)
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            data = {"version": 1, "items": {}}
            if title and sessions_dir:
                self._import_old(data, title, sessions_dir, by_name or {})
            if data["items"]:
                self.lib.write_json(lid, FILE, data)
        self.cache[lid] = data
        return data

    def _import_old(self, data, title, sessions_dir, by_name):
        """First time: bring in this lesson's old timed-out questions from sessions/unanswered.jsonl."""
        try:
            with open(os.path.join(sessions_dir, "unanswered.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("lesson") != title or not r.get("question"):
                        continue
                    k = key_for(r["question"])
                    e = data["items"].setdefault(k, {
                        "key": k, "question": r["question"], "judge_q": r["question"], "answer": r.get("answer", ""),
                        "explanation": "", "more": [], "type": r.get("card", ""), "mine": "", "sid": by_name.get(r.get("student")),
                        "name": r.get("student", ""), "missed": 0, "timeouts": 0, "starred": False, "mastered": False,
                        "first": r.get("when") or now_iso()})
                    e["timeouts"] += 1
                    e["last"], e["when"] = "TIMEOUT", r.get("when") or now_iso()
        except OSError:
            pass

    def _save(self, lid):
        self.lib.write_json(lid, FILE, self.cache[lid])
        self.rev += 1

    # ---------------------------------------------------------- recording

    def record(self, lid, it, student, verdict, judge_q, **ctx):
        """A card was answered (verdict CORRECT/PARTLY/WRONG) or timed out (verdict TIMEOUT)."""
        if not lid:
            return None
        with self.lock:
            data = self._load(lid, **ctx)
            k = it.get("orig_key") if it.get("type") == "second_chance" and it.get("orig_key") else key_for(it["question"])
            e = data["items"].get(k)
            if it.get("type") == "second_chance" and e:
                # 🔁 the second chance is about the original question: right = learned, otherwise one more miss
                if verdict == "CORRECT":
                    e.update(mastered=True, starred=False, mastered_at=now_iso(), mine=it.get("teacher_answer") or e.get("mine"))
                else:
                    e["missed" if verdict != "TIMEOUT" else "timeouts"] = e.get("missed" if verdict != "TIMEOUT" else "timeouts", 0) + 1
                    e.update(last=verdict, when=now_iso(), mine=it.get("teacher_answer") or e.get("mine"), mastered=False)
                self._save(lid)
                return k
            if verdict == "CORRECT" and not e:
                return None                              # nothing to review
            if not e:
                e = data["items"][k] = {"key": k, "missed": 0, "timeouts": 0, "starred": False, "mastered": False,
                                        "more": [], "first": now_iso()}
            e.update(question=it["question"], judge_q=judge_q, answer=it.get("answer", ""), type=it.get("type", ""),
                     label=it.get("label", ""), sid=it.get("sid"), name=student.get("name", ""),
                     emoji=student.get("emoji", ""), choices=it.get("choices"),
                     claims=[{"name": c.get("name"), "text": c.get("text")} for c in it.get("claims") or []] or None)
            if it.get("explanation"):
                e["explanation"] = it["explanation"]
            if verdict in ("WRONG", "PARTLY", "TIMEOUT"):
                e["missed" if verdict != "TIMEOUT" else "timeouts"] += 1
                e.update(last=verdict, when=now_iso(), mastered=False, mine=it.get("teacher_answer") or "")
            else:                                        # correct this time: keep it only if starred
                e["mine"] = it.get("teacher_answer") or e.get("mine", "")
            self._save(lid)
            return k

    def set_explanation(self, lid, k, text):
        with self.lock:
            data = self._load(lid)
            e = data["items"].get(k)
            if e and text and not e.get("explanation"):
                e["explanation"] = text
                self._save(lid)

    def star(self, lid, it, student, on, judge_q):
        """⭐ from the answer panel during class."""
        with self.lock:
            data = self._load(lid)
            k = key_for(it["question"])
            e = data["items"].get(k)
            if not e:
                if not on:
                    return {"ok": True}
                e = data["items"][k] = {"key": k, "missed": 0, "timeouts": 0, "mastered": False, "more": [],
                                        "first": now_iso(), "when": now_iso(), "last": it.get("verdict") or ""}
                e.update(question=it["question"], judge_q=judge_q, answer=it.get("answer", ""), type=it.get("type", ""),
                         label=it.get("label", ""), sid=it.get("sid"), name=student.get("name", ""),
                         emoji=student.get("emoji", ""), explanation=it.get("explanation") or "",
                         mine=it.get("teacher_answer") or "", choices=it.get("choices"),
                         claims=[{"name": c.get("name"), "text": c.get("text")} for c in it.get("claims") or []] or None)
            e["starred"] = bool(on)
            if on:
                e["mastered"] = False
            if not on and not e.get("missed") and not e.get("timeouts"):
                del data["items"][k]                     # unstarred and never missed: nothing left to keep
            self._save(lid)
            return {"ok": True, "key": k}

    # ---------------------------------------------------------- the Review tab

    def entries(self, lid, **ctx):
        with self.lock:
            data = self._load(lid, **ctx)
            out = []
            for e in data["items"].values():
                if visible(e):
                    d = dict(e, kind=kind_of(e), lesson_id=lid)
                    out.append(d)
            out.sort(key=lambda e: e.get("when") or e.get("first") or "", reverse=True)
            return out

    def count(self, lid, **ctx):
        if not lid:
            return 0
        with self.lock:
            return sum(1 for e in self._load(lid, **ctx)["items"].values() if visible(e))

    def update(self, lid, k, **kw):
        with self.lock:
            data = self._load(lid)
            e = data["items"].get(k)
            if not e:
                return {"ok": False, "error": "That question isn't in the review list any more."}
            if "starred" in kw:
                e["starred"] = bool(kw["starred"])
            if kw.get("mastered"):
                e.update(mastered=True, starred=False, mastered_at=now_iso())
            if "more" in kw:
                e.setdefault("more", []).append(kw["more"])
            if "simple" in kw:
                e["simple"] = kw["simple"]
            if kw.get("simple_failed"):
                e["simple_tries"] = e.get("simple_tries", 0) + 1
            self._save(lid)
            return {"ok": True, "entry": dict(e, kind=kind_of(e), lesson_id=lid), "visible": visible(e)}

    def delete(self, lid, keys):
        with self.lock:
            data = self._load(lid)
            n = 0
            for k in keys:
                if data["items"].pop(k, None) is not None:
                    n += 1
            if n:
                self._save(lid)
            return {"ok": True, "deleted": n}

    def get(self, lid, k):
        with self.lock:
            return self._load(lid)["items"].get(k)

    def forget_lesson(self, lid):
        with self.lock:
            self.cache.pop(lid, None)
            self.rev += 1

    def needs_simple(self, lid, **ctx):
        """Entries still waiting for their one-sentence simple explanation (newest first)."""
        with self.lock:
            out = [e for e in self._load(lid, **ctx)["items"].values()
                   if visible(e) and not e.get("simple") and e.get("simple_tries", 0) < 3]
            out.sort(key=lambda e: e.get("when") or e.get("first") or "", reverse=True)
            return out

    def mastered_dates(self, lid, **ctx):
        """When questions were learned (I get it now / a right second chance), for the home screen."""
        with self.lock:
            return [e["mastered_at"] for e in self._load(lid, **ctx)["items"].values()
                    if e.get("mastered") and e.get("mastered_at")]

    def pool(self, lid, **ctx):
        """Entries that can come back as a 🔁 second chance."""
        with self.lock:
            return [e for e in self._load(lid, **ctx)["items"].values() if visible(e) and e.get("sid")]
