@echo off
title Learning Local AI - stopping the 5 students
REM Stops ONLY the servers listening on ports 1001-1005. Any other llama.cpp server you run is left alone.
powershell -NoProfile -Command ^
  "1001..1005 | ForEach-Object { $c = Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue; if ($c) { Stop-Process -Id $c.OwningProcess -Force; Write-Host ('stopped student on port ' + $_) } else { Write-Host ('nothing on port ' + $_) } }"
echo.
pause
