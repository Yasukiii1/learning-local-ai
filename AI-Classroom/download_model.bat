@echo off
setlocal
title Learning Local AI - download the student model
cd /d "%~dp0"
REM Downloads the LFM3-1.7B model (by Liquid AI, from Hugging Face) into the "models" folder.
REM All 5 students share this ONE file.

echo.
echo  Which graphics card memory (VRAM) do you have?
echo.
echo    1 = 8 GB          (Q4_K_M, about 1.0 GB download)
echo    2 = 12 GB or more (Q6_K,   about 1.4 GB download, a bit smarter)
echo.
choice /c 12 /n /m "Press 1 or 2: "
if errorlevel 2 (set "FILE=LFM3-1.7B-Q6_K.gguf") else (set "FILE=LFM3-1.7B-Q4_K_M.gguf")

if not exist "models" mkdir "models"
if exist "models\%FILE%" (
  echo.
  echo  models\%FILE% is already there. Nothing to download.
  goto done
)
for %%f in ("models\*.gguf") do (
  echo.
  echo  Note: models\%%~nxf is already in the folder. The students use the FIRST .gguf file,
  echo  so delete the one you don't want, or set MODEL in student_settings.bat.
)

echo.
echo  Downloading %FILE% ...
curl -L --fail --retry 3 -o "models\%FILE%.part" "https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF/resolve/main/%FILE%"
if errorlevel 1 (
  del "models\%FILE%.part" 2>nul
  echo.
  echo  Download failed. Check your internet, or download it yourself from
  echo  https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF  and put the file in the "models" folder.
  goto done
)
move /y "models\%FILE%.part" "models\%FILE%" >nul
echo.
echo  Done! Saved to models\%FILE%
if "%FILE%"=="LFM3-1.7B-Q6_K.gguf" echo  Tip: with 12 GB or more, open student_settings.bat and set CTX=20000.

:done
echo.
pause
