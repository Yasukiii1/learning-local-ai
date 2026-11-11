"""AI Classroom - quiz mode.

Students (Byte, Pixel, Mochi, Ribbit, Whiskers) write question CARDS about their own section, in their own
personality, together with the correct answer. Card types: explain_why, what_if, compare, fill_blank,
pick_one (3 buttons), spot_mistake, plus gold challenge cards that mix two topics.
After the Teacher answers: explanation reveal, verdict, a personality reaction, and "Explain more" on demand.
"""
import base64
import datetime
import hashlib
import subprocess
import json
import os
import random
import re
import threading
import time

import engine as E
import lessons as L
import review as R
import stats as ST

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


# a key point that is really the model thinking out loud ("Wait, need to check the text. Let me re-read.")
META_POINT = re.compile(r"\b(wait|let me|re-?read|need to check|i think|i'm not sure|not sure|not clear|possibly|probably|"
                        r"maybe|likely|seems|implied|unclear|it says|the text (says|mentions|lists)|according to the text|"
                        r"mistake|hmm|okay|actually)\b|\(.*\b(note|check)\b", re.I)


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
    points = [p for p in points if len(p) > 8 and "?" not in p and not echo.search(p) and not META_POINT.search(p)]
    named = [p for p in points if not re.match(r"^(it|they|this|these|those|that)\b", re.sub(r"\*\*", "", p), re.I)]
    if len(named) >= 3:
        points = named                                   # "It is the value of..." doesn't say what "it" is
    if re.search(r"<|title|words|what the text", title, re.I):
        title = ""
    qs = []
    for line in qs_txt.splitlines():
        if not bullet.match(line) and not line.strip().endswith("?"):
            continue
        q = E.fix_question(re.sub(r"\*\*|__", "", line))
        if not q or "<" in q or "</" in line:
            continue
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


def short_text(text, max_words=38, max_sent=2):
    """Not too short, not too long: whole sentences, at most max_sent of them and about max_words words."""
    parts = [x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z*\"'(])", (text or "").strip()) if x.strip()]
    out, n = [], 0
    for x in parts[:max_sent]:
        w = len(x.split())
        if out and n + w > max_words:
            break
        out.append(x)
        n += w
    return E.tidy_markdown(" ".join(out).strip())


KEY_JUNK = re.compile(r"[?:!,;()\d]|^(key idea|remember|example|note|pros|cons|option [a-z]|part \d+)$", re.I)


def add_keys(text, terms, max_spans=3, avoid=()):
    """The small model often forgets to **bold** the key words: bold the lesson's key terms that appear in the text
    until there are at least 2 (or max_spans when that's lower). Never inside an existing bold, never a term in avoid."""
    if not text or not terms:
        return text
    have = re.findall(r"\*\*(.+?)\*\*", text)
    target = min(2, max_spans)
    if len(have) >= target:
        return text
    taken = {t.lower() for t in have} | {a.lower() for a in avoid}
    for term in terms:
        if len(have) >= target:
            break
        if term.lower() in taken or any(term.lower() in h.lower() or h.lower() in term.lower() for h in have):
            continue
        parts = re.split(r"(\*\*.+?\*\*)", text)        # only search outside existing bold spans
        pat = re.compile(r"(?<![\w*])(%s(?:e?s)?)(?![\w*])" % re.escape(term), re.I)
        for k, seg in enumerate(parts):
            if seg.startswith("**") or not pat.search(seg):
                continue
            parts[k] = pat.sub(r"**\1**", seg, count=1)
            have.append(term)
            taken.add(term.lower())
            break
        text = "".join(parts)
    return text


# sentences a student should never say in an explanation: talking ABOUT the card instead of explaining it
EXPL_META = re.compile(r"(\b(question|answer|explanation|statement|sentence)\s*:|\byou asked\b|\bthe question\b|"
                       r"\bthe (correct |right )?answer (is|was)\b|\bfill in the blank\b|\bwho'?s right\b|\bhey,? teacher\b|"
                       r"\bteacher!|\bthe (teacher|lesson|text|notes) (says?|said|asked|thinks|tells us)\b|\bmy notes\b|\bthe notes\b|\bthe text\b|"
                       r"\bin simple words\b|\bunderline\b|\bin \*\*bold\*\*|\bthe fact\b|\bi know from\b|\bthis card\b|"
                       r"\blet'?s (see|check|think)\b|\bso who\b|\b(a|the) blank\b|\bi (just )?saw\b|\byou see\b|"
                       r"\bthe (word|answer) (that )?(fits|goes)\b|\b(byte|pixel|mochi|ribbit|whiskers|teacher) "
                       r"(says?|said|thinks?|believes?|is (right|wrong))\b|\bis (right|wrong)\b|\bthe statement\b|"
                       r"\bthat'?s (wrong|right|correct|incorrect|not right)\b|\bi (need|have|want|am going) to\b|\bi'?ll\b|"
                       r"\bi will\b|\bfor a child\b|\bexplain (it|this|that)\b|\bthe right idea\b|\bsimply put\b|\blevel [123]\b)", re.I)
# instruction words that leaked into an answer ("... for equilibrium. underline the fact in simple words.")
ANSWER_ECHO = re.compile(r"\b(in simple words|underline|bold the|in \*\*bold\*\*|the fact|this card|the format|"
                         r"my notes|your notes|key ?words?)\b", re.I)


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"”')])\s+", (text or "").strip()) if s.strip()]


def clean_explanation(text, already=()):
    """Keep only sentences that really EXPLAIN: no talk about the question/answer, no questions back to the child,
    and nothing the child can already see above it (the answer, the claims, an earlier explanation)."""
    seen = [re.sub(r"\*\*|__", "", s) for old in already for s in _sentences(old)]
    keep, plain_keep = [], []
    for s in _sentences(text):
        p = re.sub(r"\*\*|__", "", s).strip().strip('"“”')
        if not p or p.rstrip().endswith("?") or EXPL_META.search(p) or LEAK.search(p):
            continue
        if any(similar(p, o, 0.5) for o in seen) or any(similar(p, k, 0.6) for k in plain_keep):
            continue                                       # says again what is already on the screen
        s = s.strip()
        if (s.count('"') + s.count("“") + s.count("”")) % 2:
            s = re.sub(r"[\"“”]", "", s)                 # a quote left open by a dropped sentence
        keep.append(s)
        plain_keep.append(p)
    return E.tidy_markdown(" ".join(keep).strip())


NOTE_TAGS = {"title": "TITLE", "big": "BIG", "big idea": "BIG", "main idea": "BIG", "point": "POINT",
             "key point": "POINT", "fact": "POINT", "def": "DEF", "definition": "DEF", "word": "DEF",
             "remember": "REMEMBER", "formula": "FORMULA", "example": "EXAMPLE", "compare": "COMPARE",
             "step": "STEP", "watch": "WATCH", "watch out": "WATCH", "mistake": "WATCH", "careful": "WATCH"}
NOTE_MAX = {"TITLE": 1, "BIG": 1, "POINT": 6, "DEF": 5, "REMEMBER": 1, "FORMULA": 2, "EXAMPLE": 2, "COMPARE": 2,
            "STEP": 6, "WATCH": 2}
NOTE_LINE = re.compile(r"^\**\s*([A-Za-z][A-Za-z ]{1,12}?)\s*\**\s*(?:\d+\s*)?\**\s*:\s*(?:\*\*(?=\s))?\s*(.+)$")
NOTE_META = re.compile(r"\b(the text|from (the )?text(book)?|the notes?|the lesson says|this part says|inferred|tags?|"
                       r"capitals|(DEF|POINT|STEP|BIG|TITLE) lines?|layout|instructions?)\b|->|\bgood\.?$|\bok\.?$|"
                       r"^(none|nothing|n/?a)\b|\bno (mix-?ups?|mistakes?|warnings?|formulas?|examples?)\b|"
                       r"\b(each line|key words? of|bold(ed|ing)?\b|per (the )?example|restructure|let'?s|need to|"
                       r"i bolded|i'?ll|i will|i wrote|water cycle|the example)|:\s*$|\?.*\?", re.I)
NOTE_THINK = re.compile(r"^(wait|let me|let's|hmm+|i think|i will|i'll|maybe|actually|note:)\b", re.I)


def parse_note_title(md):
    m = re.search(r"^TITLE:\s*(.+)$", md or "", re.M) or re.search(r"^#{1,2}\s+(.+)$", md or "", re.M)
    return re.sub(r"\*\*", "", m.group(1)).strip() if m else ""


def notes_tagged(md):
    """New-style notes (tagged lines) vs the old plain Markdown ones."""
    return bool(re.search(r"^(BIG|POINT|DEF):", md or "", re.M))


def clean_notes(out, source=""):
    """A student's notes -> clean tagged lines (TITLE / BIG / POINT / DEF / REMEMBER / FORMULA / EXAMPLE / COMPARE /
    STEP / WATCH). Untagged lines become POINTs, so a sloppy reply still makes tidy notes."""
    if not out:
        return ""
    if "</think>" in out:
        out = out.rsplit("</think>", 1)[1]
    if "<think>" in out:
        return ""
    t = re.sub(r"^```\w*\s*|```\s*$", "", out.strip(), flags=re.M).strip()
    has_formula = bool(re.search(r"[=×÷]|formula|equation", source or "", re.I)) or not source
    got, count, seen = [], {}, set()
    for raw in t.splitlines():
        line = raw.strip()
        line = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", line).strip()
        line = re.sub(r"^💡\s*", "", line)
        if not line or LEAK.search(line) or NOTE_THINK.match(line) or re.match(r"(key (concepts|points) from|okay|so,? |here (are|is) )", line, re.I):
            continue
        line = re.sub(r"\s*\((?:[^()]*\b(?:text|textbook|inferred|lesson|need|should|must|short meaning|tags?)\b[^()]*|but [^()]*)\)",
                      "", line, flags=re.I).strip()
        tag, body = None, line
        m = NOTE_LINE.match(line)
        if m and m.group(1).strip().lower() in NOTE_TAGS:
            tag, body = NOTE_TAGS[m.group(1).strip().lower()], m.group(2).strip()
        elif m and m.group(1).strip().isupper():         # an unknown tag ("UNIT: newton metres") -> a plain point
            tag, body = "POINT", "%s: %s" % (m.group(1).strip().capitalize(), m.group(2).strip())
        elif line.startswith("#"):
            tag, body = "TITLE", line.lstrip("#").strip()
        else:
            tag = "POINT"
        body = re.sub(r"\\(?:boxed|text|mathrm|textbf|mathbf)\s*\{([^{}]*)\}", r"\1", body)    # LaTeX bits
        body = body.replace("\\times", "×").replace("\\cdot", "·").replace("\\div", "÷").replace("$", "")
        body = re.sub(r":\s*=\s*", " = ", body)
        body = E.tidy_markdown(body.strip())
        if len(re.sub(r"[\W_]+", "", body)) < 3 or (tag != "TITLE" and NOTE_META.search(body)):
            continue
        if tag == "TITLE":
            body = re.sub(r"\*\*", "", body).strip(" .:")
        if tag == "DEF":
            m2 = re.match(r"(.{1,60}?)\s*(?:=|:|\s[-–—]\s)\s*(.+)", body)
            if not m2:
                tag = "POINT"
            else:
                body = "%s = %s" % (m2.group(1).strip(), m2.group(2).strip())
        if tag == "FORMULA" and not has_formula:        # no formula in the lesson: the student made one up
            continue
        if tag == "COMPARE" and "|" not in body:
            tag = "POINT"
        if count.get(tag, 0) >= NOTE_MAX[tag]:
            if tag == "BIG":
                tag = "POINT"
                if count.get(tag, 0) >= NOTE_MAX[tag]:
                    continue
            else:
                continue
        key = re.sub(r"[\W_]+", " ", re.sub(r"\*\*", "", body.split(" = ")[0] if tag == "DEF" else body)).strip().lower()
        if key in seen:                                  # the small model sometimes writes everything twice
            continue
        seen.add(key)
        count[tag] = count.get(tag, 0) + 1
        got.append((tag, body))
    if not any(g[0] == "BIG" for g in got):              # no big idea: the first point is it
        for i, (tg, bd) in enumerate(got):
            if tg == "POINT":
                got[i] = ("BIG", bd)
                break
    if not any(g[0] in ("BIG", "POINT", "DEF") for g in got):
        return ""
    order = ["TITLE", "BIG", "POINT", "DEF", "STEP", "FORMULA", "EXAMPLE", "COMPARE", "WATCH", "REMEMBER"]
    got.sort(key=lambda g: order.index(g[0]))            # stable: keeps the student's order inside each tag
    return "\n".join("%s: %s" % g for g in got)[:5000]


NOT_ANSWER = re.compile(r"^(test(ing)?|idk|i ?d(o|o)n'?t know|don'?t know|dunno|no idea|not sure|pass|skip|nothing|"
                        r"\?+|\.+|-+|ok|yes|no|hm+|um+|a+|s+|x+|asdf\w*|qwe\w*)$", re.I)


def quick_verdict(answer, correct):
    """Grade without the model when it's obvious: no real answer -> WRONG, the exact key word(s) -> CORRECT."""
    a = re.sub(r"[^\w\s]", " ", (answer or "").lower()).split()
    if not a or len("".join(a)) < 2 or NOT_ANSWER.match(" ".join(a)):
        return "WRONG"
    plain = re.sub(r"[^\w\s]", " ", re.sub(r"\*\*|__", "", correct or "").lower()).split()
    stop = {"a", "an", "the", "it", "is", "are", "its", "it's", "of", "to", "and", "in"}
    core = [w for w in plain if w not in stop]
    if core and [w for w in a if w not in stop] == core:
        return "CORRECT"                                  # said exactly the answer
    bold = [re.sub(r"[^\w\s]", " ", b.lower()).split() for b in re.findall(r"\*\*(.+?)\*\*", correct or "")]
    if len(bold) == 1 and len(core) <= 4 and bold[0] and [w for w in a if w not in stop] == [w for w in bold[0] if w not in stop]:
        return "CORRECT"                                  # a one-key-word answer ("A **moment**.") said exactly
    return None


def parse_verdict(out):
    """The judge writes KEY / MATCH / GRADE lines; read the FIRST grade (it sometimes keeps talking after)."""
    t = (out or "").rsplit("</think>", 1)[-1]
    m = re.search(r"GRADE\s*:\s*\**\s*(CORRECT|PARTLY|PARTIALLY|PARTIAL|INCORRECT|WRONG)", t, re.I)
    if m:
        v = m.group(1).upper()
    else:
        m = re.search(r"MATCH\s*:\s*\**\s*(YES|HALF|NO)\b", t, re.I)
        if m:
            v = {"YES": "CORRECT", "HALF": "PARTLY", "NO": "WRONG"}[m.group(1).upper()]
        else:
            found = re.findall(r"\b(CORRECT|PARTLY|PARTIALLY|INCORRECT|WRONG)\b", t.upper())
            v = found[0] if found else "PARTLY"
    return {"INCORRECT": "WRONG", "PARTIALLY": "PARTLY", "PARTIAL": "PARTLY"}.get(v, v)


def _plain(s):
    return re.sub(r"\*\*", "", s or "")


def _wc(s):
    return len(_plain(s).split())


def note_defs(md):
    """Key words of a set of notes: DEF lines, or "**Word**: meaning" points in older notes (like the page's lessonWords)."""
    out = []
    for line in (md or "").splitlines():
        line = line.strip()
        m = re.match(r"^DEF:\s*(.+?)\s+=\s+(.+)$", line)
        if m:
            out.append((_plain(m.group(1)).strip(), m.group(2).strip()))
    if not out:
        for line in (md or "").splitlines():
            m = re.match(r"^(?:POINT:\s*)?(?:[-*]\s*)?(?:an?\s+|the\s+)?\*\*([^*]{2,40})\*\*\s*(?::|=|\s[-–—]\s|\s(?:is|are|means)\s)\s*(.{4,})$",
                         line.strip(), re.I)
            if m:
                out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def tidy_meaning(term, m):
    """A sticky note's back: no "It is ...", balanced bold, the card's own word never bold, at most 2 bold spans."""
    m = re.sub(r"\s+", " ", m or "").strip().rstrip(".").strip()
    m = re.sub(r"(?i)^(?:it is|this is|it means|this means|means|is|are|=)\s+", "", m)
    if m.count("**") % 2:
        m = m.replace("**", "")
    m = re.sub(r"(?i)\*\*(%s)\*\*" % re.escape(term), r"\1", m)
    n = [0]

    def keep(mm):
        n[0] += 1
        return mm.group(0) if n[0] <= 2 else mm.group(1)
    m = re.sub(r"\*\*([^*]+)\*\*", keep, m)
    return m[:1].upper() + m[1:] if m and not m.startswith("**") else m


def squeeze(m):
    """Filler out of a sticky note's meaning."""
    m = re.sub(r"\s*\([^)]*\)", "", m or "")
    m = re.sub(r"(?i),?\s*\b(?:etc|and so on)\b\.?", "", m)
    m = re.sub(r"(?i)\bi\.e\.,?\s*|\be\.g\.,?\s*", "like ", m)
    return re.sub(r"\s+", " ", m).strip(" ,;")


STOP = set("about above after again against because before being below between both could does doing during each "
           "from further having into more most other over same should some such than that their them then there these "
           "they this those through under until very what when where which while with would your thing things "
           "extra people person something someone always often another among within without".split())


def auto_bold(m, term, keys):
    """The student forgot the bold: bold the lesson's key words in it (at most 2), else its longest real word."""
    if "**" in m:
        return m
    n = 0
    for k in keys:
        if n >= 2 or k == term.lower() or k in term.lower():
            continue
        m2 = re.sub(r"(?i)(^|[^\w*])(%s)(?=[^\w*]|$)" % re.escape(k), r"\1**\2**", m, count=1)
        if m2 != m and "****" not in m2:
            m, n = m2, n + 1
    if n:
        return m
    words = [x for x in re.findall(r"[A-Za-z][A-Za-z-]{4,}", m) if x.lower() not in STOP and x.lower() not in term.lower()
             and not re.search(r"(?i)(?:ly|ing|ities|ity)$", x)]
    if words:
        best = max(words, key=len)
        m = re.sub(r"(?<![\w*])%s(?![\w*])" % re.escape(best), "**%s**" % best, m, count=1)
    return m


def clip_meaning(m, cap=10):
    """Too long for a sticky note: cut it at a natural break, or give up (None)."""
    if _wc(m) <= cap:
        return m
    for sep in (";", " (", ",", " - ", " – ", " which ", " that ", " so ", " and "):
        i = m.find(sep)
        if i > 0 and 3 <= _wc(m[:i]) <= cap:
            cut = m[:i].strip()
            return cut.replace("**", "") if cut.count("**") % 2 else cut
    return None


def parse_cards(out):
    cards = []
    for line in (out or "").splitlines():
        m = re.match(r"^\s*(?:[-*]\s*)?(?:(?:CARD|SHORT|LONG)\s*\d*\s*:\s*)?(.+?)\s*=\s*(.+)$", line.strip())
        if not m:
            continue
        w = _plain(m.group(1)).strip(" -*:\"'")
        w = re.sub(r"\s*~.*$", "", w).strip()
        mean = tidy_meaning(w, re.sub(r"\s*~.*$", "", m.group(2)))
        if not w or not mean or len(w.split()) > 4 or len(w) > 40 or NOTE_THINK.search(mean) or NOTE_META.search(mean):
            continue
        if _plain(mean).lower().strip() == w.lower():
            continue
        cards.append((w, mean))
    return cards


def same_word(a, b):
    a, b = _plain(a).lower().strip(), _plain(b).lower().strip()
    if not a or not b:
        return False
    if a == b or a.rstrip("s") == b.rstrip("s"):
        return True
    return (a in b or b in a) and min(len(a), len(b)) >= 5 or similar(a, b, 0.8)


def proofread_ok(old, new):
    """The proofread kept every line, tag, fact and number: only spelling / grammar changed."""
    a, b = (old or "").splitlines(), (new or "").splitlines()
    if not new or len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x.split(":", 1)[0] != y.split(":", 1)[0]:
            return False                                  # tags must stay
        if sorted(re.findall(r"\d+(?:\.\d+)?", x)) != sorted(re.findall(r"\d+(?:\.\d+)?", y)):
            return False                                  # numbers must stay
        if x != y and not similar(x, y, 0.5):
            return False                                  # a rewrite, not a correction
        if len(y) > len(x) * 1.4 + 10:
            return False
    return True


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
    if ctype == "pick_one" and _field(text, "RIGHT"):
        # the student names the right option; the app shuffles A/B/C itself (letters were often ticked wrong)
        wrong = [E.tidy_markdown(m.strip()) for m in
                 re.findall(r"^[\s\-*#>]*\**\s*WRONG\s*\d*\s*\**\s*[:\-]\s*(?:\*\*(?=\s))?\s*(.+?)\s*$", text, re.I | re.M)]
        wrong = [w for w in wrong if w][:2]
        if len(wrong) < 2:
            return None
        opts = [_field(text, "RIGHT").strip()] + wrong
        order = random.sample(range(3), 3)
        card["choices"] = [opts[i] for i in order]
        card["correct"] = order.index(0)
        return card
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
        self.priority = 0           # grades / explanations the Teacher is waiting for right now
        self.more_writing = None    # (lesson, student, started, seconds) writing extra notes the Teacher asked for
        self.more_error = None
        self.more_jobs = []         # [(lesson, student)] writing extra notes ahead (the More notes button is instant-ish)
        self.more_fails = {}        # lesson -> extra notes that came back empty in a row (stop trying after 3)
        self.more_secs = 30.0       # how long writing extra notes takes (for the loading bar)
        self.sticky_busy = None     # (lesson, student) writing sticky notes
        self.notes_writing = None    # (lesson id, student id) while a student writes notes
        self.off_lesson = 0          # cards thrown away for using things that aren't in the lesson
        self._key_terms = {}         # lesson id -> (notes rev, key terms) for add_keys()
        self.pending_cfg = {}        # ⚙️ class timings changed during a class: applied at the next Start
        self.study_failed = set()    # students whose server didn't answer while reading the lesson
        self.paused_at = None        # ⏸ class paused while the 📝 Review tab is open
        self.pause_total = 0.0
        super().__init__()
        self.review = R.Review(self.library)
        threading.Thread(target=self._warmup, daemon=True).start()
        threading.Thread(target=self._simple_worker, daemon=True).start()
        threading.Thread(target=self._bg_worker, daemon=True).start()
        if self.lesson_id:
            threading.Thread(target=self._notes_worker, args=(self.lesson_id, self.lesson_token), daemon=True).start()

    def preparing(self):
        return bool(self.prepare and self.prepare["stage"] not in ("done", "error"))

    def _notes_done(self):
        """Every part of the lesson has its notes (and sticky-note key words) written."""
        if not self.lesson_id or self.notes_writing:
            return False
        notes = {k: v for k, v in self.library.notes(self.lesson_id).items() if v and notes_tagged(v)}
        parts = {(self.library.section(self.lesson_id, sid) or {}).get("part") for sid in self.sections}
        have = {(self.library.section(self.lesson_id, int(k)) or {}).get("part") for k in notes if k.isdigit()}
        return bool(parts) and parts <= have

    def _warmup(self):
        """While no class is running and the notes are done, write the first questions ahead (config warm_cards,
        5) so Start is instant. They still appear one at a time, at the "new card every" pace."""
        while True:
            time.sleep(1.5)
            if self.running or not self.sections or self.preparing():
                continue
            with self.lock:
                ready = sum(1 for i in self.items if i["status"] == "ready")
                busy = sum(1 for v in self.generating.values() if v)
            cands = [s for s in self.sections if s in self._idle_students()]
            if ready + busy >= int(self.cfg.get("warm_cards") or 5) or busy >= 2 or not cands or self.priority:
                continue
            if not self._notes_done():                   # notes first: they're what the Teacher reads before class
                continue
            sid = random.choice([s for s in cands if s != self.last_gen_sid] or cands)
            self.last_gen_sid = sid
            self.generating[sid] = True                  # idle students help: up to 2 write at the same time
            threading.Thread(target=self._make_item, args=(sid, WARM), daemon=True).start()

    # ------------------------------------------------------------ helpers in the background (before class)

    def _idle_students(self):
        """Online students with nothing to do right now, least busy first."""
        busy = {j[1] for j in self.more_jobs}
        for t in (self.sticky_busy, self.more_writing, self.notes_writing):
            if t:
                busy.add(t[1])
        free = [k for k in self.students if self.online.get(k) and k not in busy and not self.generating.get(k)
                and self.inflight.get(self.students[k]["port"], 0) < 1]
        return sorted(free, key=lambda k: (self.inflight.get(self.students[k]["port"], 0), random.random()))

    def _bg_worker(self):
        """Before class, once the notes are done: free students write the sticky notes (1 student) and extra
        class notes ahead (up to more_ahead, by different students) so the buttons answer quickly."""
        while True:
            time.sleep(2)
            try:
                lid = self.lesson_id
                if not lid or self.running or self.preparing() or self.priority or not self._notes_done():
                    continue
                if not self.sticky_busy and self._sticky_needs(lid):
                    free = self._idle_students()
                    if free:
                        self.sticky_busy = (lid, free[0])
                        threading.Thread(target=self._sticky_job, args=(lid, free[0]), daemon=True).start()
                        continue
                pool = self._more_pool(lid)
                extras = sum(1 for k in self.library.notes(lid) if re.match(r"^x\d+-s\d+$", k))
                jobs = [j for j in self.more_jobs if j[0] == lid]
                if len(pool) + len(jobs) < int(self.cfg.get("more_ahead") or 3) and extras + len(pool) < 12 \
                        and self.more_fails.get(lid, 0) < 3:
                    free = self._idle_students()
                    if free:
                        job = (lid, free[0])
                        self.more_jobs.append(job)
                        threading.Thread(target=self._more_pool_job, args=(job,), daemon=True).start()
            except Exception:                            # noqa: BLE001 - try again next round
                pass

    # ---- 🗒 sticky notes: short meanings (3-8 key words), 12 on the board, + adds 2 more (up to sticky_max)

    def _stickies(self, lid):
        st = self.library.read_json(lid, "stickies.json", None) or {}
        st.setdefault("cards", [])
        st.setdefault("shown", 12)
        return st

    def _note_terms(self, lid):
        """Every key word in the notes, in the order of the parts (then the extra notes)."""
        notes = self.library.notes(lid)
        keys = [str(s) for s in sorted(self.students)] + sorted((k for k in notes if re.match(r"^x\d+-s\d+$", k)),
                                                               key=lambda k: int(k[1:k.index("-")]))
        out, seen, parts = [], set(), set()
        for k in keys:
            if k.isdigit():
                part = (self.library.section(lid, int(k)) or {}).get("part")
                if part in parts:
                    continue
                parts.add(part)
            for w, m in note_defs(notes.get(k)):
                if m and not any(same_word(w, x) for x in seen):   # "Primary" and "Primary sector": one card
                    seen.add(w.lower())
                    out.append((w, m))
        return out

    def _lesson_text(self, lid, limit=2200):
        try:
            with open(self.library.path(lid, "source.txt"), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return ""
        words = text.split()
        if len(words) > limit:
            start = random.randrange(0, len(words) - limit + 200)
            text = " ".join(words[start:start + limit - 200])
        return text

    def _sticky_needs(self, lid):
        st = self._stickies(lid)
        have = {c["w"].lower() for c in st["cards"]}
        first = [w for w, _ in self._note_terms(lid)[:12]]
        if any(w.lower() not in have for w in first):
            return True
        return len(st["cards"]) < int(self.cfg.get("sticky_max") or 20) and not st.get("done")

    def _sticky_job(self, lid, sid):
        t0 = time.time()
        try:
            cap = int(self.cfg.get("sticky_max") or 20)
            st = self._stickies(lid)
            terms = self._note_terms(lid)
            have = {c["w"].lower() for c in st["cards"]}
            if any(w.lower() not in have for w, _ in terms[:12]):
                st = {"cards": [], "shown": st.get("shown", 12)}          # the notes changed: a new board
                have = set()
            system = "You are %s, a student who makes short, clear flash cards. You use ONLY the lesson." % self.students[sid]["name"]
            keys = self._bold_words(lid)
            todo = [(w, m) for w, m in terms if w.lower() not in have][:max(0, cap - len(st["cards"]))]
            for chunk in (todo[:12], todo[12:]):                        # the board's 12 first, then the rest
                if chunk:
                    st["cards"] += [{"w": w, "m": m} for w, m in self._shorten(sid, chunk, keys)]
                    self._save_stickies(lid, st)
            need = cap - len(st["cards"])
            if need > 0:                                               # new key words the notes don't have yet
                text = self._lesson_text(lid, 1800)
                words = [c["w"] for c in st["cards"]] + [w for w, _ in terms]
                try:
                    with open(self.library.path(lid, "source.txt"), encoding="utf-8") as f:
                        full = f.read()
                except OSError:
                    full = text
                norm = " %s " % E._norm_words(full)
                ideas = []                                             # words the students bolded but no card has yet
                bold = " ".join([(self.library.section(lid, s) or {}).get("content") or "" for s in sorted(self.students)] +
                                list(self.library.notes(lid).values()))
                for b in re.findall(r"\*\*([^*]{4,40})\*\*", bold):
                    b = b.strip(" .,:;")
                    if len(b.split()) <= 3 and b.lower() not in STOP and " %s " % E._norm_words(b) in norm and \
                            not any(same_word(b, x) for x in words + ideas):
                        ideas.append(b)
                out = self._raw_ask(sid, system, E.fill(E.read_skill("sticky_more"), lesson=self.lesson, text=text,
                                                         have="\n".join("- " + w for w in words),
                                                         ideas="\n".join("- " + w for w in ideas[:10]) or "- (none)",
                                                         count=min(need + 4, 10)), 0, 600)
                new = []
                for w, m in parse_cards(out):
                    if len(st["cards"]) + len(new) >= cap or any(same_word(w, x) for x in words):
                        continue
                    if " %s " % E._norm_words(w) not in norm:            # only words the lesson really uses
                        continue
                    new.append((w, m))
                    words.append(w)
                st["cards"] += [{"w": w, "m": m} for w, m in self._shorten(sid, new, keys) if _wc(m) >= 2]
                st["tries"] = 0 if new else st.get("tries", 0) + 1
                if st["tries"] >= 2:
                    st["done"] = True                                  # nothing new left to find
                self._save_stickies(lid, st)
        except Exception:                                              # noqa: BLE001
            pass
        finally:
            self.sticky_busy = None
            self.notes_rev += 1
            self._log({"type": "stickies", "student": sid, "seconds": round(time.time() - t0, 1)})

    def _bold_words(self, lid):
        """The lesson's important words: everything bold in the notes, plus their key words."""
        keys = set()
        for md in self.library.notes(lid).values():
            keys.update(_plain(k).strip().lower() for k in re.findall(r"\*\*([^*]{3,40})\*\*", md or ""))
        keys.update(w.lower() for w, _ in self._note_terms(lid))
        return sorted((k for k in keys if len(k) >= 4), key=len, reverse=True)

    def _shorten(self, sid, cards, keys):
        """Sticky-note backs: 3-7 key words (a student shortens the long ones), key words in bold."""
        long = [(w, m) for w, m in cards if _wc(m) > 7]
        got = {}
        if long:
            try:
                got = {w.lower(): m for w, m in parse_cards(self._raw_ask(
                    sid, "You shorten flash cards. You keep the facts.",
                    E.fill(E.read_skill("sticky_short"), cards="\n".join("LONG: %s = %s" % (w, _plain(m)) for w, m in long)),
                    0, 500))}
            except Exception:                              # noqa: BLE001
                got = {}
        out = []
        for w, m in cards:
            nm = got.get(w.lower())
            m = nm if nm and 2 <= _wc(nm) <= 9 else (clip_meaning(m) or m)
            out.append((w, auto_bold(tidy_meaning(w, squeeze(m)), w, keys)))
        return out

    def _save_stickies(self, lid, st):
        with self.library.lock:
            old = self.library.read_json(lid, "stickies.json", None) or {}
            st["shown"] = max(st.get("shown", 12), old.get("shown", 12))
            want = old.get("want", 0)
            if want:
                st["shown"] = max(st["shown"], min(want, len(st["cards"])))
                st["want"] = want if want > len(st["cards"]) and not st.get("done") else 0
            self.library.write_json(lid, "stickies.json", st)
        self.notes_rev += 1

    def more_stickies(self, lid=None):
        """The + sticky note: 2 more on the board (written ahead, so usually instant), up to sticky_max."""
        lid = lid or self.lesson_id
        if not lid or not self.library.meta(lid):
            return {"ok": False, "error": "Pick a lesson first."}
        cap = int(self.cfg.get("sticky_max") or 20)
        with self.library.lock:
            st = self._stickies(lid)
            target = min(cap, st["shown"] + 2)
            if st["shown"] >= cap:
                return {"ok": False, "error": "That's all the sticky notes (%d)." % cap}
            if len(st["cards"]) >= target:
                st["shown"] = target
                self.library.write_json(lid, "stickies.json", st)
                ready = True
            elif st.get("done") and len(st["cards"]) > st["shown"]:
                st["shown"] = len(st["cards"])
                self.library.write_json(lid, "stickies.json", st)
                ready = True
            elif st.get("done"):
                return {"ok": False, "error": "No more key words in this lesson."}
            else:
                st["want"] = target
                self.library.write_json(lid, "stickies.json", st)
                ready = False
        self.notes_rev += 1
        if not ready and not self.sticky_busy:
            free = self._idle_students() or [k for k in self.students if self.online.get(k)]
            if not free:
                return {"ok": False, "error": "The students are offline. Turn them on in ⚙️ Settings."}
            self.sticky_busy = (lid, free[0])
            threading.Thread(target=self._sticky_job, args=(lid, free[0]), daemon=True).start()
        return {"ok": True, "ready": ready}

    def _sticky_view(self, lid):
        st = self._stickies(lid)
        cap = int(self.cfg.get("sticky_max") or 20)
        sb = self.sticky_busy
        return {"cards": st["cards"][:st["shown"]], "max": cap,
                "can_more": st["shown"] < cap and (len(st["cards"]) > st["shown"] or not st.get("done")),
                "writing": bool(sb and sb[0] == lid and st.get("want"))}

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
            self.cfg.update(self.pending_cfg)                # ⚙️ timings changed during the last class
            self.pending_cfg = {}
            self.cfg["question_interval_seconds"] = max(int(self.cfg["question_interval_seconds"]), self.min_interval())
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
            self.paused_at, self.pause_total = None, 0.0
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
            self.paused_at = None
        stats = self.stats()
        try:
            E.save_config(dict(self.cfg, **self.pending_cfg))   # keeps the measured card speed
        except OSError:
            pass
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
        pool = [{"sid": i["sid"], "question": self._question_for_judge(i), "answer": i["answer"],
                 "key": i.get("orig_key") or R.key_for(i["question"])}
                for i in self.items if i["type"] not in ("second_chance",)
                and (i["status"] == "timeout" or i.get("verdict") in ("WRONG", "PARTLY"))]
        if not pool and self.lesson_id:                      # earlier classes: the 📝 Review list (missed + ⭐ starred)
            pool = [{"sid": e["sid"], "question": e.get("judge_q") or e["question"], "answer": e.get("answer", ""),
                     "key": e["key"]}
                    for e in self.review.pool(self.lesson_id, **self._rv_ctx()) if e["sid"] in self.sections]
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
        shift_seen = self.pause_total
        while self._alive(g):
            time.sleep(0.1)
            if self.paused_at:                               # ⏸ nothing new while the class is paused
                continue
            if self.pause_total != shift_seen:               # just resumed: the next card keeps its place in line
                next_at += self.pause_total - shift_seen
                shift_seen = self.pause_total
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
        time.sleep(2.8)          # the start animation plays first: the GPU is shared with the app window
                                 # (the cards written before class are shown meanwhile)
        while self._alive(g):
            time.sleep(0.3)
            with self.lock:
                busy = [s for s, v in self.generating.items() if v]
                ahead = sum(1 for i in self.items if i["status"] == "ready")
                last_card_sid = self.items[-1]["sid"] if self.items else None
            if ahead + len(busy) >= int(self.cfg.get("hidden_ahead") or 10) or len(busy) >= int(self.cfg["max_parallel_generation"]):
                continue
            if self.priority:                            # the Teacher is waiting (grade / explanation): no new card yet
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
            if self.streak >= 3 and not streak_ready and not self.cfg.get("calm_mode") \
                    and random.random() < float(self.cfg.get("streak_card_chance") or 0):
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
        t_start = time.time()
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
                ctype, idea = kind, self._next_fact(sid)
            else:
                ctype = self._pick_type()
                idea = self._next_fact(sid)                  # one fact: the question asks about it, the answer says it
                ctype = self._fit_type(ctype, idea)
            keyword = ""
            if ctype == "lightning":
                kf = self._keyword_fact(sid)
                if kf:
                    keyword, idea = kf
                else:
                    ctype = "fill_blank"                     # no clear key word to ask for: a fill-in card instead
            rule = E.fill(types.get(ctype, ""), topic=self.topic(sid), keyword=keyword,
                          other_topic=self.topic(other) if other else "",
                          other_notes=self.sections.get(other, {}).get("content", "") if other else "",
                          orig_question=(extra or {}).get("question", ""), orig_answer=(extra or {}).get("answer", ""))
            task = E.fill(E.read_skill("make_question"), topic=self.topic(sid), idea=idea,
                          type_name=TYPE_LABELS.get(ctype, ctype).split(" ", 1)[-1], type_rule=rule)
            card = None
            for attempt in range(3):
                t = task if not attempt else task + "\n\nYour last card broke a rule. Write a DIFFERENT card this time."
                card = self._finish_card(parse_card(self._ask(sid, t, budget), ctype), ctype)
                if card and keyword:
                    card["keyword"] = keyword
                if card and not self._fits_fact(card, ctype, idea):
                    card = None                              # the question or answer drifted away from the fact
                if card:
                    break
            if card and ctype == "spot_mistake":
                points = [re.sub(r"^-\s*|\*\*", "", l) for l in self.sections.get(sid, {}).get("content", "").splitlines()]
                if any(similar(card["question"], p, 0.8) for p in points if p):
                    card = None                              # it's a TRUE sentence from the notes: no mistake to spot
            if card:
                terms = self.key_terms()
                card["answer"] = add_keys(card["answer"], terms, 3)
                if "**" not in card["question"] and ctype not in ("fill_blank", "spot_mistake"):
                    card["question"] = add_keys(card["question"], terms, 1,
                                                avoid=re.findall(r"\*\*(.+?)\*\*", card["answer"]))
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
                            teacher_answer="", verdict=None, reaction=None, more=[], lid=self.lesson_id,
                            orig_key=(extra or {}).get("key"))
                self.item_next += 1
                self.items.append(item)
                self._record_card_time(time.time() - t_start)   # ⚙️ how fast cards can come (min "new card every")
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
        q = E.QUESTION_SOURCE.sub("", q).strip()
        q = re.sub(r"\s+([?.])", r"\1", q)
        a = re.sub(r"(?<=[.!])\s+[^.!?]*\?\s*$", "", a).strip()     # drop a question tacked on after the answer
        a = " ".join(s for s in _sentences(a) if not ANSWER_ECHO.search(re.sub(r"\*\*", "", s)))
        if not a:
            return None                                  # the instructions leaked into the answer itself
        if q and self._confusing(q, ctype):
            return None
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
            r, w = (re.sub(r"\b(the )?teacher (says?|said|told us|thinks)( that)?\s*", "", x, flags=re.I).strip() for x in (r, w))
            r, w = (x[:1].upper() + x[1:] for x in (r, w))
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
            # The student's own pick stays the right one (a bold word in the answer used to re-tick another option:
            # "a **limit** ... the **slope** at a point" ticked "The slope at one point"). Unclear cards are rejected.
            ch, ok = card["choices"], card["correct"]
            words = [_content_words(c) for c in ch]
            for i in range(3):
                for j in range(i + 1, 3):
                    if (words[i] and words[i] == words[j]) or similar(ch[i], ch[j], 0.85):
                        return None                          # two options say the same thing ("F × d" / "d × F")
            a = " ".join(s for s in _sentences(a) if not re.search(r"\b(option|answer|choice)\s*\(?[ABC]\)?(?![\w])", s))
            if not a:
                return None                                  # "so option A is right": the letters are shuffled
            card["answer"] = a
            aw, nums = _content_words(a), set(re.findall(r"\d+(?:\.\d+)?", a))
            score = [len(words[i] & aw) + len(set(re.findall(r"\d+(?:\.\d+)?", ch[i])) & nums) for i in range(3)]
            if any(score[i] > score[ok] for i in range(3) if i != ok):
                return None                                  # the explanation points at a wrong option
            if score[ok] == 0 and (words[ok] or re.search(r"\d", ch[ok])):
                return None                                  # the explanation doesn't back the right option at all
        return card

    CAUSE = re.compile(r"\b(because|so that|so|helps?|helping|in order to|causes?|caused|leads? to|makes?|"
                       r"allows?|lets|when|if|therefore|as a result|to (make|pay|help|grow|get|keep|stop|protect|reduce|"
                       r"increase|save|provide|produce|create))\b", re.I)
    COMPARE = re.compile(r"\b(while|whereas|but|unlike|difference|differ|than|vs|versus|compared|both|instead)\b", re.I)

    def _fit_type(self, ctype, fact):
        """A "why" or "what if" card needs a fact that gives a reason; a "compare" card needs two things side by side.
        Otherwise the student invents a reason ("Why does option B cost more?"), so a recall card is used instead."""
        plain = re.sub(r"\*\*|__", "", fact or "")
        if ctype in ("explain_why", "what_if", "silver", "streak") and not self.CAUSE.search(plain):
            return random.choice(["pick_one", "fill_blank", "lightning"]) if ctype in ("explain_why", "what_if") else ctype
        if ctype == "compare" and not self.COMPARE.search(plain):
            return random.choice(["pick_one", "fill_blank"])
        return ctype

    def _keyword_fact(self, sid):
        """⚡ Lightning: a key point that names a clear key word ("**Evaporation** is when water turns into vapour"),
        so the question can simply ask for that word."""
        lines = [re.sub(r"^\s*[-*•]\s*", "", l).strip() for l in self.sections.get(sid, {}).get("content", "").splitlines()]
        cands = []
        for l in lines:
            m = re.search(r"\*\*(.+?)\*\*", l)
            if not m or len(m.group(1).split()) > 3 or len(l) < 25:
                continue
            term = m.group(1).strip()
            rest = re.sub(r"\*\*|__", "", l)
            if re.search(r"^\s*(the\s+)?%s\s+(is|are|means|was|were|includes?|consists? of|refers to)\b" % re.escape(term), rest, re.I) \
                    or re.search(r"\b(called|known as|named)\s+%s\b" % re.escape(term), rest, re.I):
                cands.append((term, rest))
        if not cands:
            return None
        used = self.fact_used.setdefault(("kw", sid), set())
        fresh = [c for c in cands if c[0] not in used] or cands
        term, fact = random.choice(fresh)
        used.add(term)
        return term, fact

    def _fits_fact(self, card, ctype, fact):
        """The card must be about its fact: the answer says the fact, the question asks about it.
        ⚡ Lightning cards must be easy: one short answer, never a list or a why/how."""
        if ctype in ("challenge", "second_chance", "boss", "infected") or not fact:
            return True
        padded = " %s " % E._norm_words(fact)
        q, a = re.sub(r"\*\*|__", "", card["question"]), card["answer"]
        if not self._from_text(a, padded, 0.45):
            return False                                     # the answer talks about something else
        if ctype not in ("spot_mistake", "fill_blank") and not self._from_text(q, padded, 0.25):
            return False                                     # the question isn't about this fact
        if ctype == "lightning":
            if re.match(r"^\s*(why|how|explain|describe|compare|what is the difference|what would happen)\b", q, re.I):
                return False
            if re.search(r",.*\band\b|\b(list|name (all|three|four|the \w+ )|all the)\b", q, re.I):
                return False                                 # a list is not a 10-second question
            m = re.match(r"^\s*\*\*(.+?)\*\*", a)
            if not m or len(m.group(1).split()) > 3:
                return False                                 # the answer must start with a 1-3 word **answer**
            if card.get("keyword") and E._norm_words(card["keyword"]) not in E._norm_words(m.group(1)) \
                    and E._norm_words(m.group(1)) not in E._norm_words(card["keyword"]):
                return False                                 # it asked for a different word than the key word
        return True

    def _about(self, text, it, on_topic):
        """Is the explanation about this card? It names the answer's key word (examples bring in new everyday words,
        so word overlap alone isn't enough), or most of its words come from the question, answer and fact."""
        terms = re.findall(r"\*\*(.+?)\*\*", it.get("answer") or "") + [it.get("keyword") or ""]
        plain = " %s " % E._norm_words(text)
        if any(len(E._norm_words(t)) > 2 and " %s " % E._norm_words(t) in plain for t in terms):
            return True
        return self._from_text(text, on_topic, 0.3)

    @staticmethod
    def _confusing(q, ctype):
        """Questions that confuse a child: they talk about "the text", repeat their own key phrase
        ("How does business activity ... using business activity?"), or mix two questions into one."""
        plain = re.sub(r"\*\*|__", "", q)
        if E.QUESTION_META.search(plain):
            return True
        if ctype not in ("spot_mistake", "fill_blank") and (plain.count("?") > 1 or not plain.rstrip().endswith("?")):
            return True
        if re.match(r"^what would happen if\b", plain, re.I) and re.search(r"\b(which|what|who|where|when|how)\b", plain[18:], re.I):
            return True
        words = [w for w in re.findall(r"[a-z]+", plain.lower()) if w not in STOP and len(w) > 2]
        pairs = list(zip(words, words[1:]))
        return len(pairs) != len(set(pairs))              # the same two-word phrase twice

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
        notes = {k: (clean_notes(v) if notes_tagged(v) else v) for k, v in self.library.notes(lid).items()}   # tidy older notes
        parts, seen = [], set()
        for sid in sorted(self.students):
            sec = self.library.section(lid, sid) or {}
            if not sec or sec.get("part") in seen:       # short lessons: students share a part, show it once
                continue
            seen.add(sec.get("part"))
            st = self.students[sid]
            parts.append({"sid": sid, "name": st["name"], "emoji": st.get("emoji", ""), "part": sec.get("part"),
                          "title": sec.get("title") or "Part %s" % sec.get("part"), "md": notes.get(str(sid))})
        for key in sorted((k for k in notes if re.match(r"^x\d+-s\d+$", k)), key=lambda k: int(k[1:k.index("-")])):
            esid = int(key.rsplit("-s", 1)[1])
            st = self.students.get(esid) or {}
            parts.append({"sid": esid, "name": st.get("name", ""), "emoji": st.get("emoji", ""), "part": "+",
                          "title": parse_note_title(notes[key]) or "More notes", "md": notes[key], "extra": key})
        w = self.notes_writing
        mw = self.more_writing
        mine = mw and mw[0] == lid
        return {"ok": True, "id": lid, "title": meta.get("title"), "status": meta.get("status"), "parts": parts,
                "more_writing": mw[1] if mine else None, "more_error": self.more_error,
                "more_elapsed": round(time.time() - mw[2], 2) if mine else 0, "more_eta": mw[3] if mine else 0,
                "stickies": self._sticky_view(lid),
                "words": meta.get("words"),
                "active": lid == self.library.active(), "studied": bool(meta.get("studied")),
                "writing": w[1] if w and w[0] == lid else None}

    def _proofread(self, sid, md, source=""):
        """Spelling and grammar check of fresh notes by a student (background, no thinking)."""
        try:
            out = self._raw_ask(sid, "You are a careful proofreader. You fix spelling and grammar only.",
                                E.fill(E.read_skill("proofread_notes"), notes=md), 0, 1600)
            fixed = clean_notes(out, source)
            return fixed if proofread_ok(md, fixed) else md
        except Exception:
            return md

    def more_notes(self, lid=None):
        """📒 The Teacher asked for more notes. Usually one was written ahead (by a free student): it appears after a
        short pause. Otherwise a free student writes it now. Extra sections are kept (key "x<n>-s<sid>") until the
        Teacher deletes them."""
        lid = lid or self.lesson_id
        if not lid or not self.library.meta(lid):
            return {"ok": False, "error": "Pick a lesson first."}
        if self.more_writing:
            return {"ok": False, "error": "%s is already writing more notes." % self.students[self.more_writing[1]]["name"]}
        covered = self._covered_titles(lid, pool=False)
        item = None
        with self.library.lock:
            pool = self._more_pool(lid)
            while pool and not item:
                it = pool.pop(0)
                t = parse_note_title(it.get("md"))
                if it.get("md") and not any(t and similar(t, c, 0.7) for c in covered):
                    item = it
            self.library.write_json(lid, "more_pool.json", pool)
        if item:
            sid = item.get("sid") if item.get("sid") in self.students else next(iter(self.students))
            eta = round(random.uniform(1.6, 2.3), 2)
            self.more_writing = (lid, sid, time.time(), eta)
            threading.Thread(target=self._more_reveal, args=(lid, sid, item["md"], eta), daemon=True).start()
            return {"ok": True, "sid": sid, "name": self.students[sid]["name"], "eta": eta, "ready": True}
        cands = [k for k in self.students if self.online.get(k)]
        if not cands:
            return {"ok": False, "error": "The students are offline. Turn them on in ⚙️ Settings."}
        free = self._idle_students()
        sid = free[0] if free else min(cands, key=lambda k: (self.inflight.get(self.students[k]["port"], 0),
                                                            bool(self.generating.get(k)), random.random()))
        self.more_writing = (lid, sid, time.time(), round(self.more_secs, 1))
        threading.Thread(target=self._more_notes_worker, args=(lid, sid), daemon=True).start()
        return {"ok": True, "sid": sid, "name": self.students[sid]["name"], "eta": round(self.more_secs, 1), "ready": False}

    def _more_pool(self, lid):
        return [p for p in (self.library.read_json(lid, "more_pool.json", []) or []) if isinstance(p, dict)]

    def _covered_titles(self, lid, pool=True):
        out = [parse_note_title(v) for v in self.library.notes(lid).values()]
        if pool:
            out += [parse_note_title(p.get("md")) for p in self._more_pool(lid)]
        return [t for t in out if t]

    def _save_extra(self, lid, sid, md):
        with self.library.lock:
            n = self.library.notes(lid)
            k = 1 + max([int(m.group(1)) for m in (re.match(r"x(\d+)-", key) for key in n) if m] or [0])
            n["x%d-s%d" % (k, sid)] = md
            self.library.write_json(lid, "notes.json", n)

    def _more_reveal(self, lid, sid, md, eta):
        try:
            time.sleep(eta)                               # a short "writing" moment, so it doesn't just pop in
            self._save_extra(lid, sid, md)
            self.more_error = None
        finally:
            self.more_writing = None
            self.notes_rev += 1

    def _write_more_notes(self, lid, sid):
        """One new section of notes about something the notes don't cover yet ("" if nothing new came out)."""
        meta = self.library.meta(lid) or {}
        secs = [self.library.section(lid, s) or {} for s in sorted(self.students)]
        secs = [s for s in secs if s.get("source")]
        text, focus = self._lesson_text(lid, 2200), ""
        if len(secs) > 1:                                 # each writer looks at a different part: new ideas, not twins
            self._more_turn = getattr(self, "_more_turn", random.randrange(len(secs))) + 1
            sec = secs[self._more_turn % len(secs)]
            if L.words(sec["source"]) >= 120:
                text = sec["source"] if L.words(sec["source"]) <= 2200 else " ".join(sec["source"].split()[:2200])
                focus = "Choose your idea from the part about: %s" % (sec.get("title") or "this part")
        covered = self._covered_titles(lid)
        task = E.fill(E.read_skill("more_notes"), lesson=meta.get("title") or self.lesson, text=text, focus=focus,
                      covered="\n".join("- " + c for c in covered) or "- (nothing yet)")
        for _ in range(3):
            raw = self._raw_ask(sid, "You are %s, a kind student who writes clear notes for a child. "
                                     "You use ONLY the lesson you are given." % self.students[sid]["name"],
                                task, 0, int(self.cfg.get("max_tokens_notes") or 1600))
            # the student often writes several sections (the first one a copy of a section we have): keep the new ones
            chunks = re.split(r"(?m)^(?=\s*(?:#{1,2}\s|TITLE:))", raw or "")
            covered, found = self._covered_titles(lid), []
            for ch in chunks:
                md = clean_notes(ch, text)
                title = parse_note_title(md)
                if len(md) > 60 and notes_tagged(md) and not LEAK.search(md) and title and \
                        not any(similar(title, c, 0.7) for c in covered):
                    found.append(md)
                    covered.append(title)
                if len(found) >= 2:
                    break
            if found:
                return [self._proofread(sid, md, text) for md in found]
        return []

    def _more_notes_worker(self, lid, sid):
        t0 = time.time()
        try:
            found = self._write_more_notes(lid, sid)
            if found:
                self._save_extra(lid, sid, found[0])
                if found[1:]:                             # a second new section: kept for the next click
                    with self.library.lock:
                        self.library.write_json(lid, "more_pool.json",
                                                self._more_pool(lid) + [{"md": md, "sid": sid} for md in found[1:]])
                self.more_error = None
                self.more_secs = round(0.6 * self.more_secs + 0.4 * (time.time() - t0), 1)
            else:
                self.more_error = "%s couldn't find anything new to add. Try again." % self.students[sid]["name"]
        except Exception:                                 # noqa: BLE001
            self.more_error = "Something went wrong writing the notes. Try again."
        finally:
            self.more_writing = None
            self.notes_rev += 1

    def _more_pool_job(self, job):
        lid, sid = job
        t0 = time.time()
        try:
            found = self._write_more_notes(lid, sid)
            if found:
                with self.library.lock:
                    pool = self._more_pool(lid)
                    for md in found:
                        t = parse_note_title(md)
                        if not any(similar(t, parse_note_title(p.get("md")), 0.7) for p in pool):
                            pool.append({"md": md, "sid": sid})
                    self.library.write_json(lid, "more_pool.json", pool)
                self.more_fails[lid] = 0
                self.more_secs = round(0.6 * self.more_secs + 0.4 * (time.time() - t0), 1)
            else:
                self.more_fails[lid] = self.more_fails.get(lid, 0) + 1
        except Exception:                                 # noqa: BLE001
            self.more_fails[lid] = self.more_fails.get(lid, 0) + 1
        finally:
            if job in self.more_jobs:
                self.more_jobs.remove(job)

    def delete_note(self, lid, key):
        """Only the extra notes the Teacher asked for can be deleted (never the 5 parts)."""
        if not re.match(r"^x\d+-s\d+$", key or ""):
            return {"ok": False, "error": "These notes can't be deleted."}
        with self.library.lock:
            n = self.library.notes(lid)
            if key not in n:
                return {"ok": False, "error": "Already gone."}
            del n[key]
            self.library.write_json(lid, "notes.json", n)
        self.notes_rev += 1
        return {"ok": True}

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
        if r.get("ok"):
            self.review.forget_lesson(lid)
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
            self.study_failed = set()
            for _ in range(120):                             # the students may still be starting up: wait up to 60 s
                if all(self.online.get(s) for s in self.sections) or tok != self.lesson_token:
                    break
                if _ == 0:
                    P["msg"] = "Waiting for the students to come online…"
                time.sleep(0.5)
            if not any(self.online.get(s) for s in self.sections):
                P.update(stage="error", msg="The students are offline. Run start_students.bat, wait until they're ready, "
                                            "then select the lesson again.")
                return
            P["msg"] = "The students are reading the lesson…"
            workers = [threading.Thread(target=self._study, args=(lid, sid, tok), daemon=True) for sid in self.sections]
            for w in workers:
                w.start()
            for w in workers:
                w.join()
            if tok != self.lesson_token:
                return
            if self.study_failed:
                names = ", ".join(self.students[s]["name"] for s in sorted(self.study_failed))
                P.update(stage="error", msg="%s couldn't read the lesson (no answer from the student server). Check the "
                                            "students are running, then select the lesson again." % names)
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
            replied = False
            system = ("You are %s, a careful student. You read the text you are given and use ONLY what it says." % st["name"])
            for k, piece in enumerate(ps):
                if tok != self.lesson_token:
                    return
                n_points = max(4, min(10, L.words(piece) // 35))
                task = E.fill(E.read_skill("study_part"), lesson=self.lesson, name=st["name"], piece=k + 1,
                              pieces=len(ps), text=piece, points=n_points, questions=5 if k == 0 else 3)
                for attempt in range(2):
                    raw = self._raw_ask(sid, system, task, self.cfg.get("thinking_budget_study", 0),
                                        int(self.cfg.get("max_tokens_study") or 900))
                    replied = replied or bool(raw)
                    t, pts, q = parse_study(raw)
                    if pts:
                        break
                padded = " %s " % E._norm_words(piece + " " + self.lesson)
                title = title or t
                points += [p for p in pts if self._from_text(p, padded)]
                qs += [x for x in q if self._from_text(x, padded, 0.4)]
                P["students"][key] = (k + 1) / len(ps)
                self._prep_pct()
            if not replied:                               # the student's server didn't answer: NOT studied, try again later
                self.study_failed.add(sid)
                return
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
                if str(sid) in notes and not LEAK.search(notes[str(sid)]) and notes_tagged(notes[str(sid)]):
                    done_parts.add(sec.get("part"))
                    continue                  # (old-style notes or leaked thinking get written again)
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
                                                   int(self.cfg.get("max_tokens_notes") or 1600)), text)
                    if len(md) > 60 and not LEAK.search(md) and notes_tagged(md):
                        break
                md = self._proofread(sid, md, text) if md else md
                if md and tok == self.lesson_token:
                    self.library.save_note(lid, sid, md)
                    done_parts.add(sec.get("part"))
                    self.notes_rev += 1
            self._proofread_old(lid, tok)
        finally:
            if self.notes_writing and self.notes_writing[0] == lid:
                self.notes_writing = None
                self.notes_rev += 1

    def _proofread_old(self, lid, tok):
        """Notes written before the spelling check existed get one proofread each (remembered in proofread.json)."""
        done = set(self.library.read_json(lid, "proofread.json", []) or [])
        for key, md in list(self.library.notes(lid).items()):
            if tok != self.lesson_token or self.running:
                return
            h = hashlib.md5((md or "").encode("utf-8")).hexdigest()
            if h in done or not notes_tagged(md):
                continue
            m = re.search(r"s?(\d+)$", key)
            sid = int(m.group(1)) if m and int(m.group(1)) in self.students else next(iter(self.students))
            if not self.online.get(sid):
                continue
            fixed = self._proofread(sid, clean_notes(md))
            with self.library.lock:
                n = self.library.notes(lid)
                if n.get(key) == md:
                    n[key] = fixed
                    self.library.write_json(lid, "notes.json", n)
            done.update({h, hashlib.md5(fixed.encode("utf-8")).hexdigest()})
            self.library.write_json(lid, "proofread.json", sorted(done))
            if fixed != md:
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
        if self.cfg.get("calm_mode"):
            return
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
        if self.cfg.get("calm_mode"):
            return
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
        v = self._grade(it["sid"], q["q"], q["a"], text)
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
        self._review_record(it, it["verdict"])
        self._log({"type": "boss_result", "id": it["id"], "verdict": it["verdict"]})

    @staticmethod
    def _right_answer(it):
        """What the explanation must explain: for a pick-one card, the right option itself plus why."""
        if it.get("type") == "pick_one" and it.get("choices") and isinstance(it.get("correct"), int):
            return 'The right option is "%s". %s' % (it["choices"][it["correct"]], it["answer"])
        return it["answer"]

    def _question_for_judge(self, it):
        if it["type"] == "spot_mistake":
            return 'What is wrong in this statement, and what is correct: "%s"' % it["question"]
        if it["type"] == "fill_blank":
            return 'Fill in the blank: "%s"' % it["question"]
        if it["type"] == "whos_right":
            return '%s Who is right: %s' % (it["question"], " or ".join('%s ("%s")' % (c["name"], c["text"]) for c in it["claims"]))
        return it["question"]

    def _grade(self, sid, question, correct, answer):
        """CORRECT / PARTLY / WRONG in well under a second: obvious answers locally, the rest with a 3-line check
        (no thinking: KEY / MATCH / GRADE). New cards wait meanwhile, so the GPU is free for this."""
        v = quick_verdict(answer, correct)
        if v:
            return v
        stop = {"the", "and", "its", "that", "this", "for", "with", "are", "was", "what", "which", "why", "how", "does", "you"}
        words = lambda t: {w for w in re.findall(r"[a-z0-9]+", re.sub(r"\*\*|__", "", t or "").lower()) if len(w) > 2 and w not in stop}
        mine, asked, right = words(answer), words(question), words(correct)
        if mine and mine <= asked and not (mine & right):
            return "WRONG"                                # only repeats words from the question
        self.priority += 1
        try:
            out = self._ask(sid, E.fill(E.read_skill("judge_answer"), question=question, correct=correct, answer=answer),
                            0, any_port=True, max_tokens=int(self.cfg.get("max_tokens_judge") or 80))
        finally:
            self.priority = max(0, self.priority - 1)
        return parse_verdict(out)

    def _judge_item(self, it, g):
        q = self._question_for_judge(it)
        if not it["verdict"]:
            it["verdict"] = self._grade(it["sid"], q, it["answer"], it["teacher_answer"])
            with self.lock:
                self._apply_streak(it)
                self._zombie_cure_check(it)
        verdict = it["verdict"]
        self._review_record(it, verdict)
        if it["type"] not in SPECIAL:
            self._record_result(it["sid"], it["idea"], verdict)
        self._prefetch_more(it, 2)
        self._log({"type": "answer", "id": it["id"], "student": it["sid"], "card": it["type"], "question": it["question"],
                   "correct": it["answer"], "teacher": it["teacher_answer"], "verdict": verdict})
        # (no opinion reactions: the panel shows the automatic explanation instead)

    def _auto_explain(self, it):
        """The explanation shown under the answer: why/how, no opinion about the Teacher's answer."""
        it["explaining"] = True
        try:
            self._auto_explain_work(it)
        finally:
            it["explaining"] = False

    def _auto_explain_work(self, it):
        task = E.fill(E.read_skill("auto_explain"), question=self._question_for_judge(it), correct=self._right_answer(it),
                      fact=it.get("idea") or it["answer"])
        on_topic = " %s " % E._norm_words(it["answer"] + " " + (it.get("idea") or "") + " " + self._question_for_judge(it))
        text, best = "", ""
        for _ in range(3):
            urgent = it.get("status") == "answered"        # the Teacher is waiting for this one
            if urgent:
                self.priority += 1
            try:
                raw = self._ask(it["sid"], task, self.cfg.get("thinking_budget_cards", 0), any_port=True, max_tokens=300)
            finally:
                if urgent:
                    self.priority = max(0, self.priority - 1)
            text = E.keep_key_styles(E.clean(raw, self.names, limit=420), self.vocab)
            shown = [it["answer"], it["question"]] + [c.get("text", "") for c in it.get("claims") or []]
            text = clean_explanation(text, shown)        # no "Question: ... Answer: ...", nothing already on screen
            if len((text or "").split()) < 8:
                if len((text or "").split()) >= 4 and self._about(text, it, on_topic) and len(text) > len(best):
                    best = text                          # short but useful: keep it in case nothing better comes
                text = ""
                continue
            if BROKEN.search(text or ""):
                text = ""
                continue
            text = re.sub(r"^(good (try|job|effort)|well done|nice( try)?|great( job)?|not quite|you'?re (right|close))\b[^.!?]*[.!?]\s*",
                          "", text or "", flags=re.I).strip()                 # strip any opinion that slipped in
            if text and not self._about(text, it, on_topic):
                text = ""                                    # wandered off to other facts: try again
                continue
            if text:
                break
        text = text or best
        # nothing good after 3 tries: show no explanation box at all, rather than the answer a second time
        it["explanation"] = add_keys(short_text(text, 38, 2), self.key_terms(it.get("lid"))) if text else ""
        if it.get("review_key") and it.get("lid"):          # saved for review before the explanation was ready
            self.review.set_explanation(it["lid"], it["review_key"], it["explanation"])

    def explain_more(self, item_id):
        it = self._item(item_id)
        if not it or it["status"] not in ("answered", "done"):
            return {"ok": False, "error": "Answer the question first."}
        level = len(it["more"]) + 2          # level 1 is the automatic explanation
        if level > 3:
            return {"ok": False, "error": "That's all the explanations for this one."}
        res = None
        job = (it.get("more_pre") or {}).get(level)
        if job:                                           # written ahead (or being written): use it
            self.priority += 1                            # the Teacher is waiting: no new cards meanwhile
            try:
                job["done"].wait(timeout=30)
            finally:
                self.priority = max(0, self.priority - 1)
            res = job.get("res")
        if not res:
            res = self._write_more(it, level, urgent=True)
        if not res:
            return {"ok": False, "error": "The class couldn't think of a new way to explain it. Try again in a moment."}
        it["more"].append(res["text"])
        self._log({"type": "explain_more", "id": it["id"], "level": level, "text": res["text"]})
        self._prefetch_more(it, level + 1)
        h = self.students[res["sid"]]
        return {"ok": True, "text": res["text"], "level": level, "max": level >= 3, "by": h["name"],
                "emoji": h.get("emoji", ""), "sid": res["sid"], "helped": res["sid"] != it["sid"]}

    def _prefetch_more(self, it, level):
        """Write the next "Explain more" in the background, so the button answers at once."""
        pre = it.setdefault("more_pre", {})
        if level > 3 or level in pre or it["type"] == "boss":
            return
        job = {"done": threading.Event()}
        pre[level] = job
        def work():
            try:
                for _ in range(120):                      # the first explanation comes first (it's what was read)
                    if not it.get("explaining") and it.get("explanation") is not None:
                        break
                    time.sleep(0.25)
                if len(it["more"]) + 2 == level:
                    job["res"] = self._write_more(it, level, urgent=False)
            finally:
                job["done"].set()
        threading.Thread(target=work, daemon=True).start()

    def _write_more(self, it, level, urgent):
        previous = " ".join([it["answer"], it.get("explanation") or ""] + it["more"])
        helper = self._free_student(it["sid"])
        task = E.fill(E.read_skill("explain_more"), question=self._question_for_judge(it), correct=self._right_answer(it),
                      previous=previous, level=level)
        text = ""
        for attempt in range(4):
            if attempt == 2:                              # two tries failed: ask another student
                helper = self._free_student(helper, avoid=helper)
            t = task if attempt == 0 else task + (
                "\n\nIMPORTANT: your last try was almost the same as before. Use a COMPLETELY different "
                "comparison or example this time.")
            if urgent:
                self.priority += 1
            try:
                raw = self._ask(helper, t, self.cfg.get("thinking_budget_cards", 0), any_port=True, max_tokens=200)
            finally:
                if urgent:
                    self.priority = max(0, self.priority - 1)
            text = E.keep_key_styles(E.clean(raw, self.names, limit=420), self.vocab)
            shown = [it["answer"], it["question"], it.get("explanation") or ""] + it["more"] + \
                    [c.get("text", "") for c in it.get("claims") or []]
            text = short_text(clean_explanation(text, shown), 40, 2)   # only the NEW part, and not too long
            if len((text or "").split()) < 8 or BROKEN.search(text):
                text = ""
                continue
            if not any(similar(text, old, 0.4) for old in [it.get("explanation") or ""] + it["more"]):
                break                                        # a genuinely new explanation
            text = text if attempt == 3 else ""
        if not text:
            return None
        return {"text": add_keys(text, self.key_terms(it.get("lid"))), "sid": helper}

    def _free_student(self, sid, avoid=None):
        """The card's own student if its server has a free slot, otherwise the least busy online student."""
        own = self.students[sid]["port"]
        if sid != avoid and self.online.get(sid) and self.inflight.get(own, 0) < 1 and not self.generating.get(sid):
            return sid
        cands = [k for k in self.students if self.online.get(k) and k != avoid] or [sid]
        return min(cands, key=lambda k: (self.inflight.get(self.students[k]["port"], 0), bool(self.generating.get(k)), k != sid))

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
        self._review_record(it, "TIMEOUT")
        self._log({"type": "timeout", "id": it["id"], "question": it["question"]})
        return {"ok": True}


    # ------------------------------------------------------------ ⚙️ settings

    TYPE_KEYS = ["explain_why", "what_if", "compare", "fill_blank", "pick_one", "spot_mistake", "lightning", "whos_right"]
    LEVEL_WEIGHT = {"off": 0, "some": 2, "often": 4}
    CLASS_KEYS = ("class_minutes", "question_seconds", "question_interval_seconds", "max_visible")

    def min_interval(self):
        """The fastest "new card every" the students can keep up with: one card takes card_seconds_measured
        (incl. rewrites), max_parallel_generation are written at once, plus 25% for the explanations sharing the GPU."""
        per = float(self.cfg.get("card_seconds_measured") or 12.5)
        par = max(1, int(self.cfg.get("max_parallel_generation") or 2))
        return max(3, int(-(-per / par * 1.25 // 1)))   # rounded up

    def _record_card_time(self, seconds):
        old = float(self.cfg.get("card_seconds_measured") or 12.5)
        self.cfg["card_seconds_measured"] = round(old * 0.85 + float(seconds) * 0.15, 2)

    def get_settings(self):
        c, d = self.cfg, E.DEFAULT_CONFIG
        w = c.get("question_type_weights") or {}
        level = lambda v: "off" if not v else "some" if v <= 2 else "often"
        pend = dict(self.pending_cfg)
        val = lambda k: pend.get(k, c[k])
        return {
            "class_minutes": val("class_minutes"), "question_seconds": val("question_seconds"),
            "question_interval_seconds": val("question_interval_seconds"), "max_visible": val("max_visible"),
            "types": {t: level(w.get(t, 0)) for t in self.TYPE_KEYS},
            "meteors": float(c.get("meteor_chance") or 0) > 0, "zombies": float(c.get("zombie_chance") or 0) > 0,
            "streak": float(c.get("streak_card_chance") or 0) > 0, "second_chance": int(c.get("second_chance_every") or 0) > 0,
            "challenge_every": int(c.get("challenge_every") or 0),
            "calm_mode": bool(c.get("calm_mode")), "sound": bool(c.get("sound", True)),
            "text_size": c.get("text_size") or "M", "animations": c.get("animations") or "full",
            "students": [{"id": k, "name": s["name"], "emoji": s.get("emoji", ""), "personality": s.get("personality", ""),
                          "online": bool(self.online.get(k))} for k, s in self.students.items()],
            "min_interval": self.min_interval(), "card_seconds": float(c.get("card_seconds_measured") or 12.5),
            "running": self.running, "pending": sorted(pend),
        }

    def save_settings(self, changes):
        """Save what the ⚙️ tab changed. Class timings wait for the next class if one is running."""
        c, d = self.cfg, E.DEFAULT_CONFIG
        clamp = lambda v, lo, hi: max(lo, min(hi, int(round(float(v)))))
        for k, v in (changes or {}).items():
            if k == "class_minutes":
                self._set_class(k, clamp(v, 5, 30))
            elif k == "question_seconds":
                self._set_class(k, clamp(v, 15, 60))
            elif k == "question_interval_seconds":
                self._set_class(k, clamp(v, self.min_interval(), 30))
            elif k == "max_visible":
                self._set_class(k, clamp(v, 3, 12))
            elif k == "types" and isinstance(v, dict):
                w = dict(c.get("question_type_weights") or {})
                for t, lv in v.items():
                    if t in self.TYPE_KEYS and lv in self.LEVEL_WEIGHT:
                        w[t] = self.LEVEL_WEIGHT[lv]
                if not any(w.get(t) for t in self.TYPE_KEYS):
                    return {"ok": False, "error": "Keep at least one card type on."}
                c["question_type_weights"] = w
            elif k == "meteors":
                c["meteor_chance"] = d["meteor_chance"] if v else 0
            elif k == "zombies":
                c["zombie_chance"] = d["zombie_chance"] if v else 0
            elif k == "streak":
                c["streak_card_chance"] = d["streak_card_chance"] if v else 0
            elif k == "second_chance":
                c["second_chance_every"] = 6 if v else 0
            elif k == "challenge_every":
                c["challenge_every"] = clamp(v, 0, 30)
            elif k in ("calm_mode", "sound"):
                c[k] = bool(v)
            elif k == "text_size" and v in ("S", "M", "L"):
                c[k] = v
            elif k == "animations" and v in ("full", "less"):
                c[k] = v
        E.save_config(dict(c, **self.pending_cfg))
        return dict(self.get_settings(), ok=True)

    def _set_class(self, k, v):
        if self.running:
            self.pending_cfg[k] = v                          # applies when the next class starts
        else:
            self.cfg[k] = v
            self.pending_cfg.pop(k, None)

    def reset_settings(self):
        """Everything on the ⚙️ tab back to the defaults (students and grown-up settings stay)."""
        d = E.DEFAULT_CONFIG
        for k in ("question_type_weights", "meteor_chance", "zombie_chance", "streak_card_chance", "second_chance_every",
                  "challenge_every", "calm_mode", "sound", "text_size", "animations"):
            self.cfg[k] = json.loads(json.dumps(d[k]))
        for k in self.CLASS_KEYS:
            self._set_class(k, d[k])
        E.save_config(dict(self.cfg, **self.pending_cfg))
        return dict(self.get_settings(), ok=True)

    def save_student(self, sid, name, emoji, personality, picture=None):
        sid = int(sid)
        if sid not in self.students:
            return {"ok": False, "error": "No such student."}
        name = re.sub(r"[^\w '\-]", "", (name or "").strip())[:16]
        if not name:
            return {"ok": False, "error": "Give the student a name."}
        if any(s["name"].lower() == name.lower() for k, s in self.students.items() if k != sid):
            return {"ok": False, "error": "Another student already has that name."}
        st = self.students[sid]
        st.update(name=name, emoji=(emoji or "").strip()[:4] or st.get("emoji", ""), personality=(personality or "").strip()[:160])
        for s in self.cfg["students"]:
            if int(s["id"]) == sid:
                s.update(name=st["name"], emoji=st["emoji"], personality=st["personality"])
        self.names = [s["name"] for s in self.students.values()] + ["Teacher"]
        if picture:                                         # data URL from the file picker
            m = re.match(r"data:image/(png|jpeg|jpg|gif|webp);base64,(.+)", picture, re.S)
            if not m:
                return {"ok": False, "error": "That picture type isn't supported."}
            raw = base64.b64decode(m.group(2))
            if len(raw) > 3_000_000:
                return {"ok": False, "error": "That picture is too big (3 MB max)."}
            folder = self.folder("avatars")
            for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                try:
                    os.remove(os.path.join(folder, "s%d%s" % (sid, ext)))
                except OSError:
                    pass
            with open(os.path.join(folder, "s%d.%s" % (sid, "jpg" if m.group(1) == "jpeg" else m.group(1))), "wb") as f:
                f.write(raw)
        elif picture == "":                                 # remove the picture
            for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                try:
                    os.remove(os.path.join(self.folder("avatars"), "s%d%s" % (sid, ext)))
                except OSError:
                    pass
        E.save_config(dict(self.cfg, **self.pending_cfg))
        return {"ok": True}

    def students_power(self, on):
        """▶ start / ■ stop the 5 student servers (ports 1001-1005 only) with the scripts next to the app."""
        folder = self.folder()
        if on:
            script = os.path.join(folder, "start_students_hidden.ps1")
            if not os.path.isfile(script):
                return {"ok": False, "error": "start_students_hidden.ps1 is missing next to the app."}
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", script],
                             cwd=folder, creationflags=0x08000000)          # CREATE_NO_WINDOW
        else:
            script = os.path.join(folder, "stop_students.bat")
            if not os.path.isfile(script):
                return {"ok": False, "error": "stop_students.bat is missing next to the app."}
            subprocess.Popen(["cmd", "/c", script], cwd=folder, creationflags=0x08000000)
        return {"ok": True}

    # ------------------------------------------------------------ 📝 review

    def _rv_ctx(self, lid=None):
        """What the review store needs the first time it opens a lesson (to bring in old timed-out questions)."""
        lid = lid or self.lesson_id
        title = self.lesson if lid == self.lesson_id else (self.library.meta(lid) or {}).get("title")
        return {"title": title, "sessions_dir": self.folder("sessions"),
                "by_name": {s["name"]: k for k, s in self.students.items()}}

    def _review_count(self):
        try:
            return self.review.count(self.lesson_id, **self._rv_ctx()) if self.lesson_id else 0
        except Exception:                                    # noqa: BLE001 - never break polling
            return 0

    def _review_record(self, it, verdict):
        lid = it.get("lid") or self.lesson_id
        if not lid:
            return
        try:
            k = self.review.record(lid, it, self.students.get(it["sid"], {}), verdict, self._question_for_judge(it),
                                   **self._rv_ctx(lid))
            if k:
                it["review_key"] = k
        except Exception as e:                               # noqa: BLE001 - saving for review must never break class
            self._log({"type": "review_error", "error": str(e)})

    def star(self, item_id, on):
        """⭐ in the answer panel: save this question in the 📝 Review list (or take the star off)."""
        it = self._item(item_id)
        if not it or not it.get("lid"):
            return {"ok": False, "error": "That question is gone."}
        r = self.review.star(it["lid"], it, self.students.get(it["sid"], {}), on, self._question_for_judge(it))
        if r.get("key"):
            it["review_key"] = r["key"]
        return r

    def review_list(self, lid=None):
        """The 📝 Review tab: one lesson (default: the one in class) or "all"."""
        lessons = [m for m in self.library.list() if m.get("status") == "ready"]
        titles = {m["id"]: m.get("title") for m in lessons}
        lid = lid or self.lesson_id
        ids = list(titles) if lid == "all" else [lid] if lid in titles else []
        items = []
        for x in ids:
            terms = self.key_terms(x)
            for e in self.review.entries(x, **self._rv_ctx(x)):
                e["lesson"] = titles.get(x, "")
                e["answer"] = add_keys(e.get("answer", ""), terms, 3)
                for f in ("explanation", "simple"):
                    if e.get(f):
                        e[f] = add_keys(e[f], terms, 2 if f == "simple" else 3)
                e["more"] = [add_keys(m, terms) for m in e.get("more") or []]
                items.append(e)
        items.sort(key=lambda e: e.get("when") or e.get("first") or "", reverse=True)
        counts = {m["id"]: self.review.count(m["id"], **self._rv_ctx(m["id"])) for m in lessons}
        return {"ok": True, "lesson_id": lid, "active": self.lesson_id, "rev": self.review.rev, "items": items,
                "lessons": [{"id": m["id"], "title": m.get("title"), "count": counts[m["id"]]} for m in lessons]}

    def review_update(self, lid, key, changes):
        changes = changes or {}
        return self.review.update(lid, key, **{k: v for k, v in changes.items() if k in ("starred", "mastered")})

    def review_delete(self, items):
        """items = [[lesson_id, key], ...] (🗑 one, or several with Select)."""
        n = 0
        by_lesson = {}
        for lid, k in items or []:
            by_lesson.setdefault(lid, []).append(k)
        for lid, keys in by_lesson.items():
            n += self.review.delete(lid, keys).get("deleted", 0)
        return {"ok": True, "deleted": n}

    def review_explain(self, lid, key):
        """🤔 Explain more, from the Review tab (up to 2 more, like in class)."""
        e = self.review.get(lid, key)
        if not e:
            return {"ok": False, "error": "That question isn't in the review list any more."}
        more = e.get("more") or []
        if len(more) >= 2:
            return {"ok": False, "error": "That's all the explanations for this one."}
        sid = e.get("sid") if e.get("sid") in self.students else None
        sid = sid if sid and self.online.get(sid) else next((s for s in self.students if self.online.get(s)), None)
        if not sid:
            return {"ok": False, "error": "The students are offline right now. Start them, then try again."}
        level = len(more) + 2
        q, a = e.get("judge_q") or e["question"], e.get("answer", "")
        task = E.fill(E.read_skill("explain_more"), question=q, correct=a,
                      previous=" ".join([a, e.get("explanation") or ""] + more), level=level)
        system = ("You are %s, a kind student who explains things simply to a child. You only use what the question "
                  "and the correct answer say." % self.students[sid]["name"])
        text = ""
        for attempt in range(3):
            t = task if attempt == 0 else task + ("\n\nIMPORTANT: your last try was almost the same as before. Use a "
                                                  "COMPLETELY different comparison or example this time.")
            port = self._port_for(sid, True)
            self.inflight[port] = self.inflight.get(port, 0) + 1
            try:
                out = E.llm(self.host, port, [{"role": "system", "content": system}, {"role": "user", "content": t}],
                            int(self.cfg["max_tokens_chat"]), int(self.cfg["timeout_seconds"]),
                            self.cfg.get("thinking_budget_cards", 0))
            finally:
                self.inflight[port] = max(0, self.inflight.get(port, 1) - 1)
            text = E.keep_key_styles(E.clean(out, self.names, limit=420), self.vocab)
            text = clean_explanation(text, [a, e["question"], e.get("explanation") or "", e.get("simple") or ""] + more)
            if len((text or "").split()) < 8 or BROKEN.search(text):
                text = ""
                continue
            if text and not any(similar(text, old, 0.4) for old in [e.get("explanation") or ""] + more):
                break
            text = text if attempt == 2 else ""
        if not text:
            return {"ok": False, "error": "%s couldn't explain it right now, try again." % self.students[sid]["name"]}
        text = add_keys(text, self.key_terms(lid))
        r = self.review.update(lid, key, more=text)
        return {"ok": True, "text": text, "level": level, "max": level >= 3, "entry": r.get("entry")}

    def key_terms(self, lid=None):
        """The lesson's key words: what the students bolded in their key points and notes (longest first)."""
        lid = lid or self.lesson_id
        if not lid:
            return []
        stamp = self.notes_rev
        hit = self._key_terms.get(lid)
        if hit and hit[0] == stamp:
            return hit[1]
        text = " ".join((self.library.section(lid, sid) or {}).get("content", "") for sid in self.students)
        text += " " + " ".join((self.library.notes(lid) or {}).values())
        seen, terms = set(), []
        for t in re.findall(r"\*\*(.+?)\*\*", text):
            t = t.strip()
            if not t or len(t) < 3 or len(t.split()) > 3 or KEY_JUNK.search(t) or t.lower() in seen \
                    or t.lower() in GENERIC or t.lower() in STOP:
                continue
            seen.add(t.lower())
            terms.append(t)
        terms.sort(key=len, reverse=True)
        self._key_terms[lid] = (stamp, terms)
        return terms

    def _simple_worker(self):
        """In the background, each 📝 Review question gets a one-sentence simple explanation, written whenever a
        student server is completely free (so it never slows down the class)."""
        while True:
            time.sleep(3)
            try:
                if self.preparing() or not self.lesson_id:
                    continue
                free = [s for s in self.students if self.online.get(s) and self.inflight.get(self.students[s]["port"], 0) == 0]
                if not free:
                    continue
                lids = [self.lesson_id] + [m["id"] for m in self.library.list()
                                           if m.get("status") == "ready" and m["id"] != self.lesson_id]
                job = next(((lid, e) for lid in lids for e in self.review.needs_simple(lid, **self._rv_ctx(lid))), None)
                if not job:
                    time.sleep(7)
                    continue
                lid, e = job
                sid = e.get("sid") if e.get("sid") in free else free[0]
                port = self.students[sid]["port"]
                task = E.fill(E.read_skill("review_simple"), question=e.get("judge_q") or e["question"], correct=e.get("answer", ""))
                system = ("You are %s, a kind student who explains things simply to a child. You only use what the "
                          "question and the correct answer say." % self.students[sid]["name"])
                self.inflight[port] = self.inflight.get(port, 0) + 1
                try:
                    out = E.llm(self.host, port, [{"role": "system", "content": system}, {"role": "user", "content": task}],
                                200, int(self.cfg["timeout_seconds"]), 0)
                finally:
                    self.inflight[port] = max(0, self.inflight.get(port, 1) - 1)
                text = first_sentences(E.clean(out, self.names, limit=220), 1)
                padded = " %s " % E._norm_words((e.get("judge_q") or e["question"]) + " " + e.get("answer", ""))
                if not text or LEAK.search(text) or BROKEN.search(text) or len(text.split()) < 4 \
                        or not self._from_text(text, padded, 0.5):      # must stick to the question and answer
                    self.review.update(lid, e["key"], simple_failed=True)
                    continue
                text = add_keys(E.keep_key_styles(text, self.vocab if lid == self.lesson_id else
                                                  E._norm_words(text), max_spans=2), self.key_terms(lid), 2)
                self.review.update(lid, e["key"], simple=text)
            except Exception as ex:                          # noqa: BLE001 - background helper, never crash
                self._log({"type": "review_simple_error", "error": str(ex)})
                time.sleep(10)

    def dashboard(self):
        """🏠 the home screen's stats, from the class logs."""
        ready = [m for m in self.library.list() if m.get("status") == "ready"]
        titles = [m.get("title") for m in ready]
        waiting, learned = 0, []
        for m in ready:
            try:
                waiting += self.review.count(m["id"], **self._rv_ctx(m["id"]))
                learned += self.review.mastered_dates(m["id"], **self._rv_ctx(m["id"]))
            except Exception:                                # noqa: BLE001
                pass
        d = ST.dashboard(self.folder("sessions"), titles, waiting, int(self.cfg.get("class_minutes") or 15),
                         daily_goal=self.cfg.get("daily_goal") or 100, learned_dates=learned)
        d["running"] = self.running
        return d

    def pause(self, on):
        """⏸ while the 📝 Review tab is open during class: the clocks stop and no new cards come."""
        with self.lock:
            if not self.running:
                self.paused_at = None
                return {"ok": True, "paused": False}
            if on and not self.paused_at:
                self.paused_at = time.time()
            elif not on and self.paused_at:
                d = time.time() - self.paused_at
                self.paused_at = None
                self.pause_total += d
                if self.started_at:
                    self.started_at += d                     # the 15-minute class clock doesn't count the pause
                z = self.zombie
                if z and z.get("end"):
                    z["end"] += d
                    z["start"] += d
                return {"ok": True, "paused": False, "shift": d}
            return {"ok": True, "paused": bool(self.paused_at)}

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
                "notes_writing": self.notes_writing[1] if self.notes_writing and self.notes_writing[0] == self.lesson_id else None,
                "paused_at": self.paused_at if self.running else None,
                "review_rev": self.review.rev, "review_count": self._review_count(),
                "prepare": dict(self.prepare, students=dict(self.prepare["students"])) if self.prepare else None}

    def _seconds_for(self, it):
        base = float(self.cfg["question_seconds"])
        return {"lightning": float(self.cfg.get("lightning_seconds") or 10),
                "challenge": float(self.cfg.get("challenge_seconds") or 60),
                "silver": float(self.cfg.get("silver_seconds") or 45),
                "boss": float(self.cfg.get("boss_seconds") or 60),
                "streak": base * 1.25}.get(it["type"], base)
