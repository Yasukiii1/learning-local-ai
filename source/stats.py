"""🏠 Home dashboard: learning stats from the class logs (sessions/class_*.jsonl).

Every class writes one log file named class_YYYY-MM-DD_HH-MM-SS.jsonl. Records carry a "t" timestamp from now on;
older logs don't, so their time in class is estimated from the file's start (name) and last write (mtime).
Parsed files are cached by (mtime, size), so the dashboard stays fast as the logs grow.
"""
import datetime
import glob
import json
import os
import re
import threading

NAME = re.compile(r"class_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})\.jsonl$")
_cache = {}
WEEKS = 52
_lock = threading.Lock()


def _parse(path, max_minutes):
    """One class log -> {day, start, seconds, lesson, answers: [(verdict, card, student)], timeouts, best_streak}."""
    m = NAME.search(os.path.basename(path))
    if not m:
        return None
    start = datetime.datetime(*map(int, m.groups()))
    out = {"day": start.date().isoformat(), "start": start.timestamp(), "lesson": "", "answers": [], "timeouts": 0,
           "best_streak": 0}
    first_t = last_t = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                t = r.get("t")
                if t:
                    first_t = first_t or t
                    last_t = t
                typ = r.get("type")
                if typ == "class_start":
                    out["lesson"] = r.get("lesson") or ""
                elif typ == "answer" and r.get("verdict"):
                    out["answers"].append((r["verdict"], r.get("card") or "", r.get("student")))
                elif typ == "boss_result" and r.get("verdict"):
                    out["answers"].append((r["verdict"], "boss", None))
                elif typ == "timeout":
                    out["timeouts"] += 1
                elif typ == "class_stop":
                    out["best_streak"] = int((r.get("stats") or {}).get("best_streak") or 0)
    except OSError:
        return None
    if first_t and last_t:
        secs = last_t - first_t
    else:                                                  # older logs: from the start (file name) to the last write
        secs = os.path.getmtime(path) - out["start"]
    out["seconds"] = max(0, min(secs, max_minutes * 60 + 120))
    return out


def classes(folder, max_minutes=30):
    files = glob.glob(os.path.join(folder, "class_*.jsonl"))
    res = []
    with _lock:
        for p in files:
            try:
                st = os.stat(p)
            except OSError:
                continue
            key = (st.st_mtime, st.st_size)
            hit = _cache.get(p)
            if not hit or hit[0] != key:
                hit = (key, _parse(p, max_minutes))
                _cache[p] = hit
            if hit[1]:
                res.append(hit[1])
    res.sort(key=lambda c: c["start"])
    return res


def _pct(right, n):
    return round(100 * right / n) if n else None


def dashboard(folder, lesson_titles, review_waiting, max_minutes=30, today=None, daily_goal=100, learned_dates=()):
    """Everything the home screen shows. lesson_titles: titles of the lessons that still exist (newest first).
    learned_dates: ISO dates when 📝 Review questions were learned (mastered)."""
    today = today or datetime.date.today()
    cls = [c for c in classes(folder, max_minutes) if c["answers"] or c["timeouts"]]
    days, by_lesson, by_type = {}, {}, {}
    total = right = 0
    seconds = 0.0
    for c in cls:
        d = days.setdefault(c["day"], {"q": 0, "right": 0, "partly": 0, "wrong": 0, "timeouts": 0, "sec": 0.0,
                                       "classes": 0, "best": 0, "lessons": []})
        verdicts = [v for v, _, _ in c["answers"]]
        ok = verdicts.count("CORRECT")
        d["q"] += len(verdicts)
        d["right"] += ok
        d["partly"] += verdicts.count("PARTLY")
        d["wrong"] += verdicts.count("WRONG")
        d["timeouts"] += c["timeouts"]
        d["sec"] += c["seconds"]
        d["classes"] += 1
        d["best"] = max(d["best"], c["best_streak"])
        if c["lesson"] and c["lesson"] not in d["lessons"]:
            d["lessons"].append(c["lesson"])
        total += len(verdicts)
        right += ok
        seconds += c["seconds"]
        for v, card, _ in c["answers"]:
            if card:
                t = by_type.setdefault(card, [0, 0])
                t[0] += 1
                t[1] += v == "CORRECT"
        if c["lesson"]:
            L = by_lesson.setdefault(c["lesson"], {"q": 0, "right": 0, "last": 0})
            L["q"] += len(verdicts)
            L["right"] += ok
            L["last"] = max(L["last"], c["start"])

    # streaks: days in a row with at least one answered question
    active = sorted(datetime.date.fromisoformat(k) for k, v in days.items() if v["q"] > 0)
    longest = run = 0
    prev = None
    for d in active:
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    current = 0
    if active and (today - active[-1]).days <= 1:          # still alive if he played today or yesterday
        current = 1
        for i in range(len(active) - 1, 0, -1):
            if (active[i] - active[i - 1]).days == 1:
                current += 1
            else:
                break

    # the activity grid: 52 full weeks ending this week (Monday first); each day carries its details for the panel
    end = today + datetime.timedelta(days=6 - today.weekday())
    start = end - datetime.timedelta(days=WEEKS * 7 - 1)
    grid = []
    for i in range(WEEKS * 7):
        day = start + datetime.timedelta(days=i)
        v = days.get(day.isoformat())
        g = {"d": day.isoformat(), "q": v["q"] if v else 0, "min": round(v["sec"] / 60) if v else 0, "future": day > today}
        if v:
            g.update(right=v["right"], partly=v["partly"], wrong=v["wrong"], timeouts=v["timeouts"], classes=v["classes"],
                     best=v["best"], lessons=v["lessons"], pct=_pct(v["right"], v["q"]))
        grid.append(g)

    # last 7 days (sparklines) and this week vs the week before
    def span(a, b):                                        # days a..b ago (inclusive), oldest first
        return [(today - datetime.timedelta(days=k)).isoformat() for k in range(b, a - 1, -1)]
    learned = {}
    for x in learned_dates or ():
        learned[x[:10]] = learned.get(x[:10], 0) + 1
    def week(keys):
        q = sum(days.get(k, {}).get("q", 0) for k in keys)
        r = sum(days.get(k, {}).get("right", 0) for k in keys)
        return {"q": q, "pct": _pct(r, q), "min": round(sum(days.get(k, {}).get("sec", 0) for k in keys) / 60),
                "learned": sum(learned.get(k, 0) for k in keys)}
    this_w, last_w = week(span(0, 6)), week(span(7, 13))
    spark = [{"d": k, "q": days.get(k, {}).get("q", 0), "pct": _pct(days.get(k, {}).get("right", 0), days.get(k, {}).get("q", 0)),
              "min": round(days.get(k, {}).get("sec", 0) / 60), "learned": learned.get(k, 0)} for k in span(0, 6)]

    titles = [t for t in lesson_titles if t in by_lesson]
    lessons = [{"title": t, "q": by_lesson[t]["q"], "pct": _pct(by_lesson[t]["right"], by_lesson[t]["q"]) or 0}
               for t in sorted(titles, key=lambda t: -by_lesson[t]["last"])][:6]
    types = sorted(({"type": k, "q": n, "pct": _pct(r, n)} for k, (n, r) in by_type.items() if n >= 1),
                   key=lambda x: (-(x["pct"] or 0), -x["q"]))
    today_q = days.get(today.isoformat(), {}).get("q", 0)
    last = cls[-1] if cls else None
    return {
        "answered": total, "right_pct": _pct(right, total) or 0, "minutes": round(seconds / 60),
        "learned": sum(learned.values()),
        "longest_streak": longest, "current_streak": current, "grid": grid, "lessons": lessons, "types": types,
        "week": this_w, "prev_week": last_w, "spark": spark,
        "today_q": today_q, "daily_goal": int(daily_goal or 100), "review_waiting": review_waiting,
        "last_day": last["day"] if last else None, "today": today.isoformat(), "classes": len(cls),
    }
