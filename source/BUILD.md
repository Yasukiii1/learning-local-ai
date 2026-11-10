# 🛠️ Building AI-Classroom.exe from source

You only need this if you want to change the app. To just play, download the ready-made zip from the
[Releases page](https://github.com/Yasukiii1/learning-local-ai/releases/latest).

## What's here

| File | What it does |
|---|---|
| `app.py` | opens the window (pywebview) and connects the page to the Python code |
| `quiz.py` | the class: question cards, judging, explanations, special cards, zombies, lessons |
| `engine.py` | settings (`config.json`), the students' skill files, and the calls to the llama.cpp servers |
| `lessons.py` | the lesson library: reads PDF / Word / text / pictures and splits them into 5 parts |
| `ui/index.html` | the whole interface (one HTML file) |
| `skills_default/*.md` | the default instructions for the students (copied to `skills/` on first start) |
| `tools/ocr.ps1` | reads text from pictures and scanned PDFs with Windows' built-in OCR |

## Build

Requires Python 3.11 or newer (3.13 is what was used).

```bat
cd source
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
build.bat
```

`build.bat` creates `dist\AI-Classroom.exe`. Copy it next to the start scripts (the `AI-Classroom` folder in this repo).

## Run without building

```bat
.venv\Scripts\python app.py
```

When run like this, the app keeps its data (`config.json`, `lessons\`, `sessions\`...) next to `app.py`.
