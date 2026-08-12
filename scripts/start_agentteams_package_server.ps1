$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packageRoot = Join-Path $projectRoot "agentteams\worker-packages"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$port = 18765

if (-not (Test-Path -LiteralPath $packageRoot)) {
    throw "Worker package directory not found: $packageRoot"
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Project virtual environment not found: $venvPython"
}

$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "AgentTeams package server already listens on http://127.0.0.1:$port/"
    exit 0
}

$logRoot = Join-Path $env:TEMP "sales-agent-teams-runtime"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$stdoutLog = Join-Path $logRoot "agentteams-package-server.out.log"
$stderrLog = Join-Path $logRoot "agentteams-package-server.err.log"

$process = Start-Process `
    -FilePath $venvPython `
    -ArgumentList @("-m", "http.server", $port, "--bind", "0.0.0.0", "--directory", $packageRoot) `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Write-Host "AgentTeams package server started."
Write-Host "URL: http://127.0.0.1:$port/"
Write-Host "PID: $($process.Id)"
Write-Host "Packages: $packageRoot"
