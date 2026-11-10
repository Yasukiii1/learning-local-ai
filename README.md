# 🎓 Learning Local AI — the AI Classroom

A classroom game where **you are the Teacher** and **5 small AI students** quiz you about any lesson you give them:
a PDF, your notes, a picture of a page, or some pasted text.

Everything runs **on your own computer** with [llama.cpp](https://github.com/ggml-org/llama.cpp). No internet and no account needed after setup.

| The students | |
|---|---|
| 🤖 **Byte** | nerdy and precise, loves numbers and exact facts |
| 🦊 **Pixel** | super curious, always asks why and how |
| 🐼 **Mochi** | calm, explains with everyday comparisons |
| 🐸 **Ribbit** | funny and playful, but keeps the facts right |
| 🐱 **Whiskers** | careful, likes tricky "what if" questions |

---

## ⬇️ Download

1. Go to the **[Releases page](https://github.com/Yasukiii1/learning-local-ai/releases/latest)**.
2. Download **`Learning-Local-AI.zip`** (under *Assets*).
3. Right-click the zip → **Extract All…** and put the folder anywhere, for example on your Desktop.

> The green **Code → Download ZIP** button only gives you the source code. Use the Releases page to get the ready-to-run `AI-Classroom.exe`.

---

## ✅ Requirements

| | |
|---|---|
| **System** | Windows 10 or 11 (64-bit) |
| **Graphics card** | **8 GB VRAM or more** (NVIDIA, AMD or Intel) |
| **llama.cpp** | already installed, a **recent build** (build 12196 from November 2026 or newer, it needs LFM3 support) |
| **Disk space** | about 2 GB (the model is 1.0–1.4 GB) |
| **Memory (RAM)** | 16 GB recommended |

`AI-Classroom.exe` uses Microsoft Edge WebView2, which is already built into Windows 10 and 11.

---

## 🚀 Quick start

Do these steps inside the extracted `Learning-Local-AI` folder.

| Step | What to do |
|---|---|
| **1** | Double-click **`download_model.bat`**. Press **1** for an 8 GB graphics card, or **2** for 12 GB or more. It downloads the student model into the `models` folder. |
| **2** | *Only if `llama-server` is **not** on your PATH:* open **`student_settings.bat`** with Notepad and fill in the full path to `llama-server.exe`. |
| **3** | Double-click **`start_students.bat`**. Five windows open (one per student). Wait until each one says `listening on http://127.0.0.1:...`. |
| **4** | Double-click **`AI-Classroom.exe`**. |
| **5** | Click **☰** (top-left), then **📚 Lessons**. Upload a file or paste text (try the files in `sample_lessons`), click the lesson, and press **✓ Select**. |

The students read the lesson (about 15–30 seconds), then the class starts by itself. Type your answers at the bottom and press **Enter**.

📘 **Need more detail on the 5 student models?** See **[SETUP_STUDENTS.md](SETUP_STUDENTS.md)**.

When you're done, double-click **`stop_students.bat`** to free up your graphics card.

---

## 🏫 How the class works

- A new **question card** arrives every 10 seconds, and up to 9 are on screen. You have **30 seconds** for each one.
- After you answer, the right panel shows the answer, whether you were **✅ correct**, **🤏 partly right** or **❌ not quite**, and a **📖 explanation**.
- Still confused? Press **🤔 Still confused?** for an even simpler explanation (up to 2 more).
- The students only ask about **your lesson**. Questions that use things outside the lesson are thrown away.
- While you play, the students write **simple notes** about the lesson in the 📚 Lessons tab, with the **key words in bold**.

**Card types:** 🧠 Explain why · 🔀 What if… · ⚖️ Compare · ✍️ Fill the blank · 🔘 Pick one · 🕵️ Spot the mistake · ⚡ Lightning (10 s) · 🗳️ Who's right?

**Special cards and events:**

| | |
|---|---|
| ⭐ **Gold challenge** | every 10th card, harder, 60 seconds |
| 🥈 **Silver** | every 5th card, a bit harder, 45 seconds |
| 🔥 **Streak card** | can appear when you have 3 or more correct in a row, worth +3 |
| ☄️ **Meteor** | after 10 answers, a meteor can strike a waiting card |
| 🧟 **Zombie** | after 20 answers, a zombie can bite a card. Answer it correctly before it spreads! If it reaches a gold card, it becomes the 👑 **Zombie Boss** (2 parts, +5 streak) |

The class lasts **15 minutes**. At the end, you get a report card.

---

## 📁 What's in the folder

(In this GitHub repo, the scripts are in the [`AI-Classroom`](AI-Classroom) folder and the exe is on the Releases page. The zip has them all together.)

```
Learning-Local-AI/
├── AI-Classroom.exe            ← the app
├── download_model.bat          ← step 1: downloads the student model
├── student_settings.bat        ← llama-server path, memory and GPU settings
├── start_students.bat          ← starts the 5 students (5 windows)
├── start_students_hidden.bat   ← the same, but in the background (no windows)
├── check_students.bat          ← are the 5 students ready?
├── stop_students.bat           ← stops the 5 students
├── models/                     ← the model goes here
├── sample_lessons/             ← lessons to try (calculus, volcanoes, local AI...)
├── README.md                   ← this file
└── SETUP_STUDENTS.md           ← detailed student setup
```

The app creates these folders by itself, next to the exe:

| Folder / file | What's inside |
|---|---|
| `lessons/` | your lessons, the students' plans and notes |
| `sessions/` | a log of every class, plus questions you ran out of time on |
| `skills/` | the instructions the students follow (edit them with the ⚙ button) |
| `logs/` | app and student logs |
| `config.json` | settings such as class length, seconds per question and student names |

---

## ❓ Troubleshooting

| Problem | Fix |
|---|---|
| `Could not find llama-server.exe` | Set `LLAMA_SERVER` in `student_settings.bat` to the full path of `llama-server.exe`. |
| A student window closes straight away, or says `unknown model architecture` | Your llama.cpp is too old for LFM3. Download a newer build ([see SETUP_STUDENTS.md](SETUP_STUDENTS.md#1-check-your-llamacpp)). |
| `out of memory` / students crash | In `student_settings.bat`, lower `NGL` (try 22, then 18) or `CTX` (try 8000). Use the Q4_K_M model for 8 GB cards. |
| The app says the students are offline (grey icons at the bottom) | Run `check_students.bat`. Start them with `start_students.bat`, and wait until all 5 are ready. |
| Questions come very slowly | Close games and other GPU-heavy apps. The 5 students share your graphics card. |
| A picture or scanned PDF has no text | Windows OCR reads **printed** text only. For handwriting, type it into the text box instead. |
| Windows SmartScreen warns about the exe | Click **More info → Run anyway**. The app isn't signed because it's a hobby project. |

---

## 🛠️ Build from source (optional)

The source code is in the [`source`](source) folder (Python + pywebview + PyInstaller). See [`source/BUILD.md`](source/BUILD.md).

---

## 🙏 Credits

- Student model: **[LFM3-1.7B](https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF)** by Liquid AI (downloaded from Hugging Face under its own license, not included here).
- Runs on **[llama.cpp](https://github.com/ggml-org/llama.cpp)**.
- Window: **[pywebview](https://pywebview.flowrl.com/)** · PDF reading: **[pypdf](https://github.com/py-pdf/pypdf)** · Pictures: Windows' built-in OCR.
