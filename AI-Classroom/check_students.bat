@echo off
title Learning Local AI - are the students ready?
REM Shows whether each of the 5 students (ports 1001-1005) is ready.
powershell -NoProfile -Command ^
  "$n = 0; 1001..1005 | ForEach-Object { try { $ok = (Invoke-RestMethod ('http://127.0.0.1:' + $_ + '/health') -TimeoutSec 2).status -eq 'ok' } catch { $ok = $false }; if ($ok) { $n++ }; Write-Host ('student ' + ($_ - 1000) + '  port ' + $_ + '  ' + $(if ($ok) { 'ready' } else { 'NOT running / still loading' })) }; Write-Host ''; if ($n -eq 5) { Write-Host 'All 5 students are ready. Open AI-Classroom.exe.' } else { Write-Host ($n.ToString() + ' of 5 ready. Start them with start_students.bat, or wait a bit and check again.') }"
echo.
pause
