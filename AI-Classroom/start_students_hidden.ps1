# Learning Local AI - start the 5 student models in the background (no windows).
# Same settings as start_students.bat (read from student_settings.bat). Logs go to logs\studentN.log.
# Stop them with stop_students.bat.
param([switch]$DryRun)

$here = $PSScriptRoot
$cfg = @{ LLAMA_SERVER = ""; MODEL = ""; CTX = "12000"; NGL = "99"; THREADS = "3" }
foreach ($line in Get-Content (Join-Path $here "student_settings.bat")) {
    if ($line -match '^\s*set\s+"?(\w+)=([^"]*)"?\s*$') { $cfg[$Matches[1].ToUpper()] = $Matches[2].Trim() }
}

$exe = $cfg.LLAMA_SERVER
if (-not $exe) { $exe = (Get-Command llama-server -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
if (-not $exe -or -not (Test-Path $exe)) {
    Write-Host "Could not find llama-server.exe. Set LLAMA_SERVER in student_settings.bat (open it with Notepad)."
    exit 1
}
$model = $cfg.MODEL
if (-not $model) { $model = (Get-ChildItem (Join-Path $here "models") -Filter *.gguf -ErrorAction SilentlyContinue | Select-Object -First 1).FullName }
if (-not $model -or -not (Test-Path $model)) {
    Write-Host "No model found in the models folder. Run download_model.bat first."
    exit 1
}
Write-Host "llama-server : $exe"
Write-Host "model        : $model"
Write-Host ("context {0}, GPU layers {1}, CPU threads {2}`n" -f $cfg.CTX, $cfg.NGL, $cfg.THREADS)

$logs = Join-Path $here "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
foreach ($i in 1..5) {
    $port = 1000 + $i
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "student $i is already running on port $port"
        continue
    }
    $argList = @(
        "-m", "`"$model`"", "-c", $cfg.CTX, "--parallel", "2", "-ngl", $cfg.NGL, "-fa", "on",
        "--cache-type-k", "q8_0", "--cache-type-v", "q8_0", "--threads", $cfg.THREADS,
        "--jinja", "--temp", "0.1", "--top-k", "50", "--top-p", "1.0", "--min-p", "0", "--repeat-penalty", "1.1",
        "--alias", "student$i", "--port", "$port"
    )
    if ($DryRun) { Write-Host "would run: `"$exe`" $($argList -join ' ')"; continue }
    Start-Process -FilePath $exe -ArgumentList $argList -WindowStyle Hidden `
        -RedirectStandardError (Join-Path $logs "student$i.log") `
        -RedirectStandardOutput (Join-Path $logs "student$i.out.log")
    Write-Host "starting student $i on port $port ..."
    Start-Sleep -Seconds 3      # a small gap so the 5 students don't all load at the same instant
}
if ($DryRun) { exit 0 }

Write-Host "`nwaiting for all 5 to be ready (this can take a minute the first time)..."
$deadline = (Get-Date).AddSeconds(180)
do {
    Start-Sleep -Seconds 2
    $ready = @(1001..1005 | Where-Object {
        try { (Invoke-RestMethod "http://127.0.0.1:$_/health" -TimeoutSec 1).status -eq "ok" } catch { $false }
    })
} until ($ready.Count -eq 5 -or (Get-Date) -gt $deadline)

foreach ($p in 1001..1005) {
    $state = if ($ready -contains $p) { "ready" } else { "NOT READY - see logs\student$($p - 1000).log" }
    Write-Host ("student {0}  port {1}  {2}" -f ($p - 1000), $p, $state)
}
if ($ready.Count -eq 5) { Write-Host "`nAll 5 students are running. Open AI-Classroom.exe." }
