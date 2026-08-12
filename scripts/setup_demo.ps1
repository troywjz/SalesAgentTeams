$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.11 or newer is required."
        }
        & py -3 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.11 or newer is required."
        }
        & python -m venv .venv
    } else {
        throw "Python was not found. Install Python 3.11 or newer first."
    }
}

& $venvPython -m pip install --disable-pip-version-check --upgrade pip
& $venvPython -m pip install --disable-pip-version-check -r requirements.txt

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
}

& $venvPython -X utf8 -m scripts.ensure_postgres_database
& $venvPython -c "from app.db import init_db; init_db(); print('PostgreSQL schema is ready.')"
Write-Host ""
Write-Host "Demo environment is ready." -ForegroundColor Green
Write-Host "Run .\start_demo.cmd to start the project."
