[CmdletBinding()]
param(
    [switch]$SkipAgentTeams
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "runtime_helpers.ps1")
Initialize-Utf8Console

$projectRoot = Get-ProjectRoot
$runtimeRoot = Get-RuntimeRoot -ProjectRoot $projectRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $projectRoot ".env"
Set-Location $projectRoot

function Test-PythonEnvironmentCurrent {
    if (-not (Test-Path -LiteralPath $venvPython)) { return $false }
    $stamp = Join-Path $runtimeRoot "requirements.sha256"
    if (-not (Test-Path -LiteralPath $stamp)) { return $false }
    $expected = (Get-FileHash -Algorithm SHA256 -LiteralPath "requirements.txt").Hash.ToLowerInvariant()
    $actual = (Get-Content -LiteralPath $stamp -Raw -Encoding ASCII).Trim().ToLowerInvariant()
    if ($expected -ne $actual) { return $false }
    & $venvPython -c "import fastapi, langgraph, mcp, plotly, psycopg, sqlalchemy, uvicorn" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Get-AgentTeamsApiKey([hashtable]$Config) {
    $dedicated = Get-EnvValue -Values $Config -Name "AGENTTEAMS_LLM_API_KEY"
    if ($dedicated) { return $dedicated }
    $provider = (Get-EnvValue -Values $Config -Name "AGENTTEAMS_LLM_PROVIDER" -Default "openai-compat").ToLowerInvariant()
    $baseUrl = (Get-EnvValue -Values $Config -Name "AGENTTEAMS_OPENAI_BASE_URL" -Default "https://api.deepseek.com/v1").ToLowerInvariant()
    if ($provider -eq "qwen") { return Get-EnvValue -Values $Config -Name "DASHSCOPE_API_KEY" }
    if ($baseUrl -like "*deepseek*" -or $provider -eq "deepseek") { return Get-EnvValue -Values $Config -Name "DEEPSEEK_API_KEY" }
    if ($baseUrl -like "*siliconflow*") { return Get-EnvValue -Values $Config -Name "SILICONFLOW_API_KEY" }
    if ($baseUrl -like "*dashscope*" -or $baseUrl -like "*aliyun*") { return Get-EnvValue -Values $Config -Name "ALIYUN_API_KEY" }
    return Get-EnvValue -Values $Config -Name "OPENAI_API_KEY"
}

function Wait-AgentTeamsController([int]$TimeoutSeconds = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Get-ContainerState "agentteams-controller") -eq "running") {
            & cmd.exe /d /c "docker exec agentteams-controller agt version >nul 2>nul"
            if ($LASTEXITCODE -eq 0) { return }
        }
        Start-Sleep -Seconds 3
    }
    & docker logs --tail 100 agentteams-controller 2>&1 | Out-Host
    throw "AgentTeams Controller 未在 $TimeoutSeconds 秒内就绪。"
}

function Wait-AgentTeamsManager([int]$TimeoutSeconds = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $state = Get-ContainerState "agentteams-manager"
        if ($state -eq "running" -and (Test-TcpPort -Port 18888)) { return }
        if ($state -eq "exited") {
            & docker start agentteams-manager | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "启动 AgentTeams Manager 失败，退出码：$LASTEXITCODE"
            }
        }
        Start-Sleep -Seconds 3
    }
    & docker logs --tail 100 agentteams-manager 2>&1 | Out-Host
    throw "AgentTeams Manager 未在 $TimeoutSeconds 秒内就绪。"
}

function Install-AgentTeams([hashtable]$Config, [string]$ApiKey) {
    $installerCommit = "aa650ccacc2ba6171d1b0b5efd2a49b1472abe5d"
    $installerSha256 = "046f219873bc205d73b0a68623f55ed49afbdd09d4519b641bead58dad3ce14d"
    $installerUrl = "https://raw.githubusercontent.com/agentscope-ai/AgentTeams/$installerCommit/install/agentteams-install.ps1"
    $installerPath = Join-Path $runtimeRoot "agentteams-install.ps1"

    Write-Host "首次运行：正在下载已固定版本的官方 AgentTeams 安装器 ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $installerUrl -UseBasicParsing -OutFile $installerPath -TimeoutSec 60
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash.ToLowerInvariant()
    if ($actualHash -ne $installerSha256) {
        throw "AgentTeams 安装器哈希校验失败，已拒绝执行。"
    }

    $agentTeamsModel = Get-EnvValue -Values $Config -Name "AGENTTEAMS_DEFAULT_MODEL" -Default (
        Get-EnvValue -Values $Config -Name "DEEPSEEK_MODEL" -Default "deepseek-chat"
    )
    $adminPassword = Get-EnvValue -Values $Config -Name "AGENTTEAMS_ADMIN_PASSWORD" -Default (
        Get-EnvValue -Values $Config -Name "ADMIN_PASSWORD" -Default "admin123"
    )
    if ($adminPassword.Length -lt 8) {
        throw "AGENTTEAMS_ADMIN_PASSWORD 至少需要 8 个字符。"
    }

    $env:AGENTTEAMS_NON_INTERACTIVE = "1"
    $env:AGENTTEAMS_LLM_PROVIDER = Get-EnvValue -Values $Config -Name "AGENTTEAMS_LLM_PROVIDER" -Default "openai-compat"
    $env:AGENTTEAMS_OPENAI_BASE_URL = Get-EnvValue -Values $Config -Name "AGENTTEAMS_OPENAI_BASE_URL" -Default "https://api.deepseek.com/v1"
    $env:AGENTTEAMS_DEFAULT_MODEL = $agentTeamsModel
    $env:AGENTTEAMS_LLM_API_KEY = $ApiKey
    $embeddingModel = Get-EnvValue -Values $Config -Name "AGENTTEAMS_EMBEDDING_MODEL"
    if ($embeddingModel) {
        $env:AGENTTEAMS_EMBEDDING_MODEL = $embeddingModel
    } else {
        Remove-Item Env:AGENTTEAMS_EMBEDDING_MODEL -ErrorAction SilentlyContinue
    }
    $env:AGENTTEAMS_ADMIN_USER = Get-EnvValue -Values $Config -Name "AGENTTEAMS_ADMIN_USER" -Default "admin"
    $env:AGENTTEAMS_ADMIN_PASSWORD = $adminPassword
    $env:AGENTTEAMS_LOCAL_ONLY = "1"
    $env:AGENTTEAMS_MATRIX_E2EE = "0"
    $env:AGENTTEAMS_DOCKER_PROXY = "1"
    $env:AGENTTEAMS_MOUNT_SOCKET = "1"
    $env:AGENTTEAMS_DATA_DIR = "agentteams-sales-data"
    $env:AGENTTEAMS_WORKSPACE_DIR = Join-Path $runtimeRoot "agentteams-manager"
    $hostShareDir = Join-Path $runtimeRoot "agentteams-share"
    New-Item -ItemType Directory -Force -Path $hostShareDir | Out-Null
    $env:AGENTTEAMS_HOST_SHARE_DIR = $hostShareDir
    $env:AGENTTEAMS_DEFAULT_WORKER_RUNTIME = "qwenpaw"
    $env:AGENTTEAMS_MANAGER_RUNTIME = "openclaw"
    $env:AGENTTEAMS_WORKER_IDLE_TIMEOUT = "720"
    # 官方安装器本身固定到已审计提交；镜像再固定到本项目验证过的 digest，避免 latest 漂移。
    $registry = "higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams"
    $env:AGENTTEAMS_INSTALL_EMBEDDED_IMAGE = "$registry/agentteams-embedded@sha256:c7e467bfa5a2a733ea021c19f223180eef85e3e534873feceb8a7a132253125f"
    $env:AGENTTEAMS_INSTALL_MANAGER_IMAGE = "$registry/agentteams-manager@sha256:dd11878943e4a425ff38dcc152c9d44ea0e68d97bac89f711207134b8636c0fb"
    $env:AGENTTEAMS_INSTALL_WORKER_IMAGE = "$registry/agentteams-worker@sha256:301f9e311654eca203246fa666d63a126244ea8793f700603d2a6d37b7ffea75"
    $env:AGENTTEAMS_INSTALL_COPAW_WORKER_IMAGE = "$registry/agentteams-copaw-worker@sha256:7a6780ef76b6c7b056a2c343eeabc697f70108dae153afe8ddb76a3fad9a41b4"
    $env:AGENTTEAMS_INSTALL_QWENPAW_WORKER_IMAGE = "$registry/agentteams-qwenpaw-worker@sha256:5a8c60926009551f7ce555f657d63c8791450196a79ab41ba8bafd2e1bd51834"
    $env:AGENTTEAMS_INSTALL_HERMES_WORKER_IMAGE = "$registry/agentteams-hermes-worker@sha256:e611f38e1aa2451c97b979ae944a787f0db69c9d65c21c72a05ab33b53288e4e"

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installerPath manager -NonInteractive -EnvFile (Join-Path $runtimeRoot "agentteams-manager.env")
    if ($LASTEXITCODE -ne 0) {
        throw "AgentTeams 官方安装器执行失败，退出码：$LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".env.example") -Destination $envFile
    throw "已创建 .env。请先填写模型 API Key，再重新运行 start_all.cmd。"
}
if (-not (Test-PythonEnvironmentCurrent)) {
    Write-Host "检测到 Python 环境缺失或 requirements.txt 已更新，正在自动修复 ..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup_project.ps1") -SkipDockerBuild
}

$config = Read-DotEnv -Path $envFile
$agentTeamsEnabled = ConvertTo-Bool -Value (Get-EnvValue -Values $config -Name "AGENTTEAMS_ENABLED" -Default "true") -Default $true
if ($SkipAgentTeams) { $agentTeamsEnabled = $false }
$agentTeamsKey = ""
if ($agentTeamsEnabled) {
    $agentTeamsKey = Get-AgentTeamsApiKey -Config $config
    if ([string]::IsNullOrWhiteSpace($agentTeamsKey)) {
        throw "完整启动需要 AgentTeams 模型密钥。请填写 AGENTTEAMS_LLM_API_KEY，或填写与 AgentTeams Base URL 对应的模型密钥；若只演示 Web/MCP，请设置 AGENTTEAMS_ENABLED=false。"
    }
}

Wait-DockerEngine

Write-Host "[1/7] 启动独立 Demo PostgreSQL ..." -ForegroundColor Cyan
Invoke-DockerCompose -Arguments @("-f", "deployment/docker-compose.demo-db.yml", "up", "-d")
Wait-ContainerHealthy -Name "sales-agent-teams-demo-db" -TimeoutSeconds 90

Write-Host "[2/7] 初始化数据库与演示数据 ..." -ForegroundColor Cyan
& $venvPython -X utf8 -m scripts.ensure_postgres_database
if ($LASTEXITCODE -ne 0) { throw "Demo 数据库检查失败。" }
& $venvPython -X utf8 -c "from app.db import init_db; init_db(); print('PostgreSQL schema is ready.')"
if ($LASTEXITCODE -ne 0) { throw "Demo 数据库表初始化失败。" }

$appPort = [int](Get-EnvValue -Values $config -Name "APP_PORT" -Default "18100")
Write-Host "[3/7] 启动 Web/API ..." -ForegroundColor Cyan
if ((Test-TcpPort -Port $appPort) -and -not (
    Get-ManagedProcess -RuntimeRoot $runtimeRoot -Name "web" -ExpectedExecutable $venvPython
)) {
    throw "端口 $appPort 已被其他进程占用，无法安全启动比赛 Web。"
}
Start-ManagedProcess `
    -RuntimeRoot $runtimeRoot `
    -Name "web" `
    -FilePath $venvPython `
    -ArgumentList @("-X", "utf8", "-m", "app.main") `
    -WorkingDirectory $projectRoot | Out-Null
Wait-HttpOk -Url "http://127.0.0.1:$appPort/health" -Label "比赛 Web" -TimeoutSeconds 90

Write-Host "[4/7] 启动两个 MCP 服务 ..." -ForegroundColor Cyan
$mcpFingerprint = (& $venvPython -X utf8 scripts\runtime_fingerprint.py).Trim()
if ($LASTEXITCODE -ne 0 -or -not $mcpFingerprint) {
    throw "计算 MCP 构建指纹失败。"
}
$mcpStampPath = Join-Path $runtimeRoot "mcp-build.sha256"
$previousMcpFingerprint = if (Test-Path -LiteralPath $mcpStampPath) {
    (Get-Content -LiteralPath $mcpStampPath -Raw -Encoding ASCII).Trim()
} else {
    ""
}
& cmd.exe /d /c "docker image inspect salesagentteams-mcp-sales-agent-bridge-mcp:latest salesagentteams-mcp-sales-evaluation-insights-mcp:latest >nul 2>nul"
$mcpImagesReady = ($LASTEXITCODE -eq 0)
if (-not $mcpImagesReady -or $previousMcpFingerprint -ne $mcpFingerprint) {
    Write-Host "检测到 MCP 镜像缺失或源码已变化，正在构建 ..." -ForegroundColor Cyan
    Invoke-DockerCompose -Arguments @("-f", "deployment/docker-compose.mcp.yml", "build")
    $mcpFingerprint | Set-Content -LiteralPath $mcpStampPath -Encoding ASCII
}
Invoke-DockerCompose -Arguments @("-f", "deployment/docker-compose.mcp.yml", "up", "-d")
Wait-TcpPort -Port 18081 -Label "Sales Bridge MCP" -TimeoutSeconds 90
Wait-TcpPort -Port 18082 -Label "Evaluation Insights MCP" -TimeoutSeconds 90

if ($agentTeamsEnabled) {
    Write-Host "[5/7] 构建并托管 AgentTeams Worker 包 ..." -ForegroundColor Cyan
    & $venvPython -X utf8 agentteams\build_worker_packages.py | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Worker 包构建失败。" }
    & (Join-Path $PSScriptRoot "start_agentteams_package_server.ps1")
    Wait-TcpPort -Port 18765 -Label "Worker 包服务" -TimeoutSeconds 30

    Write-Host "[6/7] 启动 AgentTeams Controller 与 Manager ..." -ForegroundColor Cyan
    if ((Get-ContainerState "agentteams-controller") -eq "missing") {
        Install-AgentTeams -Config $config -ApiKey $agentTeamsKey
    } elseif ((Get-ContainerState "agentteams-controller") -ne "running") {
        & docker start agentteams-controller | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "启动 AgentTeams Controller 失败。" }
    }
    Wait-AgentTeamsController
    if ((Get-ContainerState "agentteams-manager") -eq "missing") {
        Wait-AgentTeamsManager
    } elseif ((Get-ContainerState "agentteams-manager") -ne "running") {
        & docker start agentteams-manager | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "启动 AgentTeams Manager 失败。" }
    }
    Wait-AgentTeamsManager

    Write-Host "[7/7] 应用六 Worker 清单并执行双层健康检查 ..." -ForegroundColor Cyan
    $agentTeamsModel = Get-EnvValue -Values $config -Name "AGENTTEAMS_DEFAULT_MODEL" -Default (
        Get-EnvValue -Values $config -Name "DEEPSEEK_MODEL" -Default "deepseek-chat"
    )
    $manifestSource = Join-Path $projectRoot "deployment\agentteams\sales-agent-teams.yaml"
    $manifestRuntime = Join-Path $runtimeRoot "sales-agent-teams.runtime.yaml"
    $manifestContent = Get-Content -LiteralPath $manifestSource -Raw -Encoding UTF8
    $manifestContent = [regex]::Replace(
        $manifestContent,
        '(?m)^(\s*model:\s*).+$',
        { param($match) $match.Groups[1].Value + $agentTeamsModel }
    )
    $manifestContent | Set-Content -LiteralPath $manifestRuntime -Encoding UTF8
    & docker cp $manifestRuntime agentteams-controller:/tmp/sales-agent-teams.yaml
    if ($LASTEXITCODE -ne 0) { throw "复制 AgentTeams 清单失败。" }
    $applySucceeded = $false
    foreach ($attempt in 1..3) {
        & cmd.exe /d /c "docker exec agentteams-controller agt apply -f /tmp/sales-agent-teams.yaml"
        if ($LASTEXITCODE -eq 0) {
            $applySucceeded = $true
            break
        }
        Write-Host "AgentTeams 清单应用暂未成功，5 秒后重试（$attempt/3）..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
    if (-not $applySucceeded) { throw "应用 AgentTeams 清单失败。" }
    & (Join-Path $PSScriptRoot "start_agentteams_workers.ps1")
} else {
    Write-Host "[5-7/7] AGENTTEAMS_ENABLED=false：跳过需要真实模型的 AgentTeams 控制面。" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "SalesAgentTeams 已完整启动。" -ForegroundColor Green
Write-Host "销售端：       http://127.0.0.1:$appPort/sales"
Write-Host "客户模拟端：   http://127.0.0.1:$appPort/customer"
Write-Host "管理员端：     http://127.0.0.1:$appPort/admin"
Write-Host "Sales MCP：    http://127.0.0.1:18081/mcp"
Write-Host "Evaluation MCP：http://127.0.0.1:18082/mcp"
if ($agentTeamsEnabled) {
    Write-Host "AgentTeams：   http://127.0.0.1:18088"
    Write-Host "Higress 控制台：http://127.0.0.1:18001"
}
Write-Host "日志目录：     $runtimeRoot"
Write-Host "关闭全部服务： .\stop_all.cmd"
