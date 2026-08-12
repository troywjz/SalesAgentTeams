$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython) -or -not (Test-Path -LiteralPath ".env")) {
    & (Join-Path $PSScriptRoot "setup_demo.ps1")
}

Write-Host ""
Write-Host "SalesAgentTeams office-skills demo is starting" -ForegroundColor Green
$appPort = & $venvPython -X utf8 -c "from app.core.config import get_settings; print(get_settings().app_port)"
Write-Host "Sales:    http://127.0.0.1:$appPort/sales"
Write-Host "Customer: http://127.0.0.1:$appPort/customer"
Write-Host "Admin:    http://127.0.0.1:$appPort/admin"
Write-Host "Health:   http://127.0.0.1:$appPort/health"
Write-Host "Press Ctrl+C to stop the service."
Write-Host ""
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
& $venvPython -X utf8 -m app.main
