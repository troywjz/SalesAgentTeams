[CmdletBinding()]
param(
    [switch]$SkipSystemInstall,
    [switch]$SkipDockerBuild
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "runtime_helpers.ps1")
Initialize-Utf8Console

$projectRoot = Get-ProjectRoot
$runtimeRoot = Get-RuntimeRoot -ProjectRoot $projectRoot
Set-Location $projectRoot

function Install-WithWinget([string]$Id, [string]$Label) {
    if ($SkipSystemInstall) {
        throw "缺少 $Label，且已指定 -SkipSystemInstall。"
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "缺少 $Label，且系统没有 winget。请先手动安装后重新运行 setup.cmd。"
    }
    Write-Host "正在通过 winget 安装 $Label ..." -ForegroundColor Cyan
    & winget install --exact --id $Id --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "$Label 安装失败，winget 退出码：$LASTEXITCODE"
    }
}

function Resolve-PythonCommand {
    $pythonCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe")
    )
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return @{ File = "py"; Prefix = @("-3") }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return @{ File = "python"; Prefix = @() }
        }
    }
    foreach ($candidate in $pythonCandidates) {
        if (Test-Path -LiteralPath $candidate) {
            & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
            if ($LASTEXITCODE -eq 0) {
                return @{ File = $candidate; Prefix = @() }
            }
        }
    }
    return $null
}

$pythonCommand = Resolve-PythonCommand
if (-not $pythonCommand) {
    Install-WithWinget -Id "Python.Python.3.12" -Label "Python 3.12"
    $pythonCommand = Resolve-PythonCommand
    if (-not $pythonCommand) {
        throw "Python 已安装，但当前终端尚未刷新 PATH。请关闭终端后重新运行 setup.cmd。"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Install-WithWinget -Id "Docker.DockerDesktop" -Label "Docker Desktop"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerBin = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"
    $dockerExe = Join-Path $dockerBin "docker.exe"
    if (Test-Path -LiteralPath $dockerExe) {
        $env:Path = "$dockerBin;$env:Path"
    } else {
        throw "Docker Desktop 已安装，但 docker.exe 不可用。请重新登录 Windows 或重启后运行 setup.cmd。"
    }
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "正在创建 Python 虚拟环境 ..." -ForegroundColor Cyan
    & $pythonCommand.File @($pythonCommand.Prefix) -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "创建 .venv 失败。"
    }
}

Write-Host "正在安装并校验 Python 依赖 ..." -ForegroundColor Cyan
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败。" }
& $venvPython -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Python 依赖安装失败。" }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Python 依赖一致性检查失败。" }

$requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath "requirements.txt").Hash.ToLowerInvariant()
$requirementsHash | Set-Content -LiteralPath (Join-Path $runtimeRoot "requirements.sha256") -Encoding ASCII

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "已创建 .env。推荐只填写 DEEPSEEK_API_KEY；Web 与 AgentTeams 会共同复用，该文件不会提交到 Git。" -ForegroundColor Yellow
} else {
    Write-Host ".env 已存在，保持原内容不变。"
}

Write-Host "正在构建六个 AgentTeams Worker 包 ..." -ForegroundColor Cyan
& $venvPython -X utf8 agentteams\build_worker_packages.py
if ($LASTEXITCODE -ne 0) { throw "Worker 包构建失败。" }

Wait-DockerEngine
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose 插件不可用；请更新 Docker Desktop。"
}

Write-Host "正在准备 PostgreSQL 镜像 ..." -ForegroundColor Cyan
Invoke-DockerCompose -Arguments @("-f", "deployment/docker-compose.demo-db.yml", "pull")
if (-not $SkipDockerBuild) {
    Write-Host "正在构建 MCP 镜像（首次运行可能需要几分钟）..." -ForegroundColor Cyan
    Invoke-DockerCompose -Arguments @("-f", "deployment/docker-compose.mcp.yml", "build")
    $mcpFingerprint = (& $venvPython -X utf8 scripts\runtime_fingerprint.py).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $mcpFingerprint) {
        throw "计算 MCP 构建指纹失败。"
    }
    $mcpFingerprint | Set-Content -LiteralPath (Join-Path $runtimeRoot "mcp-build.sha256") -Encoding ASCII
}

Write-Host ""
Write-Host "项目依赖准备完成。" -ForegroundColor Green
Write-Host "1. 在 .env 中填写 DEEPSEEK_API_KEY；其他供应商 Key 为可选切换项。"
Write-Host "2. 运行 .\start_all.cmd 启动完整项目。"
Write-Host "3. 运行 .\stop_all.cmd 关闭本项目全部服务（保留数据）。"
