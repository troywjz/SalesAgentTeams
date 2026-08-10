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
Write-Host "Sales Agent Demo is starting" -ForegroundColor Green
Write-Host "Sales UI: http://127.0.0.1:8000/sales"
Write-Host "Customer UI: http://127.0.0.1:8000/customer"
Write-Host "Admin UI: http://127.0.0.1:8000/admin"
Write-Host "Press Ctrl+C to stop the service."
Write-Host ""
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
& $venvPython -X utf8 -m app.main
