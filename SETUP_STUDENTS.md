# 🧑‍🎓 Setting up the 5 student models

The 5 students (Byte, Pixel, Mochi, Ribbit and Whiskers) are **5 copies of one small AI model**, each running in its
own `llama-server` on your computer:

| Student | Port |
|---|---|
| 🤖 Byte | `1001` |
| 🦊 Pixel | `1002` |
| 🐼 Mochi | `1003` |
| 🐸 Ribbit | `1004` |
| 🐱 Whiskers | `1005` |

`AI-Classroom.exe` talks to them on those ports. They only listen on your own computer (`127.0.0.1`), so nothing is
shared on your network.

**You need:** Windows 10/11, a graphics card with **at least 8 GB VRAM**, and llama.cpp already installed.

---

## 1. Check your llama.cpp

Open a Command Prompt and run:

```bat
llama-server --version
```

You should see something like `version: ... (build 12196, ...)`. The build number must be **12196 or higher**
(November 2026 or newer), because older builds don't know the LFM3 model.

- **`'llama-server' is not recognized`?** That's fine. You'll just type its full path in step 3.
- **Build too old, or no llama.cpp yet?** Download the newest Windows build from the
  [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) and unzip it, for example to `C:\llama.cpp`.
  - Any graphics card (NVIDIA, AMD, Intel): pick the zip that ends in **`win-vulkan-x64.zip`**.
  - NVIDIA only (often a bit faster): pick a **`win-cuda-...-x64.zip`** file. For CUDA you also need the matching
    `cudart-...zip` from the same page, unzipped into the same folder.

---

## 2. Download the model

Double-click **`download_model.bat`** and choose:

| Your graphics card | Press | Model file | Download |
|---|---|---|---|
| **8 GB** VRAM | `1` | `LFM3-1.7B-Q4_K_M.gguf` | about 1.0 GB |
| **12 GB or more** | `2` | `LFM3-1.7B-Q6_K.gguf` | about 1.4 GB, a bit smarter |

The file goes into the `models` folder. All 5 students share this **one** file, so you don't need 5 copies.

<details>
<summary>Prefer to download it yourself?</summary>

Get one of the files above from **https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF** (the *Files and versions* tab) and
put it in the `models` folder. Keep only **one** `.gguf` file in there.
</details>

---

## 3. Settings (`student_settings.bat`)

Right-click **`student_settings.bat`** → **Edit** (or open it with Notepad). These are the settings:

| Setting | What it does | 8 GB VRAM | 12 GB+ VRAM |
|---|---|---|---|
| `LLAMA_SERVER` | full path to `llama-server.exe`. **Leave empty** if `llama-server --version` worked in step 1. | your path | your path |
| `MODEL` | the model file. **Leave empty** to use the one in `models`. | empty | empty |
| `CTX` | each student's memory, in tokens | `12000` | `20000` |
| `NGL` | how many model layers go on the graphics card (`99` = all of them, fastest) | `99` | `99` |
| `THREADS` | CPU threads per student | `3` | `3` |

Example of a filled-in path:

```bat
set "LLAMA_SERVER=C:\llama.cpp\llama-server.exe"
```

Save the file when you're done.

---

## 4. Start the students

Pick **one** way:

| File | What happens |
|---|---|
| **`start_students.bat`** | Opens **5 windows**, one per student, so you can watch them work. Close a window to stop that student. |
| **`start_students_hidden.bat`** | Starts all 5 **in the background**, waits until they're ready and tells you. Logs go to the `logs` folder. |

The first start takes a little longer while Windows loads the model. A student is ready when its window shows
`listening on http://127.0.0.1:100X`.

**Check:** double-click **`check_students.bat`**. It should say `All 5 students are ready`.

Then open **`AI-Classroom.exe`**. The 5 little student icons at the bottom-left turn green when they're online.

---

## 5. Stop the students

Double-click **`stop_students.bat`**. It stops only the servers on ports 1001–1005 and leaves any other llama.cpp
servers alone. Do this when you're finished, to free up your graphics card.

---

## 🧰 Problems?

| What you see | What to do |
|---|---|
| `Could not find llama-server.exe` | Set `LLAMA_SERVER` in `student_settings.bat` (step 3). |
| `No model found in the "models" folder` | Run `download_model.bat` (step 2). |
| A student window shows `unknown model architecture 'lfm3'` and closes | Your llama.cpp is too old. Get a newer build (step 1). |
| `out of memory`, `failed to allocate`, or students crash | Lower `NGL` to `22`, then `18` (part of the model moves to the CPU: slower, but it fits). Or lower `CTX` to `8000`. Close games or other apps that use the GPU. |
| `error: unknown argument` | Your llama.cpp is too old for some options. Update it (step 1). |
| `couldn't bind to port` / `address already in use` | Something else already uses port 1001–1005. Run `stop_students.bat` first, or restart the PC. |
| Very slow answers | The 5 students share your graphics card. Close other GPU-heavy programs. With `NGL` below `99` it's slower too. |

<details>
<summary>Advanced: start one student by hand</summary>

This is exactly what `start_students.bat` runs for student 1 (port 1001). Change the port to 1002–1005 for the others:

```bat
llama-server -m models\LFM3-1.7B-Q4_K_M.gguf -c 12000 --parallel 2 -ngl 99 -fa on ^
  --cache-type-k q8_0 --cache-type-v q8_0 --threads 3 ^
  --jinja --temp 0.1 --top-k 50 --top-p 1.0 --min-p 0 --repeat-penalty 1.1 ^
  --alias student1 --port 1001
```

- `--parallel 2` gives each student 2 slots: one to talk to you, and one to plan questions in the background.
- `--temp 0.1` keeps the students careful and factual.
- `-c` is split between the 2 slots.
</details>

<details>
<summary>Advanced: different ports or student names</summary>

After the first start, `AI-Classroom.exe` creates `config.json` next to itself. In its `"students"` list, you can
change each student's `name`, `emoji`, `personality` and `port`. If you change ports, change them in the start
scripts too (they use 1001–1005).
</details>
