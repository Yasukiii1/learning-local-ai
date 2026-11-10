"""AI Classroom - quiz window. Run: python app.py  (or AI-Classroom.exe)"""
import base64
import ctypes
import datetime
import os
import time

import webview

from engine import APP_DIR, QUIZ_SKILLS, RES_DIR, default_skill, read_skill, write_skill
from quiz import Quiz


class Api:
    # underscore = hidden from the page (pywebview only exposes public members)
    def __init__(self):
        self._q = Quiz()
        self._ready = False

    def ready(self):
        """Called by the page once it has loaded (the watchdog waits for this)."""
        if not self._ready:
            log("page loaded")
        self._ready = True
        return {"ok": True}

    def poll(self, after=0, session=None):
        return self._q.poll()

    def start(self):
        return self._q.start()

    def stop(self):
        return self._q.stop()

    def answer(self, item_id, text):
        return self._q.answer(item_id, text)

    def dismiss(self, item_id):
        return self._q.dismiss(item_id)

    def skip(self, item_id):
        return self._q.skip(item_id)

    def explain_more(self, item_id):
        return self._q.explain_more(item_id)

    # 📚 lessons
    def lessons(self):
        return self._q.lessons()

    def lesson_notes(self, lesson_id):
        return self._q.lesson_notes(lesson_id)

    def import_file(self, name, data):
        return self._q.import_file(name, data)

    def import_text(self, text, title=None):
        return self._q.import_text(text, title)

    def select_lesson(self, lesson_id):
        return self._q.select_lesson(lesson_id)

    def rename_lesson(self, lesson_id, title):
        return self._q.rename_lesson(lesson_id, title)

    def delete_lesson(self, lesson_id):
        return self._q.delete_lesson(lesson_id)

    def skills(self):
        return QUIZ_SKILLS

    def get_skill(self, name):
        return read_skill(name)

    def save_skill(self, name, text):
        write_skill(name, text)
        return {"ok": True}

    def default_skill(self, name):
        return default_skill(name)

    def avatars(self):
        """Custom pictures from AI-Classroom/avatars/ (s1.png ... s5.png) as data URLs."""
        folder = self._q.folder("avatars")
        kinds = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
        out = {}
        for sid in self._q.students:
            for ext, mime in kinds.items():
                p = os.path.join(folder, "s%d%s" % (sid, ext))
                if os.path.isfile(p) and os.path.getsize(p) < 3_000_000:
                    with open(p, "rb") as f:
                        out[str(sid)] = "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode())
                    break
        return out

    def open_folder(self):
        os.startfile(self._q.folder())
        return {"ok": True}


def log(msg):
    """AI-Classroom/logs/app.log: starts, page loads, reloads (to diagnose a black window)."""
    try:
        folder = os.path.join(APP_DIR, "logs")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "app.log"), "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.datetime.now().replace(microsecond=0).isoformat(), msg))
    except OSError:
        pass


def already_running():
    """Only one AI Classroom at a time: if it's already open, bring that window to the front instead."""
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.CreateMutexW(None, False, "AI-Classroom-single-instance")
    if k32.GetLastError() != 183:                      # 183 = ERROR_ALREADY_EXISTS
        return False
    hwnd = u32.FindWindowW(None, "AI Classroom")
    if hwnd:
        u32.ShowWindow(hwnd, 9)                        # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
    return True


def main():
    if already_running():
        log("second launch: brought the open window to the front")
        return
    log("app start")
    api = Api()
    url = os.path.join(RES_DIR, "ui", "index.html")
    win = webview.create_window("AI Classroom", url=url, js_api=api,
                                width=1280, height=760, min_size=(900, 560), maximized=True,
                                background_color="#1e1f22")

    def watchdog():
        # if the page hasn't said "ready" (black window), reload it, up to 3 times
        for attempt in range(1, 4):
            for _ in range(80):
                if api._ready:
                    return
                time.sleep(0.1)
            log("page not ready after 8 s, reloading (attempt %d)" % attempt)
            try:
                win.load_url(url)
            except Exception as e:                      # noqa: BLE001
                log("reload failed: %s" % e)
        if not api._ready:
            log("page still not ready after 3 reloads")

    webview.start(watchdog)


if __name__ == "__main__":
    main()
