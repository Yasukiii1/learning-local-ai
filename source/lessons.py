"""Lesson library: lessons/<id>/ holds meta.json, source.txt, s1..s5.json (each student's part + plan),
sN_questions.json (question banks) and notes.json (the simple notes the students write).

Importing turns a PDF / Word file / text file / picture / pasted text into plain text (Windows OCR for
pictures and scanned PDFs) and cuts it into 5 parts, one per student. No AI is used for that step."""
import base64
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile

COLORS = ["#e07a80", "#d98fa3", "#e5946f", "#d9b37e", "#8fbf8a", "#7fb0d9", "#b496dd", "#e0a65e"]
TEXT_EXT = (".txt", ".md", ".markdown", ".csv")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
SUPPORTED = (".pdf", ".docx") + TEXT_EXT + IMAGE_EXT
PIECE_WORDS = 1800            # a student reads its part in pieces of about this many words
MAX_WORDS = 250_000


def words(s):
    return len(s.split())


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]
    return s or "lesson"


# ------------------------------------------------------------------ text extraction

def _run_ocr(ocr_script, path):
    """Windows' built-in OCR through PowerShell (no window)."""
    out = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ocr_script, path],
                         capture_output=True, timeout=900, creationflags=0x08000000)    # CREATE_NO_WINDOW
    text = out.stdout.decode("utf-8", "replace")
    if out.returncode != 0 and not text.strip():
        raise RuntimeError("Windows couldn't read the text in this file.")
    return text


def _columns(block):
    """Lines of a layout-mode text block -> text read column by column, or None if it isn't laid out in columns.
    Slides often put a label above its text in side-by-side boxes; read line by line, every label lands next
    to the wrong text ("land Number of people... Labour Consist of finance...")."""
    rows = []
    for line in block:
        segs = [(m.start(), m.end(), m.group().strip()) for m in re.finditer(r"\S+(?: {1,2}\S+)*", line)]
        rows.append(segs)
    if sum(1 for r in rows if len(r) >= 2) < 2:
        return None
    cols = []                                              # merge overlapping [start, end] spans into columns
    for s, e, _ in sorted(seg for r in rows for seg in r):
        if cols and s <= cols[-1][1] + 1:
            cols[-1][1] = max(cols[-1][1], e)
        else:
            cols.append([s, e])
    if len(cols) < 2:
        return None
    out = []
    for cs, ce in cols:
        parts = [t for r in rows for s, e, t in r if s >= cs and e <= ce]
        if not parts:
            continue
        head, rest = parts[0], " ".join(parts[1:])
        # a label sits alone above its text: short, and the text below starts a new sentence (capital letter)
        if rest and len(head.split()) <= 3 and not re.search(r"[.,;:!?]$", head) and rest[:1].isupper() \
                and not re.search(r"\b(of|the|a|an|and|or|in|on|to|this|that|for|with)$", head, re.I):
            out.append("%s: %s" % (head, rest))           # "Labour: Number of people available..."
        else:
            out.append(" ".join(parts))
    return "\n\n".join(out)


def _layout_page(page):
    """Read a page by its layout so side-by-side columns stay together. Falls back to the plain text."""
    try:
        lay = page.extract_text(extraction_mode="layout") or ""
    except Exception:                                      # noqa: BLE001
        return None
    blocks, cur = [], []
    for line in lay.splitlines():
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    found, out, k = False, [], 0
    while k < len(blocks):
        b = blocks[k]
        k += 1
        if len(b) <= 2 and k < len(blocks) and _columns(blocks[k]):    # a row of labels above the boxes
            joined = _columns(b + blocks[k])
            if joined and joined.count("\n\n") == _columns(blocks[k]).count("\n\n"):
                found = True
                out.append(joined)
                k += 1
                continue
        c = _columns(b)
        if c:
            found = True
            out.append(c)
        else:
            out.append(" ".join(l.strip() for l in b))
    return "\n\n".join(out) if found else None


def _pdf_text(path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = []
    for p in reader.pages:
        try:
            pages.append(_layout_page(p) or p.extract_text() or "")
        except Exception:                                  # noqa: BLE001 - one broken page shouldn't stop the rest
            pages.append("")
    return pages


def _docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        t = "".join(re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", p, re.S))
        t = (t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
        paras.append(t)
    return "\n\n".join(paras)


def extract(path, ocr_script):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        pages = _pdf_text(path)
        real = sum(len(p.strip()) for p in pages)
        if pages and real / len(pages) < 150:              # hardly any text: it's a scan, read it with OCR
            return _run_ocr(ocr_script, path), "scanned PDF"
        return "\n\n".join(pages), "PDF"
    if ext == ".docx":
        return _docx_text(path), "Word"
    if ext in IMAGE_EXT:
        return _run_ocr(ocr_script, path), "picture"
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), "notes"
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "notes"


def tidy(text):
    """Join broken PDF lines back into paragraphs; drop page numbers and empty noise."""
    text = text.replace("\r", "\n").replace("\f", "\n\n").replace("­", "").replace("\t", " ")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # hy-\nphen
    lines = [l.strip() for l in text.split("\n")]
    paras, cur = [], []
    for l in lines:
        if not l or re.fullmatch(r"(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?", l, re.I):
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        heading = len(l) < 70 and not re.search(r"[.,;:!?]$", l) and (l.isupper() or l.istitle() or re.match(r"^(\d+[.)]|#+)\s", l))
        if heading and cur:
            paras.append(" ".join(cur))
            cur = []
        cur.append(l)
        if heading or re.search(r"[.!?:]$", l) and len(l) < 60:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    paras = [re.sub(r"\s+", " ", p).strip() for p in paras]
    return "\n\n".join(p for p in paras if len(p) > 1)


def split_parts(text, n=5):
    """Cut the text into n parts of about the same size, at paragraph (or sentence) boundaries."""
    paras = []
    for p in (p.strip() for p in text.split("\n\n")):
        if not p:
            continue
        if paras and words(paras[-1]) < 8 and not re.search(r"[.!?]$", paras[-1]):
            paras[-1] += "\n" + p                          # a heading stays with the paragraph under it
        else:
            paras.append(p)
    total = sum(words(p) for p in paras)
    n = max(1, min(n, total // 50 or 1))                   # very short text: fewer parts (shared by the students)
    target = total / n
    units = []
    for p in paras:                                        # break up giant paragraphs so the parts can be balanced
        if words(p) > target * 0.6:
            units += [s for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]
        else:
            units.append(p)
    parts, cur, cum = [], [], 0
    for u in units:                                        # cut where the running total is closest to k * target
        w = words(u)
        if cur and len(parts) < n - 1 and cum + w / 2 > target * (len(parts) + 1):
            parts.append("\n\n".join(cur))
            cur = []
        cur.append(u)
        cum += w
    if cur:
        parts.append("\n\n".join(cur))
    return [p for p in parts if p.strip()] or [text]


def pieces(text, size=PIECE_WORDS):
    """A long part is read piece by piece (each piece fits the student's memory)."""
    w = text.split()
    if len(w) <= size * 1.3:
        return [text]
    out, cur = [], []
    for para in text.split("\n\n"):
        cur.append(para)
        if words("\n\n".join(cur)) >= size:
            out.append("\n\n".join(cur))
            cur = []
    if cur:
        if out and words("\n\n".join(cur)) < size * 0.3:
            out[-1] += "\n\n" + "\n\n".join(cur)
        else:
            out.append("\n\n".join(cur))
    return out


# ------------------------------------------------------------------ the library

class Library:
    def __init__(self, data_folder, res_dir, student_ids):
        self.root = os.path.join(data_folder, "lessons")
        self.ocr = os.path.join(res_dir, "tools", "ocr.ps1")
        self.sids = list(student_ids)
        self.lock = threading.RLock()
        self.rev = 1                                       # bumps whenever the list changes (the UI reloads it)
        os.makedirs(self.root, exist_ok=True)

    # ---------------------------------------------------------- files

    def path(self, lid, *parts):
        return os.path.join(self.root, lid, *parts)

    def read_json(self, lid, name, default=None):
        try:
            with open(self.path(lid, name), encoding="utf-8-sig") as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def write_json(self, lid, name, data):
        p = self.path(lid, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(p + ".tmp", p)

    def meta(self, lid):
        return self.read_json(lid, "meta.json")

    def update_meta(self, lid, **kw):
        with self.lock:
            m = self.meta(lid) or {}
            m.update(kw)
            self.write_json(lid, "meta.json", m)
            self.rev += 1
            return m

    def list(self):
        out = []
        for lid in os.listdir(self.root):
            if lid.startswith(".") or not os.path.isdir(self.path(lid)):
                continue
            m = self.meta(lid)
            if m:
                m["id"] = lid
                out.append(m)
        out.sort(key=lambda m: m.get("created", ""), reverse=True)
        return out

    def active(self):
        a = self.read_json(".", "active.json", {}) if os.path.isfile(os.path.join(self.root, "active.json")) else {}
        lid = (a or {}).get("id")
        return lid if lid and self.meta(lid) else None

    def set_active(self, lid):
        with open(os.path.join(self.root, "active.json"), "w", encoding="utf-8") as f:
            json.dump({"id": lid}, f)
        self.rev += 1

    def section(self, lid, sid):
        return self.read_json(lid, "s%d.json" % sid)

    def save_section(self, lid, sid, data):
        self.write_json(lid, "s%d.json" % sid, data)

    def notes(self, lid):
        return self.read_json(lid, "notes.json", {}) or {}

    def save_note(self, lid, sid, md):
        with self.lock:
            n = self.notes(lid)
            n[str(sid)] = md
            self.write_json(lid, "notes.json", n)

    # ---------------------------------------------------------- create / import

    def _new(self, title, kind, source_name):
        with self.lock:
            stamp = datetime.datetime.now()
            lid = "%s-%s" % (slug(title), stamp.strftime("%Y%m%d-%H%M%S"))
            used = {m.get("color") for m in self.list()[:len(COLORS) - 1]}
            color = next((c for c in COLORS if c not in used), COLORS[len(self.list()) % len(COLORS)])
            os.makedirs(self.path(lid), exist_ok=True)
            self.write_json(lid, "meta.json", {"title": title[:60], "kind": kind, "source_name": source_name,
                                               "created": stamp.isoformat(timespec="seconds"), "status": "importing",
                                               "color": color, "words": 0, "parts": 0, "studied": False})
            self.rev += 1
            return lid

    def import_file(self, name, b64):
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED:
            return {"ok": False, "error": "That file type isn't supported. Use PDF, Word (.docx), .txt/.md or a picture."}
        data = base64.b64decode(b64.split(",", 1)[-1])
        title = re.sub(r"[_\-]+", " ", os.path.splitext(os.path.basename(name))[0]).strip() or "Lesson"
        lid = self._new(title[:1].upper() + title[1:], "file", name)
        src = self.path(lid, "original" + ext)
        with open(src, "wb") as f:
            f.write(data)
        threading.Thread(target=self._finish_import, args=(lid, lambda: extract(src, self.ocr)), daemon=True).start()
        return {"ok": True, "id": lid}

    def import_text(self, text, title=None):
        text = (text or "").strip()
        if words(text) < 15:
            return {"ok": False, "error": "Paste a bit more text (at least a few sentences)."}
        if not title:
            first = text.split("\n", 1)[0].strip(" #*:")
            title = first if 3 <= len(first) <= 60 else " ".join(text.split()[:6]) + "…"
        lid = self._new(title, "text", "pasted text")
        threading.Thread(target=self._finish_import, args=(lid, lambda: (text, "pasted text")), daemon=True).start()
        return {"ok": True, "id": lid}

    def _finish_import(self, lid, get_text):
        try:
            raw, kind = get_text()
            text = tidy(raw)
            if words(text) < 15:
                raise RuntimeError("Couldn't find readable text in it." + (" If it's handwriting, try typing it in the text box."
                                                                          if kind in ("picture", "scanned PDF") else ""))
            if words(text) > MAX_WORDS:
                text = " ".join(text.split(" ")[:MAX_WORDS])
            with open(self.path(lid, "source.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            parts = split_parts(text, len(self.sids))
            for i, sid in enumerate(self.sids):
                part = parts[i % len(parts)]
                self.save_section(lid, sid, {"student": sid, "part": i % len(parts) + 1, "parts": len(parts),
                                             "title": "", "source": part, "content": "", "studied": False,
                                             "pieces": len(pieces(part))})
            self.update_meta(lid, status="ready", kind_label=kind, words=words(text), parts=len(parts))
        except Exception as e:                             # noqa: BLE001 - shown on the lesson box
            self.update_meta(lid, status="error", error=str(e)[:200] or "Couldn't read that file.")

    # ---------------------------------------------------------- manage

    def rename(self, lid, title):
        title = (title or "").strip()[:60]
        if not title or not self.meta(lid):
            return {"ok": False, "error": "Type a name first."}
        self.update_meta(lid, title=title)
        return {"ok": True}

    def delete(self, lid):
        """Moved to lessons/.trash (not gone for good)."""
        if not self.meta(lid):
            return {"ok": False, "error": "Lesson not found."}
        trash = os.path.join(self.root, ".trash")
        os.makedirs(trash, exist_ok=True)
        shutil.move(self.path(lid), os.path.join(trash, "%s_%d" % (lid, int(time.time()))))
        self.rev += 1
        return {"ok": True}

    def migrate_sections(self, sections_dir, banks_dir, title_default="Lesson"):
        """First run with the library: the old sections/ folder (sample lesson) becomes the first lesson."""
        if self.list() or not os.path.isdir(sections_dir):
            return None
        secs = {}
        for sid in self.sids:
            try:
                with open(os.path.join(sections_dir, "s%d.json" % sid), encoding="utf-8-sig") as f:
                    d = json.load(f)
                if d.get("content"):
                    secs[sid] = d
            except (OSError, ValueError):
                pass
        if not secs:
            return None
        try:
            with open(os.path.join(sections_dir, "lesson.json"), encoding="utf-8-sig") as f:
                title = json.load(f).get("title") or title_default
        except (OSError, ValueError):
            title = title_default
        lid = self._new(title, "sample", "sample lesson")
        for sid, d in secs.items():
            self.save_section(lid, sid, {"student": sid, "part": sid, "parts": len(secs), "title": d.get("title", ""),
                                         "source": d["content"], "content": d["content"], "studied": True, "pieces": 1})
            old_bank = os.path.join(banks_dir, "s%d_questions.json" % sid)
            if os.path.isfile(old_bank):
                shutil.copy(old_bank, self.path(lid, "s%d_questions.json" % sid))
        with open(self.path(lid, "source.txt"), "w", encoding="utf-8") as f:
            f.write("\n\n".join("%s\n\n%s" % (d.get("title", ""), d["content"]) for d in secs.values()))
        total = sum(words(d["content"]) for d in secs.values())
        self.update_meta(lid, status="ready", kind_label="sample", words=total, parts=len(secs), studied=True)
        self.set_active(lid)
        return lid
