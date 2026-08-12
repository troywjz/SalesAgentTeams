$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Project virtual environment is missing. Run scripts\setup_demo.ps1 first."
}

Set-Location $projectRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
# Force the deterministic local model so validation cannot call a real LLM API.
$env:DEMO_MODE = "true"
$env:LLM_PROVIDER = "demo"
$env:LLM_PROVIDER_FALLBACK = ""
$env:AGENTTEAMS_ENABLED = "false"

function Invoke-Checked([string]$Label, [scriptblock]$Command) {
    Write-Host "--- $Label ---" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked "Full test suite" { & $venvPython -X utf8 -m pytest -q }
Invoke-Checked "Deterministic team smoke test" { & $venvPython -X utf8 scripts\run_demo_team.py }
Invoke-Checked "GOAI readiness check" { & $venvPython -X utf8 scripts\check_competition_readiness.py }
Invoke-Checked "Open-source audit" { & $venvPython -X utf8 scripts\check_open_source.py }
Invoke-Checked "Git whitespace check" { & git diff --check }

Write-Host "SalesAgentTeams zero-API verification passed." -ForegroundColor Green
