@echo off
title Learning Local AI - starting the 5 students (background)
REM Starts all 5 students in the background (no windows). Logs: logs\student1.log ... student5.log
REM Stop them with stop_students.bat
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_students_hidden.ps1"
echo.
pause
