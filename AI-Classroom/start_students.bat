@echo off
setlocal EnableDelayedExpansion
title Learning Local AI - starting the 5 students
cd /d "%~dp0"
REM ==================================================================
REM  Starts the 5 "student" models on ports 1001-1005, each in its own
REM  window (you can watch them work). Settings: student_settings.bat
REM  Stop them with stop_students.bat (or close the 5 windows).
REM ==================================================================
call "%~dp0student_settings.bat"

if not defined LLAMA_SERVER for /f "delims=" %%p in ('where llama-server 2^>nul') do if not defined LLAMA_SERVER set "LLAMA_SERVER=%%p"
if not defined LLAMA_SERVER goto no_server
if not exist "%LLAMA_SERVER%" goto no_server

if not defined MODEL for %%f in ("%~dp0models\*.gguf") do if not defined MODEL set "MODEL=%%~ff"
if not defined MODEL goto no_model
if not exist "%MODEL%" goto no_model

echo llama-server : %LLAMA_SERVER%
echo model        : %MODEL%
echo context %CTX%, GPU layers %NGL%, CPU threads %THREADS%
echo.

for /L %%i in (1,1,5) do (
  echo Starting student %%i on port 100%%i ...
  if defined DRYRUN (
    echo   "%LLAMA_SERVER%" -m "%MODEL%" -c %CTX% --parallel 2 -ngl %NGL% -fa on --cache-type-k q8_0 --cache-type-v q8_0 --threads %THREADS% --jinja --temp 0.1 --top-k 50 --top-p 1.0 --min-p 0 --repeat-penalty 1.1 --alias student%%i --port 100%%i
  ) else (
    start "student %%i  (port 100%%i)" "%LLAMA_SERVER%" -m "%MODEL%" -c %CTX% --parallel 2 -ngl %NGL% -fa on ^
      --cache-type-k q8_0 --cache-type-v q8_0 --threads %THREADS% ^
      --jinja --temp 0.1 --top-k 50 --top-p 1.0 --min-p 0 --repeat-penalty 1.1 ^
      --alias student%%i --port 100%%i
    REM a small gap so the 5 students don't all load at the same instant
    timeout /t 3 /nobreak >nul
  )
)
echo.
echo All 5 students launched. Wait until each window says "listening on http://127.0.0.1:...",
echo then open AI-Classroom.exe. (check_students.bat tells you if they're ready.)
echo.
pause
exit /b 0

:no_server
echo.
echo  Could not find llama-server.exe
echo  Open student_settings.bat with Notepad and set LLAMA_SERVER to the full path, e.g.
echo    set "LLAMA_SERVER=C:\llama.cpp\build\bin\Release\llama-server.exe"
echo.
pause
exit /b 1

:no_model
echo.
echo  No model found in the "models" folder.
echo  Run download_model.bat first (or set MODEL in student_settings.bat).
echo.
pause
exit /b 1
