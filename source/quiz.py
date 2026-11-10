"""AI Classroom - quiz mode.

Students (Byte, Pixel, Mochi, Ribbit, Whiskers) write question CARDS about their own section, in their own
personality, together with the correct answer. Card types: explain_why, what_if, compare, fill_blank,
pick_one (3 buttons), spot_mistake, plus gold challenge cards that mix two topics.
After the Teacher answers: explanation reveal, verdict, a personality reaction, and "Explain more" on demand.
"""
import datetime
import hashlib
import json
import os
import random
import re
import threading
import time

import engine as E
import lessons as L

ACTIVE = ("queued", "answered")      # statuses still shown in the feed
WARM = "warm"                        # cards written while the app is idle, before Start
BLANK = "_____"
TYPE_LABELS = {"explain_why": "🧠 Explain why", "what_if": "🔀 What if…", "compare": "⚖️ Compare",
               "fill_blank": "✍️ Fill the blank", "pick_one": "🔘 Pick one", "spot_mistake": "🕵️ Spot the mistake",
               "lightning": "⚡ Lightning", "whos_right": "🗳️ Who's right?",
               "challenge": "⭐ Challenge", "silver": "🥈 Silver", "second_chance": "🔁 Second chance",
               "streak": "🔥 Streak card", "infected": "🧟 Infected", "boss": "👑 Zombie Boss"}
SPECIAL = ("challenge", "silver", "second_chance", "streak", "infected", "boss")   # never picked by weight
TWO_CHOICE = ("pick_one", "whos_right")               # answered with buttons, graded instantly
YES_NO = re.compile(r"^(can|is|are|am|do|does|did|will|would|should|could|has|have|had|was|were|isn'?t|aren'?t|don'?t)\b", re.I)
STOP = set("a an the is are was were do does did of to in on for and or with what why how which who when where "
           "it its it's that this can you your my be by as at from so if like".split())


# ------------------------------------------------------------------ helpers

def _content_words(s):
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", s.lower()).split() if w not in STOP and len(w) > 2}


def similar(q1, q2, threshold=0.6):
    """Near-duplicates (mostly the same important words)."""
    a, b = _content_words(q1), _content_words(q2)
    return bool(a and b) and len(a & b) / len(a | b) >= threshold


def gives_away(question, answer):
    """True if the question already contains the answer's main keyword (the **bold** part)."""
    ql = " %s " % re.sub(r"[^a-z0-9]+", " ", question.lower())
    for kw in re.findall(r"\*\*(.+?)\*\*", answer):
        k = re.sub(r"[^a-z0-9]+", " ", kw.lower()).strip()
        if len(k) > 2 and (" %s " % k in ql):
            return True
    return False


GENERIC = set("because which they them their there these those than then also very more most much many some any each "
              "other into onto about over under between while when after before during only just make makes made help "
              "helps used use uses using called call thing things way ways need needs get gets got good better best like "
              "really keep keeps lets let allow allows able lot lots both different same important happen happens "
              "would could should will must might every one two three first next work works working go goes".split())


def parse_study(out):
    """TITLE / KEY POINTS / QUESTIONS from a student's reading of its part."""
    if not out:
        return "", [], []
    if "</think>" in out:
        out = out.rsplit("</think>", 1)[1]
    if "<think>" in out:
        return "", [], []
    title = re.sub(r"\*\*|__|[\"'#]", "", _field(out, "TITLE") or "").strip(" .:")
    m_pts = re.search(r"^[\s*#]*KEY\s*POINTS?\**\s*:?\**\s*$", out, re.I | re.M)
    m_qs = re.search(r"^[\s*#]*QUESTIONS?\**\s*:?\**\s*$", out, re.I | re.M)
    pts_txt = out[m_pts.end():m_qs.start() if m_qs and m_qs.start() > m_pts.end() else len(out)] if m_pts else ""
    qs_txt = out[m_qs.end():] if m_qs else ""
    bullet = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
    points = [E.tidy_markdown(m.group(1)) for m in map(bullet.match, pts_txt.splitlines()) if m]
    echo = re.compile(r"<|fact (from|in) the text|key ?points?|one fact per|simple words|bold the|most important (word|facts)|covering the whole", re.I)
    points = [p for p in points if len(p) > 8 and not p.endswith("?") and not echo.search(p)]
    if re.search(r"<|title|words|what the text", title, re.I):
        title = ""
    qs = []
    for line in qs_txt.splitlines():
        if not bullet.match(line) and not line.strip().endswith("?"):
            continue
        q = re.sub(r"\*\*|__", "", E.clean_planned(line))
        if "<" in q or "</" in line:
            continue
        if q.endswith("?") and len(q) > 10 and not YES_NO.match(q):
            qs.append(q)
    return title[:60], points, qs


# a card that copied the format instructions instead of filling them in ("<under 20 words, ends with ?>")
BROKEN = re.compile(r"<\s*[a-z]|[a-z]\s*>|\.\.\.\s*$|^\s*\.\.\.|\b(under \d+ words|ends with \?|one short sentence|1 or 2 short "
                    r"sentences|said like a student|must be correct|from (your|my) notes\)|the correct (answer|option|explanation)"
                    r"\s*$|believable but wrong|exactly (two|three|four|these) lines|in \*\*bold\*\*)\b", re.I)
# the student's thinking spilled into an explanation ("But we need to follow instructions…")
LEAK = re.compile(r"\b(we need to (write|produce|output|answer|explain|follow|craft|give|make)|we must (write|bold|follow|answer)|"
                  r"the user (asks|wants|says|gives)|follow (the|these) instructions|the instructions|"
                  r"let'?s (re-?read|think|check|craft|write|see|count|aim|plan|make sure)|we need (at most|at least|about) \d|the task (is|says)|exact format|format exactly|"
                  r"the teacher \(a child\)|write only|under \d+ words)\b|<[a-z/]", re.I)


def first_sentences(text, n):
    """Keep answers and explanations short: the first n sentences."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z*\"'(])", (text or "").strip())
    return E.tidy_markdown(" ".join(parts[:n]).strip())


def clean_notes(out):
    if not out:
        return ""
    if "</think>" in out:
        out = out.rsplit("</think>", 1)[1]
    if "<think>" in out:
        return ""
    t = re.sub(r"^```\w*\s*|```\s*$", "", out.strip(), flags=re.M).strip()
    t = "\n".join(E.tidy_markdown(l.rstrip()) for l in t.splitlines())
    # drop any line where the student talks about the task instead of writing notes ("Let's aim for 6 points")
    t = "\n".join(l for l in t.splitlines() if not LEAK.search(l) and not re.match(r"\s*(key (concepts|points) from|okay|so,? )", l, re.I))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if not t.startswith("#"):
        t = "## " + t
    return t[:5000]


def load_types():
    """Read the '## name' sections of the question_types skill."""
    text = E.read_skill("question_types")
    types = {}
    for m in re.finditer(r"^##\s*(\w+)\s*\n(.*?)(?=^##\s*\w+|\Z)", text, re.M | re.S):
        types[m.group(1).strip()] = m.group(2).strip()
    return types


def _field(text, name):
    # accepts "QUESTION: x", "**Question:** x", "**QUESTION**: x", "- A) x" ...
    sep = r"[:\-]?" if name.endswith((")", ".")) else r"[:\-]"
    # the label's own closing ** is only eaten when a space follows, so "**ANSWER:** **socket**" keeps its bold
    m = re.search(r"^[\s\-*#>]*\**\s*%s\s*\**\s*%s\s*(?:\*\*(?=\s))?\s*(.+?)\s*$" % (name, sep), text, re.I | re.M)
    return E.tidy_markdown(m.group(1).strip()) if m else None


def parse_card(text, ctype):
    """Turn the model's reply into a card dict, or None if it doesn't follow the format."""
    if not text:
        return None
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        return None
    text = re.sub(r"_{3,}", "{BLANK}", text)                 # keep blanks safe from the __underline__ rules
    answer = _field(text, "ANSWER")
    if not answer:
        return None
    card = {"answer": answer}
    if ctype == "fill_blank":
        # the app makes the blank itself: the student gives a sentence + keyword
        sentence = re.sub(r"\*\*|__|\*", "", _field(text, "SENTENCE") or _field(text, "QUESTION") or "")
        keyword = re.sub(r"\*\*|__|\*", "", _field(text, "KEYWORD") or "").strip(" .\"'")
        if not sentence or not keyword or len(keyword.split()) > 3:
            return None
        pat = re.compile(r"(?<!\w)%s(?:e?s)?(?!\w)" % re.escape(keyword), re.I)    # "HDD" also hides "HDDs"
        if not pat.search(sentence):
            return None
        card["question"] = pat.sub("{BLANK}", sentence)
        card["keyword"] = keyword
        card["answer"] = "**%s**: %s" % (keyword, re.sub(r"^\**%s\**\s*[:,\-—]?\s*" % re.escape(keyword), "", answer, flags=re.I))
        return card
    if ctype == "spot_mistake":
        card["question"] = _field(text, "STATEMENT")
    else:
        card["question"] = _field(text, "QUESTION")
    if not card["question"]:
        return None
    if ctype == "whos_right":
        right, wrong = _field(text, "RIGHT"), _field(text, "WRONG")
        if not right or not wrong:
            return None
        card["right"], card["wrong"] = right, wrong
    if ctype == "pick_one":
        opts = [_field(text, "%s\\)" % L) or _field(text, "%s\\." % L) or _field(text, "\\(%s\\)" % L) for L in "ABC"]
        correct = (_field(text, "CORRECT") or "").strip().upper()[:1]
        if not all(opts) or correct not in "ABC" or not correct:
            return None
        card["choices"] = [o.strip() for o in opts]
        card["correct"] = "ABC".index(correct)
    return card


# ------------------------------------------------------------------ quiz engine

class Quiz(E.Engine):
    def __init__(self):
        self.items = []
        self.item_next = 1
        self.generating = {}
        self.started_at = None
        self.last_gen_sid = None
        self.last_gen_start = 0
        self.last_type = None
        self.made = 0
        self.inflight = {}           # port -> requests running (2 slots per student server)
        self.recent_reacts = {}
        self.streak = 0
        self.best_streak = 0
        self.retried = set()         # questions already brought back as a second chance
        self.answered_n = 0          # answered this class (for meteors and zombies)
        self.last_meteor_at = -999
        self.zombie = None           # the zombie crawling right now (one at a time)
        self.last_zombie_at = -999
        self.zombie_next = 1
        self.lesson_token = 0        # bumps when another lesson is picked: work for the old lesson is thrown away
        self.prepare = None          # the "students are reading the lesson" loading screen
        self.notes_rev = 0
        self.notes_writing = None    # (lesson id, student id) while a student writes notes
        self.off_lesson = 0          # cards thrown away for using things that aren't in the lesson
        super().__init__()
        threading.Thread(target=self._warmup, daemon=True).start()
        if self.lesson_id:
            threading.Thread(target=self._notes_worker, args=(self.lesson_id, self.lesson_token), daemon=True).start()

    def preparing(self):
        return bool(self.prepare and self.prepare["stage"] not in ("done", "error"))

    def _warmup(self):
        """While no class is running, write the first 2 cards ahead so Start is instant."""
        while True:
            time.sleep(1.5)
            if self.running or not self.sections or self.preparing():
                continue
            with self.lock:
                ready = sum(1 for i in self.items if i["status"] == "ready")
                busy = any(self.generating.values())
            cands = [s for s in self.sections if self.online.get(s)]
            if ready >= 2 or busy or not cands:
                continue
            sid = random.choice([s for s in cands if s != self.last_gen_sid] or cands)
            self.last_gen_sid = sid
            self.generating[sid] = True
            self._make_item(sid, WARM)

    # ------------------------------------------------------------ prompts / ports

    def _qpersona(self, sid):
        sec = self.sections.get(sid, {})
        st = self.students[sid]
        return E.fill(E.read_skill("student_persona"), name=st["name"], emoji=st.get("emoji", ""),
                      personality=st.get("personality") or "friendly and curious", lesson=self.lesson,
                      topic=sec.get("title", ""), section=sec.get("content", ""))

    def _port_for(self, sid, any_port):
        own = self.students[sid]["port"]
        if not any_port or self.inflight.get(own, 0) < 2:
            return own
        # all students run the same model, so a quick job can go to whichever server is free
        ports = [s["port"] for k, s in self.students.items() if self.online.get(k)]
        return min(ports or [own], key=lambda p: (self.inflight.get(p, 0), p != own))

    def _ask(self, sid, task, budget, any_port=False, max_tokens=None):
        port = self._port_for(sid, any_port)
        self.inflight[port] = self.inflight.get(port, 0) + 1
        self.typing[sid] = self.typing.get(sid, 0) + 1
        try:
            return E.llm(self.host, port,
                         [{"role": "system", "content": self._qpersona(sid)}, {"role": "user", "content": task}],
                         max_tokens or int(self.cfg["max_tokens_chat"]), int(self.cfg["timeout_seconds"]), budget)
        finally:
            self.inflight[port] = max(0, self.inflight.get(port, 1) - 1)
            self.typing[sid] = max(0, self.typing.get(sid, 1) - 1)

    def _plan_questions(self, sid, bank):
        port = self.students[sid]["port"]           # count background planning as a busy slot
        self.inflight[port] = self.inflight.get(port, 0) + 1
        try:
            return super()._plan_questions(sid, bank)
        finally:
            self.inflight[port] = max(0, self.inflight.get(port, 1) - 1)

    # ------------------------------------------------------------ session

    def start(self):
        with self.lock:
            if self.running:
                return {"ok": False, "error": "Class is already running."}
            if self.preparing():
                return {"ok": False, "error": "The students are still reading the lesson…"}
            self.load_lesson()
            if not self.sections:
                return {"ok": False, "error": "Pick a lesson first: open the ☰ sidebar, then 📚 Lessons."}
            self.gen += 1
            g = self.gen
            self.session += 1
            self.running = True
            # keep the cards written ahead while the app was idle, so the first question shows up right away
            self.items = [i for i in self.items if i["status"] == "ready" and i["sid"] in self.sections
                          and i["type"] not in SPECIAL]
            self.typing = {}
            self.fact_used = {}
            self.made = 0
            self.streak = self.best_streak = 0
            self.answered_n, self.last_meteor_at = 0, -999
            self.zombie, self.last_zombie_at = None, -999
            self.started_at = time.time()
            self.last_gen_start = 0
            stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.log_path = os.path.join(self.folder("sessions"), "class_%s.jsonl" % stamp)
        self._log({"type": "class_start", "lesson": self.lesson,
                   "topics": {sid: self.topic(sid) for sid in self.sections}})
        threading.Thread(target=self._producer, args=(g,), daemon=True).start()
        return {"ok": True}

    def stop(self):
        with self.lock:
            if not self.running:
                return {"ok": False, "error": "Class is not running."}
            self.running = False
            self.gen += 1
            self.generating = {}
            self.typing = {}
        stats = self.stats()
        self._log({"type": "class_stop", "stats": stats})
        return {"ok": True, "stats": stats}

    def stats(self):
        with self.lock:
            items = list(self.items)
        done = [i for i in items if i["status"] in ("answered", "done")]
        return {"answered": len(done), "timeout": sum(1 for i in items if i["status"] == "timeout"),
                "correct": sum(1 for i in done if i.get("verdict") == "CORRECT"),
                "partly": sum(1 for i in done if i.get("verdict") == "PARTLY"),
                "wrong": sum(1 for i in done if i.get("verdict") == "WRONG"),
                "help": sum(len(i.get("more", [])) for i in items),
                "challenges": sum(1 for i in done if i.get("challenge") and i.get("verdict") == "CORRECT"),
                "redeemed": sum(1 for i in done if i["type"] == "second_chance" and i.get("verdict") == "CORRECT"),
                "best_streak": self.best_streak}

    def _apply_streak(self, it):
        """Correct = +1 (a 🔥 streak card = +3), wrong = back to 0, partly = no change."""
        v = it.get("verdict")
        if v == "CORRECT":
            self.streak += (int(self.cfg.get("streak_card_bonus") or 3) if it["type"] == "streak" else
                            int(self.cfg.get("boss_bonus") or 5) if it["type"] == "boss" else 1)
        elif v == "WRONG":
            self.streak = 0
        self.best_streak = max(self.best_streak, self.streak)

    def _missed(self):
        """Questions the Teacher got wrong / partly / ran out of time on, this class first, then earlier classes."""
        pool = [{"sid": i["sid"], "question": self._question_for_judge(i), "answer": i["answer"]}
                for i in self.items if i["type"] not in ("second_chance",)
                and (i["status"] == "timeout" or i.get("verdict") in ("WRONG", "PARTLY"))]
        if not pool:
            by_name = {s["name"]: k for k, s in self.students.items()}
            try:
                with open(os.path.join(self.folder("sessions"), "unanswered.jsonl"), encoding="utf-8") as f:
                    for line in f:
                        r = json.loads(line)
                        sid = by_name.get(r.get("student"))
                        if r.get("lesson") == self.lesson and sid in self.sections:
                            pool.append({"sid": sid, "question": r["question"], "answer": r["answer"]})
            except (OSError, ValueError):
                pass
        return [p for p in pool if p["question"] not in self.retried]

    # ------------------------------------------------------------ making cards

    def _releaser(self, g):
        """Show one ready card every question_interval_seconds, all class long (endless feed).
        Cards are written ahead of time, so the interval stays fixed even when a card is slow or rejected."""
        interval = float(self.cfg.get("question_interval_seconds") or 10)
        first = int(self.cfg.get("first_questions") or 1)
        max_visible = int(self.cfg.get("max_visible") or 9)
        released = 0
        was_full = False
        next_at = time.time()
        while self._alive(g):
            time.sleep(0.1)
            self._zombie_tick()
            with self.lock:
                waiting = sum(1 for i in self.items if i["status"] in ACTIVE)
            if waiting >= max_visible:
                was_full = True                              # feed is full: keep writing ahead, show nothing new
                continue
            instant = was_full                               # a slot just freed up: the next card appears right away
            if not instant and time.time() < next_at:
                continue
            with self.lock:
                hot = self.streak >= 3
                ready_cards = [i for i in self.items if i["status"] == "ready"]
                # a 🔥 streak card jumps the line while the streak is hot, and waits while it isn't
                ready = next((i for i in ready_cards if i["type"] == "streak"), None) if hot else None
                ready = ready or next((i for i in ready_cards if i["type"] != "streak"), None)
                if not ready:
                    continue                                 # nothing ready yet: release as soon as one is
                ready.update(status="queued", ts=time.time(), instant=instant)
                released += 1
            was_full = False
            next_at = time.time() + (1.5 if released < first else interval)   # never bunch up after a late card

    def _producer(self, g):
        """Keep cards written ahead (hidden, config hidden_ahead) so a new one can appear instantly."""
        threading.Thread(target=self._releaser, args=(g,), daemon=True).start()
        while self._alive(g):
            time.sleep(0.3)
            with self.lock:
                busy = [s for s, v in self.generating.items() if v]
                ahead = sum(1 for i in self.items if i["status"] == "ready")
                last_card_sid = self.items[-1]["sid"] if self.items else None
            if ahead + len(busy) >= int(self.cfg.get("hidden_ahead") or 10) or len(busy) >= int(self.cfg["max_parallel_generation"]):
                continue
            cands = [s for s in self.sections if self.online.get(s) and not self.generating.get(s)]
            for avoid in (self.last_gen_sid, last_card_sid):     # spread topics: no same section twice in a row
                if len(cands) > 1 and avoid in cands:
                    cands.remove(avoid)
            if not cands:
                continue
            sid = random.choice(cands)
            self.made += 1
            # which kind of card? special ones first, otherwise a normal type by weight
            kind, extra = None, None
            with self.lock:
                streak_ready = any(i["type"] == "streak" and i["status"] in ("ready", "queued") for i in self.items)
            sc_every = int(self.cfg.get("second_chance_every") or 0)
            ch_every = int(self.cfg.get("challenge_every") or 0)
            if self.streak >= 3 and not streak_ready and random.random() < float(self.cfg.get("streak_card_chance") or 0):
                kind = "streak"
            elif sc_every and self.made % sc_every == 0 and self._missed():
                extra = random.choice(self._missed())
                kind, sid = "second_chance", extra["sid"]            # the student who asked it the first time
                self.retried.add(extra["question"])
            elif ch_every and self.made % ch_every == 0 and len(self.sections) > 1:
                kind = "challenge"                                   # gold wins when both land on the same card
            elif int(self.cfg.get("silver_every") or 0) and self.made % int(self.cfg["silver_every"]) == 0:
                kind = "silver"
            if self.generating.get(sid):
                continue
            self.last_gen_sid, self.last_gen_start = sid, time.time()
            self.generating[sid] = True
            threading.Thread(target=self._make_item, args=(sid, g, kind, extra), daemon=True).start()

    def _pick_type(self):
        weights = dict(self.cfg.get("question_type_weights") or {})
        types = load_types()
        weights = {t: w for t, w in weights.items() if t in types and w > 0 and t not in SPECIAL}
        if len(weights) > 1 and self.last_type in weights:
            del weights[self.last_type]                     # never the same type twice in a row
        if not weights:
            return "explain_why"
        t = random.choices(list(weights), weights=list(weights.values()))[0]
        self.last_type = t
        return t

    def _make_item(self, sid, g, kind=None, extra=None, budget=None):
        tok = self.lesson_token
        budget = self.cfg.get("thinking_budget_cards", 0) if budget is None else budget
        try:
            types = load_types()
            other = None
            if kind == "challenge":
                ctype = "challenge"
                other = random.choice([s for s in self.sections if s != sid])
                idea = "how %s and %s work together or differ" % (self.topic(sid), self.topic(other))
            elif kind == "second_chance":
                ctype, idea = "second_chance", extra["question"]
            elif kind in ("streak", "silver"):
                ctype, idea = kind, self._take_question(sid) or self._next_fact(sid)
            else:
                ctype = self._pick_type()
                idea = self._take_question(sid) or self._next_fact(sid)
            rule = E.fill(types.get(ctype, ""), topic=self.topic(sid),
                          other_topic=self.topic(other) if other else "",
                          other_notes=self.sections.get(other, {}).get("content", "") if other else "",
                          orig_question=(extra or {}).get("question", ""), orig_answer=(extra or {}).get("answer", ""))
            task = E.fill(E.read_skill("make_question"), topic=self.topic(sid), idea=idea,
                          type_name=TYPE_LABELS.get(ctype, ctype).split(" ", 1)[-1], type_rule=rule)
            card = None
            for attempt in range(3):
                t = task if not attempt else task + "\n\nYour last card broke a rule. Write a DIFFERENT card this time."
                card = self._finish_card(parse_card(self._ask(sid, t, budget), ctype), ctype)
                if card:
                    break
            if not card or not (g == WARM or self._alive(g)) or tok != self.lesson_token:
                return
            with self.lock:
                if ctype != "second_chance" and any(similar(i["question"], card["question"]) for i in self.items):
                    return                                   # no (near-)duplicates in one class
                st = self.students[sid]
                if ctype == "whos_right":                    # two students, one is right; random order
                    rival = random.choice([s for s in self.students if s != sid and self.online.get(s)] or
                                          [s for s in self.students if s != sid])
                    claims = [{"sid": sid, "text": card.pop("right")}, {"sid": rival, "text": card.pop("wrong")}]
                    random.shuffle(claims)
                    for c in claims:
                        c.update(name=self.students[c["sid"]]["name"], emoji=self.students[c["sid"]].get("emoji", ""))
                    card["claims"] = claims
                    card["correct"] = next(k for k, c in enumerate(claims) if c["sid"] == sid)
                item = dict(card, id=self.item_next, sid=sid, name=st["name"], emoji=st.get("emoji", ""),
                            type=ctype, label=TYPE_LABELS.get(ctype, ""), challenge=ctype == "challenge",
                            other=self.topic(other) if other else "", idea=idea, status="ready", ts=time.time(),
                            teacher_answer="", verdict=None, reaction=None, more=[])
                self.item_next += 1
                self.items.append(item)
            # write the explanation now, in the background, so it's ready the moment the Teacher answers
            threading.Thread(target=self._auto_explain, args=(item,), daemon=True).start()
            self._log({"type": "question", "id": item["id"], "student": sid, "card": ctype,
                       "question": item["question"], "answer": item["answer"], "choices": item.get("choices")})
        finally:
            self.generating[sid] = False

    def _finish_card(self, card, ctype):
        """Clean the text and reject cards that break the rules."""
        if not card:
            return None
        q = card["question"].replace("{BLANK}", "\x00")
        q = E.clean(q, self.names, limit=200)
        q = re.sub(r"\*\*\*|__|(?<![\w*])\*(?!\*)|(?<!\*)\*(?![\w*])", "", q).strip()   # only **bold** stays
        q = E.keep_key_styles(q, self.vocab, max_spans=1).strip()              # one bold lesson word at most
        q = q.replace("\x00", BLANK)                                          # put the blank back last
        a = card["answer"].replace("{BLANK}", BLANK)
        a = re.sub(r"\s*,?\s*(as (noted|mentioned|said|written) )?(in|from|according to) (my|the|your) notes\b", "", a, flags=re.I)
        a = E.clean(a, self.names, strip_greeting=False, limit=360)
        if not q or not a:
            return None
        fields = [q, a] + list(card.get("choices") or []) + [card.get(k) or "" for k in ("right", "wrong", "keyword")]
        if any(BROKEN.search(f) for f in fields if f) or LEAK.search(a):
            return None                                   # copied the format instructions / thinking leaked in
        if not self._grounded(a, card.get("keyword")):
            self.off_lesson += 1                          # uses things that aren't in the lesson: write another one
            return None
        a = E.keep_key_styles(a, self.vocab)
        if ctype == "fill_blank":
            if BLANK not in q:
                return None
            kw = (card.get("keyword") or "").lower()
            if kw in STOP or kw in GENERIC or len(kw) < 3 or (" " not in kw and kw.endswith("ly")):
                return None                                  # the hidden word must be a real lesson term
        elif ctype == "spot_mistake":
            q = q.rstrip("?").strip()
            if not q.endswith((".", "!")):
                q += "."
        else:
            if "?" not in q:
                return None
            q = q[:q.index("?") + 1]
            if YES_NO.match(q):
                return None                                  # no yes/no questions
        if ctype == "lightning" and gives_away(q, a):
            return None                                  # a quick-fact question must not contain its answer
        if ctype not in ("pick_one", "fill_blank", "whos_right"):
            # explanations may repeat the question's term: just don't bold it (the NEW key words stay bold)
            ql = " %s " % E._norm_words(q)
            a = re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(1) if " %s " % E._norm_words(m.group(1)) in ql else m.group(0), a)
        a = first_sentences(a, 3 if ctype in ("challenge", "streak", "boss") else 2)
        card = dict(card, question=q, answer=a)
        if ctype == "whos_right":
            r = re.sub(r"\*\*|__", "", E.clean(card["right"], self.names, limit=150))
            w = re.sub(r"\*\*|__", "", E.clean(card["wrong"], self.names, limit=150))
            if not r or not w or similar(r, w) and r.lower() == w.lower():
                return None
            if len(_content_words(r) & _content_words(w)) == 0 and len(_content_words(q) & _content_words(r)) == 0:
                return None                                  # the two claims aren't about the same question
            card["right"], card["wrong"] = r, w
            if len(_content_words(a) & (_content_words(r) | _content_words(q))) < 2:
                card["answer"] = r                           # the reason must be about the right claim
        if ctype == "pick_one":
            card["choices"] = [re.sub(r"^(bold|underline|italic)\s+", "", re.sub(r"\*\*|__", "", E.clean(c, self.names, limit=90)),
                                      flags=re.I) for c in card["choices"]]
            if not all(card["choices"]) or len({c.lower() for c in card["choices"]}) < 3:
                return None
            if any(len(c.split()) > 9 for c in card["choices"]):
                return None                                  # options must be short (and look alike)
            # the ticked option must be the one the explanation agrees with
            norm = [" %s " % E._norm_words(c) for c in card["choices"]]
            keys = [E._norm_words(k) for k in re.findall(r"\*\*(.+?)\*\*", a)]
            named = {i for i in range(3) for k in keys if k and (" %s " % k in norm[i] or norm[i].strip() in " %s " % k)}
            if len(named) == 1:
                card["correct"] = named.pop()                # the answer's bold key word names exactly one option
            else:
                aw = _content_words(a)
                scores = [len(_content_words(c) & aw) for c in card["choices"]]
                best = max(range(3), key=lambda i: scores[i])
                if best != card["correct"] and scores[best] > scores[card["correct"]]:
                    return None                              # the explanation points at another option
        return card

    @staticmethod
    def _from_text(s, padded, need=0.5):
        """Most of the important words of s appear in the text (padded = " normalised text ")."""
        ws = [w for w in _content_words(re.sub(r"\*\*|__", "", s)) if w not in GENERIC and not w.isdigit()]
        if not ws:
            return True
        hit = sum(1 for w in ws if any(" %s " % v in padded for v in (w, w.rstrip("s"), w + "s", re.sub(r"(es|ing|ed)$", "", w))))
        return hit / len(ws) >= need

    def _grounded(self, answer, keyword=None):
        """Does the answer come from the lesson? Its bold key words (or the fill-in word) must be lesson words,
        and most of its other important words must appear in the lesson text."""
        vocab = " %s " % self.vocab
        def known(phrase):
            p = E._norm_words(phrase)
            return bool(p) and any(" %s " % v in vocab for v in (p, p.rstrip("s"), p + "s", re.sub(r"(es|ing|ed)$", "", p)))
        keys = [k for k in re.findall(r"\*\*(.+?)\*\*", answer) if len(k) < 40] + ([keyword] if keyword else [])
        if keys and not any(known(k) for k in keys):
            return False
        words = [w for w in _content_words(re.sub(r"\*\*|__", "", answer)) if w not in GENERIC and not w.isdigit()]
        if len(words) < 3:
            return True
        return sum(1 for w in words if known(w)) / len(words) >= 0.5

    # ------------------------------------------------------------ lessons

    def lessons(self):
        act = self.library.active()
        out = []
        for m in self.library.list():
            out.append({k: m.get(k) for k in ("id", "title", "color", "status", "error", "kind_label", "words", "parts",
                                              "created", "studied", "source_name")})
            out[-1]["active"] = m["id"] == act
        return {"rev": self.library.rev, "lessons": out}

    def lesson_notes(self, lid):
        meta = self.library.meta(lid)
        if not meta:
            return {"ok": False, "error": "Lesson not found."}
        notes = self.library.notes(lid)
        parts, seen = [], set()
        for sid in sorted(self.students):
            sec = self.library.section(lid, sid) or {}
            if not sec or sec.get("part") in seen:       # short lessons: students share a part, show it once
                continue
            seen.add(sec.get("part"))
            st = self.students[sid]
            parts.append({"sid": sid, "name": st["name"], "emoji": st.get("emoji", ""), "part": sec.get("part"),
                          "title": sec.get("title") or "Part %s" % sec.get("part"), "md": notes.get(str(sid))})
        w = self.notes_writing
        return {"ok": True, "id": lid, "title": meta.get("title"), "status": meta.get("status"), "parts": parts,
                "active": lid == self.library.active(), "studied": bool(meta.get("studied")),
                "writing": w[1] if w and w[0] == lid else None}

    def import_file(self, name, b64):
        return self.library.import_file(name, b64)

    def import_text(self, text, title=None):
        return self.library.import_text(text, title)

    def rename_lesson(self, lid, title):
        r = self.library.rename(lid, title)
        if r.get("ok") and lid == self.lesson_id:
            self.lesson = title.strip()[:60]
        return r

    def delete_lesson(self, lid):
        if lid == self.library.active() and (self.running or self.preparing()):
            return {"ok": False, "error": "That lesson is in use right now. Stop the class first."}
        r = self.library.delete(lid)
        if r.get("ok") and lid == self.lesson_id:
            with self.lock:
                self.lesson_token += 1
                self.items = []
                self.load_lesson()
        return r

    def select_lesson(self, lid):
        """Use this lesson for class: the class clears, the students read it (loading screen), then questions
        come only from it."""
        meta = self.library.meta(lid)
        if not meta:
            return {"ok": False, "error": "Lesson not found."}
        if meta.get("status") == "importing":
            return {"ok": False, "error": "Still opening that file, one moment…"}
        if meta.get("status") != "ready":
            return {"ok": False, "error": meta.get("error") or "That lesson couldn't be read."}
        with self.lock:
            if self.preparing():
                return {"ok": False, "error": "The students are already reading a lesson."}
            was = self.running
            self.running = False
            self.gen += 1
            self.generating, self.typing, self.items, self.zombie = {}, {}, [], None
            self.lesson_token += 1
            tok = self.lesson_token
            self.library.set_active(lid)
            self.load_lesson()
            self.prepare = {"id": lid, "title": meta.get("title"), "stage": "reading", "pct": 0, "started": time.time(),
                            "msg": "The students are reading the lesson…", "was_running": was,
                            "students": {str(s): 0 for s in self.sections}, "cards": 0}
        if was:
            self._log({"type": "class_stop", "reason": "lesson changed", "stats": self.stats()})
        threading.Thread(target=self._prepare, args=(lid, tok), daemon=True).start()
        return {"ok": True}

    def _prep_pct(self):
        P = self.prepare
        if not P:
            return
        study = sum(P["students"].values()) / max(1, len(P["students"]))
        P["pct"] = round(min(99, study * 80 + (20 if P["cards"] else 0)))

    def _raw_ask(self, sid, system, task, budget, max_tokens):
        """A request on the student's own server that doesn't need its persona (reading, notes)."""
        port = self.students[sid]["port"]
        self.inflight[port] = self.inflight.get(port, 0) + 1
        try:
            return E.llm(self.host, port, [{"role": "system", "content": system}, {"role": "user", "content": task}],
                         max_tokens, int(self.cfg["timeout_seconds"]), budget)
        finally:
            self.inflight[port] = max(0, self.inflight.get(port, 1) - 1)

    def _prepare(self, lid, tok):
        P = self.prepare
        try:
            workers = [threading.Thread(target=self._study, args=(lid, sid, tok), daemon=True) for sid in self.sections]
            for w in workers:
                w.start()
            for w in workers:
                w.join()
            if tok != self.lesson_token:
                return
            with self.lock:
                self.load_lesson()
            if not self.sections:
                P.update(stage="error", msg="The students couldn't read that lesson.")
                return
            # the first questions, written now so class can start right away
            online = [s for s in self.sections if self.online.get(s)]
            random.shuffle(online)
            writers = online[:2]
            P.update(stage="cards", cards_started=time.time(), writing=writers,
                     msg=" and ".join(self.students[s]["name"] for s in writers) +
                     (" are" if len(writers) > 1 else " is") + " writing the first questions…")
            def first_card(sid):
                self.generating[sid] = True
                self._make_item(sid, WARM, budget=0)          # no thinking: the loading screen stays short
                P["cards"] = sum(1 for i in self.items if i["status"] == "ready")
                self._prep_pct()
            cw = [threading.Thread(target=first_card, args=(s,), daemon=True) for s in writers]
            for w in cw:
                w.start()
            # one ready card is enough to start; the other one (and the rest) keep coming during class
            deadline = time.time() + 90
            while time.time() < deadline and any(w.is_alive() for w in cw) and tok == self.lesson_token:
                if any(i["status"] == "ready" for i in self.items):
                    break
                time.sleep(0.2)
            wait = float(self.cfg.get("min_loading_seconds") or 0) - (time.time() - P["started"])
            if wait > 0:
                time.sleep(wait)
            if tok != self.lesson_token:
                return
            self.library.update_meta(lid, studied=True, last_used=datetime.datetime.now().isoformat(timespec="seconds"))
            self._log({"type": "lesson_ready", "lesson": self.lesson, "seconds": round(time.time() - P["started"], 1),
                       "topics": {sid: self.topic(sid) for sid in self.sections}})
            P.update(stage="done", pct=100, msg="Ready!")
            threading.Thread(target=self._notes_worker, args=(lid, tok), daemon=True).start()
        except Exception as e:                            # noqa: BLE001 - shown on the loading screen
            P.update(stage="error", msg="Something went wrong: %s" % e)

    def _study(self, lid, sid, tok):
        """The student reads its part (piece by piece if it's long) and writes its plan: a title, key points and
        first questions -> sN.json + sN_questions.json."""
        P = self.prepare
        key = str(sid)
        try:
            d = self.library.section(lid, sid)
            if not d:
                return
            if d.get("studied") and d.get("content"):
                return
            st = self.students[sid]
            ps = L.pieces(d.get("source") or "")
            title, points, qs = "", [], []
            system = ("You are %s, a careful student. You read the text you are given and use ONLY what it says." % st["name"])
            for k, piece in enumerate(ps):
                if tok != self.lesson_token:
                    return
                n_points = max(4, min(10, L.words(piece) // 35))
                task = E.fill(E.read_skill("study_part"), lesson=self.lesson, name=st["name"], piece=k + 1,
                              pieces=len(ps), text=piece, points=n_points, questions=5 if k == 0 else 3)
                for attempt in range(2):
                    t, pts, q = parse_study(self._raw_ask(sid, system, task, self.cfg.get("thinking_budget_study", 0),
                                                          int(self.cfg.get("max_tokens_study") or 900)))
                    if pts:
                        break
                padded = " %s " % E._norm_words(piece + " " + self.lesson)
                title = title or t
                points += [p for p in pts if self._from_text(p, padded)]
                qs += [x for x in q if self._from_text(x, padded, 0.4)]
                P["students"][key] = (k + 1) / len(ps)
                self._prep_pct()
            if not points:                                # the student couldn't summarise: use the text's sentences
                sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", d.get("source") or "") if len(s.strip()) > 25]
                points = sents[:10]
            if len(points) > 40:                          # long parts: keep 40 points spread over the whole part
                step = len(points) / 40
                points = [points[int(i * step)] for i in range(40)]
            points = [E.keep_key_styles(p, self.vocab) for p in points]
            content = "\n".join("- " + p for p in points)
            title = title or "Part %s" % d.get("part", sid)
            if tok != self.lesson_token:
                return
            d.update(title=title, content=content, studied=True)
            self.library.save_section(lid, sid, d)
            seen, bank_qs = set(), []
            for q in qs:
                if E.norm_q(q) not in seen:
                    seen.add(E.norm_q(q))
                    bank_qs.append({"q": q, "asked": 0, "results": []})
            h = hashlib.sha1((title + content).encode()).hexdigest()[:12]
            self.library.write_json(lid, "s%d_questions.json" % sid,
                                    {"student": sid, "topic": title, "section_hash": h, "questions": bank_qs})
        finally:
            if P and key in P["students"]:
                P["students"][key] = 1
                self._prep_pct()

    def _notes_worker(self, lid, tok):
        """In the background (also during class), each student writes simple notes on its part, one at a time,
        whenever its server has a free slot."""
        try:
            done_parts = set()
            for sid in sorted(self.students):
                if tok != self.lesson_token:
                    return
                sec = self.library.section(lid, sid) or {}
                notes = self.library.notes(lid)
                if not sec or sec.get("part") in done_parts:
                    continue
                if str(sid) in notes and not LEAK.search(notes[str(sid)]):
                    done_parts.add(sec.get("part"))
                    continue                              # (notes with leaked thinking get written again)
                port = self.students[sid]["port"]
                for _ in range(600):                      # wait (up to 10 min) for the student to be online and free
                    if tok != self.lesson_token:
                        return
                    if self.online.get(sid) and self.inflight.get(port, 0) < 2:
                        break
                    time.sleep(1)
                src = sec.get("source") or ""
                text = src if L.words(src) <= 2200 else re.sub(r"\*\*", "", sec.get("content") or "")
                task = E.fill(E.read_skill("write_notes"), lesson=self.lesson, topic=sec.get("title") or "this part",
                              text=text)
                self.notes_writing = (lid, sid)
                md = ""
                for _ in range(2):
                    md = clean_notes(self._raw_ask(sid, "You are %s, a kind student who writes clear notes for a child. "
                                                        "You use ONLY the text you are given." % self.students[sid]["name"],
                                                   task, self.cfg.get("thinking_budget_notes", 0),
                                                   int(self.cfg.get("max_tokens_notes") or 1600)))
                    if len(md) > 60 and not LEAK.search(md):
                        break
                if md and tok == self.lesson_token:
                    self.library.save_note(lid, sid, md)
                    done_parts.add(sec.get("part"))
                    self.notes_rev += 1
        finally:
            if self.notes_writing and self.notes_writing[0] == lid:
                self.notes_writing = None
                self.notes_rev += 1

    # ------------------------------------------------------------ teacher actions

    def _item(self, item_id):
        return next((i for i in self.items if i["id"] == int(item_id)), None)

    def answer(self, item_id, text):
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "Type an answer first."}
        with self.lock:
            it = self._item(item_id)
            if not it or it["status"] != "queued":
                return {"ok": False, "error": "That question is no longer open."}
            if it.get("judging") or it.get("infecting"):
                return {"ok": False, "error": "Hold on a second…"}
            if it["type"] == "boss":                         # 👑 one part at a time
                it["judging"] = True
                threading.Thread(target=self._answer_boss, args=(it, text), daemon=True).start()
                return {"ok": True, "boss": True, "part": it["part"]}
            if it["type"] == "pick_one":
                idx = "ABC".find(text.strip().upper()[:1])
                it["verdict"] = "CORRECT" if idx == it["correct"] else "WRONG"
                text = "%s) %s" % ("ABC"[idx], it["choices"][idx]) if idx >= 0 else text
            elif it["type"] == "whos_right":
                idx = "AB".find(text.strip().upper()[:1])
                it["verdict"] = "CORRECT" if idx == it["correct"] else "WRONG"
                text = "%s is right" % it["claims"][idx]["name"] if idx >= 0 else text
            it.update(status="answered", teacher_answer=text, answered_at=time.time())
            if it["verdict"]:
                self._apply_streak(it)
            self.answered_n += 1
            self._zombie_answered(it)
            self._maybe_meteor(it)
            self._maybe_zombie(it)
        g = self.gen
        threading.Thread(target=self._judge_item, args=(it, g), daemon=True).start()
        out = {"ok": True, "answer": it["answer"], "verdict": it["verdict"], "explanation": it.get("explanation")}
        if it["type"] in TWO_CHOICE:
            out["correct"] = it["correct"]
        return out

    def _maybe_meteor(self, answered):
        """☄️ From the meteor_after-th answer on: meteor_chance per answer (cooldown meteor_cooldown answers),
        a purple meteor strikes a random waiting card. Caller holds the lock."""
        n = self.answered_n
        if n < int(self.cfg.get("meteor_after") or 10) or n - self.last_meteor_at < int(self.cfg.get("meteor_cooldown") or 8):
            return
        if random.random() >= float(self.cfg.get("meteor_chance") or 0):
            return
        waiting = [i for i in self.items if i["status"] == "queued" and i is not answered]
        cands = [i for i in waiting[1:] if not i.get("meteor") and i["type"] not in ("challenge", "silver", "streak")]
        if not cands:                                        # (waiting[0] is the next question, leave that one alone)
            return
        target = random.choice(cands)
        target["meteor"] = True
        self.last_meteor_at = n
        self._log({"type": "meteor", "after_answer": n, "hits": target["id"], "question": target["question"]})

    # ------------------------------------------------------------ 🧟 zombies

    def _maybe_zombie(self, answered):
        """From the zombie_after-th answer: zombie_chance per answer (cooldown zombie_cooldown). A zombie bites a waiting
        card (it becomes infected); after zombie_seconds the infection spreads to the card above or below it,
        unless the Teacher answers the bitten card correctly first. Caller holds the lock."""
        n = self.answered_n
        if self.zombie or n < int(self.cfg.get("zombie_after") or 20) \
                or n - self.last_zombie_at < int(self.cfg.get("zombie_cooldown") or 10) \
                or random.random() >= float(self.cfg.get("zombie_chance") or 0):
            return
        waiting = [i for i in self.items if i["status"] == "queued" and i is not answered and not i.get("judging")]
        # index 0 is the next question: the zombie never starts on it and never targets it
        hosts = [k for k in range(1, len(waiting)) if waiting[k]["type"] not in ("boss", "challenge", "infected")]
        random.shuffle(hosts)
        for k in hosts:
            dirs = ["up", "down"]
            random.shuffle(dirs)
            for d in dirs:
                t = k - 1 if d == "up" else k + 1
                if 1 <= t < len(waiting) and waiting[t]["type"] != "boss":
                    now = time.time()
                    self.zombie = {"id": self.zombie_next, "host": waiting[k]["id"], "target": waiting[t]["id"], "dir": d,
                                   "start": now, "end": now + float(self.cfg.get("zombie_seconds") or 20),
                                   "state": "crawling", "done_at": None}
                    self.zombie_next += 1
                    self.last_zombie_at = n
                    self._log({"type": "zombie", "after_answer": n, "host": waiting[k]["id"], "target": waiting[t]["id"]})
                    # 🦷 the bite: the zombie's own card is infected right away (rewritten a bit harder)
                    host = waiting[k]
                    host["infecting"] = True
                    def bite(h=host):
                        try:
                            self._infect(h)
                        finally:
                            h["infecting"] = False
                    threading.Thread(target=bite, daemon=True).start()
                    return

    def _zombie_answered(self, it):
        """The Teacher answered the zombie's own card while it was crawling: freeze it until we know if it's right."""
        z = self.zombie
        if z and z["state"] == "crawling" and z["host"] == it["id"] and time.time() < z["end"]:
            z["state"], z["frozen_at"] = "judging", time.time()
            if it.get("verdict"):                            # buttons: graded instantly
                self._zombie_cure_check(it)

    def _zombie_cure_check(self, it):
        z = self.zombie
        if not z or z["host"] != it["id"] or z["state"] != "judging":
            return
        if it.get("verdict") == "CORRECT":
            z["state"], z["done_at"] = "cured", time.time()
            it["cured_zombie"] = True
            self.streak += int(self.cfg.get("zombie_cure_bonus") or 1)
            self.best_streak = max(self.best_streak, self.streak)
            self._log({"type": "zombie_cured", "host": it["id"]})
        else:                                                # not cured: it keeps crawling from where it was
            z["end"] += time.time() - z.get("frozen_at", time.time())
            z["state"] = "crawling"

    def _zombie_tick(self):
        z = self.zombie
        if not z:
            return
        if z["done_at"] and time.time() - z["done_at"] > 4:
            self.zombie = None                               # the UI has had time to show the ending
            return
        if z["state"] == "crawling" and time.time() >= z["end"]:
            z["state"] = "arrived"
            threading.Thread(target=self._zombie_arrive, args=(z,), daemon=True).start()

    def _zombie_arrive(self, z):
        with self.lock:
            target = self._item(z["target"])
            if not target or target["status"] != "queued" or target.get("judging"):
                waiting = [i for i in self.items if i["status"] == "queued" and not i.get("judging")]
                alts = [i for i in waiting[1:] if i["type"] != "boss"]
                if not alts:
                    z["state"], z["done_at"] = "fizzled", time.time()
                    return
                target = random.choice(alts)
                z["target"] = target["id"]
            target["infecting"] = True
        try:
            if target["type"] == "challenge":
                ok = self._make_boss(target)
            else:
                ok = self._infect(target)
            self._log({"type": "zombie_arrived", "target": target["id"], "became": target["type"], "ok": ok})
        finally:
            target["infecting"] = False
            z["done_at"] = time.time()

    def _rewrite(self, sid, ctype, idea, **extra):
        types = load_types()
        rule = E.fill(types.get(ctype, ""), topic=self.topic(sid), **extra)
        task = E.fill(E.read_skill("make_question"), topic=self.topic(sid), idea=idea,
                      type_name=TYPE_LABELS[ctype].split(" ", 1)[-1], type_rule=rule)
        for _ in range(3):
            out = self._ask(sid, task, self.cfg.get("thinking_budget_cards", 0), any_port=True)
            yield out

    def _infect(self, target):
        """🧟 the card is rewritten slightly harder, with the zombie theme."""
        idea = self._question_for_judge(target)
        for out in self._rewrite(target["sid"], "infected", idea):
            card = self._finish_card(parse_card(out, "infected"), "infected")
            if card:
                with self.lock:
                    for k in ("choices", "claims", "correct"):
                        target.pop(k, None)
                    target.update(question=card["question"], answer=card["answer"], type="infected",
                                  label=TYPE_LABELS["infected"], challenge=False, infected=True, explanation=None)
                threading.Thread(target=self._auto_explain, args=(target,), daemon=True).start()
                return True
        target["infected"] = True                            # couldn't rewrite: still looks infected
        return False

    def _make_boss(self, target):
        """👑 the zombie reached a gold card: it becomes a 2-part boss (harder than gold, 60 s for both parts)."""
        sid = target["sid"]
        other = random.choice([s for s in self.sections if s != sid] or [sid])
        for out in self._rewrite(sid, "boss", self._question_for_judge(target), other_topic=self.topic(other),
                                 other_notes=self.sections.get(other, {}).get("content", "")):
            if not out:
                continue
            if "</think>" in out:
                out = out.rsplit("</think>", 1)[1]
            parts = []
            for k in (1, 2):
                q, a = _field(out, "PART%d" % k), _field(out, "ANSWER%d" % k)
                q = E.clean(q or "", self.names, limit=200)
                q = re.sub(r"\*\*|__", "", q)
                a = E.keep_key_styles(E.clean(a or "", self.names, strip_greeting=False, limit=300), self.vocab)
                if not q or "?" not in q or not a or BROKEN.search(q) or BROKEN.search(a) or LEAK.search(a):
                    break
                parts.append({"q": q[:q.index("?") + 1], "a": a})
            if len(parts) == 2:
                with self.lock:
                    target.update(type="boss", label="👑 Zombie Boss · Part 1 of 2", boss=True, challenge=False,
                                  parts=parts, part=1, hp=2, parts_total=2, part_answers=[],
                                  question=parts[0]["q"], answer=parts[0]["a"], explanation=None, other=self.topic(other))
                whole = {"sid": sid, "type": "boss", "question": parts[0]["q"] + " " + parts[1]["q"],
                         "answer": parts[0]["a"] + " " + parts[1]["a"]}
                def explain_boss():
                    self._auto_explain(whole)
                    target["boss_explanation"] = whole.get("explanation")
                threading.Thread(target=explain_boss, daemon=True).start()
                return True
        return self._infect(target)                          # couldn't make a boss: at least infect it

    def _answer_boss(self, it, text):
        """One part of the boss: correct → the boss takes a hit and part 2 appears; wrong → the boss wins."""
        q = it["parts"][it["part"] - 1]
        out = self._ask(it["sid"], E.fill(E.read_skill("judge_answer"), question=q["q"], correct=q["a"], answer=text),
                        self.cfg["thinking_budget_judge"], any_port=True)
        found = re.findall(r"\b(CORRECT|PARTLY|PARTIALLY|INCORRECT|WRONG)\b", (out or "").rsplit("</think>", 1)[-1].upper())
        v = {"INCORRECT": "WRONG", "PARTIALLY": "PARTLY"}.get(found[-1], found[-1]) if found else "PARTLY"
        with self.lock:
            it["part_answers"].append(text)
            if v == "CORRECT" and it["part"] < it["parts_total"]:
                it["part"] += 1
                it["hp"] -= 1
                nq = it["parts"][it["part"] - 1]
                it.update(question=nq["q"], answer=nq["a"], label="👑 Zombie Boss · Part %d of %d" % (it["part"], it["parts_total"]))
                it["judging"] = False
                self._log({"type": "boss_hit", "id": it["id"], "part": it["part"]})
                return
            if v == "CORRECT":
                it["hp"] = 0
            it["verdict"] = "CORRECT" if v == "CORRECT" else "WRONG"
            it["answer"] = " ".join("**Part %d:** %s" % (k + 1, p["a"]) for k, p in enumerate(it["parts"]))
            it["question"] = " / ".join(p["q"] for p in it["parts"])
            it["explanation"] = it.get("boss_explanation") or it["answer"]
            it.update(status="answered", teacher_answer=" / ".join(it["part_answers"]), answered_at=time.time())
            self._apply_streak(it)
            self.answered_n += 1
            it["judging"] = False
        self._log({"type": "boss_result", "id": it["id"], "verdict": it["verdict"]})

    def _question_for_judge(self, it):
        if it["type"] == "spot_mistake":
            return 'What is wrong in this statement, and what is correct: "%s"' % it["question"]
        if it["type"] == "fill_blank":
            return 'Fill in the blank: "%s"' % it["question"]
        if it["type"] == "whos_right":
            return '%s Who is right: %s' % (it["question"], " or ".join('%s ("%s")' % (c["name"], c["text"]) for c in it["claims"]))
        return it["question"]

    def _judge_item(self, it, g):
        q = self._question_for_judge(it)
        if not it["verdict"]:
            out = self._ask(it["sid"], E.fill(E.read_skill("judge_answer"), question=q, correct=it["answer"],
                                              answer=it["teacher_answer"]),
                            self.cfg["thinking_budget_judge"], any_port=True)
            found = re.findall(r"\b(CORRECT|PARTLY|PARTIALLY|INCORRECT|WRONG)\b", (out or "").rsplit("</think>", 1)[-1].upper())
            it["verdict"] = {"INCORRECT": "WRONG", "PARTIALLY": "PARTLY"}.get(found[-1], found[-1]) if found else "PARTLY"
            with self.lock:
                self._apply_streak(it)
                self._zombie_cure_check(it)
        verdict = it["verdict"]
        if it["type"] not in SPECIAL:
            self._record_result(it["sid"], it["idea"], verdict)
        self._log({"type": "answer", "id": it["id"], "student": it["sid"], "card": it["type"], "question": it["question"],
                   "correct": it["answer"], "teacher": it["teacher_answer"], "verdict": verdict})
        # (no opinion reactions: the panel shows the automatic explanation instead)

    def _auto_explain(self, it):
        """The explanation shown under the answer: why/how, no opinion about the Teacher's answer."""
        task = E.fill(E.read_skill("auto_explain"), question=self._question_for_judge(it), correct=it["answer"])
        text = ""
        for _ in range(2):
            text = E.keep_key_styles(E.clean(self._ask(it["sid"], task, self.cfg.get("thinking_budget_cards", 0), any_port=True),
                                             self.names, limit=420), self.vocab)
            if LEAK.search(text or "") or BROKEN.search(text or ""):
                text = ""
                continue
            text = re.sub(r"^(good (try|job|effort)|well done|nice( try)?|great( job)?|not quite|you'?re (right|close))\b[^.!?]*[.!?]\s*",
                          "", text or "", flags=re.I).strip()                 # strip any opinion that slipped in
            if text and not similar(text, it["answer"]):
                break
        it["explanation"] = first_sentences(text, 3) or it["answer"]

    def explain_more(self, item_id):
        it = self._item(item_id)
        if not it or it["status"] not in ("answered", "done"):
            return {"ok": False, "error": "Answer the question first."}
        level = len(it["more"]) + 2          # level 1 is the automatic explanation
        if level > 3:
            return {"ok": False, "error": "That's all the explanations for this one."}
        previous = " ".join([it["answer"], it.get("explanation") or ""] + it["more"])
        task = E.fill(E.read_skill("explain_more"), question=self._question_for_judge(it), correct=it["answer"],
                      previous=previous, level=level)
        text = ""
        for attempt in range(3):
            t = task if attempt == 0 else task + (
                "\n\nIMPORTANT: your last try was almost the same as before. Use a COMPLETELY different "
                "comparison or example this time.")
            text = E.keep_key_styles(E.clean(self._ask(it["sid"], t, self.cfg.get("thinking_budget_cards", 0), any_port=True),
                                             self.names, limit=420), self.vocab)
            if LEAK.search(text or "") or BROKEN.search(text or ""):
                text = ""
                continue
            if text and not any(similar(text, old, 0.4) for old in [it.get("explanation") or ""] + it["more"]):
                break                                        # a genuinely new explanation
            text = text if attempt == 2 else ""
        if not text:
            return {"ok": False, "error": "%s couldn't explain it right now, try again." % it["name"]}
        it["more"].append(text)
        self._log({"type": "explain_more", "id": it["id"], "level": level, "text": text})
        return {"ok": True, "text": text, "level": level, "max": level >= 3}

    def dismiss(self, item_id):
        """OK pressed after reading the explanation."""
        with self.lock:
            it = self._item(item_id)
            if it and it["status"] == "answered":
                it["status"] = "done"
        return {"ok": True}

    def skip(self, item_id):
        """30 s ran out: move on, and keep the question for later review."""
        with self.lock:
            it = self._item(item_id)
            if not it or it["status"] != "queued":
                return {"ok": False}
            it["status"] = "timeout"
            self.streak = 0                                  # running out of time breaks the streak
        rec = {"lesson": self.lesson, "student": it["name"], "card": it["type"], "question": it["question"],
               "answer": it["answer"], "when": datetime.datetime.now().replace(microsecond=0).isoformat()}
        try:
            with open(os.path.join(self.folder("sessions"), "unanswered.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self._log({"type": "timeout", "id": it["id"], "question": it["question"]})
        return {"ok": True}

    # ------------------------------------------------------------ UI polling

    def poll(self, after=0, session=None):
        with self.lock:
            items = []
            for i in self.items:
                if i["status"] not in ACTIVE or not self.running:     # class over: the feed clears
                    continue
                d = {k: i.get(k) for k in ("id", "sid", "name", "emoji", "question", "status", "verdict", "type",
                                           "label", "challenge", "other", "choices", "reaction", "meteor", "instant",
                                           "infected", "boss", "hp", "part", "parts_total", "judging", "infecting",
                                           "cured_zombie")}
                if i.get("claims"):                          # who's right: names + claims, but not who is right
                    d["claims"] = [{k: c[k] for k in ("sid", "name", "emoji", "text")} for c in i["claims"]]
                d["seconds"] = self._seconds_for(i)
                if i["status"] == "answered":
                    d["answer"], d["teacher_answer"] = i["answer"], i["teacher_answer"]
                    d["explanation"] = i.get("explanation")
                    if i["type"] in TWO_CHOICE:
                        d["correct"] = i["correct"]
                items.append(d)
            thinking = [{"sid": s, "name": self.students[s]["name"], "emoji": self.students[s].get("emoji", "")}
                        for s, v in self.generating.items() if v]
        members = [{"id": sid, "name": s["name"], "emoji": s.get("emoji", ""), "online": bool(self.online.get(sid)),
                    "topic": self.topic(sid)} for sid, s in self.students.items()]
        return {"session": self.session, "running": self.running, "lesson": self.lesson,
                "started_at": self.started_at, "now": time.time(),
                "class_seconds": int(float(self.cfg["class_minutes"]) * 60),
                "question_seconds": int(self.cfg["question_seconds"]),
                "items": items, "thinking": thinking, "members": members, "stats": self.stats(),
                "streak": self.streak, "streak_bonus": int(self.cfg.get("streak_card_bonus") or 3),
                "zombie": dict(self.zombie) if self.zombie and self.running else None,
                "lesson_id": self.lesson_id, "lessons_rev": self.library.rev, "notes_rev": self.notes_rev,
                "prepare": dict(self.prepare, students=dict(self.prepare["students"])) if self.prepare else None}

    def _seconds_for(self, it):
        base = float(self.cfg["question_seconds"])
        return {"lightning": float(self.cfg.get("lightning_seconds") or 10),
                "challenge": float(self.cfg.get("challenge_seconds") or 60),
                "silver": float(self.cfg.get("silver_seconds") or 45),
                "boss": float(self.cfg.get("boss_seconds") or 60),
                "streak": base * 1.25}.get(it["type"], base)
