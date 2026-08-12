$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "runtime_helpers.ps1")
Initialize-Utf8Console

$projectRoot = Get-ProjectRoot
$runtimeRoot = Get-RuntimeRoot -ProjectRoot $projectRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
Set-Location $projectRoot

$workerNames = @(
    "agentteams-worker-sales-intent-worker",
    "agentteams-worker-sales-sop-worker",
    "agentteams-worker-sales-knowledge-worker",
    "agentteams-worker-sales-conversation-worker",
    "agentteams-worker-sales-safety-worker",
    "agentteams-worker-sales-memory-worker"
)

if (Test-DockerEngine) {
    Write-Host "正在停止六个 AgentTeams Worker ..." -ForegroundColor Cyan
    foreach ($name in $workerNames) {
        if ((Get-ContainerState $name) -eq "running") {
            & docker stop --timeout 20 $name | Out-Host
        }
    }

    foreach ($name in @("agentteams-manager", "agentteams-controller", "agentteams-docker-proxy")) {
        if ((Get-ContainerState $name) -eq "running") {
            Write-Host "正在停止 $name ..."
            & docker stop --timeout 30 $name | Out-Host
        }
    }
} else {
    Write-Host "Docker Engine 未运行；跳过容器停机。" -ForegroundColor Yellow
}

if (Test-Path -LiteralPath $venvPython) {
    Stop-ManagedProcess -RuntimeRoot $runtimeRoot -Name "agentteams-package-server" -ExpectedExecutable $venvPython
}

if (Test-DockerEngine) {
    Write-Host "正在停止两个 MCP 容器 ..." -ForegroundColor Cyan
    Invoke-DockerCompose -Arguments @("-f", "deployment/docker-compose.mcp.yml", "stop")
}

if (Test-Path -LiteralPath $venvPython) {
    Stop-ManagedProcess -RuntimeRoot $runtimeRoot -Name "web" -ExpectedExecutable $venvPython
    Stop-ProjectPythonFallback `
        -ExpectedExecutable $venvPython `
        -CommandMarkers @("-m app.main", "-m http.server 18765")
}

if (Test-DockerEngine) {
    Write-Host "正在停止独立 Demo PostgreSQL ..." -ForegroundColor Cyan
    Invoke-DockerCompose -Arguments @("-f", "deployment/docker-compose.demo-db.yml", "stop")
}

Write-Host ""
Write-Host "SalesAgentTeams 相关服务已全部关闭，数据库卷和 AgentTeams 数据卷均已保留。" -ForegroundColor Green
Write-Host "原项目 sales_agent 的容器不在本脚本管理范围内。"
