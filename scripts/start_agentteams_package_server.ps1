$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
. (Join-Path $PSScriptRoot "runtime_helpers.ps1")

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

$runtimeRoot = Get-RuntimeRoot -ProjectRoot $projectRoot
$existingProcess = Get-ManagedProcess `
    -RuntimeRoot $runtimeRoot `
    -Name "agentteams-package-server" `
    -ExpectedExecutable $venvPython
if ($existingProcess -and (Test-TcpPort -Port $port)) {
    Write-Host "AgentTeams package server already listens on http://127.0.0.1:$port/"
    exit 0
}
if (Test-TcpPort -Port $port) {
    throw "端口 $port 已被未登记进程占用，无法安全启动 Worker 包服务。"
}

$process = Start-ManagedProcess `
    -RuntimeRoot $runtimeRoot `
    -Name "agentteams-package-server" `
    -FilePath $venvPython `
    -ArgumentList @("-m", "http.server", $port, "--bind", "0.0.0.0", "--directory", $packageRoot) `
    -WorkingDirectory $projectRoot
Wait-TcpPort -Port $port -Label "Worker 包服务" -TimeoutSeconds 15

Write-Host "AgentTeams package server started."
Write-Host "URL: http://127.0.0.1:$port/"
Write-Host "PID: $($process.Id)"
Write-Host "Packages: $packageRoot"
