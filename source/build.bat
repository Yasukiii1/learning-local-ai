@echo off
cd /d "%~dp0"
REM Builds dist\AI-Classroom.exe (one file, no console window).
if not exist ".venv\Scripts\python.exe" (
  echo Create the virtual environment first - see BUILD.md
  pause
  exit /b 1
)
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name AI-Classroom ^
  --add-data "ui;ui" --add-data "skills_default;skills_default" --add-data "tools;tools" ^
  --hidden-import pypdf app.py
echo.
echo Done: dist\AI-Classroom.exe
pause
