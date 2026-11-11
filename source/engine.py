"""AI Classroom v2 - the "director" behind the Discord-style chat.

The app decides WHO talks, WHAT kind of message it is (share / ask / answer /
reply / ping the teacher / react) and WHEN it is posted. Each student model only
writes the words, following the skill files in skills/.
"""
import datetime
import hashlib
import json
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.request

from lessons import Library

# ------------------------------------------------------------------ paths

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = APP_DIR

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
SKILLS_DIR = os.path.join(APP_DIR, "skills")
DEFAULT_SKILLS_DIR = os.path.join(RES_DIR, "skills_default")

CONFIG_VERSION = 15
SKILLS_VERSION = 28
# settings whose default changed: older config files get the new value once
CONFIG_UPGRADES = {2: ["message_gap_seconds"], 3: ["thinking_budget_plan"], 4: ["students"], 5: [],
                   6: ["question_type_weights"], 7: ["challenge_every", "second_chance_every"], 8: ["zombie_seconds"], 9: [], 10: ["max_tokens_study"], 11: ["thinking_budget_study"], 12: ["thinking_budget_plan", "max_tokens_plan"], 13: [], 14: ["thinking_budget_notes"], 15: ["daily_goal"]}

DEFAULT_STUDENTS = [
    {"id": 1, "name": "Byte", "emoji": "🤖", "port": 1001,
     "personality": "nerdy and precise, loves numbers, units and exact facts"},
    {"id": 2, "name": "Pixel", "emoji": "🦊", "port": 1002,
     "personality": "super curious, always wants to know why and how things work"},
    {"id": 3, "name": "Mochi", "emoji": "🐼", "port": 1003,
     "personality": "calm and gentle, explains things simply with everyday comparisons"},
    {"id": 4, "name": "Ribbit", "emoji": "🐸", "port": 1004,
     "personality": "funny and playful, uses silly comparisons but always keeps the facts correct"},
    {"id": 5, "name": "Whiskers", "emoji": "🐱", "port": 1005,
     "personality": "careful and thoughtful, likes tricky 'what would happen if' questions"},
]

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "max_message_chars": 170,
    "data_folder": APP_DIR.replace("\\", "/"),      # lessons, sessions, logs... live next to the app
    "host": "127.0.0.1",
    "students": DEFAULT_STUDENTS,
    "class_minutes": 15,              # class timer (bottom-left)
    "question_seconds": 30,           # time to answer one question, then it moves on
    "question_interval_seconds": 10,  # a new question card arrives every N seconds, for the whole class
    "warm_cards": 5,                  # questions written before class (after the notes), so Start is instant
    "more_ahead": 3,                  # extra class notes written ahead (by 2-3 free students) for the More notes button
    "sticky_max": 20,                 # sticky notes: 12 on the board, the + note adds more up to this
    "first_questions": 2,             # cards that arrive right at the start, so there's something to answer
    "max_visible": 9,                 # at most this many question cards on screen at once
    "hidden_ahead": 10,               # cards written ahead and kept hidden; one appears instantly when a slot frees up
    "meteor_after": 10,               # ☄️ meteors can start once this many questions are answered
    "meteor_chance": 0.35,            # chance per answered question
    "meteor_cooldown": 8,             # answered questions between two meteors
    "zombie_after": 20,               # 🧟 zombies can start once this many questions are answered
    "zombie_chance": 0.4,             # chance per answered question
    "zombie_cooldown": 10,            # answered questions between two zombies
    "zombie_seconds": 15,             # after the bite, the infection spreads to the next card after this long
    "zombie_cure_bonus": 1,           # extra streak for curing (answering its card correctly in time)
    "boss_seconds": 60,               # time for the 2-part zombie boss (shared)
    "boss_bonus": 5,                  # streak for beating the boss
    "max_parallel_generation": 2,     # how many students write a question at the same time
    "challenge_every": 10,            # every Nth card is a ⭐ gold challenge card (0 = off)
    "challenge_seconds": 60,          # time for a gold card
    "silver_every": 5,                # every Nth card is a 🥈 silver card: slightly harder (0 = off)
    "silver_seconds": 45,             # time for a silver card
    "second_chance_every": 0,         # every Nth card brings back a missed question, reworded (0 = off)
    "streak_card_chance": 0.1,        # while on a 3+ streak: chance per card of a harder 🔥 streak card
    "streak_card_bonus": 3,           # a correct streak card adds this much to the streak
    "lightning_seconds": 10,          # time for a ⚡ lightning card
    "question_type_weights": {"explain_why": 3, "what_if": 2, "compare": 2, "fill_blank": 2,
                              "pick_one": 2, "spot_mistake": 1, "lightning": 2, "whos_right": 2},
    "message_gap_seconds": [4.0, 5.0],
    "ping_interval_seconds": [10, 12],
    "ping_cooldown_seconds": 45,
    "followup_chance": 0.35,
    "followup_max": 3,
    "group_sizes": [2, 3],
    "chat_history_messages": 14,
    "max_tokens_chat": 1024,
    "thinking_budget_chat": 200,     # thinking stays ON, just shorter, so chat keeps a 2-3 s pace
    "thinking_budget_judge": 300,     # a bit more thought when grading the teacher
    "thinking_budget_cards": 0,       # writing cards + explanations: no thinking (with a budget it rambles into the card)
    "thinking_budget_plan": 0,        # planning a list of questions: no thinking (with a budget it rambles for ~60 s)
    "max_tokens_plan": 1200,
    "thinking_budget_study": 0,       # reading a new lesson: no thinking (clean and ~6x faster; with a budget it rambles)
    "max_tokens_study": 900,
    "thinking_budget_notes": 0,
    "max_tokens_notes": 1600,
    "min_loading_seconds": 4,          # the "students are reading" screen shows at least this long
    "questions_per_batch": 10,
    "max_questions_per_student": 150,
    "timeout_seconds": 180,
    # ⚙️ settings tab
    "calm_mode": False,               # no meteors / zombies / streak cards, less motion
    "sound": True,
    "text_size": "M",                 # S / M / L
    "animations": "full",             # full / less
    "card_seconds_measured": 12.5,    # average seconds to write one card (incl. rewrites), measured live
    "daily_goal": 100,                # 🏠 questions a day for the goal ring
}

QUIZ_SKILLS = ["student_persona", "make_question", "question_types", "judge_answer", "auto_explain", "explain_more",
               "plan_questions", "study_part", "write_notes", "review_simple", "proofread_notes", "more_notes",
               "sticky_more", "sticky_short"]
SKILL_NAMES = QUIZ_SKILLS + ["persona", "chat_share", "chat_ask_peer", "chat_answer_peer", "chat_reply", "teacher_reply",
               "teacher_asks_me",
               "ask_teacher", "react", "react_correct", "react_partly", "react_wrong"]

TEACHER, SYSTEM = 0, -1


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                user = json.load(f)
            old = int(user.get("config_version", 1))
            for ver, keys in CONFIG_UPGRADES.items():
                if old < ver:
                    for k in keys:
                        user.pop(k, None)
            user["config_version"] = CONFIG_VERSION
            cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
        except (OSError, json.JSONDecodeError):
            pass
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:   # write back so new settings are visible
        json.dump(cfg, f, indent=2)
    return cfg


def save_config(cfg):
    """Write the settings back to config.json (only known keys)."""
    out = {k: cfg[k] for k in DEFAULT_CONFIG if k in cfg}
    out["config_version"] = CONFIG_VERSION
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


# ------------------------------------------------------------------ skills

def upgrade_skills():
    """When the built-in skills change, back up the old skills folder and install the new defaults."""
    vfile = os.path.join(SKILLS_DIR, ".version")
    try:
        with open(vfile) as f:
            ver = int(f.read().strip() or 0)
    except (OSError, ValueError):
        ver = 1 if os.path.isdir(SKILLS_DIR) and os.listdir(SKILLS_DIR) else SKILLS_VERSION
    if ver < SKILLS_VERSION and os.path.isdir(SKILLS_DIR):
        backup = os.path.join(SKILLS_DIR, "old", "v%d_%s" % (ver, datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")))
        os.makedirs(backup, exist_ok=True)
        for n in os.listdir(SKILLS_DIR):
            if n.endswith(".md"):
                shutil.move(os.path.join(SKILLS_DIR, n), os.path.join(backup, n))
    os.makedirs(SKILLS_DIR, exist_ok=True)
    with open(vfile, "w") as f:
        f.write(str(SKILLS_VERSION))


def skill_path(name):
    return os.path.join(SKILLS_DIR, name + ".md")


def read_skill(name):
    path = skill_path(name)
    if not os.path.isfile(path):
        os.makedirs(SKILLS_DIR, exist_ok=True)
        shutil.copy(os.path.join(DEFAULT_SKILLS_DIR, name + ".md"), path)
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def write_skill(name, text):
    if name not in SKILL_NAMES:
        raise ValueError("unknown skill")
    os.makedirs(SKILLS_DIR, exist_ok=True)
    with open(skill_path(name), "w", encoding="utf-8") as f:
        f.write(text)


def default_skill(name):
    with open(os.path.join(DEFAULT_SKILLS_DIR, name + ".md"), encoding="utf-8") as f:
        return f.read()


def fill(template, **kw):
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template


# ------------------------------------------------------------------ model calls

def llm(host, port, messages, max_tokens, timeout, think_budget=-1):
    payload = {"messages": messages, "max_tokens": max_tokens, "stream": False}
    if think_budget is not None and int(think_budget) >= 0:
        payload["thinking_budget_tokens"] = int(think_budget)
    body = json.dumps(payload).encode()
    req = urllib.request.Request("http://%s:%d/v1/chat/completions" % (host, port), data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        return None


def health(host, port):
    try:
        with urllib.request.urlopen("http://%s:%d/health" % (host, port), timeout=1.5) as r:
            return json.loads(r.read().decode()).get("status") == "ok"
    except Exception:
        return False


# thinking that spilled into the message: at the start -> throw away, later on -> cut it off
SUMMARY = re.compile(r"\b(student\s*\d+|teacher)\s*(asked|said|mentioned|replied|talked|wanted|was|is asking)\b", re.I)
START_LEAK = re.compile(r"^(we need|we should|let'?s (see|check|think|write)|let me|okay,? so (we|i)|the user|"
                        r"i need to|i should|- newest|newest last|recent chat|your task|word count)", re.I)
MID_LEAK = re.compile(r"\"\s+(let'?s|let me|okay|so)\W*$|\"\s+(let'?s (see|check|count|think)|let me)\b|\"?\s*(word count|your task|recent chat \(|newest last|write only your|"
                      r"we need to write|let's check|check length|count words|the task (is|says))", re.I)
GREETING = re.compile(r"^(hey|hi|hello|yo)\b( there| everyone| guys| all| team| class| teacher| student\s*\d)?"
                      r"[!,.]*\s*", re.I)


STYLE = re.compile(r"\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|__(.+?)__|(?<![*\w])\*(?!\*)(\S(?:[^*]*?\S)?)\*(?![*\w])")


def _norm_words(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


def keep_key_styles(text, vocab, max_spans=3):
    """Bold/italic/underline only on real KEY POINTS: a short term (1-3 words) that appears in the
    lesson notes. Whole sentences, questions, lead-ins ("Can you explain:") and random words lose the style."""
    if not text or not vocab:
        return text
    padded = " %s " % vocab
    kept = [0]

    def judge(m):
        inner = next(g for g in m.groups() if g is not None)
        words = _norm_words(inner)
        ok = (words and len(words.split()) <= 3 and not re.search(r"[?:!,;]", inner)
              and len(inner) < 0.6 * len(text)
              and (" %s " % words in padded or " %s " % words.rstrip("s") in padded))
        if ok and kept[0] < max_spans:
            kept[0] += 1
            return m.group(0)
        return inner

    return STYLE.sub(judge, text)


def tidy_markdown(t):
    """Remove style markers that were opened but never closed (e.g. a cut-off '*short-term')."""
    for mark in ("**", "__"):
        if t.count(mark) % 2:
            i = t.rfind(mark)
            t = t[:i] + t[i + len(mark):]
    singles = [m.start() for m in re.finditer(r"(?<!\*)\*(?!\*)", t)]
    if len(singles) % 2:
        i = singles[-1]
        t = t[:i] + t[i + 1:]
    return t


def clean(text, names, allow_teacher_ping=False, strip_greeting=True, limit=170):
    """Strip the usual small-model wrapping: think tags, 'Name:' labels, quotes.
    Returns "" when the model leaked its thinking into the message (caller retries).
    The app adds "@Teacher" itself where needed, so it is always removed here."""
    if not text:
        return ""
    t = text
    if "</think>" in t:
        t = t.rsplit("</think>", 1)[1]
    if "<think>" in t:
        return ""                                   # thinking got cut off and spilled into the message
    t = re.sub(r"^\s*[-*•]\s+", "", t.strip())
    if START_LEAK.search(t):
        return ""
    if len(SUMMARY.findall(t)) >= 2 or SUMMARY.match(t):   # it summarised the chat instead of talking
        return ""
    mid = MID_LEAK.search(t)
    if mid:
        if mid.start() < 15:
            return ""
        t = t[:mid.start()].rstrip(" \"'")
    label = r"^\s*\**\s*(?:%s)\s*\**\s*[:\-]\s*" % "|".join(re.escape(n) for n in names)
    t = re.sub(label, "", t, flags=re.I)
    t = re.sub(r"@\s*Teacher\b[,:!]?\s*", "", t, flags=re.I)
    t = t.strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'`":
        t = t[1:-1].strip()
    if t.count('"') % 2 == 1:                       # stray quote left over, e.g. ...? 😊"
        t = t[:-1].rstrip() if t.endswith('"') else t.lstrip('"').lstrip()
    t = " ".join(t.split())
    if strip_greeting:
        g = GREETING.sub("", t, count=1)
        if g and g != t:
            t = g[0].upper() + g[1:]
    t = tidy_markdown(t)
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    if len(t) > limit:                              # keep it chat-sized: cut at a sentence end
        ends = [m.end() for m in re.finditer(r"[.!?](\s|$)", t[:limit + 1])]
        if ends and ends[-1] > 40:
            cut = t[:ends[-1]].strip()
            rest = t[ends[-1]:]
            emo = re.match(r"\s*([^\w\s\"'(]{1,3})(\s|$)", rest)   # keep a trailing emoji
            t = cut + (" " + emo.group(1) if emo else "")
        else:
            t = t[:limit].rsplit(" ", 1)[0] + "…"
    return t


# ------------------------------------------------------------------ reactions to the Teacher

AGREE_START = re.compile(r"^(yes|yeah|yep|yup|correct|exactly|right\b|you'?re (right|correct)|that'?s (right|correct|it)|"
                         r"nice|great|good job|got it|perfect|thanks|thank you|awesome)", re.I)
DISAGREE = re.compile(r"(not (quite )?(right|correct|it)\b|wrong|incorrect|i don'?t think|isn'?t (right|correct)|"
                      r"not sure that'?s|don'?t agree|not quite)", re.I)
PARTLY_WORDS = re.compile(r"(close|partly|partially|almost|part of|half|on the right track|nearly|some of)", re.I)

FALLBACK_REACT = {
    "CORRECT": ["Yes, that's right, thank you!", "Got it, thanks!", "That makes sense, thank you! 🙌"],
    "PARTLY": ["Close! That's partly right.", "You're on the right track, but there's a bit more to it.",
               "Almost! Part of that is right."],
    "WRONG": ["Hmm, I don't think that's quite right.", "I'm not sure that's correct, Teacher.",
              "Hmm, I don't think that's it."],
}


def soften(text):
    """No harsh 'you're wrong' to a child: make it calm."""
    if not text:
        return text
    t = re.sub(r"^(no[,!.]?\s*)?you'?re (wrong|incorrect)\b[\s,.!—–-]*", "Hmm, I don't think that's quite right, ",
               text, flags=re.I)
    t = re.sub(r"\byou'?re (wrong|incorrect)\b", "I don't think that's quite right", t, flags=re.I)
    t = re.sub(r"\bthe teacher is (wrong|incorrect)\b", "that's not quite right", t, flags=re.I)
    return t


def matches_verdict(text, verdict):
    """The reaction's words must agree with the verdict badge."""
    if verdict == "CORRECT":
        return not DISAGREE.search(text)
    if verdict == "WRONG":
        return bool(DISAGREE.search(text)) and not AGREE_START.search(text)
    return bool(PARTLY_WORDS.search(text)) and not re.match(r"^(you'?re (right|correct)|exactly|correct)\b", text, re.I)


def clean_planned(line):
    """One planned question line: no bullets, numbers, 'Line3:' / 'Question:' labels, quotes or double '??'."""
    q = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
    q = re.sub(r"^(line\s*\d+|question\s*\d*|q\d*)\s*[:.)-]\s*", "", q, flags=re.I).strip().strip('"“”').strip()
    q = re.sub(r"\?(\s*\?)+", "?", q)
    return q


QUESTION_YES_NO = re.compile(r"^(can|is|are|am|do|does|did|will|would|should|could|has|have|had|was|were|isn'?t|aren'?t|don'?t)\b", re.I)
QUESTION_SOURCE = re.compile(r"\s*,?\s*\b(according to|as (said|written|shown|mentioned) in|mentioned in|listed in|given in|"
                             r"described in|from|in) (the|this|my|your|our) (text|notes?|lesson|passage|slides?|textbook|book)\b", re.I)
QUESTION_META = re.compile(r"\b(the|this|my|your) (text|notes?|passage|slides?|textbook)\b|\banything else\b|\bmentioned\b|"
                           r"\b(wait|let me|i think|not sure)\b", re.I)


def fix_question(q):
    """A planned question, cleaned so a child can understand it on its own. None = throw it away.
    'What does X mean according to the text?' -> 'What does X mean?'; yes/no and meta questions are dropped."""
    q = clean_planned(q or "")
    q = re.sub(r"\b(are|is) (listed|mentioned|given|described|shown|named|written) (in|from) (the|this|my|your) "
               r"(text|notes?|lesson|passage|slides?|textbook|book)\b", r"\1 there", q, flags=re.I)
    q = QUESTION_SOURCE.sub("", q).strip()
    if re.search(r"\b(are|is|was|were|does|do)\s*\?$", q, re.I):
        return None                                        # cutting "in the text" left a broken question
    q = re.sub(r"\s+\?", "?", q)
    if not q.endswith("?") or len(q) < 10 or q.count("?") > 1:
        return None                                        # two questions in one, or not a question
    if QUESTION_YES_NO.match(re.sub(r"\*\*|__", "", q)) or QUESTION_META.search(q):
        return None
    if re.match(r"^(what|how|why) would happen if\b", q, re.I) and \
            re.search(r"\b(which|what|who|where|when|how)\b", q[18:], re.I):
        return None                                        # "What would happen if ... which sector?" makes no sense
    return q[0].upper() + q[1:]


def norm_q(q):
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()


# ------------------------------------------------------------------ engine

class Engine:
    def __init__(self):
        self.lock = threading.RLock()
        self.post_lock = threading.Lock()
        self.cfg = load_config()
        self.host = self.cfg["host"]
        self.students = {int(s["id"]): {"id": int(s["id"]), "name": s.get("name") or "Student %d" % int(s["id"]),
                                        "port": int(s["port"]), "emoji": s.get("emoji", ""),
                                        "personality": s.get("personality", "")} for s in self.cfg["students"]}
        self.names = [s["name"] for s in self.students.values()] + ["Teacher"]
        self.messages = []
        self.next_id = 1
        self.session = 0              # bumps on every Start, the UI clears its view
        self.running = False
        self.gen = 0                  # bumps on Start/Stop so old worker threads exit
        self.typing = {}
        self.online = {}
        self.groups = []
        self.ping = None
        self.cooldown_until = {}
        self.next_ping_at = 0
        self.last_post = 0
        self.gap = 0
        self.recent_thanks = {sid: [] for sid in self.students}
        self.bank_locks = {}          # (lesson id, student) -> lock: a slow plan for an old lesson never blocks the new one
        self.prep = {sid: "" for sid in self.students}
        self.fact_used = {}
        self.busy = set()             # students currently handling the Teacher (left out of group chat)
        self.log_path = None
        upgrade_skills()
        for n in SKILL_NAMES:
            read_skill(n)
        self.library = Library(self.cfg["data_folder"], RES_DIR, sorted(self.students))
        try:
            self.library.migrate_sections(self.folder("sections"), self.folder("banks"))
        except Exception:                                  # noqa: BLE001 - the sample lesson is optional
            pass
        self.load_lesson()
        threading.Thread(target=self._health_loop, daemon=True).start()

    # ---------------------------------------------------------- lesson / folders

    def folder(self, *parts):
        p = os.path.join(self.cfg["data_folder"], *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def load_lesson(self):
        """The active lesson from the library (lessons/<id>/s1..s5.json)."""
        self.lesson, self.lesson_id, self.sections = "Lesson", self.library.active(), {}
        self._vocab = None
        if not self.lesson_id:
            return
        self.lesson = (self.library.meta(self.lesson_id) or {}).get("title") or self.lesson
        for sid in self.students:
            d = self.library.section(self.lesson_id, sid)
            if not d or not (d.get("content") or d.get("source")):
                continue
            src = d.get("source") or d["content"]
            content = d.get("content") or " ".join(src.split()[:300])    # not studied yet: the start of the part
            self.sections[sid] = {"title": d.get("title") or "Part %d" % d.get("part", sid), "content": content,
                                  "source": src, "studied": bool(d.get("studied"))}

    def lesson_path(self, *parts):
        return self.library.path(self.lesson_id, *parts)

    @property
    def vocab(self):
        """All words of the lesson (titles, key points and the original text), used to decide what counts as a
        key point and whether an answer comes from the lesson."""
        if self._vocab is None:
            self._vocab = _norm_words(" ".join([self.lesson] + [s["title"] + " " + s["content"] + " " + s.get("source", "")
                                                                for s in self.sections.values()]))
        return self._vocab

    def _next_fact(self, sid):
        """Hand out the section's sentences (or key points) one by one so the class moves through the whole section."""
        content = re.sub(r"\*\*|__", "", self.sections.get(sid, {}).get("content", ""))
        facts = [re.sub(r"^\s*[-*•]\s*", "", s).strip() for s in re.split(r"(?<=[.!?])\s+|\n+", content)]
        facts = [f for f in facts if len(f) > 20]
        if not facts:
            return self.topic(sid)
        used = self.fact_used.setdefault(sid, set())
        unused = [i for i in range(len(facts)) if i not in used]
        if not unused:
            used.clear()
            unused = list(range(len(facts)))
        i = random.choice(unused[:3])        # roughly in order, a little random
        used.add(i)
        return facts[i]

    def topic(self, sid):
        return self.sections.get(sid, {}).get("title", "")

    def name(self, sid):
        if sid == TEACHER:
            return "Teacher"
        if sid == SYSTEM:
            return "System"
        return self.students[sid]["name"]

    # ---------------------------------------------------------- health

    def _health_loop(self):
        while True:
            for sid, s in self.students.items():
                was = self.online.get(sid)
                self.online[sid] = health(self.host, s["port"])
                if self.online[sid] and not was and sid in self.sections:
                    self._ensure_bank_async(sid)
            time.sleep(4)

    # ---------------------------------------------------------- question banks

    def _bank_lock(self, sid):
        with self.lock:
            return self.bank_locks.setdefault((getattr(self, "lesson_id", None), sid), threading.Lock())

    def _bank_file(self, sid):
        if not self.lesson_id:
            return os.path.join(self.folder("banks"), "s%d_questions.json" % sid)
        return self.lesson_path("s%d_questions.json" % sid)

    def _section_hash(self, sid):
        s = self.sections.get(sid, {})
        return hashlib.sha1((s.get("title", "") + s.get("content", "")).encode()).hexdigest()[:12]

    def _load_bank(self, sid):
        p = self._bank_file(sid)
        h = self._section_hash(sid)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8-sig") as f:
                    b = json.load(f)
                if b.get("section_hash") == h:
                    b["_file"] = p
                    return b
            except (OSError, json.JSONDecodeError):
                pass
        return {"student": sid, "topic": self.topic(sid), "section_hash": h, "questions": [], "_file": p}

    def _save_bank(self, sid, bank):
        # saved where it was loaded from: a plan that finishes after the lesson changed stays with its own lesson
        p = bank.get("_file") or self._bank_file(sid)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in bank.items() if k != "_file"}, f, indent=2, ensure_ascii=False)
        os.replace(p + ".tmp", p)

    def _plan_questions(self, sid, bank):
        """Ask the student to plan another batch of questions. Caller holds the bank lock."""
        cap = int(self.cfg["max_questions_per_student"])
        if len(bank["questions"]) >= cap:
            return 0
        count = min(int(self.cfg["questions_per_batch"]), cap - len(bank["questions"]))
        existing = "\n".join(q["q"] for q in bank["questions"]) or "(none yet)"
        self.prep[sid] = "planning questions…"
        sys_msg = self._persona(sid)
        task = fill(read_skill("plan_questions"), topic=self.topic(sid), count=count, existing=existing)
        out = llm(self.host, self.students[sid]["port"],
                  [{"role": "system", "content": sys_msg}, {"role": "user", "content": task}],
                  int(self.cfg["max_tokens_plan"]), int(self.cfg["timeout_seconds"]),
                  self.cfg["thinking_budget_plan"])
        seen ={norm_q(q["q"]) for q in bank["questions"]}
        added = 0
        out = (out or "").rsplit("</think>", 1)[-1] if "</think>" in (out or "") else ("" if "<think>" in (out or "") else out)
        for line in (out or "").splitlines():
            q = fix_question(line)
            if not q or norm_q(q) in seen:
                continue
            seen.add(norm_q(q))
            bank["questions"].append({"q": q, "asked": 0, "results": []})
            added += 1
        self._save_bank(sid, bank)
        self.prep[sid] = "%d questions planned" % len(bank["questions"])
        return added

    def _ensure_bank_async(self, sid):
        if getattr(self, "preparing", lambda: False)():
            return                                   # the students are reading a new lesson, that comes first
        def work():
            with self._bank_lock(sid):
                bank = self._load_bank(sid)
                unasked = sum(1 for q in bank["questions"] if not q["asked"])
                if unasked < 5:
                    self._plan_questions(sid, bank)
                else:
                    self.prep[sid] = "%d questions planned" % len(bank["questions"])
        threading.Thread(target=work, daemon=True).start()

    def _unasked_count(self, sid):
        try:
            return sum(1 for q in self._load_bank(sid)["questions"] if not q["asked"])
        except Exception:
            return 0

    def _take_question(self, sid):
        with self._bank_lock(sid):
            bank = self._load_bank(sid)
            for q in bank["questions"]:                    # old banks: tidy (or retire) confusing questions
                if not q["asked"] and not q.get("checked"):
                    fixed = fix_question(q["q"])
                    q["checked"] = True
                    if fixed:
                        q["q"] = fixed
                    else:
                        q["asked"] = 99
            unasked = [q for q in bank["questions"] if not q["asked"]]
            if not unasked:
                self._plan_questions(sid, bank)
                unasked = [q for q in bank["questions"] if not q["asked"]]
            if unasked:
                q = random.choice(unasked[:5])
            elif bank["questions"]:
                q = min(bank["questions"], key=lambda x: (x["asked"], random.random()))
            else:
                return None
            q["asked"] += 1
            self._save_bank(sid, bank)
            left = len(unasked) - 1
        if left < 5:
            self._ensure_bank_async(sid)
        return q["q"]

    def _record_result(self, sid, question, verdict):
        with self._bank_lock(sid):
            bank = self._load_bank(sid)
            for q in bank["questions"]:
                if q["q"] == question:
                    q["results"].append(verdict)
            self._save_bank(sid, bank)

    # ---------------------------------------------------------- prompts

    def _group_of(self, sid):
        for g in self.groups:
            if sid in g:
                return g
        return []

    def _persona(self, sid):
        mates = [m for m in self._group_of(sid) if m != sid]
        mates_txt = ", ".join("%s (topic: %s)" % (self.name(m), self.topic(m)) for m in mates) or "everyone in class"
        sec = self.sections.get(sid, {})
        return fill(read_skill("persona"), name=self.name(sid), lesson=self.lesson, topic=sec.get("title", ""),
                    section=sec.get("content", ""), groupmates=mates_txt)

    def _transcript(self, sid):
        group = set(self._group_of(sid))
        keep = []
        with self.lock:
            msgs = list(self.messages)
        by_id = {m["id"]: m for m in msgs}
        for m in msgs:
            if m["author"] == SYSTEM:
                continue
            if m["author"] in group or m["author"] == TEACHER and (
                    m.get("reply_to") and by_id.get(m["reply_to"], {}).get("author") in group):
                keep.append(m)
        lines = []
        for m in keep[-int(self.cfg["chat_history_messages"]):]:
            who = self.name(m["author"])
            ref = by_id.get(m.get("reply_to"))
            to = " (replying to %s)" % self.name(ref["author"]) if ref else ""
            lines.append("%s%s: %s" % (who, to, m["text"]))
        return "\n".join(lines) or "(the chat is empty, you are first)"

    def _write(self, sid, task, max_tokens=None, ping=False, with_chat=True):
        """with_chat=False for replies to the Teacher's answer: the group chat isn't needed there and
        small models otherwise start summarising it ("Student 3 asked..., Student 2 said...")."""
        if with_chat:
            user = "Recent chat (newest last):\n%s\n\nYOUR TASK:\n%s\n\nWrite ONLY your chat message." % (
                self._transcript(sid), task)
        else:
            user = "YOUR TASK:\n%s\n\nWrite ONLY your chat message." % task
        msgs = [{"role": "system", "content": self._persona(sid)}, {"role": "user", "content": user}]
        self.typing[sid] = self.typing.get(sid, 0) + 1
        try:
            for attempt in range(2):                 # one retry if the thinking leaked into the message
                out = llm(self.host, self.students[sid]["port"], msgs,
                          max_tokens or int(self.cfg["max_tokens_chat"]), int(self.cfg["timeout_seconds"]),
                          self.cfg["thinking_budget_chat"] if attempt == 0 else self.cfg["thinking_budget_judge"])
                text = clean(out, self.names, limit=int(self.cfg["max_message_chars"]))
                if text:
                    return keep_key_styles(text, self.vocab)
            return ""
        finally:
            self.typing[sid] = max(0, self.typing.get(sid, 1) - 1)

    # ---------------------------------------------------------- posting

    def _alive(self, g):
        return self.running and self.gen == g

    def _add(self, author, text, reply_to=None, kind="chat", meta=None):
        with self.lock:
            m = {"id": self.next_id, "author": author, "name": self.name(author), "text": text,
                 "reply_to": reply_to, "kind": kind, "meta": meta or {},
                 "mention": author != TEACHER and text.startswith("@Teacher"), "ts": time.time()}
            self.next_id += 1
            self.messages.append(m)
        self._log(m)
        return m

    def _post(self, author, text, g, reply_to=None, kind="chat", meta=None, priority=False):
        """Students post through a gate so messages come out every few seconds (config message_gap_seconds).
        priority=True (anything said to the Teacher) skips the wait so the child isn't kept waiting."""
        self.typing[author] = self.typing.get(author, 0) + 1          # keep "typing…" while waiting
        try:
            while True:
                if not self._alive(g):
                    return None
                with self.post_lock:
                    if priority or time.time() >= self.last_post + self.gap:
                        m = self._add(author, text, reply_to, kind, meta)
                        self.last_post = time.time()
                        lo, hi = self.cfg["message_gap_seconds"]
                        self.gap = random.uniform(float(lo), float(hi))
                        return m
                time.sleep(0.15)
        finally:
            self.typing[author] = max(0, self.typing.get(author, 1) - 1)

    def _sys(self, text):
        return self._add(SYSTEM, text, kind="system")

    def _log(self, record):
        if not self.log_path:
            return
        record = dict(record, t=round(time.time(), 1))     # 🏠 live stats: when it happened
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------------------------------------------------------- session

    def start(self):
        with self.lock:
            if self.running:
                return {"ok": False, "error": "Session is already running."}
            self.load_lesson()
            members = [sid for sid in self.students if sid in self.sections]
            if len(members) < 2:
                return {"ok": False, "error": "Need at least 2 section files in %s" % self.folder("sections")}
            self.gen += 1
            g = self.gen
            self.session += 1
            self.messages = []
            self.running = True
            self.ping = None
            self.cooldown_until = {}
            self.typing = {}
            self.last_post = 0
            self.gap = 0
            self.fact_used = {}
            random.shuffle(members)
            sizes = [int(x) for x in self.cfg["group_sizes"]]
            self.groups, i = [], 0
            for size in sizes:
                if i < len(members):
                    self.groups.append(sorted(members[i:i + size]))
                    i += size
            if i < len(members):
                self.groups[-1] = sorted(self.groups[-1] + members[i:])
            self.groups = [grp for grp in self.groups if grp]
            lo, hi = self.cfg["ping_interval_seconds"]
            self.next_ping_at = time.time() + random.uniform(float(lo), float(hi))
            stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.log_path = os.path.join(self.folder("sessions"), "session_%s.jsonl" % stamp)
        self._log({"type": "session_start", "lesson": self.lesson, "groups": self.groups,
                   "topics": {sid: self.topic(sid) for sid in self.sections}})
        for gi, grp in enumerate(self.groups):
            label = "Group %s" % "ABCDEFG"[gi]
            self._sys("%s: %s" % (label, ", ".join("%s (%s)" % (self.name(s), self.topic(s)) for s in grp)))
            threading.Thread(target=self._group_loop, args=(grp, g), daemon=True).start()
        threading.Thread(target=self._ping_loop, args=(g,), daemon=True).start()
        return {"ok": True}

    def stop(self):
        with self.lock:
            if not self.running:
                return {"ok": False, "error": "Session is not running."}
            self.running = False
            self.gen += 1
            self.ping = None
            self.typing = {}
        self._sys("Session stopped.")
        self._log({"type": "session_stop"})
        return {"ok": True}

    # ---------------------------------------------------------- group chat

    def _group_loop(self, members, g):
        last, first = None, True
        time.sleep(random.uniform(0.1, 1.2))
        while self._alive(g):
            picked = self._pick(members, last, first)
            if not picked:                      # everyone in the group is busy with the Teacher
                time.sleep(0.5)
                continue
            speaker, action, target, ref = picked
            first = False
            sec_t = self.topic(target) if target else ""
            ctx = ('You are replying to %s, who said: "%s"' % (self.name(ref["author"]), ref["text"])) if ref else ""
            if action == "share":
                task = fill(read_skill("chat_share"), topic=self.topic(speaker), fact=self._next_fact(speaker),
                            reply_context=ctx, target=self.name(target) if target else "your group")
            elif action == "ask":
                task = fill(read_skill("chat_ask_peer"), target=self.name(target), target_topic=sec_t,
                            topic=self.topic(speaker), fact=self._next_fact(target), reply_context=ctx)
            elif action == "answer":
                task = fill(read_skill("chat_answer_peer"), target=self.name(target), msg_text=ref["text"],
                            topic=self.topic(speaker))
            else:
                task = fill(read_skill("chat_reply"), target=self.name(target), msg_text=ref["text"],
                            topic=self.topic(speaker))
            text = self._write(speaker, task)
            if not self._alive(g):
                break
            if not text:
                time.sleep(1.5)
                continue
            meta = {"action": action}
            if action == "ask":
                meta["asks"] = target
            m = self._post(speaker, text, g, reply_to=ref["id"] if ref else None, meta=meta)
            if m and action == "answer":
                ref["meta"]["answered"] = True
            if m and ref:
                ref["meta"].setdefault("replied_by", []).append(speaker)
            last = speaker

    def _pick(self, members, last, first):
        with self.lock:
            recent = [m for m in self.messages[-12:] if m["author"] in members and m["kind"] == "chat"]
        # someone in my group asked a groupmate a question -> that groupmate answers
        free = [s for s in members if s not in self.busy]     # busy = talking with the Teacher right now
        if not free:
            return None
        for m in reversed(recent):
            asked = m["meta"].get("asks")
            if asked in free and not m["meta"].get("answered"):
                return asked, "answer", m["author"], m
        choices = [s for s in free if s != last] or free
        speaker = random.choice(choices)
        others = [s for s in members if s != speaker]
        # every bot message is a reply to another bot (only the very first message of a group has nothing to reply to)
        latest_other = next((m for m in reversed(recent) if m["author"] != speaker), None)
        if first or not others or not latest_other:
            return speaker, "share", None, latest_other
        fresh = next((m for m in reversed(recent) if m["author"] != speaker
                      and speaker not in m["meta"].get("replied_by", [])
                      and not m["meta"].get("answered")), None)
        r = random.random()
        if r < 0.35:      # share my own point, as a reply to the latest groupmate message
            return speaker, "share", latest_other["author"], latest_other
        if r < 0.70:      # ask a groupmate about their topic, replying to their latest message
            target = random.choice(others)
            ref = next((m for m in reversed(recent) if m["author"] == target), latest_other)
            return speaker, "ask", target, ref
        if fresh:         # react to something I haven't replied to yet
            return speaker, "reply", fresh["author"], fresh
        return speaker, "share", latest_other["author"], latest_other

    # ---------------------------------------------------------- teacher pings

    def _ping_loop(self, g):
        while self._alive(g):
            time.sleep(0.4)
            if self.ping or time.time() < self.next_ping_at:
                continue
            now = time.time()
            cands = [s for s in self.sections if self.online.get(s) and self.cooldown_until.get(s, 0) <= now]
            if not cands:
                continue
            ready = [s for s in cands if self._unasked_count(s) > 0]   # don't make the class wait for planning
            cands = ready or cands
            self._ask_teacher(random.choice(cands), g, chain=1)

    def _ask_teacher(self, sid, g, chain, reply_to=None):
        self.ping = {"sid": sid, "question": None, "msg_id": None, "chain": chain, "state": "asking"}
        question = self._take_question(sid)
        if not question or not self._alive(g):
            self.ping = None
            lo, hi = self.cfg["ping_interval_seconds"]
            self.next_ping_at = time.time() + random.uniform(float(lo), float(hi))
            return
        self.ping["question"] = question
        text = self._write(sid, fill(read_skill("ask_teacher"), question=question), ping=True)
        text = re.sub(r"@\s*Teacher\b[,:]?\s*", "", text or "", flags=re.I).strip()
        if "?" not in text:
            text = question
        q_end = text.index("?") + 1                  # stop at the question: no hints or answers after it
        emo = re.match(r"\s*([^\w\s\"'(]{1,3})(\s|$)", text[q_end:])
        text = text[:q_end] + (" " + emo.group(1) if emo else "")
        m = self._post(sid, "@Teacher " + text, g, reply_to=reply_to, kind="ping",
                       meta={"question": question, "chain": chain}, priority=True)
        if not m:
            self.ping = None
            return
        self.ping.update({"msg_id": m["id"], "state": "waiting"})

    def _judge(self, answer_msg, g):
        sid = self.ping["sid"]
        try:
            self._judge_inner(answer_msg, g)
        finally:
            self.busy.discard(sid)

    def _grade(self, sid, question, answer_msg, g):
        """The student checks the Teacher's answer to ITS question, then reacts.
        The reaction is checked so it always matches the verdict badge."""
        answer = answer_msg["text"]
        self.typing[sid] = self.typing.get(sid, 0) + 1
        try:
            out = llm(self.host, self.students[sid]["port"],
                      [{"role": "system", "content": self._persona(sid)},
                       {"role": "user", "content": fill(read_skill("judge_answer"), question=question, answer=answer)}],
                      int(self.cfg["max_tokens_chat"]), int(self.cfg["timeout_seconds"]),
                      self.cfg["thinking_budget_judge"])
        finally:
            self.typing[sid] = max(0, self.typing.get(sid, 1) - 1)
        found = re.findall(r"\b(CORRECT|PARTLY|PARTIALLY|INCORRECT|WRONG)\b", (out or "").upper())
        verdict = {"INCORRECT": "WRONG", "PARTIALLY": "PARTLY"}.get(found[-1], found[-1]) if found else "PARTLY"

        skill = {"CORRECT": "react_correct", "PARTLY": "react_partly", "WRONG": "react_wrong"}[verdict]
        recent = "; ".join(self.recent_thanks[sid][-5:]) or "(none)"
        task = fill(read_skill(skill), question=question, answer=answer, recent=recent)
        text = ""
        for _ in range(2):                           # retry once if the words don't match the verdict
            text = soften(self._write(sid, task, with_chat=False))
            # must match the badge, and must be about the Teacher's answer (not other students)
            if text and matches_verdict(text, verdict) and not re.search(r"\bstudent\s*\d", text, re.I):
                break
            text = ""
        if not text:
            text = random.choice(FALLBACK_REACT[verdict])
        if verdict == "CORRECT":
            self.recent_thanks[sid] = (self.recent_thanks[sid] + [text])[-8:]
        self._post(sid, "@Teacher " + text, g, reply_to=answer_msg["id"], kind="react", meta={"verdict": verdict},
                   priority=True)
        return verdict

    def _judge_inner(self, answer_msg, g):
        p = self.ping
        sid, question, answer = p["sid"], p["question"], answer_msg["text"]
        p["state"] = "judging"
        verdict = self._grade(sid, question, answer_msg, g)
        self._record_result(sid, question, verdict)
        self._log({"type": "ping_result", "student": sid, "question": question, "answer": answer,
                   "verdict": verdict, "chain": p["chain"]})

        if (verdict == "CORRECT" and p["chain"] < int(self.cfg["followup_max"])
                and random.random() < float(self.cfg["followup_chance"]) and self._alive(g)):
            self._ask_teacher(sid, g, chain=p["chain"] + 1, reply_to=answer_msg["id"])
            return
        self.ping = None
        self.cooldown_until[sid] = time.time() + float(self.cfg["ping_cooldown_seconds"])
        lo, hi = self.cfg["ping_interval_seconds"]
        self.next_ping_at = time.time() + random.uniform(float(lo), float(hi))

    # ---------------------------------------------------------- teacher input

    def teacher_send(self, text, reply_to=None):
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty"}
        reply_to = int(reply_to) if reply_to else None
        with self.lock:
            target = next((m for m in self.messages if m["id"] == reply_to), None) if reply_to else None
        m = self._add(TEACHER, text, reply_to=reply_to)
        if not self.running:
            return {"ok": True, "note": "Session is stopped, nobody will answer."}
        g = self.gen
        mention = re.search(r"@\s*Student\s*(\d)", text, re.I)
        p = self.ping
        if p and p["state"] == "waiting" and (reply_to == p["msg_id"] or (not reply_to and not mention)):
            self.busy.add(p["sid"])          # step out of the group chat right away
            threading.Thread(target=self._judge, args=(m, g), daemon=True).start()
            return {"ok": True}
        sid = None
        if target and target["author"] in self.students:
            sid = target["author"]
        elif mention and int(mention.group(1)) in self.sections:
            sid = int(mention.group(1))
        else:
            sid = random.choice(list(self.sections))
        self.busy.add(sid)
        threading.Thread(target=self._answer_teacher, args=(sid, m, target, g), daemon=True).start()
        return {"ok": True}

    def _answer_teacher(self, sid, msg, target, g):
        """Teacher talked to a student outside a ping. Three different situations:
        - the Teacher ANSWERED a question this student asked  -> check it and react (with a verdict badge)
        - the Teacher ASKED this student something             -> answer it
        - anything else                                         -> short friendly reply"""
        try:
            is_question = target and (target["kind"] == "ping" or target["meta"].get("action") == "ask"
                                      or re.search(r"\?\s*\W{0,6}$", target["text"]))
            if target and target["author"] == sid and is_question:
                question = re.sub(r"^@\S+\s*", "", target["text"]).strip()
                verdict = self._grade(sid, question, msg, g)
                self._log({"type": "teacher_answered_question", "student": sid, "question": question,
                           "answer": msg["text"], "verdict": verdict})
                return
            mine = target["text"] if target and target["author"] == sid else ""
            skill = "teacher_asks_me" if "?" in msg["text"] else "teacher_reply"
            text = soften(self._write(sid, fill(read_skill(skill), msg_text=msg["text"], lesson=self.lesson,
                                                my_message=mine or "(nothing, they wrote to you directly)")))
            if text and self._alive(g):
                self._post(sid, "@Teacher " + text, g, reply_to=msg["id"], meta={"action": skill}, priority=True)
        finally:
            self.busy.discard(sid)

    # ---------------------------------------------------------- UI polling

    def poll(self, after=0, session=None):
        with self.lock:
            reset = session != self.session
            msgs = [m for m in self.messages if reset or m["id"] > int(after or 0)]
            groups = list(self.groups)
            p = dict(self.ping) if self.ping else None
        members = []
        now = time.time()
        for sid, s in self.students.items():
            gi = next((i for i, grp in enumerate(groups) if sid in grp), None)
            members.append({"id": sid, "name": s["name"], "port": s["port"], "topic": self.topic(sid),
                            "has_section": sid in self.sections, "online": bool(self.online.get(sid)),
                            "typing": self.typing.get(sid, 0) > 0,
                            "group": "ABCDEFG"[gi] if gi is not None else None,
                            "cooldown": max(0, int(self.cooldown_until.get(sid, 0) - now)) if self.running else 0,
                            "prep": self.prep.get(sid, "")})
        return {"session": self.session, "reset": reset, "messages": msgs, "members": members,
                "running": self.running, "lesson": self.lesson,
                "ping": {"sid": p["sid"], "msg_id": p["msg_id"], "state": p["state"]} if p else None,
                "next_ping_in": max(0, round(self.next_ping_at - now)) if self.running and not p else None}
